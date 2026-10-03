"""The synthetic resume set and the evaluation's scoring (SP-04b Task 10)."""

import json
from pathlib import Path

from hirevion_core.documents.files import sniff
from hirevion_core.documents.pii import find
from hirevion_devcli.resume_eval import FieldScore, score_list, score_resume, score_value
from hirevion_devcli.synthetic_resumes import generate


def test_the_set_is_the_same_for_the_same_seed(tmp_path: Path) -> None:
    first = generate(tmp_path / "a", count=12, seed=3)
    second = generate(tmp_path / "b", count=12, seed=3)
    assert [t.name for t in first] == [t.name for t in second]
    assert (tmp_path / "a" / "truth.jsonl").read_text() == (
        tmp_path / "b" / "truth.jsonl"
    ).read_text()


def test_files_are_what_they_say_and_identity_numbers_are_valid(tmp_path: Path) -> None:
    truths = generate(tmp_path, count=12, seed=3)
    for truth in truths:
        data = (tmp_path / truth.file).read_bytes()
        expected = {"jpg": "jpeg"}.get(truth.file.rsplit(".", 1)[1], truth.file.rsplit(".", 1)[1])
        assert sniff(data) == expected, truth.file
        if truth.aadhaar:
            assert [m.kind for m in find(truth.personal["Aadhaar"])] == ["aadhaar"]
        assert truth.email.endswith("@example.test")
    assert (tmp_path / "bundle.zip").exists()
    assert not (tmp_path / "eicar.txt").exists()  # a desktop anti-virus would take it
    rows = (tmp_path / "truth.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 12 and json.loads(rows[0])["file"] == "resume-001.pdf"


def test_the_f1_arithmetic() -> None:
    score = FieldScore(tp=8, fp=2, fn=2)
    assert (score.precision, score.recall, round(score.f1, 3)) == (0.8, 0.8, 0.8)
    assert FieldScore().f1 == 1.0  # nothing expected, nothing given


def test_values_and_lists_are_matched_fuzzily_once_each() -> None:
    same = lambda a, b: a.lower() == b.lower()  # noqa: E731
    assert score_value("Asha Rao", "asha rao", same) == FieldScore(tp=1)
    assert score_value("Asha Rao", "Ravi", same) == FieldScore(fp=1, fn=1)
    assert score_value("Asha Rao", None, same) == FieldScore(fn=1)
    assert score_list(["Go", "Python"], ["python", "Rust", "python"], same) == FieldScore(
        tp=1, fp=1, fn=1
    )


def test_a_resume_is_scored_field_by_field() -> None:
    truth = {
        "name": "Asha Rao",
        "email": "asha@example.test",
        "phone": "9876543210",
        "location": "Pune",
        "skills": ["Python", "Kubernetes"],
        "positions": [{"title": "Backend Engineer", "company": "Acme Labs", "start": 2021}],
        "institutions": ["Pune Institute of Technology"],
        "degrees": ["B.Tech"],
        "certifications": [],
        "languages": ["English"],
        "links": ["linkedin.com/in/asha"],
        "projects": [],
    }
    extraction = {
        "name": {"value": "Asha Rao"},
        "email": {"value": "ASHA@example.test"},
        "phone": {"value": "+91 98765 43210"},
        "location": {"value": "Pune, Maharashtra"},
        "skills": [{"name": "py"}, {"name": "k8s"}],
        "positions": [{"title": "Backend Engineer", "company": "Acme Labs", "start": "2021-04"}],
        "education": [{"institution": "Pune Institute of Technology", "degree": "BTech"}],
        "languages": [{"name": "English"}],
        "links": [{"url": "https://www.linkedin.com/in/asha/"}],
    }
    scores = score_resume(truth, extraction)
    assert all(score.f1 == 1.0 for score in scores.values()), {
        name: score for name, score in scores.items() if score.f1 < 1
    }
