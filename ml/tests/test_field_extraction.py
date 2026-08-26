"""Interpretation of recognised text into declarations.

No OCR engine is involved anywhere in this file. Field extraction takes text
and returns declarations; giving it text directly is what makes these tests
deterministic, offline, and a measurement of interpretation rather than of
recognition.
"""

import pytest

from labelextract.contracts import LabelFieldKey, OcrResult
from labelextract.fields import RuleBasedFieldExtractor
from labelextract.fields.normalisation import is_uncertain
from labelextract.fields.rule_based import SUPPORTED_KEYS, UNSUPPORTED_KEYS


@pytest.fixture
def extractor():
    return RuleBasedFieldExtractor()


def _extract(extractor, ocr_lines, image_ref, lines, **kwargs):
    return extractor.extract(ocr_lines(lines, **kwargs), image_ref)


def _field(fields, key):
    for extracted in fields:
        if extracted.key is key:
            return extracted
    return None


# --- net quantity -----------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "quantity", "unit", "base_quantity"),
    [
        ("Net Qty: 500 g", 500, "g", 500),
        ("Net Weight 1 kg", 1, "kg", 1000),
        ("NET QUANTITY: 250 ml", 250, "ml", 250),
        ("Net Vol. 2 L", 2, "l", 2000),
        ("Net Wt: 4 x 100 g", 100, "g", 400),
    ],
)
def test_net_quantity_is_extracted_and_converted(
    extractor, ocr_lines, image_ref, line, quantity, unit, base_quantity
):
    fields = _extract(extractor, ocr_lines, image_ref, [line])
    found = _field(fields, LabelFieldKey.NET_QUANTITY)

    assert found is not None
    assert found.normalized_value["quantity"] == quantity
    assert found.normalized_value["unit"] == unit
    assert found.normalized_value["base_quantity"] == base_quantity
    assert is_uncertain(found.normalized_value) is False


def test_a_bare_quantity_is_not_reported_as_a_net_quantity(
    extractor, ocr_lines, image_ref
):
    """Precision over recall, deliberately.

    A number with a unit is not a declaration. Reporting one as the net
    quantity would make `field_presence` PASS, which hides a package that
    genuinely failed to declare it - the more damaging of the two errors here.
    """
    fields = _extract(extractor, ocr_lines, image_ref, ["Contains 500 g of goodness"])
    assert _field(fields, LabelFieldKey.NET_QUANTITY) is None


def test_nutrition_panel_quantities_are_ignored(extractor, ocr_lines, image_ref):
    """The nutrition table is the dominant source of false positives."""
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        ["Nutritional Information", "Quantity per 100 g: Fat 20 g, Protein 7 g"],
    )
    assert _field(fields, LabelFieldKey.NET_QUANTITY) is None


def test_recall_can_be_traded_back_explicitly(ocr_lines, image_ref):
    """The keyword requirement is a documented setting, not a hidden default."""
    relaxed = RuleBasedFieldExtractor(require_net_quantity_keyword=False)
    fields = relaxed.extract(ocr_lines(["SUNRISE ATTA 500 g"]), image_ref)
    found = _field(fields, LabelFieldKey.NET_QUANTITY)

    assert found is not None
    # And what it costs is stated on the field itself, not left implicit.
    assert is_uncertain(found.normalized_value) is True


# --- retail sale price ------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "amount"),
    [
        ("MRP Rs. 250.00", "250.00"),
        ("M.R.P. ₹ 99", "99"),
        ("Maximum Retail Price INR 1,250", "1250"),
        ("MRP 45", "45"),
    ],
)
def test_price_is_extracted(extractor, ocr_lines, image_ref, line, amount):
    fields = _extract(extractor, ocr_lines, image_ref, [line])
    found = _field(fields, LabelFieldKey.RETAIL_SALE_PRICE)

    assert found is not None
    assert found.normalized_value["amount"] == amount
    assert found.normalized_value["currency"] == "INR"


