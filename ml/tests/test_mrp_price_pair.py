"""The combined MRP/USP price pair, and the OCR-degraded legend that hid it.

The regression
--------------
The Plix "Acne Fighter" tablet tube prints its retail and unit sale prices as
one sticker. The classifier's seed dataset transcribes it as::

    MRP ₹ (Incl. of all taxes) / USP (Per Tablet) ₹: 350.00/23.33

A 2D composite of that declaration face was recognised as::

    NSP oertatiey, —-:350.00/23.33

and no retail sale price was extracted, so rule 6(1)(e)'s presence check
reported the MRP missing from a label that visibly prints it. The line reads
most naturally as the `USP (Per Tablet) ₹:` half of the legend - `U` read as
`N`, `(Per Tablet)` as `oertatiey,`, `₹` as `—-` - with the pair after it. The
`MRP` half was not on the line. Even a *perfect* recognition of that half-line
produced nothing: a line naming only a unit sale price was skipped by the MRP
detector, and the unit-price detector cannot read `/23.33` because no unit
follows it.

Where the inputs come from
--------------------------
- `NSP oertatiey, —-:350.00/23.33` is the recognised text reported for the
  composite. The image is not in this repository.
- Lines quoted from the "transcription" are the seed dataset's
  `manual_transcription` of the same face, which was typed by a model and is
  flagged there as unverified.
- Lines marked *constructed* are not readings of anything. Each exists to
  probe one guard, and says which.

Nothing here makes a legal claim, and nothing asserts the package complies.
"""

from decimal import Decimal

import pytest

from labelextract.contracts import LabelFieldKey
from labelextract.fields import RuleBasedFieldExtractor
from labelextract.fields import patterns as P
from labelextract.fields.normalisation import is_uncertain
from labelextract.fields.rule_based import MATCHED_BY_KEYWORD, MATCHED_BY_PATTERN

MRP = LabelFieldKey.RETAIL_SALE_PRICE
USP = LabelFieldKey.UNIT_SALE_PRICE

#: The regression reading, character for character.
DEGRADED_STICKER = "NSP oertatiey, —-:350.00/23.33"

#: The same sticker, as the seed dataset transcribes it.
TRANSCRIBED_STICKER = "MRP ₹ (Incl. of all taxes) / USP (Per Tablet) ₹: 350.00/23.33"

#: The nutrition table from the transcription of the same face - the numbers a
#: loose price rule would reach for first (`400`, `15`, `4.2`, `135.53`).
NUTRITION_TABLE = [
    "Nutritional Information (Approx Values)",
    "Serving Size-1 Tablet (4.2g), Servings Per Container-15",
    "Nutrients Per serving (4.2g tablet) %RDA",
    "Energy 3.061Kcal 0.15",
    "Protein 0.03g 0.06",
    "Sodium 135.53mg 6.77",
    "Potassium 389.74mg 11.13",
    "Curcuma longa (Curcuminoids - 25%) 400mg **",
    "Aloe Vera Extract (Aloe barbadensis miller) 300mg **",
    "Vitamin C (L-Ascorbic Acid) 32.5mg 50",
    "Zinc (Zinc Sulphate) 6.6mg 50",
]


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


def _unread_keys(extractor, ocr_lines, image_ref, lines):
    ocr = ocr_lines(lines)
    return {
        item.key
        for item in extractor.unread_declarations(ocr, extractor.extract(ocr, image_ref))
    }


# --- A. the regression -------------------------------------------------------


def test_the_ocr_degraded_sticker_yields_the_retail_sale_price(
    extractor, ocr_lines, image_ref
):
    found = _field(_extract(extractor, ocr_lines, image_ref, [DEGRADED_STICKER]), MRP)

    assert found is not None, "the pair is on the line and the MRP was not read"
    assert found.normalized_value["amount"] == "350.00"
    assert found.normalized_value["currency"] == "INR"


def test_the_second_amount_of_the_pair_is_never_the_retail_sale_price(
    extractor, ocr_lines, image_ref
):
    """`23.33` is the price per tablet. It is not the MRP, and it is not
    recorded as a unit sale price either: no unit was read beside it."""
    fields = _extract(extractor, ocr_lines, image_ref, [DEGRADED_STICKER])

    assert _field(fields, MRP).normalized_value["amount"] != "23.33"
    assert "23.33" not in (_field(fields, MRP).normalized_value.get("candidates") or [])
    assert _field(fields, USP) is None


