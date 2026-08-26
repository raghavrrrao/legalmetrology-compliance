"""The seam between Django and the OCR/ML layer.

This module is the ONLY place in the backend that imports `labelextract`. That
is the whole point of the boundary: if a future engine needs a different call
signature, a queue, or a GPU, this file changes and nothing else does.

Responsibilities, in order:

    1. Turn a `ProductImage` row into a `labelextract.ImageRef`.
    2. Resolve the configured pipeline by name and version.
    3. Run it.
    4. Persist the structured result as an `ExtractionRun`, its fields, and
       any declarations the label named that could not be read.

Explicitly NOT its responsibility: deciding what the readings mean. That is
`apps.compliance`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from labelextract import registry
from labelextract.contracts import (
    ExtractionResult,
    ExtractionStatus,
    ImageRef,
    LabelFieldKey,
)
from labelextract.exceptions import LabelExtractError

from apps.extraction.models import (
    ExtractedLabelField,
    ExtractionRun,
    UnreadLabelDeclaration,
)
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
    """Convert a stored image row into the ML layer's input contract."""
    return ImageRef(
        path=Path(image.image.path),
        image_format=image.image_format,
        size_bytes=image.size_bytes,
        width=image.width,
        height=image.height,
    )


@transaction.atomic
def run_extraction(
    image: ProductImage,
    *,
    engine_name: str | None = None,
    engine_version: str | None = None,
) -> ExtractionRun:
    """Run extraction over `image` and persist the result.

    Always returns a saved `ExtractionRun`, including when extraction failed -
    a failure is a fact about the image worth recording, and silently returning
    nothing would leave the UI unable to explain why no result appeared.

    Runs synchronously. That is a deliberate choice for the base structure:
    with a placeholder engine there is nothing to wait for, and introducing a
    task queue now would add infrastructure with no work to do. When a real OCR
    engine makes this slow, only this function needs to move behind a queue -
    callers already treat the run as a row they poll, not a value they await.
    """
    engine_name = engine_name or settings.DEFAULT_EXTRACTION_ENGINE_NAME
    engine_version = engine_version or settings.DEFAULT_EXTRACTION_ENGINE_VERSION

    run = ExtractionRun.objects.create(
        image=image,
        engine_name=engine_name,
        engine_version=engine_version,
        status=ExtractionRun.Status.RUNNING,
        started_at=timezone.now(),
    )

    ProductImage.objects.filter(pk=image.pk).update(
        status=ProductImage.Status.PROCESSING
    )

    try:
        pipeline = registry.get_pipeline(engine_name, engine_version)
        result = pipeline.run(build_image_ref(image))
    except LabelExtractError as exc:
        # A known extraction failure: recorded, not raised. One unreadable
        # image must not fail the whole request.
        logger.warning(
            "Extraction failed for image %s: %s", image.pk, exc.code
        )
        return _finalise_failure(run, image, code=exc.code, message=str(exc))
    except Exception as exc:
        # Unexpected: log with a traceback, still record the run so the image
        # does not sit in PROCESSING forever, then re-raise so the bug is not
        # quietly absorbed into a "this image was unreadable" result.
        logger.exception("Unexpected error extracting image %s", image.pk)
        _finalise_failure(
            run, image, code="internal_error", message=exc.__class__.__name__
        )
        raise

    return _persist_result(run, image, result)


# --- persistence ------------------------------------------------------------


