"""Train the product classifier offline and export it as a JSON artifact.

    pip install -e "./ml[classify-train]"
    python -m labelextract.classification.train
    python -m labelextract.classification.train --dataset my_set.json \\
        --output artifact.json --report report.json

What it does, in order:

1. Loads and validates a dataset (`dataset.py`).
2. **Leave-one-product-out cross-validation.** For each product, fits a
   model on every other product's examples and classifies the held-out
   product's examples through the *same* `TfidfProductClassifier` code path
   the pipeline runs - thresholds, UNKNOWN and all - so the number reported
   is the number the system would produce. Splitting by product rather than
   by example is not optional: two panels of one pack share its brand, its
   address block and its licence numbers, and a split that separates them
   measures memorisation.
3. Fits the final model on every trainable example and exports it.
4. Writes a report: the cross-validated metrics, the resubstitution fit
   (labelled as such - it is not a generalisation figure), every prediction
   made, the configuration, and the measured training and inference times
   on this machine.

scikit-learn is imported inside `fit`, nowhere else, and only when training.
The exported artifact is evaluated by `model.py` with no scikit-learn at all;
the equivalence between the two is asserted by `tests/test_classification_model.py`
whenever scikit-learn is installed. Nothing here is imported by the runtime
classifier, so a deployment never pays for this module's dependencies.

Honesty rules the report follows, and that anything quoting it must too:

- The cross-validated figures are the only generalisation estimate. The
  resubstitution figures say whether the model can fit its own data and
  nothing more.
- A class represented by a single product **cannot** be predicted correctly
  when that product is held out - there is nothing to learn it from - and
  its cross-validated recall will be 0. The report says so per class rather
  than averaging it away.
- N is stated everywhere a rate is. A rate over eleven examples is a rate
  over eleven examples.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from labelextract.classification import taxonomy
from labelextract.classification.classifier import (
    NAME,
    VERSION,
    ClassifierConfig,
    TfidfProductClassifier,
    shipped_artifact_path,
)
from labelextract.classification.dataset import (
    ClassificationDataset,
    ClassificationExample,
    load_dataset,
)
from labelextract.classification.metrics import ClassificationMetrics, compute_metrics
from labelextract.classification.model import (
    ARTIFACT_FORMAT,
    FeatureConfig,
    TfidfLinearModel,
)
from labelextract.classification.preprocessing import (
    TOKENISER_VERSION,
    ngram_features,
    preprocess_text,
    word_tokens,
)


class TrainingDependencyError(RuntimeError):
    """scikit-learn is not installed. Training needs the `classify-train` extra."""


@dataclass(frozen=True)
class TrainingConfig:
    """Hyperparameters. Every value is recorded in the artifact."""

    ngram_range: tuple[int, int] = (1, 2)
    #: Drop n-grams seen in fewer documents than this. Two is the floor at
    #: which a feature is more than one document's noise.
    min_df: int = 2
    sublinear_tf: bool = False
    #: Inverse regularisation strength, scikit-learn's `C`.
    C: float = 1.0
    #: `balanced` re-weights classes by inverse frequency, which matters when
    #: one product category outnumbers the others seven to one.
    class_weight: str | None = "balanced"
    max_iter: int = 1000
    random_state: int = 0
    #: Examples with fewer word tokens than this are excluded from *training*
    #: (a blank front panel teaches nothing) but still scored in evaluation,
    #: where the classifier is expected to abstain on them.
    min_train_tokens: int = 3

    def as_dict(self) -> dict[str, Any]:
        return {
            "ngram_range": list(self.ngram_range),
            "min_df": self.min_df,
            "sublinear_tf": self.sublinear_tf,
            "C": self.C,
            "class_weight": self.class_weight,
            "max_iter": self.max_iter,
            "random_state": self.random_state,
            "solver": "lbfgs",
            "min_train_tokens": self.min_train_tokens,
        }

    @property
    def features(self) -> FeatureConfig:
        return FeatureConfig(
            ngram_range=self.ngram_range,
            sublinear_tf=self.sublinear_tf,
            norm="l2",
            smooth_idf=True,
            min_df=self.min_df,
        )


def trainable(examples: Sequence[ClassificationExample], config: TrainingConfig) -> list[ClassificationExample]:
    """The examples with enough text to learn from."""
    return [
        example for example in examples
        if len(word_tokens(preprocess_text(example.text))) >= config.min_train_tokens
    ]


# --- fitting ----------------------------------------------------------------


def fit(
    examples: Sequence[ClassificationExample],
    config: TrainingConfig,
    *,
    model_version: str = VERSION,
    trained_on: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fit TF-IDF + logistic regression and return the artifact as a dict.

    Raises:
        TrainingDependencyError: scikit-learn is not importable.
        ValueError: fewer than two classes are present in `examples`.
    """
    try:
        import sklearn
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise TrainingDependencyError(
            "Training needs scikit-learn. Install the optional extra: "
            'pip install -e "./ml[classify-train]"'
        ) from exc

    if not examples:
        raise ValueError("no examples to train on")
    labels = sorted({example.subcategory for example in examples})
    if len(labels) < 2:
        raise ValueError(f"training needs at least two classes, got {labels}")

    texts = [preprocess_text(example.text) for example in examples]
    targets = [example.subcategory for example in examples]

    vectoriser = TfidfVectorizer(
        analyzer=lambda text: ngram_features(text, config.ngram_range),
        min_df=config.min_df,
        sublinear_tf=config.sublinear_tf,
        norm="l2",
        use_idf=True,
        smooth_idf=True,
        lowercase=False,
    )
    matrix = vectoriser.fit_transform(texts)
    classifier = LogisticRegression(
        C=config.C,
        class_weight=config.class_weight,
        max_iter=config.max_iter,
        solver="lbfgs",
        random_state=config.random_state,
    )
    classifier.fit(matrix, targets)

    vocabulary = [""] * len(vectoriser.vocabulary_)
    for term, column in vectoriser.vocabulary_.items():
        vocabulary[int(column)] = term
    classes = [str(name) for name in classifier.classes_]
    link = "sigmoid" if len(classes) == 2 else "softmax"

    return {
        "artifact_format": ARTIFACT_FORMAT,
        "model_name": NAME,
        "model_version": model_version,
        "taxonomy_version": taxonomy.TAXONOMY_VERSION,
        "tokeniser_version": TOKENISER_VERSION,
        "features": config.features.as_dict(),
        "vocabulary": vocabulary,
        "idf": [float(value) for value in vectoriser.idf_],
        "classes": classes,
        "coef": [[float(value) for value in row] for row in classifier.coef_],
        "intercept": [float(value) for value in classifier.intercept_],
        "link": link,
        "trained_on": dict(trained_on or {}),
        "training": {
            **config.as_dict(),
            "n_examples": len(examples),
            "n_features": len(vocabulary),
            "library": f"scikit-learn {sklearn.__version__}",
            "python": platform.python_version(),
        },
    }


