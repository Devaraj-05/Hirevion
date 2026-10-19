"""Screening (PRD §15 to §18, §90): the configuration, screening a job's candidates, the ranked and
explained results, recruiter actions and export. Every job route goes through the reader's
resource scope first (ADR-0014)."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from io import BytesIO, StringIO
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends, Query, Request
from fastapi.responses import Response
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.access.deps import own_tenant
from hirevion_api.authz import Principal, requires
from hirevion_api.jobs.routes import reference
from hirevion_api.pagination import Page, PageParams, page_params, paginate
from hirevion_api.problems import ProblemError
from hirevion_api.routing import api_router
from hirevion_api.screening.schemas import (
    ActionRequest,
    ActionResult,
    ApplicationScreening,
    ApplicationState,
    CandidateBrief,
    DecisionRequest,
    HistoryEntry,
    RankedApplication,
    ScreenAccepted,
    ScreeningConfigResponse,
    ScreeningConfigUpdate,
    ScreeningResultResponse,
    ScreeningSummary,
    ScreenRequest,
)
from hirevion_core.access import UNSET
from hirevion_core.access.audit import record
from hirevion_core.access.errors import NotFound
from hirevion_core.access.scope import resource_scope
from hirevion_core.jobs import jobs
from hirevion_core.models import (
    Application,
    ApplicationHistory,
    Candidate,
    Job,
    ScreeningResult,
)
from hirevion_core.screening import config, runner, workflow
from hirevion_core.screening.config import Config

router = api_router(tags=["screening"])

ViewsCandidates = Annotated[Principal, requires("candidates.view")]
ManagesCandidates = Annotated[Principal, requires("candidates.manage")]
ViewsJobs = Annotated[Principal, requires("jobs.view")]
ManagesJobs = Annotated[Principal, requires("jobs.create")]
ManagesOrganization = Annotated[Principal, requires("admin.organization.manage")]
# PRD §90-adjacent exports carry personal data out of the system: a recent password first.
Exports = Annotated[Principal, requires("candidates.view", step_up=True)]
Pages = Annotated[PageParams, Depends(page_params)]
EXPORT_COLUMNS = (
    "Rank",
    "Candidate",
    "Match score",
    "Stage",
    "Required skills",
    "Preferred skills",
    "Experience",
    "Missing requirements",
    "Strengths",
    "Concerns",
    "Knock-outs",
)
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def _config(settings: Config) -> ScreeningConfigResponse:
    return ScreeningConfigResponse(
        weights=settings.weights,
        knockouts=settings.knockouts,
        blind=settings.blind,
        version=settings.version,
        inherited=settings.inherited,
        source=settings.source,  # type: ignore[arg-type]
    )


def _changes(body: ScreeningConfigUpdate) -> dict[str, Any]:
    sent = body.model_fields_set
    return {
        "weights": body.weights if "weights" in sent and body.weights is not None else UNSET,
        "knockouts": (
            body.knockouts if "knockouts" in sent and body.knockouts is not None else UNSET
        ),
        "blind": body.blind if "blind" in sent and body.blind is not None else UNSET,
    }


async def _job_in_scope(session: AsyncSession, principal: Principal, job_id: UUID) -> Job:
    return await jobs.require_in_scope(
        session, job_id, await resource_scope(session, principal.user_id)
    )


def _brief(candidate: Candidate) -> CandidateBrief:
    return CandidateBrief(
        id=candidate.id,
        name=candidate.name,
        headline=candidate.headline,
        location=candidate.location,
        flags=candidate.flags,
    )


def _ranked(
    application: Application, result: ScreeningResult | None, candidate: Candidate
) -> RankedApplication:
    return RankedApplication(
        application_id=application.id,
        rank=application.rank,
        stage=application.stage,  # type: ignore[arg-type]
        score=result.score if result else None,
        candidate=_brief(candidate),
        skill_match=result.skill_match if result else {},
        experience=result.experience if result else {},
        knockouts=result.knockouts if result else [],
        semantic_similarity=result.semantic_similarity if result else None,
        recruiter_id=application.recruiter_id,
        hiring_manager_id=application.hiring_manager_id,
        screened_at=result.created_at if result else None,
    )


def _states(applications: Sequence[Application]) -> ActionResult:
    return ActionResult(applications=[ApplicationState.model_validate(app) for app in applications])


# Configuration


@router.get("/jobs/{job_id}/screening-config")
async def get_job_screening_config(
    job_id: UUID, request: Request, principal: ViewsJobs
) -> ScreeningConfigResponse:
    """The weights, knock-outs and blind mode the job's screening uses."""
    async with own_tenant(request, principal) as session:
        await _job_in_scope(session, principal, job_id)
        return _config(await config.effective(session, job_id))


@router.put("/jobs/{job_id}/screening-config")
async def update_job_screening_config(
    job_id: UUID, body: ScreeningConfigUpdate, request: Request, principal: ManagesJobs
) -> ScreeningConfigResponse:
    """Gives the job its own configuration (starting from what it inherited). Turning blind
    screening off is the organisation's decision: it needs `admin.organization.manage`."""
    if body.blind is False and "admin.organization.manage" not in principal.permissions:
        raise ProblemError(
            403,
            "blind-screening-locked",
            "Only an organisation administrator can turn blind screening off",
        )
    async with own_tenant(request, principal) as session:
        await _job_in_scope(session, principal, job_id)
        saved = await config.save(session, principal.actor(request), job_id, **_changes(body))
        return _config(saved)


