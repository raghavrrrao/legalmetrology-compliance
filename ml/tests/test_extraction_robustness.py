"""Regression tests for the failures found by the real-world baseline.

Every test here corresponds to a specific reading the pipeline got wrong on a
photograph of an actual packaged commodity. The evidence lines are quoted from
the OCR output that run produced - not retyped from the packages - so each test
pins the exact text that broke it.

The photographs themselves are local evaluation data and are deliberately not
in this repository. What is committed is the *recognised text* those images
produced, which is what the extraction layer actually consumes and all a
regression test needs.

The bar these tests defend, in one line: **for a Legal Metrology record, a
fabricated value is worse than a missing one.** Several tests below assert that
the extractor produces nothing, and they are the important ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from labelextract.contracts import (
    ImageRef,
    LabelFieldKey,
    OcrResult,
    TextBlock,
)
from labelextract.fields import RuleBasedFieldExtractor, is_uncertain


@pytest.fixture
def extract():
    """Run the real extractor over lines of recognised text."""
    extractor = RuleBasedFieldExtractor()
    image = ImageRef(
        path=Path("label.jpg"),
        image_format="jpeg",
        size_bytes=1024,
        width=1080,
        height=1440,
    )

    def _extract(*lines: str) -> dict[LabelFieldKey, dict]:
        ocr = OcrResult(
            blocks=tuple(
                TextBlock(text=line, box=None, confidence=0.9) for line in lines
            ),
            raw={},
        )
        return {
            field.key: field.normalized_value or {}
            for field in extractor.extract(ocr, image)
        }

    return _extract


@pytest.fixture
def unread():
    """Declarations the extractor reports as named-but-unread."""
    extractor = RuleBasedFieldExtractor()
    image = ImageRef(
        path=Path("label.jpg"),
        image_format="jpeg",
        size_bytes=1024,
        width=1080,
        height=1440,
    )

    def _unread(*lines: str) -> set[LabelFieldKey]:
        ocr = OcrResult(
            blocks=tuple(
                TextBlock(text=line, box=None, confidence=0.9) for line in lines
            ),
            raw={},
        )
        fields = extractor.extract(ocr, image)
        return {item.key for item in extractor.unread_declarations(ocr, fields)}

    return _unread


# --- batch number: the highest-risk defect found ----------------------------


def test_blank_batch_declaration_produces_no_batch_number(extract):
    """`Batch No.` with the value left blank must not become `"No"`.

    The original failure, from a namkeen pack whose batch field is printed and
    genuinely empty. `BATCH_NUMBER`'s optional `(?:no\\.?|...)` group backtracks
    and the value group takes the keyword's own suffix, so the extractor
    emitted `batch_number = "No"` with `uncertain: false`.

    `field_presence` PASSES on any extracted field regardless of its
    uncertainty flag, so this recorded a package that declared no batch number
    as having declared one - turning a real violation into a pass. That is the
    single most damaging thing this layer can do.
    """
    assert LabelFieldKey.BATCH_NUMBER not in extract("Batch No.")


def test_blank_batch_declaration_is_reported_as_unread(unread):
    """Producing no field is right; producing no *signal* is not.

    "The package declares no batch number" and "the batch number is printed and
    we could not read it" are opposite findings, and the second is a retake,
    not a violation.
    """
    assert LabelFieldKey.BATCH_NUMBER in unread("Batch No. :")


def test_batch_keyword_in_a_cross_reference_yields_no_value(extract):
    """A line saying *where* a declaration is printed declares nothing.

    Four supermarket packs carry this sentence. Reading a value out of it
    produced `batch_number = "No"` on two of them.
    """
    fields = extract(
        "See Above Panel for Date of Packaging,",
        "MRP Rs. (incl. of all taxes), Batch No. & Use By Date",
    )
    assert LabelFieldKey.BATCH_NUMBER not in fields


def test_cross_reference_still_reports_the_declaration_as_unread(unread):
    """The cross-reference names the declarations, so they are unread, not absent."""
    reported = unread("MRP Rs. (incl. of all taxes), Batch No. & Use By Date")
    assert LabelFieldKey.BATCH_NUMBER in reported
    assert LabelFieldKey.RETAIL_SALE_PRICE in reported


def test_ocr_damaged_batch_keyword_yields_no_value(extract):
    """`Batch Ni` is damaged label text, not a batch code.

    From an icing-sugar pack: OCR rendered the cross-reference sentence as
    `PRs. (inc, of al laxes), Batch Ni`, and the extractor emitted
    `batch_number = "Ni"` as certain. No stopword list catches `Ni`; requiring
    a digit does.
    """
    assert LabelFieldKey.BATCH_NUMBER not in extract(
        "PRs. (inc, of al laxes), Batch Ni"
    )


@pytest.mark.parametrize(
    "line, expected",
    [
        ("Batch No.: N668", "N668"),
        ("Batch No. 2546", "2546"),
        ("LOT NO: PKM26F154", "PKM26F154"),
        ("Batch No.: K BL28I50075", "K BL28I50075"),
        ("B.No. L-2456", "L-2456"),
        ("Batch Code: AB12/C3", "AB12/C3"),
    ],
)
def test_real_batch_formats_are_still_extracted(extract, line, expected):
    """The guards must not cost legitimate batch numbers.

    Every value here is a real format, four of them read off the packs in the
    evaluation set. This is the test that fails if the fix is over-tightened.
    """
    fields = extract(line)
    assert fields[LabelFieldKey.BATCH_NUMBER]["batch_number"] == expected


def test_batch_value_does_not_swallow_following_label_text(extract):
    """Allowing a two-token value must not let it run into the next declaration."""
    fields = extract("Batch No: A123 Use By 01/26")
    assert fields[LabelFieldKey.BATCH_NUMBER]["batch_number"] == "A123"


def test_batch_code_beginning_with_a_stopword_is_not_rejected(extract):
    """Stopwords are matched as whole tokens, not as prefixes.

    `NOVA-12` starts with the letters of `no` and is a perfectly good batch
    code. Rejecting it would be over-correction.
    """
    fields = extract("Batch No.: NOVA-12")
    assert fields[LabelFieldKey.BATCH_NUMBER]["batch_number"] == "NOVA-12"


# --- net quantity -----------------------------------------------------------


def test_multipack_is_not_reduced_to_a_unit_count(extract):
    """`4 UNITS X 125 g + 125 g FREE` must not become `4 units`.

    The original failure, from the best-recognised image in the whole
    evaluation set - so this is an extraction defect, not an OCR one. The old
    code took `QUANTITY.search`'s *first* match and committed to it, recording
    a 625 g carton as a count of four with no mass anywhere in the output and
    `uncertain: false`.
    """
    quantity = extract(
        "p NET CONTENTS WHEN PACKED 4 UNITS X 125 9 + 125 g FREE?"
    )[LabelFieldKey.NET_QUANTITY]

    assert quantity.get("measure") != "count"
    assert quantity.get("quantity") != 4
    # A bonus quantity makes the declared total genuinely ambiguous, so no
    # value is committed to at all.
    assert quantity.get("base_quantity") is None
    assert is_uncertain(quantity)


def test_bonus_quantity_withholds_a_value_and_lists_what_was_printed(extract):
    """`500 g + 50 g free` may declare 500 g or 550 g. Neither is guessed."""
    quantity = extract("Net Qty: 500 g + 50 g free")[LabelFieldKey.NET_QUANTITY]

    assert quantity.get("base_quantity") is None
    assert is_uncertain(quantity)
    assert quantity["candidates"] == ["500 g", "50 g"]


def test_multipack_without_a_bonus_is_read_as_a_total(extract):
    """`4 units x 125 g` is unambiguous, so it is committed to.

    The fix must not turn every multipack into an uncertain reading - only the
    ones a bonus quantity makes genuinely ambiguous.
    """
    quantity = extract("Net Contents: 4 units x 125 g")[LabelFieldKey.NET_QUANTITY]

    assert quantity["pack_count"] == 4
    assert quantity["base_quantity"] == 500
    assert quantity["base_unit"] == "g"
    assert not is_uncertain(quantity)


def test_a_measurable_quantity_beats_a_bare_count_on_the_same_line(extract):
    """Where a line declares both, the mass is the net quantity."""
    quantity = extract("Net Quantity: 10 N 250 g")[LabelFieldKey.NET_QUANTITY]
    assert quantity["measure"] == "mass"
    assert quantity["base_quantity"] == 250


@pytest.mark.parametrize(
    "line, base_quantity, base_unit",
    [
        ("NET QUANTITY : 120 GRAMS (125 mt) sc", 120, "g"),
        ("Net Weight : 500g", 500, "g"),
        ("Net Qty: 1 kg", 1000, "g"),
        ("Net Contents 500 ml.", 500, "ml"),
        ("Net Qty: 6 x 100 g", 600, "g"),
    ],
)
def test_valid_quantity_formats_are_preserved(
    extract, line, base_quantity, base_unit
):
    """Reading the whole line must not change what a single-quantity line means."""
    quantity = extract(line)[LabelFieldKey.NET_QUANTITY]
    assert quantity["base_quantity"] == base_quantity
    assert quantity["base_unit"] == base_unit
    assert not is_uncertain(quantity)


def test_a_count_only_declaration_is_still_read(extract):
    """`15N TABLETS` has no mass, and that absence is the correct answer."""
    quantity = extract("NET QUANTITY: 15N TABLETS")[LabelFieldKey.NET_QUANTITY]
    assert quantity["measure"] == "count"
    assert quantity["quantity"] == 15


def test_nutrition_panel_quantities_are_still_suppressed(extract):
    """The precision guard that was already working must keep working."""
    assert LabelFieldKey.NET_QUANTITY not in extract(
        "Nutritional Information per 100 g", "Energy 310 kcal Protein 9 g"
    )


# --- OCR-corrupted keywords -------------------------------------------------


def test_stray_glyph_inside_a_keyword_does_not_lose_the_date(extract):
    """`Use @ By: 26/01/26` - the date was perfect, the keyword had one bad glyph.

    From an icing-sugar pack. A single spurious `@` between "Use" and "By" cost
    a fully recognised expiry date.
    """
    best_before = extract("Use @ By: 26/01/26")[LabelFieldKey.BEST_BEFORE]
    assert best_before["date"] == "2026-01-26"


def test_worded_shelf_life_is_read(extract):
    """`BEST BEFORE TWO MONTHS AFTER PACKING`, recognised exactly and discarded."""
    best_before = extract("BEST BEFORE TWO MONTHS AFTER PACK")[
        LabelFieldKey.BEST_BEFORE
    ]
    assert best_before["duration_value"] == 2
    assert best_before["duration_unit"] == "months"


def test_keyword_tolerance_does_not_match_a_missing_word(extract):
    """The tolerance is for stray glyphs, not for absent or misspelled words.

    `ie By` is what OCR made of "Use By" on one pack by losing two characters.
    Matching it would mean matching a bare `by`, which collides with "Marketed
    by" and "Packed by" and would invent declarations that were never printed.
    Not recovering this is the correct trade, and this test pins it.
    """
    assert LabelFieldKey.BEST_BEFORE not in extract("ie By: 30/09/25")


def test_marketed_by_is_not_read_as_a_best_before_date(extract):
    """The direct false positive the previous test guards against."""
    assert LabelFieldKey.BEST_BEFORE not in extract(
        "Marketed by AVENUE SUPERMARTS LTD. 12/2025"
    )


# --- consumer care ----------------------------------------------------------


def test_four_group_toll_free_number_is_read(extract):
    """`1800-10-22-221` was recognised perfectly and matched by nothing."""
    contact = extract(
        "LEVERCARE-QUERY / FEEDBACK, TOLL FREE: 1800-10-22-221,"
    )[LabelFieldKey.CONSUMER_CARE_CONTACT]
    assert contact["phones"] == ["1800-10-22-221"]


def test_landline_with_std_code_is_read(extract):
    """`022-71230555` was recognised exactly; no landline pattern existed."""
    contact = extract("Consumer Care, Phone No.: 022-71230555")[
        LabelFieldKey.CONSUMER_CARE_CONTACT
    ]
    assert contact["phones"] == ["022-71230555"]


def test_a_reading_with_a_value_outranks_a_bare_keyword(extract):
    """"We saw the word 'contact'" is not a better reading than the number."""
    contact = extract(
        "For Feedback/Suggestions, Please Contact",
        "Consumer Care Phone No.: 022-71230555",
    )[LabelFieldKey.CONSUMER_CARE_CONTACT]
    assert contact["phones"] == ["022-71230555"]


def test_a_licence_number_is_not_read_as_a_phone_number(extract):
    """A false positive introduced by adding landline support, and removed again.

    A licence number and a landline are both long digit runs printed after a
    `No.`. On the first retest, the OCR line `m Lic No (0721999000621` was
    reported as a consumer-care phone. Two guards now prevent it: the landline
    pattern requires a separator between STD code and subscriber number, and
    phone patterns are not applied to a line carrying a licence keyword.
    """
    fields = extract("m Lic No (0721999000621")
    contact = fields.get(LabelFieldKey.CONSUMER_CARE_CONTACT, {})
    assert contact.get("phones") is None


def test_an_unbroken_digit_run_is_not_a_landline(extract):
    """Barcodes and batch codes are digit runs too."""
    fields = extract("Consumer Care 08903363011237")
    contact = fields.get(LabelFieldKey.CONSUMER_CARE_CONTACT, {})
    assert contact.get("phones") is None


def test_mobile_numbers_are_still_read(extract):
    """The pattern that already worked must keep working."""
    contact = extract("WHATSAPP / CUSTOMER CARE : 8867162337")[
        LabelFieldKey.CONSUMER_CARE_CONTACT
    ]
    assert contact["phones"] == ["8867162337"]


# --- FSSAI licence ----------------------------------------------------------


def test_fssai_licence_is_extracted(extract):
    """A mandatory declaration that was being read well and discarded."""
    licence = extract("FSSAI Lic. No. 11523084000466")[LabelFieldKey.FSSAI_LICENCE]
    assert licence["licence_number"] == "11523084000466"
    assert not is_uncertain(licence)


def test_truncated_fssai_licence_is_uncertain_not_silently_accepted(extract):
    """13 digits is an incomplete reading, and a reviewer needs to see it.

    OCR truncated the licence number on two packs. A 13-digit licence recorded
    as correct would be a defect in a compliance record; recording nothing at
    all would hide that the declaration was there.
    """
    licence = extract("fssai LIC. No. 1152299800056")[LabelFieldKey.FSSAI_LICENCE]
    assert is_uncertain(licence)
    assert licence["licence_number"] == "1152299800056"
    assert licence["digit_count"] == 13


def test_fssai_digits_are_never_invented_to_reach_fourteen(extract):
    """Nothing is repaired - the digits read are the digits reported."""
    licence = extract("FSSAI Lic No. 1152308400046")[LabelFieldKey.FSSAI_LICENCE]
    assert licence["licence_number"] == "1152308400046"


def test_fssai_keyword_without_digits_is_reported_unread(unread):
    assert LabelFieldKey.FSSAI_LICENCE in unread("fssai")


# --- validation -------------------------------------------------------------


def test_implausible_price_is_withdrawn_rather_than_recorded(extract):
    """A run-together price is not a declaration."""
    price = extract("MRP Rs. 99999999 (incl. of all taxes)")[
        LabelFieldKey.RETAIL_SALE_PRICE
    ]
    assert price.get("amount") is None
    assert is_uncertain(price)


def test_ordinary_prices_are_unaffected(extract):
    price = extract("MRP = 40.00")[LabelFieldKey.RETAIL_SALE_PRICE]
    assert price["amount"] == "40.00"
    assert not is_uncertain(price)


# --- number truncation ------------------------------------------------------
#
# Found by writing the implausible-price test above, not by the baseline: the
# ten-product set happens to contain no price of four or more digits written
# without a comma, so nothing exercised it.


@pytest.mark.parametrize(
    "line, expected",
    [
        ("MRP Rs. 1500", "1500"),
        ("MRP Rs. 2499", "2499"),
        ("MRP Rs. 1,500", "1500"),
        ("M.R.P. Rs 12500.50", "12500.50"),
        ("MRP Rs. 349.00", "349.00"),
        ("MRP Rs. 1,00,000", "100000"),
    ],
)
def test_prices_are_not_truncated_to_three_digits(extract, line, expected):
    """`Rs. 1500` must not be read as `150`.

    `_NUMBER`'s first branch was `\\d{1,3}(?:,\\d{2,3})*`, whose comma group
    could match zero times - so it matched any three-digit run. Python
    alternation is leftmost-first rather than longest-match, so an ungrouped
    number never reached the branch that would have taken all of its digits,
    and the remaining digits were silently dropped:

        MRP Rs. 1500  ->  amount 150

    A tenfold understatement of the most legally significant number on the
    package, emitted with `uncertain: false`. Indian packs usually print a
    four-digit price without a comma, so this was reachable on real labels.
    """
    price = extract(line)[LabelFieldKey.RETAIL_SALE_PRICE]
    assert price["amount"] == expected


@pytest.mark.parametrize(
    "line, base_quantity",
    [
        ("Net Qty: 1500 g", 1500),
        ("Net Weight: 2500 g", 2500),
        ("Net Qty: 1,500 g", 1500),
    ],
)
def test_quantities_are_not_truncated_to_three_digits(
    extract, line, base_quantity
):
    """The same truncation reached net quantity: `1500 g` was read as `150 g`."""
    quantity = extract(line)[LabelFieldKey.NET_QUANTITY]
    assert quantity["base_quantity"] == base_quantity


def test_a_name_that_is_only_punctuation_is_withdrawn(extract):
    """`Manufactured by: #` recorded `#` as the manufacturer's name."""
    fields = extract("Manufactured by: #")
    name = fields.get(LabelFieldKey.MANUFACTURER_NAME, {})
    assert name.get("name") is None


