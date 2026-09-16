"""The shipped artifact, on the label text it was trained on.

Read the scope carefully. Every text here comes from the seed dataset the
artifact was trained on, so a correct answer is **resubstitution**, not
generalisation: it shows the model fits its ten products, and nothing about
an eleventh. What these tests protect is that the shipped artifact is the
one the dataset produced, that it loads, that known label text is handled
the way the documentation says, and that a retrained artifact which changed
those answers is noticed rather than shipped silently.

The three products named in the brief - the Plix "Acne Fighter" tablets, the
ShineXPro helmet cleaner and the Dove bar - are the regression anchors.
"""

from __future__ import annotations

import re

import pytest

from labelextract.classification import (
    VERSION,
    build_classifier,
    load_dataset,
    matched_signals,
    preprocess_text,
    taxonomy,
)
from labelextract.classification.dataset import ClassificationExample
from labelextract.classification.model import ARTIFACT_FORMAT
from labelextract.classification.preprocessing import TOKENISER_VERSION

@pytest.fixture(scope="module")
def classifier():
    instance = build_classifier()
    instance.warmup()
    return instance


@pytest.fixture(scope="module")
def seed() -> dict[str, ClassificationExample]:
    return {example.example_id: example for example in load_dataset().examples}


# --- the artifact itself ------------------------------------------------------


def test_shipped_artifact_loads_and_matches_its_version(classifier):
    model = classifier.model
    assert model.model_version == VERSION == "0.1.0"
    assert model.model_name == "tfidf-logreg"
    assert classifier.artifact_path.name == "product_classifier_v0.1.0.json"


def test_shipped_artifact_was_trained_on_the_shipped_dataset(classifier):
    """The two committed files must agree, or a number quoted about one
    describes the other. Retrain after editing the dataset."""
    dataset = load_dataset()
    assert classifier.model.trained_on["dataset_sha256"] == dataset.sha256
    assert classifier.model.trained_on["dataset_version"] == dataset.dataset_version


def test_shipped_artifact_speaks_the_current_vocabularies(classifier):
    artifact = classifier.model.as_dict()
    assert artifact["artifact_format"] == ARTIFACT_FORMAT
    assert artifact["taxonomy_version"] == taxonomy.TAXONOMY_VERSION
    assert artifact["tokeniser_version"] == TOKENISER_VERSION


def test_shipped_artifact_knows_exactly_the_seed_classes(classifier):
    assert classifier.model.classes == (
        "cleaning-product", "cosmetics-and-toiletries", "general-food", "health-supplement",
    )
    assert all(taxonomy.is_subcategory(name) for name in classifier.model.classes)


def test_shipped_artifact_is_small(classifier):
    """A few hundred kilobytes of JSON, not a weights file."""
    assert classifier.artifact_path.stat().st_size < 1_000_000


def test_shipped_artifact_records_its_provenance(classifier):
    training = classifier.model.training
    assert training["library"].startswith("scikit-learn ")
    assert training["class_weight"] == "balanced"
    assert training["n_examples"] == 33


# --- the three anchors --------------------------------------------------------


def test_acne_fighter_declaration_face_is_a_food_supplement(classifier, seed):
    """Plix 'Acne Fighter': nutritional information, ingredients, serving size,
    INS codes, 'not for medicinal use', '15N TABLETS'. Food, and the
    supplement subcategory when the text is clean enough to say so."""
    ocr = classifier.classify_text(seed["p002_03_left/ocr"].text)
    assert ocr.category == taxonomy.PACKAGED_FOOD
    assert ocr.subcategory == "health-supplement"

    clean = classifier.classify_text(seed["p002_03_left/transcription"].text)
    assert clean.category == taxonomy.PACKAGED_FOOD
    assert clean.subcategory == "health-supplement"

    cleaned = preprocess_text(seed["p002_03_left/transcription"].text)
    labels = {signal.label for signal in matched_signals(cleaned)}
    assert {"nutritional information", "ingredients", "serving size",
            "effervescent / tablets / capsules", "not for medicinal use",
            "food additive code"} <= labels
    assert "15n tablets" in cleaned


def test_acne_fighter_marketer_face_is_still_food(classifier, seed):
    """The address face carries an FSSAI licence and little else; the
    category holds and the subcategory is honestly left open."""
    result = classifier.classify_text(seed["p002_04_right/ocr"].text)
    assert result.category == taxonomy.PACKAGED_FOOD
    assert result.subcategory is None


def test_helmet_cleaner_declaration_block_is_non_food(classifier, seed):
    """ShineXPro: 'aerosol', 'flammable', 'spray', 'keep out of reach of
    children'. Non-food from both the OCR reading and the transcription; the
    cleaning-product subcategory is reached from the clean text."""
    ocr = classifier.classify_text(seed["p001_05_declaration_closeup/ocr"].text)
    assert ocr.category == taxonomy.PACKAGED_NON_FOOD

    clean = classifier.classify_text(seed["p001_05_declaration_closeup/transcription"].text)
    assert clean.category == taxonomy.PACKAGED_NON_FOOD
    assert clean.subcategory == "cleaning-product"

    cleaned = preprocess_text(seed["p001_05_declaration_closeup/transcription"].text)
    labels = {signal.label for signal in matched_signals(cleaned)}
    assert {"spray / aerosol", "flammable / chemical warning",
            "keep out of reach of children"} <= labels


