"""The classifier as a pipeline stage: where its output lands, what it never touches.

The OCR engine is always a stub here so the tests need no binary. What is
exercised is the orchestration: the classification rides in metadata, the
reading is byte-identical with and without a classifier, a classifier
failure costs the classification and not the reading, and the registered
Tesseract pipelines are wired the way `.env.example` says.
"""

from __future__ import annotations

import pytest

from labelextract import registry
from labelextract.classification import build_classifier
from labelextract.classification.classifier import TfidfProductClassifier
from labelextract.contracts import (
    UNKNOWN_CATEGORY,
    BoundingBox,
    ExtractionStatus,
    ImageRef,
    OcrResult,
    ProductClassification,
    TextBlock,
)
from labelextract.exceptions import EngineNotAvailableError
from labelextract.fields import RuleBasedFieldExtractor
from labelextract.interfaces import OcrEngine, ProductClassifier
from labelextract.ocr import tesseract
from labelextract.pipeline import ExtractionPipeline


FOOD_LINES = (
    "Nutritional Information",
    "Ingredients: wheat flour, sugar, edible oil",
    "FSSAI Lic. No. 10012345678901",
    "Energy 450 kcal",
    "Net Qty: 500 g",
    "MRP Rs. 120.00 (incl. of all taxes)",
)


class StubOcr(OcrEngine):
    name = "stub-ocr"
    version = "0"

    def __init__(self, lines=FOOD_LINES):
        self.lines = lines

    def recognise(self, image):
        return OcrResult(
            blocks=tuple(
                TextBlock(text, BoundingBox(1, 1 + i * 20, 300, 18), 0.9)
                for i, text in enumerate(self.lines)
            ),
            raw={"engine": "stub"},
        )


class Exploding(ProductClassifier):
    name = "exploding"
    version = "0"

    def classify(self, ocr, fields, image):
        raise RuntimeError("boom")


class Unavailable(ProductClassifier):
    name = "unavailable"
    version = "0"

    def classify(self, ocr, fields, image):
        raise EngineNotAvailableError("no artifact")


def pipeline(classifier, lines=FOOD_LINES) -> ExtractionPipeline:
    return ExtractionPipeline(
        name="test", version="0",
        ocr_engine=StubOcr(lines),
        field_extractor=RuleBasedFieldExtractor(),
        classifier=classifier,
    )


@pytest.fixture
def fixture_classifier(classification_artifact):
    return TfidfProductClassifier(classification_artifact(), version="test")


# --- where the output lands -----------------------------------------------------


def test_classification_rides_in_metadata(image_ref, fixture_classifier):
    result = pipeline(fixture_classifier).run(image_ref)
    assert result.status is ExtractionStatus.COMPLETED
    body = result.metadata["product_classification"]
    assert body["category"] == "packaged-food"
    assert body["classifier_name"] == "tfidf-logreg"
    assert body["classifier_version"] == "test"
    assert result.metadata["classifier_name"] == "tfidf-logreg"
    assert result.metadata["classifier_version"] == "test"


def test_classification_is_never_a_field(image_ref, fixture_classifier):
    """A consumer iterating `fields` must never meet a category."""
    result = pipeline(fixture_classifier).run(image_ref)
    assert all(not isinstance(field, ProductClassification) for field in result.fields)
    assert {field.key.value for field in result.fields} == {"net_quantity", "retail_sale_price"}


def test_the_reading_is_identical_with_and_without_a_classifier(image_ref, fixture_classifier):
    with_ = pipeline(fixture_classifier).run(image_ref)
    without = pipeline(None).run(image_ref)
    assert with_.ocr == without.ocr
    assert with_.fields == without.fields
    assert with_.status == without.status
    assert without.metadata["product_classification"] is None
    assert without.metadata["classifier_name"] is None
    assert without.metadata["classifier_version"] is None


def test_the_classifier_sees_the_full_text_and_the_fields(image_ref, fixture_classifier):
    seen = {}

    class Recording(ProductClassifier):
        name = "recording"
        version = "0"

        def classify(self, ocr, fields, image):
            seen.update(text=ocr.full_text, fields=fields, image=image)
            return fixture_classifier.classify_text(ocr.full_text)

    pipeline(Recording()).run(image_ref)
    assert seen["text"] == "\n".join(FOOD_LINES)
    assert {field.key.value for field in seen["fields"]} == {"net_quantity", "retail_sale_price"}
    assert isinstance(seen["image"], ImageRef)