def test_a_name_that_is_only_label_vocabulary_is_withdrawn(extract):
    """`Marketed By Address` yielded a marketer called "Address"."""
    fields = extract("I ae Exee.ve Al Marketed By Address")
    assert fields.get(LabelFieldKey.OTHER, {}).get("name") is None


def test_real_company_names_are_still_extracted(extract):
    """The validation must not cost legitimate names."""
    name = extract("MFG. BY LAKME LEVER PVT. LTD., (UNIT-II), SURVEY No. 159/B,")[
        LabelFieldKey.MANUFACTURER_NAME
    ]
    assert name["name"].startswith("LAKME LEVER PVT. LTD.")


def test_a_date_with_an_impossible_year_is_withdrawn(extract):
    """A year outside the printable range means a digit was misread."""
    packed = extract("Pkd: 30/01/1026")[LabelFieldKey.DATE_OF_PACKING]
    assert packed.get("date") is None
    assert is_uncertain(packed)


def test_ordinary_dates_are_unaffected(extract):
    fields = extract("Pkd: 30/01/26", "Use By: 30/04/26")
    assert fields[LabelFieldKey.DATE_OF_PACKING]["date"] == "2026-01-30"
    assert fields[LabelFieldKey.BEST_BEFORE]["date"] == "2026-04-30"


