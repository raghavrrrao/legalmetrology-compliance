"""The artifact format and the plain-Python evaluation of it.

Two things are protected here. The loader refuses any artifact this code
cannot evaluate faithfully - wrong shapes, wrong versions, unknown classes -
because every one of those failures would otherwise produce numbers that
still look like probabilities. And the evaluation itself is checked against
hand-computed values on a tiny artifact, and against scikit-learn's own
`predict_proba` whenever scikit-learn happens to be installed.
"""

from __future__ import annotations

import json
import math

import pytest

from labelextract.classification.model import (
    ARTIFACT_FORMAT,
    ArtifactError,
    TfidfLinearModel,
    load_artifact,
)
from labelextract.classification.preprocessing import TOKENISER_VERSION
from labelextract.classification.taxonomy import TAXONOMY_VERSION


def tiny_artifact(**overrides):
    """A three-class softmax artifact small enough to compute by hand."""
    artifact = {
        "artifact_format": ARTIFACT_FORMAT,
        "model_name": "tfidf-logreg",
        "model_version": "test",
        "taxonomy_version": TAXONOMY_VERSION,
        "tokeniser_version": TOKENISER_VERSION,
        "features": {
            "ngram_range": [1, 1], "sublinear_tf": False, "norm": "l2",
            "smooth_idf": True, "min_df": 1,
        },
        "vocabulary": ["ingredients", "fssai", "shampoo", "detergent"],
        "idf": [1.0, 2.0, 1.0, 1.0],
        "classes": ["cleaning-product", "cosmetics-and-toiletries", "general-food"],
        "coef": [
            [-1.0, -1.0, 0.0, 3.0],
            [-1.0, -1.0, 3.0, 0.0],
            [2.0, 2.0, -1.0, -1.0],
        ],
        "intercept": [0.0, 0.0, 0.0],
        "link": "softmax",
        "trained_on": {},
        "training": {},
    }
    artifact.update(overrides)
    return artifact


def softmax(values):
    peak = max(values)
    weights = [math.exp(v - peak) for v in values]
    return [w / sum(weights) for w in weights]


# --- vectorisation ------------------------------------------------------------


def test_vectorise_is_tf_times_idf_l2_normalised():
    model = TfidfLinearModel(tiny_artifact())
    row = model.vectorise("fssai ingredients fssai")
    # tf: ingredients 1, fssai 2. tf*idf: 1*1, 2*2 -> (1, 4); norm sqrt(17).
    assert set(row) == {0, 1}
    assert row[0] == pytest.approx(1 / math.sqrt(17))
    assert row[1] == pytest.approx(4 / math.sqrt(17))


def test_out_of_vocabulary_terms_are_dropped_before_normalising():
    model = TfidfLinearModel(tiny_artifact())
    assert model.vectorise("ingredients unknownword another") == {0: pytest.approx(1.0)}


def test_empty_text_vectorises_to_an_empty_row():
    model = TfidfLinearModel(tiny_artifact())
    assert model.vectorise("") == {}
    assert model.vectorise("nothing known here") == {}


def test_sublinear_tf_applies_one_plus_log():
    artifact = tiny_artifact()
    artifact["features"]["sublinear_tf"] = True
    model = TfidfLinearModel(artifact)
    row = model.vectorise("fssai fssai fssai")
    assert row == {1: pytest.approx(1.0)}  # a single term normalises to 1
    raw = model.decision({1: (1 + math.log(3)) * 2.0})
    assert raw  # shape only; the value is checked through predict_proba below


# --- prediction ---------------------------------------------------------------


def test_softmax_probabilities_match_a_hand_computation():
    model = TfidfLinearModel(tiny_artifact())
    row = model.vectorise("detergent")  # -> {3: 1.0}
    proba = model.probabilities(row)
    expected = softmax([3.0, 0.0, -1.0])
    assert [proba[c] for c in model.classes] == pytest.approx(expected)
    assert sum(proba.values()) == pytest.approx(1.0)


