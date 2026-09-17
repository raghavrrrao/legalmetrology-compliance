"""Automatic applicability through the one-shot endpoint, over the real pipeline.

`POST /api/v1/images/` runs extraction and evaluation in one call, so the
classification the policy acts on is the one the *shipped* classifier produced
a moment earlier - not a fixture. Three things are pinned:

- with the default policy the shipped artifact is UNCERTAIN, the category is
  not filled, and the person is asked (B);
- with an accepted policy entry for the shipped artifact its category is
  established automatically and says so (A);
- a classifier that raises costs nothing but the classification: the reading
  is stored, the check is produced, and the assessment reads `failed` (D).

Recognition is stubbed, as every extraction test stubs it; the classifier is
the real artifact, or one that explodes.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from labelextract import registry
from labelextract.classification import build_classifier, load_dataset
from labelextract.contracts import BoundingBox, ImageRef, OcrResult, ProductClassification, TextBlock
from labelextract.interfaces import OcrEngine, ProductClassifier
from labelextract.pipeline import ExtractionPipeline

from apps.catalog.models import Product, ProductCategory
from apps.compliance.models import ComplianceCheck
from apps.extraction.models import ExtractionRun
from apps.rules.framework_loader import load_framework
from apps.rules.loader import load_rules

pytestmark = pytest.mark.django_db

_SHIPPED = "auto-applicability-shipped"
_EXPLODING = "auto-applicability-exploding"
_VERSION = "0.0.0"


def _seed_text(example_id: str) -> str:
    return next(e.text for e in load_dataset().examples if e.example_id == example_id)


class _LabelOcr(OcrEngine):
    """Reads the Plix declaration face off any image - a packaged food."""

    name = "auto-applicability-ocr"
    version = _VERSION

    def recognise(self, image: ImageRef) -> OcrResult:
        lines = _seed_text("p002_03_left/transcription").splitlines()
        return OcrResult(
            blocks=tuple(TextBlock(text, BoundingBox(4, 4 + i * 20, 300, 18), 0.9) for i, text in enumerate(lines)),
            raw={"source": "auto-applicability-test"},
        )


class _Exploding(ProductClassifier):
    name = "auto-applicability-exploding"
    version = _VERSION

    def classify(self, ocr, fields, image) -> ProductClassification:
        raise RuntimeError("classifier bug")


@pytest.fixture(autouse=True)
def _register_pipelines():
    registered = set(registry.available_pipelines())
    if (_SHIPPED, _VERSION) not in registered:
        registry.register_pipeline(
            _SHIPPED,
            _VERSION,
            lambda: ExtractionPipeline(name=_SHIPPED, version=_VERSION, ocr_engine=_LabelOcr(), classifier=build_classifier()),
        )
    if (_EXPLODING, _VERSION) not in registered:
        registry.register_pipeline(
            _EXPLODING,
            _VERSION,
            lambda: ExtractionPipeline(name=_EXPLODING, version=_VERSION, ocr_engine=_LabelOcr(), classifier=_Exploding()),
        )


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    settings.DEMO_PUBLIC_ANALYSIS_API = True


@pytest.fixture
def shipped_rules(settings, category, media_root):
    root = ProductCategory.objects.create(code="packaged-commodity", name="Packaged commodity")
    category.parent = root
    category.save()
    ProductCategory.objects.create(code="packaged-non-food", name="Packaged non-food", parent=root)
    assert load_rules(settings.RULES_DEFINITIONS_DIR).ok
    assert load_framework(settings.RULES_FRAMEWORK_DIR).ok


def _pipeline(settings, name):
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = name
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _VERSION


def _analyse(client, png_bytes, **fields):
    return client.post(
        reverse("v1:image-analyse"),
        {"image": SimpleUploadedFile("label.png", png_bytes, content_type="image/png"), **fields},
        format="multipart",
    )


def test_with_the_default_policy_the_shipped_classifier_is_a_suggestion(client, png_bytes, settings, shipped_rules):
    """B, over the real artifact."""
    _pipeline(settings, _SHIPPED)

    body = _analyse(client, png_bytes).json()

    assert body["extraction"]["product_classification"]["category"] == "packaged-food"
    assert body["product_category_code"] is None
    assert body["result"] == "review_required"
    assessment = body["applicability_assessment"]
    assert assessment["status"] == "uncertain"
    assert assessment["classifier"]["name"] == "tfidf-logreg"
    assert assessment["classifier"]["version"] == build_classifier().version
    assert assessment["category"]["proposed"] == "packaged-food"
    assert assessment["category"]["disposition"] == "needs_confirmation"
    assert assessment["questions"][0]["suggested"] == "packaged-food"
    assert Product.objects.filter(category_source="classifier").count() == 0


def test_with_an_accepted_policy_the_shipped_classifier_establishes_the_category(client, png_bytes, settings, shipped_rules):
    """A, over the real artifact, under an entry a deployment would have to write."""
    _pipeline(settings, _SHIPPED)
    artifact = f"tfidf-logreg/{build_classifier().version}"
    settings.AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS = {
        artifact: {"min_confidence": 0.60, "evaluation": "tests: hypothetical held-out evaluation"}
    }

    body = _analyse(client, png_bytes).json()

    assert body["product_category_code"] == "packaged-food"
    assert body["product_category_source"] == "classifier"
    assert body["rules_evaluated"] > 0
    assessment = body["applicability_assessment"]
    assert assessment["status"] == "confident"
    assert assessment["category"]["disposition"] == "established_automatically"
    assert assessment["questions"] == []
    product = ComplianceCheck.objects.get(pk=body["id"]).product
    assert product.category_source == "classifier"
    assert "tfidf-logreg" in product.category_basis and "hypothetical held-out evaluation" in product.category_basis


def test_a_stated_category_is_never_overridden_on_the_one_shot_path(client, png_bytes, settings, shipped_rules):
    _pipeline(settings, _SHIPPED)
    settings.AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS = {
        f"tfidf-logreg/{build_classifier().version}": {"min_confidence": 0.60, "evaluation": "tests"}
    }

    body = _analyse(client, png_bytes, category_code="packaged-non-food").json()

    assert body["product_category_code"] == "packaged-non-food"
    assert body["product_category_source"] == "submitter"
    assert body["applicability_assessment"]["category"]["disposition"] == "contradicted_by_submitter"


def test_a_classifier_that_raises_costs_only_the_classification(client, png_bytes, settings, shipped_rules):
    """D. The reading is stored, the verdict is produced, nothing is guessed."""
    _pipeline(settings, _EXPLODING)
    settings.AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS = {
        f"{_EXPLODING}/{_VERSION}": {"min_confidence": 0.5, "evaluation": "tests"}
    }

    response = _analyse(client, png_bytes)

    assert response.status_code == 201
    body = response.json()
    run = ExtractionRun.objects.get(pk=body["extraction"]["id"])
    assert run.status == ExtractionRun.Status.COMPLETED
    assert body["extraction"]["produced_usable_output"] is True
    assert body["extraction"]["recognised_text"]
    assert body["extraction"]["product_classification"] is None
    assert body["product_category_code"] is None
    assert body["result"] == "review_required"
    assert body["applicability_assessment"]["status"] == "failed"
    assert body["applicability_assessment"]["questions"][0]["kind"] == "category"
