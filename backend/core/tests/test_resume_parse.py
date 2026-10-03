"""The resume parse (SP-04b Task 5): verified quotes, contact checks, evidence and masking."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from hirevion_core.ai.types import AiContext, ChatMessage, LlmResult, Tier
from hirevion_core.documents import pii
from hirevion_core.documents.resume import parse_resume
from hirevion_core.documents.sections import normalise
from hirevion_core.ids import uuid7

AADHAAR = "23412341234" + str(pii.verhoeff_check_digit("23412341234"))
PAGE_ONE = (
    "Asha Rao\nasha.rao@example.test | +91 98765 43210 | Pune\n"
    f"Aadhaar: {AADHAAR}\n\nSummary\nBackend engineer who builds APIs.\n\n"
    "Skills\nPython, Kubernetes"
)
PAGE_TWO = (
    "Experience\nSenior Engineer, Acme Software (2020 - present)\n- Built payment APIs\n\n"
    "Education\nB.Tech, Computer Science, Pune University, 2016"
)
ANSWER: dict[str, Any] = {
    "name": {"value": "Asha Rao", "quote": "Asha Rao"},
    "email": {"value": "asha.rao@example.test", "quote": "asha.rao@example.test"},
    "phone": {"value": "+91 98765 43210", "quote": "+91 98765 43210"},
    "location": {"value": "Pune", "quote": "Pune"},
    "summary": {
        "value": "Backend engineer who builds APIs",
        "quote": "Backend engineer who builds APIs",
    },
    "skills": [
        {"name": "Python", "years": None, "quote": "Python"},
        {"name": "Rust", "years": 3, "quote": "3 years of Rust"},  # not in the resume
    ],
    "total_experience_years": 6,
    "positions": [
        {
            "company": "Acme Software",
            "title": "Senior Engineer",
            "start": "2020",
            "end": None,
            "current": True,
            "quote": "Senior Engineer, Acme Software (2020 - present)",
        },
        {
            "company": "Globex",
            "title": "Engineer",
            "start": "2016",
            "end": "2020",
            "current": False,
            "quote": "Engineer, Globex (2016 - 2020)",  # made up
        },
    ],
    "education": [
        {
            "institution": "Pune University",
            "degree": "B.Tech",
            "field": "Computer Science",
            "start": None,
            "end": "2016",
            "quote": "B.Tech, Computer Science, Pune University, 2016",
        }
    ],
    "certifications": [],
    "projects": [],
    "achievements": [{"text": "Built payment APIs", "quote": "Built payment APIs"}],
    "languages": [],
    "links": [],
}


class FakeLLM:
    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.sent: list[str] = []

    async def complete[T: BaseModel](
        self,
        ctx: AiContext,
        messages: Sequence[ChatMessage],
        schema: type[T],
        tier: Tier = "strong",
    ) -> LlmResult[T]:
        self.sent += [message["content"] for message in messages]
        return LlmResult(schema.model_validate(self.answer), "fake-llm", 100, 100)


async def parse(answer: dict[str, Any]) -> tuple[Any, FakeLLM]:
    llm = FakeLLM(answer)
    pages = [normalise(PAGE_ONE)[0], normalise(PAGE_TWO)[0]]
    result = await parse_resume(llm, UUID(int=1), "\n\n".join(pages), pages, document_id=uuid7())
    return result, llm


async def test_items_whose_quotes_are_missing_are_dropped_and_counted() -> None:
    result, _ = await parse(ANSWER)
    profile = result.profile
    assert [skill["name"] for skill in profile["skills"]] == ["Python"]
    assert [position["company"] for position in profile["positions"]] == ["Acme Software"]
    assert result.dropped == 2


async def test_contact_details_must_be_in_the_text() -> None:
    answer = {**ANSWER, "email": {"value": "someone@else.test", "quote": "Asha Rao"}}
    result, _ = await parse(answer)
    assert result.profile["email"] is None
    assert result.profile["phone"]["value"] == "+91 98765 43210"
    assert result.dropped == 3


async def test_evidence_gives_the_page_and_section() -> None:
    result, _ = await parse(ANSWER)
    profile = result.profile
    assert (profile["name"]["page"], profile["skills"][0]["section"]) == (1, "skills")
    position = profile["positions"][0]
    assert (position["page"], position["section"]) == (2, "experience")
    assert profile["education"][0]["section"] == "qualifications"


async def test_the_ai_never_sees_a_raw_aadhaar_number() -> None:
    _, llm = await parse(ANSWER)
    sent = "\n".join(llm.sent)
    assert AADHAAR not in sent
    assert f"XXXX XXXX {AADHAAR[-4:]}" in sent
    assert "<resume>" in sent