@router.delete("/jobs/{job_id}/screening-config")
async def reset_job_screening_config(
    job_id: UUID, request: Request, principal: ManagesJobs
) -> ScreeningConfigResponse:
    """Drops the job's own configuration: it uses the organisation's default again."""
    async with own_tenant(request, principal) as session:
        await _job_in_scope(session, principal, job_id)
        return _config(await config.reset(session, principal.actor(request), job_id))


@router.get("/screening-config")
async def get_screening_defaults(
    request: Request, principal: ManagesOrganization
) -> ScreeningConfigResponse:
    """The organisation's default screening configuration."""
    async with own_tenant(request, principal) as session:
        return _config(await config.effective(session, None))


@router.put("/screening-config")
async def update_screening_defaults(
    body: ScreeningConfigUpdate, request: Request, principal: ManagesOrganization
) -> ScreeningConfigResponse:
    async with own_tenant(request, principal) as session:
        saved = await config.save(session, principal.actor(request), None, **_changes(body))
        return _config(saved)


# Screening and results


@router.post("/jobs/{job_id}/screen", status_code=202)
async def screen_job(
    job_id: UUID, body: ScreenRequest, request: Request, principal: ManagesCandidates
) -> ScreenAccepted:
    """Screens the job's candidates in the background (PRD §90). Results that are still current
    are reused, so screening again costs nothing for unchanged candidates."""
    async with own_tenant(request, principal) as session:
        await _job_in_scope(session, principal, job_id)
        queued = await runner.request_screening(
            session, principal.actor(request), job_id, body.application_ids
        )
        return ScreenAccepted(queued=queued)


@router.get("/jobs/{job_id}/screening-summary")
async def screening_summary(
    job_id: UUID, request: Request, principal: ViewsCandidates
) -> ScreeningSummary:
    """How far screening has got: for progress while it runs."""
    async with own_tenant(request, principal) as session:
        await _job_in_scope(session, principal, job_id)
        stages = {
            row[0]: row[1]
            for row in await session.execute(
                select(Application.stage, func.count())
                .where(Application.job_id == job_id)
                .group_by(Application.stage)
            )
        }
        screened = await session.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.job_id == job_id, Application.screening_result_id.is_not(None))
        )
        return ScreeningSummary(
            applications=sum(stages.values()),
            screened=int(screened or 0),
            waiting=stages.get("parsed", 0) + stages.get("uploaded", 0),
            stages=stages,
        )


@router.get("/jobs/{job_id}/screening-results")
async def screening_results(
    job_id: UUID,
    request: Request,
    principal: ViewsCandidates,
    page: Pages,
    stage: Annotated[str | None, Query(max_length=20)] = None,
) -> Page[RankedApplication]:
    """The job's screened candidates, best first (PRD §16)."""
    async with own_tenant(request, principal) as session:
        await _job_in_scope(session, principal, job_id)
        statement = select(Application).where(
            Application.job_id == job_id, Application.rank.is_not(None)
        )
        if stage:
            statement = statement.where(Application.stage == stage)
        rows, next_cursor = await paginate(
            session, statement, [Application.rank, Application.id], page
        )
        results = {
            result.id: result
            for result in (
                await session.scalars(
                    select(ScreeningResult).where(
                        ScreeningResult.id.in_(
                            [row.screening_result_id for row in rows if row.screening_result_id]
                        )
                    )
                )
            ).all()
        }
        people = {
            person.id: person
            for person in (
                await session.scalars(
                    select(Candidate).where(Candidate.id.in_({row.candidate_id for row in rows}))
                )
            ).all()
        }
        return Page(
            items=[
                _ranked(
                    row,
                    results.get(row.screening_result_id) if row.screening_result_id else None,
                    people[row.candidate_id],
                )
                for row in rows
            ],
            next_cursor=next_cursor,
        )


@router.get("/applications/{application_id}/screening")
async def application_screening(
    application_id: UUID, request: Request, principal: ViewsCandidates
) -> ApplicationScreening:
    """One application's screening in full: every factor with its evidence, and its history."""
    async with own_tenant(request, principal) as session:
        application = await session.get(Application, application_id)
        if application is None:
            raise NotFound("application-not-found", "No such application")
        try:
            await _job_in_scope(session, principal, application.job_id)
        except NotFound:  # out of reach looks the same as missing
            raise NotFound("application-not-found", "No such application") from None
        candidate = await session.get_one(Candidate, application.candidate_id)
        result = (
            await session.get(ScreeningResult, application.screening_result_id)
            if application.screening_result_id
            else None
        )
        history = await session.scalars(
            select(ApplicationHistory)
            .where(ApplicationHistory.application_id == application.id)
            .order_by(ApplicationHistory.created_at, ApplicationHistory.id)
        )
        return ApplicationScreening(
            application_id=application.id,
            job_id=application.job_id,
            stage=application.stage,  # type: ignore[arg-type]
            rank=application.rank,
            candidate=_brief(candidate),
            result=ScreeningResultResponse.model_validate(result) if result else None,
            history=[HistoryEntry.model_validate(entry) for entry in history],
        )


