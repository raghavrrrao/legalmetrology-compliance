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

    1. Turn each `ProductImage` row into a `labelextract.ImageRef`.
    2. Resolve the configured pipeline by name and version.
    3. Run it over every photograph in the set.
    4. Check each returned result against the contract before trusting it.
    5. Persist the merged result as one `ExtractionRun` plus its fields, each
       field carrying the photograph it was read from.

One run, several photographs
----------------------------
A packaged commodity declares different things on different panels, so an
inspection may carry more than one photograph of the same package. They are
read into **one** `ExtractionRun`, not one run each, because the rule engine
judges the package: a net quantity printed on the back is a declaration the
package makes, and a run per photograph would report the front as failing to
declare it.

The pipeline is still run once per photograph - it reads one image, and
pretending otherwise would mean inventing an engine capability. What this
module does is merge what came back:

- every declaration is stored with `ExtractedLabelField.image` set to the
  photograph it was read from, so a finding can cite image 2;
- the run's status is the best outcome of the set, because "was this label
  read well enough to judge against" is a question about the package and one
  unreadable close-up does not make the answer no;
- each photograph's own outcome is kept on its `ExtractionRunImage` row, so a
  submitter can still be told that image 3 was unreadable.

Nothing here decides which of two conflicting readings of the same declaration
to believe. That is a question about evidence, and it is answered once, in
`apps.rules.checks.base.CheckContext.from_run`, where every validator sees the
same answer.

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
from collections.abc import Mapping, Sequence
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