def test_the_degraded_reading_is_reported_uncertain_and_says_why(
    extractor, ocr_lines, image_ref
):
    """No MRP keyword was recognised, so the reading is a pattern match.

    That is what the field says, and how it ranks: a pattern-matched, uncertain
    candidate loses to any keyword-anchored one elsewhere on the label.
    """
    found = _field(_extract(extractor, ocr_lines, image_ref, [DEGRADED_STICKER]), MRP)

    assert is_uncertain(found.normalized_value) is True
    assert found.normalized_value["matched_by"] == MATCHED_BY_PATTERN
    assert any(
        "combined MRP/USP price pair" in reason
        for reason in found.normalized_value["uncertainty_reasons"]
    )


def test_the_evidence_is_the_line_exactly_as_recognised(
    extractor, ocr_lines, image_ref
):
    """The corruption is the evidence a reviewer needs, so it is kept verbatim,
    with the box and the engine's own confidence."""
    found = _field(
        _extract(extractor, ocr_lines, image_ref, [DEGRADED_STICKER], confidence=0.61),
        MRP,
    )

    assert found.raw_value == DEGRADED_STICKER
    assert found.confidence == 0.61
    assert found.box is not None and found.box.width > 0


def test_a_perfect_reading_of_the_same_half_line_gives_the_same_answer(
    extractor, ocr_lines, image_ref
):
    """The defect was not only the corruption: the clean half-line read nothing."""
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["USP (Per Tablet) ₹: 350.00/23.33"]),
        MRP,
    )

    assert found.normalized_value["amount"] == "350.00"
    assert is_uncertain(found.normalized_value) is True


def test_the_nutrition_table_beside_the_sticker_does_not_compete(
    extractor, ocr_lines, image_ref
):
    """The transcription's nutrition table above the regression line.

    One retail sale price comes out, it is the sticker's, and no number from the
    table is listed as a competing reading.
    """
    fields = _extract(
        extractor, ocr_lines, image_ref, [*NUTRITION_TABLE, DEGRADED_STICKER]
    )
    found = _field(fields, MRP)

    assert found.normalized_value["amount"] == "350.00"
    assert "candidates" not in found.normalized_value
    assert found.raw_value == DEGRADED_STICKER


# --- B. an MRP keyword on the line is unaffected -----------------------------


@pytest.mark.parametrize(
    "line",
    [
        "MRP ₹ 350.00",
        "MRP ₹ 350.00/23.33",
        TRANSCRIBED_STICKER,
        # Constructed: the abbreviations joined, no currency glyph read.
        "MRP/USP: 350.00/23.33",
        # Constructed: the dotted form with a written-out currency.
        "M.R.P. Rs. 350.00/23.33",
    ],
)
def test_a_keyword_anchored_mrp_is_committed_to_and_takes_the_first_amount(
    extractor, ocr_lines, image_ref, line
):
    found = _field(_extract(extractor, ocr_lines, image_ref, [line]), MRP)

    assert Decimal(found.normalized_value["amount"]) == Decimal("350")
    assert is_uncertain(found.normalized_value) is False
    assert found.normalized_value["matched_by"] == MATCHED_BY_KEYWORD


def test_a_keyword_reading_elsewhere_outranks_the_pair_and_agreement_is_not_conflict(
    extractor, ocr_lines, image_ref
):
    """Constructed: the same price printed once with its keyword, once as a pair."""
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["MRP ₹ 350.00", DEGRADED_STICKER]),
        MRP,
    )

    assert found.raw_value == "MRP ₹ 350.00"
    assert is_uncertain(found.normalized_value) is False


def test_a_keyword_reading_that_disagrees_with_the_pair_is_reported_not_resolved(
    extractor, ocr_lines, image_ref
):
    """Constructed. The keyword reading wins the ranking; the disagreement is
    listed, and the field is flagged, rather than either value being dropped."""
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["MRP Rs. 399.00", DEGRADED_STICKER]),
        MRP,
    )

    assert found.normalized_value["amount"] == "399.00"
    assert is_uncertain(found.normalized_value) is True
    assert set(found.normalized_value["candidates"]) == {"399.00", "350.00"}


# --- C. OCR variation the pair tolerates, and where it stops -----------------


def test_the_wrapped_sticker_reads_the_pair_but_not_the_tax_words_above_it(
    extractor, ocr_lines, image_ref
):
    """Constructed from the transcription wrapped at its `/`, with the degraded
    second line.

    The price is read from the line that carries it. `(Incl. of all taxes)` is
    on the line above, and adjacency is a layout guess this extractor does not
    make - so `inclusive_of_all_taxes` stays absent, meaning "not observed".
    """
    lines = ["MRP ₹ (Incl. of all taxes) /", DEGRADED_STICKER]
    found = _field(_extract(extractor, ocr_lines, image_ref, lines), MRP)

    assert found.normalized_value["amount"] == "350.00"
    assert "inclusive_of_all_taxes" not in found.normalized_value
    assert MRP not in _unread_keys(extractor, ocr_lines, image_ref, lines)


