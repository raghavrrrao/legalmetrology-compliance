"""The shipped `ProductClassifier`: OCR text -> category, with an UNKNOWN path.

    recognised text
        -> preprocess_text                     (deterministic clean-up)
        -> enough tokens?  no -> UNKNOWN       ("insufficient text")
        -> TfidfLinearModel.predict_proba      (probability per subcategory)
        -> sum per category                    (probability per category)
        -> best category >= threshold?  no -> UNKNOWN ("below threshold")
        -> best subcategory >= threshold?  no -> subcategory None
        -> ProductClassification, with evidence

Two thresholds and a token floor, all in `ClassifierConfig`, all documented
as **initial, uncalibrated baselines**. Nothing about 0.6 is scientific: it
is the point below which a two-category answer is closer to a coin than to a
finding, chosen so the first model would abstain often rather than rarely.
The right values come from validation data the project does not yet have -
`docs/ml/product-classification.md` says how they should be set once it
does, and `train.py` reports the UNKNOWN rate the current values produce on
the seed set so the effect of changing them is visible.

The confidence reported is the probability mass the model puts behind the
chosen category. It is a statement about the *text* - "this reads like a
packaged food" - and about nothing else. It is not a compliance figure and
no part of this system may treat it as one.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from labelextract.classification import taxonomy
from labelextract.classification.model import (
    MODEL_NAME,
    ArtifactError,
    TfidfLinearModel,
    load_artifact,
)
from labelextract.classification.preprocessing import (
    preprocess_text,
    word_tokens,
)
from labelextract.classification.signals import describe, matched_signals
from labelextract.contracts import (
    ExtractedField,
    ImageRef,
    OcrResult,
    ProductClassification,
)
from labelextract.exceptions import EngineNotAvailableError
from labelextract.interfaces import ProductClassifier

NAME = MODEL_NAME

#: The artifact version this package ships and `build_classifier` loads. The
#: file is named after it, and the loader checks the artifact agrees, so a
#: stale or renamed file is refused rather than run under the wrong label.
VERSION = "0.1.0"

#: Where the shipped artifact lives inside the installed package.
ARTIFACT_RESOURCE_DIR = "artifacts"


def shipped_artifact_path(version: str = VERSION) -> Path:
    """The on-disk path of the artifact shipped for `version`."""
    package = resources.files("labelextract.classification")
    return Path(str(package / ARTIFACT_RESOURCE_DIR / f"product_classifier_v{version}.json"))


@dataclass(frozen=True)
class ClassifierConfig:
    """Decision thresholds. Initial baselines - see the module docstring."""

    #: Probability mass a category needs before it is reported at all. Below
    #: it the answer is UNKNOWN and the scores are reported as evidence.
    min_category_confidence: float = 0.60
    #: Probability mass a subcategory needs before it is named. Below it the
    #: category is still reported and `subcategory` is None.
    min_subcategory_confidence: float = 0.50
    #: Fewer word tokens than this and no prediction is attempted. Three
    #: tokens is a brand name; it is not a label.
    min_tokens: int = 3
    #: How many matched signals and weighted terms to carry as evidence.
    max_evidence_signals: int = 8
    max_evidence_terms: int = 6

    def __post_init__(self) -> None:
        for name in ("min_category_confidence", "min_subcategory_confidence"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1], got {value!r}")
        if self.min_tokens < 0:
            raise ValueError("min_tokens must be non-negative")


class TfidfProductClassifier(ProductClassifier):
    """Classifies a label from its recognised text using a shipped artifact.

    The artifact is loaded once, lazily, on `warmup()` or first use, and the
    instance is then safe to share across threads: the loaded model is
    immutable and every call reads it only.

    Args:
        artifact_path: An artifact to load instead of the shipped one. For
            tests and experiments. The artifact's `model_version` must equal
            `version`.
        version: The version this instance reports. Defaults to the shipped
            artifact's.
        config: Thresholds. Defaults are the documented initial baselines.
    """

    name = NAME

    def __init__(
        self,
        artifact_path: Path | None = None,
        *,
        version: str = VERSION,
        config: ClassifierConfig | None = None,
    ) -> None:
        self.version = version
        self.artifact_path = (
            Path(artifact_path) if artifact_path is not None
            else shipped_artifact_path(version)
        )
        self.config = config or ClassifierConfig()
        self._model: TfidfLinearModel | None = None
        self._lock = threading.Lock()

    # --- lifecycle ----------------------------------------------------------

    def warmup(self) -> None:
        """Load the artifact now, so a bad one fails at startup, not on upload.

        Raises:
            EngineNotAvailableError: the artifact is absent or invalid.
        """
        self._ensure_loaded()

    @property
    def model(self) -> TfidfLinearModel:
        return self._ensure_loaded()

    def _ensure_loaded(self) -> TfidfLinearModel:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                try:
                    model = load_artifact(self.artifact_path)
                except ArtifactError as exc:
                    raise EngineNotAvailableError(
                        f"product classifier artifact unavailable: {exc}"
                    ) from exc
                if model.model_version != self.version:
                    raise EngineNotAvailableError(
                        f"product classifier artifact is version "
                        f"{model.model_version!r}; this classifier is "
                        f"registered as {self.version!r}"
                    )
                if model.model_name != self.name:
                    raise EngineNotAvailableError(
                        f"product classifier artifact is model "
                        f"{model.model_name!r}, not {self.name!r}"
                    )
                self._model = model
        return self._model

    # --- the ProductClassifier interface ------------------------------------

    def classify(
        self,
        ocr: OcrResult,
        fields: tuple[ExtractedField, ...],
        image: ImageRef,
    ) -> ProductClassification:
        """Classify from the recognised text. `fields` and `image` are unused.

        They are accepted so the signature is the interface's; a later model
        may weigh which declarations were found, or look at the pixels.
        """
        return self.classify_text(ocr.full_text)

    def classify_text(self, text: str | None) -> ProductClassification:
        """Classify an arbitrary piece of label text.

        The method tests and the training harness call, so that what is
        measured offline is exactly what runs in the pipeline.
        """
        cleaned = preprocess_text(text)
        token_count = len(word_tokens(cleaned))
        if token_count < self.config.min_tokens:
            return self._unknown(
                evidence=(
                    f"insufficient text: {token_count} word token(s), "
                    f"fewer than the {self.config.min_tokens} required",
                ),
            )

        model = self._ensure_loaded()
        row = model.vectorise(cleaned)
        if not row:
            # Not one n-gram of this text is in the vocabulary. The model's
            # output would be its intercept-only prior, which says something
            # about the training set and nothing about this label.
            return self._unknown(
                evidence=(
                    f"insufficient evidence: none of the {token_count} word "
                    f"token(s) is known to the model",
                ),
            )
        subcategory_scores = model.probabilities(row)
        category_scores = _aggregate(subcategory_scores)

        best_category, category_mass = max(
            category_scores.items(), key=lambda item: (item[1], item[0])
        )
        signals = matched_signals(cleaned)[: self.config.max_evidence_signals]
        signal_evidence = tuple(describe(signal) for signal in signals)

        if category_mass < self.config.min_category_confidence:
            return self._unknown(
                evidence=(
                    f"below confidence threshold "
                    f"{self.config.min_category_confidence:.2f}: best "
                    f"candidate {best_category} ({category_mass:.2f})",
                    *signal_evidence,
                ),
                category_scores=category_scores,
                subcategory_scores=subcategory_scores,
            )

        candidates = {
            name: mass for name, mass in subcategory_scores.items()
            if taxonomy.category_for(name) == best_category
        }
        best_subcategory, subcategory_mass = max(
            candidates.items(), key=lambda item: (item[1], item[0])
        )
        term_evidence = tuple(
            f"term: {term!r} weighed for {best_subcategory}"
            for term, weight in model.contributions(row, best_subcategory)
            if weight > 0.0
        )[: self.config.max_evidence_terms]

        if subcategory_mass < self.config.min_subcategory_confidence:
            reported_subcategory: str | None = None
            reported_mass: float | None = None
            note = (
                f"subcategory below threshold "
                f"{self.config.min_subcategory_confidence:.2f}: best "
                f"candidate {best_subcategory} ({subcategory_mass:.2f})",
            )
        else:
            reported_subcategory = best_subcategory
            reported_mass = _rounded(subcategory_mass)
            note = ()

        return ProductClassification(
            category=best_category,
            subcategory=reported_subcategory,
            confidence=_rounded(category_mass),
            subcategory_confidence=reported_mass,
            evidence=(*note, *signal_evidence, *term_evidence),
            category_scores=_rounded_map(category_scores),
            subcategory_scores=_rounded_map(subcategory_scores),
            classifier_name=self.name,
            classifier_version=self.version,
        )

    def _unknown(
        self,
        *,
        evidence: tuple[str, ...],
        category_scores: dict[str, float] | None = None,
        subcategory_scores: dict[str, float] | None = None,
    ) -> ProductClassification:
        """The declined answer. Confidence is None: nothing was asserted."""
        return ProductClassification(
            category=taxonomy.UNKNOWN,
            subcategory=None,
            confidence=None,
            subcategory_confidence=None,
            evidence=evidence,
            category_scores=_rounded_map(category_scores or {}),
            subcategory_scores=_rounded_map(subcategory_scores or {}),
            classifier_name=self.name,
            classifier_version=self.version,
        )


def build_classifier(config: ClassifierConfig | None = None) -> TfidfProductClassifier:
    """The classifier the registered Tesseract pipeline wires in.

    Loads nothing until `warmup()` or the first classification, so building
    a pipeline stays free and a missing artifact is reported by the health
    check rather than at import time.
    """
    return TfidfProductClassifier(config=config)


def _aggregate(subcategory_scores: dict[str, float]) -> dict[str, float]:
    """Sum subcategory mass into its category. Every category is present."""
    totals = {category: 0.0 for category in taxonomy.CATEGORIES}
    for name, mass in subcategory_scores.items():
        totals[taxonomy.category_for(name)] += mass
    return totals


def _rounded(value: float) -> float:
    """Four decimals: enough to compare, few enough not to imply precision."""
    return round(min(1.0, max(0.0, value)), 4)


def _rounded_map(scores: dict[str, float]) -> dict[str, float]:
    return {name: _rounded(mass) for name, mass in scores.items()}
