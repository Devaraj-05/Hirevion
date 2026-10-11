"""The recruiter's side of proctoring (SP-14; PRD §65, §66, §90): the report's data, the live
dashboard's snapshot, the evidence, reviewing events, and a hidden subscribe-only token to watch.

Every route needs `reports.proctoring.view` and reaches only interviews in the user's resource
scope. Looking at proctoring data is itself audited (`proctoring.viewed`, `.live_viewed`,
`.evidence_viewed`, `.observed`); a page that reloads often is recorded once every five minutes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.access.deps import own_tenant
from hirevion_api.authz import Principal, requires
from hirevion_api.deps import get_redis
from hirevion_api.interview_session.routes import media
from hirevion_api.pagination import PageParams, page_params, paginate
from hirevion_api.problems import ProblemError
from hirevion_api.proctoring.schemas import (
    Counts,
    EvidenceItem,
    EvidenceList,
    LiveSnapshot,
    ObserveResponse,
    ProctorEventItem,
    ProctoringReport,
    ProctoringStatus,
    ReviewBody,
    ReviewInfo,
    ReviewStatus,
    SessionSummary,
    Severity,
)
from hirevion_api.routing import api_router
from hirevion_core.access import audit
from hirevion_core.access.scope import resource_scope
from hirevion_core.interviews import assignment
from hirevion_core.models import (
    Interview,
    ProctorEvent,
    ProctorEventReview,
    ProctorEvidence,
    ProctorSession,
)
from hirevion_core.proctoring import live
from hirevion_core.proctoring.review import publish_review, review_event
from hirevion_core.proctoring.store import ENDED, event_json, status_json
from hirevion_core.storage.paths import BlobPath

log = logging.getLogger(__name__)
router = api_router(tags=["proctoring"])

Views = Annotated[Principal, requires("reports.proctoring.view")]
Reviews = Annotated[Principal, requires("interviews.manage")]
AUDIT_QUIET = 300
OBSERVER_TTL = timedelta(hours=2)
DOWNLOAD_PREFIX = "interviews/"


def _reviewer_only(principal: Principal) -> UUID | None:
    return None if "candidates.view" in principal.permissions else principal.user_id


def _needs(principal: Principal, *permissions: str) -> None:
    if not all(p in principal.permissions for p in permissions):
        raise ProblemError(403, "forbidden", "You don't have permission to do this")


async def _interview(session: AsyncSession, principal: Principal, interview_id: UUID) -> Interview:
    scope = await resource_scope(session, principal.user_id)
    return await assignment.get_interview(
        session, interview_id, scope, reviewer_only=_reviewer_only(principal)
    )


async def _record(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    action: str,
    interview_id: UUID,
    *,
    quiet: bool = True,
    **details: object,
) -> None:
    """Audits a look at proctoring data; with `quiet`, once per five minutes per user and
    interview, so a page that reloads doesn't flood the log."""
    if quiet:
        key = f"hv:pc:audit:{action}:{principal.user_id}:{interview_id}"
        if not await get_redis(request).set(key, "1", nx=True, ex=AUDIT_QUIET):
            return
    await audit.record(
        session,
        principal.actor(request),
        action,
        "interview",
        interview_id,
        details=details,
    )


def _item(
    row: ProctorEvent, evidence: int = 0, review: ProctorEventReview | None = None
) -> ProctorEventItem:
    body = event_json(row)
    body.update(id=row.id, evidence_count=evidence)
    if review is not None:
        body["review"] = ReviewInfo(
            outcome=review.outcome,  # type: ignore[arg-type]
            reason=review.reason,
            reviewer_id=review.reviewer_id,
            reviewed_at=review.created_at,
        )
    return ProctorEventItem.model_validate(body)


