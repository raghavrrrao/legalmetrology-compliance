"""Golden regressions for the extraction/normalisation hardening pass.

Where these lines come from
---------------------------
Every string in this file is **recognised text this project actually produced**,
copied out of the stored Tesseract output under
`ml/data/evaluation/ocr_runs/after/`, which was run over the ten retail packages
photographed for `our-eval-v0.3-usp-partial`. Nothing here is a drafted label, a
plausible-looking line, or a corruption anybody invented to make a point: each
one is named with the sample it came off, and can be found in that sample's
`_raw.txt` by searching for it.

That matters because the corruptions are the interesting part. `MRP €349.00`,
`M.R.P %:120f`, `Batch Ni`, `NET QUANTITY : 120 GRAMS (125 mt)`, `perg` - a
person writing fake OCR does not produce those, and an extractor tuned against
invented noise is tuned against the wrong distribution.

No OCR engine runs here. Field extraction takes text and returns declarations;
handing it the stored text directly is what makes these tests deterministic,
offline, and a measurement of *interpretation* rather than of recognition. The
whole point of the layering these tests defend is that the two can fail
separately:

    OCR read `MRP €349.00` and we extracted nothing    -> extraction failure
    OCR read nothing where the label prints `₹350`     -> OCR failure

Several assertions below are that the extractor produced **nothing**, or
produced a value it refused to commit to. Those are not weak tests. A
fabricated declaration is the most expensive output this layer has, because
`field_presence` passes on any extracted field regardless of its uncertainty
flag - so a value invented here turns a package that declared nothing legible
into one that declared something.

Nothing in this file makes a legal claim. Locating a declaration says nothing
about whether it was required or whether its value was correct; both are
decided by verified `ComplianceRule` rows in the deterministic engine.
"""

from decimal import Decimal

import pytest

from labelextract.contracts import ExtractedField, LabelFieldKey, OcrResult
from labelextract.fields import RuleBasedFieldExtractor
from labelextract.fields.normalisation import is_uncertain

MRP = LabelFieldKey.RETAIL_SALE_PRICE
USP = LabelFieldKey.UNIT_SALE_PRICE
QTY = LabelFieldKey.NET_QUANTITY
CARE = LabelFieldKey.CONSUMER_CARE_CONTACT
MFG = LabelFieldKey.DATE_OF_MANUFACTURE
PKD = LabelFieldKey.DATE_OF_PACKING
BEST = LabelFieldKey.BEST_BEFORE
BATCH = LabelFieldKey.BATCH_NUMBER


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


def _unread(extractor, ocr_lines, image_ref, lines):
    ocr = ocr_lines(lines)
    fields = extractor.extract(ocr, image_ref)
    return fields, {item.key: item for item in extractor.unread_declarations(ocr, fields)}


def _committed(field: ExtractedField | None, name: str):
    """The value the extractor committed to for `name`, or None if it withheld one."""
    if field is None or field.normalized_value is None:
        return None
    return field.normalized_value.get(name)


# --- 1. an MRP that OCR read is extracted -----------------------------------
#
# The brief's headline failure: "a label visibly containing an MRP such as ₹350
# was OCR-readable, but the structured MRP extraction failed". Every line here
# is a real reading in which the rupee glyph did not survive recognition - `₹`
# came back as `€`, as `%`, as `=`, or as nothing at all - which is the form
# that failure actually takes on this corpus. The keyword is what anchors the
# amount; the currency glyph is not required, and must not be.


@pytest.mark.parametrize(
    ("line", "amount", "sample"),
    [
        # p001_05_declaration_closeup: `₹` recognised as `€`.
        ("MRP €349.00 (INCL. OF ALL TAXES) Kno", "349.00", "p001_05"),
        # p007_01_back: `₹` recognised as `%`, and a stray `f` after the digits.
        ("M.R.P %:120f", "120", "p007_01_back"),
        # p010_01_back: `₹` recognised as `=`.
        ("MRP = 40.00", "40.00", "p010_01_back"),
    ],
)
def test_an_mrp_ocr_read_is_extracted_whatever_became_of_the_rupee_glyph(
    extractor, ocr_lines, image_ref, line, amount, sample
):
    found = _field(_extract(extractor, ocr_lines, image_ref, [line]), MRP)

    assert found is not None, f"{sample}: OCR read an MRP and extraction lost it"
    assert _committed(found, "amount") == amount
    assert _committed(found, "currency") == "INR"