def test_tax_inclusivity_is_read_when_declared(extractor, ocr_lines, image_ref):
    fields = _extract(
        extractor, ocr_lines, image_ref, ["MRP Rs. 250 (inclusive of all taxes)"]
    )
    found = _field(fields, LabelFieldKey.RETAIL_SALE_PRICE)
    assert found.normalized_value["inclusive_of_all_taxes"] is True


def test_a_price_without_an_mrp_keyword_is_marked_uncertain(
    extractor, ocr_lines, image_ref
):
    fields = _extract(extractor, ocr_lines, image_ref, ["Rs. 250"])
    found = _field(fields, LabelFieldKey.RETAIL_SALE_PRICE)

    assert found is not None
    assert is_uncertain(found.normalized_value) is True


def test_a_unit_price_is_not_reported_as_the_retail_sale_price(
    extractor, ocr_lines, image_ref
):
    """`₹200 per kg` is a different declaration, and one we do not extract yet."""
    fields = _extract(extractor, ocr_lines, image_ref, ["Unit price Rs. 200 per kg"])
    assert _field(fields, LabelFieldKey.RETAIL_SALE_PRICE) is None


# --- dates ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "key"),
    [
        ("Mfg Date: 25/12/2024", LabelFieldKey.DATE_OF_MANUFACTURE),
        ("Manufactured on 25 DEC 2024", LabelFieldKey.DATE_OF_MANUFACTURE),
        ("Packed on: 25/12/2024", LabelFieldKey.DATE_OF_PACKING),
        ("Date of Packing 25-12-2024", LabelFieldKey.DATE_OF_PACKING),
        ("Best Before: 25/12/2026", LabelFieldKey.BEST_BEFORE),
        ("Use by 25 Dec 2026", LabelFieldKey.BEST_BEFORE),
        ("EXP 25/12/2026", LabelFieldKey.BEST_BEFORE),
        ("Date of Import: 25/12/2024", LabelFieldKey.DATE_OF_IMPORT),
    ],
)
def test_dates_are_attributed_to_the_right_declaration(
    extractor, ocr_lines, image_ref, line, key
):
    fields = _extract(extractor, ocr_lines, image_ref, [line])
    found = _field(fields, key)

    assert found is not None, f"{line!r} produced no {key.value}"
    assert found.normalized_value["date"].endswith("-12-25")


def test_a_date_on_the_following_line_is_still_found(
    extractor, ocr_lines, image_ref
):
    """Labels print the keyword above the value, and OCR breaks lines."""
    fields = _extract(
        extractor, ocr_lines, image_ref, ["Best Before", "25/12/2026"]
    )
    found = _field(fields, LabelFieldKey.BEST_BEFORE)

    assert found is not None
    assert found.normalized_value["date"] == "2026-12-25"
    # The evidence spans both lines, so a reviewer can see why they were joined.
    assert "Best Before" in found.raw_value and "25/12/2026" in found.raw_value


def test_two_dates_on_one_line_are_not_mixed_up(extractor, ocr_lines, image_ref):
    fields = _extract(
        extractor, ocr_lines, image_ref, ["MFG 25/12/2024 EXP 24/12/2026"]
    )

    manufacture = _field(fields, LabelFieldKey.DATE_OF_MANUFACTURE)
    expiry = _field(fields, LabelFieldKey.BEST_BEFORE)
    assert manufacture.normalized_value["date"] == "2024-12-25"
    assert expiry.normalized_value["date"] == "2026-12-24"


def test_an_ambiguous_date_is_not_silently_resolved(extractor, ocr_lines, image_ref):
    """The central guarantee of this layer, asserted on the extracted field."""
    fields = _extract(extractor, ocr_lines, image_ref, ["Mfg Date: 03/04/2025"])
    found = _field(fields, LabelFieldKey.DATE_OF_MANUFACTURE)

    assert found is not None
    assert is_uncertain(found.normalized_value) is True
    assert "date" not in found.normalized_value
    assert set(found.normalized_value["candidates"]) == {"2025-04-03", "2025-03-04"}