from apps.extraction.models import (
    ExtractedLabelField,
    ExtractionRun,
    ExtractionRunImage,
)
from apps.images.constants import MAX_IMAGES_PER_INSPECTION
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

    `image` is the primary photograph and `images` is the whole set in the
    order it was supplied. `image` is not deprecated by `images`: it is
    position 1, it is what `ExtractionRun.image` points at, and a single-image
    inspection is a set of one where the two say the same thing.
    """

    image: ProductImage
    run: ExtractionRun
    #: Every photograph of this inspection, in position order. Always at least
    #: one, and `images[0] is image`.
    images: tuple[ProductImage, ...] = ()

    def __post_init__(self) -> None:
        if not self.images:
            object.__setattr__(self, "images", (self.image,))

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


@dataclass(frozen=True)
class PipelineStatus:
    """What the health endpoint may say about the configured pipeline.

    Three separate facts, kept separate because they fail independently and
    conflating them is how a deployment reports itself healthy while doing no
    recognition at all:

    `is_placeholder`  the pipeline is wiring only. True means no pixel is read,
                      whatever else is working.
    `is_available`    the pipeline's runtime dependencies resolve - for
                      Tesseract, that pytesseract is importable AND the
                      `tesseract` binary answers. False here is the deployment
                      failure that `is_placeholder=False` alone cannot show:
                      the real engine is *configured*, so nothing looks like a
                      placeholder, and every upload fails one at a time.
    `detail`          a short, non-sensitive reason when something is wrong.

    No version string for the binary, and that is deliberate: the health
    endpoint is public and states only whether each dependency answered. See
    `apps.core.api.views.HealthView`.
    """

    name: str
    version: str
    is_placeholder: bool | None
    is_available: bool
    detail: str = ""


def default_pipeline_status() -> PipelineStatus:
    """Resolve the configured pipeline and check it can actually run.

    Never raises. Every failure is reported as `is_available=False` with a
    reason, because this exists to answer a health check - an endpoint that
    500s when a dependency is missing tells an operator less than one that
    says which dependency it was.

    `warmup()` is what makes this more than a registry lookup. Resolving a
    pipeline only proves it is registered; the Tesseract engine's warmup calls
    the binary, so a container built without `tesseract` installed is caught
    here rather than on a user's first upload.
    """
    name = settings.DEFAULT_EXTRACTION_ENGINE_NAME
    version = settings.DEFAULT_EXTRACTION_ENGINE_VERSION

    try:
        pipeline = registry.get_pipeline(name, version)
    except Exception as exc:
        logger.exception("Configured extraction pipeline could not be resolved")
        return PipelineStatus(
            name=name,
            version=version,
            is_placeholder=None,
            is_available=False,
            detail=f"pipeline not resolvable: {exc.__class__.__name__}",
        )

    is_placeholder = pipeline.is_placeholder

    try:
        pipeline.warmup()
    except LabelExtractError as exc:
        # The expected shape of "this engine cannot run here": pytesseract is
        # missing, or the binary is not on PATH. `exc.code` is a stable, short
        # identifier from the ml/ layer - not a path, not a traceback.
        logger.warning("Extraction pipeline %s %s is unavailable: %s", name, version, exc)
        return PipelineStatus(
            name=name,
            version=version,
            is_placeholder=is_placeholder,
            is_available=False,
            detail=exc.code,
        )
    except Exception as exc:
        logger.exception("Extraction pipeline %s %s failed to warm up", name, version)
        return PipelineStatus(
            name=name,
            version=version,
            is_placeholder=is_placeholder,
            is_available=False,
            detail=exc.__class__.__name__,
        )

    return PipelineStatus(
        name=name,
        version=version,
        is_placeholder=is_placeholder,
        is_available=True,
    )


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

    One photograph. `run_extraction_over` is the same operation for a set of
    them, and this is the set of one - it delegates rather than repeating the
    sequence, so the two can never drift into reading a single image
    differently depending on which door the caller came through.

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
    return run_extraction_over(
        [image], engine_name=engine_name, engine_version=engine_version
    )


def run_extraction_over(
    images: Sequence[ProductImage],
    *,
    engine_name: str | None = None,
    engine_version: str | None = None,
) -> ExtractionRun:
    """Read every photograph in `images` into one persisted `ExtractionRun`.

    The photographs are read in the order given, and that order is the
    `position` on each `ExtractionRunImage` row - the number a person is shown
    beside a piece of evidence. `images[0]` becomes `ExtractionRun.image`, the
    primary photograph.

    A photograph that cannot be read does not fail the inspection. Its own
    membership row records `failed` with the reason, and the run carries on
    with the rest - because a blurred close-up alongside two readable panels is
    a worse photograph, not an unreadable package. Only when *every* photograph
    failed is the run itself FAILED, which is the same outcome a single
    unreadable image has always produced.

    Args:
        images: One or more saved `ProductImage` rows. Duplicates are rejected:
            the same photograph twice is a submission mistake, and storing it
            would double-count its declarations.
        engine_name: Override the configured pipeline. For comparing engines.
        engine_version: Override the configured pipeline version.

    Returns:
        A saved `ExtractionRun` whose `fields` each name the photograph they
        were read from.

    Raises:
        ValueError: the set is empty, too large, holds a duplicate, or holds
            something that is not a saved `ProductImage`. All programming or
            request errors rather than extraction outcomes, so there is no run
            to record them against.
        MalformedExtractionResult: an engine broke its output contract. A
            failed run is recorded first, then this is re-raised.
    """
    images = _require_image_set(images)

    engine_name = engine_name or settings.DEFAULT_EXTRACTION_ENGINE_NAME
    engine_version = engine_version or settings.DEFAULT_EXTRACTION_ENGINE_VERSION

    run = ExtractionRun.objects.create(
        image=images[0],
        engine_name=engine_name,
        engine_version=engine_version,
        status=ExtractionRun.Status.RUNNING,
        started_at=timezone.now(),
    )

    for image in images:
        _set_image_status(image, ProductImage.Status.PROCESSING)

    try:
        pipeline = registry.get_pipeline(engine_name, engine_version)
        readings = [
            _read_one_image(pipeline, image, position)
            for position, image in enumerate(images, start=1)
        ]
        # Scoped to the write, so a database error part-way through cannot leave
        # a run marked COMPLETED with only half its fields. The savepoint is
        # released on the way out, before either `except` clause below touches
        # the connection again.
        with transaction.atomic():
            return _persist_readings(run, readings)
    except LabelExtractError as exc:
        # Reachable only from resolving the pipeline: a failure to read one
        # photograph is handled per image in `_read_one_image` and never
        # arrives here. An unresolvable pipeline is a fact about the whole
        # run, so it is recorded against all of its images.
        logger.warning(
            "Extraction pipeline unavailable for run %s: %s", run.pk, exc.code
        )
        return _finalise_failure(run, images, code=exc.code, message=str(exc))
    except Exception as exc:
        # Unexpected - a bug in an engine, a broken result contract, or the
        # database itself. Record what we can so the images do not sit in
        # PROCESSING forever, then re-raise so the bug is not quietly absorbed
        # into a "these photographs were unreadable" result.
        logger.exception("Unexpected error extracting run %s", run.pk)
        _record_failure_best_effort(
            run, images, code="internal_error", message=exc.__class__.__name__
        )
        raise


@dataclass(frozen=True)
class _ImageReading:
    """What the pipeline made of one photograph of the set.

    Exactly one of `result` and `error_code` is set. A private value: it never
    leaves this module, and everything it carries is either persisted onto an
    `ExtractionRunImage` row or merged into the run.
    """

    image: ProductImage
    position: int
    result: ExtractionResult | None = None
    error_code: str = ""
    error_message: str = ""

    @property
    def succeeded(self) -> bool:
        return self.result is not None


def _read_one_image(pipeline, image: ProductImage, position: int) -> _ImageReading:
    """Run the pipeline over one photograph, recording a failure as a value.

    A `LabelExtractError` is caught here rather than propagating, because one
    unreadable photograph in a set of three is an outcome for that photograph
    and not for the inspection. A `MalformedExtractionResult` is deliberately
    *not* caught: an engine that broke its own output contract is a bug, and
    `run_extraction_over` re-raises it after recording the run as failed.
    """
    try:
        result = _checked_result(pipeline.run(build_image_ref(image)))
    except LabelExtractError as exc:
        logger.warning(
            "Extraction failed for image %s (position %d): %s",
            image.pk,
            position,
            exc.code,
        )
        return _ImageReading(
            image=image,
            position=position,
            error_code=exc.code,
            error_message=str(exc),
        )
    return _ImageReading(image=image, position=position, result=result)


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

    One photograph. `ingest_and_extract_all` is the same call for a set of
    them, and this delegates to it, so a single upload takes exactly the path a
    set of one does.

    Ingestion and extraction stay separate underneath. A caller that already
    holds a stored image calls `run_extraction` directly, and re-running an old
    image must not re-upload it.

    Raises:
        ValidationError: the upload was rejected. Nothing is stored and no run
            is created - there is no image for a run to be about.
    """
    return ingest_and_extract_all(
        [upload],
        product=product,
        uploaded_by=uploaded_by,
        view_types=[view_type],
        engine_name=engine_name,
        engine_version=engine_version,
    )


