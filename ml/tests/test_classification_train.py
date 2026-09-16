"""The offline trainer: fit, export, cross-validate, report.

Skipped in full without scikit-learn, which is a training-only dependency
(`pip install -e "./ml[classify-train]"`). The suite must pass without it;
CI installs it in a separate step so these run there too.

The fixture dataset is built in code - three products per class, one line
of plausible label text each - so nothing here depends on the seed set's
contents or on any file outside `tmp_path`.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("sklearn")

from labelextract.classification import taxonomy  # noqa: E402
from labelextract.classification.classifier import ClassifierConfig  # noqa: E402
from labelextract.classification.dataset import load_dataset  # noqa: E402
from labelextract.classification.model import TfidfLinearModel  # noqa: E402
from labelextract.classification.train import (  # noqa: E402
    TrainingConfig,
    classifier_from_artifact,
    cross_validate,
    fit,
    main,
    run,
    trainable,
)

TEXTS = {
    "general-food": [
        "ingredients wheat flour sugar salt fssai lic no 12345 net weight 500 g",
        "nutritional information energy 450 kcal protein 8 g carbohydrate 70 g fssai",
        "ingredients rice edible oil spices best before 6 months net qty 200 g",
    ],
    "cleaning-product": [
        "floor cleaner disinfectant keep out of reach of children spray 500 ml",
        "detergent powder for household use keep away from heat net qty 1 kg",
        "extremely flammable aerosol pressurised container do not pierce spray",
    ],
    "cosmetics-and-toiletries": [
        "shampoo for dry hair for external use only 200 ml",
        "bathing bar soap moisturising cream 125 g dermatologically tested",
        "toothpaste with fluoride 100 g for external use only skin",
    ],
}


@pytest.fixture
def dataset_path(tmp_path):
    examples = []
    for label, items in TEXTS.items():
        for index, text in enumerate(items):
            examples.append(
                {
                    "example_id": f"{label}-{index}/ocr",
                    "product_id": f"{label}-{index}",
                    "category": taxonomy.category_for(label),
                    "subcategory": label,
                    "text": text,
                    "text_source": "ocr",
                    "labelled_by": "test",
                    "label_verified_by": "test",
                    "ocr_engine": "stub",
                    "ocr_engine_version": "0",
                    "source_dataset": None,
                    "source_sample_id": None,
                    "image_sha256": None,
                    "note": "",
                }
            )
    # One blank front panel, to be excluded from training and abstained on.
    examples.append({**examples[0], "example_id": "blank/ocr", "product_id": "general-food-0", "text": ""})
    path = tmp_path / "set.json"
    path.write_text(
        json.dumps(
            {
                "dataset_version": "fixture-v1",
                "created_on": "2026-01-01",
                "description": "in-code fixture",
                "taxonomy_version": taxonomy.TAXONOMY_VERSION,
                "examples": examples,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_fit_exports_a_valid_artifact(dataset_path):
    dataset = load_dataset(dataset_path)
    artifact = fit(trainable(dataset.examples, TrainingConfig(min_df=1)), TrainingConfig(min_df=1), model_version="t")
    model = TfidfLinearModel(artifact)  # validates
    assert model.classes == ("cleaning-product", "cosmetics-and-toiletries", "general-food")
    assert model.link == "softmax"
    assert len(model.vocabulary) == len(model.idf) == len(model.coef[0])
    assert artifact["training"]["library"].startswith("scikit-learn")
    assert artifact["training"]["n_examples"] == 9


def test_fit_is_deterministic(dataset_path):
    examples = load_dataset(dataset_path).examples
    config = TrainingConfig(min_df=1)
    first = fit(examples, config, model_version="t")
    second = fit(examples, config, model_version="t")
    assert first["coef"] == second["coef"]
    assert first["vocabulary"] == second["vocabulary"]


def test_two_classes_export_a_sigmoid_link(dataset_path):
    examples = [e for e in load_dataset(dataset_path).examples if e.subcategory != "general-food"]
    artifact = fit(examples, TrainingConfig(min_df=1), model_version="t")
    assert artifact["link"] == "sigmoid"
    assert len(artifact["coef"]) == 1
    model = TfidfLinearModel(artifact)
    proba = model.predict_proba("shampoo for dry hair")
    assert proba["cosmetics-and-toiletries"] > proba["cleaning-product"]


def test_fit_refuses_a_single_class(dataset_path):
    examples = [e for e in load_dataset(dataset_path).examples if e.subcategory == "general-food"]
    with pytest.raises(ValueError, match="at least two classes"):
        fit(examples, TrainingConfig(min_df=1))


def test_trainable_excludes_blank_examples(dataset_path):
    dataset = load_dataset(dataset_path)
    kept = trainable(dataset.examples, TrainingConfig())
    assert len(kept) == len(dataset.examples) - 1
    assert all(e.text for e in kept)


def test_the_fitted_model_classifies_its_own_examples(dataset_path):
    dataset = load_dataset(dataset_path)
    config = TrainingConfig(min_df=1)
    artifact = fit(trainable(dataset.examples, config), config, model_version="t")
    classifier = classifier_from_artifact(artifact, ClassifierConfig(min_category_confidence=0.5))
    for example in dataset.examples:
        result = classifier.classify_text(example.text)
        if not example.text:
            assert result.is_unknown
        else:
            assert result.category == example.category, example.example_id


def test_cross_validation_splits_by_product(dataset_path):
    dataset = load_dataset(dataset_path)
    predictions, notes = cross_validate(dataset, TrainingConfig(min_df=1), ClassifierConfig())
    assert notes["method"] == "leave-one-product-out"
    assert len(notes["folds"]) == len(dataset.product_ids)
    assert len(predictions) == len(dataset.examples)
    for fold in notes["folds"]:
        assert fold["n_train"] < len(dataset.examples)
        assert fold["held_out_classes_absent_from_training"] == []
    held_out_products = {p.product_id for p in predictions}
    assert held_out_products == set(dataset.product_ids)


def test_run_writes_the_artifact_and_an_honest_report(dataset_path, tmp_path):
    output = tmp_path / "out" / "artifact.json"
    report_path = tmp_path / "out" / "report.json"
    report = run(
        dataset_path, output, report_path,
        config=TrainingConfig(min_df=1), model_version="t", log=lambda *_: None,
    )
    assert output.exists() and report_path.exists()
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["dataset"]["n_products"] == 9
    assert written["dataset"]["unverified_labels"] == 0
    assert "cross_validation" in written and "resubstitution" in written
    assert "NOT generalisation" in written["resubstitution"]["note"]
    for level in ("category", "subcategory"):
        metrics = written["cross_validation"]["metrics"][level]
        assert set(metrics) >= {"strict_accuracy", "accuracy_on_predicted", "unknown_rate",
                                "macro_precision", "macro_recall", "macro_f1",
                                "per_class", "confusion"}
    assert written["inference_latency"]["n_texts"] == 9
    assert report["artifact"]["classes"] == ["cleaning-product", "cosmetics-and-toiletries", "general-food"]
    model = TfidfLinearModel(json.loads(output.read_text(encoding="utf-8")))
    assert model.trained_on["dataset_version"] == "fixture-v1"
    assert model.trained_on["dataset_sha256"] == load_dataset(dataset_path).sha256
    assert model.trained_on["excluded_examples"] == ["blank/ocr"]


def test_the_command_line_entry_point(dataset_path, tmp_path, capsys):
    output = tmp_path / "cli.json"
    code = main([
        "--dataset", str(dataset_path), "--output", str(output),
        "--model-version", "t", "--min-df", "1", "--skip-cv",
    ])
    assert code == 0
    assert output.exists()
    assert output.with_suffix(".metrics.json").exists()
    assert "artifact written" in capsys.readouterr().out