@pytest.mark.parametrize(
    "line",
    [
        "MRP ₹350",
        "MRP: ₹350",
        "M.R.P. ₹350",
        "MRP Rs. 350",
        "M.R.P. Rs 350",
        "Maximum Retail Price ₹350",
        "MRP* 350.00",
        "M.R.P. Rs.350/-",
        "Retail Sale Price: 350.00",
        "₹350.00 inclusive of all taxes",
    ],
)
def test_the_printed_forms_of_an_mrp_are_read(extractor, ocr_lines, image_ref, line):
    """The phrasings a retail pack uses, each anchored by the keyword alone.

    Compared as a `Decimal`, because `amount` is a string on purpose and keeps
    the precision the label printed: `350` and `350.00` are the same money and
    are not the same reading, and flattening them here would hide a normaliser
    that had started rounding.
    """
    found = _field(_extract(extractor, ocr_lines, image_ref, [line]), MRP)

    assert found is not None, line
    assert Decimal(_committed(found, "amount")) == Decimal("350"), line
    assert _committed(found, "currency") == "INR"


# --- tax inclusion is read, never inferred ----------------------------------


def test_tax_inclusion_is_recorded_only_where_the_line_says_so(
    extractor, ocr_lines, image_ref
):
    """`inclusive_of_all_taxes` is a reading, not a consequence of finding a price.

    `p001_05_declaration_closeup` prints the words on the price line and they
    are recognised, so the key is written. `p010_01_back` prints `MRP = 40.00`
    with the tax wording in a legend box elsewhere on the pack, and the key is
    **absent** - not False. Absent means "not observed"; writing True there
    would manufacture the evidence rule 6(1)(e) is tested against.
    """
    with_words = _field(
        _extract(
            extractor, ocr_lines, image_ref, ["MRP €349.00 (INCL. OF ALL TAXES) Kno"]
        ),
        MRP,
    )
    without = _field(_extract(extractor, ocr_lines, image_ref, ["MRP = 40.00"]), MRP)

    assert _committed(with_words, "inclusive_of_all_taxes") is True
    assert "inclusive_of_all_taxes" not in (without.normalized_value or {})


def test_a_price_beside_a_keyword_is_not_enough_to_prove_a_tax_declaration(
    extractor, ocr_lines, image_ref
):
    """`p007_01_back` prints the tax wording on the line *below* the price.

        M.R.P %:120f
        (Incl. of all taxes) %

    A person reads those as one declaration. This extractor reads lines, and
    "the line below belongs to this declaration" is a layout guess it cannot
    check - the line below an MRP is as often a batch code or an address. So
    the tax indication stays unobserved rather than being inferred from
    adjacency. The price itself is still read.
    """
    found = _field(
        _extract(
            extractor, ocr_lines, image_ref, ["M.R.P %:120f", "(Incl. of all taxes) %"]
        ),
        MRP,
    )

    assert _committed(found, "amount") == "120"
    assert "inclusive_of_all_taxes" not in (found.normalized_value or {})


# --- 2. a net quantity that OCR read is normalised --------------------------


@pytest.mark.parametrize(
    ("line", "quantity", "unit", "base", "sample"),
    [
        # p001_05_declaration_closeup, the reference declaration panel.
        ("NET QUANTITY : 120 GRAMS (125 mt) sc", 120, "grams", 120, "p001_05"),
        # p007_01_back: the unit printed hard against its number.
        ("Net Weight : 500g", 500, "g", 500, "p007_01_back"),
    ],
)
def test_a_net_quantity_ocr_read_is_normalised(
    extractor, ocr_lines, image_ref, line, quantity, unit, base, sample
):
    found = _field(_extract(extractor, ocr_lines, image_ref, [line]), QTY)

    assert found is not None, sample
    assert _committed(found, "quantity") == quantity
    assert _committed(found, "unit") == unit
    assert _committed(found, "base_quantity") == base
    assert _committed(found, "base_unit") == "g"


@pytest.mark.parametrize(
    "line",
    [
        "Net Quantity: 120 g",
        "Net Quantity: 120g",
        "Net Quantity: 120 GRAMS",
        "Net Quantity: 120 G",
    ],
)
def test_the_spacing_and_casing_of_a_printed_unit_do_not_change_the_reading(
    extractor, ocr_lines, image_ref, line
):
    found = _field(_extract(extractor, ocr_lines, image_ref, [line]), QTY)

    assert _committed(found, "base_quantity") == 120
    assert _committed(found, "base_unit") == "g"
    assert is_uncertain(found.normalized_value) is False