def _persist_result(
    run: ExtractionRun, image: ProductImage, result: ExtractionResult
) -> ExtractionRun:
    run.status = _STATUS_MAP[result.status]
    run.is_placeholder = result.is_placeholder
    run.processing_ms = result.processing_ms
    run.completed_at = timezone.now()
    run.recognised_text = result.ocr.full_text
    run.raw_output = {
        "engine_raw": dict(result.ocr.raw),
        "metadata": dict(result.metadata),
        "block_count": len(result.ocr.blocks),
    }
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

    unread = _unread_rows(run, result)
    if unread:
        UnreadLabelDeclaration.objects.bulk_create(unread)

    ProductImage.objects.filter(pk=image.pk).update(
        status=(
            ProductImage.Status.FAILED
            if run.status == ExtractionRun.Status.FAILED
            else ProductImage.Status.PROCESSED
        )
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
    ProductImage.objects.filter(pk=image.pk).update(
        status=ProductImage.Status.FAILED
    )
    return run


def _validated_key(key: LabelFieldKey) -> str:
    """Guard the field-key vocabulary at the boundary.

    `ExtractedLabelField.field_key` has no database-level choices, because the
    vocabulary belongs to the ml/ package. This is where that contract is
    enforced instead, so a typo in an engine cannot write an unrecognised key
    that the compliance engine would then never match.
    """
    if not isinstance(key, LabelFieldKey):
        raise ValueError(f"Not a LabelFieldKey: {key!r}")
    return key.value


#: Key under which the ML layer reports declarations it named but could not
#: read. Defined by `labelextract.pipeline.ExtractionPipeline._metadata`; the
#: whole mapping is also stored verbatim in `raw_output` as diagnostics.
_UNREAD_METADATA_KEY = "unread_declarations"

#: The `labelextract.contracts.UnreadDeclaration.as_dict()` keys this reads.
#: Anything else in an entry is ignored rather than rejected, so an engine that
#: adds a diagnostic field does not break persistence.
_UNREAD_REQUIRED_KEYS = ("key", "evidence_text")


def _unread_rows(
    run: ExtractionRun, result: ExtractionResult
) -> list[UnreadLabelDeclaration]:
    """Build the unread-declaration rows for `result`, skipping malformed ones.

    This is the seam. The ML layer reports these in `metadata` rather than on
    `ExtractionResult.fields`, deliberately and permanently - an unread
    declaration is not a field, and `field_presence` passes on any field. Here
    they become rows in their own table, which is the copy
    `apps.rules.checks` reads.

    Defensive on purpose, in three ways, because `metadata` is a mapping any
    pipeline can populate and this is where an engine's mistake would otherwise
    reach the compliance engine:

    1. **A missing key is normal, not an error.** A pipeline with no field
       extractor, or one predating the mechanism, reports nothing here.
    2. **An unrecognised `key` is dropped.** Same guard as `_validated_key`
       gives `ExtractedLabelField`: a key outside the ml/ vocabulary would
       never match a rule, so writing it would be a row that silently does
       nothing.
    3. **An entry without evidence is dropped.** "An MRP keyword was seen",
       with no line to show for it, is a claim a reviewer cannot check.

    A skipped entry is logged and the run still records everything else. One
    malformed observation must not cost the declarations that were read - the
    same policy the pipeline itself applies one layer up.
    """
    raw = result.metadata.get(_UNREAD_METADATA_KEY) or []
    if not isinstance(raw, (list, tuple)):
        logger.warning(
            "Engine %s reported %s as %s, not a list; ignoring it",
            result.engine_name,
            _UNREAD_METADATA_KEY,
            type(raw).__name__,
        )
        return []

    known_keys = {key.value for key in LabelFieldKey}
    rows: list[UnreadLabelDeclaration] = []

    for entry in raw:
        if not isinstance(entry, dict) or not all(
            entry.get(name) for name in _UNREAD_REQUIRED_KEYS
        ):
            logger.warning(
                "Engine %s reported an unread declaration with no key or no "
                "evidence; dropping it",
                result.engine_name,
            )
            continue

        field_key = entry["key"]
        if field_key not in known_keys:
            logger.warning(
                "Engine %s reported an unread declaration for %r, which is not "
                "in the labelextract vocabulary; dropping it",
                result.engine_name,
                field_key,
            )
            continue

        evidence_text = str(entry["evidence_text"])
        if not evidence_text.strip():
            continue

        rows.append(
            UnreadLabelDeclaration(
                run=run,
                field_key=field_key,
                evidence_text=evidence_text,
                confidence=entry.get("confidence"),
                bounding_box=entry.get("box"),
            )
        )
    return rows
