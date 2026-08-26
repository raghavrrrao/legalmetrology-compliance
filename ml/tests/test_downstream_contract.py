"""What consumers of this package are allowed to rely on.

Every other test file asks whether a component behaves correctly. This one asks
a different question: **would a change here break the Django backend, the API
response, or a stored run, without any test in `ml/` noticing?**

The three consumers, and what each of them reads
------------------------------------------------
`backend/apps/extraction/services/extraction_service.py` is the only module in
the backend that imports `labelextract`. It copies:

    result.status                 -> ExtractionRun.status      (mapped enum)
    result.error_code             -> ExtractionRun.error_code  (CharField)
    result.ocr.full_text          -> ExtractionRun.recognised_text
    result.ocr.raw    ─┐
    result.metadata    ├────────► ExtractionRun.raw_output     (JSONField)
    len(ocr.blocks)   ─┘
    result.fields[*]              -> ExtractedLabelField rows

`backend/apps/rules/checks/field_presence.py` reads `LabelFieldKey` and
validates every rule's `field_key` against it at load time.

`labelextract.cli` prints the same shape a developer compares against a stored
run.

Why a JSON test rather than an eyeball
--------------------------------------
`raw_output` is a `JSONField`. Anything in `metadata` or `ocr.raw` that is not
JSON-serialisable - a `Path`, an `Enum`, a `Decimal`, a `set` - raises at
`run.save()`, in Django, at request time, on a code path no test in `ml/`
exercises. The failure would look like a backend bug and would be introduced by
an `ml/` change. That is exactly the kind of break this file exists to catch on
the side that caused it.

These tests need no Pillow, no pytesseract and no binary. Stub components stand
in for the engine, because what is under test is the *shape* of what comes out,
not what any engine reads.
"""

from __future__ import annotations

import json

import pytest

from labelextract import contracts, exceptions
from labelextract.contracts import (
    BoundingBox,
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    ImageRef,
    LabelFieldKey,
    OcrResult,
    TextBlock,
    UnreadDeclaration,
)
from labelextract.interfaces import FieldExtractor, OcrEngine
from labelextract.pipeline import ExtractionPipeline


class _StubOcrEngine(OcrEngine):
    name = "stub-ocr"
    version = "1.0.0"

    def __init__(self, blocks=()):
        self._blocks = blocks

    def recognise(self, image: ImageRef) -> OcrResult:
        return OcrResult(blocks=self._blocks, raw={"engine": self.name, "words": []})


class _StubFieldExtractor(FieldExtractor):
    name = "stub-fields"
    version = "1.0.0"

    def __init__(self, fields=(), unread=()):
        self._fields = fields
        self._unread = unread

    def extract(self, ocr, image):
        return self._fields

    def unread_declarations(self, ocr, fields):
        return self._unread


def _populated_pipeline() -> ExtractionPipeline:
    """A pipeline whose result carries one of everything a consumer reads."""
    block = TextBlock(
        text="MRP : 349.00 INCL. OF ALL TAXES",
        box=BoundingBox(x=4, y=8, width=300, height=20),
        confidence=0.87,
    )
    extracted = ExtractedField(
        key=LabelFieldKey.RETAIL_SALE_PRICE,
        raw_value="MRP : 349.00 INCL. OF ALL TAXES",
        normalized_value={
            "amount": "349.00",
            "currency": "INR",
            "inclusive_of_all_taxes": True,
            "uncertain": False,
            "matched_by": "keyword",
        },
        confidence=0.87,
        box=BoundingBox(x=4, y=8, width=300, height=20),
    )
    unread = UnreadDeclaration(
        key=LabelFieldKey.NET_QUANTITY,
        evidence_text="NET QUANTITY :",
        box=BoundingBox(x=4, y=40, width=120, height=18),
        confidence=0.61,
    )
    return ExtractionPipeline(
        name="contract-probe",
        version="1.0.0",
        ocr_engine=_StubOcrEngine(blocks=(block,)),
        field_extractor=_StubFieldExtractor(fields=(extracted,), unread=(unread,)),
    )


@pytest.fixture
def result(image_ref):
    return _populated_pipeline().run(image_ref)


# --- everything the backend persists must survive a JSONField ---------------


def _as_raw_output(result: ExtractionResult) -> dict:
    """The exact structure `extraction_service._persist_result` builds."""
    return {
        "engine_raw": dict(result.ocr.raw),
        "metadata": dict(result.metadata),
        "block_count": len(result.ocr.blocks),
    }


def test_raw_output_is_json_serialisable(result):
    """A `Path` or an `Enum` in metadata is a 500 at request time, not here.

    `ExtractionRun.raw_output` is a JSONField. Django serialises it on save,
    inside a request, in a module that has no reason to suspect `ml/` of
    putting a non-JSON value there.
    """
    encoded = json.dumps(_as_raw_output(result))

    assert json.loads(encoded)["metadata"]["ocr_engine_name"] == "stub-ocr"