@pytest.mark.parametrize("line", ["Net Quantity: 125 ml", "Net Quantity: 125mL"])
def test_a_volume_is_normalised_onto_millilitres_not_grams(
    extractor, ocr_lines, image_ref, line
):
    """Nothing converts between mass and volume. 125 ml is not 125 g."""
    found = _field(_extract(extractor, ocr_lines, image_ref, [line]), QTY)

    assert _committed(found, "base_unit") == "ml"
    assert _committed(found, "measure") == "volume"


# --- 3. consumer-care elements ----------------------------------------------


def test_every_contact_element_on_the_panel_reaches_the_reading(
    extractor, ocr_lines, image_ref
):
    """`p001_05_declaration_closeup`, three printed lines, one declaration."""
    found = _field(
        _extract(
            extractor,
            ocr_lines,
            image_ref,
            [
                "IN CASE OF CONSUMER COMPLAINTS, CONTACT:",
                "ADDRESS MENTIONED AT MANUFACTURED BY",
                "WHATSAPP / CUSTOMER CARE : 8867162397",
                "MAIL : CARE@SHINEXPRO.IN",
            ],
        ),
        CARE,
    )

    assert found is not None
    assert _committed(found, "phones") == ["8867162397"]
    assert _committed(found, "emails") == ["CARE@SHINEXPRO.IN"]


def test_a_toll_free_number_and_an_email_on_one_panel_are_both_read(
    extractor, ocr_lines, image_ref
):
    """`p003_03_right`, the Dove five-bar pack."""
    found = _field(
        _extract(
            extractor,
            ocr_lines,
            image_ref,
            [
                "_ LEVERCARE-QUERY / FEEDBACK, TOLL FREE: 1800-10-22-221,",
                "PO BOX 14760, MUMBAI 400 099, LEVER.CARE@UNILEVER.COM",
            ],
        ),
        CARE,
    )

    assert _committed(found, "phones") == ["1800-10-22-221"]
    assert _committed(found, "emails") == ["LEVER.CARE@UNILEVER.COM"]


def test_a_space_ocr_opened_at_the_at_sign_does_not_cost_the_address(
    extractor, ocr_lines, image_ref
):
    """The separator is OCR's; the address is the label's.

    Both halves still have to be recognised in full. What is normalised away is
    a space the engine inserted, and the line it was read from survives in
    `raw_value` so the repair stays visible to a reviewer.
    """
    found = _field(
        _extract(
            extractor, ocr_lines, image_ref, ["Consumer care: care @example.com"]
        ),
        CARE,
    )

    assert _committed(found, "emails") == ["care@example.com"]
    assert found.raw_value == "Consumer care: care @example.com"


@pytest.mark.parametrize(
    ("line", "sample"),
    [
        # p009_01_back: the space at the `@` AND the dot before the TLD are
        # both gone. Putting the dot back would be a character we never read.
        ("B2l suggestion @dmartindia com", "p009_01_back"),
        # p006_01_back: same pack, same declaration, the dot lost again.
        ("3 ie 'On@dmartnda, com", "p006_01_back"),
    ],
)
def test_an_address_missing_a_character_is_not_repaired_into_one(
    extractor, ocr_lines, image_ref, line, sample
):
    found = _field(_extract(extractor, ocr_lines, image_ref, [line]), CARE)

    assert _committed(found, "emails") is None, sample


def test_a_phone_number_missing_a_digit_is_not_completed(
    extractor, ocr_lines, image_ref
):
    """`p002_04_right`: the pack prints `+91 93218 60981` and OCR lost the last
    digit to a `!`. Nine digits is not an Indian mobile number, and supplying
    the tenth would be inventing the one character nobody read."""
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["% +91 93218 6098! soa"]), CARE
    )

    assert _committed(found, "phones") is None


