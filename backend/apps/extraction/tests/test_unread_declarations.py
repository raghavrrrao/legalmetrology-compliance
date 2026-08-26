"""The ML -> backend crossing for declarations that were named but not read.

What is being tested here
-------------------------
`labelextract` reports these in `ExtractionResult.metadata["unread_declarations"]`
rather than on `ExtractionResult.fields`, deliberately and permanently: an
unread declaration is not a field, and `field_presence` passes on any field
whatever its uncertainty. `apps.extraction.services.extraction_service` is the
one place in the backend that reads the ML layer's output, so it is the one
place that seam can be crossed - and this file is where the crossing is
checked.

A real pipeline is registered in the `labelextract` registry and resolved by
name exactly as a production one is, so the service, the persistence code and
the model under test are all the real ones. Only recognition is stubbed. No
Tesseract binary is involved, for the same reason the rest of the suite avoids
it: a test that needed it installed would fail on half the team's machines and
would be measuring recognition rather than integration.

What this file does NOT test
----------------------------
What the *compliance* engine concludes from these rows. That is
`apps/rules/tests/test_checks.py` (the validator) and
`apps/compliance/tests/test_engine.py` (the verdict). Nothing here makes a
legal claim: that a keyword was printed says nothing about whether the
declaration was required.
"""

import json

import pytest

from labelextract import registry
from labelextract.contracts import (
    BoundingBox,
    ExtractedField,
    ImageRef,
    LabelFieldKey,
    OcrResult,
    TextBlock,
    UnreadDeclaration,
)
from labelextract.interfaces import FieldExtractor, OcrEngine
from labelextract.pipeline import ExtractionPipeline

from apps.extraction.models import ExtractionRun, UnreadLabelDeclaration
from apps.extraction.services import extraction_service
from apps.extraction.services.extraction_service import _unread_rows
from apps.images.models import ProductImage

pytestmark = pytest.mark.django_db

_TEST_VERSION = "0.0.0"
#: A panel photographed edge-on: the MRP keyword is legible, its value is not.
_EDGE_ON_PIPELINE = "backend-test-unread-edge-on"
#: The same panel cut off by the frame: three declarations named, one read.
_CROPPED_PIPELINE = "backend-test-unread-cropped"
#: An engine that reports nothing unread, which must stay the normal case.
_CLEAN_PIPELINE = "backend-test-unread-clean"


class _StubOcrEngine(OcrEngine):
    name = "backend-test-unread-ocr"
    version = _TEST_VERSION

    def __init__(self, lines):
        self._lines = lines

    def recognise(self, image: ImageRef) -> OcrResult:
        return OcrResult(
            blocks=tuple(
                TextBlock(
                    text=text,
                    box=BoundingBox(x=4, y=4 + index * 20, width=200, height=18),
                    confidence=0.62,
                )
                for index, text in enumerate(self._lines)
            ),
            raw={"engine": self.name, "line_count": len(self._lines)},
        )


class _StubFieldExtractor(FieldExtractor):
    """Reports a fixed set of fields and a fixed set of unread declarations.

    Written out rather than driven by `RuleBasedFieldExtractor`, so this file
    tests the *crossing* and not the extractor's detection logic. That is
    covered in `ml/tests/test_unread_declarations.py`.
    """

    name = "backend-test-unread-fields"
    version = _TEST_VERSION

    def __init__(self, fields=(), unread=()):
        self._fields = fields
        self._unread = unread

    def extract(self, ocr: OcrResult, image: ImageRef):
        return self._fields

    def unread_declarations(self, ocr: OcrResult, fields):
        return self._unread


_NET_QUANTITY_FIELD = ExtractedField(
    key=LabelFieldKey.NET_QUANTITY,
    raw_value="NET QUANTITY : 120 GRAMS",
    normalized_value={
        "quantity": 120,
        "unit": "grams",
        "base_quantity": 120,
        "base_unit": "g",
        "measure": "mass",
        "uncertain": False,
    },
    confidence=0.82,
    box=BoundingBox(x=4, y=4, width=200, height=18),
)

_UNREAD_MRP = UnreadDeclaration(
    key=LabelFieldKey.RETAIL_SALE_PRICE,
    evidence_text="MRP",
    box=BoundingBox(x=513, y=1240, width=28, height=12),
    confidence=0.93,
)


def _register(name: str, build) -> None:
    """Register once per process; the registry rejects duplicates on purpose."""
    if (name, _TEST_VERSION) not in list(registry.available_pipelines()):
        registry.register_pipeline(name, _TEST_VERSION, build)


