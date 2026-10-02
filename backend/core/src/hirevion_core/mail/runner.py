"""The background workers: the outbox relay, the mail consumer and the documents consumer.

They run inside the API process (`HV_API_RUN_WORKERS`, on by default) or alone with
`uv run hv worker`. SP-18's worker takes them over later.
"""

from __future__ import annotations

import asyncio
from functools import partial

from redis.asyncio import Redis

from hirevion_core.ai import build_ai
from hirevion_core.ai.settings import load_ai_settings
from hirevion_core.db.session import create_database
from hirevion_core.documents.consumer import DocumentConsumer
from hirevion_core.documents.pipeline import DocumentServices, give_up, handle_event
from hirevion_core.documents.scan import ClamdScanner
from hirevion_core.documents.settings import load_document_settings
from hirevion_core.mail.consumer import MailConsumer
from hirevion_core.mail.sender import SmtpSender
from hirevion_core.mail.settings import MailSettings, load_mail_settings
from hirevion_core.outbox import OutboxRelay
from hirevion_core.settings import CoreSettings
from hirevion_core.storage.service import StorageService, load_storage_settings


async def run_workers(
    core: CoreSettings, stop: asyncio.Event, mail: MailSettings | None = None
) -> None:
    """Relays the outbox, sends email and processes documents until `stop` is set."""
    relay_db = create_database(core, "relay")
    app_db = create_database(core, "app")
    redis = Redis.from_url(core.valkey_url())
    storage = StorageService(load_storage_settings())
    try:
        documents = load_document_settings()
        services = DocumentServices(
            db=app_db,
            blobs=storage,
            scanner=ClamdScanner(documents.clamav_host, documents.clamav_port),
            ai=build_ai(load_ai_settings(), app_db),
            scan=documents.documents_scan,
        )
        await asyncio.gather(
            OutboxRelay(relay_db, redis).run_forever(stop),
            MailConsumer(redis, SmtpSender(mail or load_mail_settings())).run_forever(stop),
            DocumentConsumer(
                redis, partial(handle_event, services), on_give_up=partial(give_up, services)
            ).run_forever(stop),
        )
    finally:
        await storage.aclose()
        await redis.aclose()
        await app_db.dispose()
        await relay_db.dispose()
