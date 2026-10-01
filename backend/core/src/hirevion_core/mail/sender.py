"""Queueing an email in the outbox, and sending one over SMTP."""

from __future__ import annotations

from collections.abc import Mapping
from email.message import EmailMessage
from typing import Protocol
from uuid import UUID

import aiosmtplib
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.mail.render import MailTemplate, RenderedMail
from hirevion_core.mail.settings import MailSettings
from hirevion_core.outbox import publish_event

MAIL_TOPIC = "mail"


class MailSender(Protocol):
    async def send(self, to: str, mail: RenderedMail) -> None: ...


async def queue_mail(
    session: AsyncSession,
    *,
    organization_id: UUID,
    template: MailTemplate,
    to: str,
    locale: str,
    context: Mapping[str, str],
) -> UUID:
    """Writes the email to the outbox in the caller's transaction: it goes out only if that
    commits. The payload may hold a single-use link; the consumer deletes it once sent."""
    return await publish_event(
        session,
        organization_id,
        MAIL_TOPIC,
        {"template": template, "to": to, "locale": locale, "context": dict(context)},
    )


class SmtpSender:
    def __init__(self, settings: MailSettings) -> None:
        self._settings = settings

    async def send(self, to: str, mail: RenderedMail) -> None:
        message = EmailMessage()
        message["From"] = self._settings.mail_from
        message["To"] = to
        message["Subject"] = mail.subject
        message.set_content(mail.text)
        message.add_alternative(mail.html, subtype="html")
        password = self._settings.smtp_password.get_secret_value()
        await aiosmtplib.send(
            message,
            hostname=self._settings.smtp_host,
            port=self._settings.smtp_port,
            username=self._settings.smtp_username or None,
            password=password or None,
            start_tls=self._settings.smtp_starttls,
            timeout=10,
        )
