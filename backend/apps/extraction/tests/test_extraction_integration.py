"""The integration boundary: upload -> ProductImage -> run -> fields.

The three existing service test files each hold one end of this steady:
`test_extraction_service.py` pins the placeholder path, `..._ocr.py` pins what a
reading looks like once persisted, and `test_pipeline_contract.py` pins that a
real extractor's conclusions survive into a compliance check. What none of them
covered is the *joins* - the places where the pieces meet and where a defect is
silent rather than loud:

- an upload reaching extraction without having gone through validation;
- a run whose fields belong to some other run;
- an engine that breaks its output contract, and whose junk is written anyway;
- a failure that leaves no record, so the image sits in PROCESSING forever;
- a partial write, leaving a run marked COMPLETED with half its readings.

Every one of those produces a database that looks fine and answers wrongly.
That is why they are pinned here rather than left to be noticed later.

Nothing in this file asserts a legal requirement, and nothing asserts what the
extractor *should* conclude - that is `ml/tests/`' job. These are backend
guarantees only: whatever the ML layer concluded arrives intact, or is refused.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection

from labelextract import registry
from labelextract.contracts import (
    BoundingBox,
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    ImageRef,
    LabelFieldKey,
    OcrResult,
    TextBlock,
)
from labelextract.exceptions import OcrFailureError
from labelextract.interfaces import FieldExtractor, OcrEngine
from labelextract.pipeline import ExtractionPipeline

from apps.extraction.models import ExtractedLabelField, ExtractionRun
from apps.extraction.services import extraction_service
from apps.extraction.services.extraction_service import (
    ExtractionOutcome,
    MalformedExtractionResult,
    ingest_and_extract,
    run_extraction,
)
from apps.images.models import ProductImage

pytestmark = pytest.mark.django_db

_VERSION = "0.0.0-integration"


# --- test doubles -----------------------------------------------------------
#
# Deterministic and offline on purpose. Nothing here reaches an OCR binary or a
# network service: a suite that needed either would fail on a fresh clone and
# would be measuring recognition rather than integration.


class _ScriptedOcrEngine(OcrEngine):
    """Returns fixed lines. The only faked component on the success paths."""

    name = "integration-ocr"
    version = _VERSION

    def __init__(self, lines: tuple[str, ...]) -> None:
        self._lines = lines

    def recognise(self, image: ImageRef) -> OcrResult:
        return OcrResult(
            blocks=tuple(
                TextBlock(
                    text=line,
                    box=BoundingBox(x=2, y=2 + i * 20, width=200, height=16),
                    confidence=0.8,
                )
                for i, line in enumerate(self._lines)
            ),
            raw={"engine": "integration-ocr"},
        )


class _TwoFieldExtractor(FieldExtractor):
    """One confident reading and one explicitly uncertain one."""

    name = "integration-fields"
    version = _VERSION

    def extract(self, ocr: OcrResult, image: ImageRef):
        return (
            ExtractedField(
                key=LabelFieldKey.NET_QUANTITY,
                raw_value="Net Qty: 500 g",
                normalized_value={
                    "base_quantity": 500,
                    "base_unit": "g",
                    "uncertain": False,
                },
                confidence=0.8,
                box=BoundingBox(x=2, y=22, width=200, height=16),
            ),
            ExtractedField(
                key=LabelFieldKey.DATE_OF_MANUFACTURE,
                raw_value="Mfg: 03/04/2025",
                normalized_value={
                    "uncertain": True,
                    "uncertainty_reasons": ["DD/MM and MM/DD both parse"],
                    "candidates": ["2025-04-03", "2025-03-04"],
                },
                confidence=None,
                box=None,
            ),
        )


class _BrokenPipeline:
    """Returns whatever it was given, in place of an `ExtractionResult`.

    Registered through the real registry, because the registry is not - and
    should not be - type-checked: it stores factories. That is precisely why
    the service has to check what comes back out of one.
    """

    def __init__(self, payload: object) -> None:
        self._payload = payload

    is_placeholder = False

    def run(self, image: ImageRef) -> object:
        return self._payload


def _register(name: str, factory) -> None:
    """Register once per process; the registry rejects duplicates on purpose."""
    if (name, _VERSION) not in list(registry.available_pipelines()):
        registry.register_pipeline(name, _VERSION, factory)


_READING = "integration-reading"
_FAILING = "integration-failing"

_register(
    _READING,
    lambda: ExtractionPipeline(
        name=_READING,
        version=_VERSION,
        ocr_engine=_ScriptedOcrEngine(("Net Qty: 500 g", "Mfg: 03/04/2025")),
        field_extractor=_TwoFieldExtractor(),
    ),
)


class _FailingOcrEngine(OcrEngine):
    name = "integration-failing-ocr"
    version = _VERSION

    def recognise(self, image: ImageRef) -> OcrResult:
        raise OcrFailureError("the OCR service fell over")


_register(
    _FAILING,
    lambda: ExtractionPipeline(
        name=_FAILING, version=_VERSION, ocr_engine=_FailingOcrEngine()
    ),
)


class _TransactionProbePipeline:
    """Records whether a transaction was open while the engine was running."""

    is_placeholder = False

    def __init__(self) -> None:
        self.in_atomic_block: bool | None = None

    def run(self, image: ImageRef) -> ExtractionResult:
        self.in_atomic_block = connection.in_atomic_block
        return ExtractionResult(
            status=ExtractionStatus.EMPTY,
            engine_name=_PROBE,
            engine_version=_VERSION,
            processing_ms=0,
        )


_PROBE = "integration-transaction-probe"
#: The registry caches instances, so the object the service resolves is this
#: one and the test can read what it observed.
_PROBE_PIPELINE = _TransactionProbePipeline()
_register(_PROBE, lambda: _PROBE_PIPELINE)

#: Each entry is a distinct way for an engine to break its output contract.
_MALFORMED = {
    "malformed-not-a-result": {"status": "completed"},
    "malformed-status": ExtractionResult(
        status="banana",
        engine_name="broken",
        engine_version=_VERSION,
        processing_ms=1,
    ),
    "malformed-processing-ms": ExtractionResult(
        status=ExtractionStatus.COMPLETED,
        engine_name="broken",
        engine_version=_VERSION,
        processing_ms=-5,
        ocr=OcrResult(blocks=(TextBlock(text="something"),)),
    ),
    "malformed-processing-ms-overflow": ExtractionResult(
        status=ExtractionStatus.COMPLETED,
        engine_name="broken",
        engine_version=_VERSION,
        # The shape of a real engine bug: a wall-clock epoch where an elapsed
        # time belongs. `processing_ms` is a 32-bit column, so without a bound
        # here this arrives as a database error naming nothing - the exact
        # outcome the check exists to replace with a message naming the engine.
        processing_ms=1_700_000_000_000,
        ocr=OcrResult(blocks=(TextBlock(text="something"),)),
    ),
    "malformed-field-key": ExtractionResult(
        status=ExtractionStatus.COMPLETED,
        engine_name="broken",
        engine_version=_VERSION,
        processing_ms=1,
        ocr=OcrResult(blocks=(TextBlock(text="Net Qty 500 g"),)),
        # A plain string where the vocabulary is required. The column would
        # accept it, and the compliance engine would then never match it.
        fields=(ExtractedField(key="net_quantity", raw_value="500 g"),),
    ),
    "malformed-normalized-value": ExtractionResult(
        status=ExtractionStatus.COMPLETED,
        engine_name="broken",
        engine_version=_VERSION,
        processing_ms=1,
        ocr=OcrResult(blocks=(TextBlock(text="Mfg 2025"),)),
        fields=(
            ExtractedField(
                key=LabelFieldKey.DATE_OF_MANUFACTURE,
                raw_value="2025",
                normalized_value={"parsed": datetime(2025, 4, 3)},
            ),
        ),
    ),
    "malformed-raw-output": ExtractionResult(
        status=ExtractionStatus.COMPLETED,
        engine_name="broken",
        engine_version=_VERSION,
        processing_ms=1,
        ocr=OcrResult(
            blocks=(TextBlock(text="text"),),
            # A Path in engine diagnostics: plausible, and not JSON.
            raw={"source": Path("/tmp/whatever.png")},
        ),
    ),
}

for _name, _payload in _MALFORMED.items():
    _register(_name, lambda payload=_payload: _BrokenPipeline(payload))


def _run(image: ProductImage, pipeline: str) -> ExtractionRun:
    return run_extraction(image, engine_name=pipeline, engine_version=_VERSION)


# --- A. a successful extraction is persisted end to end ---------------------


def test_an_upload_travels_the_whole_flow_in_one_call(png_upload, media_root, product):
    """upload -> ProductImage -> ExtractionRun -> ExtractedLabelField."""
    outcome = ingest_and_extract(
        png_upload,
        product=product,
        view_type=ProductImage.ViewType.BACK,
        engine_name=_READING,
        engine_version=_VERSION,
    )

    assert isinstance(outcome, ExtractionOutcome)
    assert outcome.succeeded is True
    assert outcome.image.pk is not None
    assert outcome.image.view_type == ProductImage.ViewType.BACK
    assert outcome.run.status == ExtractionRun.Status.COMPLETED
    assert outcome.run.fields.count() == 2


def test_the_outcome_names_the_image_the_run_was_about(png_upload, media_root):
    outcome = ingest_and_extract(
        png_upload, engine_name=_READING, engine_version=_VERSION
    )

    assert outcome.run.image_id == outcome.image.pk


def test_the_image_ends_in_processed_after_a_successful_run(png_upload, media_root):
    outcome = ingest_and_extract(
        png_upload, engine_name=_READING, engine_version=_VERSION
    )
    outcome.image.refresh_from_db()

    assert outcome.image.status == ProductImage.Status.PROCESSED


def test_the_returned_image_reports_its_status_without_being_reloaded(
    png_upload, media_root
):
    """The object handed back must not disagree with the row it describes.

    Status is written with `QuerySet.update()`, which by design never touches
    the Python instance. The test above reloads before asserting, so it cannot
    see that - but `docs/api.md` tells the future endpoint to serialise exactly
    this object, and a serializer does not reload. Left unmirrored, the first
    response the UI ever sees reports `uploaded` for an image that has finished
    processing.
    """
    outcome = ingest_and_extract(
        png_upload, engine_name=_READING, engine_version=_VERSION
    )

    assert outcome.image.status == ProductImage.Status.PROCESSED


# --- B. repeat processing -----------------------------------------------------


def test_each_run_over_the_same_image_is_a_separate_record(product_image):
    """Re-processing is supported, not deduplicated.

    Comparing a new engine against an old one on the same photograph is the
    whole reason `ExtractionRun` is a foreign key rather than a one-to-one.
    """
    first = _run(product_image, _READING)
    second = _run(product_image, _READING)

    assert first.pk != second.pk
    assert product_image.extraction_runs.count() == 2


def test_a_second_run_does_not_overwrite_the_first(product_image):
    """The earlier run keeps its own status, timings and readings.

    A compliance result cites a specific run. If a re-run edited that row, the
    finding would silently start referring to readings that never produced it.
    """
    first = _run(product_image, _READING)
    first_completed_at = first.completed_at

    _run(product_image, _READING)

    reloaded = ExtractionRun.objects.get(pk=first.pk)
    assert reloaded.status == ExtractionRun.Status.COMPLETED
    assert reloaded.completed_at == first_completed_at
    assert reloaded.fields.count() == 2


def test_fields_belong_to_the_run_that_read_them(product_image):
    """No field is shared, re-parented, or duplicated across runs."""
    first = _run(product_image, _READING)
    second = _run(product_image, _READING)

    first_ids = set(first.fields.values_list("pk", flat=True))
    second_ids = set(second.fields.values_list("pk", flat=True))

    assert first_ids and second_ids
    assert first_ids.isdisjoint(second_ids)
    assert ExtractedLabelField.objects.filter(run=first).count() == 2
    assert ExtractedLabelField.objects.filter(run=second).count() == 2


def test_a_failed_re_run_does_not_disturb_an_earlier_good_one(product_image):
    """The interesting ordering: success first, failure second.

    The image status follows the latest attempt, but the earlier run - and the
    readings a compliance result may already cite - must be untouched.
    """
    good = _run(product_image, _READING)
    bad = _run(product_image, _FAILING)

    good.refresh_from_db()
    assert good.status == ExtractionRun.Status.COMPLETED
    assert good.fields.count() == 2
    assert bad.status == ExtractionRun.Status.FAILED
    assert bad.fields.count() == 0


# --- C. uncertainty survives persistence ------------------------------------


def test_an_uncertain_reading_stays_marked_uncertain(product_image):
    """A guess must never become indistinguishable from a measurement."""
    run = _run(product_image, _READING)
    date = run.fields.get(field_key="date_of_manufacture")

    assert date.normalized_value["uncertain"] is True
    assert date.normalized_value["candidates"] == ["2025-04-03", "2025-03-04"]
    assert date.normalized_value["uncertainty_reasons"]


def test_an_unreported_confidence_is_stored_as_null_not_zero(product_image):
    """NULL means "the engine did not say". Zero would be a claim it never made."""
    run = _run(product_image, _READING)

    assert run.fields.get(field_key="date_of_manufacture").confidence is None
    assert run.fields.get(field_key="net_quantity").confidence == pytest.approx(0.8)


def test_the_unread_declaration_channel_survives_into_raw_output(product_image):
    """`raw_output["metadata"]` is where "named but unreadable" lives.

    It has no column of its own, so a reshape of `raw_output` would silently
    delete the distinction between "the package declares no MRP" and "the MRP
    was printed too small to read". Pinned here as a persistence contract; what
    the extractor puts in it is `ml/tests/`' business.
    """
    run = _run(product_image, _READING)

    assert "unread_declarations" in run.raw_output["metadata"]


# --- D. failure is recorded as failure --------------------------------------


def test_an_engine_failure_produces_a_failed_run_and_no_readings(product_image):
    run = _run(product_image, _FAILING)

    assert run.status == ExtractionRun.Status.FAILED
    assert run.error_code == "ocr_failed"
    assert run.error_message
    assert run.fields.count() == 0


def test_a_failed_run_is_not_usable_output(product_image):
    """The flag the compliance engine reads to avoid reporting a bad photo.

    If this were True, an unreadable photograph would look exactly like a
    package that declared nothing.
    """
    run = _run(product_image, _FAILING)

    assert run.produced_usable_output is False


def test_a_failed_run_leaves_the_image_marked_failed_not_processing(product_image):
    """An image stuck in PROCESSING is a queue leak with no explanation."""
    _run(product_image, _FAILING)
    product_image.refresh_from_db()

    assert product_image.status == ProductImage.Status.FAILED


def test_the_caller_s_image_object_reports_failure_without_being_reloaded(
    product_image,
):
    """The same mirroring guarantee on the path that matters most.

    A caller that reacts to a failed run by inspecting the image it passed in
    would otherwise be told the image is still `uploaded`, which reads as "not
    attempted yet" rather than "attempted and failed".
    """
    _run(product_image, _FAILING)

    assert product_image.status == ProductImage.Status.FAILED


def test_an_image_row_with_no_stored_file_is_a_recorded_failure(
    db, product, media_root
):
    """Not a crash: an unusable row is a fact about the image.

    `build_image_ref` cannot produce a path for it, and the honest outcome is
    the same `invalid_image` a deleted file gets.
    """
    orphan = ProductImage.objects.create(
        product=product,
        original_filename="never-stored.png",
        content_type="image/png",
        image_format="png",
        size_bytes=0,
        width=64,
        height=64,
        checksum_sha256="0" * 64,
    )

    run = run_extraction(orphan, engine_name=_READING, engine_version=_VERSION)

    assert run.status == ExtractionRun.Status.FAILED
    assert run.error_code == "invalid_image"


def test_an_unsaved_image_is_a_programming_error_not_a_run(db, media_root):
    """There is nothing for a run to be about, so nothing is recorded."""
    with pytest.raises(ValueError):
        run_extraction(ProductImage())

    assert ExtractionRun.objects.count() == 0


@pytest.mark.parametrize("bad_input", [None, "not-an-image", 42])
def test_a_non_image_argument_is_refused(db, bad_input):
    with pytest.raises(ValueError):
        run_extraction(bad_input)


# --- E. a malformed result is refused, not written --------------------------


@pytest.mark.parametrize("pipeline", sorted(_MALFORMED))
def test_a_malformed_result_is_refused(product_image, pipeline):
    """The database is permissive here; this layer is not.

    `field_key` has no choices, `raw_output` and `normalized_value` take any
    JSON. Every case in `_MALFORMED` would therefore be *accepted* by the
    columns and only go wrong later - a reading the compliance engine never
    matches, or a run whose diagnostics cannot be read back.
    """
    with pytest.raises(MalformedExtractionResult):
        _run(product_image, pipeline)


@pytest.mark.parametrize("pipeline", sorted(_MALFORMED))
def test_a_malformed_result_writes_no_readings(product_image, pipeline):
    with pytest.raises(MalformedExtractionResult):
        _run(product_image, pipeline)

    assert ExtractedLabelField.objects.count() == 0


@pytest.mark.parametrize("pipeline", sorted(_MALFORMED))
def test_a_malformed_result_still_leaves_a_failed_run_behind(
    product_image, pipeline
):
    """The bug is raised *and* recorded.

    Raising alone would leave the image in PROCESSING with no explanation;
    recording alone would file an engine bug away as "the photo was
    unreadable". Both, and neither instead of the other.
    """
    with pytest.raises(MalformedExtractionResult):
        _run(product_image, pipeline)

    run = ExtractionRun.objects.get(image=product_image)
    assert run.status == ExtractionRun.Status.FAILED
    assert run.error_code == "internal_error"
    assert run.error_message == "MalformedExtractionResult"

    product_image.refresh_from_db()
    assert product_image.status == ProductImage.Status.FAILED


def test_a_write_that_fails_part_way_leaves_no_half_result(
    product_image, monkeypatch
):
    """A run marked COMPLETED with half its readings is the worst outcome.

    It is indistinguishable from a package that declared fewer things than it
    did, and nothing anywhere reports an error. The readings and the run's
    final state are written in one block so that cannot happen.
    """

    def _explode(*args, **kwargs):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(
        ExtractedLabelField.objects, "bulk_create", _explode
    )

    with pytest.raises(RuntimeError):
        _run(product_image, _READING)

    run = ExtractionRun.objects.get(image=product_image)
    assert run.status == ExtractionRun.Status.FAILED
    assert run.error_code == "internal_error"
    assert run.fields.count() == 0
    assert run.produced_usable_output is False

    # The recognised text is kept rather than blanked. It is diagnostic context
    # for whoever investigates, and it cannot be mistaken for a usable reading:
    # the run is FAILED, so `produced_usable_output` is False and the
    # compliance engine treats it as inconclusive.
    assert "Net Qty: 500 g" in run.recognised_text


# --- F. traceability --------------------------------------------------------


def test_a_stored_reading_can_be_traced_back_to_the_bytes_it_came_from(
    png_upload, media_root, product
):
    """image -> run -> field, and the run names the engine that produced it.

    This is the chain a reviewer walks when someone disputes a finding. Every
    link is asserted from the field end, because that is the direction the
    question is actually asked in.
    """
    outcome = ingest_and_extract(
        png_upload, product=product, engine_name=_READING, engine_version=_VERSION
    )

    field = ExtractedLabelField.objects.get(
        run=outcome.run, field_key="net_quantity"
    )

    # Which extraction attempt produced it, and with what.
    assert field.run_id == outcome.run.pk
    assert field.run.engine_name == _READING
    assert field.run.engine_version == _VERSION
    assert field.run.started_at is not None
    assert field.run.completed_at is not None

    # Which image, and which exact bytes.
    assert field.run.image_id == outcome.image.pk
    assert field.run.image.checksum_sha256 == outcome.image.checksum_sha256

    # What was read, and where it was read from.
    assert field.raw_value == "Net Qty: 500 g"
    assert field.normalized_value["base_quantity"] == 500
    assert field.bounding_box == {"x": 2, "y": 22, "width": 200, "height": 16}

    # And what the engine recognised overall, for context.
    assert "Net Qty: 500 g" in field.run.recognised_text


def test_the_placeholder_flag_reaches_the_row(product_image):
    """A real engine's output must not be marked placeholder, or vice versa.

    The API surfaces this so the UI can never present wiring output as a
    reading.
    """
    real = _run(product_image, _READING)
    placeholder = run_extraction(product_image)

    assert real.is_placeholder is False
    assert placeholder.is_placeholder is True


# --- G. the integration cannot bypass validation or storage safety ----------


@pytest.mark.parametrize(
    ("name", "payload", "content_type"),
    [
        ("photo.png", b"#!/bin/sh\necho pwned\n", "image/png"),
        ("payload.php", None, "image/png"),
        ("label.png", None, "application/pdf"),
    ],
)
def test_a_rejected_upload_never_reaches_extraction(
    png_bytes, media_root, name, payload, content_type
):
    """The refusal happens before any row or run exists.

    A run created for a rejected upload would be a record of analysing
    something that was never stored.
    """
    body = png_bytes if payload is None else payload

    with pytest.raises(ValidationError):
        ingest_and_extract(
            SimpleUploadedFile(name, body, content_type=content_type),
            engine_name=_READING,
            engine_version=_VERSION,
        )

    assert ProductImage.objects.count() == 0
    assert ExtractionRun.objects.count() == 0


def test_extraction_reads_the_generated_path_not_the_client_filename(
    png_bytes, media_root
):
    """What the ML layer is handed is our path, never the uploader's string."""
    outcome = ingest_and_extract(
        SimpleUploadedFile(
            "../../escape.png", png_bytes, content_type="image/png"
        ),
        engine_name=_READING,
        engine_version=_VERSION,
    )

    ref = extraction_service.build_image_ref(outcome.image)

    assert ref.path.exists()
    assert "escape" not in ref.path.name
    assert Path(media_root).resolve() in ref.path.resolve().parents