def classifier_from_artifact(
    artifact: dict[str, Any], config: ClassifierConfig
) -> TfidfProductClassifier:
    """A ready classifier over an in-memory artifact, for cross-validation."""
    model = TfidfLinearModel(artifact)
    instance = TfidfProductClassifier(version=model.model_version, config=config)
    instance._model = model  # noqa: SLF001 - the trainer is this class's peer
    return instance


# --- evaluation -------------------------------------------------------------


@dataclass(frozen=True)
class Prediction:
    example_id: str
    product_id: str
    text_source: str
    true_category: str
    true_subcategory: str
    category: str
    subcategory: str | None
    confidence: float | None
    subcategory_confidence: float | None
    category_scores: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "example_id": self.example_id,
            "product_id": self.product_id,
            "text_source": self.text_source,
            "true_category": self.true_category,
            "true_subcategory": self.true_subcategory,
            "predicted_category": self.category,
            "predicted_subcategory": self.subcategory,
            "confidence": self.confidence,
            "subcategory_confidence": self.subcategory_confidence,
            "category_scores": self.category_scores,
            "category_correct": self.category == self.true_category,
            "subcategory_correct": self.subcategory == self.true_subcategory,
        }


def predict_all(
    classifier: TfidfProductClassifier, examples: Sequence[ClassificationExample]
) -> list[Prediction]:
    predictions = []
    for example in examples:
        result = classifier.classify_text(example.text)
        predictions.append(
            Prediction(
                example_id=example.example_id,
                product_id=example.product_id,
                text_source=example.text_source,
                true_category=example.category,
                true_subcategory=example.subcategory,
                category=result.category,
                subcategory=result.subcategory,
                confidence=result.confidence,
                subcategory_confidence=result.subcategory_confidence,
                category_scores=dict(result.category_scores),
            )
        )
    return predictions


