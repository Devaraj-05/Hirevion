"""The licence gate (D1; master plan §13): permissive licences and unmodified MPL-2.0 only; no
GPL, AGPL, LGPL, SSPL or non-commercial code. A dependency is read from what its package says,
in whatever words it uses."""

import json
from pathlib import Path

import pytest

from hirevion_devcli.licenses import (
    EXCEPTIONS,
    allowed,
    check_javascript,
    check_python,
    verdict,
)


@pytest.mark.parametrize(
    "text",
    [
        "MIT",
        "MIT License",
        "Apache-2.0",
        "Apache Software License",
        "Apache 2.0 License",
        "Apache License 2.0",
        "BSD-3-Clause",
        "BSD License",
        "3-Clause BSD License",
        "BSD-2-Clause",
        "ISC",
        "ISC License (ISCL)",
        "Zlib",
        "Python Software Foundation License",
        "PSF-2.0",
        "Mozilla Public License 2.0 (MPL 2.0)",
        "MPL-2.0",
        "MIT-0",
        "0BSD",
        "Unlicense",
        "CC0-1.0",
        "BlueOak-1.0.0",
        "MIT-CMU",
        "(MIT OR CC0-1.0)",
        "MIT AND PSF-2.0",
        "Apache-2.0 AND MIT",
        "Apache-2.0 OR BSD-3-Clause",
        "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0",
        "Apache Software License; MIT License",
        "MPL-2.0 AND MIT",
        "(MIT OR GPL-3.0-or-later)",  # a choice: MIT is allowed
        "Apache-2.0 AND CNRI-Python",
    ],
)
def test_these_licences_are_allowed(text: str) -> None:
    assert allowed(text), text


@pytest.mark.parametrize(
    "text",
    [
        "GPL-3.0-only",
        "GNU General Public License v3 (GPLv3)",
        "AGPL-3.0-or-later",
        "GNU Affero General Public License v3",
        "LGPL-3.0-only",
        "GNU Lesser General Public License v3 (LGPLv3)",
        "SSPL-1.0",
        "Server Side Public License",
        "CC-BY-NC-4.0",
        "Commercial",
        "UNLICENSED",
        "Other/Proprietary License",
        "MIT AND GPL-2.0-only",  # all of them apply
        "Apache Software License; Other/Proprietary License",
        "BUSL-1.1",
        "",
        "UNKNOWN",
        "Something we have never heard of",
    ],
)
def test_these_licences_are_not(text: str) -> None:
    assert not allowed(text), text


def test_a_named_exception_passes_with_its_reason_and_others_do_not() -> None:
    assert "livekit-local-inference" in EXCEPTIONS
    assert EXCEPTIONS["livekit-local-inference"]
    ok, note = verdict(
        "livekit-local-inference", "Apache Software License; Other/Proprietary License"
    )
    assert ok and "exception" in note
    ok, _ = verdict("some-other-package", "Apache Software License; Other/Proprietary License")
    assert not ok


def test_python_dependencies_are_read_from_pip_licenses_output(tmp_path: Path) -> None:
    report = tmp_path / "py.json"
    report.write_text(
        json.dumps(
            [
                {"Name": "fine", "Version": "1.0", "License": "MIT License"},
                {"Name": "hirevion-core", "Version": "0.1", "License": "UNKNOWN"},
                {"Name": "bad", "Version": "2.0", "License": "GNU General Public License v3"},
            ]
        ),
        encoding="utf-8",
    )
    problems = check_python(report)
    assert problems == [
        "bad 2.0: GNU General Public License v3"
    ]  # our own packages are not checked


def test_javascript_dependencies_are_read_from_license_checker_output(tmp_path: Path) -> None:
    report = tmp_path / "js.json"
    report.write_text(
        json.dumps(
            {
                "react@19.1.0": {"licenses": "MIT"},
                "caniuse-lite@1.0.1": {"licenses": "CC-BY-4.0"},
                "dual@1.0.0": {"licenses": ["MIT", "Apache-2.0"]},
                "copyleft@3.0.0": {"licenses": "GPL-3.0-or-later"},
                "@hirevion/ui@0.1.0": {"licenses": "UNLICENSED"},
                "mystery@0.0.1": {"licenses": "Custom: https://example.test/license"},
            }
        ),
        encoding="utf-8",
    )
    problems = check_javascript(report)
    assert problems == [
        "copyleft@3.0.0: GPL-3.0-or-later",
        "mystery@0.0.1: Custom: https://example.test/license",
    ]


def test_the_font_is_an_accepted_exception() -> None:
    ok, note = verdict("@fontsource-variable/inter", "OFL-1.1")
    assert ok and "Open Font License" in note
    assert not verdict("some-font", "OFL-1.1")[0]
