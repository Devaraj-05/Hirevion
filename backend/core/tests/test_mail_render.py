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
