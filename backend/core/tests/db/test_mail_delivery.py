"""Email through the outbox: committed changes send mail, rolled-back ones don't, failures retry.

Needs Mailpit (SMTP 1025, API 8025) from `uv run hv up`, or CI's service container. Each test
uses its own recipient and searches for it, so a developer's own Mailpit messages stay put.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import aiohttp
import pytest
from redis.asyncio import Redis

from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.mail.consumer import DEAD_LETTER_STREAM, MAIL_STREAM, MailConsumer
from hirevion_core.mail.render import RenderedMail, render
from hirevion_core.mail.sender import SmtpSender, queue_mail
from hirevion_core.mail.settings import MailSettings
from hirevion_core.outbox import OutboxRelay

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
MAILPIT_API = "http://127.0.0.1:8025/api/v1"
SETTINGS = MailSettings(smtp_host="127.0.0.1", smtp_port=1025)
CONTEXT = {
    "name": "Ravi",
    "link": "https://app.hirevion.localhost/reset-password/x",
    "minutes": "30",
}


class RecordingSender:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.attempts = 0
        self.sent: list[tuple[str, RenderedMail]] = []

    async def send(self, to: str, mail: RenderedMail) -> None:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise ConnectionError("SMTP is down")
        self.sent.append((to, mail))


def recipient() -> str:
    return f"mail-{uuid7().hex[-12:]}@example.test"


async def mailpit_messages(to: str) -> list[dict[str, Any]]:
    async with (
        aiohttp.ClientSession() as session,
        session.get(f"{MAILPIT_API}/search", params={"query": f'to:"{to}"'}) as response,
    ):
        response.raise_for_status()
        body = await response.json()
    return list(body["messages"])


async def wait_for_mail(to: str) -> list[dict[str, Any]]:
    for _ in range(50):
        messages = await mailpit_messages(to)
        if messages:
            return messages
        await asyncio.sleep(0.1)
    return []


async def queue(db: Database, organization_id: UUID, to: str) -> None:
    async with db.tenant(organization_id) as session:
        await queue_mail(
            session,
            organization_id=organization_id,
            template="reset_password",
            to=to,
            locale="en-IN",
            context=CONTEXT,
        )


@pytest.mark.usefixtures("empty_outbox")
async def test_a_committed_email_reaches_the_inbox(
    app_db: Database, relay_db: Database, valkey: Redis, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    to = recipient()
    await queue(app_db, acme, to)

    assert await OutboxRelay(relay_db, valkey).run_once() == 1
    assert await MailConsumer(valkey, SmtpSender(SETTINGS)).run_once() == 1

    messages = await wait_for_mail(to)
    assert [m["Subject"] for m in messages] == [render("reset_password", "en-IN", CONTEXT).subject]
    # The link expires, but it shouldn't wait in Valkey either: sent entries are deleted.
    assert await valkey.xlen(MAIL_STREAM) == 0


@pytest.mark.usefixtures("empty_outbox")
async def test_a_rolled_back_email_is_never_sent(
    app_db: Database, relay_db: Database, valkey: Redis, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    with pytest.raises(RuntimeError):
        async with app_db.tenant(acme) as session:
            await queue_mail(
                session,
                organization_id=acme,
                template="reset_password",
                to=recipient(),
                locale="en-IN",
                context=CONTEXT,
            )
            raise RuntimeError("the change failed")
    assert await OutboxRelay(relay_db, valkey).run_once() == 0


@pytest.mark.usefixtures("empty_outbox")
async def test_a_failed_send_is_retried(
    app_db: Database, relay_db: Database, valkey: Redis, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    to = recipient()
    await queue(app_db, acme, to)
    await OutboxRelay(relay_db, valkey).run_once()

    sender = RecordingSender(failures=1)
    consumer = MailConsumer(valkey, sender, retry_idle_ms=0)
    assert await consumer.run_once() == 0
    assert await consumer.run_once() == 1
    assert [address for address, _ in sender.sent] == [to]


@pytest.mark.usefixtures("empty_outbox")
async def test_an_email_that_keeps_failing_goes_to_the_dead_letter_stream(
    app_db: Database, relay_db: Database, valkey: Redis, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    await queue(app_db, acme, recipient())
    await OutboxRelay(relay_db, valkey).run_once()

    sender = RecordingSender(failures=100)
    consumer = MailConsumer(valkey, sender, retry_idle_ms=0, max_deliveries=5)
    for _ in range(8):
        await consumer.run_once()
    assert sender.attempts == 5
    assert await valkey.xlen(DEAD_LETTER_STREAM) == 1
    pending = await valkey.xpending(MAIL_STREAM, "mail")
    assert pending["pending"] == 0


@pytest.mark.usefixtures("empty_outbox")
async def test_a_republished_event_is_sent_once(
    app_db: Database, relay_db: Database, valkey: Redis, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    await queue(app_db, acme, recipient())
    await OutboxRelay(relay_db, valkey).run_once()
    # The relay publishes at least once: a crash before its commit repeats the event.
    [(_, fields)] = await valkey.xrange(MAIL_STREAM)
    await valkey.xadd(MAIL_STREAM, fields)

    sender = RecordingSender()
    consumer = MailConsumer(valkey, sender)
    await consumer.run_once()
    await consumer.run_once()
    assert len(sender.sent) == 1
