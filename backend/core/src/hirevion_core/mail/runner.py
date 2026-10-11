"""The background workers: the outbox relay, the mail, documents, screening, evaluation and
transcript consumers, the interview scheduler, and the media worker (recording continuity and
assembly).

The proctoring watcher and the `recording.gap` consumer (SP-14) run with them.
They run inside the API process (`HV_API_RUN_WORKERS`, on by default) or alone with
`uv run hv worker`. SP-18's worker takes them over later.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from redis.asyncio import Redis

from hirevion_core.ai import build_ai
from hirevion_core.ai.settings import load_ai_settings
from hirevion_core.db.session import create_database
from hirevion_core.documents.consumer import DocumentConsumer, StreamConsumer
from hirevion_core.documents.pipeline import DocumentServices, give_up, handle_event
from hirevion_core.documents.scan import ClamdScanner
from hirevion_core.documents.settings import load_document_settings
from hirevion_core.evaluation.runner import (
    EVALUATION_TOPIC,
    give_up_evaluation,
    handle_evaluation_event,
)
from hirevion_core.identity.settings import load_identity_settings
from hirevion_core.interview_session.transcripts import ABANDONED_TOPIC, handle_completed
from hirevion_core.interview_session.transcripts import TOPIC as COMPLETED_TOPIC
from hirevion_core.interviews.scheduler import InterviewScheduler
from hirevion_core.mail.consumer import MailConsumer
from hirevion_core.mail.sender import SmtpSender
from hirevion_core.mail.settings import MailSettings, load_mail_settings
from hirevion_core.outbox import OutboxRelay
from hirevion_core.proctoring.service import ProctorEngine
from hirevion_core.proctoring.watcher import GAP_TOPIC, ProctorWatcher, handle_gap
from hirevion_core.recordings.settings import load_recording_settings
from hirevion_core.recordings.worker import media_workers
from hirevion_core.screening.runner import SCREENING_TOPIC, handle_screening_event
from hirevion_core.settings import CoreSettings
from hirevion_core.storage.paths import BlobPath
from hirevion_core.storage.service import load_optional_storage

log = logging.getLogger(__name__)


class NoStorage:
    """Where no blob storage is configured: a file can't be read, so its document is retried
    and then marked failed; pasted descriptions need no storage."""

    async def put(self, path: BlobPath, data: bytes, content_type: str) -> None:
        raise RuntimeError("no blob storage is configured (AZURE_STORAGE_*)")

    async def get(self, path: BlobPath) -> bytes:
        raise RuntimeError("no blob storage is configured (AZURE_STORAGE_*)")

    async def delete(self, path: BlobPath) -> None:
        raise RuntimeError("no blob storage is configured (AZURE_STORAGE_*)")


async def run_workers(
    core: CoreSettings, stop: asyncio.Event, mail: MailSettings | None = None
) -> None:
    """Relays the outbox, sends email and processes documents until `stop` is set."""
    relay_db = create_database(core, "relay")
    app_db = create_database(core, "app")
    redis = Redis.from_url(core.valkey_url())
    storage = load_optional_storage()
    try:
        workers = [
            OutboxRelay(relay_db, redis).run_forever(stop),
            MailConsumer(redis, SmtpSender(mail or load_mail_settings())).run_forever(stop),
            InterviewScheduler(app_db, load_identity_settings()).run_forever(stop),
            # Server-observed proctoring state, and the recording gaps SP-12 reports (SP-14).
            ProctorWatcher(ProctorEngine(app_db, redis)).run_forever(stop),
            StreamConsumer(
                redis,
                partial(handle_gap, ProctorEngine(app_db, redis)),
                topic=GAP_TOPIC,
                group="proctoring",
            ).run_forever(stop),
            # Transcript artifacts for each completed or abandoned interview (SP-09).
            *(
                StreamConsumer(
                    redis,
                    partial(handle_completed, app_db, storage),
                    topic=topic,
                    group="transcripts",
                    # The media worker reads these streams too.
                    delete_handled=False,
                ).run_forever(stop)
                for topic in (COMPLETED_TOPIC, ABANDONED_TOPIC)
            ),
            # Recording continuity and assembly (SP-12).
            *media_workers(app_db, redis, storage, load_recording_settings(), stop),
        ]
        try:
            documents = load_document_settings()
            services = DocumentServices(
                db=app_db,
                blobs=storage or NoStorage(),
                scanner=ClamdScanner(documents.clamav_host, documents.clamav_port),
                ai=build_ai(load_ai_settings(), app_db),
                scan=documents.documents_scan,
            )
        except ValueError:
            # Missing AI keys or bad document settings stop documents only, not email.
            log.exception("Documents won't be processed: their services can't start")
        else:
            consumer = DocumentConsumer(
                redis, partial(handle_event, services), on_give_up=partial(give_up, services)
            )
            workers.append(consumer.run_forever(stop))
            screening = StreamConsumer(
                redis,
                partial(handle_screening_event, app_db, services.ai),
                topic=SCREENING_TOPIC,
            )
            workers.append(screening.run_forever(stop))
            # Evaluations of completed interviews (SP-10).
            evaluation = StreamConsumer(
                redis,
                partial(handle_evaluation_event, app_db, services.ai),
                topic=EVALUATION_TOPIC,
                on_give_up=partial(give_up_evaluation, app_db),
            )
            workers.append(evaluation.run_forever(stop))
        await asyncio.gather(*workers)
    finally:
        if storage is not None:
            await storage.aclose()
        await redis.aclose()
        await app_db.dispose()
        await relay_db.dispose()
