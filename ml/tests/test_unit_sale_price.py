"""The unit sale price declaration - rule 6(11)'s "Rs. _ per g".

No OCR engine is involved. Field extraction takes text and returns
declarations, so giving it text directly measures interpretation rather than
recognition, deterministically and offline.

**Nothing here asserts an accuracy figure.** Every case is a phrasing that
either must be read, must be read *with a stated reservation*, or must not be
read at all. Which of the three a line falls into is a design decision this
file pins down; how often the phrasings occur on real packaging is measured
against the frozen evaluation set, not here.

The line the whole detector was written for, read by the current pipeline off
`p001_05_declaration_closeup` in that set:

    UNIT SALE PRICE : Rs.2.91 PER GRAM

and the two harder ones it also has to survive:

    MRP (INCL. OF ALL TAXES), USP, #MFD. & @USE BEFORE: SEE BELOW.
    Z 0.08 perg
"""

import pytest

from labelextract.contracts import LabelFieldKey, OcrResult, TextBlock
from labelextract.fields import RuleBasedFieldExtractor
from labelextract.fields import patterns as P
from labelextract.fields.normalisation import is_uncertain
from labelextract.fields.rule_based import SUPPORTED_KEYS

USP = LabelFieldKey.UNIT_SALE_PRICE
MRP = LabelFieldKey.RETAIL_SALE_PRICE


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


# --- capability -------------------------------------------------------------


def test_unit_sale_price_is_a_supported_declaration():
    """The capability list is what the rules layer and the metrics both read."""
    assert USP in SUPPORTED_KEYS


# --- the declaration, read with a keyword -----------------------------------


@pytest.mark.parametrize(
    ("line", "amount", "per_unit", "measure"),
    [
        # The form rule 6(11) prescribes, as the frozen set's product 001
        # prints it.
        ("UNIT SALE PRICE : ₹2.91 PER GRAM", "2.91", "gram", "mass"),
        # OCR routinely loses the rupee glyph; the keyword is doing the
        # anchoring, so its absence is not fatal.
        ("UNIT SALE PRICE : 2.91 PER GRAM", "2.91", "gram", "mass"),
        ("Unit Sale Price: Rs. 200 per kg", "200", "kg", "mass"),
        ("Unit Price Rs.12 per piece", "12", "piece", "count"),
        ("UNIT SALE PRICE: INR 0.45 per ml", "0.45", "ml", "volume"),
        # The slash form, and the abbreviation labels actually print.
        ("USP: ₹0.93/g", "0.93", "g", "mass"),
        ("USP ₹0.93 / g", "0.93", "g", "mass"),
    ],
)
def test_a_keyword_anchored_unit_price_is_read_and_committed_to(
    extractor, ocr_lines, image_ref, line, amount, per_unit, measure
):
    found = _field(_extract(extractor, ocr_lines, image_ref, [line]), USP)

    assert found is not None
    assert found.normalized_value["amount"] == amount
    assert found.normalized_value["currency"] == "INR"
    assert found.normalized_value["per_unit"] == per_unit
    assert found.normalized_value["per_measure"] == measure
    assert not is_uncertain(found.normalized_value)
    assert found.normalized_value["matched_by"] == "keyword"


def test_the_amount_is_an_exact_decimal_string_not_a_float(
    extractor, ocr_lines, image_ref
):
    """Money, for the same reason the retail sale price is a string."""
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["UNIT SALE PRICE: Rs.0.10 per g"]),
        USP,
    )
    assert found.normalized_value["amount"] == "0.10"
    assert isinstance(found.normalized_value["amount"], str)


def test_the_rate_may_be_printed_before_the_keyword(
    extractor, ocr_lines, image_ref
):
    """Allowed, but only when a currency token anchors it."""
    found = _field(
        _extract(
            extractor, ocr_lines, image_ref, ["₹2.91 per gram UNIT SALE PRICE"]
        ),
        USP,
    )
    assert found is not None
    assert found.normalized_value["amount"] == "2.91"


def test_the_keyword_does_not_reach_past_its_own_value(
    extractor, ocr_lines, image_ref
):
    """The net quantity on the same line must not become the unit price."""
    found = _field(
        _extract(
            extractor,
            ocr_lines,
            image_ref,
            ["UNIT SALE PRICE : Rs.2.91 PER GRAM (NET 120 GRAMS)"],
        ),
        USP,
    )
    assert found.normalized_value["amount"] == "2.91"


