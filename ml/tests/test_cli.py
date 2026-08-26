"""The developer CLI: argument handling, exit codes, and output shape.

Nothing here runs Tesseract. The CLI is tested against the registry's
placeholder pipeline and against a pipeline registered by this module, which is
enough to pin down everything the CLI itself is responsible for.
"""

import json

import pytest

from labelextract import cli, registry
from labelextract.baseline import null_engine
from labelextract.cli import main
from labelextract.cli import _parser
from labelextract.contracts import (
    BoundingBox,
    ExtractedField,
    ImageRef,
    LabelFieldKey,
    OcrResult,
    TextBlock,
)
from labelextract.exceptions import InvalidImageError
from labelextract.interfaces import FieldExtractor, OcrEngine
from labelextract.pipeline import ExtractionPipeline

_CLI_PIPELINE = "cli-test-pipeline"
_FAILING_PIPELINE = "cli-test-failing-pipeline"
_CLI_VERSION = "0.0.0"


class _FixedOcrEngine(OcrEngine):
    name = "cli-test-ocr"
    version = "0.0.0"

    def recognise(self, image: ImageRef) -> OcrResult:
        return OcrResult(
            blocks=(
                TextBlock(
                    text="Net Qty: 500 g",
                    box=BoundingBox(x=1, y=1, width=100, height=10),
                    confidence=0.9,
                ),
            ),
            raw={"words": ["Net", "Qty:", "500", "g"]},
        )


class _FixedFieldExtractor(FieldExtractor):
    name = "cli-test-fields"
    version = "0.0.0"

    def extract(self, ocr: OcrResult, image: ImageRef):
        return (
            ExtractedField(
                key=LabelFieldKey.NET_QUANTITY,
                raw_value="Net Qty: 500 g",
                normalized_value={"quantity": 500, "unit": "g", "uncertain": False},
                confidence=0.9,
                box=BoundingBox(x=1, y=1, width=100, height=10),
            ),
        )


class _FailingOcrEngine(OcrEngine):
    name = "cli-test-failing-ocr"
    version = "0.0.0"

    def recognise(self, image: ImageRef) -> OcrResult:
        raise InvalidImageError("this engine cannot read this image")


def _build() -> ExtractionPipeline:
    return ExtractionPipeline(
        name=_CLI_PIPELINE,
        version=_CLI_VERSION,
        ocr_engine=_FixedOcrEngine(),
        field_extractor=_FixedFieldExtractor(),
    )


# Registered once, at import. `register_pipeline` rejects duplicates on
# purpose, so a unique name is what keeps this from colliding with anything.
registry.register_pipeline(_CLI_PIPELINE, _CLI_VERSION, _build)
registry.register_pipeline(
    _FAILING_PIPELINE,
    _CLI_VERSION,
    lambda: ExtractionPipeline(
        name=_FAILING_PIPELINE, version=_CLI_VERSION, ocr_engine=_FailingOcrEngine()
    ),
)


def _run(capsys, *argv) -> tuple[int, dict]:
    code = main(list(argv))
    captured = capsys.readouterr()
    body = json.loads(captured.out) if captured.out.strip() else {}
    return code, body


def test_a_completed_run_prints_the_result_and_exits_zero(capsys, png_path):
    code, body = _run(
        capsys, str(png_path), "--pipeline", _CLI_PIPELINE,
        "--pipeline-version", _CLI_VERSION,
    )

    assert code == 0
    assert body["status"] == "completed"
    assert body["recognised_text"] == "Net Qty: 500 g"
    assert body["fields"][0]["key"] == "net_quantity"
    assert body["fields"][0]["normalized_value"]["quantity"] == 500


def test_geometry_and_confidence_appear_in_the_output(capsys, png_path):
    _, body = _run(
        capsys, str(png_path), "--pipeline", _CLI_PIPELINE,
        "--pipeline-version", _CLI_VERSION,
    )

    assert body["blocks"][0]["box"] == {"x": 1, "y": 1, "width": 100, "height": 10}
    assert body["blocks"][0]["confidence"] == 0.9


def test_engine_diagnostics_are_opt_in_because_they_are_large(capsys, png_path):
    _, without = _run(
        capsys, str(png_path), "--pipeline", _CLI_PIPELINE,
        "--pipeline-version", _CLI_VERSION,
    )
    _, with_raw = _run(
        capsys, str(png_path), "--pipeline", _CLI_PIPELINE,
        "--pipeline-version", _CLI_VERSION, "--raw",
    )

    assert "raw" not in without
    assert with_raw["raw"]["words"] == ["Net", "Qty:", "500", "g"]


def test_an_empty_run_exits_one(capsys, png_path):
    """A distinct exit code, so a shell script can tell it from a failure."""
    code, body = _run(
        capsys, str(png_path), "--pipeline", null_engine.NAME,
        "--pipeline-version", null_engine.VERSION,
    )

    assert code == 1
    assert body["status"] == "empty"
    assert body["is_placeholder"] is True