def ingest_and_extract_all(
    uploads: Sequence,
    *,
    product=None,
    uploaded_by=None,
    view_types: Sequence[str] | None = None,
    engine_name: str | None = None,
    engine_version: str | None = None,
) -> ExtractionOutcome:
    """Store every photograph of one inspection, then read them into one run.

    Args:
        uploads: The files as received, in the order the submitter supplied
            them. The first is the primary photograph.
        product: The commodity these photographs show, when already known.
        uploaded_by: The user, when the request is authenticated.
        view_types: Which panel each photograph shows, positionally. A shorter
            sequence leaves the rest `unspecified`; None leaves them all so.
            Padded rather than repeated, because "the first one is the front"
            says nothing about the second and copying the value across would
            record a claim the submitter did not make.
        engine_name: Override the configured pipeline. For comparing engines.
        engine_version: Override the configured pipeline version.

    Returns:
        An `ExtractionOutcome` whose `images` are the stored photographs in
        order and whose `run` read all of them.

    Raises:
        ValidationError: an upload was rejected, or a view type is not a
            recognised value. **Ingestion stops at the first rejection**, so
            the photographs before it are already stored while the rest are
            not, and no run exists. They are orphaned rows, not a half-made
            inspection: nothing points at them, the next attempt stores its own
            copies, and the alternative - deleting what was already written -
            would destroy an image on a path where no result was produced to
            justify it. The API reports the rejection against the whole
            request, which is what the submitter needs to act on.
        ValueError: the set is empty or larger than
            `MAX_IMAGES_PER_INSPECTION`.
    """
    # Imported here rather than at module scope: keeping the service-level
    # dependency local makes it visible that this one function is the only
    # thing in the extraction app that ingests.
    from apps.images.services.ingestion import ingest_product_image

    uploads = list(uploads)
    if not uploads:
        raise ValueError("An inspection needs at least one photograph.")
    if len(uploads) > MAX_IMAGES_PER_INSPECTION:
        raise ValueError(
            f"An inspection may carry at most {MAX_IMAGES_PER_INSPECTION} "
            f"photographs; {len(uploads)} were supplied."
        )

    panels = list(view_types or ())
    images = [
        ingest_product_image(
            upload,
            product=product,
            uploaded_by=uploaded_by,
            view_type=(
                panels[index]
                if index < len(panels) and panels[index]
                else ProductImage.ViewType.UNSPECIFIED
            ),
        )
        for index, upload in enumerate(uploads)
    ]
    run = run_extraction_over(
        images, engine_name=engine_name, engine_version=engine_version
    )
    return ExtractionOutcome(image=images[0], run=run, images=tuple(images))


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