_register(
    _EDGE_ON_PIPELINE,
    lambda: ExtractionPipeline(
        name=_EDGE_ON_PIPELINE,
        version=_TEST_VERSION,
        ocr_engine=_StubOcrEngine(["ShineXPro Helmet Cleaner", "NET", "MRP"]),
        field_extractor=_StubFieldExtractor(unread=(_UNREAD_MRP,)),
    ),
)
_register(
    _CROPPED_PIPELINE,
    lambda: ExtractionPipeline(
        name=_CROPPED_PIPELINE,
        version=_TEST_VERSION,
        ocr_engine=_StubOcrEngine(["NET QUANTITY : 120 GRAMS", "MRP", "BEST BEFORE 2"]),
        field_extractor=_StubFieldExtractor(
            fields=(_NET_QUANTITY_FIELD,),
            unread=(
                _UNREAD_MRP,
                UnreadDeclaration(
                    key=LabelFieldKey.BEST_BEFORE,
                    evidence_text="BEST BEFORE 2",
                    box=None,
                    confidence=None,
                ),
            ),
        ),
    ),
)
_register(
    _CLEAN_PIPELINE,
    lambda: ExtractionPipeline(
        name=_CLEAN_PIPELINE,
        version=_TEST_VERSION,
        ocr_engine=_StubOcrEngine(["NET QUANTITY : 120 GRAMS"]),
        field_extractor=_StubFieldExtractor(fields=(_NET_QUANTITY_FIELD,)),
    ),
)


def _run(image: ProductImage, pipeline: str) -> ExtractionRun:
    return extraction_service.run_extraction(
        image, engine_name=pipeline, engine_version=_TEST_VERSION
    )


# --- the crossing -----------------------------------------------------------


def test_an_unread_declaration_becomes_a_row(product_image):
    """The seam, in one test: the ML layer said it, the database has it."""
    run = _run(product_image, _EDGE_ON_PIPELINE)

    [unread] = run.unread_declarations.all()

    assert unread.field_key == LabelFieldKey.RETAIL_SALE_PRICE.value
    assert unread.evidence_text == "MRP"


def test_the_evidence_line_survives_the_boundary(product_image):
    """Verbatim, not summarised. It is what a reviewer checks the claim against."""
    run = _run(product_image, _EDGE_ON_PIPELINE)

    assert run.unread_declarations.get().evidence_text == _UNREAD_MRP.evidence_text


def test_the_bounding_box_survives_the_boundary(product_image):
    """In source-image pixels, so the UI can point at the panel to re-shoot."""
    run = _run(product_image, _EDGE_ON_PIPELINE)

    assert run.unread_declarations.get().bounding_box == {
        "x": 513,
        "y": 1240,
        "width": 28,
        "height": 12,
    }


def test_the_confidence_survives_the_boundary(product_image):
    run = _run(product_image, _EDGE_ON_PIPELINE)

    assert run.unread_declarations.get().confidence == pytest.approx(0.93)


def test_an_unreported_box_or_confidence_is_stored_as_null_not_zero(product_image):
    """NULL means the engine did not report it. Zero would be a measurement."""
    run = _run(product_image, _CROPPED_PIPELINE)
    best_before = run.unread_declarations.get(field_key="best_before")

    assert best_before.bounding_box is None
    assert best_before.confidence is None


def test_several_unread_declarations_all_cross(product_image):
    """A cropped panel names more than one declaration at once."""
    run = _run(product_image, _CROPPED_PIPELINE)

    assert set(run.unread_declarations.values_list("field_key", flat=True)) == {
        "retail_sale_price",
        "best_before",
    }


# --- the two collections stay apart -----------------------------------------


def test_an_unread_declaration_never_becomes_an_extracted_field(product_image):
    """Requirement the whole separate table exists to enforce.

    A value-less `ExtractedLabelField` would make `field_presence` PASS, which
    would record an unreadable declaration as a declared one.
    """
    run = _run(product_image, _EDGE_ON_PIPELINE)

    assert run.fields.count() == 0
    assert run.unread_declarations.count() == 1


def test_a_field_that_was_read_and_one_that_was_not_land_in_different_tables(
    product_image,
):
    run = _run(product_image, _CROPPED_PIPELINE)

    assert set(run.fields.values_list("field_key", flat=True)) == {"net_quantity"}
    assert "net_quantity" not in set(
        run.unread_declarations.values_list("field_key", flat=True)
    )


def test_a_run_with_nothing_unread_writes_no_rows(product_image):
    """The normal case. Every existing run and every clean photograph is this."""
    run = _run(product_image, _CLEAN_PIPELINE)

    assert run.unread_declarations.count() == 0
    assert run.fields.count() == 1


def test_deleting_a_run_takes_its_unread_declarations_with_it(product_image):
    """CASCADE, same as the fields: an orphan observation cites nothing."""
    run = _run(product_image, _EDGE_ON_PIPELINE)
    run_id = run.pk

    run.delete()

    assert not UnreadLabelDeclaration.objects.filter(run_id=run_id).exists()


# --- the diagnostics copy is still there ------------------------------------


def test_the_raw_metadata_copy_is_still_persisted(product_image):
    """The rows are the compliance engine's copy; `raw_output` stays the record.

    Keeping both is deliberate. `raw_output` is the engine's verbatim output
    and is what a run is re-analysed from months later; the rows are what a
    check queries. If these ever disagree, the verbatim copy is the evidence.
    """
    run = _run(product_image, _EDGE_ON_PIPELINE)

    reported = run.raw_output["metadata"]["unread_declarations"]

    assert [item["key"] for item in reported] == ["retail_sale_price"]
    assert reported[0]["evidence_text"] == "MRP"