def test_a_shelf_life_is_recorded_as_a_duration(extractor, ocr_lines, image_ref):
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        ["Best before 9 months from the date of packaging"],
    )
    found = _field(fields, LabelFieldKey.BEST_BEFORE)

    assert found.normalized_value["duration_value"] == 9
    assert found.normalized_value["duration_unit"] == "months"
    assert "date" not in found.normalized_value


# --- batch / lot ------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "value"),
    [
        ("Batch No: B24X117", "B24X117"),
        ("BATCH NO. 2024/117", "2024/117"),
        ("Lot No : LT-9981", "LT-9981"),
        ("B.No 7712", "7712"),
    ],
)
def test_batch_numbers_are_extracted(extractor, ocr_lines, image_ref, line, value):
    fields = _extract(extractor, ocr_lines, image_ref, [line])
    found = _field(fields, LabelFieldKey.BATCH_NUMBER)

    assert found is not None
    assert found.normalized_value["batch_number"] == value


def test_a_batch_value_that_reads_as_a_date_is_marked_uncertain(
    extractor, ocr_lines, image_ref
):
    """`Batch No: 03/2025` may be a batch code or a packing date that ran in."""
    fields = _extract(extractor, ocr_lines, image_ref, ["Batch No: 03/2025"])
    found = _field(fields, LabelFieldKey.BATCH_NUMBER)

    assert found is not None
    assert is_uncertain(found.normalized_value) is True
    assert "batch_number" not in found.normalized_value


# --- consumer care, country, names ------------------------------------------


def test_consumer_care_contact_is_extracted(extractor, ocr_lines, image_ref):
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        ["Customer Care: 1800 123 4567, care@example.com"],
    )
    found = _field(fields, LabelFieldKey.CONSUMER_CARE_CONTACT)

    assert found.normalized_value["emails"] == ["care@example.com"]
    assert found.normalized_value["phones"] == ["1800 123 4567"]


def test_a_bare_phone_number_with_no_keyword_is_uncertain(
    extractor, ocr_lines, image_ref
):
    """It may belong to the manufacturer's address rather than consumer care."""
    fields = _extract(extractor, ocr_lines, image_ref, ["Pune 411001 9876543210"])
    found = _field(fields, LabelFieldKey.CONSUMER_CARE_CONTACT)

    assert found is not None
    assert is_uncertain(found.normalized_value) is True


@pytest.mark.parametrize(
    "line",
    ["Country of Origin: India", "Made in India", "Product of India"],
)
def test_country_of_origin_is_extracted(extractor, ocr_lines, image_ref, line):
    fields = _extract(extractor, ocr_lines, image_ref, [line])
    found = _field(fields, LabelFieldKey.COUNTRY_OF_ORIGIN)

    assert found is not None
    assert found.normalized_value["country_text"] == "India"


@pytest.mark.parametrize(
    ("line", "key"),
    [
        ("Manufactured by: Sunrise Foods Pvt Ltd", LabelFieldKey.MANUFACTURER_NAME),
        ("Packed by: Sunrise Packers", LabelFieldKey.PACKER_NAME),
        ("Imported by: Acme Imports LLP", LabelFieldKey.IMPORTER_NAME),
    ],
)
def test_names_are_extracted_but_always_flagged_incomplete(
    extractor, ocr_lines, image_ref, line, key
):
    """The address continues on the next lines and is not extracted.

    Reporting the first line as if it were the whole declaration would be a
    quiet overstatement, so every name carries the caveat with it.
    """
    fields = _extract(extractor, ocr_lines, image_ref, [line])
    found = _field(fields, key)

    assert found is not None
    assert is_uncertain(found.normalized_value) is True
    assert "address" in found.normalized_value["uncertainty_reasons"][0]


