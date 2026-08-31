"""Three ways a keyword was being read as its own value, and the guards for them.

Every case here is the same shape of defect: the extractor located a
declaration correctly and then committed to a value that was really part of the
label's *wording* or was not a value at all. That is the most expensive failure
this layer has, because `field_presence` passes on any extracted field
regardless of its uncertainty flag - so a package that declared nothing legible
is recorded as having declared `No`.

All three were found by running `tesseract` 0.2.0 over
`our-eval-v0.3-usp-partial` and reading the disagreements, and all three are
reproduced here as the recognised text that produced them. No OCR engine is
involved: field extraction takes text and returns declarations, and giving it
text directly is what makes these tests deterministic and offline.
"""

import pytest

from labelextract.contracts import LabelFieldKey
from labelextract.fields import RuleBasedFieldExtractor
from labelextract.fields import patterns as P
from labelextract.fields.normalisation import is_uncertain


@pytest.fixture
def extractor():
    return RuleBasedFieldExtractor()


def _extract(extractor, ocr_lines, image_ref, lines):
    return extractor.extract(ocr_lines(lines), image_ref)


def _field(fields, key):
    for extracted in fields:
        if extracted.key is key:
            return extracted
    return None


def _unread(extractor, ocr_lines, image_ref, lines):
    ocr = ocr_lines(lines)
    return {
        item.key: item
        for item in extractor.unread_declarations(ocr, extractor.extract(ocr, image_ref))
    }


# --- 1. the batch keyword's own qualifier ------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        # `p007_01_back`: the pack prints the label and stamps nothing against
        # it. This produced the only fabricated value in the whole 364-cell set.
        "Batch No.",
        "Batch No. :",
        "Lot No.",
        # `p010_01_back`: a legend box explaining which markings appear above.
        "Batch No. & Use By Date",
        "Batch Number",
        "Batch Code:",
    ],
)
def test_a_batch_keyword_with_no_code_after_it_yields_no_value(
    extractor, ocr_lines, image_ref, line
):
    """`No` is how the label writes "number". It is never a production code."""
    fields = _extract(extractor, ocr_lines, image_ref, [line])
    assert _field(fields, LabelFieldKey.BATCH_NUMBER) is None


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Batch No. PKM126F154", "PKM126F154"),
        ("Batch No.:GN30A60040", "GN30A60040"),
        ("Batch: PL02K50116", "PL02K50116"),
        ("B.No. 2546", "2546"),
        ("LOT NO: N668", "N668"),
        ("Batch Number 2546", "2546"),
        # The guard is written with word boundaries precisely so a genuine code
        # that begins with those letters keeps matching. There is no boundary
        # between `NO` and `1`.
        ("Batch Code: NO123", "NO123"),
        ("Batch No: CODE45", "CODE45"),
        ("Batch No: NOS9", "NOS9"),
    ],
)
def test_a_real_batch_code_is_still_read(
    extractor, ocr_lines, image_ref, line, expected
):
    fields = _extract(extractor, ocr_lines, image_ref, [line])
    found = _field(fields, LabelFieldKey.BATCH_NUMBER)

    assert found is not None
    assert found.normalized_value["batch_number"] == expected


def test_a_named_batch_declaration_with_no_readable_code_is_reported_unread(
    extractor, ocr_lines, image_ref
):
    """The declaration is on the label; its value could not be read.

    Absence of a field and "we saw this named and read nothing" are different
    findings, and the second one means *photograph the panel again* rather than
    *this package may be non-compliant*. It is deliberately not an
    `ExtractedField`: a value-less field would still make `field_presence` pass.
    """
    unread = _unread(extractor, ocr_lines, image_ref, ["Batch No. :"])

    assert LabelFieldKey.BATCH_NUMBER in unread
    assert unread[LabelFieldKey.BATCH_NUMBER].evidence_text == "Batch No. :"


def test_a_batch_code_that_was_read_is_not_also_reported_unread(
    extractor, ocr_lines, image_ref
):
    unread = _unread(extractor, ocr_lines, image_ref, ["Batch No. PKM126F154"])
    assert LabelFieldKey.BATCH_NUMBER not in unread


@pytest.mark.parametrize("line", ["a lot of people prefer it", "batch cooked daily"])
def test_ordinary_prose_is_not_reported_as_an_unread_batch_declaration(
    extractor, ocr_lines, image_ref, line
):
    """An unread observation is a positive claim about what the label says.

    `batch` and `lot` are ordinary English words, which is why the anchor
    requires the qualifier that makes the phrase unambiguous.
    """
    unread = _unread(extractor, ocr_lines, image_ref, [line])
    assert LabelFieldKey.BATCH_NUMBER not in unread


def test_every_string_the_batch_anchor_matches_is_a_batch_keyword():
    """The anchor and the extraction pattern must not drift apart.

    The anchor is what licenses an unread claim; the pattern is what reads a
    value. If the anchor ever matched a phrase the pattern does not recognise
    as a batch keyword, the two would be describing different declarations.
    """
    for phrase in ("Batch No. X1", "Lot Number X1", "B.No. X1", "L No. X1"):
        assert P.BATCH_NUMBER_ANCHOR.search(phrase) is not None
        assert P.BATCH_NUMBER.search(phrase) is not None


# --- 2. a name keyword whose value line was not recognised -------------------