def _require_image_set(images: Sequence[ProductImage]) -> list[ProductImage]:
    """Reject a set that could never produce a coherent inspection.

    Bounded because every photograph costs a full pipeline pass inside the same
    synchronous request. De-duplicated because the same photograph twice would
    have its declarations counted twice and would breach the membership row's
    own uniqueness constraint - as an IntegrityError, after a run row had
    already been written.
    """
    if images is None:
        raise ValueError("run_extraction_over requires images, got None")
    images = [_require_saved_image(image) for image in images]
    if not images:
        raise ValueError("run_extraction_over requires at least one image")
    if len(images) > MAX_IMAGES_PER_INSPECTION:
        raise ValueError(
            f"An inspection may carry at most {MAX_IMAGES_PER_INSPECTION} "
            f"photographs; {len(images)} were supplied."
        )
    seen: set = set()
    for image in images:
        if image.pk in seen:
            raise ValueError(
                f"Image {image.pk} was supplied more than once; a photograph "
                "may appear in an inspection only once."
            )
        seen.add(image.pk)
    return images


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
    # `OcrResult` and `ExtractionResult` are plain dataclasses with no
    # `__post_init__`, so their container type hints are documentation rather
    # than enforcement. Persistence calls `dict()` on the two mappings and
    # `len()`/iteration on the two sequences, so an engine that leaves one None
    # breaks inside the write with a bare TypeError - reported as a generic
    # `internal_error` that names Python rather than the engine at fault.
    _require_mapping(result.ocr.raw, what="ocr.raw")
    _require_sequence(result.ocr.blocks, what="ocr.blocks")
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

    _require_mapping(result.metadata, what="metadata")
    _require_sequence(result.fields, what="fields")

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


def _require_mapping(value: object, *, what: str) -> None:
    """Reject anything persistence would call `dict()` on and misread.

    `Mapping` rather than `dict` on purpose: an engine is free to hand back any
    mapping type, and the contract asks for one. The case worth stopping is not
    only `None` - which at least fails loudly - but a list of pairs, which
    `dict()` accepts silently. That would store an engine's diagnostics as
    though they had been sent as a mapping, and `metadata` is where
    `unread_declarations` rides, so a quiet reshape there loses the distinction
    between "no MRP declared" and "the MRP could not be read".
    """
    if not isinstance(value, Mapping):
        raise MalformedExtractionResult(
            f"{what} must be a Mapping, got {type(value).__name__}"
        )


def _require_sequence(value: object, *, what: str) -> None:
    """Reject anything persistence would iterate or measure and fail on.

    A `list` is accepted as readily as a `tuple`: the contract names a tuple,
    but nothing here depends on immutability and refusing a list would be
    restrictive for no gain. `str` and `bytes` are excluded because they are
    sequences that would iterate into characters rather than items.

    A one-shot iterable is refused for a subtler reason than a crash: this
    function iterates `fields`, and `_persist_result` iterates it again. A
    generator would be empty by the second pass, and the run would be stored
    COMPLETED with none of the declarations the engine actually read.
    """
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MalformedExtractionResult(
            f"{what} must be a sequence, got {type(value).__name__}"
        )


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


#: Sentinel for "the engine did not send this key", distinct from a key it
#: sent as None. Only `_merged_metadata` needs the distinction, and only for
#: `unread_declarations`, where absent and empty mean different things.
_ABSENT = object()


#: Per-image status for a photograph the pipeline could not read.
_IMAGE_STATUS_MAP = {
    ExtractionRun.Status.COMPLETED: ExtractionRunImage.Status.COMPLETED,
    ExtractionRun.Status.EMPTY: ExtractionRunImage.Status.EMPTY,
    ExtractionRun.Status.FAILED: ExtractionRunImage.Status.FAILED,
}


