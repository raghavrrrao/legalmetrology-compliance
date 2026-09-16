"""`product_classification` on the wire: an observation beside the reading.

The classifier lives in `ml/` and runs as the last stage of the extraction
pipeline; its output rides in `ExtractionRun.raw_output["metadata"]` the
same way `unread_declarations` does, and the serializer surfaces it. Three
things are pinned here:

- **Additive.** The field appears on the extraction body and inside the
  `extraction` block of a compliance result, and it is `null` for every run
  that carries none - older runs, pipelines without a classifier, failed
  classifiers. Nothing an existing client reads has moved.
- **Inert.** A classification changes no verdict. The compliance engine
  answers applicability from `Product.category` and the stated declarations,
  and a run whose classifier said "packaged-food" still evaluates as a
  submission of unknown commodity unless a person said otherwise.
- **Real.** One test drives the shipped classifier - the actual artifact -
  through the endpoint over a stubbed OCR engine, so the vocabulary the
  API emits is the vocabulary the ml/ package defines.

Recognition is stubbed for the reason every test in this app stubs it: a
test that needed Tesseract would fail on half the team's machines and would
be measuring recognition rather than integration.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from labelextract import registry
from labelextract.classification import (
    build_classifier,
    load_dataset,
    taxonomy,
)
from labelextract.contracts import (
    BoundingBox,
    ImageRef,
    OcrResult,
    ProductClassification,
    TextBlock,
)
from labelextract.interfaces import OcrEngine, ProductClassifier
from labelextract.pipeline import ExtractionPipeline

from apps.catalog.management.commands.seed_categories import _CATEGORIES
from apps.compliance.models import ComplianceCheck
from apps.extraction.api.serializers import ExtractionRunSerializer
from apps.extraction.models import ExtractionRun
from apps.extraction.services import extraction_service

pytestmark = pytest.mark.django_db

_CLASSIFYING_PIPELINE = "classification-api-shipped"
_EXPLODING_PIPELINE = "classification-api-exploding"
_TEST_VERSION = "0.0.0"


def _seed_text(example_id: str) -> str:
    return next(e.text for e in load_dataset().examples if e.example_id == example_id)


class _LabelOcr(OcrEngine):
    """Reads the Plix declaration face, line by line, off any image."""

    name = "classification-api-ocr"
    version = _TEST_VERSION

    def recognise(self, image: ImageRef) -> OcrResult:
        lines = _seed_text("p002_03_left/transcription").splitlines()
        return OcrResult(
            blocks=tuple(
                TextBlock(text, BoundingBox(4, 4 + i * 20, 300, 18), 0.9)
                for i, text in enumerate(lines)
            ),
            raw={"source": "classification-api-test"},
        )


class _Exploding(ProductClassifier):
    name = "classification-api-exploding"
    version = _TEST_VERSION

    def classify(self, ocr, fields, image) -> ProductClassification:
        raise RuntimeError("classifier bug")


@pytest.fixture(autouse=True)
def _register_test_pipelines():
    registered = set(registry.available_pipelines())

    def _ensure(name, factory):
        if (name, _TEST_VERSION) not in registered:
            registry.register_pipeline(name, _TEST_VERSION, factory)

    _ensure(
        _CLASSIFYING_PIPELINE,
        lambda: ExtractionPipeline(
            name=_CLASSIFYING_PIPELINE, version=_TEST_VERSION,
            ocr_engine=_LabelOcr(), classifier=build_classifier(),
        ),
    )
    _ensure(
        _EXPLODING_PIPELINE,
        lambda: ExtractionPipeline(
            name=_EXPLODING_PIPELINE, version=_TEST_VERSION,
            ocr_engine=_LabelOcr(), classifier=_Exploding(),
        ),
    )


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    settings.DEMO_PUBLIC_ANALYSIS_API = True


@pytest.fixture
def classifying_pipeline(settings):
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = _CLASSIFYING_PIPELINE
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _TEST_VERSION


def _upload(client, png_bytes, url_name="v1:label-extract"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return client.post(
        reverse(url_name),
        {"image": SimpleUploadedFile("label.png", png_bytes, content_type="image/png")},
        format="multipart",
    )


# --- the serializer ---------------------------------------------------------


def _run_with_metadata(product_image, metadata) -> ExtractionRun:
    return ExtractionRun.objects.create(
        image=product_image, engine_name="stub", engine_version="0",
        status=ExtractionRun.Status.COMPLETED,
        raw_output={"engine_raw": {}, "metadata": metadata, "block_count": 0},
    )


def test_a_stored_classification_is_passed_through_unchanged(product_image):
    classification = ProductClassification(
        category="packaged-food", subcategory="health-supplement",
        confidence=0.7232, subcategory_confidence=0.5517,
        evidence=("signal: fssai (typical of packaged-food)",),
        category_scores={"packaged-food": 0.7232, "packaged-non-food": 0.2768},
        subcategory_scores={"general-food": 0.1715, "health-supplement": 0.5517},
        classifier_name="tfidf-logreg", classifier_version="0.1.0",
    ).as_dict()
    run = _run_with_metadata(product_image, {"product_classification": classification})

    assert ExtractionRunSerializer(run).data["product_classification"] == classification


def test_a_run_without_a_classification_reports_null(product_image):
    run = _run_with_metadata(product_image, {"unread_declarations": []})
    assert ExtractionRunSerializer(run).data["product_classification"] is None


def test_a_run_from_before_the_field_existed_reports_null(product_image):
    run = ExtractionRun.objects.create(
        image=product_image, engine_name="old", engine_version="0",
        status=ExtractionRun.Status.COMPLETED, raw_output={},
    )
    assert ExtractionRunSerializer(run).data["product_classification"] is None


@pytest.mark.parametrize("junk", ["packaged-food", 12, [], {"confidence": 0.9}, {"category": 3}])
def test_malformed_metadata_reports_null_rather_than_a_category(product_image, junk):
    run = _run_with_metadata(product_image, {"product_classification": junk})
    assert ExtractionRunSerializer(run).data["product_classification"] is None


def test_an_unknown_classification_is_not_null(product_image):
    """The classifier ran and declined. That is an answer, not an absence."""
    unknown = ProductClassification(
        category=taxonomy.UNKNOWN, evidence=("insufficient text",),
        classifier_name="tfidf-logreg", classifier_version="0.1.0",
    ).as_dict()
    run = _run_with_metadata(product_image, {"product_classification": unknown})
    body = ExtractionRunSerializer(run).data["product_classification"]
    assert body["category"] == "unknown"
    assert body["confidence"] is None


# --- through the pipeline and the endpoint ----------------------------------


def test_the_shipped_classifier_reaches_the_stored_run(product_image, classifying_pipeline):
    run = extraction_service.run_extraction(product_image)

    assert run.status == ExtractionRun.Status.COMPLETED
    body = run.raw_output["metadata"]["product_classification"]
    assert body["category"] == "packaged-food"
    assert body["subcategory"] == "health-supplement"
    assert body["classifier_name"] == "tfidf-logreg"
    assert body["classifier_version"] == build_classifier().version
    assert run.raw_output["metadata"]["classifier_name"] == "tfidf-logreg"


def test_the_extraction_endpoint_carries_the_classification(client, png_bytes, media_root, classifying_pipeline):
    response = _upload(client, png_bytes)

    assert response.status_code == 201
    body = response.json()
    classification = body["product_classification"]
    assert classification["category"] == "packaged-food"
    assert classification["subcategory"] == "health-supplement"
    assert 0.0 <= classification["confidence"] <= 1.0
    assert any("nutritional information" in item for item in classification["evidence"])
    assert set(classification) == {
        "category", "subcategory", "confidence", "subcategory_confidence",
        "evidence", "category_scores", "subcategory_scores",
        "classifier_name", "classifier_version",
    }
    # The reading itself is untouched by the new stage.
    assert body["recognised_text"].startswith("Nutritional Information")
    assert "result" not in body and "violations" not in body


def test_a_classifier_failure_costs_the_field_not_the_reading(client, png_bytes, media_root, settings):
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = _EXPLODING_PIPELINE
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _TEST_VERSION

    response = _upload(client, png_bytes)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert body["produced_usable_output"] is True
    assert body["product_classification"] is None


def test_the_compliance_result_embeds_the_classification_and_ignores_it(
    client, png_bytes, media_root, classifying_pipeline
):
    """The category the classifier suggests changes nothing downstream.

    No `category_code` was given and no product exists, so the engine must
    still report that the commodity is not known - however confidently the
    classifier thinks it is a food.
    """
    response = _upload(client, png_bytes, url_name="v1:image-analyse")

    assert response.status_code == 201
    body = response.json()
    assert body["extraction"]["product_classification"]["category"] == "packaged-food"
    assert body["product_category_code"] is None
    assert body["result"] == ComplianceCheck.Result.REVIEW_REQUIRED
    assert body["rules_evaluated"] == 0


# --- the vocabulary is the backend's ------------------------------------------


def test_classifier_categories_are_seeded_product_category_codes():
    """A category the classifier can answer with must be a code the backend
    already knows, or the applicability layer could never consume it."""
    seeded = {code for code, _name, _parent in _CATEGORIES}
    assert set(taxonomy.CATEGORIES) <= seeded
    assert taxonomy.UNKNOWN not in seeded


def test_subcategories_that_name_a_condition_name_a_loaded_one(settings):
    """Where a subcategory reuses an applicability-condition code, the
    framework files must define that code, or the reuse is fiction."""
    import json
    from pathlib import Path

    conditions = json.loads(
        (Path(settings.RULES_FRAMEWORK_DIR) / "applicability_conditions.json")
        .read_text(encoding="utf-8")
    )
    codes = {item["code"] for item in conditions["conditions"]}
    named = {
        item.applicability_condition for item in taxonomy.SUBCATEGORIES
        if item.applicability_condition is not None
    }
    assert named
    assert named <= codes


def test_the_serializer_imports_no_ml_runtime():
    """The field is read out of stored JSON, so the import boundary pinned by
    `test_extraction_integration.py` holds: only `extraction_service` runs an
    engine, and this serializer runs nothing."""
    from pathlib import Path

    from apps.extraction.api import serializers

    source = Path(serializers.__file__).read_text(encoding="utf-8")
    assert "import labelextract" not in source
    assert "from labelextract" not in source


# --- failure safety through the service and the health check --------------


_MISSING_ARTIFACT_PIPELINE = "classification-api-missing-artifact"


@pytest.fixture
def missing_artifact_pipeline(settings, tmp_path):
    """The shipped classifier class, pointed at an artifact that is absent -
    the failure a broken package build would produce - behind stubbed OCR."""
    from labelextract.classification.classifier import TfidfProductClassifier

    if (_MISSING_ARTIFACT_PIPELINE, _TEST_VERSION) not in set(registry.available_pipelines()):
        registry.register_pipeline(
            _MISSING_ARTIFACT_PIPELINE, _TEST_VERSION,
            lambda: ExtractionPipeline(
                name=_MISSING_ARTIFACT_PIPELINE, version=_TEST_VERSION,
                ocr_engine=_LabelOcr(),
                classifier=TfidfProductClassifier(
                    tmp_path / "absent.json", version="0.0.0"
                ),
            ),
        )
    registry.clear_cache()
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = _MISSING_ARTIFACT_PIPELINE
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _TEST_VERSION


def test_a_missing_artifact_still_stores_a_completed_reading(product_image, missing_artifact_pipeline):
    run = extraction_service.run_extraction(product_image)

    assert run.status == ExtractionRun.Status.COMPLETED
    assert run.produced_usable_output is True
    assert run.error_code == ""
    assert run.recognised_text.startswith("Nutritional Information")
    assert run.raw_output["metadata"]["product_classification"] is None
    assert run.raw_output["metadata"]["classifier_name"] == "tfidf-logreg"


def test_a_missing_artifact_is_reported_by_the_health_check(client, missing_artifact_pipeline):
    """Deliberate, and worth stating: the health endpoint warms every stage,
    so a 0.4.0 deployment whose classifier artifact is absent reports the
    pipeline `available: false` - even though uploads would still produce a
    reading with a null classification. The artifact ships inside the
    package, so this can only happen with a broken build, and a broken build
    should fail its health check rather than run quietly degraded. If that
    trade-off is ever changed, this test is the place it is decided."""
    body = client.get(reverse("v1:health")).json()

    assert body["extraction_engine"]["available"] is False
    assert body["extraction_engine"]["detail"] == "engine_not_available"
    assert body["extraction_engine"]["is_placeholder"] is False


def test_the_shipped_artifact_passes_the_health_check(client, classifying_pipeline):
    """The counterpart: with the real artifact in place, warm-up succeeds."""
    body = client.get(reverse("v1:health")).json()

    assert body["extraction_engine"]["available"] is True
    assert body["extraction_engine"]["detail"] == ""