# --- 4. a month and year that OCR read is normalised ------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("MFG 11/2025", "2025-11"),
        ("MFD 11/2025", "2025-11"),
        ("MFG. DT.: 11-2025", "2025-11"),
        ("MFG NOV 2025", "2025-11"),
        ("MFG NOVEMBER 2025", "2025-11"),
        ("Date of Manufacture: 11/2025", "2025-11"),
    ],
)
def test_a_month_and_year_declaration_is_normalised(
    extractor, ocr_lines, image_ref, line, expected
):
    found = _field(_extract(extractor, ocr_lines, image_ref, [line]), MFG)

    assert _committed(found, "year_month") == expected
    assert "date" not in (found.normalized_value or {})


def test_a_packing_date_ocr_read_is_normalised(extractor, ocr_lines, image_ref):
    """`p010_01_back`."""
    found = _field(_extract(extractor, ocr_lines, image_ref, ["Pkd: 30/01/26"]), PKD)

    assert _committed(found, "date") == "2026-01-30"


# --- 5. a malformed date is not guessed at ----------------------------------


def test_a_run_together_date_is_not_turned_into_one(
    extractor, ocr_lines, image_ref
):
    """`1142025` is the brief's own example, and the shape a stamped date takes
    when the separators do not survive recognition.

    It could be 11/4/2025, or 1/14/2025, or 114/2025, or not a date at all.
    Choosing is guessing, and a guessed date reads downstream exactly like a
    measured one. So: no date, and the declaration is reported **unread** with
    the line it was read from as its evidence - which is a different fact from
    a package that never dated itself, and the two must not collapse.
    """
    fields, unread = _unread(extractor, ocr_lines, image_ref, ["Mfg Date: 1142025"])

    assert _field(fields, MFG) is None
    assert MFG in unread
    assert unread[MFG].evidence_text == "Mfg Date: 1142025"


def test_an_unread_date_declaration_carries_no_value_at_all(
    extractor, ocr_lines, image_ref
):
    """An `UnreadDeclaration` has no value field to fill in, by construction."""
    _, unread = _unread(extractor, ocr_lines, image_ref, ["MFG. DT. :"])

    assert set(unread[MFG].as_dict()) == {"key", "evidence_text", "box", "confidence"}


def test_a_shelf_life_below_a_manufacture_keyword_is_not_the_manufacture_date(
    extractor, ocr_lines, image_ref
):
    """`p001_05_declaration_closeup`, the reading that this pass removed.

        MFG. DT. :
        BEST BEFORE 2 YEARS FROM MFG. DT-

    The stamp after `MFG. DT. :` did not survive recognition. What follows is a
    whole, self-contained best-before declaration belonging to the keyword on
    its own line - and a package is manufactured on a day, never "two years
    from" anything. Reading it as the manufacture date attributed one
    declaration's value to another and recorded a date nobody had read.
    """
    fields, unread = _unread(
        extractor,
        ocr_lines,
        image_ref,
        ["MFG. DT. :", "BEST BEFORE 2 YEARS FROM MFG. DT-"],
    )

    assert _field(fields, MFG) is None
    assert MFG in unread

    shelf_life = _field(fields, BEST)
    assert _committed(shelf_life, "duration_value") == 2
    assert _committed(shelf_life, "duration_unit") == "years"


@pytest.mark.parametrize(
    ("key_value", "line"),
    [
        ("date_of_manufacture", "Date of Manufacture: 11/2025"),
        ("date_of_manufacture", "MFG. DT. :"),
        ("date_of_manufacture", "MFG DATE"),
        ("date_of_manufacture", "MFD. DT."),
        ("date_of_manufacture", "Manufacturing Date"),
        ("date_of_packing", "Date of Packing"),
        ("date_of_packing", "Packing Date"),
        ("date_of_packing", "Pkd. On"),
        ("date_of_packing", "Packed On"),
    ],
)
def test_a_date_anchor_never_disagrees_with_the_keyword_it_narrows(key_value, line):
    """Two patterns for one idea can drift; this is what stops them.

    Everything a `DATE_ANCHORS` entry accepts must also be a `DATE_KEYWORDS`
    match for the same declaration. An anchor accepting something the detector
    does not recognise would report a declaration unread that the extractor
    would never have looked for in the first place.
    """
    from labelextract.fields import patterns as P

    anchor = dict(P.DATE_ANCHORS)[key_value]
    keyword = dict(P.DATE_KEYWORDS)[key_value]

    assert anchor.search(line), line
    assert keyword.search(line), line