def score(predictions: Sequence[Prediction]) -> dict[str, ClassificationMetrics]:
    """Metrics at both levels. Subcategory abstention includes 'category only'."""
    category = compute_metrics(
        [item.true_category for item in predictions],
        [item.category for item in predictions],
        labels=list(taxonomy.CATEGORIES),
    )
    subcategory = compute_metrics(
        [item.true_subcategory for item in predictions],
        [item.subcategory for item in predictions],
        labels=sorted({item.true_subcategory for item in predictions}),
    )
    return {"category": category, "subcategory": subcategory}


def cross_validate(
    dataset: ClassificationDataset,
    config: TrainingConfig,
    classifier_config: ClassifierConfig,
) -> tuple[list[Prediction], dict[str, Any]]:
    """Leave-one-product-out. Returns every held-out prediction and fold notes."""
    groups = dataset.by_product()
    predictions: list[Prediction] = []
    folds: list[dict[str, Any]] = []
    for held_out, held_examples in groups.items():
        training = trainable(
            [
                example for product, examples in groups.items()
                if product != held_out for example in examples
            ],
            config,
        )
        classes_in_training = sorted({example.subcategory for example in training})
        held_classes = sorted({example.subcategory for example in held_examples})
        unlearnable = [name for name in held_classes if name not in classes_in_training]
        artifact = fit(training, config, model_version="cv")
        classifier = classifier_from_artifact(artifact, classifier_config)
        fold_predictions = predict_all(classifier, held_examples)
        predictions.extend(fold_predictions)
        folds.append(
            {
                "held_out_product": held_out,
                "n_train": len(training),
                "n_held_out": len(held_examples),
                "classes_in_training": classes_in_training,
                "held_out_classes_absent_from_training": unlearnable,
            }
        )
    return predictions, {"method": "leave-one-product-out", "folds": folds}


# --- timing -----------------------------------------------------------------


def measure_inference(
    classifier: TfidfProductClassifier,
    examples: Sequence[ClassificationExample],
    *,
    repeats: int = 50,
) -> dict[str, Any]:
    """Wall-clock per-example latency of preprocessing and classification.

    Measured here, on this machine, over the dataset's own texts, and
    reported with the machine so the number travels with its context.
    """
    texts = [example.text for example in examples if example.text.strip()]
    if not texts:
        return {"n_texts": 0}
    classifier.warmup()
    preprocessing_ms: list[float] = []
    classify_ms: list[float] = []
    for _ in range(repeats):
        for text in texts:
            started = time.perf_counter()
            cleaned = preprocess_text(text)
            word_tokens(cleaned)
            preprocessing_ms.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            classifier.classify_text(text)
            classify_ms.append((time.perf_counter() - started) * 1000)
    return {
        "n_texts": len(texts),
        "repeats": repeats,
        "preprocessing_ms": _summary(preprocessing_ms),
        "classify_ms_including_preprocessing": _summary(classify_ms),
        "machine": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
        },
    }


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "mean": round(statistics.fmean(ordered), 4),
        "median": round(statistics.median(ordered), 4),
        "p95": round(ordered[int(0.95 * (len(ordered) - 1))], 4),
        "max": round(ordered[-1], 4),
    }


# --- the command --------------------------------------------------------------