async def _reviews(
    session: AsyncSession, ids: list[UUID]
) -> tuple[dict[UUID, ProctorEventReview], dict[UUID, int]]:
    latest: dict[UUID, ProctorEventReview] = {}
    if ids:
        for review in await session.scalars(
            select(ProctorEventReview)
            .where(ProctorEventReview.proctor_event_id.in_(ids))
            .order_by(ProctorEventReview.created_at)
        ):
            latest[review.proctor_event_id] = review
    evidence: dict[UUID, int] = {}
    if ids:
        rows = await session.execute(
            select(ProctorEvidence.proctor_event_id, func.count())
            .where(ProctorEvidence.proctor_event_id.in_(ids))
            .group_by(ProctorEvidence.proctor_event_id)
        )
        evidence = {event_id: number for event_id, number in rows if event_id is not None}
    return latest, evidence


@router.get("/proctoring/{interview_id}")
async def get_proctoring_report(
    interview_id: UUID,
    request: Request,
    principal: Views,
    params: Annotated[PageParams, Depends(page_params)],
    severity: Annotated[Severity | None, Query(description="Only this severity.")] = None,
    review_status: Annotated[ReviewStatus | None, Query(description="Only this review.")] = None,
) -> ProctoringReport:
    """Every proctoring event of the interview in order, dismissed ones included and marked,
    with the session's summary and the counts PRD §68's report is built from."""
    async with own_tenant(request, principal) as session:
        interview = await _interview(session, principal, interview_id)
        proctor = await session.scalar(
            select(ProctorSession).where(ProctorSession.interview_id == interview.id)
        )
        statement = select(ProctorEvent).where(ProctorEvent.interview_id == interview.id)
        if severity is not None:
            statement = statement.where(ProctorEvent.severity == severity)
        if review_status is not None:
            statement = statement.where(ProctorEvent.review_status == review_status)
        rows, next_cursor = await paginate(
            session, statement, [ProctorEvent.started_at, ProctorEvent.id], params
        )
        reviews, evidence = await _reviews(session, [row.id for row in rows])
        counts = await live.counts(session, interview.id)
        await _record(request, session, principal, "proctoring.viewed", interview.id)
    summary = None
    if proctor is not None:
        summary = SessionSummary(
            id=proctor.id,
            status=proctor.status,  # type: ignore[arg-type]
            level=proctor.level,
            policy_version=proctor.policy_version,
            opened_at=proctor.opened_at,
            closed_at=proctor.closed_at,
            acked_through=proctor.acked_through,
            heartbeats=proctor.heartbeats,
            last_heartbeat_at=proctor.last_heartbeat_at,
            checks=list(proctor.policy.get("checks", [])),
            accommodations=list(proctor.policy.get("accommodations", [])),
            app_version=proctor.app_version,
        )
    return ProctoringReport(
        interview_id=interview_id,
        session=summary,
        status=ProctoringStatus.model_validate(status_json(proctor, interview.status))
        if proctor is not None
        else None,
        counts=Counts.model_validate(counts),
        events=[_item(row, evidence.get(row.id, 0), reviews.get(row.id)) for row in rows],
        next_cursor=next_cursor,
    )


@router.get("/proctoring/{interview_id}/live")
async def get_proctoring_live(
    interview_id: UUID, request: Request, principal: Views
) -> LiveSnapshot:
    """The live dashboard's starting point: devices, connection health, the AI's state, the
    transcript's tail, recent events and the stream position to follow from. Opening it is
    audited."""
    _needs(principal, "interviews.view")
    async with own_tenant(request, principal) as session:
        interview = await _interview(session, principal, interview_id)
        body = await live.snapshot(session, get_redis(request), interview)
        ids = [UUID(event["id"]) for event in body["events"]]
        reviews, evidence = await _reviews(session, ids)
        await _record(
            request,
            session,
            principal,
            "proctoring.live_viewed",
            interview.id,
            status=interview.status,
        )
    events = [
        {
            **event,
            "evidence_count": evidence.get(UUID(event["id"]), 0),
            "review": _review_body(reviews.get(UUID(event["id"]))),
        }
        for event in body["events"]
    ]
    return LiveSnapshot.model_validate({**body, "events": events})


def _review_body(review: ProctorEventReview | None) -> dict[str, object] | None:
    if review is None:
        return None
    return {
        "outcome": review.outcome,
        "reason": review.reason,
        "reviewer_id": review.reviewer_id,
        "reviewed_at": review.created_at,
    }


