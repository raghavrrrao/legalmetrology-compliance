"""Product category classification from recognised label text.

    OCR text
        -> preprocessing.preprocess_text      deterministic clean-up
        -> model.TfidfLinearModel             TF-IDF + logistic regression
        -> classifier.TfidfProductClassifier  thresholds, UNKNOWN, evidence
        -> contracts.ProductClassification    category / subcategory / confidence / evidence

The classifier identifies *what kind of product* a label belongs to, so the
applicability layer can ask the right questions about it. It never decides
which rules apply and never decides compliance - `docs/ml/product-classification.md`
sets out where the line is and why.

Runtime needs nothing outside the standard library: the shipped artifact is
JSON and `model.py` evaluates it directly. scikit-learn is needed only to
*train* a new artifact (`train.py`, the `classify-train` extra).
"""

from labelextract.classification.classifier import (
    NAME,
    VERSION,
    ClassifierConfig,
    TfidfProductClassifier,
    build_classifier,
    shipped_artifact_path,
)
from labelextract.classification.dataset import (
    ClassificationDataError,
    ClassificationDataset,
    ClassificationExample,
    load_dataset,
    seed_dataset_path,
)
from labelextract.classification.model import (
    ArtifactError,
    TfidfLinearModel,
    load_artifact,
)
from labelextract.classification.preprocessing import (
    feature_tokens,
    preprocess_text,
    word_tokens,
)
from labelextract.classification.signals import SIGNALS, matched_signals
from labelextract.classification.taxonomy import (
    CATEGORIES,
    PACKAGED_FOOD,
    PACKAGED_NON_FOOD,
    SUBCATEGORIES,
    TAXONOMY_VERSION,
    UNKNOWN,
    category_for,
)

__all__ = [
    "ArtifactError",
    "CATEGORIES",
    "ClassificationDataError",
    "ClassificationDataset",
    "ClassificationExample",
    "ClassifierConfig",
    "NAME",
    "PACKAGED_FOOD",
    "PACKAGED_NON_FOOD",
    "SIGNALS",
    "SUBCATEGORIES",
    "TAXONOMY_VERSION",
    "TfidfLinearModel",
    "TfidfProductClassifier",
    "UNKNOWN",
    "VERSION",
    "build_classifier",
    "category_for",
    "feature_tokens",
    "load_artifact",
    "load_dataset",
    "matched_signals",
    "preprocess_text",
    "seed_dataset_path",
    "shipped_artifact_path",
    "word_tokens",
]