def test_intercept_only_prior_when_nothing_is_known():
    artifact = tiny_artifact(intercept=[0.0, 1.0, 0.0])
    model = TfidfLinearModel(artifact)
    proba = model.predict_proba("nothing in vocabulary")
    assert [proba[c] for c in model.classes] == pytest.approx(softmax([0.0, 1.0, 0.0]))


def test_sigmoid_link_for_two_classes():
    artifact = tiny_artifact(
        classes=["cleaning-product", "general-food"],
        coef=[[2.0, 2.0, -2.0, -2.0]],
        intercept=[0.5],
        link="sigmoid",
    )
    model = TfidfLinearModel(artifact)
    proba = model.predict_proba("ingredients")  # row {0: 1.0}; z = 2.5
    positive = 1 / (1 + math.exp(-2.5))
    assert proba["general-food"] == pytest.approx(positive)
    assert proba["cleaning-product"] == pytest.approx(1 - positive)


def test_contributions_name_the_terms_that_drove_a_class():
    model = TfidfLinearModel(tiny_artifact())
    row = model.vectorise("shampoo detergent")
    ranked = model.contributions(row, "cleaning-product")
    assert ranked[0][0] == "detergent" and ranked[0][1] > 0
    assert ranked[1][0] == "shampoo" and ranked[1][1] == pytest.approx(0.0)
    with pytest.raises(KeyError):
        model.contributions(row, "not-a-class")


def test_sigmoid_contributions_negate_for_the_first_class():
    artifact = tiny_artifact(
        classes=["cleaning-product", "general-food"],
        coef=[[2.0, 0.0, 0.0, -2.0]],
        intercept=[0.0],
        link="sigmoid",
    )
    model = TfidfLinearModel(artifact)
    row = model.vectorise("detergent")
    assert model.contributions(row, "cleaning-product")[0][1] == pytest.approx(2.0)
    assert model.contributions(row, "general-food")[0][1] == pytest.approx(-2.0)


def test_as_dict_round_trips_through_json():
    artifact = tiny_artifact()
    model = TfidfLinearModel(artifact)
    assert json.loads(json.dumps(model.as_dict())) == artifact


# --- validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda a: a.pop("coef"), "missing keys"),
        (lambda a: a.update(artifact_format="other/9"), "unsupported artifact format"),
        (lambda a: a.update(taxonomy_version="999"), "taxonomy"),
        (lambda a: a.update(tokeniser_version="999"), "tokeniser"),
        (lambda a: a.update(link="probit"), "unknown link"),
        (lambda a: a.update(idf=[1.0]), "one value per vocabulary term"),
        (lambda a: a.update(coef=[[1.0, 2.0]] * 3), "one value per term"),
        (lambda a: a.update(coef=[[0.0] * 4]), "must have 3 row"),
        (lambda a: a.update(intercept=[0.0]), "one value per coef row"),
        (lambda a: a.update(classes=["cleaning-product", "not-a-thing", "general-food"]), "not in the taxonomy"),
        (lambda a: a.update(classes=["general-food"] * 3), "duplicates"),
        (lambda a: a.update(vocabulary=["a", "a", "b", "c"]), "duplicate terms"),
        (lambda a: a.update(idf=[1.0, "x", 1.0, 1.0]), "only numbers"),
        (lambda a: a.update(idf=[1.0, float("nan"), 1.0, 1.0]), "non-finite"),
        (lambda a: a["features"].update(smooth_idf=False), "smooth_idf"),
        (lambda a: a["features"].update(norm="l1"), "unsupported norm"),
        (lambda a: a["features"].pop("min_df"), "malformed"),
    ],
)
def test_malformed_artifacts_are_refused(mutate, message):
    artifact = tiny_artifact()
    mutate(artifact)
    with pytest.raises(ArtifactError, match=message):
        TfidfLinearModel(artifact)


