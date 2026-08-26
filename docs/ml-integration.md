# Plugging in an OCR engine

How to add an engine without touching Django. Read
[`ml/README.md`](../ml/README.md) first for the package layout and for what the
engine that already ships does and does not do.

> **One engine is already implemented.** `ml/labelextract/ocr/tesseract.py`
> registers a `tesseract` / `0.1.0` pipeline: Pillow preprocessing, Tesseract 5
> recognition, deterministic field extraction. This document is now about adding
> a *second* engine alongside it - which is the point of a name-and-version
> registry: two engines can be registered at once and compared on the same
> images.
>
> The placeholder `null-engine` is still the shipped default and has not been
> removed. Selecting Tesseract is step 5 below.

## The contract

```
backend  ──imports──▶  labelextract
```

One direction only. `labelextract` never imports Django, never touches the
database, never sees an HTTP request. You can develop and test an OCR engine
with no database and no web server running.

The backend resolves engines **by name and version** through
`labelextract.registry`. The only backend module that imports `labelextract` at
all is `backend/apps/extraction/services/extraction_service.py`.

Consequence: adding a real engine changes files in `ml/` plus two settings
values. No Django code, no migration.

## Steps

### 1. Write the engine

Create `ml/labelextract/ocr/<your_engine>.py` and subclass `OcrEngine`.
`tesseract.py` is a worked example of everything below; this sketch is the shape
it has to take:

```python
from labelextract.contracts import BoundingBox, ImageRef, OcrResult, TextBlock
from labelextract.exceptions import EngineNotAvailableError, InvalidImageError
from labelextract.interfaces import OcrEngine


class TesseractOcrEngine(OcrEngine):
    name = "tesseract"
    version = "5.3.0"

    def warmup(self) -> None:
        # Load binaries/models here, not in __init__, so the cost is paid once
        # at startup rather than on a user's first upload.
        if not shutil.which("tesseract"):
            raise EngineNotAvailableError("tesseract binary not found on PATH")

    # Put the call into the engine itself behind a small injectable object -
    # `TesseractRunner` in the shipped engine. Everything worth testing (parsing,
    # grouping, confidence rescaling, error mapping) can then be exercised with a
    # deterministic fake and no binary installed, which is what keeps the suite
    # runnable on a fresh clone and offline.

    def recognise(self, image: ImageRef) -> OcrResult:
        ...
        return OcrResult(
            blocks=tuple(
                TextBlock(
                    text=word,
                    box=BoundingBox(x=x, y=y, width=w, height=h),
                    # If your engine reports no confidence, pass None.
                    # Do not substitute a number to fill the field.
                    confidence=conf,
                )
                for ...
            ),
            raw={"engine_output": ...},
        )
```

Rules that are not negotiable:

- **Never invent a confidence.** `None` means "this engine does not report
  one". A fabricated 0.95 propagates into a compliance result and makes a
  guess look like a measurement.
- **Return an empty `OcrResult` for an unreadable image.** That is a valid
  outcome, not an error. The pipeline turns it into `ExtractionStatus.EMPTY`,
  and the compliance engine correctly treats it as inconclusive rather than as
  a missing declaration.
- **Raise `InvalidImageError` / `EngineNotAvailableError`** for real failures.
  The pipeline catches `LabelExtractError` and records a failed run. Anything
  else propagates, because a bug in your engine should be loud rather than
  recorded as "this image was unreadable".
- **Leave `is_placeholder` alone.** It defaults to `False`, which is correct
  for a real engine.
- **Import your dependencies lazily**, inside the method that needs them, and
  raise `EngineNotAvailableError` on ImportError. That is what lets
  `labelextract` install with no dependencies, the registry list every pipeline,
  and the whole test suite run on a machine with no OCR stack at all.
- **Validate anything that reaches a subprocess.** `TesseractOptions` accepts
  only ISO-639-style language codes for exactly this reason, and a test asserts
  it.

### 1b. Preprocessing is a separate stage, with a lifecycle

`ImagePreprocessor.process()` returns a *new* `ImageRef`; the original is
evidence and must never be overwritten. Implement `release()` if you write an
intermediate to disk - the pipeline calls it in a `finally`, on the success
path, the recorded-failure path and the re-raised-bug path alike, so a
long-running server does not accumulate a copy of every upload.

`release()` must never raise, and must refuse to delete a path outside the
directory it owns.

Any transform that **resizes** moves bounding boxes into preprocessed-image
space. `ExtractionPipeline` records `source_dimensions` and
`preprocessed_dimensions` in run metadata so that is detectable rather than a
silent mismatch between an evidence overlay and the photograph under it.

### 2. Write the field extractor

`OcrEngine` reports characters. `FieldExtractor` decides what they mean.

`ml/labelextract/fields/` already contains one: keyword-anchored patterns,
English, covering a documented subset of `LabelFieldKey`. Reuse it unless your
engine returns something structurally different.

