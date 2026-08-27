"""The seam between Django and the OCR/ML layer.

This module is the ONLY place in the backend that reaches the ML *runtime* -
`labelextract.registry`, `labelextract.pipeline`, `labelextract.exceptions` and
any engine behind them. That is the whole point of the boundary: if a future
engine needs a different call signature, a queue, or a GPU, this file changes
and nothing else does.

The one deliberate exception is `labelextract.contracts`, which is a
dependency-free vocabulary rather than an implementation.
`apps.rules.checks.field_presence` imports `LabelFieldKey` from it so that a
rule and a reading agree on what a field is called - one vocabulary, owned by
the ml/ package, rather than two that drift. Both boundaries are pinned by
tests in `apps/extraction/tests/test_extraction_integration.py`.

Responsibilities, in order:

    1. Turn a `ProductImage` row into a `labelextract.ImageRef`.
    2. Resolve the configured pipeline by name and version.
    3. Run it.
    4. Check the returned result against the contract before trusting it.
    5. Persist the structured result as an `ExtractionRun` plus its fields.

Explicitly NOT its responsibility: deciding what the readings mean. That is
`apps.compliance`. A run recorded here is an observation - "this is what we
read off this photograph" - never a finding about whether the package is lawful.

Transaction shape, and why it is not one block
----------------------------------------------
The failure record is the point of this service, so it has to survive whatever
went wrong. If the whole function were atomic, the `except` clause that records
a failure and re-raises would have its own record rolled back on the way out -
leaving the image stuck in PROCESSING with nothing at all explaining why, which
is the exact outcome the record exists to prevent.

So the run row is created first, and only the *result* persistence - the run's
final state plus its fields together - is wrapped in a block. A half-written
result is never visible: either a run has its fields or it is marked failed.

A caller that wraps this in its own `atomic()` (or runs under `ATOMIC_REQUESTS`)
gets the usual consequence: a re-raised exception discards the failure record
along with everything else. Callers that need the record to survive should let
this function manage its own transactions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from labelextract import registry
from labelextract.contracts import (
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    ImageRef,
    LabelFieldKey,
    OcrResult,
)
from labelextract.exceptions import InvalidImageError, LabelExtractError

from apps.extraction.models import ExtractedLabelField, ExtractionRun
from apps.images.models import ProductImage

logger = logging.getLogger(__name__)

#: Maps the ML layer's status onto the database's. They are separate enums on
#: purpose - the database records a lifecycle (including PENDING and RUNNING,
#: which the synchronous pipeline never reports), while the ML layer reports
#: only an outcome.
_STATUS_MAP = {
    ExtractionStatus.COMPLETED: ExtractionRun.Status.COMPLETED,
    ExtractionStatus.EMPTY: ExtractionRun.Status.EMPTY,
    ExtractionStatus.FAILED: ExtractionRun.Status.FAILED,
}


#: Upper bound for `ExtractionRun.processing_ms`. The column is a
#: `PositiveIntegerField`, which PostgreSQL stores as a 32-bit integer; this is
#: that column's ceiling restated where the contract is checked, not a judgement
#: about how long extraction may take.
_MAX_PROCESSING_MS = 2**31 - 1


class MalformedExtractionResult(ValueError):
    """An engine returned something this layer refuses to store.

    Deliberately not a `LabelExtractError`. Those describe an image or an engine
    that could not do its job, which is an ordinary outcome recorded and moved
    past. This describes an engine that ran and then broke its own output
    contract, which is a bug. It is recorded as a failed run - so the image does
    not sit in PROCESSING forever - and then re-raised, because a contract
    violation quietly filed away as "the photo was unreadable" is a bug nobody
    will ever be shown.
    """


@dataclass(frozen=True)
class ExtractionOutcome:
    """What one upload-through-extraction call produced.

    Deliberately thin. Everything else worth knowing hangs off `run` - its
    status, its error code, its `raw_output`, and `run.fields` - and copying any
    of that here would create a second version of it that can drift.
    """

    image: ProductImage
    run: ExtractionRun

    @property
    def succeeded(self) -> bool:
        """True only when the label was read well enough to judge against.

        False covers both "the pipeline failed" and "the photograph was
        unreadable". Neither is evidence that a declaration is missing.
        """
        return self.run.produced_usable_output


def default_pipeline_is_placeholder() -> bool:
    """Whether the configured pipeline performs real recognition.

    Used by the health endpoint so the team can see at a glance that the system
    is still running on wiring rather than a real OCR engine.

    Raises:
        PipelineNotFoundError: the configured name/version is not registered.
    """
    pipeline = registry.get_pipeline(
        settings.DEFAULT_EXTRACTION_ENGINE_NAME,
        settings.DEFAULT_EXTRACTION_ENGINE_VERSION,
    )
    return pipeline.is_placeholder


def build_image_ref(image: ProductImage) -> ImageRef:
    """Convert a stored image row into the ML layer's input contract.

    Raises:
        InvalidImageError: the row carries no reachable file. A row whose
            `image` field is empty, or whose storage backend keeps the file
            somewhere with no local path, cannot be handed to a pipeline that
            opens a path. Raising the ML layer's own error means the caller
            records it as an ordinary `invalid_image` failure rather than
            crashing - the row is unusable, which is a fact about the image and
            not a bug in this service.
    """
    try:
        path = Path(image.image.path)
    except (ValueError, NotImplementedError) as exc:
        raise InvalidImageError(
            f"Image {image.pk} has no readable file on disk"
        ) from exc

    return ImageRef(
        path=path,
        image_format=image.image_format,
        size_bytes=image.size_bytes,
        width=image.width,
        height=image.height,
    )


def run_extraction(
    image: ProductImage,
    *,
    engine_name: str | None = None,
    engine_version: str | None = None,
) -> ExtractionRun:
    """Run extraction over `image` and persist the result.

    Always returns a saved `ExtractionRun`, including when extraction failed - a
    failure is a fact about the image worth recording, and silently returning
    nothing would leave the UI unable to explain why no result appeared.

    Each call produces a *new* run. Processing the same image twice is a
    supported operation, not a mistake to be deduplicated: it is how a better
    engine is compared against an older one on the same evidence. Nothing is
    overwritten, and every `ExtractedLabelField` belongs to the run that read it.

    Runs synchronously. That is a deliberate choice for the base structure: with
    a placeholder engine there is nothing to wait for, and introducing a task
    queue now would add infrastructure with no work to do. When a real OCR
    engine makes this slow, only this function needs to move behind a queue -
    callers already treat the run as a row they poll, not a value they await.

    Raises:
        ValueError: `image` is not a saved `ProductImage`. A programming error
            rather than an extraction outcome, so there is no run to record it
            against.
        MalformedExtractionResult: the engine broke its output contract. A
            failed run is recorded first, then this is re-raised.
    """
    image = _require_saved_image(image)

    engine_name = engine_name or settings.DEFAULT_EXTRACTION_ENGINE_NAME
    engine_version = engine_version or settings.DEFAULT_EXTRACTION_ENGINE_VERSION

    run = ExtractionRun.objects.create(
        image=image,
        engine_name=engine_name,
        engine_version=engine_version,
        status=ExtractionRun.Status.RUNNING,
        started_at=timezone.now(),
    )

    _set_image_status(image, ProductImage.Status.PROCESSING)

    try:
        pipeline = registry.get_pipeline(engine_name, engine_version)
        result = _checked_result(pipeline.run(build_image_ref(image)))
        # Scoped to the write, so a database error part-way through cannot leave
        # a run marked COMPLETED with only half its fields. The savepoint is
        # released on the way out, before either `except` clause below touches
        # the connection again.
        with transaction.atomic():
            return _persist_result(run, image, result)
    except LabelExtractError as exc:
        # A known extraction failure: recorded, not raised. One unreadable image
        # must not fail the whole request.
        logger.warning("Extraction failed for image %s: %s", image.pk, exc.code)
        return _finalise_failure(run, image, code=exc.code, message=str(exc))
    except Exception as exc:
        # Unexpected - a bug in an engine, a broken result contract, or the
        # database itself. Record what we can so the image does not sit in
        # PROCESSING forever, then re-raise so the bug is not quietly absorbed
        # into a "this image was unreadable" result.
        logger.exception("Unexpected error extracting image %s", image.pk)
        _record_failure_best_effort(
            run, image, code="internal_error", message=exc.__class__.__name__
        )
        raise


def ingest_and_extract(
    upload,
    *,
    product=None,
    uploaded_by=None,
    view_type: str = ProductImage.ViewType.UNSPECIFIED,
    engine_name: str | None = None,
    engine_version: str | None = None,
) -> ExtractionOutcome:
    """Store `upload` as a `ProductImage`, then extract from it.

    The whole documented flow in one call: upload -> ProductImage -> extraction
    -> ExtractionRun -> ExtractedLabelField. It exists so the two halves cannot
    be wired together wrongly by each new caller - in particular so that nothing
    can reach extraction with a file that never went through
    `apps.images.validators`.

    Ingestion and extraction stay separate underneath. A caller that already
    holds a stored image calls `run_extraction` directly, and re-running an old
    image must not re-upload it.

    Raises:
        ValidationError: the upload was rejected. Nothing is stored and no run
            is created - there is no image for a run to be about.
    """
    # Imported here rather than at module scope: keeping the service-level
    # dependency local makes it visible that this one function is the only
    # thing in the extraction app that ingests.
    from apps.images.services.ingestion import ingest_product_image

    image = ingest_product_image(
        upload, product=product, uploaded_by=uploaded_by, view_type=view_type
    )
    run = run_extraction(
        image, engine_name=engine_name, engine_version=engine_version
    )
    return ExtractionOutcome(image=image, run=run)


# --- input guards -----------------------------------------------------------


def _require_saved_image(image: ProductImage) -> ProductImage:
    """Reject an input that could never produce a traceable run.

    An unsaved row has no committed primary key for `ExtractionRun.image` to
    point at, so the readings would have nothing to be about. Left to Django,
    this surfaces as an `IntegrityError` from a foreign key constraint, after a
    run row and an image status update have already been attempted.

    `pk is None` is *not* the test here: `UUIDPrimaryKeyModel` fills the key in
    from a `default`, so an unsaved `ProductImage()` already has one.
    `_state.adding` is what distinguishes an instance that has never been
    written from one that was loaded or created.
    """
    if image is None:
        raise ValueError("run_extraction requires a ProductImage, got None")
    if not isinstance(image, ProductImage):
        raise ValueError(f"Not a ProductImage: {type(image).__name__}")
    if image.pk is None or image._state.adding:
        raise ValueError(
            "run_extraction requires a saved ProductImage; this one has not "
            "been written to the database"
        )
    return image


# --- the engine's half of the contract --------------------------------------


def _checked_result(result: object) -> ExtractionResult:
    """Refuse to persist anything that is not a well-formed result.

    The database has no opinion about most of this: `field_key` has no choices,
    `raw_output` takes any JSON, `normalized_value` takes any JSON. That
    permissiveness is deliberate - the vocabulary and the shapes belong to the
    ml/ package - which makes this function the only thing standing between an
    engine bug and a table of readings nothing downstream can interpret.

    Checked rather than trusted because the failure mode is silent. A run stored
    with an unrecognised `field_key` raises nothing at all; the compliance
    engine simply never matches it, and a declaration that *was* read on the
    package gets reported as absent.

    Raises:
        MalformedExtractionResult: naming the specific breach.
    """
    if not isinstance(result, ExtractionResult):
        raise MalformedExtractionResult(
            f"Pipeline returned {type(result).__name__}, not an ExtractionResult"
        )
    if result.status not in _STATUS_MAP:
        raise MalformedExtractionResult(
            f"Unknown extraction status: {result.status!r}"
        )
    if not isinstance(result.ocr, OcrResult):
        raise MalformedExtractionResult(
            f"Result carries {type(result.ocr).__name__}, not an OcrResult"
        )
    if (
        not isinstance(result.processing_ms, int)
        # `bool` is an `int` in Python, and `True` would be stored as 1ms - a
        # measurement nobody took. The ml/ contract's first rule is that a
        # value which cannot be measured is reported as None, never invented.
        or isinstance(result.processing_ms, bool)
        or not 0 <= result.processing_ms <= _MAX_PROCESSING_MS
    ):
        # The database would reject the out-of-range cases too, but as a bare
        # `DataError: integer out of range` with nothing in it naming the
        # engine that produced it - and only after the run row had been
        # written. The bound is the column's, not a policy: an engine
        # reporting an epoch where an elapsed time belongs is the realistic
        # way to exceed it.
        raise MalformedExtractionResult(
            "processing_ms must be a non-negative int no greater than "
            f"{_MAX_PROCESSING_MS}, got {result.processing_ms!r}"
        )

    for extracted in result.fields:
        if not isinstance(extracted, ExtractedField):
            raise MalformedExtractionResult(
                f"Result carries {type(extracted).__name__} in fields, not an "
                "ExtractedField"
            )
        _validated_key(extracted.key)
        _require_json_safe(
            extracted.normalized_value,
            what=f"normalized_value for {extracted.key.value}",
        )
    return result


def _validated_key(key: LabelFieldKey) -> str:
    """Guard the field-key vocabulary at the boundary.

    `ExtractedLabelField.field_key` has no database-level choices, because the
    vocabulary belongs to the ml/ package. This is where that contract is
    enforced instead, so a typo in an engine cannot write an unrecognised key
    that the compliance engine would then never match.
    """
    if not isinstance(key, LabelFieldKey):
        raise MalformedExtractionResult(f"Not a LabelFieldKey: {key!r}")
    return key.value


def _require_json_safe(value: object, *, what: str) -> None:
    """Reject a value the JSON columns would fail to store.

    `raw_output` and `normalized_value` are documented as engine-shaped, so
    almost any content is legitimate - but only if it survives `json.dumps`,
    which is what the column does to it. A `Path` or a `datetime` in an engine's
    diagnostics would otherwise surface as an adaptation error from inside a
    save, after the run row had already been written.
    """
    if value is None:
        return
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise MalformedExtractionResult(
            f"{what} is not JSON-serialisable: {exc}"
        ) from exc


# --- persistence ------------------------------------------------------------


def _set_image_status(image: ProductImage, status: str) -> None:
    """Move `image` to `status`, in the database and on the instance.

    The write is a `QuerySet.update()` rather than `image.save()` so that a
    status change cannot carry a stale copy of every other column back over a
    concurrent writer's work. The cost of that choice is that `update()` never
    touches the Python object - and this service hands that same object back to
    its caller inside `ExtractionOutcome`, where a serializer will read it
    without reloading. Unmirrored, a finished image reports `uploaded`.

    Mirrored *after* the write, so a failed update leaves the instance honest
    rather than claiming a status that was never stored.
    """
    ProductImage.objects.filter(pk=image.pk).update(status=status)
    image.status = status


def _persist_result(
    run: ExtractionRun, image: ProductImage, result: ExtractionResult
) -> ExtractionRun:
    raw_output = {
        "engine_raw": dict(result.ocr.raw),
        # Carries `unread_declarations` - declarations the label named whose
        # values could not be read. Stored verbatim because that distinction
        # ("absent" versus "printed but illegible") exists nowhere else in the
        # schema, and losing it turns a request to retake a photograph into a
        # reported violation.
        "metadata": dict(result.metadata),
        "block_count": len(result.ocr.blocks),
    }
    _require_json_safe(raw_output, what="raw_output")

    run.status = _STATUS_MAP[result.status]
    run.is_placeholder = result.is_placeholder
    run.processing_ms = result.processing_ms
    run.completed_at = timezone.now()
    run.recognised_text = result.ocr.full_text
    run.raw_output = raw_output
    run.error_code = result.error_code or ""
    run.error_message = result.error_message or ""
    run.save()

    fields = [
        ExtractedLabelField(
            run=run,
            field_key=_validated_key(extracted.key),
            raw_value=extracted.raw_value,
            normalized_value=(
                dict(extracted.normalized_value)
                if extracted.normalized_value is not None
                else None
            ),
            confidence=extracted.confidence,
            bounding_box=extracted.box.as_dict() if extracted.box else None,
        )
        for extracted in result.fields
    ]
    if fields:
        ExtractedLabelField.objects.bulk_create(fields)

    _set_image_status(
        image,
        ProductImage.Status.FAILED
        if run.status == ExtractionRun.Status.FAILED
        else ProductImage.Status.PROCESSED,
    )
    return run


def _finalise_failure(
    run: ExtractionRun, image: ProductImage, *, code: str, message: str
) -> ExtractionRun:
    run.status = ExtractionRun.Status.FAILED
    run.completed_at = timezone.now()
    run.error_code = code
    run.error_message = message
    run.save()
    _set_image_status(image, ProductImage.Status.FAILED)
    return run


def _record_failure_best_effort(
    run: ExtractionRun, image: ProductImage, *, code: str, message: str
) -> None:
    """Record a failure without letting the attempt replace the real error.

    Used only on the re-raise path. If the original exception *was* the database
    going away, this write fails too - and propagating that would report a
    connection error in place of the bug that caused it. The original exception
    is the one worth seeing, so a secondary failure is logged and dropped.
    """
    try:
        _finalise_failure(run, image, code=code, message=message)
    except Exception:
        logger.exception(
            "Could not record the failed extraction run %s; the original error "
            "follows",
            run.pk,
        )