# --- conflicts and refusals -------------------------------------------------


def test_two_different_values_for_one_declaration_are_both_reported(
    extractor, ocr_lines, image_ref
):
    """Disagreement is information. Picking one silently would discard it."""
    fields = _extract(
        extractor, ocr_lines, image_ref, ["MRP Rs. 250", "M.R.P. Rs. 260"]
    )
    found = _field(fields, LabelFieldKey.RETAIL_SALE_PRICE)

    assert is_uncertain(found.normalized_value) is True
    assert set(found.normalized_value["candidates"]) == {"250", "260"}


def test_only_one_field_is_emitted_per_declaration(extractor, ocr_lines, image_ref):
    fields = _extract(
        extractor, ocr_lines, image_ref, ["MRP Rs. 250", "M.R.P. Rs. 260"]
    )
    keys = [extracted.key for extracted in fields]
    assert keys.count(LabelFieldKey.RETAIL_SALE_PRICE) == 1


def test_nothing_is_emitted_for_an_empty_ocr_result(extractor, image_ref):
    """No text means no declarations - never a guess to fill the set."""
    assert extractor.extract(OcrResult(), image_ref) == ()


def test_text_with_no_declarations_yields_no_fields(
    extractor, ocr_lines, image_ref
):
    fields = _extract(
        extractor, ocr_lines, image_ref, ["SUNRISE", "The taste of morning"]
    )
    assert fields == ()


# --- provenance -------------------------------------------------------------


def test_geometry_and_confidence_survive_onto_the_field(
    extractor, ocr_lines, image_ref
):
    """Without the box the UI cannot show *where* a declaration was read."""
    fields = _extract(extractor, ocr_lines, image_ref, ["Net Qty: 500 g"])
    found = _field(fields, LabelFieldKey.NET_QUANTITY)

    assert found.box is not None
    assert found.confidence == pytest.approx(0.9)


def test_an_unreported_ocr_confidence_stays_none(extractor, ocr_lines, image_ref):
    """None means 'the engine reported none'. It must not become a number."""
    fields = _extract(
        extractor, ocr_lines, image_ref, ["Net Qty: 500 g"], confidence=None
    )
    assert _field(fields, LabelFieldKey.NET_QUANTITY).confidence is None


def test_the_raw_reading_is_preserved_untouched(extractor, ocr_lines, image_ref):
    fields = _extract(extractor, ocr_lines, image_ref, ["Net Qty: 500 g"])
    assert _field(fields, LabelFieldKey.NET_QUANTITY).raw_value == "Net Qty: 500 g"


def test_every_field_records_how_it_was_located(extractor, ocr_lines, image_ref):
    fields = _extract(
        extractor, ocr_lines, image_ref, ["Net Qty: 500 g", "MRP Rs. 250"]
    )
    assert fields
    for extracted in fields:
        assert extracted.normalized_value["matched_by"] in {"keyword", "pattern"}


# --- the supported/unsupported boundary -------------------------------------


def test_the_unsupported_list_is_derived_not_maintained_by_hand():
    """So the documentation cannot drift away from what the code does."""
    from labelextract.contracts import LabelFieldKey as Keys

    assert SUPPORTED_KEYS | UNSUPPORTED_KEYS == set(Keys)
    assert not SUPPORTED_KEYS & UNSUPPORTED_KEYS


@pytest.mark.parametrize(
    "key",
    [
        LabelFieldKey.MANUFACTURER_ADDRESS,
        LabelFieldKey.COMMON_OR_GENERIC_NAME,
        LabelFieldKey.UNIT_SALE_PRICE,
    ],
)
def test_unsupported_declarations_are_declared_unsupported(key):
    """These are not extracted, and the code says so rather than the docs alone."""
    assert key in UNSUPPORTED_KEYS