```python
from labelextract.contracts import ExtractedField, LabelFieldKey
from labelextract.interfaces import FieldExtractor


class RegexFieldExtractor(FieldExtractor):
    name = "regex-fields"
    version = "0.1.0"

    def extract(self, ocr, image) -> tuple[ExtractedField, ...]:
        ...
```

**Mark ambiguity instead of resolving it.** When a value has more than one valid
reading, emit the field with `normalized_value["uncertain"] = True`, list the
`candidates`, and omit the structured key you could not commit to. A guess
presented as a value cannot later be told apart from a measurement. The
normalisation rules are in [`ml/README.md`](../ml/README.md).

**Never emit a field you did not actually locate.** A missing declaration is
meaningful input to the compliance engine; inventing one to "complete the set"
silently turns a non-compliant package into a compliant one.

`LabelFieldKey` is a vocabulary of what appears on packaging. Adding a key
means "we can now read this off a package". It never means "this is required" —
that claim only ever comes from a verified rule.

### 3. Register it

In `ml/labelextract/registry.py`:

```python
def _register_builtin_pipelines() -> None:
    from labelextract.baseline import null_engine
    from labelextract.ocr import tesseract, your_engine

    register_pipeline(null_engine.NAME, null_engine.VERSION,
                      null_engine.build_pipeline)
    register_pipeline(tesseract.NAME, tesseract.VERSION,
                      tesseract.build_pipeline)
    register_pipeline(your_engine.NAME, your_engine.VERSION,
                      your_engine.build_pipeline)
```

Import the *module*, not its runtime. The factory resolves Pillow, pytesseract
or your framework when it is first called, so registration itself costs nothing
and never fails on a machine without them.

### 4. Declare dependencies

Add them to the **`[ocr]` optional extra** in `ml/pyproject.toml`, pinned to a
compatible minor range - not to `dependencies`, and not to
`backend/requirements.txt`. Keeping them optional is what lets CI, the health
endpoint and the test suite run without them.

```bash
pip install -e "./ml[ocr]"
```

A large OCR or ML framework is a team decision - it affects install time and
disk for all six people. Raise it before installing it. That constraint is the
main reason the first engine is Tesseract rather than a neural one.

### 5. Switch the backend over

In `.env`:

```
DEFAULT_EXTRACTION_ENGINE_NAME=tesseract
DEFAULT_EXTRACTION_ENGINE_VERSION=0.1.0
```

The version here is the **pipeline's**, not the Tesseract binary's. The binary's
version is recorded per run in `ExtractionRun.raw_output`, where it belongs: the
pipeline version means "this combination of preprocessing, engine settings and
patterns", which is what makes two runs comparable.

That is the whole backend change. `/api/v1/health/` will then report
`is_placeholder: false`, and the UI's "no OCR engine is installed" notice
disappears on its own.

### 6. Test it

```bash
cd ml && pytest
```

Use a fixture built in code, never a downloaded dataset, and **never make the
suite depend on your engine being installed**. Inject a fake for the engine call
and test your own parsing exhaustively; guard the one real end-to-end smoke test
with `pytest.importorskip` plus a capability check, as
`ml/tests/test_ocr_tesseract.py` does.

Mirror the existing tests in `ml/tests/test_pipeline.py` - particularly the ones
asserting that an unreadable image is not reported as readable.

Then confirm the integration end to end:

```bash
cd backend && pytest apps/extraction
```

## Versioning

`ExtractionRun` stores `engine_name` and `engine_version` as plain text. Old
runs stay interpretable after you upgrade, and results are never coupled to
whichever engine happens to be current.

Bump `version` when behaviour changes — new weights, new preprocessing, a
different threshold. Register the new version alongside the old rather than
mutating it, so a comparison across versions is possible.

## Model artifacts

The Tesseract pipeline has **no artifacts at all**: language data is installed
by the operating system's package manager into a system directory, so there is
nothing to download, checksum or version. What follows applies to an engine that
ships weights, not to that one.

**Never commit weights.** `.gitignore` blocks `*.pt`, `*.onnx`, `*.h5`,
`*.traineddata`, `ml/artifacts/`, `ml/models/`, `ml/data/`. A 200 MB file in
Git history is in every clone forever.

Intended strategy, to be finalised by whoever lands the first real model:

- Weights download on demand into git-ignored `ml/artifacts/`.
- A small committed manifest records URL, version and SHA-256.
- `warmup()` verifies the checksum before loading and raises
  `EngineNotAvailableError` if the artifact is absent.
- Training datasets never enter this repository.

## Reporting performance honestly

When you publish accuracy, character error rate, or field-extraction F1:

- State the dataset, its size, and how it was collected.
- Use a held-out test set the model never saw during development.
- Report where it fails — unusual fonts, low light, reflective packaging,
  multilingual labels, curved surfaces.
- Never quote a figure from a paper or a vendor as if it were measured on our
  data.

No OCR system reads every packaging format correctly. Saying so is not a
weakness in a demonstration; a specific, honest failure mode is more credible
than a round number with no provenance.
