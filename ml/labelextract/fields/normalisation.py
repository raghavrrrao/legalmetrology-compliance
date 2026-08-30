"""Turning recognised strings into structured values - or refusing to.

The rule this module exists to enforce
--------------------------------------
**Normalisation may change presentation. It may never change meaning, and it
may never resolve an ambiguity by guessing.**

`03/04/2025` on an Indian label is *probably* 3 April. It is not certainly 3
April. A normaliser that silently picks one produces a date that looks
measured, flows into a compliance finding, and cannot be distinguished later
from a date that was actually unambiguous. So this module emits both candidates
and marks the value uncertain, and the raw reading is preserved untouched in
`ExtractedField.raw_value` either way.

The uncertainty convention
--------------------------
Every mapping produced here carries::

    {
        ...,                          # field-specific structured keys
        "uncertain": bool,            # always present
        "uncertainty_reasons": [...], # present only when uncertain
    }

Structured keys are **absent** when the value could not be committed to, rather
than present-and-wrong. Code downstream must therefore use `.get()` and treat
absence as "not determined". `candidates` lists the readings we could not
choose between.

`uncertain` is about *interpretation*. It is a different axis from
`ExtractedField.confidence`, which is the OCR engine's opinion of the
*characters*. A perfectly recognised `03/04/2025` is high-confidence and
uncertain at the same time, and collapsing the two would lose the distinction.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

#: Always present on a normalised mapping.
UNCERTAIN_KEY = "uncertain"
#: Present only when `uncertain` is True. A list of short, specific strings.
REASONS_KEY = "uncertainty_reasons"

#: Exact conversions to a single base unit per kind of measure. Only conversions
#: that are exact by definition appear here - nothing converts between mass and
#: volume, because "500 ml of oil weighs 500 g" is false and a compliance system
#: must not assume it.
_MASS_TO_GRAMS: dict[str, Decimal] = {
    "mcg": Decimal("0.000001"),
    "ug": Decimal("0.000001"),
    "mg": Decimal("0.001"),
    "g": Decimal(1),
    "gm": Decimal(1),
    "gms": Decimal(1),
    "gram": Decimal(1),
    "grams": Decimal(1),
    "gr": Decimal(1),
    "kg": Decimal(1000),
    "kgs": Decimal(1000),
    "kilogram": Decimal(1000),
    "kilograms": Decimal(1000),
}

_VOLUME_TO_MILLILITRES: dict[str, Decimal] = {
    "ml": Decimal(1),
    "mls": Decimal(1),
    "millilitre": Decimal(1),
    "millilitres": Decimal(1),
    "milliliter": Decimal(1),
    "milliliters": Decimal(1),
    "cc": Decimal(1),
    "cl": Decimal(10),
    "dl": Decimal(100),
    "l": Decimal(1000),
    "ltr": Decimal(1000),
    "ltrs": Decimal(1000),
    "lt": Decimal(1000),
    "litre": Decimal(1000),
    "litres": Decimal(1000),
    "liter": Decimal(1000),
    "liters": Decimal(1000),
}

#: Units that are a count of articles rather than a measure. Legal Metrology
#: labels write these as "N", "U" or "pcs". They have no base conversion.
_COUNT_UNITS: frozenset[str] = frozenset(
    {"n", "u", "pc", "pcs", "piece", "pieces", "no", "nos", "unit", "units"}
)

_MONTH_NAMES: dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

#: A two-digit year on packaging is within living memory of the packing date,
#: never the 1900s. 25 -> 2025.
_CENTURY = 2000

_WHITESPACE = re.compile(r"\s+")
#: 1,00,000 (Indian grouping) and 1,000,000 (international) are both a
#: separator; 12,5 is not, and is treated as ambiguous rather than assumed.
_THOUSANDS = re.compile(r"^\d{1,3}(?:,\d{2,3})+$")


# --- text -------------------------------------------------------------------


def normalise_text(text: str) -> str:
    """Collapse whitespace and normalise Unicode form. Nothing else.

    NFKC folds presentation variants onto their canonical characters -
    full-width digits, ligatures, the several Unicode rupee-adjacent glyphs -
    which is a change of encoding, not of meaning.

    What this deliberately does NOT do is repair OCR errors. Mapping `O` to `0`
    or `l` to `1` would turn an unreliable reading into a confident wrong one,
    and the resulting value would be indistinguishable from a correct read.
    """
    if not text:
        return ""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def certain(**values) -> dict:
    """Build a normalised mapping for a value we could commit to."""
    return {**values, UNCERTAIN_KEY: False}


def uncertain(reasons: list[str] | str, **values) -> dict:
    """Build a normalised mapping for a value we could not commit to.

    Structured keys the caller could not determine must simply be omitted.
    """
    if isinstance(reasons, str):
        reasons = [reasons]
    return {**values, UNCERTAIN_KEY: True, REASONS_KEY: list(reasons)}


def is_uncertain(normalised: dict | None) -> bool:
    """True when a mapping is missing or explicitly marks itself uncertain.

    A missing mapping counts as uncertain: no normaliser ran, so nothing has
    vouched for an interpretation.
    """
    if not normalised:
        return True
    return bool(normalised.get(UNCERTAIN_KEY, True))


# --- numbers ----------------------------------------------------------------


def parse_decimal(text: str) -> tuple[Decimal | None, str | None]:
    """Parse a printed number.

    Returns `(value, None)` on success, or `(None, reason)` when the digits
    cannot be read unambiguously - most often a comma that could be either a
    thousands separator or a decimal point.
    """
    cleaned = normalise_text(text).replace(" ", "")
    if not cleaned:
        return None, "no digits found"

    if "," in cleaned:
        if _THOUSANDS.match(cleaned.split(".")[0]) or _THOUSANDS.match(cleaned):
            cleaned = cleaned.replace(",", "")
        else:
            return None, f"comma in {text!r} could be a decimal point or a separator"

    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None, f"{text!r} is not a number"
    if value < 0:
        return None, "negative quantities do not appear on packaging"
    return value, None


def _as_number(value: Decimal) -> float | int:
    """Emit JSON-friendly numbers without inventing precision.

    Whole values stay integers so `500 g` does not become `500.0` in the API
    and, from there, `500.0` on screen.
    """
    if value == value.to_integral_value():
        return int(value)
    return float(value)


# --- quantity ---------------------------------------------------------------


def normalise_quantity(
    value_text: str, unit_text: str, *, pack_count_text: str | None = None
) -> dict:
    """Structure a net-quantity reading, converting only where it is exact.

    Emits `base_quantity`/`base_unit` (grams or millilitres) alongside the value
    as printed, so two packages can be compared without anyone re-parsing the
    string. Count units get no base value: `10 N` has no gram equivalent, and
    inventing one would be a fabricated measurement.
    """
    unit = normalise_text(unit_text).lower().rstrip(".")
    value, reason = parse_decimal(value_text)
    if value is None:
        return uncertain(reason or "quantity could not be parsed", unit=unit or None)

    pack_count = None
    if pack_count_text:
        counted, count_reason = parse_decimal(pack_count_text)
        if counted is None or counted <= 0:
            return uncertain(
                count_reason or "multi-pack count could not be parsed",
                quantity=_as_number(value),
                unit=unit,
            )
        pack_count = int(counted)

    structured: dict = {"quantity": _as_number(value), "unit": unit}
    if pack_count is not None:
        structured["pack_count"] = pack_count

    if unit in _MASS_TO_GRAMS:
        total = value * _MASS_TO_GRAMS[unit] * (pack_count or 1)
        structured.update(
            measure="mass", base_quantity=_as_number(total), base_unit="g"
        )
        return certain(**structured)

    if unit in _VOLUME_TO_MILLILITRES:
        total = value * _VOLUME_TO_MILLILITRES[unit] * (pack_count or 1)
        structured.update(
            measure="volume", base_quantity=_as_number(total), base_unit="ml"
        )
        return certain(**structured)

    if unit in _COUNT_UNITS:
        # No base conversion exists, and that absence is the correct answer
        # rather than a gap: it is not an uncertain reading.
        structured["measure"] = "count"
        return certain(**structured)

    return uncertain(f"unrecognised unit {unit!r}", **structured)


# --- price ------------------------------------------------------------------


def normalise_price(
    amount_text: str, *, currency: str = "INR", inclusive_of_taxes: bool | None = None
) -> dict:
    """Structure a printed price.

    `amount` is a **string**, not a float. A retail price is money: 0.1 has no
    exact binary representation, and a price that drifts by a paise between
    extraction and display is a defect in a system whose entire purpose is
    checking declarations. The string is a canonical decimal, so a consumer can
    parse it exactly with `Decimal`.
    """
    value, reason = parse_decimal(amount_text)
    if value is None:
        return uncertain(reason or "price could not be parsed", currency=currency)

    exponent = -value.as_tuple().exponent
    if exponent > 2:
        # Three or more decimal places is not how a retail price is printed;
        # it is usually a misread decimal point or a run-together number.
        return uncertain(
            f"{amount_text!r} has more decimal places than a retail price carries",
            currency=currency,
            candidates=[str(value)],
        )

    structured: dict = {"amount": str(value), "currency": currency}
    if inclusive_of_taxes is not None:
        structured["inclusive_of_all_taxes"] = inclusive_of_taxes
    return certain(**structured)


# --- unit sale price --------------------------------------------------------


def normalise_unit_price(
    amount_text: str, unit_text: str, *, currency: str = "INR"
) -> dict:
    """Structure a unit sale price - an amount attached to one unit of measure.

    Rule 6(11) prescribes the printed form ("Rs. _ per g"), so the unit the
    package actually printed is the legally material part of this declaration.
    That is why nothing here converts the amount onto a base unit the way
    `normalise_quantity` does: `Rs. 2.91 per gram` and `Rs. 2910 per kilogram`
    are the same rate but not the same declaration, and reporting a figure the
    package never printed would put an invented number where evidence belongs.
    `per_measure` is emitted instead, which is enough for a later check to know
    which family of units it is looking at without any value being restated.

    Nothing here is a legal decision. Whether the declared unit is the one the
    net-quantity band requires, and whether the declaration was needed at all
    given the retail sale price, are both questions for the rules layer against
    this evidence.
    """
    unit = normalise_text(unit_text).lower().rstrip(".")
    structured = normalise_price(amount_text, currency=currency)

    if is_uncertain(structured):
        # The amount could not be committed to. `normalise_price` has already
        # said why; the unit is carried through so the reading is still
        # recognisable as a *unit* price rather than a bare failure.
        return {**structured, "per_unit": unit or None}

    structured = {**structured, "per_unit": unit}

    if unit in _MASS_TO_GRAMS:
        structured["per_measure"] = "mass"
    elif unit in _VOLUME_TO_MILLILITRES:
        structured["per_measure"] = "volume"
    elif unit in _COUNT_UNITS:
        structured["per_measure"] = "count"
    else:
        return uncertain(f"unrecognised unit {unit!r}", **structured)

    return structured


# --- dates ------------------------------------------------------------------


def normalise_date(
    *,
    first: str | None = None,
    second: str | None = None,
    year: str | None = None,
    month_name: str | None = None,
) -> dict:
    """Structure a printed date, or report why it cannot be pinned down.

    Called with whichever components the pattern matched:

    - `month_name` + `year` (+ optional `first` as the day) - unambiguous.
    - `first`/`second`/`year` all numeric - ambiguous when both could be a
      month, because DD/MM and MM/DD are both in use and the label does not
      say which.
    - `month`/`year` only - a partial date, which "best before 06/2026" really
      is. Reported as `year_month`, not padded out to a day we did not read.

    On success the mapping carries an ISO `date` (or `year_month`). On
    ambiguity it carries `candidates` and no committed value.
    """
    parsed_year = _parse_year(year)
    if year is not None and parsed_year is None:
        return uncertain(f"{year!r} is not a usable year")

    if month_name:
        month = _MONTH_NAMES.get(normalise_text(month_name).lower().rstrip("."))
        if month is None:
            return uncertain(f"unrecognised month name {month_name!r}")
        if parsed_year is None:
            return uncertain("a month was read but no year")
        if first:
            day = _parse_int(first)
            if day is None or not _valid_day(day, month, parsed_year):
                return uncertain(f"{first!r} is not a valid day of {month_name}")
            return certain(date=f"{parsed_year:04d}-{month:02d}-{day:02d}")
        return certain(year_month=f"{parsed_year:04d}-{month:02d}")

    if first is not None and second is None:
        # A single numeric component alongside a year: month and year.
        month = _parse_int(first)
        if month is None or not 1 <= month <= 12 or parsed_year is None:
            return uncertain(f"{first!r}/{year!r} is not a usable month and year")
        return certain(year_month=f"{parsed_year:04d}-{month:02d}")

    left = _parse_int(first)
    right = _parse_int(second)
    if left is None or right is None or parsed_year is None:
        return uncertain("date components could not be read as numbers")

    day_month = _valid_day(left, right, parsed_year) and 1 <= right <= 12
    month_day = _valid_day(right, left, parsed_year) and 1 <= left <= 12

    if day_month and month_day:
        # Both readings are valid calendar dates. Indian labels are
        # overwhelmingly DD/MM, but "overwhelmingly" is not "always", and this
        # value can end up in a compliance finding. Report both.
        return uncertain(
            "both DD/MM and MM/DD are valid readings of this date",
            candidates=[
                f"{parsed_year:04d}-{right:02d}-{left:02d}",
                f"{parsed_year:04d}-{left:02d}-{right:02d}",
            ],
        )
    if day_month:
        return certain(date=f"{parsed_year:04d}-{right:02d}-{left:02d}")
    if month_day:
        return certain(date=f"{parsed_year:04d}-{left:02d}-{right:02d}")
    return uncertain(f"{left}/{right}/{parsed_year} is not a valid calendar date")


def normalise_duration(count_text: str, unit_text: str) -> dict:
    """Structure "best before 9 months from packaging" and its variants.

    A shelf life is not a date. It is stored as a duration, and no expiry date
    is computed from it here: doing that needs a packing date this reading does
    not contain, and a wrong expiry is exactly the kind of fabricated value
    this layer exists to avoid.
    """
    count, reason = parse_decimal(count_text)
    if count is None or count <= 0:
        return uncertain(reason or "duration could not be parsed")
    unit = normalise_text(unit_text).lower().rstrip("s.")
    if unit not in {"day", "week", "month", "year"}:
        return uncertain(f"unrecognised duration unit {unit_text!r}")
    return certain(duration_value=_as_number(count), duration_unit=f"{unit}s")


def _parse_int(text: str | None) -> int | None:
    if text is None:
        return None
    stripped = normalise_text(text)
    if not stripped.isdigit():
        return None
    return int(stripped)


def _parse_year(text: str | None) -> int | None:
    value = _parse_int(text)
    if value is None:
        return None
    if len(normalise_text(text or "")) == 2:
        return _CENTURY + value
    if 1900 <= value <= 2999:
        return value
    return None


def _valid_day(day: int, month: int, year: int) -> bool:
    if not 1 <= month <= 12 or day < 1:
        return False
    return day <= _days_in_month(month, year)


def _days_in_month(month: int, year: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    return 30 if month in (4, 6, 9, 11) else 31