def test_the_image_ref_carries_measured_facts_not_claimed_ones(
    png_bytes, media_root
):
    """A PNG announced as a JPEG reaches the engine as a PNG."""
    outcome = ingest_and_extract(
        SimpleUploadedFile("label.jpg", png_bytes, content_type="image/jpg"),
        engine_name=_READING,
        engine_version=_VERSION,
    )

    ref = extraction_service.build_image_ref(outcome.image)

    assert ref.image_format == "png"
    assert ref.size_bytes == len(png_bytes)
    assert ref.width == 64 and ref.height == 64


# --- H. the transaction shape the failure record depends on -----------------


@pytest.mark.django_db(transaction=True)
def test_the_run_row_is_written_outside_any_transaction_of_our_own(
    png_bytes, media_root
):
    """The service must not wrap itself in a transaction, or the record dies.

    Everything else in this file runs inside pytest-django's wrapping
    transaction, which makes the service's own `atomic()` a savepoint and hides
    the top-level boundary entirely. `transaction=True` removes that wrapper, so
    this is the only place the production shape is actually exercised.

    The assertion is deliberately about the boundary rather than about a row:
    if `run_extraction` were atomic as a whole - as it was before this
    integration - the run row would still be *visible* to this connection, and a
    test that merely queried for it would pass while the guarantee was gone. It
    is the absence of an open transaction that makes the failure record survive
    a re-raise, so that is what is pinned.
    """
    _PROBE_PIPELINE.in_atomic_block = None
    image = ProductImage.objects.create(
        image=SimpleUploadedFile("label.png", png_bytes, content_type="image/png"),
        original_filename="label.png",
        content_type="image/png",
        image_format="png",
        size_bytes=len(png_bytes),
        width=64,
        height=64,
        checksum_sha256="0" * 64,
    )

    run = run_extraction(image, engine_name=_PROBE, engine_version=_VERSION)

    assert _PROBE_PIPELINE.in_atomic_block is False
    assert run.status == ExtractionRun.Status.EMPTY


