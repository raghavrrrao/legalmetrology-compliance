"""Normalisation may change presentation. It may never change meaning.

These tests exist mostly to pin down the *refusals*. Anyone can write a
normaliser that parses `500 g`; the property worth protecting is that an
ambiguous reading comes back marked ambiguous instead of quietly resolved.
"""

import pytest

from labelextract.fields.normalisation import (
    REASONS_KEY,
    is_uncertain,
    normalise_date,
    normalise_duration,
    normalise_price,
    normalise_quantity,
    normalise_text,
    normalise_unit_price,
    parse_decimal,
)


# --- text -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Net   Qty \n 500 g ", "Net Qty 500 g"),
        ("\t\tMRP Rs.\t250", "MRP Rs. 250"),
        ("", ""),
    ],
)
def test_whitespace_is_collapsed(raw, expected):
    assert normalise_text(raw) == expected


def test_unicode_presentation_forms_are_folded():
    """Full-width digits are the same digits, differently encoded."""
    assert normalise_text("５００") == "500"


def test_ocr_confusions_are_not_repaired():
    """`O` is not turned into `0`.

    Repairing a misread would produce a value indistinguishable from one that
    was read correctly, which is the single most damaging thing this layer
    could do: the reviewer loses the signal that anything was wrong.
    """
    assert normalise_text("5OO g") == "5OO g"


# --- numbers ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("500", 500), ("2.5", "2.5"), ("1,000", 1000), ("1,00,000", 100000)],
)
def test_thousands_separators_are_removed(raw, expected):
    value, reason = parse_decimal(raw)
    assert reason is None
    assert str(value) == str(expected)


def test_a_comma_that_could_be_a_decimal_point_is_refused():
    value, reason = parse_decimal("12,5")
    assert value is None
    assert "comma" in reason


# --- quantity ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "unit", "base_quantity", "base_unit"),
    [
        ("500", "g", 500, "g"),
        ("1", "kg", 1000, "g"),
        ("1.5", "kg", 1500, "g"),
        ("250", "ml", 250, "ml"),
        ("2", "L", 2000, "ml"),
        ("50", "mg", "0.05", "g"),
    ],
)
def test_quantities_convert_to_a_base_unit(value, unit, base_quantity, base_unit):
    result = normalise_quantity(value, unit)
    assert result["base_unit"] == base_unit
    assert str(result["base_quantity"]) == str(base_quantity)
    assert is_uncertain(result) is False


def test_mass_and_volume_are_never_converted_into_each_other():
    """500 ml of oil does not weigh 500 g, and nothing here may assume it does."""
    assert normalise_quantity("500", "ml")["measure"] == "volume"
    assert normalise_quantity("500", "g")["measure"] == "mass"


def test_multipacks_multiply_into_the_base_quantity():
    result = normalise_quantity("100", "g", pack_count_text="4")
    assert result["pack_count"] == 4
    assert result["quantity"] == 100
    assert result["base_quantity"] == 400


def test_count_units_get_no_base_conversion_and_that_is_not_uncertainty():
    """`10 N` has no gram equivalent. Absence is the right answer, not a doubt."""
    result = normalise_quantity("10", "N")
    assert result["measure"] == "count"
    assert "base_quantity" not in result
    assert is_uncertain(result) is False


def test_an_unrecognised_unit_is_uncertain_not_dropped():
    result = normalise_quantity("500", "zz")
    assert is_uncertain(result) is True
    assert "base_quantity" not in result


# --- price ------------------------------------------------------------------


def test_price_is_carried_as_an_exact_decimal_string():
    """Money must not round-trip through a float."""
    result = normalise_price("250.50")
    assert result["amount"] == "250.50"
    assert isinstance(result["amount"], str)
    assert result["currency"] == "INR"


def test_tax_inclusivity_is_recorded_only_when_it_was_read():
    assert "inclusive_of_all_taxes" not in normalise_price("250")
    assert normalise_price("250", inclusive_of_taxes=True)["inclusive_of_all_taxes"]


def test_a_price_with_too_many_decimals_is_uncertain():
    """`250.000` is a misread decimal point, not a retail price."""
    result = normalise_price("250.000")
    assert is_uncertain(result) is True
    assert "amount" not in result


# --- unit sale price --------------------------------------------------------