def test_a_failed_result_is_json_serialisable_too(image_ref):
    """The failure path persists as well, and has a different metadata shape."""
    from labelextract.exceptions import OcrFailureError

    class _Failing(_StubOcrEngine):
        def recognise(self, image):
            raise OcrFailureError("the engine aborted")

    failed = ExtractionPipeline(
        name="contract-probe", version="1.0.0", ocr_engine=_Failing()
    ).run(image_ref)

    assert failed.status is ExtractionStatus.FAILED
    json.dumps(_as_raw_output(failed))


def test_every_normalised_value_is_json_serialisable(result):
    """`ExtractedLabelField.normalized_value` is a JSONField as well.

    Normalisation deals in `Decimal` internally, and a `Decimal` that escaped
    into the mapping would break persistence for every price on every label.
    `normalise_price` returns the amount as a string for exactly this reason.
    """
    for extracted in result.fields:
        if extracted.normalized_value is not None:
            json.dumps(dict(extracted.normalized_value))


# --- the metadata keys a consumer reads by name -----------------------------

#: Every key `_metadata` emits. Pinned as a literal so *adding* one is a
#: deliberate, reviewable change rather than a silent one - a stored run's
#: shape is part of what the frontend and any future analysis read.
EXPECTED_METADATA_KEYS = frozenset(
    {
        "unread_declarations",
        "bounding_box_space",
        "preprocessing_scale",
        "preprocessed",
        "field_extraction_ran",
        "source_image_format",
        "source_dimensions",
        "preprocessed_dimensions",
        "preprocessor_name",
        "ocr_engine_name",
        "ocr_engine_version",
        "field_extractor_name",
    }
)


def test_metadata_carries_exactly_the_documented_keys(result):
    assert set(result.metadata) == EXPECTED_METADATA_KEYS


def test_unread_declarations_are_present_on_every_completed_run(image_ref):
    """The key exists whether or not anything was unread, and whether or not an
    extractor ran at all.

    A consumer that has to distinguish "no unread declarations" from "this run
    predates the mechanism" cannot do it from an absent key without guessing.
    """
    without_extractor = ExtractionPipeline(
        name="contract-probe", version="1.0.0", ocr_engine=_StubOcrEngine()
    ).run(image_ref)

    assert without_extractor.metadata["unread_declarations"] == []


def test_bounding_box_space_is_one_of_two_known_values(result):
    """A consumer drawing evidence overlays branches on this string."""
    assert result.metadata["bounding_box_space"] in ("source", "preprocessed")


# --- the unread-declaration transport ---------------------------------------


def test_an_unread_declaration_serialises_flat_and_without_a_value(result):
    """The shape a consumer parses out of `raw_output["metadata"]`.

    Four keys, no value of any kind. An unread observation that acquired a
    value would be indistinguishable from a reading, and `field_presence`
    passes on any reading.
    """
    [observation] = result.metadata["unread_declarations"]

    assert set(observation) == {"key", "evidence_text", "box", "confidence"}
    assert observation["key"] == LabelFieldKey.NET_QUANTITY.value
    assert observation["evidence_text"] == "NET QUANTITY :"
    assert observation["box"] == {"x": 4, "y": 40, "width": 120, "height": 18}
    assert observation["confidence"] == 0.61
    assert "value" not in observation
    assert "raw_value" not in observation
    assert "normalized_value" not in observation


def test_an_unread_declaration_is_never_also_an_extracted_field(result):
    """The two collections must not overlap, at the persisted boundary.

    A key appearing in both would let a presence check pass on the strength of
    a declaration nobody could read.
    """
    unread = {item["key"] for item in result.metadata["unread_declarations"]}
    extracted = {field.key.value for field in result.fields}

    assert unread.isdisjoint(extracted)


def test_the_unread_type_is_reachable_from_the_package_root():
    """A consumer must not have to import a private module to use it.

    The backend is documented as depending on this package's public API only.
    `UnreadDeclaration` was defined in `contracts` and left out of the root
    re-export, so wiring it into the rules layer would have meant reaching past
    the boundary the rest of the contracts are behind.
    """
    import labelextract

    assert labelextract.UnreadDeclaration is contracts.UnreadDeclaration
    assert "UnreadDeclaration" in labelextract.__all__


# --- the error codes the frontend branches on -------------------------------