def test_a_full_label_produces_only_declarations_it_actually_found(
    extractor, ocr_lines, image_ref
):
    """The end-to-end shape, on a realistic back panel."""
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        [
            "SUNRISE CLASSIC BISCUITS",
            "Net Qty: 500 g",
            "M.R.P. Rs. 250.00 (incl. of all taxes)",
            "Batch No: B24X117",
            "Mfg Date: 25/12/2024",
            "Best Before 9 months from packaging",
            "Country of Origin: India",
            "Manufactured by: Sunrise Foods Pvt Ltd, Pune 411001",
            "Customer Care: 1800 123 4567",
            "Nutritional Information per 100 g: Energy 450 kcal, Fat 20 g",
        ],
    )
    found = {extracted.key for extracted in fields}

    assert LabelFieldKey.NET_QUANTITY in found
    assert LabelFieldKey.RETAIL_SALE_PRICE in found
    assert LabelFieldKey.BATCH_NUMBER in found
    assert LabelFieldKey.DATE_OF_MANUFACTURE in found
    assert LabelFieldKey.BEST_BEFORE in found
    assert LabelFieldKey.COUNTRY_OF_ORIGIN in found
    assert LabelFieldKey.MANUFACTURER_NAME in found
    assert LabelFieldKey.CONSUMER_CARE_CONTACT in found
    # Never invented to complete the set, however obvious the gap looks.
    assert LabelFieldKey.MANUFACTURER_ADDRESS not in found
    assert LabelFieldKey.COMMON_OR_GENERIC_NAME not in found


# --- regression: country of origin must not match prose that shares its words


@pytest.mark.parametrize(
    "line",
    [
        "Made in a facility that also processes nuts and milk",
        "Made in a unit that also handles wheat",
        "Product of the finest wheat grown in Punjab",
        "Origin of ingredients: multiple countries",
        "Manufactured in accordance with FSSAI guidelines",
    ],
)
def test_marketing_and_allergen_text_is_not_a_country_declaration(
    extractor, ocr_lines, image_ref, line
):
    """These share their opening words with a real declaration and nothing else.

    Emitting them as *uncertain* would not be good enough: `field_presence`
    PASSES on any extracted field regardless of its uncertainty flag, so a
    package that never declared an origin would be recorded as having one.
    Nothing is emitted at all.
    """
    fields = _extract(extractor, ocr_lines, image_ref, [line])
    assert _field(fields, LabelFieldKey.COUNTRY_OF_ORIGIN) is None


@pytest.mark.parametrize(
    ("line", "country"),
    [
        ("Country of Origin: India", "India"),
        ("COUNTRY OF ORIGIN - INDIA", "INDIA"),
        ("Country of Origin: United States of America", "United States of America"),
        ("Country of Origin: Trinidad and Tobago", "Trinidad and Tobago"),
    ],
)
def test_an_explicit_declaration_is_committed_to(
    extractor, ocr_lines, image_ref, line, country
):
    """Nothing else on a package is phrased "Country of Origin"."""
    fields = _extract(extractor, ocr_lines, image_ref, [line])
    found = _field(fields, LabelFieldKey.COUNTRY_OF_ORIGIN)

    assert found is not None
    assert found.normalized_value["country_text"] == country
    assert is_uncertain(found.normalized_value) is False


@pytest.mark.parametrize(
    "line", ["Made in India", "MADE IN INDIA", "Product of India"]
)
def test_an_implied_origin_is_extracted_but_flagged(
    extractor, ocr_lines, image_ref, line
):
    """"Made in X" is usually the country and sometimes the factory's town.

    Extracted, because it is how most Indian labels actually print it - and
    flagged, because the wording alone cannot settle which of the two it is.
    """
    fields = _extract(extractor, ocr_lines, image_ref, [line])
    found = _field(fields, LabelFieldKey.COUNTRY_OF_ORIGIN)

    assert found is not None
    assert found.normalized_value["country_text"].casefold() == "india"
    assert is_uncertain(found.normalized_value) is True


# --- regression: MRP must be the price, not the first number on the line ----