def _merged_status(readings: list[_ImageReading]) -> str:
    """The run's status, from the outcomes of the photographs it read.

    The best outcome of the set wins, and that is the whole decision worth
    understanding here. `produced_usable_output` - which is `status ==
    COMPLETED` - is what tells the compliance engine whether an absent
    declaration is evidence about the *package* or only about the
    *photograph*. For a set, the honest answer is that the label was read well
    enough to judge against as soon as any one photograph was read well enough,
    because the declarations it found are declarations the package makes.

    Taking the worst outcome instead would mean a submitter who adds a blurred
    close-up to two good panels gets every finding downgraded to "could not be
    decided" - punished for supplying more evidence, which is precisely
    backwards.

    What the unreadable photograph is *not* allowed to do is disappear: its own
    `ExtractionRunImage` row records `failed` and why, and the interface shows
    it. This function decides the verdict-affecting question only.
    """
    statuses = {
        _STATUS_MAP[reading.result.status]
        for reading in readings
        if reading.succeeded
    }
    if ExtractionRun.Status.COMPLETED in statuses:
        return ExtractionRun.Status.COMPLETED
    if ExtractionRun.Status.EMPTY in statuses:
        return ExtractionRun.Status.EMPTY
    return ExtractionRun.Status.FAILED


def _merged_processing_ms(readings: list[_ImageReading]) -> int | None:
    """Total time the pipeline spent, across every photograph it read.

    A sum rather than a maximum or an average: the photographs are read one
    after another in the same request, so the sum is the time that actually
    passed inside the pipeline. Per-photograph figures are kept on the
    membership rows, so nothing is lost by totalling them here.

    None when no photograph produced a measurement, which is what the column
    means - never 0, which would be a measurement nobody took. Clamped at the
    column's ceiling rather than overflowing it; reaching that would need
    roughly 25 days of extraction in one request.
    """
    measured = [
        reading.result.processing_ms
        for reading in readings
        if reading.succeeded and reading.result.processing_ms is not None
    ]
    if not measured:
        return None
    return min(sum(measured), _MAX_PROCESSING_MS)


def _merged_metadata(readings: list[_ImageReading]) -> dict:
    """One `metadata` mapping for the set, from each photograph's own.

    Two rules, and both exist to keep the ml/ package's vocabulary intact:

    **`unread_declarations` is concatenated**, in position order. Each entry is
    a declaration some photograph named but could not read, and that stays true
    of every entry however many photographs there were. The entries keep the
    shape `labelextract.contracts.UnreadDeclaration` defines - no key is added
    to say which photograph an entry came from, because that would be this
    layer editing a contract written on the other side of the ML boundary. The
    structured channel for image attribution is `ExtractedLabelField.image`.

    **Everything else is taken from the earliest photograph that reported it.**
    `product_classification` is the key that matters: the classifier runs per
    photograph, so a set of three produces three classifications of the same
    package, and there is no honest way to merge them into a fourth. Position
    order is used because position 1 is the primary photograph, and because a
    rule a person can predict beats one they cannot. The classification is a
    suggestion that decides nothing - `apps.compliance` never reads it - so
    selecting one is a display choice, not a determination.

    For a single photograph this returns that photograph's metadata unchanged,
    which is what it has always been.
    """
    merged: dict = {}
    unread: list = []
    reported_unread = False
    for reading in readings:
        if not reading.succeeded:
            continue
        metadata = dict(reading.result.metadata)
        declarations = metadata.pop("unread_declarations", _ABSENT)
        if isinstance(declarations, list):
            reported_unread = True
            unread.extend(declarations)
        elif declarations is not _ABSENT:
            # An engine reported something that is not a list under this key.
            # Kept, first-wins, rather than dropped: `raw_output` is stored
            # verbatim everywhere else, and a reshape here is exactly what
            # would lose the "named but illegible" channel silently.
            merged.setdefault("unread_declarations", declarations)
        for key, value in metadata.items():
            merged.setdefault(key, value)
    if reported_unread:
        # Set even when empty, because an engine that reported an empty list
        # said something ("I read everything I saw named") that an absent key
        # does not. Never invented: absent stays absent.
        merged["unread_declarations"] = unread
    return merged