@router.get("/proctoring/{interview_id}/evidence")
async def list_proctoring_evidence(
    interview_id: UUID,
    request: Request,
    principal: Views,
    event_id: Annotated[UUID | None, Query(description="Only this event's evidence.")] = None,
) -> EvidenceList:
    """The interview's evidence (PRD §67) with five-minute download links for stored snapshots;
    segments and transcript or process references carry their window or details. Viewing is
    audited."""
    async with own_tenant(request, principal) as session:
        interview = await _interview(session, principal, interview_id)
        statement = (
            select(ProctorEvidence)
            .where(ProctorEvidence.interview_id == interview.id)
            .order_by(ProctorEvidence.created_at, ProctorEvidence.id)
        )
        if event_id is not None:
            statement = statement.where(ProctorEvidence.proctor_event_id == event_id)
        rows = (await session.scalars(statement)).all()
        await _record(
            request,
            session,
            principal,
            "proctoring.evidence_viewed",
            interview.id,
            quiet=False,
            event_id=str(event_id) if event_id else None,
            items=len(rows),
        )
    sign = getattr(getattr(request.app.state, "storage", None), "download_url", None)
    items = []
    for row in rows:
        url = None
        if row.blob_path and sign is not None and row.proctor_event_id is not None:
            key = row.blob_path.removeprefix(f"{row.organization_id}/")
            url = sign(row.organization_id, BlobPath(row.organization_id, key))
        items.append(
            EvidenceItem(
                id=row.id,
                event_id=row.proctor_event_id,
                kind=row.kind,
                origin=row.origin,  # type: ignore[arg-type]
                url=url,
                content_type=row.content_type,
                bytes=row.bytes,
                sha256=row.sha256,
                window_start=row.window_start,
                window_end=row.window_end,
                ref=row.ref,
                created_at=row.created_at,
            )
        )
    return EvidenceList(items=items)


@router.post("/proctoring/{interview_id}/events/{event_id}/review")
async def review_proctor_event(
    interview_id: UUID, event_id: UUID, body: ReviewBody, request: Request, principal: Reviews
) -> ProctorEventItem:
    """Confirms an event, or marks it a false positive or not relevant, with the reason. The
    event stays in the report; the decision is audited and shown to everyone watching."""
    _needs(principal, "reports.proctoring.view")
    async with own_tenant(request, principal) as session:
        interview = await _interview(session, principal, interview_id)
        done = await review_event(
            session, principal.actor(request), interview.id, event_id, body.outcome, body.reason
        )
        evidence = await session.scalar(
            select(func.count())
            .select_from(ProctorEvidence)
            .where(ProctorEvidence.proctor_event_id == done.event.id)
        )
    try:
        await publish_review(get_redis(request), interview_id, done)
    except Exception:
        # The review is saved; whoever is watching catches up from the report.
        log.exception("Couldn't publish the review of proctor event %s", event_id)
    return _item(done.event, evidence or 0, done.review)


@router.post("/proctoring/{interview_id}/observe")
async def observe_interview(
    interview_id: UUID, request: Request, principal: Views
) -> ObserveResponse:
    """A hidden, subscribe-only LiveKit token for the interview's room: nobody in it sees the
    recruiter, and the token can't publish. Asking for one is audited."""
    _needs(principal, "interviews.view")
    control = media(request)
    if control is None:
        raise ProblemError(503, "media-unavailable", "The interview service isn't available")
    async with own_tenant(request, principal) as session:
        interview = await _interview(session, principal, interview_id)
        if interview.status in ENDED or interview.status not in ("in_progress", "interrupted"):
            raise ProblemError(409, "interview-not-live", "The interview isn't running")
        await _record(request, session, principal, "proctoring.observed", interview.id, quiet=False)
        name = f"observer-{principal.user_id}"
    expires = datetime.now(UTC) + OBSERVER_TTL
    token = control.observer_token(interview_id, principal.user_id, name, expires)
    return ObserveResponse(
        livekit_url=token.url,
        room=token.room,
        identity=token.identity,
        token=token.token,
        expires_at=token.expires_at,
    )