# Actions


@router.post("/jobs/{job_id}/applications/actions")
async def act_on_applications(
    job_id: UUID, body: ActionRequest, request: Request, principal: ManagesCandidates
) -> ActionResult:
    """Shortlist, reject, hold, review or assign, for one candidate or many (PRD §18)."""
    async with own_tenant(request, principal) as session:
        await _job_in_scope(session, principal, job_id)
        applications = await workflow.act(
            session,
            principal.actor(request),
            job_id,
            body.application_ids,
            body.action,
            reason=body.reason,
            user_id=body.user_id,
        )
        return _states(applications)


async def _decide(
    request: Request,
    principal: Principal,
    candidate_id: UUID,
    body: DecisionRequest,
    action: Literal["shortlist", "reject"],
) -> ApplicationState:
    async with own_tenant(request, principal) as session:
        await _job_in_scope(session, principal, body.job_id)
        application = await session.scalar(
            select(Application).where(
                Application.candidate_id == candidate_id, Application.job_id == body.job_id
            )
        )
        if application is None:
            raise NotFound("application-not-found", "This candidate hasn't applied to that job")
        [changed] = await workflow.act(
            session,
            principal.actor(request),
            body.job_id,
            [application.id],
            action,
            reason=body.reason,
        )
        return ApplicationState.model_validate(changed)


@router.post("/candidates/{candidate_id}/shortlist")
async def shortlist_candidate(
    candidate_id: UUID, body: DecisionRequest, request: Request, principal: ManagesCandidates
) -> ApplicationState:
    """Shortlists the candidate for `job_id` (PRD §90)."""
    return await _decide(request, principal, candidate_id, body, "shortlist")


@router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: UUID, body: DecisionRequest, request: Request, principal: ManagesCandidates
) -> ApplicationState:
    """Rejects the candidate for `job_id`, with a reason (PRD §90)."""
    return await _decide(request, principal, candidate_id, body, "reject")


# Export


def _cell(value: Any) -> Any:
    """A number stays a number (it sorts and filters as one); text a spreadsheet would run as
    a formula (CSV/formula injection) is prefixed so it can't."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_STARTS) else text


def _rows(
    ranked: Sequence[tuple[Application, ScreeningResult | None, Candidate]],
) -> list[list[Any]]:
    rows = []
    for application, result, candidate in ranked:
        skills = result.skill_match if result else {}
        rows.append(
            [
                _cell(application.rank),
                _cell(candidate.name),
                _cell(result.score if result else ""),
                _cell(application.stage),
                _cell(skills.get("required_score", "")),
                _cell(skills.get("preferred_score", "")),
                _cell(result.experience.get("score", "") if result else ""),
                _cell("; ".join(result.missing) if result else ""),
                _cell("; ".join(result.strengths) if result else ""),
                _cell("; ".join(result.concerns) if result else ""),
                _cell("; ".join(result.knockouts) if result else ""),
            ]
        )
    return rows


def _plain(value: Any) -> Any:
    """The cell as a spreadsheet cell: text needs no guard there (it is typed as text)."""
    if isinstance(value, str) and value.startswith("'") and value[1:].startswith(_FORMULA_STARTS):
        return value[1:]
    return value


@router.get("/jobs/{job_id}/screening-results/export")
async def export_screening_results(
    job_id: UUID,
    request: Request,
    principal: Exports,
    format: Literal["csv", "xlsx"] = "csv",
) -> Response:
    """The ranking as CSV or XLSX (PRD §18 "Export"); needs a recent password, and is audited."""
    async with own_tenant(request, principal) as session:
        job = await _job_in_scope(session, principal, job_id)
        rows = _rows(await runner.ranking(session, job_id))
        await record(
            session,
            principal.actor(request),
            "screening.exported",
            "job",
            job_id,
            details={"format": format, "rows": len(rows)},
        )
    name = f"{reference(job.number)}-ranking.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    if format == "csv":
        out = StringIO()
        writer = csv.writer(out)
        writer.writerow(EXPORT_COLUMNS)
        writer.writerows(rows)
        # A byte-order mark, so Excel reads names with accents as UTF-8.
        return Response(
            "\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers
        )
    workbook = Workbook()
    sheet = workbook.active
    if sheet is None:  # a new workbook always has its first sheet
        raise RuntimeError("openpyxl made a workbook without a sheet")
    sheet.title = "Ranking"
    sheet.append(list(EXPORT_COLUMNS))
    for row in rows:
        sheet.append([_plain(value) for value in row])
    for cells in sheet.iter_rows(min_row=2):
        for cell in cells:
            if isinstance(cell.value, str):
                cell.data_type = "s"  # text, even if it starts with "=": never a formula
    data = BytesIO()
    workbook.save(data)
    return Response(
        data.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
