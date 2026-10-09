"""Candidate sign-in for the desktop app (PRD §8, §28; `docs/api/contracts/candidate-auth.md`;
ADR-0021).

Sign-in checks §28's six items in the contract's order: the app version, the account and
password, an assigned interview, its job, its status and its window. A new device key gets an
emailed one-time code first when the organisation asks for one. A signed-in device gets an
access token and a rotating refresh token, both bound to its key; using a spent refresh token
revokes the whole family.

Refusals are `Refusal`s carrying the contract's status and code. Some must still write before
they're raised (a failed code attempt counts, a reused refresh token revokes its family), so
those writes commit first and the refusal is raised after.
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.audit import AuditEntry, AuditService
from hirevion_core.candidate_access.accounts import AccountRow, find_accounts
from hirevion_core.candidate_access.dpop import Proof
from hirevion_core.candidate_access.tokens import (
    CandidateAuthSettings,
    TokenClaims,
    TokenSigner,
    new_otp_code,
    new_refresh_token,
    refresh_hash,
)
from hirevion_core.db.session import Database
from hirevion_core.desktop import releases
from hirevion_core.identity.lockout import Lockout
from hirevion_core.identity.passwords import verify_password_in_thread
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7
from hirevion_core.mail.sender import queue_mail
from hirevion_core.models import (
    Candidate,
    CandidateAccount,
    CandidateDevice,
    CandidateOtp,
    CandidateRefreshToken,
    Interview,
    Job,
    Organization,
    OrganizationSettings,
)

# Statuses a candidate can start or resume (PRD §28 check 5).
AVAILABLE = ("invited", "in_progress", "interrupted")
_USER_AGENT = re.compile(r"HirevionInterview/(\S+)")
_audit = AuditService()


class Refusal(Exception):
    """A refusal from the contract: its HTTP status, code, title, extra members and headers."""

    def __init__(
        self,
        http_status: int,
        code: str,
        title: str,
        *,
        headers: Mapping[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(f"{http_status} {code}")
        self.status = http_status
        self.code = code
        self.title = title
        self.headers = dict(headers or {})
        self.extra = extra


@dataclass(frozen=True, slots=True)
class AppInfo:
    version: str
    channel: str = "stable"
    os: str = ""
    arch: str = "x64"


@dataclass(frozen=True, slots=True)
class InterviewView:
    id: UUID
    job_title: str
    status: str
    starts_at: datetime
    expires_at: datetime
    duration_minutes: int
    third_eye: str
    proctoring_level: str
    coding: bool


@dataclass(frozen=True, slots=True)
class CandidateView:
    id: UUID
    name: str
    email: str
    locale: str


@dataclass(frozen=True, slots=True)
class OrganizationView:
    id: UUID
    name: str
    support_email: str


@dataclass(frozen=True, slots=True)
class SignedIn:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    candidate: CandidateView
    organization: OrganizationView
    interviews: list[InterviewView]


@dataclass(frozen=True, slots=True)
class OtpRequired:
    challenge_id: UUID
    sent_to: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class Refreshed:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int


@dataclass(frozen=True, slots=True)
class Profile:
    candidate: CandidateView
    organization: OrganizationView
    interviews: list[InterviewView]


@dataclass(frozen=True, slots=True)
class SessionToken:
    token: str
    expires_at: datetime
    interview: InterviewView


@dataclass(slots=True)
class _Evaluation:
    """An account's interviews against checks 3 to 6."""

    eligible: list[tuple[Interview, Job]] = field(default_factory=list)
    refusal: Refusal | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def masked(email: str) -> str:
    """`a***@example.test`: enough for the candidate to recognise, not enough to harvest."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def app_version_from(user_agent: str | None) -> str | None:
    match = _USER_AGENT.search(user_agent or "")
    return match.group(1) if match else None


def window_end(interview: Interview) -> datetime:
    """When the interview can no longer be taken: the window's end, plus its duration once it
    has started (so one started late in its window can finish)."""
    if interview.status in ("in_progress", "interrupted"):
        return interview.expires_at + timedelta(minutes=interview.duration_minutes)
    return interview.expires_at


def _view(interview: Interview, job: Job) -> InterviewView:
    policy = interview.policy
    return InterviewView(
        id=interview.id,
        job_title=job.title,
        status=interview.status,
        starts_at=interview.starts_at,
        expires_at=interview.expires_at,
        duration_minutes=interview.duration_minutes,
        third_eye=str(policy.get("third_eye", "optional")),
        proctoring_level=str(policy.get("proctoring_level", "standard")),
        coding=bool(policy.get("coding", {}).get("enabled")),
    )


async def evaluate(session: AsyncSession, account: CandidateAccount, now: datetime) -> _Evaluation:
    """PRD §28 checks 3 to 6 over every interview the candidate was invited to."""
    rows = [
        (row[0], row[1])
        for row in await session.execute(
            select(Interview, Job)
            .join(Job, Job.id == Interview.job_id)
            .where(
                Interview.candidate_id == account.candidate_id,
                Interview.status.not_in(("scheduled", "cancelled")),
            )
            .order_by(Interview.starts_at)
        )
    ]
    result = _Evaluation()
    if not rows:
        result.refusal = Refusal(403, "no-interview", "You have no interview to take")
        return result
    open_jobs = [(i, j) for i, j in rows if j.status == "open"]
    if not open_jobs:
        result.refusal = Refusal(403, "job-closed", "The job for your interview is closed")
        return result
    available = [(i, j) for i, j in open_jobs if i.status in AVAILABLE]
    if not available:
        latest = max(open_jobs, key=lambda pair: pair[0].updated_at)[0]
        result.refusal = Refusal(
            403,
            "interview-not-available",
            "Your interview can't be started now",
            interview_status=latest.status,
        )
        return result
    live = [(i, j) for i, j in available if window_end(i) > now]
    if not live:
        expired_at = max(window_end(i) for i, _ in available)
        result.refusal = Refusal(
            403,
            "interview-expired",
            "Your interview's window has closed",
            expired_at=expired_at.isoformat(),
        )
        return result
    result.eligible = live
    return result


class CandidateAuthService:
    def __init__(
        self,
        db: Database,
        redis: Redis,
        signer: TokenSigner,
        *,
        settings: CandidateAuthSettings,
        identity: IdentitySettings,
        lockout: Lockout | None = None,
    ) -> None:
        self._db = db
        self._signer = signer
        self._settings = settings
        self._identity = identity
        self._lockout = lockout or Lockout(redis, settings=identity)

    # Sign-in

    async def login(
        self,
        email: str,
        password: str,
        app: AppInfo,
        device_name: str,
        proof: Proof,
        *,
        ip: str | None,
        user_agent: str | None,
    ) -> SignedIn | OtpRequired:
        await self._require_current(app.version, app.channel)
        email = email.strip()
        lockout_key = f"candidate:{email}"
        locked = await self._lockout.retry_after(lockout_key)
        if locked is not None:
            raise _account_locked(locked)
        rows = await find_accounts(self._db, email)
        matches: list[AccountRow] = []
        for row in rows or [None]:  # type: ignore[list-item]
            valid, _ = await verify_password_in_thread(row.password_hash if row else None, password)
            if (
                row is not None
                and valid
                and row.status == "active"
                and row.organization_status == "active"
            ):
                matches.append(row)
        if not matches:
            wait = await self._lockout.record_failure(lockout_key)
            for row in rows:
                async with self._db.tenant(row.organization_id) as session:
                    await self._record(
                        session,
                        row.organization_id,
                        row.account_id,
                        "candidate.login.failed",
                        ip,
                        user_agent,
                    )
            if wait is not None:
                raise _account_locked(wait)
            raise Refusal(401, "invalid-credentials", "Email or password is incorrect")
        await self._lockout.reset(lockout_key)
        now = _now()
        chosen: tuple[AccountRow, _Evaluation] | None = None
        first_refusal: Refusal | None = None
        for row in matches:
            async with self._db.tenant(row.organization_id) as session:
                account = await session.get_one(CandidateAccount, row.account_id)
                evaluation = await evaluate(session, account, now)
            if evaluation.eligible:
                soonest = evaluation.eligible[0][0].starts_at
                if chosen is None or soonest < chosen[1].eligible[0][0].starts_at:
                    chosen = (row, evaluation)
            elif first_refusal is None:
                first_refusal = evaluation.refusal
        if chosen is None:
            raise first_refusal or Refusal(403, "no-interview", "You have no interview to take")
        row, evaluation = chosen
        async with self._db.tenant(row.organization_id) as session:
            account = await session.get_one(CandidateAccount, row.account_id)
            device = await self._device(session, account.id, proof.jkt)
            needs_code = await self._new_device_code_required(session)
            if needs_code and (device is None or device.verified_at is None):
                challenge = await self._send_code(
                    session, account, proof, app, device_name, now, ip, user_agent
                )
                return challenge
            device = await self._register(session, account, device, proof, app, device_name, now)
            await self._record(
                session,
                account.organization_id,
                account.id,
                "candidate.login.succeeded",
                ip,
                user_agent,
                {"device_id": str(device.id)},
            )
            return await self._sign_in(session, account, device, evaluation, now)

    async def verify_code(
        self,
        challenge_id: UUID,
        code: str,
        proof: Proof,
        *,
        ip: str | None,
        user_agent: str | None,
    ) -> SignedIn:
        found = await self._challenge(challenge_id)
        if found is None:
            raise Refusal(410, "otp-expired", "This code has expired; sign in again")
        organization_id, account_id = found
        now = _now()
        refusal: Refusal | None = None
        async with self._db.tenant(organization_id) as session:
            otp = await session.scalar(
                select(CandidateOtp).where(CandidateOtp.id == challenge_id).with_for_update()
            )
            account = await session.get_one(CandidateAccount, account_id)
            if otp is None or otp.used_at is not None or otp.expires_at <= now:
                raise Refusal(410, "otp-expired", "This code has expired; sign in again")
            if otp.attempts >= self._settings.candidate_otp_attempts:
                raise Refusal(429, "otp-attempts-exceeded", "Too many wrong codes; sign in again")
            if not hmac.compare_digest(otp.jkt, proof.jkt):
                raise Refusal(401, "dpop-invalid", "Request refused")
            if not hmac.compare_digest(otp.code_hash, self._signer.otp_hash(otp.id, code.strip())):
                otp.attempts += 1
                left = self._settings.candidate_otp_attempts - otp.attempts
                await self._record(
                    session, organization_id, account_id, "candidate.otp.failed", ip, user_agent
                )
                refusal = (
                    Refusal(400, "otp-invalid", "That code isn't right", attempts_left=left)
                    if left > 0
                    else Refusal(
                        429, "otp-attempts-exceeded", "Too many wrong codes; sign in again"
                    )
                )
            else:
                otp.used_at = now
                app = AppInfo(**otp.context.get("app", {"version": "0.0.0"}))
                evaluation = await evaluate(session, account, now)
                if not evaluation.eligible:
                    refusal = evaluation.refusal
                else:
                    device = await self._device(session, account.id, proof.jkt)
                    device = await self._register(
                        session,
                        account,
                        device,
                        proof,
                        app,
                        str(otp.context.get("device_name", "")),
                        now,
                    )
                    await self._record(
                        session,
                        organization_id,
                        account_id,
                        "candidate.otp.verified",
                        ip,
                        user_agent,
                        {"device_id": str(device.id)},
                    )
                    await self._record(
                        session,
                        organization_id,
                        account_id,
                        "candidate.login.succeeded",
                        ip,
                        user_agent,
                        {"device_id": str(device.id)},
                    )
                    return await self._sign_in(session, account, device, evaluation, now)
        raise refusal or Refusal(410, "otp-expired", "This code has expired; sign in again")

    async def resend_code(
        self, challenge_id: UUID, proof: Proof, *, ip: str | None, user_agent: str | None
    ) -> None:
        """A new code for the same challenge. Wrong attempts still count: after the last one the
        challenge is dead, and only signing in again starts another."""
        found = await self._challenge(challenge_id)
        if found is None:
            raise Refusal(410, "otp-expired", "This code has expired; sign in again")
        organization_id, account_id = found
        now = _now()
        async with self._db.tenant(organization_id) as session:
            otp = await session.scalar(
                select(CandidateOtp).where(CandidateOtp.id == challenge_id).with_for_update()
            )
            if otp is None or otp.used_at is not None or otp.expires_at <= now:
                raise Refusal(410, "otp-expired", "This code has expired; sign in again")
            if not hmac.compare_digest(otp.jkt, proof.jkt):
                raise Refusal(401, "dpop-invalid", "Request refused")
            if otp.attempts >= self._settings.candidate_otp_attempts:
                raise Refusal(429, "otp-attempts-exceeded", "Too many wrong codes; sign in again")
            wait = (
                self._settings.candidate_otp_resend_seconds
                - (now - otp.last_sent_at).total_seconds()
            )
            if wait > 0 or otp.sends >= self._settings.candidate_otp_max_sends:
                retry = (
                    max(1, int(wait)) if wait > 0 else self._settings.candidate_otp_resend_seconds
                )
                raise Refusal(
                    429,
                    "rate-limited",
                    "Wait a moment before asking for another code",
                    headers={"Retry-After": str(retry)},
                    retry_after=retry,
                )
            account = await session.get_one(CandidateAccount, account_id)
            code = new_otp_code()
            otp.code_hash = self._signer.otp_hash(otp.id, code)
            otp.sends += 1
            otp.last_sent_at = now
            otp.expires_at = now + self._settings.otp_ttl
            await self._mail_code(session, account, code)
            await self._record(
                session, organization_id, account_id, "candidate.otp.sent", ip, user_agent
            )

    # Tokens

    async def refresh(
        self, token: str, proof: Proof, *, ip: str | None, user_agent: str | None
    ) -> Refreshed:
        version = app_version_from(user_agent)
        found = await self._refresh_row(token)
        if found is None:
            raise Refusal(401, "refresh-invalid", "Sign in again")
        now = _now()
        refusal: Refusal | None = None
        async with self._db.tenant(found.organization_id) as session:
            row = await session.scalar(
                select(CandidateRefreshToken)
                .where(CandidateRefreshToken.id == found.token_id)
                .with_for_update()
            )
            if row is None or row.revoked_at is not None or row.family_expires_at <= now:
                raise Refusal(401, "refresh-invalid", "Sign in again")
            device = await session.get_one(CandidateDevice, row.device_id)
            if not hmac.compare_digest(device.jkt, proof.jkt):
                raise Refusal(401, "dpop-invalid", "Request refused")
            if row.used_at is not None:
                await self._revoke_family(session, row.family_id, now)
                await self._record(
                    session,
                    row.organization_id,
                    row.account_id,
                    "candidate.token.reused",
                    ip,
                    user_agent,
                    {"family_id": str(row.family_id)},
                )
                refusal = Refusal(401, "refresh-reused", "Sign in again")
            elif device.revoked_at is not None:
                raise Refusal(401, "refresh-invalid", "Sign in again")
            else:
                # The app's own version (User-Agent), else what the device last reported.
                running = version or str(device.app.get("version", "0.0.0"))
                channel = str(device.app.get("channel", "stable"))
                outdated = await releases.is_outdated(session, running, channel)
                if outdated is not None:
                    raise _update_required(outdated)
                if version is not None and version != device.app.get("version"):
                    device.app = {**device.app, "version": version}
                row.used_at = now
                device.last_seen_at = now
                refresh, digest = new_refresh_token()
                session.add(
                    CandidateRefreshToken(
                        organization_id=row.organization_id,
                        account_id=row.account_id,
                        device_id=row.device_id,
                        family_id=row.family_id,
                        token_hash=digest,
                        family_expires_at=row.family_expires_at,
                    )
                )
                access = self._signer.issue(
                    account_id=row.account_id,
                    organization_id=row.organization_id,
                    jkt=device.jkt,
                    family_id=row.family_id,
                    scope="candidate",
                    expires_at=now + self._settings.access_ttl,
                    now=now,
                )
                await self._record(
                    session,
                    row.organization_id,
                    row.account_id,
                    "candidate.token.refreshed",
                    ip,
                    user_agent,
                )
                return Refreshed(
                    access_token=access,
                    expires_in=int(self._settings.access_ttl.total_seconds()),
                    refresh_token=refresh,
                    refresh_expires_in=int((row.family_expires_at - now).total_seconds()),
                )
        raise refusal or Refusal(401, "refresh-invalid", "Sign in again")

    async def family_active(self, claims: TokenClaims, now: datetime | None = None) -> bool:
        """Whether the token's sign-in is still live: not signed out of, not revoked for reuse,
        its device not revoked and its account still active."""
        moment = now or _now()
        async with self._db.tenant(claims.organization_id) as session:
            live = await session.scalar(
                select(CandidateRefreshToken.id)
                .join(CandidateDevice, CandidateDevice.id == CandidateRefreshToken.device_id)
                .where(
                    CandidateRefreshToken.family_id == claims.family_id,
                    CandidateRefreshToken.revoked_at.is_(None),
                    CandidateRefreshToken.family_expires_at > moment,
                    CandidateDevice.revoked_at.is_(None),
                )
                .limit(1)
            )
            account = await session.get(CandidateAccount, claims.account_id)
        return live is not None and account is not None and account.status == "active"

    async def logout(self, claims: TokenClaims, *, ip: str | None, user_agent: str | None) -> None:
        now = _now()
        async with self._db.tenant(claims.organization_id) as session:
            await self._revoke_family(session, claims.family_id, now)
            await self._record(
                session,
                claims.organization_id,
                claims.account_id,
                "candidate.logout",
                ip,
                user_agent,
            )

    async def profile(self, claims: TokenClaims) -> Profile:
        now = _now()
        async with self._db.tenant(claims.organization_id) as session:
            account = await session.get_one(CandidateAccount, claims.account_id)
            evaluation = await evaluate(session, account, now)
            candidate, organization = await self._views(session, account)
        return Profile(candidate, organization, [_view(i, j) for i, j in evaluation.eligible])

    async def session_token(
        self,
        claims: TokenClaims,
        interview_id: UUID,
        *,
        ip: str | None,
        user_agent: str | None,
    ) -> SessionToken:
        now = _now()
        async with self._db.tenant(claims.organization_id) as session:
            account = await session.get_one(CandidateAccount, claims.account_id)
            found = (
                await session.execute(
                    select(Interview, Job)
                    .join(Job, Job.id == Interview.job_id)
                    .where(
                        Interview.id == interview_id,
                        Interview.candidate_id == account.candidate_id,
                        Interview.status.not_in(("scheduled",)),
                    )
                )
            ).first()
            if found is None:
                raise Refusal(404, "interview-not-found", "No such interview")
            interview, job = found[0], found[1]
            if interview.status not in AVAILABLE or job.status != "open":
                raise Refusal(
                    403,
                    "interview-not-available",
                    "This interview can't be started now",
                    interview_status=interview.status,
                )
            if now < interview.starts_at:
                raise Refusal(
                    409,
                    "interview-not-open",
                    "The interview's window hasn't opened yet",
                    starts_at=interview.starts_at.isoformat(),
                )
            end = window_end(interview)
            if end <= now:
                raise Refusal(
                    410,
                    "interview-expired",
                    "The interview's window has closed",
                    expired_at=end.isoformat(),
                )
            family_end = await session.scalar(
                select(CandidateRefreshToken.family_expires_at)
                .where(CandidateRefreshToken.family_id == claims.family_id)
                .limit(1)
            )
            ends = [
                interview.expires_at + timedelta(minutes=interview.duration_minutes),
                now + self._settings.session_ttl,
            ]
            if family_end is not None:
                ends.append(family_end)
            expires_at = min(ends)
            token = self._signer.issue(
                account_id=account.id,
                organization_id=account.organization_id,
                jkt=claims.jkt,
                family_id=claims.family_id,
                scope="interview",
                expires_at=expires_at,
                now=now,
                interview_id=interview.id,
            )
            await self._record(
                session,
                account.organization_id,
                account.id,
                "candidate.session_token.issued",
                ip,
                user_agent,
                {"interview_id": str(interview.id)},
            )
            return SessionToken(token, expires_at, _view(interview, job))

    # Helpers

    async def _require_current(self, version: str, channel: str) -> None:
        async with self._db.unscoped() as session:
            outdated = await releases.is_outdated(session, version, channel)
        if outdated is not None:
            raise _update_required(outdated)

    async def _new_device_code_required(self, session: AsyncSession) -> bool:
        row = await session.scalar(select(OrganizationSettings))
        settings = row.candidate_access if row else {}
        return bool(settings.get("new_device_otp", True))

    async def _device(
        self, session: AsyncSession, account_id: UUID, jkt: str
    ) -> CandidateDevice | None:
        return await session.scalar(
            select(CandidateDevice).where(
                CandidateDevice.account_id == account_id, CandidateDevice.jkt == jkt
            )
        )

    async def _register(
        self,
        session: AsyncSession,
        account: CandidateAccount,
        device: CandidateDevice | None,
        proof: Proof,
        app: AppInfo,
        name: str,
        now: datetime,
    ) -> CandidateDevice:
        details = {"version": app.version, "channel": app.channel, "os": app.os, "arch": app.arch}
        if device is None:
            device = CandidateDevice(
                organization_id=account.organization_id,
                account_id=account.id,
                jkt=proof.jkt,
                public_jwk=dict(proof.jwk),
                name=name.strip()[:100],
                app=details,
                verified_at=now,
                first_seen_at=now,
                last_seen_at=now,
            )
            try:
                async with session.begin_nested():
                    session.add(device)
                    await session.flush()
            except IntegrityError:
                # Another sign-in from the same new key registered it a moment ago.
                existing = await self._device(session, account.id, proof.jkt)
                if existing is None:
                    raise
                return await self._register(session, account, existing, proof, app, name, now)
            await self._record(
                session,
                account.organization_id,
                account.id,
                "candidate.device.registered",
                None,
                None,
                {"device_id": str(device.id), "name": device.name},
            )
        else:
            if device.revoked_at is not None:
                raise Refusal(401, "invalid-credentials", "Email or password is incorrect")
            device.verified_at = device.verified_at or now
            device.last_seen_at = now
            device.app = details
            if name.strip():
                device.name = name.strip()[:100]
        return device

    async def _sign_in(
        self,
        session: AsyncSession,
        account: CandidateAccount,
        device: CandidateDevice,
        evaluation: _Evaluation,
        now: datetime,
    ) -> SignedIn:
        family_id = uuid7()
        family_expires_at = now + self._settings.refresh_ttl
        refresh, digest = new_refresh_token()
        session.add(
            CandidateRefreshToken(
                organization_id=account.organization_id,
                account_id=account.id,
                device_id=device.id,
                family_id=family_id,
                token_hash=digest,
                family_expires_at=family_expires_at,
            )
        )
        await session.flush()
        access = self._signer.issue(
            account_id=account.id,
            organization_id=account.organization_id,
            jkt=device.jkt,
            family_id=family_id,
            scope="candidate",
            expires_at=now + self._settings.access_ttl,
            now=now,
        )
        candidate, organization = await self._views(session, account)
        return SignedIn(
            access_token=access,
            expires_in=int(self._settings.access_ttl.total_seconds()),
            refresh_token=refresh,
            refresh_expires_in=int(self._settings.refresh_ttl.total_seconds()),
            candidate=candidate,
            organization=organization,
            interviews=[_view(i, j) for i, j in evaluation.eligible],
        )

    async def _views(
        self, session: AsyncSession, account: CandidateAccount
    ) -> tuple[CandidateView, OrganizationView]:
        candidate = await session.get_one(Candidate, account.candidate_id)
        organization = await session.get_one(Organization, account.organization_id)
        return (
            CandidateView(account.id, candidate.name, account.email, account.locale),
            OrganizationView(
                organization.id,
                organization.name,
                organization.support_email or self._identity.support_email,
            ),
        )

    async def _send_code(
        self,
        session: AsyncSession,
        account: CandidateAccount,
        proof: Proof,
        app: AppInfo,
        device_name: str,
        now: datetime,
        ip: str | None,
        user_agent: str | None,
    ) -> OtpRequired:
        challenge_id = uuid7()
        code = new_otp_code()
        session.add(
            CandidateOtp(
                id=challenge_id,
                organization_id=account.organization_id,
                account_id=account.id,
                jkt=proof.jkt,
                code_hash=self._signer.otp_hash(challenge_id, code),
                last_sent_at=now,
                expires_at=now + self._settings.otp_ttl,
                context={
                    "app": {
                        "version": app.version,
                        "channel": app.channel,
                        "os": app.os,
                        "arch": app.arch,
                    },
                    "device_name": device_name.strip()[:100],
                },
            )
        )
        await session.flush()
        await self._mail_code(session, account, code)
        await self._record(
            session, account.organization_id, account.id, "candidate.otp.sent", ip, user_agent
        )
        return OtpRequired(
            challenge_id=challenge_id,
            sent_to=masked(account.email),
            expires_in=int(self._settings.otp_ttl.total_seconds()),
        )

    async def _mail_code(self, session: AsyncSession, account: CandidateAccount, code: str) -> None:
        candidate = await session.get_one(Candidate, account.candidate_id)
        await queue_mail(
            session,
            organization_id=account.organization_id,
            template="candidate_code",
            to=account.email,
            locale=account.locale,
            context={
                "name": candidate.name,
                "code": code,
                "minutes": str(self._settings.candidate_otp_minutes),
            },
        )

    async def _challenge(self, challenge_id: UUID) -> tuple[UUID, UUID] | None:
        async with self._db.unscoped() as session:
            row = (
                await session.execute(
                    text("SELECT * FROM auth_candidate_otp(:id)"), {"id": challenge_id}
                )
            ).first()
        return (row.organization_id, row.account_id) if row else None

    async def _refresh_row(self, token: str) -> Any:
        async with self._db.unscoped() as session:
            return (
                await session.execute(
                    text("SELECT * FROM auth_candidate_refresh(:hash)"),
                    {"hash": refresh_hash(token)},
                )
            ).first()

    async def _revoke_family(self, session: AsyncSession, family_id: UUID, now: datetime) -> None:
        await session.execute(
            update(CandidateRefreshToken)
            .where(
                CandidateRefreshToken.family_id == family_id,
                CandidateRefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def _record(
        self,
        session: AsyncSession,
        organization_id: UUID,
        account_id: UUID,
        action: str,
        ip: str | None,
        user_agent: str | None,
        details: dict[str, object] | None = None,
    ) -> None:
        await _audit.append(
            session,
            organization_id,
            AuditEntry(
                action=action,
                resource_type="candidate_account",
                resource_id=str(account_id),
                actor_type="candidate",
                actor_id=str(account_id),
                ip=ip,
                user_agent=user_agent,
                details=details or {},
            ),
        )


def _account_locked(retry_after: int) -> Refusal:
    return Refusal(
        423,
        "account-locked",
        "Too many attempts; try again later",
        headers={"Retry-After": str(retry_after)},
        retry_after=retry_after,
    )


def _update_required(channel: Any) -> Refusal:
    return Refusal(
        426,
        "app-update-required",
        "Update the app to continue",
        minimum_version=channel.minimum_version,
        download_url=channel.download_url,
    )


__all__ = [
    "AppInfo",
    "CandidateAuthService",
    "OtpRequired",
    "Profile",
    "Refreshed",
    "Refusal",
    "SessionToken",
    "SignedIn",
]