@pytest.mark.parametrize(
    ("key_value", "line"),
    [
        # The narrowing is real, not a copy. Each of these is a *name*
        # declaration that the loose keyword matches and the anchor must not:
        # reporting a date unread here would claim the label says something it
        # does not. All four are lines from the frozen set.
        ("date_of_manufacture", "MFG. BY LAKME LEVER PVT. LTD., (UNIT-II),"),
        ("date_of_manufacture", "MANUFACTURED BY:"),
        ("date_of_packing", "Packed by BAZINGA MEDIA (P) LTD"),
        ("date_of_packing", "Packed & Marketed by:"),
    ],
)
def test_a_name_declaration_is_never_a_date_anchor(key_value, line):
    from labelextract.fields import patterns as P

    assert dict(P.DATE_KEYWORDS)[key_value].search(line), (
        f"{line!r} should still match the loose keyword, or this test proves nothing"
    )
    assert not dict(P.DATE_ANCHORS)[key_value].search(line)


def test_the_packaging_spelling_is_matched_by_neither_pattern(
    extractor, ocr_lines, image_ref
):
    """A limitation, recorded rather than left to be rediscovered.

    `p006_01_back` and `p010_01_back` both print
    `See Above Panel for Date of Packaging,` - a legend line - and
    `pack(?:ing|ed)?\\b` does not reach `Packaging`. Neither the detector nor
    the anchor matches it, which is at least *consistent*: the extractor never
    looks for that spelling, so it never reports one unread either. Widening
    both is a recall change this pass did not measure, and a legend line is a
    poor case to widen for.
    """
    from labelextract.fields import patterns as P

    line = "See Above Panel for Date of Packaging,"
    assert not dict(P.DATE_KEYWORDS)["date_of_packing"].search(line)
    assert not dict(P.DATE_ANCHORS)["date_of_packing"].search(line)

    fields, unread = _unread(extractor, ocr_lines, image_ref, [line])
    assert _field(fields, PKD) is None
    assert PKD not in unread


def test_a_date_below_the_keyword_is_still_read_and_still_flagged(
    extractor, ocr_lines, image_ref
):
    """The lookahead survives the guard - only a *competing* keyword stops it."""
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["MFG. DT. :", "11/2025"]), MFG
    )

    assert _committed(found, "year_month") == "2025-11"
    assert is_uncertain(found.normalized_value) is True


def test_an_ambiguous_numeric_date_reports_both_readings(
    extractor, ocr_lines, image_ref
):
    """`03/04/2025` is 3 April or 4 March. The label does not say which."""
    found = _field(_extract(extractor, ocr_lines, image_ref, ["MFG 03/04/2025"]), MFG)

    assert _committed(found, "date") is None
    assert set(found.normalized_value["candidates"]) == {"2025-04-03", "2025-03-04"}


# --- 6. several prices on one label go to the right declarations ------------


def test_a_retail_price_and_a_unit_price_are_not_confused_for_each_other(
    extractor, ocr_lines, image_ref
):
    """`p001_05_declaration_closeup`, both declarations printed and both read.

    `₹` came back as `€` on one line and as `¥` on the other. Each amount has
    to land on the declaration its own keyword names: 349.00 is the retail sale
    price, 2.91 per gram is the unit sale price, and neither may stand in for
    the other.
    """
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        [
            "MRP €349.00 (INCL. OF ALL TAXES) Kno",
            "UNIT SALE PRICE : ¥2.91 PER GRAM",
        ],
    )

    assert _committed(_field(fields, MRP), "amount") == "349.00"
    assert _committed(_field(fields, USP), "amount") == "2.91"
    assert _committed(_field(fields, USP), "per_unit") == "gram"


def test_a_unit_price_alone_does_not_also_become_a_retail_price(
    extractor, ocr_lines, image_ref
):
    """One amount is one declaration. A package declaring only a rate has not
    declared an MRP, and recording one would make `field_presence` pass."""
    fields = _extract(
        extractor, ocr_lines, image_ref, ["USP: Rs.0.93/g"]
    )

    assert _field(fields, USP) is not None
    assert _field(fields, MRP) is None


def test_a_quantity_after_the_mrp_keyword_is_not_read_as_the_price(
    extractor, ocr_lines, image_ref
):
    fields = _extract(
        extractor, ocr_lines, image_ref, ["MRP (incl. of all taxes) for 500 g pack: 250"]
    )

    assert _committed(_field(fields, MRP), "amount") == "250"


