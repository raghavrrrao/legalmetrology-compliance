"""A last check between extraction and the emitted field.

Its job is to **reject**, never to repair. It answers one question about a
reading the detectors already committed to:

    is this value obviously not a declaration?

and when the answer is yes, it strips the committed value and marks the mapping
uncertain with the reason. It never substitutes a better value, never guesses
what was meant, and never turns an uncertain reading into a certain one.

Why a separate stage
--------------------
Every detector in `rule_based` already guards its own patterns, and those
guards are the primary defence. This exists because the failure it protects
against is asymmetric in a way that justifies belt and braces:

`field_presence` PASSES on any extracted field regardless of its uncertainty
flag. So a fabricated value does not merely record something wrong - it records
a package as having *declared* something it never declared, turning a real
violation into a pass. A missing declaration produces a review flag and a human
looks at the photograph. The two errors are not equally bad, and the cheap
insurance against the worse one is a single choke point every candidate passes
through, so a future detector, or a future pattern change, cannot route around
the guards by accident.

This is why the checks here duplicate some of what the detectors do. That
duplication is deliberate and is the point of the stage.

What it deliberately does NOT do
--------------------------------
- **It does not check whether a declared value is correct.** Whether 500 g is
  the true net quantity, or whether an MRP is fair, is a compliance question
  decided by verified `ComplianceRule` rows, not here.
- **It does not repair OCR confusions.** Turning `5OO` into `500` would produce
  a value indistinguishable from a correct reading and destroy the only signal
  that anything was wrong. See `normalisation`'s module docstring.
- **It does not apply plausibility limits that encode policy.** The bounds
  below are the limits of physical printing and the calendar, not of what a
  regulator permits.
"""

from __future__ import annotations

import re
from typing import Any

from labelextract.contracts import LabelFieldKey
from labelextract.fields import patterns as P
from labelextract.fields.normalisation import normalise_text

#: Keys whose committed value is stripped when a check rejects it, so that
#: `.get()` returns None and a consumer reading absence as "not determined"
#: gets the right answer. The mapping is kept - with its reason - rather than
#: the whole field being dropped, because "we found this declaration named and
#: could not read a usable value" is a different fact from "this declaration is
#: not on the package", and the second is not something this stage can know.
_VALUE_KEYS: dict[LabelFieldKey, tuple[str, ...]] = {
    LabelFieldKey.BATCH_NUMBER: ("batch_number",),
    LabelFieldKey.NET_QUANTITY: (
        "quantity", "unit", "base_quantity", "base_unit", "measure", "pack_count",
    ),
    LabelFieldKey.RETAIL_SALE_PRICE: ("amount", "inclusive_of_all_taxes"),
    LabelFieldKey.FSSAI_LICENCE: ("licence_number", "digit_count"),
    LabelFieldKey.MANUFACTURER_NAME: ("name",),
    LabelFieldKey.PACKER_NAME: ("name",),
    LabelFieldKey.IMPORTER_NAME: ("name",),
    LabelFieldKey.COUNTRY_OF_ORIGIN: ("country_text",),
    LabelFieldKey.OTHER: ("name",),
}

#: The largest net quantity that can be printed on a retail package, in base
#: units. 100 kg / 100 litres. Not a legal limit - a sanity bound on what a
#: consumer package physically is, chosen so that a misplaced decimal point or
#: a run-together number is caught while every real pack passes.
_MAX_BASE_QUANTITY = 100_000

#: The largest plausible printed retail price, in rupees. Deliberately generous:
#: this catches `₹` misread as a leading digit (the measured `₹465` -> `8465`
#: case is 18x, not 1000x, so it is NOT caught here - the detector's
#: keyword-proximity rule is what handles that) and run-together numbers, not
#: expensive products.
_MAX_PRICE = 1_000_000

#: A printed date outside this range is a misreading, not a date. Packaging
#: carries manufacture dates in the recent past and use-by dates a few years
#: ahead; a year outside this window came from damaged digits.
_MIN_YEAR = 1990
_MAX_YEAR = 2099

#: Minimum length for a free-text name. Two characters cannot identify a
#: company, and the measured failures - `#`, `Ni` - are all shorter than this.
_MIN_NAME_LENGTH = 3


def validate(key: LabelFieldKey, normalized: dict) -> dict:
    """Return `normalized`, with any unusable committed value withdrawn.

    Pure: the input mapping is never mutated.
    """
    for check in _CHECKS.get(key, ()):
        reason = check(normalized)
        if reason is not None:
            return _withdraw(key, normalized, reason)
    return normalized


def _withdraw(key: LabelFieldKey, normalized: dict, reason: str) -> dict:
    """Strip the committed value and record why it was not trusted."""
    stripped = {
        name: value
        for name, value in normalized.items()
        if name not in _VALUE_KEYS.get(key, ())
    }
    reasons = list(stripped.get(P_REASONS, []))
    if reason not in reasons:
        reasons.append(reason)
    stripped[P_UNCERTAIN] = True
    stripped[P_REASONS] = reasons
    return stripped


