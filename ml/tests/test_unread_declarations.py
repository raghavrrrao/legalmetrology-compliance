"""Telling "not on the label" apart from "on the label but unreadable".

No OCR engine is involved. Every case here is built from synthetic lines, so
what is measured is interpretation rather than recognition, and the result does
not depend on which Tesseract happens to be installed.

The case that prompted this, from a real photograph of a curved aerosol can
(`04_right_clean`): OCR returned the single line `MRP` and nothing else,
because the rest of that line was foreshortened past legibility. `extract()`
correctly emitted no field - a keyword is not a price - and the result was an
empty `fields` tuple, which is the *same* output a package with no MRP at all
would produce.

Those are opposite findings. One means "photograph the panel again"; the other
is a potential violation. This file pins the distinction, and pins the two ways
of getting it wrong:

- inventing a value, or a field, from a bare keyword;
- letting an unread declaration inflate into something confident.
"""

import pytest

from labelextract.contracts import (
    ExtractedField,
    ImageRef,
    LabelFieldKey,
    OcrResult,
    UnreadDeclaration,
)
from labelextract.fields import SUPPORTED_KEYS, RuleBasedFieldExtractor
from labelextract.interfaces import FieldExtractor


@pytest.fixture
def extractor():
    return RuleBasedFieldExtractor()


def _run(extractor, ocr_lines, image_ref, lines, **kwargs):
    """Extract, then ask what was seen and not read - as the pipeline does."""
    ocr = ocr_lines(lines, **kwargs)
    fields = extractor.extract(ocr, image_ref)
    return fields, extractor.unread_declarations(ocr, fields)


# --- the case this exists for -----------------------------------------------


def test_a_keyword_with_no_value_is_reported_as_unread_not_as_a_field(
    extractor, ocr_lines, image_ref
):
    """`MRP` alone: no price was read, and the package plainly declares one."""
    fields, unread = _run(extractor, ocr_lines, image_ref, ["MRP"])

    assert fields == ()
    assert [item.key for item in unread] == [LabelFieldKey.RETAIL_SALE_PRICE]
    assert unread[0].evidence_text == "MRP"


def test_an_unread_declaration_carries_its_evidence_and_geometry(
    extractor, ocr_lines, image_ref
):
    """A reviewer has to be able to go and look at the line we mean."""
    _, unread = _run(extractor, ocr_lines, image_ref, ["MRP"])

    assert unread[0].box is not None
    assert unread[0].confidence == pytest.approx(0.9)


def test_nothing_is_reported_unread_once_the_value_is_read(
    extractor, ocr_lines, image_ref
):
    """The same keyword, this time with its value: a field, and no observation."""
    fields, unread = _run(extractor, ocr_lines, image_ref, ["MRP Rs. 349.00"])

    assert [f.key for f in fields] == [LabelFieldKey.RETAIL_SALE_PRICE]
    assert unread == ()


def test_a_declaration_read_on_another_line_is_not_reported_unread(
    extractor, ocr_lines, image_ref
):
    """A label routinely prints the keyword twice. One reading is enough."""
    fields, unread = _run(
        extractor, ocr_lines, image_ref, ["MRP", "MRP Rs. 349.00 incl. of all taxes"]
    )

    assert any(f.key is LabelFieldKey.RETAIL_SALE_PRICE for f in fields)
    assert unread == ()


def test_one_observation_per_declaration_however_often_it_is_named(
    extractor, ocr_lines, image_ref
):
    """Three unreadable MRP lines are one finding, not three."""
    _, unread = _run(extractor, ocr_lines, image_ref, ["MRP", "M.R.P.", "MRP :"])

    assert len(unread) == 1


# --- what must NOT be reported ----------------------------------------------


def test_a_bare_net_is_not_treated_as_a_net_quantity_keyword(
    extractor, ocr_lines, image_ref
):
    """`NET` on its own names nothing.

    It was recognised on the same real photograph as the bare `MRP`, and it is
    deliberately not reported: the net-quantity keyword requires a following
    word (`net qty`, `net weight`, `net contents`). "NET" alone could be the
    start of any of them, or of nothing. Reporting it would be a guess about
    what the label says, which is the thing this whole file exists to prevent.
    """
    fields, unread = _run(extractor, ocr_lines, image_ref, ["NET"])

    assert fields == ()
    assert unread == ()


