"""Concrete orchestrator that turns pluggable components into an ExtractionResult.

This is the only place that knows the ordering of the extraction stages. It is
a plain class, not an abstract one: there is exactly one sensible order for
these stages, so there is nothing worth subclassing.

    ImageRef
        -> ImagePreprocessor.process()   (optional)
        -> OcrEngine.recognise()         (required)
        -> boxes mapped back to source-image space
        -> FieldExtractor.extract()      (optional)
        -> ExtractionResult

Why the mapping step is here and not in a component
---------------------------------------------------
A preprocessor that resizes hands the engine a different coordinate system, so
every box that comes back describes the *intermediate* rather than the
photograph a reviewer is looking at. Neither component can fix that alone: the
preprocessor never sees the boxes, and the engine never sees the original. This
class is the only place that holds both, so the correction belongs here.

It runs before field extraction, so an `ExtractedField` inherits an already
corrected box and no consumer has to know a resize happened. `metadata` records
the scale that was applied and which space the boxes are in, so a run stays
interpretable without re-deriving it.

Failure policy: a `LabelExtractError` from any stage is caught and turned into
`ExtractionResult(status=FAILED, error_code=...)` rather than propagating. The
backend records a failed run and moves on; one unreadable photograph must not
take down a batch. Unexpected exceptions are NOT caught - a bug in an engine
should surface loudly rather than be recorded as "this image was unreadable".
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace

from labelextract.contracts import (
    BoundingBox,
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    ImageRef,
    OcrResult,
    UnreadDeclaration,
)
from labelextract.exceptions import LabelExtractError
from labelextract.interfaces import FieldExtractor, ImagePreprocessor, OcrEngine

logger = logging.getLogger(__name__)


class ExtractionPipeline:
    """Runs the configured components against one image.

    Args:
        name: Pipeline identifier persisted on the extraction run.
        version: Pipeline version persisted alongside `name`.
        ocr_engine: Required. Without recognition there is nothing to extract.
        preprocessor: Optional image preparation stage.
        field_extractor: Optional interpretation stage. When absent, the result
            carries recognised text but no declarations - useful while an OCR
            engine is being evaluated on its own.
    """

    def __init__(
        self,
        *,
        name: str,
        version: str,
        ocr_engine: OcrEngine,
        preprocessor: ImagePreprocessor | None = None,
        field_extractor: FieldExtractor | None = None,
    ) -> None:
        if ocr_engine is None:
            raise ValueError("ExtractionPipeline requires an ocr_engine")
        self.name = name
        self.version = version
        self.ocr_engine = ocr_engine
        self.preprocessor = preprocessor
        self.field_extractor = field_extractor

    @property
    def is_placeholder(self) -> bool:
        """True when any configured component is wiring-only."""
        components = (self.preprocessor, self.ocr_engine, self.field_extractor)
        return any(c is not None and c.is_placeholder for c in components)

    def warmup(self) -> None:
        for component in (self.preprocessor, self.ocr_engine, self.field_extractor):
            if component is not None:
                component.warmup()

    def run(self, image: ImageRef) -> ExtractionResult:
        """Execute the pipeline and return a structured result."""
        started = time.perf_counter()
        source = image
        scale: tuple[float, float] | None = None
        unread: tuple[UnreadDeclaration, ...] = ()
        try:
            if self.preprocessor is not None:
                source = self.preprocessor.process(image)

            ocr = self.ocr_engine.recognise(source)

            # Before extraction, so fields inherit corrected geometry.
            scale = _scale_to_source(original=image, processed=source)
            ocr = _rescaled(ocr, scale, original=image)

            fields: tuple[ExtractedField, ...] = ()
            if self.field_extractor is not None:
                fields = self.field_extractor.extract(ocr, source)
                unread = self._unread_declarations(ocr, fields)
        except LabelExtractError as exc:
            return self._failure(exc, started)
        finally:
            # Runs on the success path, the recorded-failure path and the
            # re-raised-bug path alike: an intermediate file must not survive
            # any of them. `source is not image` is the test for "the
            # preprocessor created this", so the original is never touched.
            if self.preprocessor is not None and source is not image:
                self._release(source)

        return ExtractionResult(
            status=self._status_for(ocr, fields),
            engine_name=self.name,
            engine_version=self.version,
            processing_ms=_elapsed_ms(started),
            ocr=ocr,
            fields=fields,
            is_placeholder=self.is_placeholder,
            metadata=self._metadata(image, source, scale, unread),
        )

    def _unread_declarations(
        self, ocr: OcrResult, fields: tuple[ExtractedField, ...]
    ) -> tuple[UnreadDeclaration, ...]:
        """Ask the extractor what it saw named but could not read.

        Optional on the interface, so an extractor that does not implement it
        contributes nothing and nothing changes for it.

        Guarded, and for the same reason `_release` is: this is a *secondary*
        observation about a result that is already complete. An extractor
        raising here must not cost the caller the declarations that were
        successfully read - that would trade a whole result for a footnote
        about it.

        "Not implemented" and "implemented and broken" are separated on
        purpose. `FieldExtractor` supplies a default, so a subclass always has
        the method; an extractor that does not subclass it is out of contract
        but perfectly functional, and logging a traceback for it on every
        single image would bury the case that actually needs attention.
        """
        reporter = getattr(self.field_extractor, "unread_declarations", None)
        if reporter is None:
            return ()

        try:
            return tuple(reporter(ocr, fields))
        except Exception:
            logger.warning(
                "Field extractor %r failed to report unread declarations; "
                "continuing with the fields it did extract",
                getattr(self.field_extractor, "name", self.field_extractor),
                exc_info=True,
            )
            return ()

    def _release(self, processed: ImageRef) -> None:
        """Discard a preprocessing intermediate without ever failing the run.

        `release()` is called from a `finally`, which is the most dangerous
        place in this class for an exception to escape. Raising there would
        replace whatever the block was doing:

        - a successful extraction would become a crash, losing a result that
          was already complete and correct;
        - a recorded `FAILED` result would be discarded mid-`return`, so the
          `error_code` explaining the real problem never reaches the caller;
        - a genuine bug propagating out of an engine would be masked by a
          message about a temporary file.

        In every case the caller would be told about the wrong thing. Cleanup
        is housekeeping: it cannot be allowed to overrule the outcome of the
        work it is cleaning up after.

        `ImagePreprocessor.release` is documented as never raising, and the one
        implementation here honours that. This guard is for the ones that do
        not - a future engine, or a third-party preprocessor - so their bug
        costs a leftover file and a log line instead of a lost extraction.
        """
        try:
            self.preprocessor.release(processed)
        except Exception:
            # Logged with a traceback so the faulty implementation is
            # findable, then deliberately dropped.
            logger.warning(
                "Preprocessor %r failed to release %s; continuing so the "
                "extraction result is not lost",
                getattr(self.preprocessor, "name", self.preprocessor),
                processed.path,
                exc_info=True,
            )

    def _metadata(
        self,
        image: ImageRef,
        source: ImageRef,
        scale: tuple[float, float] | None = None,
        unread: tuple[UnreadDeclaration, ...] = (),
    ) -> dict:
        """Which components ran, and what the image looked like on the way in.

        Persisted verbatim by the backend into `ExtractionRun.raw_output`. It
        records *how* a result was produced, which is what makes a
        disappointing run diagnosable months later without re-running it.

        `preprocessed_dimensions` differing from `source_dimensions` means the
        preprocessor resized. `bounding_box_space` then says whether the boxes
        were mapped back: "source" when the scale was known and applied,
        "preprocessed" when the dimensions were not recorded and no honest
        mapping was possible. A consumer drawing boxes over the original must
        read that key rather than assume.

        `unread_declarations` is the exception to "nothing here is an
        extraction result": it is an observation *about* the extraction -
        declarations named on the label whose values could not be read. It
        rides here rather than on `ExtractionResult.fields` because it is
        explicitly not a field (see `contracts.UnreadDeclaration`), and
        because the backend already persists this whole mapping verbatim, so
        the signal reaches a stored run with no change on that side.
        """
        return {
            "unread_declarations": [item.as_dict() for item in unread],
            "bounding_box_space": (
                "preprocessed"
                if source is not image and scale is None
                else "source"
            ),
            "preprocessing_scale": list(scale) if scale is not None else None,
            "preprocessed": self.preprocessor is not None,
            "field_extraction_ran": self.field_extractor is not None,
            "source_image_format": image.image_format,
            "source_dimensions": _dimensions(image),
            "preprocessed_dimensions": (
                _dimensions(source) if source is not image else None
            ),
            "preprocessor_name": _component_name(self.preprocessor),
            "ocr_engine_name": self.ocr_engine.name,
            "ocr_engine_version": self.ocr_engine.version,
            "field_extractor_name": _component_name(self.field_extractor),
        }

    def _status_for(
        self, ocr: OcrResult, fields: tuple[ExtractedField, ...]
    ) -> ExtractionStatus:
        """EMPTY when nothing was recognised, COMPLETED otherwise.

        EMPTY is reported on the OCR text alone. Recognising text but matching
        no declarations is a COMPLETED run with zero fields - the difference
        matters downstream: "the photo was unreadable" and "the photo was
        readable and these declarations were absent" are different findings.
        """
        if not ocr.blocks and not fields:
            return ExtractionStatus.EMPTY
        return ExtractionStatus.COMPLETED

    def _failure(self, exc: LabelExtractError, started: float) -> ExtractionResult:
        return ExtractionResult(
            status=ExtractionStatus.FAILED,
            engine_name=self.name,
            engine_version=self.version,
            processing_ms=_elapsed_ms(started),
            is_placeholder=self.is_placeholder,
            error_code=exc.code,
            error_message=str(exc),
        )


def _scale_to_source(
    *, original: ImageRef, processed: ImageRef
) -> tuple[float, float] | None:
    """Factors that carry a preprocessed-space coordinate back to the source.

    None means "not determinable, so nothing will be moved": either no
    preprocessing ran, or one of the two images did not record its dimensions.
    Guessing a scale would put every box in the wrong place while looking
    exactly as authoritative as a correct one, so the honest outcome is to
    leave the boxes alone and say so in `metadata["bounding_box_space"]`.
    """
    if processed is original:
        return None
    for value in (
        original.width, original.height, processed.width, processed.height
    ):
        if not value:  # None, or a zero that would divide badly
            return None
    return (
        original.width / processed.width,
        original.height / processed.height,
    )


def _rescaled(
    ocr: OcrResult, scale: tuple[float, float] | None, *, original: ImageRef
) -> OcrResult:
    """Return `ocr` with every block box expressed in source-image space.

    The engine's `raw` diagnostics are deliberately left untouched. They are
    documented as the engine's verbatim output, and rewriting coordinates
    inside a structure whose shape is the engine's business would make this
    orchestrator depend on which engine ran. Anything reading `raw` word
    geometry is reading engine-space and `metadata["preprocessing_scale"]` is
    what converts it.
    """
    if scale is None:
        return ocr
    scale_x, scale_y = scale
    if scale_x == 1.0 and scale_y == 1.0:
        return ocr
    return replace(
        ocr,
        blocks=tuple(
            replace(block, box=_scale_box(block.box, scale_x, scale_y, original))
            for block in ocr.blocks
        ),
    )


def _scale_box(
    box: BoundingBox | None, scale_x: float, scale_y: float, original: ImageRef
) -> BoundingBox | None:
    """Scale one box, keeping it valid and inside the source image.

    `BoundingBox` refuses a zero-width or negative-origin box, and rounding a
    two-pixel box down can produce either. Clamping to a minimum of one pixel
    keeps a real detection representable; dropping it would lose the evidence
    the box exists to provide.
    """
    if box is None:
        return None

    x = max(0, round(box.x * scale_x))
    y = max(0, round(box.y * scale_y))
    width = max(1, round(box.width * scale_x))
    height = max(1, round(box.height * scale_y))

    # A box that rounds past the edge would describe pixels the reviewer cannot
    # be shown. Pull it back inside rather than reporting a region that is not
    # in the photograph.
    if original.width:
        x = min(x, original.width - 1)
        width = min(width, original.width - x)
    if original.height:
        y = min(y, original.height - 1)
        height = min(height, original.height - y)

    return BoundingBox(x=x, y=y, width=max(1, width), height=max(1, height))


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _dimensions(image: ImageRef) -> list[int] | None:
    """[width, height], or None when either was never measured."""
    if image.width is None or image.height is None:
        return None
    return [image.width, image.height]


def _component_name(component: object | None) -> str | None:
    return None if component is None else getattr(component, "name", None)
