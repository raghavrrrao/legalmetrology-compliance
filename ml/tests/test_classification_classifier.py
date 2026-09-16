"""`TfidfProductClassifier`: the output contract and the UNKNOWN path.

Every test here runs against a hand-built artifact, not the shipped one, so
what is asserted is the *mechanics* - thresholds, aggregation, evidence, the
shape of the answer - independently of what any trained model happens to
believe. The shipped artifact is exercised in `test_classification_regression.py`.
"""

from __future__ import annotations

import json

import pytest

from labelextract.classification import taxonomy
from labelextract.classification.classifier import (
    ClassifierConfig,
    TfidfProductClassifier,
    build_classifier,
)
from labelextract.contracts import (
    UNKNOWN_CATEGORY,
    BoundingBox,
    ImageRef,
    OcrResult,
    ProductClassification,
    TextBlock,
)
from labelextract.exceptions import EngineNotAvailableError


@pytest.fixture
def classifier(classification_artifact) -> TfidfProductClassifier:
    return TfidfProductClassifier(classification_artifact(), version="test")


def image_ref(tmp_path) -> ImageRef:
    return ImageRef(path=tmp_path / "x.png", image_format="png", size_bytes=1)


# --- the output contract ------------------------------------------------------


def test_returns_the_contract_type_with_every_field(classifier):
    result = classifier.classify_text("Ingredients: wheat. FSSAI 123. Energy 400 kcal")
    assert isinstance(result, ProductClassification)
    assert result.category == taxonomy.PACKAGED_FOOD
    assert result.subcategory == "general-food"
    assert 0.0 <= result.confidence <= 1.0
    assert 0.0 <= result.subcategory_confidence <= 1.0
    assert result.evidence and all(isinstance(item, str) for item in result.evidence)
    assert set(result.category_scores) == set(taxonomy.CATEGORIES)
    assert set(result.subcategory_scores) == set(classifier.model.classes)
    assert result.classifier_name == "tfidf-logreg"
    assert result.classifier_version == "test"
    assert not result.is_unknown


def test_as_dict_is_json_safe_and_carries_every_key(classifier):
    body = classifier.classify_text("Ingredients: wheat. FSSAI 123.").as_dict()
    assert set(body) == {
        "category", "subcategory", "confidence", "subcategory_confidence",
        "evidence", "category_scores", "subcategory_scores",
        "classifier_name", "classifier_version",
    }
    json.dumps(body)


def test_category_confidence_is_the_sum_of_its_subcategories(classifier):
    result = classifier.classify_text("Ingredients FSSAI energy supplement tablets serving")
    food = (
        result.subcategory_scores["general-food"]
        + result.subcategory_scores["health-supplement"]
    )
    assert result.category_scores[taxonomy.PACKAGED_FOOD] == pytest.approx(food, abs=1e-3)
    assert sum(result.category_scores.values()) == pytest.approx(1.0, abs=1e-3)
    assert result.confidence == result.category_scores[result.category]


def test_confidence_is_never_reported_as_a_compliance_figure(classifier):
    """No key of the output names a legal outcome."""
    body = classifier.classify_text("Ingredients FSSAI").as_dict()
    forbidden = {"compliant", "compliance", "violation", "verdict", "result", "status"}
    assert not forbidden & {key.lower() for key in body}


# --- known categories -------------------------------------------------------


@pytest.mark.parametrize(
    "text, category, subcategory",
    [
        ("detergent spray flammable keep away", taxonomy.PACKAGED_NON_FOOD, "cleaning-product"),
        ("shampoo soap bathing bar", taxonomy.PACKAGED_NON_FOOD, "cosmetics-and-toiletries"),
        ("supplement tablets serving size fssai", taxonomy.PACKAGED_FOOD, "health-supplement"),
        ("ingredients fssai energy kcal", taxonomy.PACKAGED_FOOD, "general-food"),
    ],
)
def test_known_signals_classify_as_expected(classifier, text, category, subcategory):
    result = classifier.classify_text(text)
    assert (result.category, result.subcategory) == (category, subcategory)


