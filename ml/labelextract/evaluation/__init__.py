"""Infrastructure for measuring the OCR and extraction layers honestly.

**This package contains no dataset and no measurement.** It is the code that
reads a frozen evaluation set, validates it, runs a pipeline over it and scores
the result. The set itself - photographs and the annotations a person wrote for
them - lives outside the repository under `ml/data/our-evaluation-set/`, which
`.gitignore` excludes in full.

So a clone gets the method and none of the data, which is the arrangement
`docs/data-strategy.md` requires: photographs of retail packaging carry
third-party trade dress and occasionally incidental personal data, and a file
committed once is in every clone permanently.

**No accuracy, CER, WER, precision, recall or F1 figure for this system has
been measured.** Nothing in this package changes that. It makes measuring
possible; running it is a separate act, and `docs/evaluation-strategy.md` sets
out what may be claimed afterwards.

Layout
------
    schema.py       what ground truth is, and what makes it invalid
    dataset.py      loading a frozen set from disk, checksums included
    prediction.py   what the pipeline said - kept structurally apart from truth
    metrics.py      scoring, and refusing to score what it cannot
    runner.py       pipeline over dataset, producing a structured report
    cli.py          `python -m labelextract.evaluation.cli`
"""

from labelextract.evaluation.dataset import (
    EvaluationDataset,
    Sample,
    describe_dataset,
    file_sha256,
    load_dataset,
    load_manifest,
)
from labelextract.evaluation.metrics import (
    FieldCounts,
    ScoreReport,
    TextAccuracy,
    UncertaintyCounts,
    normalise_for_comparison,
    score,
)
from labelextract.evaluation.prediction import FieldPrediction, SamplePrediction
from labelextract.evaluation.runner import (
    REPORT_VERSION,
    EvaluationReport,
    evaluate,
    evaluate_path,
)
from labelextract.evaluation.schema import (
    DatasetManifest,
    EvaluationDataError,
    FieldAnnotation,
    FieldTruthState,
    SampleAnnotation,
    SampleEntry,
    supported_keys_only,
)

__all__ = [
    "REPORT_VERSION",
    "DatasetManifest",
    "EvaluationDataError",
    "EvaluationDataset",
    "EvaluationReport",
    "FieldAnnotation",
    "FieldCounts",
    "FieldPrediction",
    "FieldTruthState",
    "Sample",
    "SampleAnnotation",
    "SampleEntry",
    "SamplePrediction",
    "ScoreReport",
    "TextAccuracy",
    "UncertaintyCounts",
    "describe_dataset",
    "evaluate",
    "evaluate_path",
    "file_sha256",
    "load_dataset",
    "load_manifest",
    "normalise_for_comparison",
    "score",
    "supported_keys_only",
]