# --- the guarantee the whole change exists to provide ------------------------


@pytest.mark.parametrize(
    "line",
    [
        "Batch No.",
        "Batch No. :",
        "Batch Number:",
        "Lot No.",
        "MRP Rs. (incl. of all taxes), Batch No. & Use By Date",
        "PRs. (inc, of al laxes), Batch Ni",
        "Batch No. & Use By Date",
    ],
)
def test_no_declaration_keyword_is_ever_emitted_as_a_batch_value(extract, line):
    """The invariant, stated once over every phrasing that broke it.

    If this fails, a package is being recorded as declaring a batch number it
    does not declare.
    """
    value = extract(line).get(LabelFieldKey.BATCH_NUMBER, {}).get("batch_number")
    assert value is None, f"{line!r} produced a fabricated batch number {value!r}"


# --- a marketing claim is not a bonus quantity -------------------------------
#
# `BONUS_QUANTITY` used to end in a bare `(?:free|extra)\b`, so any line
# carrying either word had its quantity withheld. Every line below declares one
# unambiguous quantity, and all three were reported with no value at all.


@pytest.mark.parametrize(
    "line, base_quantity",
    [
        ("Net Qty: 500 g   Gluten Free", 500),
        ("Net Weight: 250 g Preservative Free", 250),
        ("Net Contents: 500 g Alcohol Free", 500),
        ("Net Wt 200 g Free From Preservatives", 200),
        ("Net Qty: 1 kg Sugar Free", 1000),
    ],
)
def test_a_composition_claim_does_not_withhold_the_quantity(
    extract, line, base_quantity
):
    """`Gluten Free` is a claim about what is in the pack, not an offer.

    There is nothing ambiguous about `Net Qty: 500 g Gluten Free` - the package
    declares 500 g - and withholding it recorded a compliant declaration as
    unreadable. The fix is structural rather than a list of phrases: a bonus
    quantity needs *a printed quantity* immediately before the offer word.
    """
    quantity = extract(line)[LabelFieldKey.NET_QUANTITY]
    assert quantity["base_quantity"] == base_quantity
    assert not is_uncertain(quantity)


