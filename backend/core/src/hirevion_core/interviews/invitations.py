"""Invitations and the other emails about an interview (PRD §25; SP-07a).

An invitation carries §25's eight contents: the company, the job, the duration, the window,
how to get and use the desktop app, the system requirements, the privacy and recording notice,
and support. Each email sent is an `invitations` row holding those contents, so the portal and
an audit can show exactly what the candidate was told. A candidate whose account is still
`invited` gets a fresh set-password link in every email; an active one is told to sign in.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.errors import Invalid
from hirevion_core.candidate_access.accounts import ensure_account, issue_candidate_token
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.mail.render import MailTemplate
from hirevion_core.mail.sender import queue_mail
from hirevion_core.models import Candidate, Interview, Invitation, Job, Organization

Kind = Literal["invitation", "reminder", "reschedule", "cancellation"]
_TEMPLATES: dict[Kind, MailTemplate] = {
    "invitation": "interview_invitation",
    "reminder": "interview_reminder",
    "reschedule": "interview_rescheduled",
    "cancellation": "interview_cancelled",
}
SYSTEM_REQUIREMENTS = (
    "Windows 10 (22H2) or Windows 11, 64-bit or ARM",
    "A webcam, a microphone and speakers or a headset",
    "At least 4 GB of free memory and 2 GB of free disk space",
    "An internet connection of at least 5 Mbps upload",
    "A quiet, well-lit room where you can be alone",
)
THIRD_EYE_REQUIREMENT = "A smartphone with a camera, on the same Wi-Fi, as a second camera"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _clock(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def format_moment(moment: datetime, timezone: str, locale: str) -> str:
    """`12 Oct 2026, 10:00 AM` (en-IN) or `Oct 12, 2026, 10:00 AM` (en-US), in `timezone`."""
    local = moment.astimezone(ZoneInfo(timezone))
    month = _MONTHS[local.month - 1]
    day = (
        f"{month} {local.day}, {local.year}"
        if locale == "en-US"
        else (f"{local.day} {month} {local.year}")
    )
    return f"{day}, {_clock(local)}"


def format_window(starts_at: datetime, expires_at: datetime, timezone: str, locale: str) -> str:
    """The window in the interview's time zone, named by its abbreviation (IST, PDT, ...). A
    window across a daylight-saving change names each end's own zone."""
    zone = ZoneInfo(timezone)
    start_zone = starts_at.astimezone(zone).tzname() or timezone
    end_zone = expires_at.astimezone(zone).tzname() or timezone
    start = format_moment(starts_at, timezone, locale)
    end = format_moment(expires_at, timezone, locale)
    if start_zone != end_zone:
        return f"{start} {start_zone} to {end} {end_zone}"
    return f"{start} to {end} {start_zone}"


def recorded(policy: dict[str, Any]) -> str:
    """What the interview records, in words: "your screen, camera and microphone"."""
    recording = policy.get("recording", {})
    parts = [
        label
        for key, label in (("screen", "screen"), ("camera", "camera"), ("audio", "microphone"))
        if recording.get(key, True)
    ]
    if policy.get("third_eye") in ("optional", "required"):
        parts.append("phone camera (if you pair one)")
    if not parts:
        return "the conversation's transcript"
    words = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
    return f"your {words}, and the conversation's transcript"


def requirements(policy: dict[str, Any]) -> list[str]:
    items = list(SYSTEM_REQUIREMENTS)
    if policy.get("third_eye") in ("optional", "required"):
        items.append(
            THIRD_EYE_REQUIREMENT
            + (" (required)" if policy.get("third_eye") == "required" else " (optional)")
        )
    return items


def contents(
    interview: Interview,
    organization: Organization,
    job: Job,
    settings: IdentitySettings,
) -> dict[str, Any]:
    """PRD §25's eight contents, as stored on the invitation and rendered into the email."""
    portal = settings.candidate_origin.rstrip("/")
    return {
        "company": organization.name,
        "job": job.title,
        "duration_minutes": interview.duration_minutes,
        "window": {
            "starts_at": interview.starts_at.isoformat(),
            "expires_at": interview.expires_at.isoformat(),
            "timezone": interview.timezone,
            "text": format_window(
                interview.starts_at, interview.expires_at, interview.timezone, interview.locale
            ),
        },
        "desktop_instructions": {
            "download": f"{portal}/download",
            "steps": ["download", "install for yourself (no administrator rights)", "sign in"],
        },
        "system_requirements": requirements(interview.policy),
        "privacy_notice": {"recorded": recorded(interview.policy), "notices": f"{portal}/notices"},
        "support": {
            "email": organization.support_email or settings.support_email,
            "requests": f"{portal}/requests",
        },
    }


async def send(
    session: AsyncSession,
    interview: Interview,
    kind: Kind,
    *,
    settings: IdentitySettings,
    now: datetime,
    sent_by: UUID | None = None,
    reason: str | None = None,
    reminder: Literal["opens", "closes"] = "opens",
) -> Invitation:
    """Emails the candidate about `interview` (through the outbox, so only if the transaction
    commits) and records what was sent. Creates the candidate's account on the first one."""
    candidate = await session.get_one(Candidate, interview.candidate_id)
    job = await session.get_one(Job, interview.job_id)
    organization = await session.get_one(Organization, interview.organization_id)
    if not candidate.email:
        raise Invalid("no-email", "The candidate has no email address", field="candidate")
    account = await ensure_account(session, candidate, locale=interview.locale)
    if interview.candidate_account_id != account.id:
        interview.candidate_account_id = account.id
    portal = settings.candidate_origin.rstrip("/")
    hours = settings.candidate_link_hours
    if kind == "cancellation":
        account_action, account_link = "sign_in", f"{portal}/forgot-password"
    elif account.status == "invited":
        token = await issue_candidate_token(
            session, account, "set_password", ttl=timedelta(hours=hours), now=now
        )
        account_action, account_link = "set_password", f"{portal}/invitation/{token}"
    else:
        account_action, account_link = "sign_in", f"{portal}/forgot-password"
    details = contents(interview, organization, job, settings)
    await queue_mail(
        session,
        organization_id=interview.organization_id,
        template=_TEMPLATES[kind],
        to=account.email,
        locale=interview.locale,
        context={
            "name": candidate.name,
            "email": account.email,
            "organization": details["company"],
            "job": details["job"],
            "duration": str(details["duration_minutes"]),
            "window": details["window"]["text"],
            "download_link": details["desktop_instructions"]["download"],
            "requirements": "\n".join(details["system_requirements"]),
            "recorded": details["privacy_notice"]["recorded"],
            "notices_link": details["privacy_notice"]["notices"],
            "support_email": details["support"]["email"],
            "requests_link": details["support"]["requests"],
            "account_action": account_action,
            "account_link": account_link,
            "link_hours": str(hours),
            "reminder": reminder,
            "reason": reason or "",
        },
    )
    invitation = Invitation(
        organization_id=interview.organization_id,
        interview_id=interview.id,
        kind=kind,
        sent_to=account.email,
        locale=interview.locale,
        contents={**details, **({"reminder": reminder} if kind == "reminder" else {})},
        created_by=sent_by,
    )
    session.add(invitation)
    await session.flush()
    return invitation