def test_ocr_noise_that_names_no_declaration_reports_nothing(
    extractor, ocr_lines, image_ref
):
    """`MANUPACTYD. is .` is a misrecognised word, not a manufacturer."""
    fields, unread = _run(
        extractor, ocr_lines, image_ref, ["MANUPACTYD. is .", "; |} fragrance that linges*"]
    )

    assert fields == ()
    assert unread == ()


@pytest.mark.parametrize(
    "line",
    [
        "the quantity supplied may vary",
        "quantity surveyor report",
        "Shake well to distribute the quantity evenly",
    ],
)
def test_the_ordinary_english_word_quantity_is_not_evidence(
    extractor, ocr_lines, image_ref, line
):
    """Prose containing "quantity" is not a net-quantity declaration.

    `NET_QUANTITY_KEYWORD` ends in a bare `\\bquantity\\b`, which is right where
    the detector uses it - a number and a unit must be on the same line before
    anything is emitted, so prose never produces a field. As evidence *on its
    own* it is wrong, and an earlier version of this reported `net_quantity`
    unread for every one of these lines.

    `NET_QUANTITY_ANCHOR` is the strict half, and this is what it is for.
    """
    fields, unread = _run(extractor, ocr_lines, image_ref, [line])

    assert fields == ()
    assert unread == ()


def test_the_strict_anchor_never_disagrees_with_the_keyword_it_narrows(
    extractor, ocr_lines, image_ref
):
    """Two patterns for one idea can drift; this is what stops them.

    Everything `NET_QUANTITY_ANCHOR` accepts must also be a net-quantity
    keyword. If it ever accepted something the detector does not recognise, the
    extractor would report a declaration unread that it would never have looked
    for in the first place.
    """
    from labelextract.fields import patterns as P

    accepted = [
        "Net Qty: 500 g", "Net Quantity", "NET WEIGHT", "Net Wt:", "net contents",
        "Net Vol. 2 L", "net volume", "NET QUANTITY : 120 GRAMS (125 mL)",
    ]
    for line in accepted:
        if P.NET_QUANTITY_ANCHOR.search(line):
            assert P.NET_QUANTITY_KEYWORD.search(line), line

    # And the narrowing is real, not a copy.
    assert P.NET_QUANTITY_KEYWORD.search("quantity")
    assert not P.NET_QUANTITY_ANCHOR.search("quantity")


def test_no_text_at_all_reports_nothing_unread(extractor, image_ref):
    """`EMPTY` is already inconclusive about every declaration.

    Listing keywords as unread would need keywords, and there are none - but
    the point is that a blank photograph must not start producing observations
    about what a package does or does not declare.
    """
    fields = extractor.extract(OcrResult(), image_ref)
    assert extractor.unread_declarations(OcrResult(), fields) == ()


def test_an_unread_declaration_is_never_an_extracted_field(
    extractor, ocr_lines, image_ref
):
    """The load-bearing separation.

    A presence check passes on any extracted field regardless of its
    uncertainty flag. If a value-less keyword ever became a field, a package
    whose MRP nobody could read would be recorded as having declared one - a
    possible violation silently turned into a pass.
    """
    fields, unread = _run(extractor, ocr_lines, image_ref, ["MRP", "Best Before"])

    assert fields == ()
    assert unread != ()
    for item in unread:
        assert not isinstance(item, ExtractedField)
        assert not hasattr(item, "normalized_value")
        assert not hasattr(item, "raw_value")


def test_low_confidence_evidence_stays_low_confidence(
    extractor, ocr_lines, image_ref
):
    """An observation never scores better than the reading it came from."""
    _, unread = _run(extractor, ocr_lines, image_ref, ["MRP"], confidence=0.11)

    assert unread[0].confidence == pytest.approx(0.11)


def test_unreported_confidence_stays_unreported(extractor, ocr_lines, image_ref):
    """None means "the engine did not score this" and must never become 0.0."""
    _, unread = _run(extractor, ocr_lines, image_ref, ["MRP"], confidence=None)

    assert unread[0].confidence is None


# --- other keyword-anchored declarations ------------------------------------


@pytest.mark.parametrize(
    ("line", "key"),
    [
        ("Net Qty:", LabelFieldKey.NET_QUANTITY),
        ("Net Weight", LabelFieldKey.NET_QUANTITY),
        ("Best Before", LabelFieldKey.BEST_BEFORE),
        ("Use By", LabelFieldKey.BEST_BEFORE),
        ("Date of Import", LabelFieldKey.DATE_OF_IMPORT),
    ],
)
def test_other_unambiguous_keywords_behave_the_same_way(
    extractor, ocr_lines, image_ref, line, key
):
    """Not MRP-specific - but only for keywords that name one declaration."""
    fields, unread = _run(extractor, ocr_lines, image_ref, [line])

    assert not any(f.key is key for f in fields)
    assert key in {item.key for item in unread}