@pytest.mark.parametrize(
    "line, candidates",
    [
        ("Net Qty: 500 g + 50 g free", ["500 g", "50 g"]),
        ("Net Weight 1 kg & 100 g extra", ["1000 g", "100 g"]),
        ("Net Contents: 500 ml, 50 ml free", ["500 ml", "50 ml"]),
    ],
)
def test_a_real_bonus_quantity_is_still_withheld(extract, line, candidates):
    """The behaviour the marketing-claim fix must not cost.

    `500 g + 50 g free` may declare 500 g or 550 g. The package knows; the
    characters do not, and committing to either would put a number into the
    compliance record that is wrong half the time.
    """
    quantity = extract(line)[LabelFieldKey.NET_QUANTITY]
    assert quantity.get("base_quantity") is None
    assert quantity.get("quantity") is None
    assert is_uncertain(quantity)
    assert quantity["candidates"] == candidates


def test_a_bonus_quantity_without_a_leading_sign_is_still_withheld(extract):
    """`125 g FREE` is a bonus whether or not a `+` survived OCR."""
    quantity = extract("NET WT 500 g 125 g FREE")[LabelFieldKey.NET_QUANTITY]
    assert quantity.get("base_quantity") is None
    assert is_uncertain(quantity)


# --- one rule for cross-references -------------------------------------------
#
# A phrase naming where a declaration is printed used to veto the whole line in
# two detectors and be ignored by the other six. The rule is now uniform and is
# about the value: a usable value survives, an absent one is reported unread,
# and nothing is read out of the reference text.


