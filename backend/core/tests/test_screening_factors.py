"""Blind text and the deterministic screening factors (SP-05 Task 2)."""

from decimal import Decimal
from uuid import UUID

from hirevion_core.screening.blind import blind_text
from hirevion_core.screening.factors import (
    CandidateSkillIn,
    JobSkillIn,
    experience_score,
    skill_match,
)

PY, K8S, GO = UUID(int=1), UUID(int=2), UUID(int=3)


def test_required_skills_are_matched_by_taxonomy_id_then_name() -> None:
    match = skill_match(
        [
            JobSkillIn("Python", PY, "required", None),
            JobSkillIn("Kubernetes", K8S, "required", None),
            JobSkillIn("Terraform", None, "required", None),
        ],
        [CandidateSkillIn("Python", PY, None), CandidateSkillIn("terraform", None, None)],
    )
    assert match.matched_required == ["Python", "Terraform"]
    assert match.missing_required == ["Kubernetes"]
    assert round(match.required_score) == 67


def test_too_few_years_earn_half_credit() -> None:
    match = skill_match(
        [JobSkillIn("Python", PY, "required", Decimal(5))],
        [CandidateSkillIn("Python", PY, Decimal(2))],
    )
    assert (match.required_score, match.short_on_years) == (50.0, ["Python"])


def test_preferred_and_optional_skills_and_empty_lists() -> None:
    match = skill_match(
        [JobSkillIn("Go", GO, "preferred", None), JobSkillIn("Rust", None, "optional", None)],
        [CandidateSkillIn("Go", GO, None)],
    )
    assert match.required_score == 100.0  # nothing required: nothing missing
    assert round(match.preferred_score) == 67  # Go counts 1, Rust 0.5 of the 1.5 possible
    assert match.missing_preferred == ["Rust"]


def test_experience_is_scored_against_the_minimum() -> None:
    assert experience_score(Decimal(4), Decimal(8), 6) == (100.0, [])
    assert experience_score(Decimal(4), None, 2) == (50.0, ["2 years against a minimum of 4"])
    assert experience_score(None, None, 1) == (100.0, [])
    score, notes = experience_score(Decimal(2), Decimal(4), 12)
    assert score == 100.0 and notes == ["12 years, above the range of up to 4"]
    assert experience_score(Decimal(3), None, None) == (50.0, ["Years of experience unclear"])


def test_the_blind_text_has_no_name_contact_or_personal_details() -> None:
    text = (
        "Asha Rao\nasha.rao@example.test | +91 98765 43210 | Pune\n"
        "linkedin.com/in/asha-rao\n\nSummary\nBackend engineer.\n\n"
        "Experience\nSenior Engineer, Acme Software\nDOB: 14/03/1996\n\n"
        "Personal Details\nFather's Name: Ravi Rao\nMarital Status: Married\n"
        "Aadhaar: XXXX XXXX 1234\n"
    )
    blind = blind_text(text, {"name": {"value": "Asha Rao"}})
    for gone in ("Asha", "asha.rao@", "98765", "linkedin", "14/03/1996", "Ravi Rao", "Married"):
        assert gone not in blind, gone
    assert "Backend engineer." in blind and "Senior Engineer, Acme Software" in blind
    assert "Pune" not in blind  # it shared the contact line