@pytest.mark.parametrize(
    ("line", "amount"),
    [
        # The quantity is printed before the price. Taking the first number
        # here recorded 500 as the retail price, confidently.
        ("MRP (incl. of all taxes) for 500 g pack: 250", "250"),
        ("M.R.P. 500 g pack 250.00", "250.00"),
        ("MRP 1 kg pack Rs. 120", "120"),
        # The price follows the keyword directly.
        ("MRP Rs. 250.00", "250.00"),
        ("M.R.P.: 45", "45"),
        ("Maximum Retail Price INR 1,250", "1250"),
        ("Retail Sale Price Rs 99.50", "99.50"),
        # The price precedes the keyword - accepted only because a currency
        # token anchors it.
        ("Rs. 250 M.R.P.", "250"),
    ],
)
def test_the_price_is_read_and_not_the_nearest_number(
    extractor, ocr_lines, image_ref, line, amount
):
    fields = _extract(extractor, ocr_lines, image_ref, [line])
    found = _field(fields, LabelFieldKey.RETAIL_SALE_PRICE)

    assert found is not None, f"{line!r} produced no price"
    assert found.normalized_value["amount"] == amount


def test_a_quantity_is_never_reported_as_the_price(extractor, ocr_lines, image_ref):
    """The specific failure this guards: a net quantity becoming an MRP."""
    fields = _extract(
        extractor, ocr_lines, image_ref, ["MRP for 500 g pack: 250"]
    )
    found = _field(fields, LabelFieldKey.RETAIL_SALE_PRICE)

    assert found.normalized_value["amount"] != "500"
    assert found.normalized_value["amount"] == "250"


def test_an_mrp_keyword_with_no_price_reports_nothing(
    extractor, ocr_lines, image_ref
):
    """Never a guess. The price is on another line, or was not read."""
    fields = _extract(
        extractor, ocr_lines, image_ref, ["MRP incl. of all taxes"]
    )
    assert _field(fields, LabelFieldKey.RETAIL_SALE_PRICE) is None


def test_a_quantity_alone_after_the_keyword_is_not_a_price(
    extractor, ocr_lines, image_ref
):
    fields = _extract(extractor, ocr_lines, image_ref, ["MRP for the 500 g pack"])
    assert _field(fields, LabelFieldKey.RETAIL_SALE_PRICE) is None


# --- regression: a cross-line reading is an inference, not a reading --------


def test_a_date_read_from_the_next_line_is_uncertain(
    extractor, ocr_lines, image_ref
):
    """Nothing ties the two together except adjacency, which is a guess.

    The same date on the keyword's own line is committed to; this one is not.
    """
    fields = _extract(
        extractor, ocr_lines, image_ref, ["Best Before", "25/12/2026"]
    )
    found = _field(fields, LabelFieldKey.BEST_BEFORE)

    assert found.normalized_value["date"] == "2026-12-25"
    assert is_uncertain(found.normalized_value) is True
    assert any(
        "line after the keyword" in reason
        for reason in found.normalized_value["uncertainty_reasons"]
    )


def test_a_date_on_the_keyword_line_stays_certain(extractor, ocr_lines, image_ref):
    """The contrast that makes the flag above mean something."""
    fields = _extract(
        extractor, ocr_lines, image_ref, ["Best Before 25/12/2026"]
    )
    found = _field(fields, LabelFieldKey.BEST_BEFORE)

    assert is_uncertain(found.normalized_value) is False


def test_an_unrelated_date_below_a_keyword_is_not_taken_as_fact(
    extractor, ocr_lines, image_ref
):
    """A batch code under "Packed by" is not a packing date, and cannot be one."""
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        ["Packed by: ACME Foods Pvt Ltd", "Batch 12/2025"],
    )
    found = _field(fields, LabelFieldKey.DATE_OF_PACKING)

    assert found is not None
    assert is_uncertain(found.normalized_value) is True