@pytest.mark.parametrize(
    "line, key, value_key, expected",
    [
        (
            "Net Quantity: 500 g. See above for nutrition",
            LabelFieldKey.NET_QUANTITY,
            "base_quantity",
            500,
        ),
        (
            "Net Quantity: 500 g (see below for offers)",
            LabelFieldKey.NET_QUANTITY,
            "base_quantity",
            500,
        ),
        (
            "Batch No.: A123. Refer above panel for storage",
            LabelFieldKey.BATCH_NUMBER,
            "batch_number",
            "A123",
        ),
        (
            "MRP Rs. 40.00 (see below for offers)",
            LabelFieldKey.RETAIL_SALE_PRICE,
            "amount",
            "40.00",
        ),
        (
            "Best Before 12/2026. See above panel.",
            LabelFieldKey.BEST_BEFORE,
            "year_month",
            "2026-12",
        ),
    ],
)
def test_a_cross_reference_does_not_invalidate_a_usable_value(
    extract, line, key, value_key, expected
):
    """The declaration is on the line; the reference is about something else.

    All five lines name a declaration *and* print its value. Two of them - the
    net quantities - were suppressed outright, while the MRP and the date on
    either side of them were extracted from the same phrasing. One rule now
    covers all four detectors.
    """
    assert extract(line)[key][value_key] == expected