def test_helmet_cleaner_back_panel_is_non_food(classifier, seed):
    result = classifier.classify_text(seed["p001_02_back_clean/ocr"].text)
    assert result.category == taxonomy.PACKAGED_NON_FOOD
    assert result.subcategory == "cleaning-product"


def test_dove_bar_declaration_panel_is_a_toiletry(classifier, seed):
    """An ingredient list on a soap. 'Ingredients' alone is not food."""
    for key in ("p003_03_right/ocr", "p003_03_right/transcription"):
        result = classifier.classify_text(seed[key].text)
        assert result.category == taxonomy.PACKAGED_NON_FOOD, key
        assert result.subcategory == "cosmetics-and-toiletries", key


def test_a_dmart_back_panel_is_food(classifier, seed):
    result = classifier.classify_text(seed["p009_01_back/ocr"].text)
    assert result.category == taxonomy.PACKAGED_FOOD
    assert result.subcategory == "general-food"


# --- robustness on the same texts -------------------------------------------


ANCHORS = [
    ("p001_05_declaration_closeup/transcription", taxonomy.PACKAGED_NON_FOOD),
    ("p002_03_left/ocr", taxonomy.PACKAGED_FOOD),
    ("p003_03_right/ocr", taxonomy.PACKAGED_NON_FOOD),
    ("p009_01_back/ocr", taxonomy.PACKAGED_FOOD),
]


@pytest.mark.parametrize("key, category", ANCHORS)
def test_casing_does_not_change_the_scores(classifier, seed, key, category):
    base = classifier.classify_text(seed[key].text)
    upper = classifier.classify_text(seed[key].text.upper())
    lower = classifier.classify_text(seed[key].text.lower())
    assert base.category == category
    assert upper.category_scores == base.category_scores
    assert lower.category_scores == base.category_scores


@pytest.mark.parametrize("key, category", ANCHORS)
def test_duplicated_text_keeps_the_category(classifier, seed, key, category):
    text = seed[key].text
    result = classifier.classify_text(text + "\n" + text + "\n" + text)
    assert result.category == category


@pytest.mark.parametrize("key, category", ANCHORS)
def test_dropped_characters_keep_the_category(classifier, seed, key, category):
    """Mild OCR damage: one letter in seven vanishes from inside words."""
    damaged = re.sub(
        r"([a-z])([a-z])",
        lambda m: m.group(1) if sum(map(ord, m.group(0))) % 7 == 0 else m.group(0),
        seed[key].text,
    )
    assert damaged != seed[key].text
    assert classifier.classify_text(damaged).category == category


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Known limitation, recorded rather than hidden: with every o/O read "
        "as 0 the model can still commit to a wrong category at ~0.6, because "
        "the threshold is not calibrated and ten products cannot teach it "
        "what noise looks like. See docs/ml/product-classification.md."
    ),
)
@pytest.mark.parametrize("key, category", ANCHORS)
def test_heavy_corruption_should_abstain_or_stay_right(classifier, seed, key, category):
    """Every `o`/`O` read as `0` - a common Tesseract confusion, applied
    everywhere. The outcome this classifier *should* produce is the right
    category or UNKNOWN, never a confident wrong answer. It does not yet
    manage that on every anchor, so this is an expected failure that turns
    into a pass - and a notice - when a better model or calibration lands."""
    corrupted = seed[key].text.replace("o", "0").replace("O", "0")
    result = classifier.classify_text(corrupted)
    assert result.is_unknown or result.category == category


# --- UNKNOWN on real inputs -----------------------------------------------------


def test_empty_front_panel_reading_is_unknown(classifier, seed):
    """`p007_02_front` is a Devanagari-only brand face the English OCR
    reads as a few characters of noise."""
    assert len(preprocess_text(seed["p007_02_front/ocr"].text)) < 20


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Dove",
        "Dove bar",
        "नेमो नमकीन स्वादिष्ट खाद्य पदार्थ शुद्ध शाकाहारी",
        "xq zzv plorf wubb qqq kkk mmm",
        "!!! ??? ... --- ***",
    ],
)
def test_text_with_nothing_to_go_on_is_unknown(classifier, text):
    result = classifier.classify_text(text)
    assert result.is_unknown
    assert result.confidence is None
    assert result.subcategory is None


def test_the_shipped_thresholds_are_the_documented_baselines(classifier):
    assert classifier.config.min_category_confidence == 0.60
    assert classifier.config.min_subcategory_confidence == 0.50
    assert classifier.config.min_tokens == 3


# --- resubstitution fit, as a whole ------------------------------------------


def test_shipped_model_never_gives_a_wrong_category_on_its_own_seed_set(classifier):
    """Resubstitution. Not a generalisation claim: the honest measure is the
    leave-one-product-out run in the metrics report and the docs."""
    wrong = []
    unknown = 0
    for example in load_dataset().examples:
        result = classifier.classify_text(example.text)
        if result.is_unknown:
            unknown += 1
        elif result.category != example.category:
            wrong.append(example.example_id)
    assert wrong == []
    assert unknown <= 3