@pytest.mark.parametrize(
    "line",
    [
        # `packed\s*(?:on|date)?` matches the bare stem, so the packing-date
        # keyword fires on a line that names a *packer*. Same for `manufactured`.
        "Packed by",
        "Packed by BAZINGA MEDIA (P) LTD",
        "Manufactured by",
        "Manufactured & Marketed by BAZINGA MEDIA",
        # The value is part of these patterns, so a bare keyword never matches.
        "Marketed by",
        "Imported by",
        "Batch",
        "Country of Origin",
    ],
)
def test_a_keyword_shared_with_another_declaration_is_never_reported(
    extractor, ocr_lines, image_ref, line
):
    """The precision guard.

    `Packed by BAZINGA MEDIA` names a packer and carries no packing date. A
    coarser rule reported `date_of_packing` as "named but unread" here, which
    is a claim that the label says something it does not. An unread observation
    sends a human to look at the package, so a wrong one wastes exactly the
    attention this mechanism exists to direct.

    The cost is recall: a genuinely unreadable `MFG. DT.` is not reported
    either. Precision is the right side to err on - see the same trade-off for
    `require_net_quantity_keyword`.
    """
    _, unread = _run(extractor, ocr_lines, image_ref, [line])

    assert {item.key for item in unread} == set()


def test_a_bare_contact_keyword_is_a_field_already_not_an_unread_observation(
    extractor, ocr_lines, image_ref
):
    """Documents existing extractor behaviour, which this did not change.

    `_consumer_care_contact` emits a keyword-only field marked uncertain when
    it finds the keyword and no email or phone. So the declaration is not
    unresolved - it is resolved, uncertainly - and reporting it again as unread
    would double-count it.

    Whether a value-less uncertain field is the right output there is a
    separate question about the extractor, deliberately not reopened here.
    """
    fields, unread = _run(extractor, ocr_lines, image_ref, ["Customer Care"])

    care = [f for f in fields if f.key is LabelFieldKey.CONSUMER_CARE_CONTACT]
    assert len(care) == 1
    assert care[0].normalized_value["uncertain"] is True
    assert unread == ()


def test_every_reported_key_is_one_the_extractor_actually_attempts(
    extractor, ocr_lines, image_ref
):
    """Reporting a declaration unread that is never attempted would be a lie.

    It would say "the label names this and we could not read it" when the truth
    is "we never look for this at all".
    """
    _, unread = _run(
        extractor,
        ocr_lines,
        image_ref,
        ["MRP", "Net Qty:", "Customer Care", "Mfg. Date", "Marketed by",
         "Imported by", "Packed by", "Best Before"],
    )

    assert {item.key for item in unread} <= SUPPORTED_KEYS


# --- the contract -----------------------------------------------------------


def test_an_observation_without_evidence_is_refused():
    """An unfalsifiable claim is worse than no claim."""
    with pytest.raises(ValueError):
        UnreadDeclaration(key=LabelFieldKey.RETAIL_SALE_PRICE, evidence_text="   ")


def test_a_confidence_outside_the_unit_interval_is_refused():
    with pytest.raises(ValueError):
        UnreadDeclaration(
            key=LabelFieldKey.RETAIL_SALE_PRICE,
            evidence_text="MRP",
            confidence=1.4,
        )


def test_the_json_form_is_flat_and_carries_no_value():
    """It is persisted verbatim in run metadata, so it must stay JSON-safe."""
    body = UnreadDeclaration(
        key=LabelFieldKey.RETAIL_SALE_PRICE, evidence_text="MRP", confidence=0.93
    ).as_dict()

    assert body == {
        "key": "retail_sale_price",
        "evidence_text": "MRP",
        "box": None,
        "confidence": 0.93,
    }
    assert "value" not in body


def test_an_extractor_that_does_not_implement_it_reports_nothing():
    """The hook is optional, so nothing existing had to change to keep working."""

    class _Minimal(FieldExtractor):
        name, version = "minimal", "0.0.0"

        def extract(self, ocr: OcrResult, image: ImageRef):
            return ()

    assert _Minimal().unread_declarations(OcrResult(), ()) == ()
