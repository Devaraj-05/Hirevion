"""Email templates (SP-02 spec, "Email")."""

import pytest
from jinja2 import UndefinedError

from hirevion_core.mail.render import MAIL_TEMPLATES, render

LINK = "https://app.hirevion.localhost/reset-password/abc123"
FORGOT = "https://app.hirevion.localhost/forgot-password"
CONTEXTS: dict[str, dict[str, str]] = {
    "reset_password": {"name": "Ravi", "link": LINK, "minutes": "30"},
    "password_changed": {"name": "Ravi", "forgot_link": FORGOT},
    "verify_email": {
        "name": "Ravi",
        "link": "https://app.hirevion.localhost/verify-email/abc",
        "hours": "24",
    },
    "email_change_requested": {"name": "Ravi", "new_email": "new@x.test", "forgot_link": FORGOT},
    "invitation": {
        "name": "Ravi",
        "inviter": "Olivia Admin",
        "organization": "Acme Talent",
        "link": "https://app.hirevion.localhost/set-password/abc",
        "hours": "72",
    },
}
INTERVIEW = {
    "name": "Asha",
    "email": "asha@example.test",
    "organization": "Acme Talent",
    "job": "Backend Engineer",
    "duration": "45",
    "window": "12 Oct 2026, 10:00 AM to 13 Oct 2026, 11:59 PM IST",
    "download_link": "https://candidate.hirevion.localhost/download",
    "requirements": "Windows 10 22H2 or Windows 11\nA webcam and a microphone",
    "recorded": "your screen, camera and microphone",
    "notices_link": "https://candidate.hirevion.localhost/notices",
    "support_email": "help@acme.example.test",
    "requests_link": "https://candidate.hirevion.localhost/requests",
    "account_action": "set_password",
    "account_link": "https://candidate.hirevion.localhost/invitation/abc",
    "link_hours": "168",
    "reminder": "opens",
    "reason": "",
}
CONTEXTS.update(
    {
        "interview_invitation": {**INTERVIEW, "link": INTERVIEW["account_link"]},
        "interview_reminder": {**INTERVIEW, "link": INTERVIEW["account_link"]},
        "interview_rescheduled": {**INTERVIEW, "link": INTERVIEW["account_link"]},
        "interview_cancelled": {**INTERVIEW, "forgot_link": INTERVIEW["support_email"]},
        "candidate_code": {"name": "Asha", "code": "042137", "minutes": "10", "link": "042137"},
    }
)


@pytest.mark.parametrize("locale", ["en-IN", "en-US"])
@pytest.mark.parametrize("template", MAIL_TEMPLATES)
def test_every_template_renders_in_both_languages(template: str, locale: str) -> None:
    context = CONTEXTS[template]
    mail = render(template, locale, context)  # type: ignore[arg-type]
    assert mail.subject and "\n" not in mail.subject
    link = context.get("link", context.get("forgot_link"))
    assert link in mail.text and link in mail.html
    assert context["name"] in mail.text


def test_the_html_part_escapes_what_users_typed() -> None:
    context = {**CONTEXTS["reset_password"], "name": "<script>alert(1)</script>"}
    mail = render("reset_password", "en-IN", context)
    assert "<script>" not in mail.html and "&lt;script&gt;" in mail.html
    assert "<script>alert(1)</script>" in mail.text


def test_a_missing_value_is_an_error_not_a_blank() -> None:
    with pytest.raises(UndefinedError):
        render("reset_password", "en-IN", {"name": "Ravi"})


def test_an_unknown_language_falls_back_to_en_in() -> None:
    context = CONTEXTS["reset_password"]
    assert render("reset_password", "fr-FR", context) == render("reset_password", "en-IN", context)


def test_the_expiry_is_stated() -> None:
    assert "30 minutes" in render("reset_password", "en-US", CONTEXTS["reset_password"]).text


@pytest.mark.parametrize("locale", ["en-IN", "en-US"])
def test_an_invitation_says_who_invited_them_and_where(locale: str) -> None:
    mail = render("invitation", locale, CONTEXTS["invitation"])
    assert "Acme Talent" in mail.subject
    for part in (mail.text, mail.html):
        assert "Olivia Admin" in part and "Acme Talent" in part and "72 hours" in part


@pytest.mark.parametrize("locale", ["en-IN", "en-US"])
def test_an_interview_invitation_holds_all_eight_contents(locale: str) -> None:
    """PRD §25: company, job, duration, window, desktop instructions, system requirements, the
    privacy and recording notice, and support."""
    mail = render("interview_invitation", locale, INTERVIEW)
    for part in (mail.text, mail.html):
        assert "Acme Talent" in part
        assert "Backend Engineer" in part
        assert "45 minutes" in part
        assert "13 Oct 2026" in part
        assert "candidate.hirevion.localhost/download" in part
        assert "A webcam and a microphone" in part
        assert "your screen, camera and microphone" in part
        assert "candidate.hirevion.localhost/notices" in part
        assert "help@acme.example.test" in part
        assert "candidate.hirevion.localhost/invitation/abc" in part


def test_an_active_account_is_told_to_sign_in_rather_than_set_a_password() -> None:
    context = {**INTERVIEW, "account_action": "sign_in"}
    text = render("interview_invitation", "en-IN", context).text
    assert "Set your password" not in text and "already set" in text


def test_the_reminder_says_whether_the_window_opens_or_closes() -> None:
    assert "opens soon" in render("interview_reminder", "en-US", INTERVIEW).subject
    closes = {**INTERVIEW, "reminder": "closes"}
    assert "closes soon" in render("interview_reminder", "en-US", closes).subject


def test_a_window_across_a_clock_change_names_both_zones() -> None:
    from datetime import UTC, datetime

    from hirevion_core.interviews.invitations import format_window

    text = format_window(
        datetime(2026, 10, 30, 17, 0, tzinfo=UTC),
        datetime(2026, 11, 6, 7, 59, tzinfo=UTC),
        "America/Los_Angeles",
        "en-US",
    )
    assert text == "Oct 30, 2026, 10:00 AM PDT to Nov 5, 2026, 11:59 PM PST"
    india = format_window(
        datetime(2026, 10, 12, 4, 30, tzinfo=UTC),
        datetime(2026, 10, 13, 18, 29, tzinfo=UTC),
        "Asia/Kolkata",
        "en-IN",
    )
    assert india == "12 Oct 2026, 10:00 AM to 13 Oct 2026, 11:59 PM IST"
