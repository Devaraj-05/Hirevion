"""Personal data in resumes (ADR-0015): built-in recognisers for Indian identity numbers and
contact details, and the masking applied before text is stored or sent to an AI service.

Aadhaar numbers (12 digits, first 2–9, Verhoeff-valid) and PANs keep only their last four
characters. Phones, emails and dates of birth are found (for checking parsed contact details,
and for SP-05's blind mode) but left in place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# The Verhoeff tables: multiplication in the dihedral group D5, the position permutation and
# the inverse.
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)

# 12 digits, ungrouped or in 4-4-4 groups, not inside a longer number.
_AADHAAR = re.compile(r"(?<![\dX])([2-9]\d{3})[ -]?(\d{4})[ -]?(\d{4})(?!\d)")
# Holder types in the fourth letter: P(erson), C(ompany), H(UF), F(irm), A(OP), T(rust),
# B(OI), L(ocal authority), J(uridical person), G(overnment).
_PAN = re.compile(r"\b[A-Z]{3}[ABCFGHJLPT][A-Z][0-9]{4}[A-Z]\b")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(
    r"(?<![\w+])(?:(?:\+?91)[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"  # Indian mobiles
    r"|(?<![\w+])\+(?!91)\d{1,3}[\s-]?\d(?:[\s-]?\d){6,11}(?!\d)"  # other E.164 numbers
)
_MONTHS = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE = (
    r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}\s*,?\s*\d{{4}}"
    rf"|{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*\d{{4}}"
)
_DOB = re.compile(
    rf"\b(?:D\.?O\.?B\.?|Date\s+of\s+Birth|Born(?:\s+on)?)\b[^\n\d]{{0,30}}?({_DATE})",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PiiMatch:
    kind: str
    start: int
    end: int
    value: str


@dataclass(frozen=True, slots=True)
class Masked:
    text: str
    counts: dict[str, int] = field(default_factory=dict)


def verhoeff_check_digit(digits: str) -> int:
    check = 0
    for index, digit in enumerate(reversed(digits)):
        check = _D[check][_P[(index + 1) % 8][int(digit)]]
    return _INV[check]


def verhoeff_valid(digits: str) -> bool:
    check = 0
    for index, digit in enumerate(reversed(digits)):
        check = _D[check][_P[index % 8][int(digit)]]
    return check == 0


def normalise_phone(value: str) -> str | None:
    """The digits of a phone number, with India's 91 or 0 prefix dropped from a mobile."""
    digits = re.sub(r"\D", "", value)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) >= 7 else None


def find(text: str) -> list[PiiMatch]:
    """Every recognised item, in text order."""
    found: list[PiiMatch] = []
    for match in _AADHAAR.finditer(text):
        if verhoeff_valid("".join(match.groups())):
            found.append(PiiMatch("aadhaar", match.start(), match.end(), match.group()))
    found += [PiiMatch("pan", m.start(), m.end(), m.group()) for m in _PAN.finditer(text)]
    found += [PiiMatch("email", m.start(), m.end(), m.group()) for m in _EMAIL.finditer(text)]
    taken = [(m.start, m.end) for m in found if m.kind == "aadhaar"]
    for match in _PHONE.finditer(text):
        if not any(start < match.end() and match.start() < end for start, end in taken):
            found.append(PiiMatch("phone", match.start(), match.end(), match.group().strip()))
    found += [PiiMatch("dob", m.start(1), m.end(1), m.group(1)) for m in _DOB.finditer(text)]
    return sorted(found, key=lambda m: m.start)


def mask(text: str) -> Masked:
    """`text` with Aadhaar numbers and PANs masked, and a count of each kind found."""
    counts: dict[str, int] = {}
    pieces: list[str] = []
    position = 0
    for match in find(text):
        counts[match.kind] = counts.get(match.kind, 0) + 1
        if match.kind not in ("aadhaar", "pan") or match.start < position:
            continue
        digits = re.sub(r"\D", "", match.value)
        replacement = (
            f"XXXX XXXX {digits[-4:]}" if match.kind == "aadhaar" else f"XXXXXX{match.value[-4:]}"
        )
        pieces += [text[position : match.start], replacement]
        position = match.end
    pieces.append(text[position:])
    return Masked("".join(pieces), counts)