def test_mixed_casing_and_repetition_do_not_change_the_answer(classifier):
    base = classifier.classify_text("shampoo soap bathing bar")
    shouted = classifier.classify_text("SHAMPOO Soap BATHING bar")
    doubled = classifier.classify_text("shampoo soap bathing bar shampoo soap bathing bar")
    assert shouted.category_scores == base.category_scores
    # Doubling every count leaves the L2-normalised vector unchanged.
    assert doubled.category_scores == base.category_scores
    assert doubled.subcategory == base.subcategory


def test_is_deterministic(classifier):
    text = "Ingredients: wheat, sugar. FSSAI. Energy 400 kcal. Net Qty 500 g"
    first = classifier.classify_text(text)
    for _ in range(5):
        assert classifier.classify_text(text) == first


# --- the UNKNOWN path ---------------------------------------------------------


@pytest.mark.parametrize("text", [None, "", "   ", "\n\n"])
def test_missing_text_is_unknown_with_no_confidence(classifier, text):
    result = classifier.classify_text(text)
    assert result.is_unknown
    assert result.category == UNKNOWN_CATEGORY
    assert result.subcategory is None
    assert result.confidence is None
    assert result.subcategory_confidence is None
    assert any("insufficient text" in item for item in result.evidence)


def test_extremely_short_text_is_unknown(classifier):
    result = classifier.classify_text("Dove")
    assert result.is_unknown
    assert "insufficient text: 1 word token(s)" in result.evidence[0]


def test_garbage_ocr_that_matches_nothing_is_unknown(classifier):
    result = classifier.classify_text("xq zzv plorf wubb qqq kkk")
    assert result.is_unknown
    assert any("none of the 6 word token(s) is known" in item for item in result.evidence)
    assert result.confidence is None


def test_below_threshold_is_unknown_but_keeps_the_scores(classification_artifact):
    strict = TfidfProductClassifier(
        classification_artifact(), version="test",
        config=ClassifierConfig(min_category_confidence=1.0),
    )
    result = strict.classify_text("ingredients fssai energy")
    assert result.is_unknown
    assert result.confidence is None
    assert result.category_scores[taxonomy.PACKAGED_FOOD] > 0.5
    assert any("below confidence threshold 1.00" in item for item in result.evidence)
    assert any("best candidate packaged-food" in item for item in result.evidence)


def test_subcategory_below_threshold_leaves_the_category(classification_artifact):
    picky = TfidfProductClassifier(
        classification_artifact(), version="test",
        config=ClassifierConfig(min_subcategory_confidence=1.0),
    )
    result = picky.classify_text("ingredients fssai energy")
    assert result.category == taxonomy.PACKAGED_FOOD
    assert result.subcategory is None
    assert result.subcategory_confidence is None
    assert result.confidence is not None
    assert any("subcategory below threshold 1.00" in item for item in result.evidence)


def test_unknown_can_never_carry_a_subcategory():
    with pytest.raises(ValueError):
        ProductClassification(category=UNKNOWN_CATEGORY, subcategory="general-food")


def test_min_tokens_is_configurable(classification_artifact):
    lenient = TfidfProductClassifier(
        classification_artifact(), version="test",
        config=ClassifierConfig(min_tokens=1),
    )
    assert not lenient.classify_text("shampoo").is_unknown


@pytest.mark.parametrize(
    "kwargs", [{"min_category_confidence": 1.5}, {"min_subcategory_confidence": -0.1},
               {"min_tokens": -1}],
)
def test_config_rejects_impossible_thresholds(kwargs):
    with pytest.raises(ValueError):
        ClassifierConfig(**kwargs)


# --- evidence -----------------------------------------------------------------