def test_no_base_unit_conversion_is_invented(extractor, ocr_lines, image_ref):
    """Rule 6(11) prescribes the printed unit, so the printed unit is reported.

    `Rs.200 per kg` and `Rs.0.20 per g` are the same rate and not the same
    declaration. Restating one as the other would put a figure the package
    never printed where evidence belongs.
    """
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["Unit Sale Price: Rs.200 per kg"]),
        USP,
    )
    assert found.normalized_value["per_unit"] == "kg"
    assert "base_quantity" not in found.normalized_value
    assert "amount_per_base_unit" not in found.normalized_value


# --- read, but with the reservation stated ----------------------------------


def test_a_rate_with_no_keyword_is_emitted_uncertain(
    extractor, ocr_lines, image_ref
):
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["₹0.08 per g"]), USP
    )

    assert found is not None
    assert found.normalized_value["amount"] == "0.08"
    assert is_uncertain(found.normalized_value)
    assert any(
        "no unit-sale-price keyword" in reason
        for reason in found.normalized_value["uncertainty_reasons"]
    )
    assert found.normalized_value["matched_by"] == "pattern"


def test_two_different_rates_on_one_label_are_reported_not_resolved(
    extractor, ocr_lines, image_ref
):
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        ["UNIT SALE PRICE: Rs.2.91 per gram", "Unit Price: Rs.3.10 per gram"],
    )
    found = _field(fields, USP)

    assert [f.key for f in fields].count(USP) == 1
    assert is_uncertain(found.normalized_value)
    assert len(found.normalized_value["candidates"]) == 2


# --- not read at all --------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        # No currency and no keyword. This is the frozen set's `Z 0.08 perg`,
        # where OCR lost the rupee glyph: honestly missed, never guessed at.
        "0.08 per g",
        "Z 0.08 perg",
        # The nutrition panel is full of real rates and none is a price.
        "Nutritional Information per 100 g: Energy 450 kcal, Fat 20 g",
        "Protein 2.5 g per serving",
        "Energy per 100 g: 450 kcal",
        # A decimal comma this project refuses to resolve by guessing. Reading
        # `5 per g` off `Rs.12,5 per g` would be a confident wrong price.
        "UNIT SALE PRICE : Rs.12,5 per g",
        "Rs.12,5 per g",
        # Prose that happens to contain the words.
        "Sold by unit weight in select stores",
        # A pharmacopoeia marker, which is what USP means on a supplement.
        "Vitamin C USP 500 mg",
        "Ascorbic Acid USP",
    ],
)
def test_lines_that_must_not_produce_a_unit_sale_price(
    extractor, ocr_lines, image_ref, line
):
    """An extracted field makes `field_presence` PASS whether or not it is
    flagged uncertain, so a line that is not this declaration must produce no
    field at all rather than an uncertain one."""
    assert _field(_extract(extractor, ocr_lines, image_ref, [line]), USP) is None


@pytest.mark.parametrize(
    "line",
    [
        "Unit sale price: Rs.200 per 1 kg",
        "USP: Rs.200 per 1 kg",
    ],
)
def test_a_rate_written_with_an_explicit_one_is_a_known_miss(
    extractor, ocr_lines, image_ref, line
):
    """Recorded so nobody re-derives it as a bug.

    `NON_DECLARATION_CONTEXT` claims any line containing `per <digit>` before
    the unit-price detector is consulted, because that is the shape of the
    entire nutrition panel (`per 100 g`, `per 30 g serving`). `per 1 kg` is
    collateral. Loosening the guard to reach one unattested phrasing would let
    the nutrition panel back in, and a wrongly reported declaration is the more
    expensive failure.
    """
    assert _field(_extract(extractor, ocr_lines, image_ref, [line]), USP) is None


def test_an_unrecognised_unit_is_not_committed_to(
    extractor, ocr_lines, image_ref
):
    """`dozen` is not a unit of measure this vocabulary knows - and rule 13(4)
    prohibits it outright, which is the rules layer's business, not this one's."""
    fields = _extract(extractor, ocr_lines, image_ref, ["Unit Sale Price: Rs.5 per dozen"])
    found = _field(fields, USP)
    if found is not None:  # pragma: no cover - documents either outcome
        assert is_uncertain(found.normalized_value)
        assert "amount" not in found.normalized_value or "per_measure" not in (
            found.normalized_value
        )