@pytest.mark.parametrize(
    "line, key",
    [
        ("Net Quantity: See above panel", LabelFieldKey.NET_QUANTITY),
        ("Batch No.: See above panel", LabelFieldKey.BATCH_NUMBER),
        ("MRP: Refer to above panel", LabelFieldKey.RETAIL_SALE_PRICE),
        ("Best Before: See above panel", LabelFieldKey.BEST_BEFORE),
    ],
)
def test_a_named_declaration_with_no_value_is_unread_not_invented(
    extract, unread, line, key
):
    """No value, so no field - and the observation that it was named survives.

    "The package declares no batch number" and "the package says its batch
    number is on the other panel" are opposite findings. Neither may be
    fabricated out of the reference text: `above` and `panel` are declaration
    vocabulary, never a value.
    """
    assert key not in extract(line)
    assert key in unread(line)


def test_a_nutrition_panel_line_is_still_suppressed(extract):
    """The override is anchored on `Net Qty`, not on the bare word `quantity`.

    `NET_QUANTITY_KEYWORD` ends in a bare `\bquantity\b`, so a panel heading
    reading `Quantity per 100 g` would cancel its own nutrition guard and be
    read as a 100 g declaration. `NET_QUANTITY_ANCHOR` is what the override
    uses, and it requires the word "net".
    """
    assert LabelFieldKey.NET_QUANTITY not in extract("Quantity per 100 g")
    assert LabelFieldKey.NET_QUANTITY not in extract(
        "Nutritional Information per 100 g", "Energy 310 kcal Protein 9 g"
    )


