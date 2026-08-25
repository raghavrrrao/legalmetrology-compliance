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
        try:
            source = image
            if self.preprocessor is not None:
                source = self.preprocessor.process(image)

            ocr = self.ocr_engine.recognise(source)

            fields: tuple[ExtractedField, ...] = ()
            if self.field_extractor is not None:
                fields = self.field_extractor.extract(ocr, source)
        except LabelExtractError as exc:
            return self._failure(exc, started)

        return ExtractionResult(
            status=self._status_for(ocr, fields),
            engine_name=self.name,
            engine_version=self.version,
            processing_ms=_elapsed_ms(started),
            ocr=ocr,
            fields=fields,
            is_placeholder=self.is_placeholder,
            metadata={
                "preprocessed": self.preprocessor is not None,
                "field_extraction_ran": self.field_extractor is not None,
                "source_image_format": image.image_format,
            },
        )

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