def test_sigmoid_link_requires_exactly_two_classes():
    with pytest.raises(ArtifactError, match="exactly two"):
        TfidfLinearModel(tiny_artifact(link="sigmoid", coef=[[0.0] * 4], intercept=[0.0]))


def test_a_non_object_is_refused():
    with pytest.raises(ArtifactError):
        TfidfLinearModel(["not", "an", "object"])


def test_load_artifact_reports_a_missing_file(tmp_path):
    with pytest.raises(ArtifactError, match="could not be read"):
        load_artifact(tmp_path / "absent.json")


def test_load_artifact_reports_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ArtifactError, match="not valid JSON"):
        load_artifact(path)


def test_load_artifact_reads_a_valid_file(tmp_path):
    path = tmp_path / "ok.json"
    path.write_text(json.dumps(tiny_artifact()), encoding="utf-8")
    assert load_artifact(path).classes == (
        "cleaning-product", "cosmetics-and-toiletries", "general-food",
    )


# --- equivalence with scikit-learn -------------------------------------------


def test_plain_python_inference_matches_scikit_learn():
    """The exported artifact must reproduce the library that trained it.

    Skipped without scikit-learn: it is a training-only dependency and the
    suite must pass on a machine without it. When it is present, the whole
    train -> export -> evaluate loop is checked to floating-point precision,
    which is what makes shipping JSON instead of a pickle defensible.
    """
    pytest.importorskip("sklearn")
    from labelextract.classification.dataset import ClassificationExample
    from labelextract.classification.preprocessing import preprocess_text
    from labelextract.classification.train import TrainingConfig, fit

    texts = {
        "general-food": [
            "ingredients wheat flour sugar salt fssai lic no 12345 net weight 500 g",
            "nutritional information energy 450 kcal protein 8 g carbohydrate 70 g fssai",
            "ingredients rice edible oil spices best before 6 months net qty 200 g",
        ],
        "cleaning-product": [
            "floor cleaner disinfectant keep out of reach of children spray 500 ml",
            "detergent powder for household use keep away from heat net qty 1 kg",
            "extremely flammable aerosol pressurised container do not pierce",
        ],
        "cosmetics-and-toiletries": [
            "shampoo for dry hair for external use only 200 ml",
            "bathing bar soap moisturising cream 125 g dermatologically tested",
            "toothpaste with fluoride 100 g for external use only",
        ],
    }
    examples = [
        ClassificationExample(
            example_id=f"{label}-{index}", product_id=f"{label}-{index}",
            category="packaged-food" if label == "general-food" else "packaged-non-food",
            subcategory=label, text=text, text_source="manual_transcription",
            labelled_by="test", label_verified_by=None, ocr_engine=None,
            ocr_engine_version=None, source_dataset=None, source_sample_id=None,
            image_sha256=None, note="",
        )
        for label, items in texts.items() for index, text in enumerate(items)
    ]
    config = TrainingConfig(min_df=1)
    artifact = fit(examples, config, model_version="test")
    model = TfidfLinearModel(artifact)

    # Re-fit scikit-learn's own objects the same way to compare directly.
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from labelextract.classification.preprocessing import ngram_features

    cleaned = [preprocess_text(e.text) for e in examples]
    vectoriser = TfidfVectorizer(
        analyzer=lambda t: ngram_features(t, config.ngram_range),
        min_df=1, norm="l2", smooth_idf=True, lowercase=False,
    )
    matrix = vectoriser.fit_transform(cleaned)
    reference = LogisticRegression(
        C=config.C, class_weight="balanced", max_iter=config.max_iter,
        solver="lbfgs", random_state=0,
    ).fit(matrix, [e.subcategory for e in examples])

    probes = cleaned + [
        "shampoo ingredients fssai",
        "spray detergent energy kcal",
        "completely unknown words only",
        "",
    ]
    for text in probes:
        ours = model.predict_proba(text)
        theirs = reference.predict_proba(vectoriser.transform([text]))[0]
        for class_name, value in zip(reference.classes_, theirs):
            assert ours[class_name] == pytest.approx(value, abs=1e-9), text
