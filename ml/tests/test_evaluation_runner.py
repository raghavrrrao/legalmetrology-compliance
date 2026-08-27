"""The runner: dataset in, report out, and what the report is careful to say.

The **real** `RuleBasedFieldExtractor` runs in these tests. Only the OCR engine
is faked, and only because the suite must pass on a clone with no Tesseract
binary installed - so the readings being scored are the ones production would
produce, and a change to extraction shows up here.

None of this is a measurement. The dataset is synthetic, written by the test,
over PNGs built byte-by-byte. It exercises the harness.
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest

from labelextract import registry
from labelextract.contracts import ImageRef, OcrResult, TextBlock
from labelextract.evaluation import (
    EvaluationDataError,
    evaluate,
    evaluate_path,
    file_sha256,
    load_dataset,
)
from labelextract.evaluation.cli import main as evaluation_cli
from labelextract.exceptions import PipelineNotFoundError
from labelextract.fields import RuleBasedFieldExtractor
from labelextract.interfaces import OcrEngine
from labelextract.pipeline import ExtractionPipeline

_VERSION = "0.0.0-evaluation-test"


def _png_bytes(grey: int = 0x80) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
    scanlines = b"".join(b"\x00" + bytes((grey, grey, grey)) * 4 for _ in range(4))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


class _ScriptedOcrEngine(OcrEngine):
    """Returns the same lines for every image. The only faked component."""

    name = "scripted"
    version = _VERSION

    def __init__(self, lines: tuple[str, ...]):
        self._lines = lines

    def recognise(self, image: ImageRef) -> OcrResult:
        return OcrResult(
            blocks=tuple(
                TextBlock(text=line, box=None, confidence=0.9) for line in self._lines
            ),
            raw={"engine": "scripted"},
        )


class _ExplodingOcrEngine(OcrEngine):
    name = "exploding"
    version = _VERSION

    def recognise(self, image: ImageRef) -> OcrResult:
        raise RuntimeError("engine fell over")


def _pipeline(lines: tuple[str, ...]) -> ExtractionPipeline:
    return ExtractionPipeline(
        name="scripted",
        version=_VERSION,
        ocr_engine=_ScriptedOcrEngine(lines),
        preprocessor=None,
        field_extractor=RuleBasedFieldExtractor(),
    )


@pytest.fixture
def image_ref_factory():
    """Build an ImageRef without needing a decoder installed."""

    def _factory(path: Path) -> ImageRef:
        return ImageRef(
            path=path,
            image_format="png",
            size_bytes=path.stat().st_size,
            width=4,
            height=4,
        )

    return _factory


@pytest.fixture
def dataset_root(tmp_path):
    def _build(fields: list[dict], *, reference_text: str | None = None) -> Path:
        root = tmp_path / "set"
        (root / "images").mkdir(parents=True, exist_ok=True)
        (root / "annotations").mkdir(parents=True, exist_ok=True)

        (root / "images" / "eval_0001.png").write_bytes(_png_bytes())
        annotation = {
            "sample_id": "eval_0001",
            "annotated_by": "a-reviewer",
            "annotated_on": "2026-01-15",
            "conditions": ["flat"],
            "fields": fields,
        }
        if reference_text is not None:
            annotation["reference_text"] = reference_text
        (root / "annotations" / "eval_0001.json").write_text(
            json.dumps(annotation), encoding="utf-8"
        )
        (root / "MANIFEST.json").write_text(
            json.dumps(
                {
                    "dataset_version": "v1",
                    "created_on": "2026-01-15",
                    "description": "Synthetic fixture. Not a measurement.",
                    "samples": [
                        {
                            "sample_id": "eval_0001",
                            "image": "images/eval_0001.png",
                            "annotation": "annotations/eval_0001.json",
                            "image_sha256": file_sha256(root / "images" / "eval_0001.png"),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return root

    return _build


# --- a run against the real extractor ---------------------------------------


def test_a_correct_reading_scores_as_a_true_positive(dataset_root, image_ref_factory):
    root = dataset_root(
        [{"key": "net_quantity", "state": "present_and_readable", "value": "500 g"}]
    )
    report = evaluate(
        load_dataset(root),
        _pipeline(("Net Quantity: 500 g",)),
        run_date="2026-02-01",
        image_ref_factory=image_ref_factory,
    )

    quantity = next(
        item for item in report.as_dict()["scores"]["per_field"]
        if item["key"] == "net_quantity"
    )
    assert quantity["true_positive"] == 1
    assert quantity["value_correct"] == 1
    assert quantity["recall"] == 1.0


def test_a_declaration_the_label_does_not_carry_is_not_invented(
    dataset_root, image_ref_factory
):
    root = dataset_root([{"key": "batch_number", "state": "not_present"}])
    report = evaluate(
        load_dataset(root),
        _pipeline(("Net Quantity: 500 g",)),
        run_date="2026-02-01",
        image_ref_factory=image_ref_factory,
    )

    batch = next(
        item for item in report.as_dict()["scores"]["per_field"]
        if item["key"] == "batch_number"
    )
    assert batch["true_negative"] == 1
    assert batch["false_positive"] == 0


def test_the_report_names_the_dataset_and_the_engine(dataset_root, image_ref_factory):
    """A number without its dataset, size and date is not a claim."""
    root = dataset_root([])
    body = evaluate(
        load_dataset(root),
        _pipeline(("Net Quantity: 500 g",)),
        run_date="2026-02-01",
        image_ref_factory=image_ref_factory,
    ).as_dict()

    assert body["dataset"]["dataset_version"] == "v1"
    assert body["dataset"]["sample_count"] == 1
    assert body["dataset"]["created_on"] == "2026-01-15"
    assert body["engine"]["pipeline_name"] == "scripted"
    assert body["engine"]["pipeline_version"] == _VERSION
    assert body["engine"]["is_placeholder"] is False
    assert body["environment"]["run_date"] == "2026-02-01"
    assert body["report_version"]


def test_per_condition_information_travels_with_each_sample(
    dataset_root, image_ref_factory
):
    """Reporting per condition is required; the runner must carry the labels."""
    root = dataset_root([])
    body = evaluate(
        load_dataset(root),
        _pipeline(("Net Quantity: 500 g",)),
        run_date="2026-02-01",
        image_ref_factory=image_ref_factory,
    ).as_dict()

    assert body["per_sample"][0]["conditions"] == ["flat"]
    assert body["dataset"]["conditions"] == {"flat": 1}


# --- determinism -------------------------------------------------------------


def test_two_runs_over_the_same_input_produce_identical_json(
    dataset_root, image_ref_factory
):
    """A diff between two reports must show a change in the numbers, nothing else."""
    root = dataset_root(
        [{"key": "net_quantity", "state": "present_and_readable", "value": "500 g"}]
    )
    dataset = load_dataset(root)
    pipeline = _pipeline(("Net Quantity: 500 g",))

    first = evaluate(dataset, pipeline, run_date="2026-02-01",
                     image_ref_factory=image_ref_factory).to_json()
    second = evaluate(dataset, pipeline, run_date="2026-02-01",
                      image_ref_factory=image_ref_factory).to_json()

    assert first == second
    json.loads(first)  # and it is valid JSON


# --- failures are recorded, never scored ------------------------------------


def test_a_crashed_sample_is_recorded_and_excluded_from_scoring(
    dataset_root, image_ref_factory
):
    """A crashed run measures the harness, not the extractor.

    Folding it into recall would quietly improve the number every time a bug
    was fixed, which is precisely backwards.
    """
    root = dataset_root(
        [{"key": "net_quantity", "state": "present_and_readable", "value": "500 g"}]
    )
    broken = ExtractionPipeline(
        name="exploding",
        version=_VERSION,
        ocr_engine=_ExplodingOcrEngine(),
        preprocessor=None,
        field_extractor=RuleBasedFieldExtractor(),
    )

    body = evaluate(
        load_dataset(root), broken, run_date="2026-02-01",
        image_ref_factory=image_ref_factory,
    ).as_dict()

    assert len(body["failures"]) == 1
    assert body["failures"][0]["sample_id"] == "eval_0001"
    quantity = next(
        item for item in body["scores"]["per_field"] if item["key"] == "net_quantity"
    )
    assert quantity["false_negative"] == 0
    assert quantity["recall"] is None


# --- ground truth and prediction stay apart ---------------------------------


def test_the_report_never_writes_ground_truth_back(dataset_root, image_ref_factory):
    """Running an evaluation must not modify the annotations it scored against."""
    root = dataset_root([{"key": "net_quantity", "state": "present_but_unreadable"}])
    annotation_path = root / "annotations" / "eval_0001.json"
    before = annotation_path.read_bytes()

    evaluate(
        load_dataset(root), _pipeline(("Net Quantity: 500 g",)),
        run_date="2026-02-01", image_ref_factory=image_ref_factory,
    )

    assert annotation_path.read_bytes() == before


def test_a_reading_for_an_unreadable_declaration_is_reported_as_fabricated(
    dataset_root, image_ref_factory
):
    """End to end, through the real extractor: the failure that matters most."""
    root = dataset_root([{"key": "net_quantity", "state": "present_but_unreadable"}])
    body = evaluate(
        load_dataset(root), _pipeline(("Net Quantity: 500 g",)),
        run_date="2026-02-01", image_ref_factory=image_ref_factory,
    ).as_dict()

    quantity = next(
        item for item in body["scores"]["per_field"] if item["key"] == "net_quantity"
    )
    assert quantity["fabricated"] == 1
    kinds = {item["kind"] for item in body["scores"]["disagreements"]}
    assert "fabricated_value" in kinds


# --- CER / WER through the runner -------------------------------------------


def test_cer_is_unavailable_without_a_transcription(dataset_root, image_ref_factory):
    root = dataset_root([])
    body = evaluate(
        load_dataset(root), _pipeline(("Net Quantity: 500 g",)),
        run_date="2026-02-01", image_ref_factory=image_ref_factory,
    ).as_dict()

    text = body["scores"]["text_accuracy"]
    assert text["cer"] is None and text["wer"] is None
    assert text["unavailable_reason"]


def test_cer_is_computed_when_a_transcription_exists(dataset_root, image_ref_factory):
    root = dataset_root([], reference_text="Net Quantity: 500 g")
    body = evaluate(
        load_dataset(root), _pipeline(("Net Quantity: 500 g",)),
        run_date="2026-02-01", image_ref_factory=image_ref_factory,
    ).as_dict()

    text = body["scores"]["text_accuracy"]
    assert text["cer"] == 0.0
    assert text["scored_samples"] == 1
    assert text["unavailable_reason"] is None


# --- the CLI -----------------------------------------------------------------


def test_the_validate_command_accepts_a_good_dataset(dataset_root, capsys):
    root = dataset_root([])
    assert evaluation_cli(["validate", str(root)]) == 0
    assert "dataset v1" in capsys.readouterr().out


def test_the_validate_command_rejects_a_tampered_dataset(dataset_root, capsys):
    root = dataset_root([])
    (root / "images" / "eval_0001.png").write_bytes(_png_bytes(grey=0x10))

    assert evaluation_cli(["validate", str(root)]) == 1
    assert "does not match the manifest digest" in capsys.readouterr().err


def test_the_validate_command_says_so_when_the_set_measures_nothing(tmp_path, capsys):
    """"Validated" on an empty set is the sentence that gets misremembered."""
    root = tmp_path / "empty"
    root.mkdir()
    (root / "MANIFEST.json").write_text(
        json.dumps(
            {"dataset_version": "v1", "created_on": "2026-01-15", "samples": []}
        ),
        encoding="utf-8",
    )

    assert evaluation_cli(["validate", str(root)]) == 0
    assert "can measure nothing yet" in capsys.readouterr().err


def test_evaluate_path_refuses_an_unusable_dataset(dataset_root):
    root = dataset_root([])
    (root / "images" / "eval_0001.png").unlink()

    with pytest.raises(EvaluationDataError):
        evaluate_path(root, _pipeline(("x",)))


# --- the default paths, which nothing else here exercises --------------------
#
# Found in review: every test above injects `image_ref_factory`, and the CLI
# tests only ran `validate`. That left the two code paths production actually
# uses - the default `ImageRef` builder and the `run` command - executed by
# nothing. Both reach `labelextract.cli` through a *lazy* private import, so a
# rename there would have surfaced at runtime rather than in the suite.


def test_evaluate_builds_its_own_image_ref_when_none_is_injected(dataset_root):
    """The production path: no factory supplied, so the runner builds the ref.

    This is what exercises `_default_image_ref`, and with it the import of
    `labelextract.cli._image_ref`. It needs no OCR stack: the format comes from
    the file's magic bytes, and dimensions are optional metadata.
    """
    root = dataset_root(
        [{"key": "net_quantity", "state": "present_and_readable", "value": "500 g"}]
    )

    report = evaluate(
        load_dataset(root), _pipeline(("Net Quantity: 500 g",)), run_date="2026-02-01"
    )

    assert report.failures == (), f"the default image path failed: {report.failures}"
    quantity = next(
        item for item in report.as_dict()["scores"]["per_field"]
        if item["key"] == "net_quantity"
    )
    assert quantity["true_positive"] == 1


def test_the_run_command_writes_a_report(dataset_root, tmp_path, capsys):
    """The `run` subcommand end to end, including pipeline-version resolution.

    Exercises the second lazy private import, `_only_version_of` - a bare
    `--pipeline` must resolve to a registered version the same way
    `labelextract.cli` resolves it.
    """
    registry.register_pipeline(
        "evaluation-cli-test", _VERSION, lambda: _pipeline(("Net Quantity: 500 g",))
    )
    root = dataset_root(
        [{"key": "net_quantity", "state": "present_and_readable", "value": "500 g"}]
    )
    destination = tmp_path / "report.json"

    exit_code = evaluation_cli(
        ["run", str(root), "--pipeline", "evaluation-cli-test",
         "--report", str(destination)]
    )

    assert exit_code == 0
    body = json.loads(destination.read_text(encoding="utf-8"))
    assert body["dataset"]["dataset_version"] == "v1"
    assert body["engine"]["pipeline_name"] == "scripted"
    assert "wrote" in capsys.readouterr().out


def test_the_run_command_refuses_an_unknown_pipeline(dataset_root, capsys):
    root = dataset_root([])
    assert evaluation_cli(["run", str(root), "--pipeline", "no-such-engine"]) == 3
    assert capsys.readouterr().err.strip()


def test_the_run_command_refuses_a_tampered_dataset(dataset_root, capsys):
    """A run must not proceed on a set whose bytes no longer match the manifest."""
    root = dataset_root([])
    (root / "images" / "eval_0001.png").write_bytes(_png_bytes(grey=0x10))

    assert evaluation_cli(["run", str(root), "--pipeline", "null-engine"]) == 1
    assert "does not match the manifest digest" in capsys.readouterr().err