def test_the_space_lost_between_per_and_its_unit_does_not_cost_the_rate(
    extractor, ocr_lines, image_ref
):
    """`p010_01_back` prints `₹ 0.08 per g`; OCR returned `Z 0.08 perg`.

    Every character of the declaration was recognised and only the space
    between two of them was lost, so reading it repairs nothing. It stays
    uncertain, because no unit-sale-price keyword was recognised on the line.
    """
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["Rs. 0.08 perg"]), USP
    )

    assert _committed(found, "amount") == "0.08"
    assert _committed(found, "per_unit") == "g"
    assert is_uncertain(found.normalized_value) is True


# --- 7. several quantities on one line are not collapsed --------------------


def test_competing_quantities_on_one_line_are_all_reported(
    extractor, ocr_lines, image_ref
):
    """`p003_03_right`, a five-bar soap pack.

        p NET CONTENTS WHEN PACKED 4 UNITS X 125 9 + 125 g FREE?

    The leftmost reading is `4 units`, and it used to be emitted committed and
    unflagged - so a reviewer was shown "this package declares 4" for a package
    declaring 625 g of soap, with the gram readings on the same line discarded
    unmentioned. Nothing here decides which is the net quantity. The
    disagreement is reported, and a person resolves it.
    """
    found = _field(
        _extract(
            extractor,
            ocr_lines,
            image_ref,
            ["p NET CONTENTS WHEN PACKED 4 UNITS X 125 9 + 125 g FREE?"],
        ),
        QTY,
    )

    assert found is not None
    assert is_uncertain(found.normalized_value) is True
    assert len(found.normalized_value["candidates"]) == 2


def test_a_mass_and_a_volume_printed_together_are_not_collapsed_into_one(
    extractor, ocr_lines, image_ref
):
    """A dual-declared aerosol prints both, and neither is the other."""
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["Net Qty: 120 g (125 ml)"]), QTY
    )

    assert is_uncertain(found.normalized_value) is True
    assert len(found.normalized_value["candidates"]) == 2


def test_one_quantity_printed_twice_is_not_a_disagreement(
    extractor, ocr_lines, image_ref
):
    """Two readings that normalise to the same value agree, so nothing is flagged."""
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["Net Qty: 500 g (500 g)"]), QTY
    )

    assert _committed(found, "base_quantity") == 500
    assert is_uncertain(found.normalized_value) is False


def test_a_multipack_is_one_quantity_not_two(extractor, ocr_lines, image_ref):
    """`4 x 100 g` is a single declaration whose form the pattern already knows."""
    found = _field(_extract(extractor, ocr_lines, image_ref, ["Net Wt: 4 x 100 g"]), QTY)

    assert _committed(found, "pack_count") == 4
    assert _committed(found, "base_quantity") == 400
    assert is_uncertain(found.normalized_value) is False


# --- 8. OCR corruption behaves safely ---------------------------------------


def test_a_keyword_qualifier_read_as_noise_is_not_emitted_as_a_batch_code(
    extractor, ocr_lines, image_ref
):
    """`p006_01_back`: the pack's legend line, as recognised.

    The pack prints `MRP Rs. (incl. of all taxes), Batch No. & Use By Date` - a
    legend saying where the declarations are, not a declaration. OCR returned
    `Batch Ni`, and `Ni` was emitted as the batch code, committed and
    unflagged: a production code that appears nowhere on the package, shown to
    a reviewer as if it had been read off one.
    """
    fields = _extract(
        extractor, ocr_lines, image_ref, ["PRs. (inc, of al laxes), Batch Ni"]
    )

    assert _field(fields, BATCH) is None


@pytest.mark.parametrize(
    "value",
    ["No", "Nos", "Ni", "Ne", "Na", "NG", "Code", "Number"],
)
def test_no_misreading_of_the_batch_qualifier_becomes_a_batch_code(
    extractor, ocr_lines, image_ref, value
):
    fields = _extract(extractor, ocr_lines, image_ref, [f"Batch {value}"])

    assert _field(fields, BATCH) is None


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Batch No. PKM126F154", "PKM126F154"),
        ("Batch No.:GN30A60040", "GN30A60040"),
        ("Batch: PL02K50116", "PL02K50116"),
        ("B.No. 2546", "2546"),
        ("Batch No: N668", "N668"),
    ],
)
def test_a_real_batch_code_off_the_evaluation_set_is_still_read(
    extractor, ocr_lines, image_ref, line, expected
):
    """The digit requirement must not cost a genuine code. Every batch number
    in the frozen set carries digits, and each of these is one of them."""
    found = _field(_extract(extractor, ocr_lines, image_ref, [line]), BATCH)

    assert _committed(found, "batch_number") == expected


