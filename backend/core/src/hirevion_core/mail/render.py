"""Rendering an email: a subject, a plain-text part and an HTML part, per language."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

MailTemplate = Literal[
    "reset_password",
    "password_changed",
    "verify_email",
    "email_change_requested",
    "invitation",
    "interview_invitation",
    "interview_reminder",
    "interview_rescheduled",
    "interview_cancelled",
    "candidate_code",
]
MAIL_TEMPLATES: tuple[MailTemplate, ...] = (
    "reset_password",
    "password_changed",
    "verify_email",
    "email_change_requested",
    "invitation",
    "interview_invitation",
    "interview_reminder",
    "interview_rescheduled",
    "interview_cancelled",
    "candidate_code",
)

LOCALES = ("en-IN", "en-US")
DEFAULT_LOCALE = "en-IN"


@dataclass(frozen=True, slots=True)
class RenderedMail:
    subject: str
    text: str
    html: str


_environment = Environment(
    loader=PackageLoader("hirevion_core.mail", "templates"),
    # Only the HTML part is escaped; the text part shows what the user typed as it is.
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False),
    # A missing value is an error, never a silently blank link.
    undefined=StrictUndefined,
)


def render(template: MailTemplate, locale: str, context: Mapping[str, str]) -> RenderedMail:
    language = locale if locale in LOCALES else DEFAULT_LOCALE
    subject = _environment.get_template(f"{language}/{template}.subject.txt.j2").render(context)
    subject = " ".join(subject.split())
    text = _environment.get_template(f"{language}/{template}.txt.j2").render(context)
    html = _environment.get_template(f"{language}/{template}.html.j2").render(
        {**context, "lang": language, "title": subject}
    )
    return RenderedMail(subject=subject, text=text, html=html)
