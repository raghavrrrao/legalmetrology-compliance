"""A TF-IDF + linear-model artifact, and inference over it in plain Python.

Why inference is re-implemented rather than delegated to scikit-learn
--------------------------------------------------------------------
`labelextract` installs with no dependencies, and the backend that imports it
runs in a `python:3.11-slim` container whose only ML component is a system
Tesseract binary. Loading a pickled scikit-learn pipeline at request time
would mean shipping numpy, scipy and scikit-learn (well over a hundred
megabytes of wheels) to evaluate a dot product, tying the artifact to the
exact scikit-learn version that pickled it, and executing whatever code a
pickle file contains - `pickle.load` runs arbitrary bytecode, and
`.gitignore` blocks `*.pkl` and `*.joblib` for a reason.

A TF-IDF vectoriser plus a logistic-regression classifier *is* a vocabulary,
an IDF vector, a coefficient matrix and an intercept vector. Exported to
JSON, that is a few hundred kilobytes of numbers a reviewer can open,
`git diff` can show, and a hundred lines of standard-library Python can
evaluate in well under a millisecond. So the model is **trained** with
scikit-learn (`train.py`, behind the optional `classify-train` extra) and
**run** here, and a test asserts that the two agree to floating-point
precision on the same inputs whenever scikit-learn happens to be installed.

The artifact
------------
A JSON object. Every key is required; the loader refuses anything it does
not understand rather than defaulting it.

    artifact_format     "labelextract.classification.tfidf-linear/1"
    model_name          "tfidf-logreg"
    model_version       e.g. "0.1.0"
    taxonomy_version    must equal taxonomy.TAXONOMY_VERSION
    tokeniser_version   must equal preprocessing.TOKENISER_VERSION
    features            {ngram_range, sublinear_tf, norm, smooth_idf, min_df}
    vocabulary          [term, ...]          index = feature column
    idf                 [float, ...]         one per term
    classes             [subcategory, ...]   one per row of coef
    coef                [[float, ...], ...]  (n_classes, n_terms), or (1, n_terms) when binary
    intercept           [float, ...]
    link                "softmax" | "sigmoid"
    trained_on          provenance: dataset version and SHA-256, counts, date, library versions
    training            the hyperparameters used

The `link` field records how scikit-learn turns decisions into probabilities
for this class count: a multinomial softmax for three or more classes, a
single sigmoid for two. Both are implemented below.

Nothing here knows what a category *means*. This module maps text to a
probability per class string and stops.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from labelextract.classification.preprocessing import (
    TOKENISER_VERSION,
    ngram_features,
)
from labelextract.classification.taxonomy import TAXONOMY_VERSION, is_subcategory

ARTIFACT_FORMAT = "labelextract.classification.tfidf-linear/1"

MODEL_NAME = "tfidf-logreg"


class ArtifactError(ValueError):
    """The artifact is missing, malformed, or built for a different code.

    A `ValueError` rather than a `LabelExtractError` on purpose: the
    classifier wraps it into `EngineNotAvailableError` at its boundary, but
    the trainer and the tests want the plain, specific failure.
    """


@dataclass(frozen=True)
class FeatureConfig:
    """How text becomes a vector. Recorded in the artifact; never defaulted."""

    ngram_range: tuple[int, int]
    sublinear_tf: bool
    norm: str
    smooth_idf: bool
    min_df: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "ngram_range": list(self.ngram_range),
            "sublinear_tf": self.sublinear_tf,
            "norm": self.norm,
            "smooth_idf": self.smooth_idf,
            "min_df": self.min_df,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FeatureConfig":
        try:
            low, high = data["ngram_range"]
            config = cls(
                ngram_range=(int(low), int(high)),
                sublinear_tf=bool(data["sublinear_tf"]),
                norm=str(data["norm"]),
                smooth_idf=bool(data["smooth_idf"]),
                min_df=int(data["min_df"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ArtifactError(f"features block is malformed: {exc}") from exc
        if config.norm not in ("l2", "none"):
            raise ArtifactError(f"unsupported norm {config.norm!r}")
        if not config.smooth_idf:
            # Only the smoothed IDF is implemented below. Refusing is better
            # than silently computing a different number from the trainer.
            raise ArtifactError("only smooth_idf=true artifacts are supported")
        return config


class TfidfLinearModel:
    """Evaluates one artifact. Immutable once built; safe to share.

    `predict_proba` is the whole API: cleaned text in, a probability per
    class out. `vectorise` and `contributions` are exposed for evidence and
    for tests.
    """

    def __init__(self, artifact: Mapping[str, Any]) -> None:
        self._artifact = _validated(artifact)
        self.model_name: str = self._artifact["model_name"]
        self.model_version: str = self._artifact["model_version"]
        self.features = FeatureConfig.from_dict(self._artifact["features"])
        self.vocabulary: tuple[str, ...] = tuple(self._artifact["vocabulary"])
        self._index: dict[str, int] = {
            term: column for column, term in enumerate(self.vocabulary)
        }
        self.idf: tuple[float, ...] = tuple(float(v) for v in self._artifact["idf"])
        self.classes: tuple[str, ...] = tuple(self._artifact["classes"])
        self.coef: tuple[tuple[float, ...], ...] = tuple(
            tuple(float(v) for v in row) for row in self._artifact["coef"]
        )
        self.intercept: tuple[float, ...] = tuple(
            float(v) for v in self._artifact["intercept"]
        )
        self.link: str = self._artifact["link"]
        self.trained_on: dict[str, Any] = dict(self._artifact["trained_on"])
        self.training: dict[str, Any] = dict(self._artifact["training"])

    # --- vectorisation ------------------------------------------------------

    def vectorise(self, cleaned: str) -> dict[int, float]:
        """The TF-IDF row for `cleaned`, as {column: weight}, L2-normalised.

        Mirrors `TfidfVectorizer.transform` for the recorded configuration:
        raw term counts over the n-gram analyzer, optional `1 + log(tf)`,
        multiplied by the smoothed IDF, then L2-normalised over the columns
        that exist in the vocabulary. Out-of-vocabulary n-grams are dropped
        *before* normalisation, exactly as they never become columns there.
        """
        counts = Counter(ngram_features(cleaned, self.features.ngram_range))
        row: dict[int, float] = {}
        for term, count in counts.items():
            column = self._index.get(term)
            if column is None:
                continue
            tf = 1.0 + math.log(count) if self.features.sublinear_tf else float(count)
            row[column] = tf * self.idf[column]
        if self.features.norm == "l2" and row:
            norm = math.sqrt(sum(value * value for value in row.values()))
            if norm > 0.0:
                row = {column: value / norm for column, value in row.items()}
        return row

    # --- prediction ---------------------------------------------------------

    def decision(self, row: Mapping[int, float]) -> list[float]:
        """The linear scores, one per coefficient row (before the link)."""
        scores = []
        for weights, bias in zip(self.coef, self.intercept):
            total = bias
            for column, value in row.items():
                total += weights[column] * value
            scores.append(total)
        return scores

    def predict_proba(self, cleaned: str) -> dict[str, float]:
        """Probability per class for `cleaned`, summing to 1.

        An empty or wholly out-of-vocabulary text is not an error: its row is
        all zeros and the result is the model's intercept-only prior, which
        the classifier then treats as it treats any weak evidence.
        """
        return self.probabilities(self.vectorise(cleaned))

    def probabilities(self, row: Mapping[int, float]) -> dict[str, float]:
        scores = self.decision(row)
        if self.link == "sigmoid":
            positive = _sigmoid(scores[0])
            return {self.classes[0]: 1.0 - positive, self.classes[1]: positive}
        return dict(zip(self.classes, _softmax(scores)))

    # --- evidence -----------------------------------------------------------

    def contributions(
        self, row: Mapping[int, float], class_name: str
    ) -> list[tuple[str, float]]:
        """Per-term contribution to `class_name`'s score, largest first.

        For the softmax link, the contribution of a term to a class is its
        weight times its coefficient for that class. For the sigmoid link
        the single coefficient row scores the *second* class, so the first
        class's contributions are its negation. Only terms present in the
        text appear.
        """
        try:
            class_index = self.classes.index(class_name)
        except ValueError:
            raise KeyError(class_name) from None
        if self.link == "sigmoid":
            sign = 1.0 if class_index == 1 else -1.0
            weights = self.coef[0]
        else:
            sign = 1.0
            weights = self.coef[class_index]
        scored = [
            (self.vocabulary[column], sign * weights[column] * value)
            for column, value in row.items()
        ]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored

    def as_dict(self) -> dict[str, Any]:
        """The artifact exactly as loaded."""
        return json.loads(json.dumps(self._artifact))


# --- loading ----------------------------------------------------------------


def load_artifact(path: Path) -> TfidfLinearModel:
    """Read and validate an artifact file.

    Raises:
        ArtifactError: the file is absent, not JSON, or fails validation.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ArtifactError(f"artifact could not be read: {path}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ArtifactError(f"artifact is not valid JSON: {path}") from exc
    return TfidfLinearModel(data)


def _validated(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse an artifact this code cannot evaluate faithfully.

    Every check here is about *silent* wrongness. A vocabulary of the wrong
    length would index the wrong IDF; a coefficient matrix of the wrong shape
    would score the wrong class; a tokeniser version other than this code's
    would vectorise text differently from how the model was trained and the
    numbers would still come out looking like probabilities.
    """
    if not isinstance(artifact, Mapping):
        raise ArtifactError("artifact must be a JSON object")
    required = (
        "artifact_format", "model_name", "model_version", "taxonomy_version",
        "tokeniser_version", "features", "vocabulary", "idf", "classes",
        "coef", "intercept", "link", "trained_on", "training",
    )
    missing = [key for key in required if key not in artifact]
    if missing:
        raise ArtifactError(f"artifact is missing keys: {missing}")
    if artifact["artifact_format"] != ARTIFACT_FORMAT:
        raise ArtifactError(
            f"unsupported artifact format {artifact['artifact_format']!r}; "
            f"this code reads {ARTIFACT_FORMAT!r}"
        )
    if artifact["taxonomy_version"] != TAXONOMY_VERSION:
        raise ArtifactError(
            f"artifact was built against taxonomy {artifact['taxonomy_version']!r}, "
            f"this code speaks {TAXONOMY_VERSION!r}"
        )
    if artifact["tokeniser_version"] != TOKENISER_VERSION:
        raise ArtifactError(
            f"artifact was built with tokeniser {artifact['tokeniser_version']!r}, "
            f"this code is {TOKENISER_VERSION!r}"
        )
    for key in ("model_name", "model_version", "link"):
        if not isinstance(artifact[key], str) or not artifact[key]:
            raise ArtifactError(f"{key} must be a non-empty string")
    if artifact["link"] not in ("softmax", "sigmoid"):
        raise ArtifactError(f"unknown link {artifact['link']!r}")

    vocabulary = artifact["vocabulary"]
    idf = artifact["idf"]
    classes = artifact["classes"]
    coef = artifact["coef"]
    intercept = artifact["intercept"]
    if not isinstance(vocabulary, list) or not vocabulary:
        raise ArtifactError("vocabulary must be a non-empty list")
    if any(not isinstance(term, str) for term in vocabulary):
        raise ArtifactError("vocabulary must contain only strings")
    if len(set(vocabulary)) != len(vocabulary):
        raise ArtifactError("vocabulary contains duplicate terms")
    if not isinstance(idf, list) or len(idf) != len(vocabulary):
        raise ArtifactError("idf must have one value per vocabulary term")
    if not isinstance(classes, list) or len(classes) < 2:
        raise ArtifactError("classes must list at least two classes")
    if len(set(classes)) != len(classes):
        raise ArtifactError("classes contains duplicates")
    unknown = [name for name in classes if not is_subcategory(name)]
    if unknown:
        raise ArtifactError(
            f"classes are not in the taxonomy: {unknown}; a model may only "
            f"predict subcategories taxonomy version {TAXONOMY_VERSION} defines"
        )
    expected_rows = 1 if artifact["link"] == "sigmoid" else len(classes)
    if artifact["link"] == "sigmoid" and len(classes) != 2:
        raise ArtifactError("a sigmoid link requires exactly two classes")
    if not isinstance(coef, list) or len(coef) != expected_rows:
        raise ArtifactError(
            f"coef must have {expected_rows} row(s) for link {artifact['link']!r}"
        )
    for row in coef:
        if not isinstance(row, list) or len(row) != len(vocabulary):
            raise ArtifactError("every coef row must have one value per term")
    if not isinstance(intercept, list) or len(intercept) != expected_rows:
        raise ArtifactError("intercept must have one value per coef row")
    for name in ("idf", "intercept"):
        _require_numbers(artifact[name], name)
    for row in coef:
        _require_numbers(row, "coef")
    if not isinstance(artifact["trained_on"], Mapping):
        raise ArtifactError("trained_on must be an object")
    if not isinstance(artifact["training"], Mapping):
        raise ArtifactError("training must be an object")
    FeatureConfig.from_dict(artifact["features"])
    return dict(artifact)


def _require_numbers(values: list, what: str) -> None:
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ArtifactError(f"{what} must contain only numbers")
        if math.isnan(value) or math.isinf(value):
            raise ArtifactError(f"{what} contains a non-finite value")


# --- links ------------------------------------------------------------------


def _softmax(scores: list[float]) -> list[float]:
    peak = max(scores)
    weights = [math.exp(score - peak) for score in scores]
    total = sum(weights)
    return [weight / total for weight in weights]


def _sigmoid(score: float) -> float:
    if score >= 0:
        return 1.0 / (1.0 + math.exp(-score))
    grown = math.exp(score)
    return grown / (1.0 + grown)
