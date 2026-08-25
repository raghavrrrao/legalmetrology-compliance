# Plugging in a real OCR engine

How to replace the placeholder without touching Django. Read
[`ml/README.md`](../ml/README.md) first for the package layout.

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

Create `ml/labelextract/tesseract/` (or whatever you are using) and subclass
`OcrEngine`:

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

### 2. Write the field extractor

`OcrEngine` reports characters. `FieldExtractor` decides what they mean.

```python
from labelextract.contracts import ExtractedField, LabelFieldKey
from labelextract.interfaces import FieldExtractor


class RegexFieldExtractor(FieldExtractor):
    name = "regex-fields"
    version = "0.1.0"

    def extract(self, ocr, image) -> tuple[ExtractedField, ...]:
        ...
```

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
    from labelextract.tesseract import build_pipeline as build_tesseract

    register_pipeline(null_engine.NAME, null_engine.VERSION,
                      null_engine.build_pipeline)
    register_pipeline("tesseract", "5.3.0", build_tesseract)
```

### 4. Declare dependencies

Add them to **both** `ml/pyproject.toml` and `backend/requirements.txt`, pinned
to a compatible minor range.

A large OCR or ML framework is a team decision — it affects install time and
disk for all six people. Raise it before installing it.

### 5. Switch the backend over

In `.env`:

```
DEFAULT_EXTRACTION_ENGINE_NAME=tesseract
DEFAULT_EXTRACTION_ENGINE_VERSION=5.3.0
```

That is the whole backend change. `/api/v1/health/` will then report
`is_placeholder: false`, and the UI's "no OCR engine is installed" notice
disappears on its own.

### 6. Test it

```bash
cd ml && pytest
```

Use a small committed fixture image, never a downloaded dataset. Mirror the
existing tests in `ml/tests/test_pipeline.py` — particularly the ones asserting
that an unreadable image is not reported as readable.

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