def _persist_readings(
    run: ExtractionRun, readings: list[_ImageReading]
) -> ExtractionRun:
    """Write the run, its membership rows and every declaration that was read.

    One write of the run, one `bulk_create` of the membership rows and one of
    the fields, whatever the size of the set - so a five-image inspection costs
    the same number of statements as a one-image one.
    """
    succeeded = [reading for reading in readings if reading.succeeded]
    first = succeeded[0] if succeeded else None

    raw_output = {
        # The primary reading's diagnostics, unchanged. `engine_raw` has always
        # been one engine's raw output and stays that; the per-photograph
        # breakdown is `images` below, added rather than folded in, so a reader
        # of an old run and a reader of a new one see the same key mean the
        # same thing.
        "engine_raw": dict(first.result.ocr.raw) if first else {},
        # Carries `unread_declarations` - declarations the label named whose
        # values could not be read. Stored verbatim because that distinction
        # ("absent" versus "printed but illegible") exists nowhere else in the
        # schema, and losing it turns a request to retake a photograph into a
        # reported violation.
        "metadata": _merged_metadata(readings),
        "block_count": sum(
            len(reading.result.ocr.blocks) for reading in succeeded
        ),
    }
    if len(readings) > 1:
        # Added only for a genuine set. A single-image run's `raw_output` keeps
        # exactly the three keys it has always had, so nothing that reads one
        # has to learn a new shape to go on working.
        raw_output["images"] = [
            {
                "position": reading.position,
                "image_id": str(reading.image.pk),
                "status": (
                    _STATUS_MAP[reading.result.status]
                    if reading.succeeded
                    else ExtractionRun.Status.FAILED
                ),
                "error_code": (
                    reading.result.error_code or ""
                    if reading.succeeded
                    else reading.error_code
                ),
                "block_count": (
                    len(reading.result.ocr.blocks) if reading.succeeded else 0
                ),
                "processing_ms": (
                    reading.result.processing_ms if reading.succeeded else None
                ),
            }
            for reading in readings
        ]
    _require_json_safe(raw_output, what="raw_output")

    failures = [reading for reading in readings if not reading.succeeded]

    run.status = _merged_status(readings)
    # One pipeline read every photograph, so `is_placeholder` is the same
    # answer for all of them; the first that ran is as good as any. False when
    # none ran, which is the safe direction: it is never a claim that real
    # recognition happened.
    run.is_placeholder = bool(first.result.is_placeholder) if first else False
    run.processing_ms = _merged_processing_ms(readings)
    run.completed_at = timezone.now()
    # Joined in position order. The declarations of one package, printed across
    # several panels, read as one label - which is what this column is for.
    run.recognised_text = "\n".join(
        reading.result.ocr.full_text
        for reading in succeeded
        if reading.result.ocr.full_text
    )
    run.raw_output = raw_output
    if first is not None:
        # The set produced a reading, so the run did not fail. An error from a
        # photograph that could not be read belongs to that photograph's own
        # row, not to the run - putting it here would report a whole
        # inspection as failed because one close-up was blurred.
        run.error_code = first.result.error_code or ""
        run.error_message = first.result.error_message or ""
    else:
        run.error_code = failures[0].error_code if failures else ""
        run.error_message = failures[0].error_message if failures else ""
    run.save()

    ExtractionRunImage.objects.bulk_create(
        [
            ExtractionRunImage(
                run=run,
                image=reading.image,
                position=reading.position,
                status=(
                    _IMAGE_STATUS_MAP[_STATUS_MAP[reading.result.status]]
                    if reading.succeeded
                    else ExtractionRunImage.Status.FAILED
                ),
                error_code=(
                    reading.result.error_code or ""
                    if reading.succeeded
                    else reading.error_code
                ),
                error_message=(
                    reading.result.error_message or ""
                    if reading.succeeded
                    else reading.error_message
                ),
                processing_ms=(
                    reading.result.processing_ms if reading.succeeded else None
                ),
            )
            for reading in readings
        ]
    )

    fields = [
        ExtractedLabelField(
            run=run,
            # The photograph this declaration was actually read from. Set here
            # rather than inferred later: once the readings are merged there is
            # no way back to which image produced which, and a finding that
            # cited the wrong panel would be worse than one citing none.
            image=reading.image,
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
        for reading in succeeded
        for extracted in reading.result.fields
    ]
    if fields:
        ExtractedLabelField.objects.bulk_create(fields)

    for reading in readings:
        _set_image_status(
            reading.image,
            ProductImage.Status.PROCESSED
            if reading.succeeded
            and _STATUS_MAP[reading.result.status] != ExtractionRun.Status.FAILED
            else ProductImage.Status.FAILED,
        )
    return run


def _finalise_failure(
    run: ExtractionRun,
    images: Sequence[ProductImage],
    *,
    code: str,
    message: str,
) -> ExtractionRun:
    """Record a run that produced no reading at all, and say why.

    Reached when the pipeline itself could not be resolved, so no photograph
    was read and every one of them shares the reason. Membership rows are still
    written: an inspection that failed still had a set, and a submitter looking
    at it needs to see which photographs they sent.
    """
    run.status = ExtractionRun.Status.FAILED
    run.completed_at = timezone.now()
    run.error_code = code
    run.error_message = message
    run.save()

    if not run.run_images.exists():
        ExtractionRunImage.objects.bulk_create(
            [
                ExtractionRunImage(
                    run=run,
                    image=image,
                    position=position,
                    status=ExtractionRunImage.Status.FAILED,
                    error_code=code,
                    error_message=message,
                )
                for position, image in enumerate(images, start=1)
            ]
        )

    for image in images:
        _set_image_status(image, ProductImage.Status.FAILED)
    return run


def _record_failure_best_effort(
    run: ExtractionRun,
    images: Sequence[ProductImage],
    *,
    code: str,
    message: str,
) -> None:
    """Record a failure without letting the attempt replace the real error.

    Used only on the re-raise path. If the original exception *was* the database
    going away, this write fails too - and propagating that would report a
    connection error in place of the bug that caused it. The original exception
    is the one worth seeing, so a secondary failure is logged and dropped.
    """
    try:
        _finalise_failure(run, images, code=code, message=message)
    except Exception:
        logger.exception(
            "Could not record the failed extraction run %s; the original error "
            "follows",
            run.pk,
        )


# --- explaining a reading ----------------------------------------------------


@dataclass(frozen=True)
class LabelPhrase:
    """A phrase a reading contains, and what it is typically found on.

    A plain value, deliberately: it crosses into `apps.compliance`, which must
    not gain a dependency on an ML type to describe its own evidence.
    """

    phrase: str
    #: A category or subcategory code this phrase is *typically* found with.
    #: A display hint about the phrase, never a claim about this package.
    indicative_of: str
    #: The surrounding text, so the phrase can be found on the photograph.
    snippet: str


#: Characters of surrounding reading shown either side of a matched phrase.
_SNIPPET_CONTEXT = 40


def label_phrases(text: str | None, *, limit: int = 6) -> tuple[LabelPhrase, ...]:
    """The signal-table phrases that occur in `text`, with their context.

    **This lives here because of where the ML boundary is, not because it is
    extraction.** `test_only_the_extraction_service_reaches_the_ml_runtime`
    holds this module as the single place the backend may import anything under
    `labelextract` beyond the shared contracts, and the phrase table lives
    there. Its caller is `apps.compliance.services.auto_applicability`, which
    shows a person what the label says when it has to ask them what kind of
    product it is.

    No engine runs. `labelextract.classification.signals` is a reviewed table
    of about thirty-five label phrases whose own docstring records that the
    model never reads it, and `preprocess_text` is a pure function that changes
    encoding, case and whitespace and nothing else - `preprocessing.py`
    documents its output as "the text a person reads to check a
    classification", which is exactly what a snippet should be. So this is a
    regex pass over text already in memory: no OCR, no model, no artifact load.

    Returns an empty tuple for empty text, and on any import failure - a broken
    ML install costs the snippets and nothing else.
    """
    if not text or not text.strip():
        return ()
    try:
        from labelextract.classification.preprocessing import preprocess_text
        from labelextract.classification.signals import matched_signals
    except Exception:  # pragma: no cover - a broken ML install
        logger.warning("Label phrase table unavailable; continuing without it")
        return ()

    cleaned = preprocess_text(text)
    phrases: list[LabelPhrase] = []
    for signal in matched_signals(cleaned):
        match = signal.pattern.search(cleaned)
        if match is None:  # pragma: no cover - matched_signals just said it does
            continue
        left = max(0, match.start() - _SNIPPET_CONTEXT)
        right = min(len(cleaned), match.end() + _SNIPPET_CONTEXT)
        body = cleaned[left:right].strip()
        phrases.append(
            LabelPhrase(
                phrase=signal.label,
                indicative_of=signal.indicative_of,
                snippet=f"{'…' if left > 0 else ''}{body}{'…' if right < len(cleaned) else ''}",
            )
        )
        if len(phrases) >= limit:
            break
    return tuple(phrases)