def run(
    dataset_path: Path | None,
    output_path: Path,
    report_path: Path | None,
    *,
    config: TrainingConfig | None = None,
    classifier_config: ClassifierConfig | None = None,
    model_version: str = VERSION,
    skip_cv: bool = False,
    log=print,
) -> dict[str, Any]:
    config = config or TrainingConfig()
    classifier_config = classifier_config or ClassifierConfig()

    dataset = load_dataset(dataset_path)
    log(f"dataset {dataset.dataset_version}: {len(dataset.examples)} examples, "
        f"{len(dataset.product_ids)} products, sha256 {dataset.sha256[:12]}...")
    for name, counts in dataset.label_counts().items():
        log(f"  {name:28s} {counts['examples']:3d} examples  {counts['products']:2d} products")

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": {
            "dataset_version": dataset.dataset_version,
            "sha256": dataset.sha256,
            "n_examples": len(dataset.examples),
            "n_products": len(dataset.product_ids),
            "label_counts": dataset.label_counts(),
            "unverified_labels": sum(1 for e in dataset.examples if not e.is_verified),
        },
        "training_config": config.as_dict(),
        "classifier_config": {
            "min_category_confidence": classifier_config.min_category_confidence,
            "min_subcategory_confidence": classifier_config.min_subcategory_confidence,
            "min_tokens": classifier_config.min_tokens,
        },
    }

    if not skip_cv:
        started = time.perf_counter()
        cv_predictions, fold_notes = cross_validate(dataset, config, classifier_config)
        cv_metrics = score(cv_predictions)
        report["cross_validation"] = {
            **fold_notes,
            "seconds": round(time.perf_counter() - started, 3),
            "metrics": {level: item.as_dict() for level, item in cv_metrics.items()},
            "predictions": [item.as_dict() for item in cv_predictions],
        }
        _log_metrics(log, "leave-one-product-out", cv_metrics)

    training = trainable(dataset.examples, config)
    excluded = [e.example_id for e in dataset.examples if e not in training]
    started = time.perf_counter()
    artifact = fit(
        training,
        config,
        model_version=model_version,
        trained_on={
            "dataset_version": dataset.dataset_version,
            "dataset_sha256": dataset.sha256,
            "n_examples": len(training),
            "n_products": len({e.product_id for e in training}),
            "excluded_examples": excluded,
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    fit_seconds = time.perf_counter() - started

    final = classifier_from_artifact(artifact, classifier_config)
    resubstitution = predict_all(final, dataset.examples)
    resubstitution_metrics = score(resubstitution)
    _log_metrics(log, "resubstitution (training-set fit, NOT generalisation)", resubstitution_metrics)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    log(f"artifact written: {output_path} ({output_path.stat().st_size:,} bytes, "
        f"{len(artifact['vocabulary'])} features, classes {artifact['classes']})")

    report["artifact"] = {
        "path": str(output_path),
        "bytes": output_path.stat().st_size,
        "model_version": model_version,
        "classes": artifact["classes"],
        "n_features": len(artifact["vocabulary"]),
        "fit_seconds": round(fit_seconds, 3),
        "excluded_examples": excluded,
    }
    report["resubstitution"] = {
        "note": "Resubstitution, NOT generalisation: the final model scored on "
                "the data it was trained on. Says whether it can fit the seed "
                "set; says nothing about labels it has not seen.",
        "metrics": {level: item.as_dict() for level, item in resubstitution_metrics.items()},
        "predictions": [item.as_dict() for item in resubstitution],
    }
    report["inference_latency"] = measure_inference(final, dataset.examples)

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        log(f"report written: {report_path}")
    return report


def _log_metrics(log, title: str, metrics: dict[str, ClassificationMetrics]) -> None:
    for level, item in metrics.items():
        log(
            f"{title} [{level}]: n={item.n_total} unknown={item.n_unknown} "
            f"({item.unknown_rate:.0%}) strict_acc={item.strict_accuracy:.3f} "
            f"acc_on_predicted={item.accuracy_on_predicted:.3f} "
            f"macro_p={item.macro_precision:.3f} macro_r={item.macro_recall:.3f} "
            f"macro_f1={item.macro_f1:.3f}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m labelextract.classification.train",
        description="Train the product classifier and export a JSON artifact.",
    )
    parser.add_argument("--dataset", type=Path, default=None,
                        help="Dataset JSON. Defaults to the shipped seed set.")
    parser.add_argument("--output", type=Path, default=None,
                        help="Artifact path. Defaults to the shipped artifact "
                             "location for --model-version.")
    parser.add_argument("--report", type=Path, default=None,
                        help="Where to write the metrics report JSON. Defaults "
                             "to <output>.metrics.json.")
    parser.add_argument("--model-version", default=VERSION)
    parser.add_argument("--C", type=float, default=TrainingConfig.C)
    parser.add_argument("--min-df", type=int, default=TrainingConfig.min_df)
    parser.add_argument("--no-balanced", action="store_true",
                        help="Do not re-weight classes by inverse frequency.")
    parser.add_argument("--skip-cv", action="store_true",
                        help="Skip cross-validation (fit and export only).")
    args = parser.parse_args(argv)

    output = args.output or shipped_artifact_path(args.model_version)
    report = args.report or output.with_suffix(".metrics.json")
    config = TrainingConfig(
        C=args.C, min_df=args.min_df,
        class_weight=None if args.no_balanced else "balanced",
    )
    try:
        run(args.dataset, output, report, config=config,
            model_version=args.model_version, skip_cv=args.skip_cv)
    except TrainingDependencyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
