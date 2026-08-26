"""Run an extraction pipeline over one local image and print the result as JSON.

    python -m labelextract.cli path/to/label.jpg
    python -m labelextract.cli label.jpg --pipeline tesseract --pipeline-version 0.1.0
    python -m labelextract.cli label.jpg --languages eng+hin

Why this exists
---------------
Tuning a pattern or trying a preprocessing setting should not require Postgres,
a Django server and an upload form. This is the shortest path from a photograph
on disk to the exact `ExtractionResult` the backend would persist.

It is a development tool. It is not imported by the backend, it takes no input
from a network, and it runs nothing it is given: the only argument that reaches
Tesseract is a language code, validated against `TesseractOptions`' allowlist
before it gets anywhere near a subprocess. The image path is a path - it is
opened, never executed.

`--languages` rebuilds the Tesseract pipeline rather than mutating the cached
one, and the result is always named as the Tesseract pipeline. Asking for
languages on any other pipeline is a usage error: a run labelled `null-engine`
while Tesseract actually produced it would defeat the point of the placeholder
flag.

Argument checking does not need the optional `[ocr]` extra
----------------------------------------------------------
Missing, empty, not-a-file and not-an-image-at-all are all decided from the path
and the file's leading bytes, so the same inputs are refused whether or not
Pillow is installed. Only measuring the image's dimensions needs a decoder, and
an absent one costs a metadata field rather than a check.

Exit codes, so it is usable from a shell script:
    0  extraction completed
    1  extraction produced no usable text (EMPTY)
    2  extraction failed (the JSON carries `error_code`)
    3  the arguments were wrong
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from labelextract import registry
from labelextract.contracts import ExtractionResult, ExtractionStatus, ImageRef
from labelextract.exceptions import (
    InvalidImageError,
    LabelExtractError,
    UnsupportedImageFormatError,
)
from labelextract.imageio import readable_file, sniff_image_format

_EXIT_BY_STATUS = {
    ExtractionStatus.COMPLETED: 0,
    ExtractionStatus.EMPTY: 1,
    ExtractionStatus.FAILED: 2,
}
_EXIT_BAD_USAGE = 3


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    try:
        image = _image_ref(Path(args.image))
    except (InvalidImageError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_BAD_USAGE

    try:
        pipeline = _pipeline(args)
    except (LabelExtractError, ValueError) as exc:
        # ValueError is how the option dataclasses reject a bad setting - an
        # invalid language code, an out-of-range page-segmentation mode. That
        # is a mistake in the arguments, so it exits like one instead of
        # printing a traceback at someone who mistyped a flag.
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_BAD_USAGE

    result = pipeline.run(image)
    print(json.dumps(_as_json(result, include_raw=args.raw), indent=2, sort_keys=True))
    return _EXIT_BY_STATUS[result.status]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m labelextract.cli",
        description="Run a label-extraction pipeline over one image.",
    )
    parser.add_argument("image", help="Path to a JPEG, PNG or WebP image.")
    parser.add_argument(
        "--pipeline",
        default="tesseract",
        help="Registered pipeline name (default: tesseract).",
    )
    parser.add_argument(
        "--pipeline-version",
        default=None,
        help="Registered pipeline version. Defaults to the newest registered "
             "version of the chosen pipeline. Pass 0.1.0 to run the frozen "
             "Tesseract baseline and compare.",
    )
    parser.add_argument(
        "--languages",
        default=None,
        help="Tesseract languages, '+'-separated, e.g. eng+hin. Requires the "
             "matching language data to be installed.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Include the engine's verbatim diagnostics, including every "
             "recognised word. Large.",
    )
    return parser


def _pipeline(args: argparse.Namespace):
    """Resolve the requested pipeline, rebuilding it if languages were given."""
    if args.languages:
        return _tesseract_with_languages(args)
    version = args.pipeline_version or _only_version_of(args.pipeline)
    return registry.get_pipeline(args.pipeline, version)


def _tesseract_with_languages(args: argparse.Namespace):
    """Build a Tesseract pipeline with an overridden language set.

    Built rather than fetched, because mutating the registry's cached instance
    would change the engine for every other caller in the process.

    It is always named and versioned as the *Tesseract* pipeline, never as
    whatever `--pipeline` said. An `ExtractionRun` labelled `null-engine` while
    Tesseract actually ran would break the guarantee the whole placeholder
    mechanism exists to provide - that what the result claims produced it is
    what produced it. Asking for languages on any other pipeline is therefore a
    usage error, not something to satisfy by quietly swapping the engine.
    """
    from labelextract.fields import RuleBasedFieldExtractor
    from labelextract.ocr import tesseract
    from labelextract.pipeline import ExtractionPipeline
    from labelextract.preprocessing import PillowPreprocessor

    if args.pipeline != tesseract.NAME:
        raise ValueError(
            f"--languages configures the {tesseract.NAME!r} OCR engine and "
            f"cannot be applied to the {args.pipeline!r} pipeline."
        )
    if args.pipeline_version not in (None, tesseract.VERSION):
        raise ValueError(
            f"--languages rebuilds the {tesseract.NAME!r} pipeline at version "
            f"{tesseract.VERSION}, not {args.pipeline_version!r}."
        )

    options = tesseract.TesseractOptions(
        languages=tuple(
            code.strip() for code in args.languages.split("+") if code.strip()
        )
    )
    return ExtractionPipeline(
        name=tesseract.NAME,
        version=tesseract.VERSION,
        ocr_engine=tesseract.TesseractOcrEngine(options),
        preprocessor=PillowPreprocessor(),
        field_extractor=RuleBasedFieldExtractor(),
    )


def _only_version_of(name: str) -> str:
    """The version to use when none was asked for: the newest registered one.

    `available_pipelines()` yields sorted pairs, so the last version of a name
    is the highest. That matters now that `tesseract` registers both its
    current configuration and the frozen 0.1.0 baseline: a bare `--pipeline
    tesseract` must run the current one, and the baseline must be asked for by
    name.
    """
    versions = [
        version for registered, version in registry.available_pipelines()
        if registered == name
    ]
    if len(versions) == 1:
        return versions[0]
    # Zero registered versions falls through to `get_pipeline`, which raises
    # PipelineNotFoundError listing what is available - a better message than
    # anything this function could produce.
    return versions[-1] if versions else ""


def _image_ref(path: Path) -> ImageRef:
    """Build the pipeline's input contract from a file on disk.

    The dependency boundary is explicit here, and it matters: **every rejection
    below works without Pillow.** Missing, empty, not-a-file and
    not-an-image-at-all are all decided from the path and the leading bytes, so
    the CLI refuses the same inputs whether or not the optional `[ocr]` extra
    is installed. Only the *dimensions* need a decoder.

    Format comes from the file's magic bytes, never from its extension, for the
    same reason `apps.images.validators` decodes rather than trusting the
    upload: an extension is a claim by whoever named the file. Pillow refines
    it when present, because a decoder's answer beats a signature's.

    Dimensions are left as None when Pillow is absent. None means "not
    measured" throughout this package, so a missing Pillow costs a metadata
    field rather than producing a made-up one.
    """
    resolved = readable_file(path)

    image_format = sniff_image_format(resolved)
    if image_format is None:
        raise UnsupportedImageFormatError(
            f"{resolved} is not a JPEG, PNG or WebP image."
        )

    width = height = None
    try:
        from PIL import Image

        with Image.open(resolved) as probe:
            width, height = probe.size
            if probe.format:
                image_format = probe.format.lower()
    except ImportError:
        # No decoder available. The signature check above already established
        # that the bytes claim a format we accept; the pipeline's own
        # preprocessing stage will decode and reject it properly if that claim
        # turns out to be false.
        pass
    except Exception as exc:
        raise InvalidImageError(
            f"{resolved} could not be read as an image: {exc}"
        ) from exc

    return ImageRef(
        path=resolved,
        image_format=image_format,
        size_bytes=resolved.stat().st_size,
        width=width,
        height=height,
    )


def _as_json(result: ExtractionResult, *, include_raw: bool) -> dict[str, Any]:
    """The same shape the backend persists, so the two can be compared."""
    body: dict[str, Any] = {
        "status": result.status.value,
        "engine_name": result.engine_name,
        "engine_version": result.engine_version,
        "is_placeholder": result.is_placeholder,
        "processing_ms": result.processing_ms,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "metadata": dict(result.metadata),
        "recognised_text": result.ocr.full_text,
        "blocks": [
            {
                "text": block.text,
                "confidence": block.confidence,
                "box": block.box.as_dict() if block.box else None,
            }
            for block in result.ocr.blocks
        ],
        "fields": [
            {
                "key": extracted.key.value,
                "raw_value": extracted.raw_value,
                "normalized_value": (
                    dict(extracted.normalized_value)
                    if extracted.normalized_value is not None
                    else None
                ),
                "confidence": extracted.confidence,
                "box": extracted.box.as_dict() if extracted.box else None,
            }
            for extracted in result.fields
        ],
    }
    if include_raw:
        body["raw"] = dict(result.ocr.raw)
    return body


if __name__ == "__main__":
    raise SystemExit(main())