# --- the boundary itself ----------------------------------------------------


def test_the_ml_package_does_not_import_django():
    """The dependency direction is one-way, and stays that way.

    `labelextract` must be usable from a CLI, a notebook or a training script
    with no settings configured. A single `from django...` anywhere in it would
    make the whole package require a Django environment, and would let database
    logic drift into the ML layer where it cannot be tested without one.
    """
    package_root = Path(extraction_service.registry.__file__).parent
    offenders = [
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*.py")
        if "django" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_only_the_extraction_service_reaches_the_ml_runtime():
    """One seam for the engine, so swapping one stays a one-file change.

    The line is drawn around the *runtime*, not the whole package.
    `labelextract.contracts` is a shared vocabulary with no engine dependencies
    - `apps.rules.checks.field_presence` imports `LabelFieldKey` from it so a
    rule and a reading can agree on what a field is called, which is the point
    of having one vocabulary rather than two. What must stay in one place is
    everything that *runs* an engine: `registry`, `pipeline`, `interfaces` and
    the engines themselves. An import of those elsewhere would fail nothing at
    all - it would just quietly make the boundary stop being a boundary.

    Only real import statements count: several modules mention `labelextract`
    in prose explaining this, and documenting a boundary is not crossing it.
    """
    backend_root = Path(__file__).resolve().parents[3]
    #: Anything under `labelextract` except the dependency-free contracts
    #: module. `labelextract.exceptions` is deliberately on the runtime side:
    #: catching an engine's failures is running one.
    imports_ml_runtime = re.compile(
        r"^\s*(?:from|import)\s+labelextract(?!\.contracts\b)\b", re.MULTILINE
    )
    offenders = sorted(
        path.relative_to(backend_root).as_posix()
        for path in backend_root.rglob("*.py")
        if "tests" not in path.parts
        and imports_ml_runtime.search(path.read_text(encoding="utf-8"))
    )

    assert offenders == ["apps/extraction/services/extraction_service.py"]


def test_no_backend_module_outside_extraction_imports_an_engine():
    """The stricter half: no app may reach an OCR implementation directly.

    Separate from the test above because this is the one that would matter on
    the day a real engine ships. Importing `labelextract.ocr.tesseract` from a
    view would work perfectly, and would pin the whole system to Tesseract in a
    file nobody thinks of as ML code.
    """
    backend_root = Path(__file__).resolve().parents[3]
    seam = backend_root / "apps/extraction/services/extraction_service.py"
    # Both spellings, since `from labelextract import registry` and
    # `from labelextract.registry import get_pipeline` bind the same thing.
    imports_engine = re.compile(
        r"^\s*(?:from\s+labelextract\s+import\s+[\w,\s]*\b"
        r"(?:ocr|baseline|preprocessing|fields|pipeline|registry)\b"
        r"|(?:from|import)\s+labelextract\."
        r"(?:ocr|baseline|preprocessing|fields|pipeline|registry)\b)",
        re.MULTILINE,
    )
    offenders = sorted(
        path.relative_to(backend_root).as_posix()
        for path in backend_root.rglob("*.py")
        if "tests" not in path.parts
        and path != seam
        and imports_engine.search(path.read_text(encoding="utf-8"))
    )

    assert offenders == []
    # ...and the seam really is one, so this test cannot pass by the pattern
    # simply never matching anything.
    assert imports_engine.search(seam.read_text(encoding="utf-8"))
