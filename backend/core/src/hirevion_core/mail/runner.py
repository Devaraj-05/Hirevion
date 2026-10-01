"""The background workers: the outbox relay and the mail consumer.

They run inside the API process (`HV_API_RUN_WORKERS`, on by default) or alone with
`uv run hv worker`. SP-18's worker takes them over later.
"""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from hirevion_core.db.session import create_database
from hirevion_core.mail.consumer import MailConsumer
from hirevion_core.mail.sender import SmtpSender
from hirevion_core.mail.settings import MailSettings, load_mail_settings
from hirevion_core.outbox import OutboxRelay
from hirevion_core.settings import CoreSettings


async def run_workers(
    core: CoreSettings, stop: asyncio.Event, mail: MailSettings | None = None
) -> None:
    """Relays the outbox and sends email until `stop` is set."""
    relay_db = create_database(core, "relay")
    redis = Redis.from_url(core.valkey_url())
    try:
        consumer = MailConsumer(redis, SmtpSender(mail or load_mail_settings()))
        await asyncio.gather(
            OutboxRelay(relay_db, redis).run_forever(stop), consumer.run_forever(stop)
        )
    finally:
        await redis.aclose()
        await relay_db.dispose()
