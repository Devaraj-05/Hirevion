"""The licence gate (D1; master plan §13): what the dependencies are allowed to be.

Allowed: MIT, Apache-2.0, BSD, ISC, Zlib, PSF and MPL-2.0 (unmodified), plus the permissive
licences of the same kind that real packages use (0BSD, MIT-0, Unlicense, CC0, BlueOak, MIT-CMU,
CNRI-Python, and CC-BY-4.0 for data such as browser-support tables). Not allowed: GPL, AGPL, LGPL,
SSPL, non-commercial or proprietary code. A package may say its licence in many words
("Apache Software License", "BSD License"), so each name is mapped to its SPDX id first; a name
this module cannot place fails the gate, and is then either added here or made an `EXCEPTIONS`
entry with its reason.

`hv licenses --python` reads `pip-licenses` output, `--js` reads `license-checker` output.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ALLOWED = frozenset(
    {
        "MIT",
        "MIT-0",
        "MIT-CMU",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "0BSD",
        "ISC",
        "Zlib",
        "PSF-2.0",
        "Python-2.0",
        "CNRI-Python",
        "MPL-2.0",
        "Unlicense",
        "CC0-1.0",
        "CC-BY-4.0",
        "BlueOak-1.0.0",
    }
)

# What packages call a licence when they don't use its SPDX id (lower-cased).
ALIASES = {
    "mit license": "MIT",
    "the mit license": "MIT",
    "mit-0": "MIT-0",
    "apache software license": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache 2.0 license": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "apache-2": "Apache-2.0",
    "bsd license": "BSD-3-Clause",
    "bsd": "BSD-3-Clause",
    "3-clause bsd license": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause",
    "bsd-3-clause license": "BSD-3-Clause",
    "2-clause bsd license": "BSD-2-Clause",
    "simplified bsd license": "BSD-2-Clause",
    "isc license (iscl)": "ISC",
    "isc license": "ISC",
    "python software foundation license": "PSF-2.0",
    "psf": "PSF-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "mozilla public license 2.0": "MPL-2.0",
    "zlib license": "Zlib",
    "the unlicense": "Unlicense",
    "the unlicense (unlicense)": "Unlicense",
    "public domain": "CC0-1.0",
}

# Dependencies accepted although a plain reading of their licence fails, each with why. An entry
# is a decision someone made: it belongs here with its reason, not in a skipped check.
EXCEPTIONS = {
    "livekit-local-inference": (
        "Apache-2.0 for the code and the LiveKit Model License for the turn-detector weights it "
        "downloads; used only by the interview agent, a separate process. The model licence "
        "needs the owner's review (STATUS.md, Found in testing)"
    ),
    "@fontsource-variable/inter": (
        "the Inter typeface under the SIL Open Font License 1.1: a font, not code; it may be "
        "embedded and served in a product and used commercially, and it is not copyleft for "
        "the documents and apps that use it"
    ),
    "pypdfium2": (
        "BSD-3-Clause or Apache-2.0; its bundled libraries (PDFium, abseil, FreeType under the "
        "FreeType licence, ICU, lcms, libjpeg-turbo, OpenJPEG, libpng, libtiff, zlib) are all "
        "permissive: checked against the licence files in its wheel"
    ),
}

# Packages of this repository: not third-party code.
OWN_PREFIXES = ("hirevion-", "@hirevion/")

_OR = re.compile(r"\s+OR\s+")
_AND = re.compile(r"\s+AND\s+|;|,")


def _unwrap(text: str) -> str:
    """ "(A OR B)" without its outer brackets; "ISC License (ISCL)" is left as it is."""
    text = text.strip()
    while text.startswith("(") and text.endswith(")") and "(" not in text[1:-1]:
        text = text[1:-1].strip()
    return text


def _name(text: str) -> str:
    cleaned = _unwrap(text)
    return ALIASES.get(cleaned.lower(), cleaned)


def _all_allowed(text: str) -> bool:
    """Every licence in an "A AND B" (or "A; B") list is allowed."""
    parts = [part for part in _AND.split(text) if part.strip()]
    if not parts:
        return False
    return all(_name(part) in ALLOWED for part in parts)


def allowed(text: str) -> bool:
    """Whether a package's licence statement meets the policy: for "A OR B" one allowed
    alternative is enough; for "A AND B" (or "A; B") all must be."""
    text = text.strip()
    if not text:
        return False
    return any(_all_allowed(alternative) for alternative in _OR.split(_unwrap(text)))


def verdict(package: str, text: str) -> tuple[bool, str]:
    """Whether a package passes, and a note when it passes only as an exception."""
    if allowed(text):
        return True, ""
    if package in EXCEPTIONS:
        return True, f"exception: {EXCEPTIONS[package]}"
    return False, ""


# The npm tool that reads each package's licence, pinned so CI and a PC read the same way.
LICENSE_CHECKER = "license-checker-rseidelsohn@4.4.2"


def workspace_directories(root: Path) -> list[Path]:
    """The pnpm workspace's packages (the `packages:` list of pnpm-workspace.yaml, with `dir/*`
    patterns expanded)."""
    found: list[Path] = []
    in_packages = False
    for line in (root / "pnpm-workspace.yaml").read_text(encoding="utf-8").splitlines():
        if line.startswith("packages:"):
            in_packages = True
        elif in_packages and line.lstrip().startswith("- "):
            pattern = line.lstrip()[2:].strip().strip("'\"")
            if pattern.endswith("/*"):
                found += sorted(p for p in (root / pattern[:-2]).iterdir() if p.is_dir())
            else:
                found.append(root / pattern)
        elif in_packages and line.strip() and not line.startswith(" "):
            in_packages = False
    return [path for path in found if (path / "package.json").exists()]


def run_python(root: Path) -> list[str]:
    """Reads the licences of the installed Python packages with `pip-licenses`."""
    with tempfile.TemporaryDirectory() as folder:
        report = Path(folder) / "python.json"
        subprocess.run(  # noqa: S603  # nosec B603 (fixed commands, no user input)
            [
                sys.executable,
                "-m",
                "piplicenses",
                "--from=mixed",
                "--format=json",
                f"--output-file={report}",
            ],
            check=True,
            cwd=root,
            capture_output=True,
        )
        return check_python(report)


def run_javascript(root: Path) -> list[str]:
    """Reads the licences of each workspace package's dependencies with `license-checker`."""
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise RuntimeError("pnpm isn't installed")
    problems: list[str] = []
    seen: set[str] = set()
    with tempfile.TemporaryDirectory() as folder:
        for directory in workspace_directories(root):
            report = Path(folder) / f"{directory.name}.json"
            subprocess.run(  # noqa: S603  # nosec B603 (fixed commands, no user input)
                [
                    pnpm,
                    "dlx",
                    LICENSE_CHECKER,
                    "--json",
                    "--start",
                    str(directory),
                    "--excludePrivatePackages",
                    "--out",
                    str(report),
                ],
                check=True,
                cwd=root,
                capture_output=True,
            )
            for problem in check_javascript(report):
                if problem not in seen:
                    seen.add(problem)
                    problems.append(problem)
    return problems


def check_python(report: Path) -> list[str]:
    """Problems in `pip-licenses --format=json` output; our own packages are not checked."""
    problems = []
    for item in json.loads(report.read_text(encoding="utf-8")):
        name, version, licence = item["Name"], item["Version"], item["License"]
        if name.lower().startswith(OWN_PREFIXES):
            continue
        if not verdict(name, licence)[0]:
            problems.append(f"{name} {version}: {licence}")
    return problems


def check_javascript(report: Path) -> list[str]:
    """Problems in `license-checker --json` output (package `name@version` to its licences)."""
    problems = []
    for key, item in json.loads(report.read_text(encoding="utf-8")).items():
        name = key.rsplit("@", 1)[0]
        if name.startswith(OWN_PREFIXES):
            continue
        licences = item.get("licenses", "")
        # A list is a choice: license-checker lists the alternatives of "(A OR B)".
        text = " OR ".join(licences) if isinstance(licences, list) else str(licences)
        if not verdict(name, text)[0]:
            problems.append(f"{key}: {text}")
    return problems