#: Every stable code this package can put in `ExtractionRun.error_code`.
#: The frontend branches on these strings rather than on English messages, so
#: renaming one is an API change.
EXPECTED_ERROR_CODES = {
    "extraction_error": exceptions.LabelExtractError,
    "invalid_image": exceptions.InvalidImageError,
    "engine_not_available": exceptions.EngineNotAvailableError,
    "pipeline_not_found": exceptions.PipelineNotFoundError,
    "unsupported_image_format": exceptions.UnsupportedImageFormatError,
    "image_too_large": exceptions.ImageTooLargeError,
    "preprocessing_failed": exceptions.PreprocessingError,
    "ocr_failed": exceptions.OcrFailureError,
    "field_extraction_failed": exceptions.FieldExtractionError,
}


@pytest.mark.parametrize(("code", "error"), sorted(EXPECTED_ERROR_CODES.items()))
def test_each_error_keeps_its_published_code(code, error):
    assert error.code == code


def test_no_error_class_shares_a_code_with_another():
    """Two errors with one code would be indistinguishable to the UI.

    `UnsupportedImageFormatError` and `ImageTooLargeError` both subclass
    `InvalidImageError` precisely so a handler can stay broad while the code
    stays specific; that only works while the codes are distinct.
    """
    subclasses = _all_subclasses(exceptions.LabelExtractError)
    codes = [cls.code for cls in subclasses]

    assert len(codes) == len(set(codes)), f"duplicate error codes among {subclasses}"


def test_every_error_is_covered_by_this_file():
    """A new exception class must appear above, or the UI cannot branch on it."""
    defined = {cls.code for cls in _all_subclasses(exceptions.LabelExtractError)}
    defined.add(exceptions.LabelExtractError.code)

    assert defined == set(EXPECTED_ERROR_CODES)


def _all_subclasses(root: type) -> list[type]:
    found: list[type] = []
    for subclass in root.__subclasses__():
        found.append(subclass)
        found.extend(_all_subclasses(subclass))
    return found


# --- the field vocabulary ---------------------------------------------------

#: `LabelFieldKey` values, pinned. `ExtractedLabelField.field_key` stores these
#: strings and `rules` validates every rule's `field_key` against them at load
#: time, so *removing or renaming* one orphans stored rows and silently
#: disables any rule that named it. Adding one is safe and expected.
PUBLISHED_FIELD_KEYS = frozenset(
    {
        "manufacturer_name",
        "packer_name",
        "importer_name",
        "manufacturer_address",
        "common_or_generic_name",
        "net_quantity",
        "retail_sale_price",
        "unit_sale_price",
        "date_of_manufacture",
        "date_of_packing",
        "date_of_import",
        "best_before",
        "consumer_care_contact",
        "country_of_origin",
        "batch_number",
        "other",
    }
)


def test_no_published_field_key_disappears():
    """Renaming one is a data migration, not an edit."""
    current = {key.value for key in LabelFieldKey}

    assert PUBLISHED_FIELD_KEYS <= current, (
        f"these keys are stored in the database and named by rule files: "
        f"{sorted(PUBLISHED_FIELD_KEYS - current)}"
    )


def test_a_new_field_key_is_a_deliberate_addition():
    """Not a failure to fear - a reminder to add it here and to the docs."""
    current = {key.value for key in LabelFieldKey}

    assert current == PUBLISHED_FIELD_KEYS, (
        f"new extraction vocabulary: {sorted(current - PUBLISHED_FIELD_KEYS)}. "
        f"Add it above, and to ml/README.md's supported/unsupported table."
    )


def test_field_keys_are_plain_strings_when_persisted():
    """`field_key` is a CharField; an enum member must serialise to its value."""
    for key in LabelFieldKey:
        assert isinstance(key.value, str)
        assert json.dumps(key.value) == f'"{key.value}"'


# --- the field row the backend builds ---------------------------------------


def test_an_extracted_field_carries_everything_a_row_needs(result):
    """The five attributes `_persist_result` copies, and their types."""
    [extracted] = result.fields

    assert extracted.key in LabelFieldKey
    assert isinstance(extracted.raw_value, str) and extracted.raw_value
    assert isinstance(extracted.normalized_value, dict)
    assert 0.0 <= extracted.confidence <= 1.0
    assert extracted.box.as_dict() == {"x": 4, "y": 8, "width": 300, "height": 20}


def test_a_bounding_box_serialises_to_the_four_keys_the_ui_draws():
    assert set(BoundingBox(x=0, y=0, width=1, height=1).as_dict()) == {
        "x",
        "y",
        "width",
        "height",
    }


def test_status_values_map_onto_the_three_the_backend_knows():
    """`_STATUS_MAP` in the extraction service has an entry per member.

    A fourth member added here without a matching entry there is a `KeyError`
    on a real upload.
    """
    assert {status.value for status in ExtractionStatus} == {
        "completed",
        "empty",
        "failed",
    }