@pytest.mark.parametrize(
    ("unit", "measure"),
    [
        ("gram", "mass"),
        ("g", "mass"),
        ("kg", "mass"),
        ("ml", "volume"),
        ("litre", "volume"),
        ("piece", "count"),
        ("n", "count"),
    ],
)
def test_a_unit_price_records_which_family_of_units_it_is_per(unit, measure):
    result = normalise_unit_price("2.91", unit)
    assert result["amount"] == "2.91"
    assert result["currency"] == "INR"
    assert result["per_unit"] == unit
    assert result["per_measure"] == measure
    assert is_uncertain(result) is False


def test_a_unit_price_keeps_the_unit_the_package_printed():
    """Rule 6(11) prescribes the printed form, so no base conversion happens.

    `Rs.200 per kg` and `Rs.0.20 per g` are the same rate and not the same
    declaration. Restating one as the other would report a figure the package
    never printed.
    """
    result = normalise_unit_price("200", "kg")
    assert result["per_unit"] == "kg"
    assert "base_quantity" not in result
    assert "base_unit" not in result


def test_a_unit_price_amount_is_an_exact_decimal_string():
    result = normalise_unit_price("0.10", "g")
    assert result["amount"] == "0.10"
    assert isinstance(result["amount"], str)


def test_an_unparseable_unit_price_amount_carries_no_value():
    result = normalise_unit_price("12,5", "g")
    assert is_uncertain(result) is True
    assert "amount" not in result
    # The unit is still reported, so the reading stays recognisable as a rate.
    assert result["per_unit"] == "g"


def test_an_unrecognised_unit_price_unit_is_uncertain():
    result = normalise_unit_price("2.91", "dozen")
    assert is_uncertain(result) is True
    assert "per_measure" not in result
    assert any("dozen" in reason for reason in result[REASONS_KEY])


def test_a_unit_price_with_too_many_decimals_is_uncertain():
    """Inherited from `normalise_price`: three decimals is a misread point."""
    result = normalise_unit_price("2.9100", "g")
    assert is_uncertain(result) is True
    assert "amount" not in result


# --- dates ------------------------------------------------------------------


def test_an_unambiguous_numeric_date_is_committed_to():
    """25 must be the day: there is no 25th month."""
    result = normalise_date(first="25", second="12", year="2025")
    assert result["date"] == "2025-12-25"
    assert is_uncertain(result) is False


def test_a_date_that_reads_both_ways_is_reported_as_ambiguous():
    """03/04/2025 is 3 April or 4 March. The label does not say which.

    Guessing DD/MM because it is the Indian convention would produce a date
    that looks measured, flows into a compliance finding, and cannot later be
    told apart from one that was genuinely unambiguous.
    """
    result = normalise_date(first="03", second="04", year="2025")

    assert is_uncertain(result) is True
    assert "date" not in result
    assert set(result["candidates"]) == {"2025-04-03", "2025-03-04"}
    assert REASONS_KEY in result


def test_a_named_month_removes_the_ambiguity():
    result = normalise_date(first="03", month_name="Apr", year="2025")
    assert result["date"] == "2025-04-03"
    assert is_uncertain(result) is False


def test_a_two_digit_year_is_read_as_this_century():
    assert normalise_date(first="25", second="12", year="25")["date"] == "2025-12-25"


def test_a_month_and_year_stay_a_month_and_year():
    """`Best before 06/2026` is a partial date; padding it to a day invents one."""
    result = normalise_date(first="06", year="2026")
    assert result["year_month"] == "2026-06"
    assert "date" not in result


@pytest.mark.parametrize(
    ("first", "second", "year"),
    [("31", "02", "2025"), ("45", "13", "2025"), ("00", "00", "2025")],
)
def test_impossible_dates_are_refused(first, second, year):
    result = normalise_date(first=first, second=second, year=year)
    assert is_uncertain(result) is True
    assert "date" not in result


# --- durations --------------------------------------------------------------


def test_a_shelf_life_stays_a_duration():
    """`best before 9 months` is not a date, and no expiry is computed from it.

    Computing one needs a packing date this reading does not contain.
    """
    result = normalise_duration("9", "months")
    assert result == {
        "duration_value": 9,
        "duration_unit": "months",
        "uncertain": False,
    }
    assert "date" not in result
