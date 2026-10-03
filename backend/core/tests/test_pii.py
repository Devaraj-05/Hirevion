"""Personal-data recognisers and masking (SP-04b Task 2, ADR-0015)."""

import pytest

from hirevion_core.documents import pii


def aadhaar(first_eleven: str) -> str:
    """A synthetic Aadhaar number: eleven digits and their Verhoeff check digit."""
    return first_eleven + str(pii.verhoeff_check_digit(first_eleven))


def test_verhoeff_matches_the_published_examples() -> None:
    assert pii.verhoeff_check_digit("236") == 3
    assert pii.verhoeff_check_digit("12345") == 1
    assert pii.verhoeff_valid("2363")
    assert not pii.verhoeff_valid("2364")


def test_an_aadhaar_number_is_found_and_masked_in_any_grouping() -> None:
    number = aadhaar("23412341234")
    spaced = f"{number[:4]} {number[4:8]} {number[8:]}"
    for written in (number, spaced, spaced.replace(" ", "-")):
        masked = pii.mask(f"Aadhaar: {written}, Pune")
        assert masked.text == f"Aadhaar: XXXX XXXX {number[-4:]}, Pune"
        assert masked.counts["aadhaar"] == 1


def test_twelve_digits_that_fail_the_checksum_are_left_alone() -> None:
    number = aadhaar("23412341234")
    wrong = number[:-1] + str((int(number[-1]) + 1) % 10)
    assert pii.mask(f"Order {wrong}").text == f"Order {wrong}"
    # Aadhaar numbers never start with 0 or 1.
    starts_with_one = aadhaar("13412341234")
    assert pii.mask(starts_with_one).counts.get("aadhaar", 0) == 0


def test_a_pan_is_masked_to_its_last_four_characters() -> None:
    masked = pii.mask("PAN ABCPE1234F issued")
    assert masked.text == "PAN XXXXXX234F issued"
    assert masked.counts["pan"] == 1
    assert pii.mask("ABCDE1234F").counts.get("pan", 0) == 0  # D isn't a holder type


def test_masking_twice_changes_nothing() -> None:
    once = pii.mask(f"{aadhaar('23412341234')} ABCPE1234F").text
    assert pii.mask(once).text == once


@pytest.mark.parametrize(
    "written",
    ["+91 98765 43210", "+91-9876543210", "098765 43210", "9876543210", "91 98765-43210"],
)
def test_indian_mobile_numbers_normalise_to_ten_digits(written: str) -> None:
    found = [m for m in pii.find(f"Call {written} today") if m.kind == "phone"]
    assert len(found) == 1
    assert pii.normalise_phone(found[0].value) == "9876543210"


def test_emails_and_labelled_dates_of_birth_are_found() -> None:
    text = "asha.rao@example.test | DOB: 14/03/1996 | Joined 01/06/2020"
    kinds = {(m.kind, m.value) for m in pii.find(text)}
    assert ("email", "asha.rao@example.test") in kinds
    assert ("dob", "14/03/1996") in kinds
    assert ("dob", "01/06/2020") not in kinds
    assert ("dob", "12 March 1995") in {
        (m.kind, m.value) for m in pii.find("Date of Birth - 12 March 1995")
    }


def test_masking_keeps_contact_details() -> None:
    text = "asha.rao@example.test +91 98765 43210"
    masked = pii.mask(text)
    assert masked.text == text
    assert masked.counts == {"email": 1, "phone": 1}
