"""`hv eval-resumes`: the resume pipeline over the synthetic set, scored field by field against
the true values (SP-04b; targets in ADR-0015: F1 ≥ 0.90 overall, ≥ 0.95 for name, email, phone).

It runs the real pipeline in this process with the configured AI profile, in an organisation of
its own, on in-memory blob storage, and writes no outbox events (so a running API's consumer
doesn't pick the documents up as well).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from rapidfuzz import fuzz
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.ai import build_ai
from hirevion_core.ai.settings import load_ai_settings
from hirevion_core.db.session import Database, create_database
from hirevion_core.documents import intake
from hirevion_core.documents.pii import normalise_phone
from hirevion_core.documents.pipeline import DocumentServices, process_document
from hirevion_core.documents.scan import ClamdScanner, FakeScanner, Scanner, ScanUnavailable
from hirevion_core.documents.settings import load_document_settings
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.identity.roles import ensure_system_roles
from hirevion_core.ids import uuid7
from hirevion_core.jobs import jobs
from hirevion_core.jobs.jobs import JobChanges
from hirevion_core.models import Document
from hirevion_core.settings import load_core_settings
from hirevion_core.storage.paths import BlobPath

from .synthetic_resumes import EICAR

FUZZY = 90
CONTACT_FIELDS = ("name", "email", "phone")
TARGET_OVERALL = 0.90
TARGET_CONTACT = 0.95
FIELDS = (
    "name",
    "email",
    "phone",
    "location",
    "skills",
    "companies",
    "titles",
    "start_years",
    "institutions",
    "degrees",
    "certifications",
    "languages",
    "links",
    "projects",
)


@dataclass
class FieldScore:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        total = 2 * self.tp + self.fp + self.fn
        return 2 * self.tp / total if total else 1.0

    def add(self, other: FieldScore) -> None:
        self.tp, self.fp, self.fn = self.tp + other.tp, self.fp + other.fp, self.fn + other.fn


# Normalising and matching


def _aliases() -> dict[str, str]:
    rows = yaml.safe_load(
        (files("hirevion_core.jobs") / "data" / "skills.yaml").read_text(encoding="utf-8")
    )
    lookup: dict[str, str] = {}
    for name, _category, aliases in rows:
        lookup[str(name).lower()] = str(name)
        for alias in aliases:
            lookup[str(alias).lower()] = str(name)
    return lookup


_ALIASES: dict[str, str] | None = None


def canonical_skill(name: str) -> str:
    global _ALIASES
    if _ALIASES is None:
        _ALIASES = _aliases()
    cleaned = " ".join(name.strip().split())
    return _ALIASES.get(cleaned.lower(), cleaned)


def _link(url: str) -> str:
    url = re.sub(r"^https?://", "", url.strip().lower())
    return re.sub(r"^www\.", "", url).rstrip("/")


def _fuzzy(a: str, b: str) -> bool:
    return fuzz.token_sort_ratio(a.lower(), b.lower()) >= FUZZY


def score_value(
    truth: str | None, predicted: str | None, same: Callable[[str, str], bool]
) -> FieldScore:
    result = FieldScore()
    if predicted and truth and same(truth, predicted):
        result.tp = 1
    else:
        result.fp = 1 if predicted else 0
        result.fn = 1 if truth else 0
    return result


def score_list(
    truth: Sequence[str], predicted: Sequence[str], same: Callable[[str, str], bool]
) -> FieldScore:
    remaining = list(dict.fromkeys(truth))
    result = FieldScore()
    for item in dict.fromkeys(predicted):
        match = next((wanted for wanted in remaining if same(wanted, item)), None)
        if match is None:
            result.fp += 1
        else:
            remaining.remove(match)
            result.tp += 1
    result.fn = len(remaining)
    return result


def _values(items: Iterable[dict[str, Any]] | None, key: str) -> list[str]:
    return [str(item[key]) for item in items or [] if item.get(key)]


def _value(extraction: dict[str, Any], key: str) -> str | None:
    item = extraction.get(key)
    return str(item["value"]) if isinstance(item, dict) and item.get("value") else None


def score_resume(truth: dict[str, Any], extraction: dict[str, Any]) -> dict[str, FieldScore]:
    """Each field's score for one resume: `truth` is a `truth.jsonl` row, `extraction` what the
    pipeline stored on the document."""
    positions = truth["positions"]
    predicted_positions = extraction.get("positions") or []
    location = _value(extraction, "location")
    return {
        "name": score_value(truth["name"], _value(extraction, "name"), _fuzzy),
        "email": score_value(
            truth["email"], _value(extraction, "email"), lambda a, b: a.lower() == b.lower()
        ),
        "phone": score_value(
            truth["phone"],
            normalise_phone(_value(extraction, "phone") or ""),
            lambda a, b: a == b,
        ),
        "location": score_value(
            truth["location"],
            location,
            lambda a, b: fuzz.partial_ratio(a.lower(), b.lower()) >= FUZZY,
        ),
        "skills": score_list(
            [canonical_skill(s) for s in truth["skills"]],
            [canonical_skill(s) for s in _values(extraction.get("skills"), "name")],
            lambda a, b: a.lower() == b.lower(),
        ),
        "companies": score_list(
            [p["company"] for p in positions], _values(predicted_positions, "company"), _fuzzy
        ),
        "titles": score_list(
            [p["title"] for p in positions], _values(predicted_positions, "title"), _fuzzy
        ),
        "start_years": score_list(
            [str(p["start"]) for p in positions],
            [s[:4] for s in _values(predicted_positions, "start")],
            lambda a, b: a == b,
        ),
        "institutions": score_list(
            truth["institutions"], _values(extraction.get("education"), "institution"), _fuzzy
        ),
        "degrees": score_list(
            truth["degrees"],
            _values(extraction.get("education"), "degree"),
            lambda a, b: a.replace(".", "").lower() == b.replace(".", "").lower(),
        ),
        "certifications": score_list(
            truth["certifications"], _values(extraction.get("certifications"), "name"), _fuzzy
        ),
        "languages": score_list(
            truth["languages"],
            _values(extraction.get("languages"), "name"),
            lambda a, b: a.lower() == b.lower(),
        ),
        "links": score_list(
            [_link(u) for u in truth["links"]],
            [_link(u) for u in _values(extraction.get("links"), "url")],
            lambda a, b: a == b,
        ),
        "projects": score_list(
            truth["projects"], _values(extraction.get("projects"), "name"), _fuzzy
        ),
    }


@dataclass
class Report:
    fields: dict[str, FieldScore] = field(default_factory=lambda: {f: FieldScore() for f in FIELDS})
    by_format: dict[str, FieldScore] = field(default_factory=dict)
    processed: int = 0
    total: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    eicar_quarantined: bool = False
    injections_flagged: int = 0
    injections: int = 0
    raw_aadhaar_found: int = 0
    duplicates_reused: int = 0
    seconds: float = 0.0
    cost_usd: Decimal = Decimal(0)
    failures: list[str] = field(default_factory=list)

    @property
    def overall(self) -> FieldScore:
        total = FieldScore()
        for score in self.fields.values():
            total.add(score)
        return total

    def met(self) -> bool:
        return (
            self.overall.f1 >= TARGET_OVERALL
            and all(self.fields[name].f1 >= TARGET_CONTACT for name in CONTACT_FIELDS)
            and self.processed == self.total
            and self.eicar_quarantined
            and self.injections_flagged == self.injections
            and self.raw_aadhaar_found == 0
        )

    def markdown(self, profile: str, model: str) -> str:
        rows = "\n".join(
            f"| {name} | {s.precision:.3f} | {s.recall:.3f} | **{s.f1:.3f}** | {s.tp} | {s.fp} "
            f"| {s.fn} |"
            for name, s in self.fields.items()
        )
        overall = self.overall
        formats = "\n".join(
            f"| {name} | {score.f1:.3f} |" for name, score in sorted(self.by_format.items())
        )
        status = ", ".join(f"{name} {count}" for name, count in sorted(self.statuses.items()))
        verdict = "met" if self.met() else "**not met**"
        failures = "\n".join(f"- {failure}" for failure in self.failures[:20]) or "- none"
        when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        targets = (
            f"field F1 ≥ {TARGET_OVERALL:.2f} overall, ≥ {TARGET_CONTACT:.2f} for name, "
            f"email and phone: {verdict}"
        )
        total_row = (
            f"| **Overall** | {overall.precision:.3f} | {overall.recall:.3f} | "
            f"**{overall.f1:.3f}** | {overall.tp} | {overall.fp} | {overall.fn} |"
        )
        quarantined = "yes" if self.eicar_quarantined else "**no**"
        parts = [
            "# Resume parsing evaluation",
            "",
            f"- **Run:** {when}, AI profile `{profile}`, model `{model}`, "
            "prompt `resume-parse-v1`.",
            f"- **Set:** `hv synth-resumes` (seed 7): {self.total} resumes.",
            f"- **Targets (ADR-0015):** {targets}.",
            f"- **Time and cost:** {self.seconds / 60:.1f} minutes, ${self.cost_usd:.4f} of AI.",
            "",
            "## Fields",
            "",
            "| Field | Precision | Recall | F1 | TP | FP | FN |",
            "|---|---|---|---|---|---|---|",
            rows,
            total_row,
            "",
            "## By format (overall F1)",
            "",
            "| Format | F1 |",
            "|---|---|",
            formats,
            "",
            "## Exit criteria (master plan §14 SP-04)",
            "",
            f"- **Processed:** {self.processed} of {self.total} reached a final status ({status}).",
            f"- **EICAR quarantined:** {quarantined}.",
            f"- **Injection samples flagged:** {self.injections_flagged} of {self.injections}.",
            f"- **Raw Aadhaar numbers stored:** {self.raw_aadhaar_found} "
            "(documents, candidates and AI records checked).",
            f"- **Exact copies reused without an AI call:** {self.duplicates_reused} "
            "(the ZIP bundle).",
            "",
            "## Failures",
            "",
            failures,
            "",
        ]
        return "\n".join(parts)


# Running


async def _setup(admin: Database, db: Database) -> Actor:
    org_id, user_id = uuid7(), uuid7()
    async with admin.unscoped() as session:
        await session.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:id, :name, :slug)"),
            {"id": org_id, "name": "Resume evaluation", "slug": f"resume-eval-{org_id.hex[-12:]}"},
        )
        await ensure_system_roles(session, org_id)
        await session.execute(
            text(
                "INSERT INTO users (id, organization_id, email, name, status) "
                "VALUES (:id, :org, :email, 'Resume Evaluator', 'active')"
            ),
            {"id": user_id, "org": org_id, "email": f"eval-{user_id.hex[-12:]}@example.test"},
        )
    return Actor(user_id, org_id, frozenset(permissions_for(["recruiter"])))


class _MemoryBlobs:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, path: BlobPath, data: bytes, content_type: str) -> None:
        self.blobs[str(path)] = data

    async def get(self, path: BlobPath) -> bytes:
        return self.blobs[str(path)]

    async def delete(self, path: BlobPath) -> None:
        self.blobs.pop(str(path), None)


async def _scanner() -> tuple[Scanner, str]:
    settings = load_document_settings()
    clamd = ClamdScanner(settings.clamav_host, settings.clamav_port, timeout=10)
    try:
        await clamd.scan(b"probe")
    except ScanUnavailable:
        return FakeScanner(), "fake (ClamAV unreachable)"
    return clamd, "ClamAV"


async def _all_documents(session: AsyncSession) -> list[Document]:
    return list((await session.scalars(select(Document))).all())


async def evaluate(
    directory: Path, *, limit: int | None = None, parallel: int = 4, log: Callable[[str], None]
) -> tuple[Report, str, str]:
    truths = [
        json.loads(line)
        for line in (directory / "truth.jsonl").read_text(encoding="utf-8").splitlines()
    ][:limit]
    core = load_core_settings()
    admin, db = create_database(core, "admin"), create_database(core, "app")
    ai_settings = load_ai_settings()
    ai = build_ai(ai_settings, db)
    try:
        actor = await _setup(admin, db)
        scanner, scanner_name = await _scanner()
        log(f"Organisation {actor.organization_id}; scanner: {scanner_name}")
        log(f"AI profile: {ai_settings.profile}")
        blobs = _MemoryBlobs()
        services = DocumentServices(db=db, blobs=blobs, scanner=scanner, ai=ai, queue_entries=False)
        async with db.tenant(actor.organization_id) as session:
            job = await jobs.create_job(session, actor, JobChanges(title="Resume evaluation"))

        uploads = [*(t["file"] for t in truths), "eicar.txt", "bundle.zip"]
        ids: dict[str, UUID] = {}
        for name in uploads:
            async with db.tenant(actor.organization_id) as session:
                document = await intake.submit_resume_file(
                    session,
                    actor,
                    job.id,
                    EICAR if name == "eicar.txt" else (directory / name).read_bytes(),
                    name,
                    blobs,
                    publish=False,
                )
                ids[name] = document.id

        started = time.monotonic()
        gate = asyncio.Semaphore(parallel)
        done = 0

        async def run(document_id: UUID) -> None:
            nonlocal done
            async with gate:
                for attempt in range(3):
                    try:
                        await process_document(services, actor.organization_id, document_id)
                        break
                    except Exception as error:  # an outage: try again, as the consumer would
                        log(f"  retrying {document_id} after {type(error).__name__}")
                        await asyncio.sleep(5 * (attempt + 1))
                done += 1
                if done % 20 == 0:
                    log(f"  {done} processed")

        # Single resumes first; the bundle's copies after, so they find the parsed originals.
        await asyncio.gather(*(run(ids[name]) for name in uploads if name != "bundle.zip"))
        await run(ids["bundle.zip"])
        async with db.tenant(actor.organization_id) as session:
            children = [
                d.id for d in await _all_documents(session) if d.parent_id == ids["bundle.zip"]
            ]
        await asyncio.gather(*(run(child) for child in children))
        seconds = time.monotonic() - started

        report = Report(total=len(truths), seconds=seconds)
        async with db.tenant(actor.organization_id) as session:
            documents = {d.id: d for d in await _all_documents(session)}
        for truth in truths:
            document = documents[ids[truth["file"]]]
            report.statuses[document.status] = report.statuses.get(document.status, 0) + 1
            if document.status in ("parsed", "quarantined", "failed"):
                report.processed += 1
            if document.status != "parsed" or not document.extraction:
                report.failures.append(f"{truth['file']}: {document.status} {document.error_code}")
                extraction: dict[str, Any] = {}
            else:
                extraction = document.extraction
            scores = score_resume(truth, extraction)
            fmt = report.by_format.setdefault(truth["format"], FieldScore())
            for name, score in scores.items():
                report.fields[name].add(score)
                fmt.add(score)
            if truth["injection"]:
                report.injections += 1
                if "injection" in document.flags:
                    report.injections_flagged += 1
        report.eicar_quarantined = documents[ids["eicar.txt"]].status == "quarantined"
        report.duplicates_reused = sum(
            1 for child in children if "duplicate_of" in documents[child].flags
        )
        numbers = [t["aadhaar"] for t in truths if t.get("aadhaar")]
        async with admin.unscoped() as session:
            stored = await session.scalar(
                text(
                    "SELECT string_agg(coalesce(d.text, '') || coalesce(d.extraction::text, '') "
                    "|| d.flags::text, ' ') FROM documents d WHERE d.organization_id = :org"
                ),
                {"org": actor.organization_id},
            )
            people = await session.scalar(
                text(
                    "SELECT string_agg(c.profile::text || c.flags::text, ' ') FROM candidates c "
                    "WHERE c.organization_id = :org"
                ),
                {"org": actor.organization_id},
            )
            recorded = await session.scalar(
                text(
                    "SELECT string_agg(coalesce(output::text, ''), ' ') FROM ai_invocations "
                    "WHERE organization_id = :org"
                ),
                {"org": actor.organization_id},
            )
            cost = await session.scalar(
                text(
                    "SELECT coalesce(sum(cost_usd), 0) FROM ai_invocations "
                    "WHERE organization_id = :org"
                ),
                {"org": actor.organization_id},
            )
        haystack = " ".join(str(value or "") for value in (stored, people, recorded))
        digits_only = re.sub(r"[ -]", "", haystack)
        report.raw_aadhaar_found = sum(1 for number in numbers if number in digits_only)
        report.cost_usd = Decimal(str(cost or 0))
        return report, ai_settings.profile, ai_settings.llm_model_strong
    finally:
        await ai.aclose()
        await db.dispose()
        await admin.dispose()