# --- interaction with the retail sale price ---------------------------------


def test_a_unit_price_line_does_not_also_become_a_retail_price(
    extractor, ocr_lines, image_ref
):
    """One amount, one declaration.

    Before the guard in `_retail_sale_price`, `USP: Rs.0.93/g` produced both
    the unit sale price it is and a speculative retail sale price from the same
    digits - recording a package that declared only a unit price as having
    declared an MRP.
    """
    fields = _extract(extractor, ocr_lines, image_ref, ["USP: ₹0.93/g"])

    assert _field(fields, USP) is not None
    assert _field(fields, MRP) is None


def test_an_mrp_written_as_a_rate_is_still_a_retail_sale_price(
    extractor, ocr_lines, image_ref
):
    """The regression the guard above must not cause.

    `MRP Rs.200/kg` is one declaration. Dropping it would lose the single
    declaration this project can least afford to miss, so the MRP keyword still
    wins the line and no unit sale price is invented beside it.
    """
    fields = _extract(extractor, ocr_lines, image_ref, ["MRP Rs.200/kg"])

    mrp = _field(fields, MRP)
    assert mrp is not None
    assert mrp.normalized_value["amount"] == "200"
    assert _field(fields, USP) is None


def test_a_line_declaring_both_yields_both(extractor, ocr_lines, image_ref):
    fields = _extract(
        extractor, ocr_lines, image_ref, ["MRP Rs.250, USP Rs.0.93/g"]
    )

    assert _field(fields, MRP).normalized_value["amount"] == "250"
    assert _field(fields, USP).normalized_value["amount"] == "0.93"


# --- named but unread -------------------------------------------------------


def test_a_keyword_with_no_value_is_reported_unread_not_extracted(
    extractor, ocr_lines
):
    """The p003 case: the panel names the declaration and defers the value.

    `USP, #MFD. & @USE BEFORE: SEE BELOW.` is a label saying "this declaration
    is here, look elsewhere for it". No value exists to read, so no field is
    emitted - but "we saw it named" and "the package never declared it" are
    opposite findings and must not collapse into an empty tuple.
    """
    ocr = ocr_lines(["UNIT SALE PRICE :"])
    fields = ()
    unread = extractor.unread_declarations(ocr, fields)

    assert [item.key for item in unread] == [USP]
    assert unread[0].evidence_text == "UNIT SALE PRICE :"


def test_the_abbreviation_alone_is_never_reported_unread(extractor, ocr_lines):
    """`USP` on its own is as likely to be *United States Pharmacopeia*.

    An unread observation is a positive claim about what the label says, and
    sending a reviewer to look for a price on a vitamin label would be exactly
    the guessing this whole mechanism exists to stop.
    """
    ocr = ocr_lines(["Ascorbic Acid USP", "Vitamin C USP 500 mg"])

    assert extractor.unread_declarations(ocr, ()) == ()


def test_a_read_unit_price_is_not_also_reported_unread(extractor, ocr_lines):
    ocr = ocr_lines(["UNIT SALE PRICE : Rs.2.91 PER GRAM"])
    fields = extractor.extract(ocr, None)

    assert extractor.unread_declarations(ocr, fields) == ()


def test_the_anchor_is_a_subset_of_the_keyword():
    """The two must not drift into disagreeing about what the keyword is."""
    for text in [
        "UNIT SALE PRICE",
        "unit sale price",
        "Unit Price",
        "unitprice",
    ]:
        if P.UNIT_SALE_PRICE_ANCHOR.search(text):
            assert P.UNIT_SALE_PRICE_KEYWORD.search(text)

    # And the abbreviation is in the keyword but deliberately not the anchor.
    assert P.UNIT_SALE_PRICE_KEYWORD.search("USP")
    assert not P.UNIT_SALE_PRICE_ANCHOR.search("USP")


# --- photograph conditions, as text ----------------------------------------


