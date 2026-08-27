"""Validate a frozen evaluation dataset, or run a pipeline against it.

    python -m labelextract.evaluation.cli validate ml/data/our-evaluation-set
    python -m labelextract.evaluation.cli run ml/data/our-evaluation-set \\
        --pipeline tesseract --report out.json

`validate` is the command to run before anything else and after any change to
the set. It parses the manifest, parses every annotation, and re-digests every
image, then says what it found. It never edits anything.

`run` executes a pipeline over every sample and prints a JSON report. It does
not decide whether the numbers are good, and it does not decide compliance -
see `runner.py`.

Exit codes: `0` fine, `1` the dataset is unusable, `2` the run failed, `3` bad
arguments. The same convention as `labelextract.cli`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from labelextract import registry
from labelextract.evaluation.dataset import describe_dataset, load_dataset
from labelextract.evaluation.runner import evaluate
from labelextract.evaluation.schema import EvaluationDataError
from labelextract.exceptions import LabelExtractError

EXIT_OK = 0
EXIT_DATASET_UNUSABLE = 1
EXIT_RUN_FAILED = 2
EXIT_BAD_USAGE = 3


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        dataset = load_dataset(
            Path(args.dataset), verify_checksums=not getattr(args, "skip_checksums", False)
        )
    except EvaluationDataError as exc:
        print(f"dataset is unusable:\n{exc}", file=sys.stderr)
        return EXIT_DATASET_UNUSABLE

    if args.command == "validate":
        description = describe_dataset(dataset)
        print(
            f"dataset {description['dataset_version']} "
            f"({description['created_on']}): {description['sample_count']} sample(s), "
            f"{description['annotated_field_count']} annotated field(s), "
            f"{description['samples_with_reference_text']} with reference text"
        )
        if description["conditions"]:
            listed = ", ".join(
                f"{name}={count}" for name, count in description["conditions"].items()
            )
            print(f"conditions: {listed}")
        if description["sample_count"] == 0:
            # Valid and empty. Said plainly, because "validated" on an empty
            # set is exactly the sentence that later gets remembered as
            # "the evaluation set is fine".
            print(
                "the manifest lists no samples - this set can measure nothing yet",
                file=sys.stderr,
            )
        return EXIT_OK

    # Same resolution rule as `labelextract.cli`: a bare --pipeline runs the
    # newest registered version. Reused rather than reimplemented so the two
    # entry points cannot disagree about which pipeline "tesseract" means.
    from labelextract.cli import _only_version_of

    version = args.pipeline_version or _only_version_of(args.pipeline)
    try:
        pipeline = registry.get_pipeline(args.pipeline, version)
    except LabelExtractError as exc:
        print(f"{exc}", file=sys.stderr)
        return EXIT_BAD_USAGE

    try:
        report = evaluate(dataset, pipeline)
    except LabelExtractError as exc:
        print(f"evaluation run failed: {exc}", file=sys.stderr)
        return EXIT_RUN_FAILED

    body = report.to_json()
    if args.report:
        Path(args.report).write_text(body, encoding="utf-8")
        print(f"wrote {args.report}")
    else:
        print(body)

    if report.failures:
        print(
            f"{len(report.failures)} sample(s) failed to run and were excluded "
            f"from scoring",
            file=sys.stderr,
        )
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m labelextract.evaluation.cli",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate", help="check a frozen dataset without running anything"
    )
    validate.add_argument("dataset", help="directory holding MANIFEST.json")
    validate.add_argument(
        "--skip-checksums",
        action="store_true",
        help=(
            "do not re-digest the images. For a quick structural check only - "
            "the digests are what make the set frozen, so a release check must "
            "not use this."
        ),
    )

    run = subparsers.add_parser("run", help="run a pipeline over the dataset and score it")
    run.add_argument("dataset", help="directory holding MANIFEST.json")
    run.add_argument("--pipeline", default="tesseract", help="registered pipeline name")
    run.add_argument(
        "--pipeline-version",
        default=None,
        help="registered pipeline version; required when several are registered",
    )
    run.add_argument("--report", default=None, help="write the JSON report here")

    return parser


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