# Imported by name rather than from `normalisation` to keep this module's
# dependency surface to the two things it actually needs.
P_UNCERTAIN = "uncertain"
P_REASONS = "uncertainty_reasons"


# --- individual checks ------------------------------------------------------
#
# Each returns a reason string when the value must be withdrawn, or None when
# it is acceptable. None means "nothing objectionable found", never "verified
# correct".


def _is_stopword_value(text: Any) -> bool:
    """True when the value is nothing but declaration-naming words.

    Whole tokens only. A genuine batch code that happens to start with the
    letters of a stopword - `NOVA-12`, `LOT7` - is not rejected, because it is
    compared token by token and `nova` is not a stopword.
    """
    if not isinstance(text, str):
        return False
    tokens = [t for t in re.split(r"[^\w]+", normalise_text(text).casefold()) if t]
    if not tokens:
        return True
    return all(token in P.DECLARATION_STOPWORDS for token in tokens)


def _check_batch(normalized: dict) -> str | None:
    value = normalized.get("batch_number")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return "the batch number read as an empty value"
    if _is_stopword_value(value):
        return (
            f"{value!r} is part of the batch-number label rather than a batch "
            f"code; the declaration appears to have been printed with no value"
        )
    if not any(character.isdigit() for character in value):
        return (
            f"{value!r} contains no digit, so it is not a plausible batch code; "
            f"it is more likely adjacent label text than a declared value"
        )
    return None


def _check_net_quantity(normalized: dict) -> str | None:
    base = normalized.get("base_quantity")
    if base is not None:
        if not isinstance(base, (int, float)) or base <= 0:
            return "a net quantity of zero or less is not a printable declaration"
        if base > _MAX_BASE_QUANTITY:
            return (
                f"{base} in base units exceeds anything a retail package "
                f"carries; the number is likely run together with another"
            )
    quantity = normalized.get("quantity")
    if quantity is not None and isinstance(quantity, (int, float)) and quantity <= 0:
        return "a net quantity of zero or less is not a printable declaration"
    pack = normalized.get("pack_count")
    if pack is not None and isinstance(pack, int) and pack <= 0:
        return "a multi-pack count of zero or less is not a printable declaration"
    return None


def _check_price(normalized: dict) -> str | None:
    amount = normalized.get("amount")
    if amount is None:
        return None
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return f"the price {amount!r} could not be read as a number"
    if value <= 0:
        return "a retail sale price of zero or less is not a printable declaration"
    if value > _MAX_PRICE:
        return (
            f"{amount} exceeds any plausible printed retail price; the digits "
            f"are likely run together with an adjacent number"
        )
    return None


def _check_date(normalized: dict) -> str | None:
    for field in ("date", "year_month"):
        value = normalized.get(field)
        if not isinstance(value, str):
            continue
        year = value[:4]
        if not year.isdigit():
            return f"{value!r} is not a readable date"
        if not _MIN_YEAR <= int(year) <= _MAX_YEAR:
            return (
                f"the year in {value!r} is outside the range a packaging date "
                f"can carry, so a digit was misread"
            )
    return None


def _check_fssai(normalized: dict) -> str | None:
    value = normalized.get("licence_number")
    if value is None:
        return None
    if not isinstance(value, str) or not value.isdigit():
        return "an FSSAI licence number is digits only"
    return None


def _check_name(normalized: dict) -> str | None:
    value = normalized.get("name")
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) < _MIN_NAME_LENGTH:
        return (
            f"{value!r} is too short to be a company name; it is more likely a "
            f"fragment of adjacent text than the declared name"
        )
    if _is_stopword_value(value):
        return (
            f"{value!r} is part of the surrounding label text rather than a "
            f"company name"
        )
    if not any(character.isalpha() for character in value):
        return f"{value!r} contains no letters, so it is not a company name"
    return None


def _check_country(normalized: dict) -> str | None:
    value = normalized.get("country_text")
    if value is None:
        return None
    if not isinstance(value, str) or not any(c.isalpha() for c in value):
        return f"{value!r} contains no letters, so it is not a country name"
    if _is_stopword_value(value):
        return f"{value!r} is label text rather than a country name"
    return None


_CHECKS: dict[LabelFieldKey, tuple] = {
    LabelFieldKey.BATCH_NUMBER: (_check_batch,),
    LabelFieldKey.NET_QUANTITY: (_check_net_quantity,),
    LabelFieldKey.RETAIL_SALE_PRICE: (_check_price,),
    LabelFieldKey.DATE_OF_MANUFACTURE: (_check_date,),
    LabelFieldKey.DATE_OF_PACKING: (_check_date,),
    LabelFieldKey.DATE_OF_IMPORT: (_check_date,),
    LabelFieldKey.BEST_BEFORE: (_check_date,),
    LabelFieldKey.FSSAI_LICENCE: (_check_fssai,),
    LabelFieldKey.MANUFACTURER_NAME: (_check_name,),
    LabelFieldKey.PACKER_NAME: (_check_name,),
    LabelFieldKey.IMPORTER_NAME: (_check_name,),
    LabelFieldKey.OTHER: (_check_name,),
    LabelFieldKey.COUNTRY_OF_ORIGIN: (_check_country,),
}