def test_evidence_names_matched_signals_and_weighted_terms(classifier):
    result = classifier.classify_text(
        "Nutritional Information. Ingredients: wheat. FSSAI Lic. Energy 400 kcal"
    )
    signals = [item for item in result.evidence if item.startswith("signal:")]
    terms = [item for item in result.evidence if item.startswith("term:")]
    assert any("nutritional information" in item for item in signals)
    assert any("ingredients" in item for item in signals)
    assert any("fssai" in item for item in signals)
    assert terms and all("general-food" in item for item in terms)


def test_evidence_is_capped_by_config(classification_artifact):
    capped = TfidfProductClassifier(
        classification_artifact(), version="test",
        config=ClassifierConfig(max_evidence_signals=1, max_evidence_terms=1),
    )
    result = capped.classify_text("ingredients fssai energy supplement serving")
    assert len([i for i in result.evidence if i.startswith("signal:")]) == 1
    assert len([i for i in result.evidence if i.startswith("term:")]) == 1


# --- the ProductClassifier interface ----------------------------------------


def test_classify_reads_the_full_recognised_text(classifier, tmp_path):
    ocr = OcrResult(
        blocks=(
            TextBlock("Ingredients: wheat", BoundingBox(1, 1, 10, 10), 0.9),
            TextBlock("FSSAI 12345", BoundingBox(1, 20, 10, 10), 0.8),
        )
    )
    result = classifier.classify(ocr, (), image_ref(tmp_path))
    assert result.category == taxonomy.PACKAGED_FOOD
    assert classifier.classify_text(ocr.full_text) == result


def test_empty_ocr_result_is_unknown(classifier, tmp_path):
    assert classifier.classify(OcrResult(), (), image_ref(tmp_path)).is_unknown


def test_is_not_a_placeholder(classifier):
    assert classifier.is_placeholder is False


# --- loading ------------------------------------------------------------------


def test_loads_lazily_and_once(classification_artifact):
    instance = TfidfProductClassifier(classification_artifact(), version="test")
    assert instance._model is None
    instance.warmup()
    model = instance._model
    assert model is not None
    instance.warmup()
    assert instance._model is model


def test_missing_artifact_is_engine_not_available(tmp_path):
    instance = TfidfProductClassifier(tmp_path / "absent.json", version="test")
    with pytest.raises(EngineNotAvailableError, match="artifact unavailable"):
        instance.warmup()


def test_version_mismatch_is_refused(classification_artifact):
    instance = TfidfProductClassifier(classification_artifact(), version="9.9.9")
    with pytest.raises(EngineNotAvailableError, match="version"):
        instance.classify_text("ingredients fssai energy")


def test_model_name_mismatch_is_refused(classification_artifact):
    path = classification_artifact(model_name="something-else")
    with pytest.raises(EngineNotAvailableError, match="model"):
        TfidfProductClassifier(path, version="test").warmup()


def test_build_classifier_points_at_the_shipped_artifact():
    instance = build_classifier()
    assert instance.artifact_path.name == f"product_classifier_v{instance.version}.json"
    assert instance.artifact_path.parent.name == "artifacts"
    assert instance._model is None  # nothing loaded at build time


# --- signals are explanatory only --------------------------------------------


def test_signals_never_influence_the_decision(classifier, monkeypatch):
    """Silence every signal: the category, subcategory, confidence and scores
    must be exactly what they were. Signals are evidence *about* a decision
    the model made from the text alone - they are not features, and they are
    not a keyword rule that could quietly become a compliance rule."""
    from labelextract.classification import classifier as module

    text = "Nutritional Information. Ingredients: wheat. FSSAI. Energy 400 kcal. Supplement tablets."
    with_signals = classifier.classify_text(text)
    monkeypatch.setattr(module, "matched_signals", lambda cleaned: ())
    without_signals = classifier.classify_text(text)

    decision = lambda r: (  # noqa: E731
        r.category, r.subcategory, r.confidence, r.subcategory_confidence,
        r.category_scores, r.subcategory_scores,
    )
    assert decision(with_signals) == decision(without_signals)
    assert any(item.startswith("signal:") for item in with_signals.evidence)
    assert not any(item.startswith("signal:") for item in without_signals.evidence)