@pytest.mark.parametrize(
    ("line", "sample"),
    [
        # p010_01_back: `500 g` with the space gone and the `g` read as a `9`.
        ("Net Quantity: 5009", "p010_01_back"),
        # p009_01_back: the same pack, the space kept and the `g` still a `9`.
        ("fe Net Quantity : 200 9", "p009_01_back"),
    ],
)
def test_a_unit_lost_to_a_digit_confusion_is_not_supplied_from_context(
    extractor, ocr_lines, image_ref, line, sample
):
    """`g` misread as `9` is one of this corpus's commonest corruptions, and it
    is deliberately **not** repaired.

    A net-quantity keyword on the line tells us a quantity is declared. It does
    not tell us the trailing `9` was a `g` rather than a digit, and `5009` is
    as readable as five thousand and nine as it is as 500 g. Committing would
    put a measurement the label never printed in front of a reviewer, and the
    number would be indistinguishable from one that was actually read.

    The declaration is not lost: the keyword is reported unread, which says
    "this panel declares a net quantity and we could not read its value" -
    a retake, not a violation.
    """
    fields, unread = _unread(extractor, ocr_lines, image_ref, [line])

    assert _field(fields, QTY) is None, sample
    assert QTY in unread, sample


def test_a_bare_number_after_a_quantity_keyword_is_not_given_a_unit(
    extractor, ocr_lines, image_ref
):
    """`12` is not `12 g`. There is no unit on the line to read."""
    fields, unread = _unread(extractor, ocr_lines, image_ref, ["Net Quantity: 12"])

    assert _field(fields, QTY) is None
    assert QTY in unread


def test_a_price_keyword_whose_value_was_not_read_produces_no_price(
    extractor, ocr_lines, image_ref
):
    """`p001_04_right_clean`: a curved can, foreshortened. OCR returned the
    keyword and nothing else."""
    fields, unread = _unread(
        extractor, ocr_lines, image_ref, ["NET", "MRP", "MANUPACTYD. is ."]
    )

    assert _field(fields, MRP) is None
    assert MRP in unread
    assert unread[MRP].evidence_text == "MRP"


def test_a_digit_read_as_a_letter_is_not_corrected_into_a_price(
    extractor, ocr_lines, image_ref
):
    """`349O` - a trailing letter O where a zero was printed.

    Nothing maps `O` to `0` here. Doing so would turn an unreliable reading
    into a confident wrong one, indistinguishable afterwards from a correct
    read. The digits that *were* recognised are what the amount is built from.
    """
    found = _field(_extract(extractor, ocr_lines, image_ref, ["MRP 349O"]), MRP)

    assert _committed(found, "amount") == "349"


# --- 9. a declaration that is absent stays absent ---------------------------


def test_text_carrying_no_declaration_produces_nothing(
    extractor, ocr_lines, image_ref
):
    """`p003_03_right`'s ingredient panel: full of words, empty of declarations."""
    fields, unread = _unread(
        extractor,
        ocr_lines,
        image_ref,
        [
            "INGREDIENTS: SODIUM COCOYL ISETHIONATE, PALMITIC ACID,",
            "ZINC OXIDE, GLYCERIN, ALPHA-ISOMETHYL IONONE, CITRONELLOL,",
            "COUMARIN, HEXYL CINNAMAL, LIMONENE, LINALOOL.",
        ],
    )

    assert fields == ()
    assert unread == {}


def test_a_nutrition_panel_quantity_is_never_the_net_quantity(
    extractor, ocr_lines, image_ref
):
    """`p002_03_left`, a supplement tube: the panel is full of real quantities
    and none of them is the declared one."""
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        [
            "onal Info",
            "nuff ifn tablet (4.20), Servings Bar 6",
            "cont Per serving (4.29 -",
        ],
    )

    assert _field(fields, QTY) is None