@pytest.mark.parametrize("noise", ["#", ":", ">", "*", "- -", "123"])
def test_a_name_keyword_followed_by_noise_emits_no_name(
    extractor, ocr_lines, image_ref, noise
):
    """`Manufactured by: #` is not a manufacturer called `#`.

    From `p007_01_back`, where the company name is printed on the line below
    and the glyph between them was recognised as `#`. Dropped rather than
    emitted uncertain: a name is free text, so there is no ambiguity to report
    - the captured characters simply are not a name.
    """
    fields = _extract(extractor, ocr_lines, image_ref, [f"Manufactured by: {noise}"])
    assert _field(fields, LabelFieldKey.MANUFACTURER_NAME) is None


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("3M India", "3M India"),
        ("S. K. Foods", "S. K. Foods"),
        ("ITC Ltd", "ITC Ltd"),
        ("A1 Foods", "A1 Foods"),
        # Trailing punctuation is stripped, as it is from every captured
        # free-text value. `raw_value` keeps the line exactly as recognised.
        ("BAZINGA MEDIA (P) LTD.", "BAZINGA MEDIA (P) LTD"),
    ],
)
def test_an_unusual_but_real_company_name_is_still_read(
    extractor, ocr_lines, image_ref, printed, expected
):
    """The guard is the weakest one that excludes the noise, on purpose.

    Company names on Indian packaging are genuinely varied. A length floor or a
    capitalisation rule would drop one of these.
    """
    fields = _extract(extractor, ocr_lines, image_ref, [f"Manufactured by: {printed}"])
    found = _field(fields, LabelFieldKey.MANUFACTURER_NAME)

    assert found is not None
    assert found.normalized_value["name"] == expected


def test_a_name_keyword_ending_its_line_takes_the_line_below(
    extractor, ocr_lines, image_ref
):
    """The layout `p007_01_back` prints: the label, then the name under it."""
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        ["Manufactured by: #", "SWAMI SMARTH FOODS"],
    )
    found = _field(fields, LabelFieldKey.MANUFACTURER_NAME)

    assert found is not None
    assert found.normalized_value["name"] == "SWAMI SMARTH FOODS"


def test_a_name_read_from_the_next_line_says_so(extractor, ocr_lines, image_ref):
    """Adjacency is an inference about layout, not a reading.

    The line below a `Marketed by:` that ends a panel is as likely to be a
    customer-care number as a company name, and a line-oriented reader cannot
    tell. The reason travels with the value so a reviewer can weigh it.
    """
    fields = _extract(
        extractor, ocr_lines, image_ref, ["Manufactured by:", "SWAMI SMARTH FOODS"]
    )
    found = _field(fields, LabelFieldKey.MANUFACTURER_NAME)

    assert is_uncertain(found.normalized_value) is True
    assert any(
        "line after the keyword" in reason
        for reason in found.normalized_value["uncertainty_reasons"]
    )
    # Both lines are quoted, so the inference is checkable against the image.
    assert found.raw_value == "Manufactured by: SWAMI SMARTH FOODS"


def test_the_line_below_is_only_read_when_the_keyword_line_carries_no_name(
    extractor, ocr_lines, image_ref
):
    """A name on the keyword's own line is not an inference and wins."""
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        ["Manufactured by: BAZINGA MEDIA", "5/1, MADANAYAKANAHALLI"],
    )
    found = _field(fields, LabelFieldKey.MANUFACTURER_NAME)

    assert found.normalized_value["name"] == "BAZINGA MEDIA"
    assert found.raw_value == "Manufactured by: BAZINGA MEDIA"


def test_the_next_line_lookahead_can_be_turned_off(ocr_lines, image_ref):
    strict = RuleBasedFieldExtractor(read_name_from_next_line=False)
    fields = strict.extract(
        ocr_lines(["Manufactured by:", "SWAMI SMARTH FOODS"]), image_ref
    )
    assert _field(fields, LabelFieldKey.MANUFACTURER_NAME) is None


def test_a_name_keyword_on_the_last_line_reads_nothing(
    extractor, ocr_lines, image_ref
):
    """There is no line below. Nothing to guess from, so nothing is emitted."""
    fields = _extract(extractor, ocr_lines, image_ref, ["Manufactured by:"])
    assert _field(fields, LabelFieldKey.MANUFACTURER_NAME) is None


# --- 3. a toll-free number the pattern could not span ------------------------


@pytest.mark.parametrize(
    "printed",
    [
        # `p003_03_right`: four groups, which the two-group pattern missed
        # entirely - the declaration was located and reported with no number.
        "1800-10-22-221",
        "1800 123 4567",
        "1800 22 1234",
        "18001234567",
        "1800-102-2221",
    ],
)
def test_the_printed_groupings_of_an_indian_toll_free_number_are_read(printed):
    assert P.TOLL_FREE_PHONE.findall(printed) == [printed]


@pytest.mark.parametrize(
    "line",
    [
        # FSSAI licence numbers crowd the same panel and contain `1800`. The
        # leading word boundary is what keeps them out.
        "Lic. No. 10018022005492",
        "Lic. No. 11425850000026",
        "Phone No.: 022-71230555",
    ],
)
def test_a_licence_number_containing_1800_is_not_a_phone_number(line):
    assert P.TOLL_FREE_PHONE.findall(line) == []


def test_a_four_group_toll_free_number_reaches_the_extracted_field(
    extractor, ocr_lines, image_ref
):
    fields = _extract(
        extractor,
        ocr_lines,
        image_ref,
        ["LEVERCARE-QUERY / FEEDBACK, TOLL FREE: 1800-10-22-221,"],
    )
    found = _field(fields, LabelFieldKey.CONSUMER_CARE_CONTACT)

    assert found is not None
    assert found.normalized_value["phones"] == ["1800-10-22-221"]