@pytest.mark.parametrize(
    ("line", "reads"),
    [
        # A clean declaration panel.
        ("UNIT SALE PRICE : ₹2.91 PER GRAM", True),
        # Small print run together, as a 6-point line comes back.
        ("UNITSALEPRICE:₹2.91PERGRAM", False),
        # A tilted line: OCR keeps the words and mangles the separators.
        ("UNIT SALE PRICE ; ₹ 2.91 PER GRAM", True),
        # Low light: characters lost from the end of the line.
        ("UNIT SALE PRICE : ₹2.9", False),
        # A partial crop that removes the value.
        ("UNIT SALE PRI", False),
        # Glare eating the currency glyph but not the digits.
        ("UNIT SALE PRICE : 2.91 PER GRAM", True),
        # A competing region merged onto the line by the segmenter.
        ("BATCH 2546 UNIT SALE PRICE : ₹2.91 PER GRAM MFG 12/24", True),
        # Pure OCR noise around the declaration.
        ("|| UNIT SALE PRICE : ₹2.91 PER GRAM ~~", True),
    ],
)
def test_degraded_readings_are_either_read_or_declined_never_guessed(
    extractor, ocr_lines, image_ref, line, reads
):
    """Each of these is a real photograph condition, expressed as the text OCR
    returns for it. The assertion is on the *outcome class*, never on accuracy:
    a degraded line is read correctly or produces nothing, and never produces a
    value the line does not contain."""
    found = _field(_extract(extractor, ocr_lines, image_ref, [line]), USP)

    if reads:
        assert found is not None
        assert found.normalized_value["amount"] == "2.91"
    else:
        assert found is None or not found.normalized_value.get("amount")


def test_a_devanagari_line_beside_an_english_one_does_not_break_the_reading(
    extractor, ocr_lines, image_ref
):
    """English-only patterns, stated plainly: the Devanagari is recognised text
    that no pattern here matches, and it must not disturb the line that is
    matched. This asserts nothing about reading Hindi."""
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        [
            "इकाई विक्रय मूल्य",
            "UNIT SALE PRICE : ₹2.91 PER GRAM",
        ],
    )
    assert _field(fields, USP).normalized_value["amount"] == "2.91"


# --- malformed and hostile input --------------------------------------------


def test_no_recognised_text_produces_nothing(extractor, image_ref):
    assert extractor.extract(OcrResult(), image_ref) == ()


def test_a_pathological_line_is_bounded_and_produces_nothing(
    extractor, ocr_lines, image_ref
):
    """A long run of separators is the shape a shredded OCR line takes. It must
    return quickly and claim nothing rather than backtrack indefinitely."""
    fields = _extract(
        extractor, ocr_lines, image_ref, ["₹" + "1/" * 4000 + " per g"]
    )
    found = _field(fields, USP)
    assert found is None or found.normalized_value.get("per_unit") == "g"


def test_unexpected_unicode_is_folded_not_repaired(
    extractor, ocr_lines, image_ref
):
    """Full-width digits are a presentation variant, so NFKC folds them. Nothing
    here repairs an OCR confusion - that would turn an unreliable reading into a
    confident wrong one."""
    found = _field(
        _extract(
            extractor,
            ocr_lines,
            image_ref,
            ["UNIT SALE PRICE : ₹２．９１ PER GRAM"],
        ),
        USP,
    )
    assert found is not None
    assert found.normalized_value["amount"] == "2.91"


def test_a_block_carrying_no_confidence_leaves_it_absent(
    extractor, ocr_lines, image_ref
):
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        ["UNIT SALE PRICE : Rs.2.91 PER GRAM"],
        confidence=None,
    )
    assert _field(fields, USP).confidence is None


def test_geometry_survives_the_trip_from_block_to_field(
    extractor, ocr_lines, image_ref
):
    found = _field(
        _extract(
            extractor, ocr_lines, image_ref, ["UNIT SALE PRICE : Rs.2.91 PER GRAM"]
        ),
        USP,
    )
    assert found.box is not None
    assert found.raw_value == "UNIT SALE PRICE : Rs.2.91 PER GRAM"


def test_a_block_with_no_box_still_yields_a_field(extractor, image_ref):
    ocr = OcrResult(
        blocks=(TextBlock(text="UNIT SALE PRICE : Rs.2.91 PER GRAM", box=None),)
    )
    found = _field(extractor.extract(ocr, image_ref), USP)
    assert found is not None
    assert found.box is None
