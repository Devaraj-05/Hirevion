"""D1 code review of the resume pipeline: identity numbers written in the ways resumes write
them are masked before the AI reads them."""

import pytest

from hirevion_core.documents import pii


def aadhaar(first_eleven: str) -> str:
    return first_eleven + str(pii.verhoeff_check_digit(first_eleven))


@pytest.mark.parametrize("separator", [".", "/", "\n", " - ", "  "])
def test_an_aadhaar_number_is_masked_whatever_separates_its_groups(separator: str) -> None:
    number = aadhaar("23412341234")
    written = separator.join((number[:4], number[4:8], number[8:]))
    masked = pii.mask(f"Aadhaar {written} ok")
    assert number[:8] not in masked.text.replace(" ", "")
    assert masked.counts["aadhaar"] == 1


def test_a_labelled_aadhaar_is_masked_even_when_a_scan_misread_a_digit() -> None:
    number = aadhaar("23412341234")
    misread = number[:-1] + str((int(number[-1]) + 1) % 10)
    masked = pii.mask(f"Aadhaar No: {misread[:4]} {misread[4:8]} {misread[8:]}")
    assert masked.text == f"Aadhaar No: XXXX XXXX {misread[-4:]}"
    # An unlabelled number that fails the checksum is still left alone.
    assert pii.mask(f"Order {misread}").text == f"Order {misread}"


def test_a_virtual_id_a_lowercase_pan_and_other_labelled_numbers_are_masked() -> None:
    masked = pii.mask(
        "VID: 1234 5678 9012 3456\npan abcpe1234f\nPassport No: K1234567\n"
        "Voter ID: ABC1234567\nBank account number: 123456789012"
    )
    for secret in ("1234 5678 9012", "abcpe", "K123456", "ABC123456", "12345678"):
        assert secret not in masked.text
    for last_four in ("3456", "234f", "4567", "4567", "9012"):
        assert last_four in masked.text
    assert masked.counts == {
        "vid": 1,
        "pan": 1,
        "passport": 1,
        "voter_id": 1,
        "bank_account": 1,
    }


def test_masking_new_kinds_twice_changes_nothing() -> None:
    once = pii.mask("VID: 1234 5678 9012 3456 Passport No: K1234567 pan abcpe1234f").text
    assert pii.mask(once).text == once
