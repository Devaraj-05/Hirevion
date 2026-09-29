"""Every AI call is recorded (PRD §79) and metered, and budgets stop runaway spend."""

from collections.abc import AsyncIterator, Awaitable, Callable
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.ai import AiServices, build_ai
from hirevion_core.ai.mock import MOCK_PRICES
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import AiBudgetExceeded, AiContext, AiUnavailable
from hirevion_core.db.session import Database
from hirevion_core.models import AiInvocation

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


class Summary(BaseModel):
    headline: str
    score: int


class Rollback(Exception):
    pass


@pytest.fixture
def ai(app_db: Database) -> AiServices:
    return build_ai(AiSettings(profile="mock"), app_db, prices=MOCK_PRICES)


def context(org: UUID, purpose: str = "screening.rank") -> AiContext:
    return AiContext(
        org,
        purpose,
        prompt_version="screening-v3",
        rubric_version="rubric-v2",
        evaluation_version="eval-v1",
        input_refs={"resume_sha256": "ab" * 32},
    )


async def invocations(admin_engine: AsyncEngine, org: UUID) -> list[dict[str, object]]:
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT * FROM ai_invocations WHERE organization_id = :org ORDER BY occurred_at"),
            {"org": org},
        )
        return [dict(row._mapping) for row in rows]


async def meters(admin_engine: AsyncEngine, org: UUID) -> dict[str, Decimal]:
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT meter, sum(quantity) FROM usage_events "
                "WHERE organization_id = :org GROUP BY meter"
            ),
            {"org": org},
        )
        return {meter: total for meter, total in rows}