def test_the_persisted_run_stays_json_safe(product_image):
    """`raw_output` is a JSONField and the rows carry a JSONField too.

    A non-serialisable value here is a 500 at request time, in Django, from an
    `ml/` change.
    """
    run = _run(product_image, _EDGE_ON_PIPELINE)

    json.dumps(run.raw_output)
    for unread in run.unread_declarations.all():
        json.dumps(unread.bounding_box)


def test_the_rows_agree_with_the_verbatim_copy(product_image):
    """Two representations of one fact must not drift at the moment of writing."""
    run = _run(product_image, _CROPPED_PIPELINE)

    from_rows = {
        (u.field_key, u.evidence_text) for u in run.unread_declarations.all()
    }
    from_raw = {
        (item["key"], item["evidence_text"])
        for item in run.raw_output["metadata"]["unread_declarations"]
    }

    assert from_rows == from_raw


# --- malformed engine output ------------------------------------------------
#
# `metadata` is a plain mapping any pipeline can populate, so this is the point
# at which a third-party or future engine's mistake would otherwise reach the
# compliance engine. Each case below is dropped and logged rather than raised:
# one malformed observation must not cost the declarations that *were* read,
# which is the same policy the ML pipeline applies one layer up.


class _Result:
    """The two attributes `_unread_rows` reads, without a pipeline run."""

    def __init__(self, metadata):
        self.metadata = metadata
        self.engine_name = "backend-test-malformed"


def test_a_missing_metadata_key_is_normal_and_yields_nothing(completed_run):
    """A pipeline with no field extractor reports nothing here. Not an error."""
    assert _unread_rows(completed_run, _Result({})) == []


@pytest.mark.parametrize("value", [None, "MRP", 42, {"key": "retail_sale_price"}])
def test_a_non_list_value_is_ignored_rather_than_crashing_the_run(
    completed_run, value
):
    assert _unread_rows(completed_run, _Result({"unread_declarations": value})) == []


@pytest.mark.parametrize(
    "entry",
    [
        {"key": "retail_sale_price"},                       # no evidence at all
        {"key": "retail_sale_price", "evidence_text": ""},  # blank evidence
        {"evidence_text": "MRP"},                           # no key
        {"key": "", "evidence_text": "MRP"},                # empty key
        "retail_sale_price",                                # not a mapping
        None,
    ],
)
def test_an_entry_without_a_key_or_evidence_is_dropped(completed_run, entry):
    """An observation nobody can check is an unfalsifiable claim."""
    rows = _unread_rows(completed_run, _Result({"unread_declarations": [entry]}))

    assert rows == []


def test_a_key_outside_the_ml_vocabulary_is_dropped(completed_run):
    """The same guard `_validated_key` gives an extracted field.

    A key no rule can name is a row that silently does nothing, which is worse
    than no row: it looks like the mechanism worked.
    """
    rows = _unread_rows(
        completed_run,
        _Result(
            {"unread_declarations": [{"key": "net_qty", "evidence_text": "NET QTY"}]}
        ),
    )

    assert rows == []


def test_one_malformed_entry_does_not_discard_the_valid_ones(completed_run):
    """The policy that matters: a bad observation costs itself, nothing more."""
    rows = _unread_rows(
        completed_run,
        _Result(
            {
                "unread_declarations": [
                    {"key": "not-a-key", "evidence_text": "junk"},
                    {"key": "retail_sale_price", "evidence_text": "MRP"},
                    {"key": "best_before", "evidence_text": ""},
                    {"key": "net_quantity", "evidence_text": "NET QUANTITY :"},
                ]
            }
        ),
    )

    assert [row.field_key for row in rows] == ["retail_sale_price", "net_quantity"]


def test_an_unrecognised_extra_diagnostic_key_is_tolerated(completed_run):
    """An engine adding a field of its own must not break persistence."""
    [row] = _unread_rows(
        completed_run,
        _Result(
            {
                "unread_declarations": [
                    {
                        "key": "retail_sale_price",
                        "evidence_text": "MRP",
                        "box": None,
                        "confidence": None,
                        "engine_note": "foreshortened",
                    }
                ]
            }
        ),
    )

    assert row.field_key == "retail_sale_price"
    assert row.evidence_text == "MRP"


def test_the_metadata_key_matches_what_the_ml_layer_actually_emits(product_image):
    """Guards the string this whole integration hangs on.

    `_UNREAD_METADATA_KEY` is a literal on the backend side. If the ML layer
    renamed the key, nothing would raise - the backend would simply stop
    finding any unread declarations, and `field_presence` would quietly go back
    to reporting them as missing declarations. That is a silent regression, and
    this is the test that makes it loud.
    """
    run = _run(product_image, _EDGE_ON_PIPELINE)

    assert (
        extraction_service._UNREAD_METADATA_KEY in run.raw_output["metadata"]
    ), "the ML layer no longer reports unread declarations under this key"
    assert run.unread_declarations.count() == 1