# --- the two withheld-quantity key lists cannot drift ------------------------


def test_withheld_quantity_keys_match_validation():
    """`_QUANTITY_VALUE_KEYS` and `validation._VALUE_KEYS` strip the same keys.

    Both exist to leave a net-quantity mapping present but with no committed
    value: `_flag_bonus` uses the first when a bonus quantity makes the total
    ambiguous, `validation._withdraw` uses the second when a check rejects the
    reading. A key in one and not the other leaves a number behind on one path
    and not the other - which is the "withheld" reading still putting a
    quantity into the compliance record, the exact failure both were written to
    prevent.

    This is the test `rule_based` claims keeps them in step. It did not exist.
    """
    from labelextract.fields import validation
    from labelextract.fields.rule_based import _QUANTITY_VALUE_KEYS

    assert set(_QUANTITY_VALUE_KEYS) == set(
        validation._VALUE_KEYS[LabelFieldKey.NET_QUANTITY]
    )


def test_withheld_quantity_keys_cover_every_key_normalise_quantity_emits():
    """Neither list may fall behind `normalise_quantity`.

    Equality with each other is not enough - both could agree and both be
    missing a key a later change adds to the normaliser, which would leave that
    value committed on a reading that was meant to carry none. Everything
    `normalise_quantity` produces except the uncertainty bookkeeping is a
    quantity value and must be strippable.
    """
    from labelextract.fields.normalisation import (
        REASONS_KEY,
        UNCERTAIN_KEY,
        normalise_quantity,
    )
    from labelextract.fields.rule_based import _QUANTITY_VALUE_KEYS

    emitted = set(normalise_quantity("125", "g", pack_count_text="4")) - {
        UNCERTAIN_KEY,
        REASONS_KEY,
        "candidates",
    }
    assert emitted <= set(_QUANTITY_VALUE_KEYS)