def test_an_empty_reading_produces_no_declarations_and_no_observations(
    extractor, image_ref
):
    """`p002_01_back`: OCR recognised nothing at all on this panel.

    Zero declarations is the correct and complete answer. Reporting keywords
    unread would need keywords, and there are none - but the point is that a
    blank photograph must not start producing observations about what a package
    does or does not declare.
    """
    fields = extractor.extract(OcrResult(), image_ref)

    assert fields == ()
    assert extractor.unread_declarations(OcrResult(), fields) == ()


# --- 10. the raw reading is preserved ---------------------------------------


def test_the_evidence_line_is_stored_exactly_as_recognised(
    extractor, ocr_lines, image_ref
):
    """"What did OCR actually read?" has to stay answerable from the field.

    The corruption in the line is the evidence a reviewer needs: `€349.00` is
    what makes it obvious that the rupee glyph was misrecognised rather than
    the amount misread. Cleaning it up in place would destroy the only record
    of that.
    """
    line = "MRP €349.00 (INCL. OF ALL TAXES) Kno"
    found = _field(_extract(extractor, ocr_lines, image_ref, [line]), MRP)

    assert found.raw_value == line
    assert _committed(found, "amount") == "349.00"


def test_geometry_survives_from_the_recognised_block_onto_the_field(
    extractor, ocr_lines, image_ref
):
    """The box is what lets a reviewer see *where on the package* this was read."""
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["MRP = 40.00"]), MRP
    )

    assert found.box is not None
    assert found.box.width > 0 and found.box.height > 0


def test_a_withheld_reading_still_says_why(extractor, ocr_lines, image_ref):
    """An uncertain field carries its reasons, so the hedge is inspectable."""
    found = _field(
        _extract(
            extractor,
            ocr_lines,
            image_ref,
            ["p NET CONTENTS WHEN PACKED 4 UNITS X 125 9 + 125 g FREE?"],
        ),
        QTY,
    )

    assert found.normalized_value["uncertainty_reasons"]
    assert all(isinstance(r, str) and r for r in found.normalized_value["uncertainty_reasons"])


# --- 11. confidence stays extraction confidence -----------------------------


def test_confidence_is_the_engines_score_for_the_characters_and_nothing_else(
    extractor, ocr_lines, image_ref
):
    """`ExtractedField.confidence` is what OCR said about the *glyphs*.

    It is not a compliance figure, not a probability that the declaration is
    correct, and not a summary of the normaliser's opinion - that is
    `normalized_value["uncertain"]`, which is a different axis and lives
    separately for exactly this reason.
    """
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["MRP = 40.00"], confidence=0.42),
        MRP,
    )

    assert found.confidence == 0.42


def test_a_perfectly_recognised_line_can_still_be_an_uncertain_reading(
    extractor, ocr_lines, image_ref
):
    """The two axes must not collapse into one another.

    `MFG 03/04/2025` is recognised flawlessly - high character confidence - and
    its meaning is genuinely ambiguous. Both facts are reported, separately.
    """
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["MFG 03/04/2025"], confidence=1.0),
        MFG,
    )

    assert found.confidence == 1.0
    assert is_uncertain(found.normalized_value) is True


def test_an_unreported_confidence_is_never_filled_in(extractor, ocr_lines, image_ref):
    """None means "the engine did not score this". It must not become 0.0."""
    found = _field(
        _extract(extractor, ocr_lines, image_ref, ["MRP = 40.00"], confidence=None),
        MRP,
    )

    assert found.confidence is None


def test_no_normalised_mapping_carries_a_compliance_verdict(
    extractor, ocr_lines, image_ref
):
    """The layering, asserted mechanically.

    Extraction produces observations. Whether a declaration was required, and
    whether the package complies, are decided by verified `ComplianceRule` rows
    in the deterministic engine. No word of that vocabulary may appear in
    anything this layer emits.
    """
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        [
            "NET QUANTITY : 120 GRAMS (125 mt) sc",
            "MRP €349.00 (INCL. OF ALL TAXES) Kno",
            "UNIT SALE PRICE : ¥2.91 PER GRAM",
            "MFG. DT. :",
            "BEST BEFORE 2 YEARS FROM MFG. DT-",
            "WHATSAPP / CUSTOMER CARE : 8867162397",
        ],
    )
    forbidden = {
        "compliant", "non_compliant", "noncompliant", "compliance", "verdict",
        "violation", "passed", "failed", "legal", "verified", "required",
    }

    assert fields
    for field in fields:
        keys = set(field.normalized_value or {})
        assert not keys & forbidden, (field.key, keys & forbidden)