def test_a_failed_run_exits_two_and_carries_the_error_code(capsys, png_path):
    """A distinct exit code again, and the stable code the frontend branches on."""
    code, body = _run(
        capsys, str(png_path), "--pipeline", _FAILING_PIPELINE,
        "--pipeline-version", _CLI_VERSION,
    )

    assert code == 2
    assert body["status"] == "failed"
    assert body["error_code"] == "invalid_image"


def test_an_empty_file_is_rejected_before_a_pipeline_is_resolved(capsys, tmp_path):
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")

    code, _ = _run(capsys, str(empty), "--pipeline", null_engine.NAME)
    assert code == 3


def test_a_path_that_is_not_a_file_is_a_usage_error(capsys, tmp_path):
    code, _ = _run(capsys, str(tmp_path / "nothing-here.png"))
    assert code == 3


def test_a_file_that_is_not_an_image_is_a_usage_error(capsys, tmp_path):
    path = tmp_path / "notes.png"
    path.write_bytes(b"just some text, not an image")

    code, _ = _run(capsys, str(path))
    assert code == 3


def test_an_unknown_pipeline_is_a_usage_error(capsys, png_path):
    code, _ = _run(capsys, str(png_path), "--pipeline", "no-such-engine")
    assert code == 3


def test_the_version_is_optional_when_only_one_is_registered(capsys, png_path):
    code, body = _run(capsys, str(png_path), "--pipeline", null_engine.NAME)

    assert code == 1
    assert body["engine_version"] == null_engine.VERSION


@pytest.mark.parametrize("languages", ["eng; rm -rf /", "../../etc/passwd"])
def test_a_malformed_language_never_reaches_a_subprocess(capsys, png_path, languages):
    """The one CLI argument that becomes a Tesseract command-line value.

    Rejected as a usage error - the pipeline is never built, so nothing is
    spawned - and reported as exit 3 rather than as a traceback.
    """
    code, body = _run(
        capsys, str(png_path), "--pipeline", "tesseract", "--languages", languages
    )

    assert code == 3
    assert body == {}


# --- the engine that ran is the engine the result names ---------------------


def test_a_language_override_is_still_reported_as_the_tesseract_pipeline():
    """The result must name the engine that actually produced it.

    `--languages` rebuilds the pipeline instead of fetching the cached one, and
    an earlier version kept whatever `--pipeline` said while running Tesseract.
    A run recorded as `null-engine` with `is_placeholder` false, produced by a
    real OCR engine, would break the one guarantee the placeholder mechanism
    exists to give.
    """
    from labelextract.ocr import tesseract

    args = _parser().parse_args(
        ["label.png", "--pipeline", "tesseract", "--languages", "eng+hin"]
    )
    pipeline = cli._pipeline(args)

    assert pipeline.name == tesseract.NAME
    assert pipeline.version == tesseract.VERSION
    assert pipeline.is_placeholder is False


def test_asking_for_languages_on_another_pipeline_is_a_usage_error(capsys, png_path):
    """Not satisfied by quietly swapping in Tesseract under the old name."""
    code, _ = _run(
        capsys, str(png_path), "--pipeline", null_engine.NAME, "--languages", "eng"
    )
    assert code == 3


# --- the input checks do not depend on the optional [ocr] extra -------------


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("notes.png", b"just some text, not an image"),
        ("doc.png", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"),
        ("empty.png", b""),
    ],
)
def test_bad_input_is_rejected_with_or_without_pillow(
    capsys, tmp_path, monkeypatch, name, content
):
    """The same refusal, decoder or no decoder.

    CI runs the ML suite once with nothing installed and once with the `[ocr]`
    extra, and these rejections must hold in both. They are decided from the
    path and the file's leading bytes, which needs no image library - only
    measuring the dimensions does. An earlier version skipped the check
    entirely when Pillow was missing, so a text file reached the pipeline and
    came back as `engine_not_available` instead of a usage error.
    """
    path = tmp_path / name
    path.write_bytes(content)

    import builtins

    real_import = builtins.__import__

    def refuse_pil(module, *args, **kwargs):
        if module == "PIL" or module.startswith("PIL."):
            raise ImportError("simulated: the [ocr] extra is not installed")
        return real_import(module, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_pil)
    without_pillow, _ = _run(capsys, str(path))

    monkeypatch.undo()
    with_pillow, _ = _run(capsys, str(path))

    assert without_pillow == 3
    assert with_pillow == 3


def test_the_format_comes_from_the_bytes_not_the_extension(tmp_path, png_path):
    """A file named `.jpg` holding PNG bytes is a PNG, as it is at upload."""
    path = tmp_path / "mislabelled.jpg"
    path.write_bytes(png_path.read_bytes())

    ref = cli._image_ref(path)

    assert ref.image_format == "png"