async def test_an_llm_call_is_recorded_with_its_governance_fields(
    ai: AiServices, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("AiRecord")
    messages = [{"role": "user", "content": "Summarise the candidate."}]
    result = await ai.llm.complete(context(org), messages, Summary)
    assert isinstance(result.value, Summary)

    [row] = await invocations(admin_engine, org)
    assert row["service"] == "llm"
    assert row["purpose"] == "screening.rank"
    assert row["provider"] == "mock"
    assert row["model"] == result.model
    assert row["model_version"] == result.model
    assert (row["prompt_version"], row["rubric_version"], row["evaluation_version"]) == (
        "screening-v3",
        "rubric-v2",
        "eval-v1",
    )
    assert row["input_refs"] == {"resume_sha256": "ab" * 32}
    assert row["output"] == result.value.model_dump(mode="json")
    assert row["input_tokens"] == result.input_tokens > 0
    assert row["output_tokens"] == result.output_tokens > 0
    assert row["latency_ms"] >= 0
    assert row["status"] == "ok"
    assert row["cost_usd"] > 0

    used = await meters(admin_engine, org)
    assert used["ai.llm.input_tokens"] == result.input_tokens
    assert used["ai.llm.output_tokens"] == result.output_tokens
    assert used["ai.cost.usd"] == row["cost_usd"]


async def test_every_service_records_its_own_usage(
    ai: AiServices, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("AiServices")
    ctx = context(org, "pipeline.check")
    embedded = await ai.embeddings.embed(ctx, ["one", "two"])
    heard = await ai.stt.transcribe(ctx, b"\x00" * 64_000, "audio/wav")
    spoken = await ai.tts.synthesize(ctx, "Welcome to your interview.")
    seen = await ai.vision.analyze(ctx, b"png", "image/png", "Describe the desk.", Summary)
    page = await ai.ocr.read_page(ctx, b"png", "image/png")

    rows = {row["service"]: row for row in await invocations(admin_engine, org)}
    assert set(rows) == {"embedding", "stt", "tts", "vision", "ocr"}
    assert rows["embedding"]["output"] == {"dimensions": 1536, "count": 2}
    assert len(embedded.vectors) == 2
    assert rows["stt"]["audio_seconds"] == Decimal(str(heard.duration_seconds))
    assert rows["stt"]["output"] == {"text": heard.text}
    assert rows["tts"]["characters"] == spoken.characters == len("Welcome to your interview.")
    assert rows["tts"]["output"] == {"characters": spoken.characters}
    assert rows["vision"]["output"] == seen.value.model_dump(mode="json")
    assert rows["ocr"]["output"] == {"text": page.text, "confidence": page.confidence}

    used = await meters(admin_engine, org)
    assert {"ai.embedding.input_tokens", "ai.stt.seconds", "ai.tts.characters"} <= set(used)
    assert used["ai.stt.seconds"] == Decimal(str(heard.duration_seconds))
    assert all(source == "pipeline.check" for source in await sources(admin_engine, org))


async def sources(admin_engine: AsyncEngine, org: UUID) -> set[str]:
    async with admin_engine.connect() as conn:
        rows = await conn.scalars(
            text("SELECT DISTINCT source FROM usage_events WHERE organization_id = :org"),
            {"org": org},
        )
        return set(rows)


async def test_a_failed_call_is_recorded_as_an_error(
    ai: AiServices, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("AiFailure")
    ai.llm.failures.append(AiUnavailable("vendor down"))  # type: ignore[attr-defined]
    with pytest.raises(AiUnavailable):
        await ai.llm.complete(context(org), [{"role": "user", "content": "x"}], Summary)
    [row] = await invocations(admin_engine, org)
    assert (row["status"], row["error_code"]) == ("error", "unavailable")
    assert row["cost_usd"] in (None, Decimal(0))


async def test_the_record_survives_the_callers_rollback(
    ai: AiServices, app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("AiRollback")
    with pytest.raises(Rollback):
        async with app_db.tenant(org):
            await ai.llm.complete(context(org), [{"role": "user", "content": "x"}], Summary)
            raise Rollback
    assert len(await invocations(admin_engine, org)) == 1


@pytest.fixture
async def spent(
    admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> AsyncIterator[UUID]:
    """An organisation that has already spent $0.02 on AI this month."""
    org = await make_organization("AiSpender")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO ai_invocations (id, occurred_at, organization_id, service, purpose, "
                "provider, model, latency_ms, cost_usd, status) VALUES (gen_random_uuid(), now(), "
                ":org, 'llm', 'test.spend', 'mock', 'mock-llm', 1, 0.02, 'ok')"
            ),
            {"org": org},
        )
    yield org


async def test_a_quota_stops_calls_before_they_reach_the_vendor(
    ai: AiServices, admin_engine: AsyncEngine, spent: UUID
) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO quotas (organization_id, meter, period, limit_value) "
                "VALUES (:org, 'ai.cost.usd', 'month', 0.01)"
            ),
            {"org": spent},
        )
    calls_before = ai.llm.calls  # type: ignore[attr-defined]
    with pytest.raises(AiBudgetExceeded):
        await ai.llm.complete(context(spent), [{"role": "user", "content": "x"}], Summary)
    assert ai.llm.calls == calls_before  # type: ignore[attr-defined]
    assert len(await invocations(admin_engine, spent)) == 1  # only the seeded spend


async def test_without_a_quota_the_default_budget_applies(
    app_db: Database, admin_engine: AsyncEngine, spent: UUID
) -> None:
    tight = build_ai(
        AiSettings(profile="mock", monthly_budget_usd=Decimal("0.01")), app_db, prices=MOCK_PRICES
    )
    with pytest.raises(AiBudgetExceeded):
        await tight.llm.complete(context(spent), [{"role": "user", "content": "x"}], Summary)
    roomy = build_ai(AiSettings(profile="mock"), app_db, prices=MOCK_PRICES)
    await roomy.llm.complete(context(spent), [{"role": "user", "content": "x"}], Summary)


async def test_tenants_cannot_see_or_change_each_others_invocations(
    ai: AiServices, app_db: Database, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("AiAcme")
    globex = await make_organization("AiGlobex")
    await ai.llm.complete(context(acme), [{"role": "user", "content": "x"}], Summary)

    async with app_db.tenant(globex) as session:
        rows = await session.scalars(
            select(AiInvocation.id).where(AiInvocation.organization_id == acme)
        )
        assert rows.all() == []
    for statement in ("UPDATE ai_invocations SET cost_usd = 0", "DELETE FROM ai_invocations"):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with app_db.tenant(acme) as session:
                await session.execute(text(statement))
