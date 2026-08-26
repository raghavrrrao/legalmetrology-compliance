"""Concrete orchestrator that turns pluggable components into an ExtractionResult.

This is the only place that knows the ordering of the extraction stages. It is
a plain class, not an abstract one: there is exactly one sensible order for
these stages, so there is nothing worth subclassing.

    ImageRef
        -> ImagePreprocessor.process()   (optional)
        -> OcrEngine.recognise()         (required)
        -> FieldExtractor.extract()      (optional)
        -> ExtractionResult

Failure policy: a `LabelExtractError` from any stage is caught and turned into
`ExtractionResult(status=FAILED, error_code=...)` rather than propagating. The
backend records a failed run and moves on; one unreadable photograph must not
take down a batch. Unexpected exceptions are NOT caught - a bug in an engine
should surface loudly rather than be recorded as "this image was unreadable".
"""

from __future__ import annotations

import time

from labelextract.contracts import (
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    ImageRef,
    OcrResult,
)
from labelextract.exceptions import LabelExtractError
from labelextract.interfaces import FieldExtractor, ImagePreprocessor, OcrEngine


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
        try:
            if self.preprocessor is not None:
                source = self.preprocessor.process(image)

            ocr = self.ocr_engine.recognise(source)

            fields: tuple[ExtractedField, ...] = ()
            if self.field_extractor is not None:
                fields = self.field_extractor.extract(ocr, source)
        except LabelExtractError as exc:
            return self._failure(exc, started)
        finally:
            # Runs on the success path, the recorded-failure path and the
            # re-raised-bug path alike: an intermediate file must not survive
            # any of them. `source is not image` is the test for "the
            # preprocessor created this", so the original is never touched.
            if self.preprocessor is not None and source is not image:
                self.preprocessor.release(source)

        return ExtractionResult(
            status=self._status_for(ocr, fields),
            engine_name=self.name,
            engine_version=self.version,
            processing_ms=_elapsed_ms(started),
            ocr=ocr,
            fields=fields,
            is_placeholder=self.is_placeholder,
            metadata=self._metadata(image, source),
        )

    def _metadata(self, image: ImageRef, source: ImageRef) -> dict:
        """Which components ran, and what the image looked like on the way in.

        Persisted verbatim by the backend into `ExtractionRun.raw_output`. It
        records *how* a result was produced, which is what makes a
        disappointing run diagnosable months later without re-running it.

        `preprocessed_dimensions` matters more than it looks: when it differs
        from `source_dimensions`, bounding boxes are in preprocessed-image
        space rather than source-image space, and anything drawing them over
        the original must scale them.
        """
        return {
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


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _dimensions(image: ImageRef) -> list[int] | None:
    """[width, height], or None when either was never measured."""
    if image.width is None or image.height is None:
        return None
    return [image.width, image.height]


def _component_name(component: object | None) -> str | None:
    return None if component is None else getattr(component, "name", None)