def test_an_empty_reading_classifies_as_unknown_not_as_food(image_ref, fixture_classifier):
    result = pipeline(fixture_classifier, lines=()).run(image_ref)
    assert result.status is ExtractionStatus.EMPTY
    assert result.metadata["product_classification"]["category"] == UNKNOWN_CATEGORY
    assert result.metadata["product_classification"]["confidence"] is None


# --- failure isolation --------------------------------------------------------


def test_a_classifier_bug_costs_the_classification_not_the_reading(image_ref, caplog):
    result = pipeline(Exploding()).run(image_ref)
    assert result.status is ExtractionStatus.COMPLETED
    assert len(result.fields) == 2
    assert result.metadata["product_classification"] is None
    assert result.metadata["classifier_name"] == "exploding"
    assert any("Product classifier" in record.message for record in caplog.records)


def test_a_missing_artifact_does_not_fail_the_run(image_ref):
    """`EngineNotAvailableError` from the OCR stage fails a run. From the
    classifier it must not: the label was read fine."""
    result = pipeline(Unavailable()).run(image_ref)
    assert result.status is ExtractionStatus.COMPLETED
    assert result.error_code is None
    assert result.metadata["product_classification"] is None


def test_warmup_reaches_the_classifier(image_ref, tmp_path):
    missing = TfidfProductClassifier(tmp_path / "absent.json", version="test")
    with pytest.raises(EngineNotAvailableError):
        pipeline(missing).warmup()


def test_a_placeholder_classifier_marks_the_pipeline(image_ref, fixture_classifier):
    class Placeholder(ProductClassifier):
        name = "placeholder"
        version = "0"

        @property
        def is_placeholder(self):
            return True

        def classify(self, ocr, fields, image):
            return fixture_classifier.classify_text(ocr.full_text)

    assert pipeline(Placeholder()).is_placeholder is True
    assert pipeline(fixture_classifier).is_placeholder is False


# --- the registered pipelines -----------------------------------------------


def test_the_current_tesseract_pipeline_carries_the_shipped_classifier():
    current = registry.get_pipeline(tesseract.NAME, tesseract.VERSION)
    assert tesseract.VERSION == "0.4.0"
    assert isinstance(current.classifier, TfidfProductClassifier)
    assert current.classifier.version == build_classifier().version


def test_the_extraction_only_pipeline_is_the_current_one_minus_the_classifier():
    current = registry.get_pipeline(tesseract.NAME, tesseract.VERSION)
    frozen = registry.get_pipeline(tesseract.NAME, tesseract.EXTRACTION_ONLY_VERSION)
    assert tesseract.EXTRACTION_ONLY_VERSION == "0.3.0"
    assert frozen.classifier is None
    assert type(frozen.ocr_engine) is type(current.ocr_engine)
    assert frozen.ocr_engine.options == current.ocr_engine.options
    assert frozen.preprocessor.config == current.preprocessor.config
    assert type(frozen.field_extractor) is type(current.field_extractor)


def test_older_pipelines_have_no_classifier():
    for version in (tesseract.PREVIOUS_VERSION, tesseract.BASELINE_VERSION):
        assert registry.get_pipeline(tesseract.NAME, version).classifier is None
    assert registry.get_pipeline("null-engine", "0.1.0").classifier is None


def test_every_tesseract_version_is_registered_in_order():
    versions = [v for name, v in registry.available_pipelines() if name == tesseract.NAME]
    assert versions == ["0.1.0", "0.2.0", "0.3.0", "0.4.0"]


def test_the_shipped_classifier_runs_inside_a_pipeline_over_stub_ocr(image_ref):
    """End to end through the real artifact with no OCR binary: the seed
    dataset's Plix declaration face, read by a stub engine line by line."""
    from labelextract.classification import load_dataset

    text = next(
        e.text for e in load_dataset().examples
        if e.example_id == "p002_03_left/transcription"
    )
    result = pipeline(build_classifier(), lines=tuple(text.splitlines())).run(image_ref)
    body = result.metadata["product_classification"]
    assert body["category"] == "packaged-food"
    assert body["subcategory"] == "health-supplement"
    assert body["classifier_version"] == "0.1.0"
    assert any("nutritional information" in item for item in body["evidence"])