@pytest.mark.parametrize("legend", ["NSP", "USP", "usp", "NRP", "MKP"])
def test_a_price_legend_misread_by_one_letter_still_introduces_the_pair(
    extractor, ocr_lines, image_ref, legend
):
    """Constructed. `USP` in any case is the unit-sale-price keyword itself."""
    found = _field(
        _extract(extractor, ocr_lines, image_ref, [f"{legend} : 350.00/23.33"]), MRP
    )

    assert found.normalized_value["amount"] == "350.00"
    assert is_uncertain(found.normalized_value) is True


def test_the_indian_price_suffix_after_the_pair_does_not_cost_it(
    extractor, ocr_lines, image_ref
):
    """Constructed: `/-` closes a price on Indian packaging; it is not a third
    amount."""
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["USP ₹ 350.00/23.33/-"]), MRP
    )

    assert found.normalized_value["amount"] == "350.00"


# --- D. nutrition text produces no MRP ---------------------------------------


def test_the_nutrition_table_alone_produces_no_price(extractor, ocr_lines, image_ref):
    fields = _extract(extractor, ocr_lines, image_ref, NUTRITION_TABLE)

    assert _field(fields, MRP) is None
    assert _field(fields, USP) is None


@pytest.mark.parametrize(
    "line",
    [
        # Recognised text off `p002_03_left`, the same product photographed.
        "nuff ifn tablet (4.20), Servings Bar 6",
        "cont Per serving (4.29 -",
        # Constructed: a legend-shaped token and a pair, on a nutrition line.
        "NSP Energy (kcal) 350.00/23.33",
        "USP per serving 12.50/25.00",
    ],
)
def test_a_nutrition_line_is_refused_even_with_a_legend_and_a_pair(
    extractor, ocr_lines, image_ref, line
):
    fields = _extract(extractor, ocr_lines, image_ref, [line])

    assert _field(fields, MRP) is None


# --- E. a price-shaped number without price context is not an MRP -----------


@pytest.mark.parametrize(
    ("line", "guard"),
    [
        ("350.00/23.33", "a pair with no legend before it"),
        ("350.00", "a bare amount"),
        ("NSP 350.00", "a garbled legend beside one amount, not a pair"),
        ("NSP: 350.00", "a garbled legend beside one amount, not a pair"),
        ("NSP 350/23", "a pair not printed to the paisa"),
        ("350.00/23.33 NSP", "a legend after the pair rather than introducing it"),
        ("nsp 350.00/23.33", "a lowercase token is not a legend misreading"),
        ("MFD/EXP 09.24/08.26", "a date-shaped pair under date keywords"),
        ("USE BY 09.24/08.26", "`USE` is not `USP` with its `P` kept"),
        ("NSP 12.00/350.00/23.33", "a chain of three is not a pair"),
        ("USP 35.00/100.00 g", "an amount against a quantity is a rate"),
        # Transcription: the sticker's neighbours.
        ("Batch No.: N668", "a batch code"),
        ("Exp. Date: 08/2026", "a date"),
        ("NET QUANTITY: 15N TABLETS", "a net quantity"),
    ],
)
def test_price_shaped_text_without_an_mrp_context_is_not_an_mrp(
    extractor, ocr_lines, image_ref, line, guard
):
    fields = _extract(extractor, ocr_lines, image_ref, [line])

    assert _field(fields, MRP) is None, guard


def test_the_misread_legend_is_not_an_mrp_keyword_on_its_own(
    extractor, ocr_lines, image_ref
):
    """`NSP` alone is not reported as an MRP named-but-unread either.

    An unread observation is a positive claim that the label names the
    declaration, and three garbled letters do not support one.
    """
    assert MRP not in _unread_keys(extractor, ocr_lines, image_ref, ["NSP"])
    assert P.MRP_KEYWORD.search(DEGRADED_STICKER) is None


@pytest.mark.parametrize("token", ["USE", "USA", "MRS", "Mrs", "MAPS", "WASP", "nsp"])
def test_words_that_merely_resemble_a_legend_are_not_one(token):
    assert P.PRICE_LEGEND_MISREAD.search(token) is None


@pytest.mark.parametrize("token", ["MRP", "USP", "NSP", "NRP", "MKP", "UBP"])
def test_the_legend_abbreviations_with_one_letter_misread_are_recognised(token):
    assert P.PRICE_LEGEND_MISREAD.search(token) is not None
