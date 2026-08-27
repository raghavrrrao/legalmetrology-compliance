"""Run a pipeline over a frozen dataset and produce a structured report.

    dataset (images + annotations)
        │
        ├── pipeline.run(image)  ──▶  ExtractionResult  ──▶  SamplePrediction
        │                                                          │
        └── SampleAnnotation ─────────────────────────────────────▶ score()
                                                                   │
                                                              EvaluationReport

What this does not do
---------------------
It does not evaluate compliance. No rule is loaded, no verdict is produced, and
`ComplianceRule` is not imported. This measures the perception layer - OCR and
field extraction - which is the layer whose errors are silent. Compliance
findings are measured "against a human reviewer's determination on the same
images" per `docs/evaluation-strategy.md` §4, which is a different exercise
needing verified rules that this repository does not yet contain.

It also makes no claim about a run. The report records what was measured, on
which dataset version, with which engine; whether that is enough to publish is
a judgement for whoever reads it, and `docs/evaluation-strategy.md` sets the
bar ("never report a number without its dataset, size and date").
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from labelextract.contracts import ImageRef
from labelextract.evaluation.dataset import (
    EvaluationDataset,
    describe_dataset,
    load_dataset,
)
from labelextract.evaluation.metrics import ScoreReport, score
from labelextract.evaluation.prediction import SamplePrediction
from labelextract.evaluation.schema import EvaluationDataError
from labelextract.pipeline import ExtractionPipeline

#: Bumped when the *scoring* changes in a way that makes two reports
#: incomparable - a new metric definition, a changed outcome table. Recorded in
#: every report for the same reason `ExtractionRun` records its engine version:
#: a stored number stays interpretable only if you know what produced it.
REPORT_VERSION = "1"


@dataclass(frozen=True)
class EvaluationReport:
    """One evaluation run, complete with what it was run against."""

    dataset: dict
    engine: dict
    environment: dict
    scores: ScoreReport
    per_sample: tuple[dict, ...]
    failures: tuple[dict, ...]

    def as_dict(self) -> dict:
        return {
            "report_version": REPORT_VERSION,
            "dataset": self.dataset,
            "engine": self.engine,
            "environment": self.environment,
            "scores": self.scores.as_dict(),
            "per_sample": list(self.per_sample),
            "failures": list(self.failures),
        }

    def to_json(self) -> str:
        """Deterministic JSON: identical input produces an identical string."""
        return json.dumps(self.as_dict(), indent=2, sort_keys=True, ensure_ascii=False)


def evaluate(
    dataset: EvaluationDataset,
    pipeline: ExtractionPipeline,
    *,
    run_date: str | None = None,
    image_ref_factory: Callable[[Path], ImageRef] | None = None,
) -> EvaluationReport:
    """Run `pipeline` over every sample in `dataset` and score the results.

    Args:
        dataset: a validated frozen dataset.
        pipeline: the pipeline under test.
        run_date: ISO date recorded in the report. Supplied by the caller so a
            report is reproducible in a test; defaults to today, because a real
            run's date is a fact about that run. Note this is the *run* date -
            the dataset's own version is fixed in its manifest and never
            derived from a clock.
        image_ref_factory: builds the `ImageRef` handed to the pipeline.
            Injectable so the suite can exercise the runner without an image
            decoder installed.

    A sample whose pipeline run raises is recorded in `failures` and excluded
    from scoring. It is not scored as a miss: a crashed run measures the
    harness, not the extractor, and folding it into recall would quietly
    improve the number every time a bug was fixed.
    """
    build_ref = image_ref_factory or _default_image_ref

    pairs = []
    per_sample: list[dict] = []
    failures: list[dict] = []

    for sample in dataset:
        try:
            result = pipeline.run(build_ref(sample.image_path))
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            failures.append(
                {
                    "sample_id": sample.sample_id,
                    "error": exc.__class__.__name__,
                    "message": str(exc)[:500],
                }
            )
            continue

        prediction = SamplePrediction.from_result(sample.sample_id, result)
        pairs.append((sample.annotation, prediction))
        per_sample.append(
            {
                "sample_id": sample.sample_id,
                "status": prediction.status,
                "conditions": list(sample.annotation.conditions),
                "recognised_characters": len(prediction.recognised_text),
                "fields_with_value": sum(
                    1 for f in prediction.fields if f.has_committed_value
                ),
                "fields_withheld": sum(
                    1 for f in prediction.fields if not f.has_committed_value
                ),
                "unread_declarations": sorted(k.value for k in prediction.unread_keys),
                "processing_ms": prediction.processing_ms,
                "error_code": prediction.error_code,
            }
        )

    engine = {
        "pipeline_name": pipeline.name,
        "pipeline_version": pipeline.version,
        "is_placeholder": _is_placeholder(pipeline),
    }

    return EvaluationReport(
        dataset=describe_dataset(dataset),
        engine=engine,
        environment={
            "run_date": run_date or date.today().isoformat(),
            "python": platform.python_version(),
            "platform": platform.system(),
        },
        scores=score(pairs),
        per_sample=tuple(sorted(per_sample, key=lambda item: item["sample_id"])),
        failures=tuple(sorted(failures, key=lambda item: item["sample_id"])),
    )


def evaluate_path(
    root: Path,
    pipeline: ExtractionPipeline,
    *,
    run_date: str | None = None,
) -> EvaluationReport:
    """Load the dataset at `root`, validate it fully, then evaluate it."""
    return evaluate(load_dataset(root), pipeline, run_date=run_date)


def _default_image_ref(path: Path) -> ImageRef:
    """Build the `ImageRef` the pipeline expects, exactly as the CLI does.

    Reuses `labelextract.cli._image_ref` rather than re-deriving format and
    dimensions here. A second implementation would drift, and the way it would
    drift is by disagreeing about an image's format - which is the difference
    between measuring the pipeline and measuring two different loaders.

    Imported inside the function so importing the evaluation package does not
    pull in argparse and the CLI's module-level work.
    """
    from labelextract.cli import _image_ref

    return _image_ref(path)


def _is_placeholder(pipeline: ExtractionPipeline) -> bool:
    """Whether the pipeline reads pixels at all.

    Recorded in the report because a run of the null engine produces a complete
    set of zeroes that looks exactly like a catastrophic OCR failure. The flag
    is what stops that being mistaken for a measurement.
    """
    engine = getattr(pipeline, "ocr_engine", None)
    return bool(getattr(engine, "is_placeholder", False))


__all__ = [
    "REPORT_VERSION",
    "EvaluationReport",
    "EvaluationDataError",
    "evaluate",
    "evaluate_path",
]
