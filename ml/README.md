# `labelextract` — the OCR / label-extraction package

The perception layer. It answers **"what is printed on this package, and
where?"** and nothing else.

> It never decides compliance. Locating a net quantity says nothing about
> whether one was required, or whether the declared value is correct. Both of
> those come from verified `ComplianceRule` rows in
> [`rules/`](../rules/README.md), evaluated by a deterministic engine that
> never asks a model anything. See
> [`docs/ai-ml-strategy.md`](../docs/ai-ml-strategy.md).

---

## PROBLEM

Given a photograph of a packaged commodity, produce a structured, auditable
record of the label declarations printed on it — with the evidence attached, so
a human reviewer can check every reading against the image.

## INPUT

A `labelextract.contracts.ImageRef`: a readable path plus the facts the caller
measured about the file (format, byte size, pixel dimensions).

- Formats: JPEG, PNG, WebP — the same allowlist
  `backend/apps/images/constants.py` enforces at upload, asserted equal by a
  backend test.
- Budget: 10 MB and 50 MP by default, matching the backend's settings and
  re-checked inside `ml/` because this package is also callable from a CLI with
  no Django in front of it.

## OUTPUT

A `labelextract.contracts.ExtractionResult`:

| Part | What it carries |
|---|---|
| `status` | `COMPLETED` / `EMPTY` / `FAILED` — three-valued on purpose |
| `ocr.blocks` | One `TextBlock` per recognised **line**: text, bounding box, confidence |
| `ocr.raw` | Verbatim engine diagnostics, including every word, so extraction can be re-run without re-running OCR |
| `fields` | `ExtractedField` per declaration found: raw reading, structured value, confidence, box |
| `error_code` | A stable string the frontend branches on, set when `FAILED` |
| `metadata` | Which components ran, source and preprocessed dimensions, timings |

`EMPTY` is not an error. It means "we read the image and recognised nothing
usable" — a blurred or blank photograph. The compliance engine treats it as
*inconclusive*, never as a missing declaration. That distinction is the
difference between telling a user "retake the photo" and telling them their
product is illegal.

## MODEL / OCR ENGINE

**Tesseract 5**, via [`pytesseract`](https://pypi.org/project/pytesseract/),
behind `interfaces.OcrEngine`.

Chosen against PaddleOCR, EasyOCR and docTR on this project's actual
constraints:

- **Free, offline, no account, no API key.** An uploaded label never leaves the
  machine, and there is no credential to leak or commit.
- **No model weights in the repository.** Language data is installed by the OS
  package manager into a system directory. Nothing downloads at runtime,
  nothing needs checksumming, nothing can end up in Git.
- **Per-word confidence and geometry.** The contracts carry
  `TextBlock.confidence` and `BoundingBox` so the UI can show *where on the
  package* a declaration was read. An engine returning a bare string would
  leave both permanently `None`.
- **Devanagari is `apt install tesseract-ocr-hin`**, not a research project.
  Indian labels are routinely bilingual.
- **Installs in minutes on Windows, macOS and Linux.** Six people, mixed
  operating systems, a hackathon timeline.

**The honest trade-off:** Tesseract is weaker than the neural engines on curved
surfaces, reflective foil, low contrast and decorative type — which describes
most retail packaging photographed by hand. The plan is to measure that and, if
the numbers justify it, register a second engine *alongside* this one rather
than replacing it. `registry` is keyed by name and version precisely so two
engines can be compared on the same images.

**No accuracy, CER, WER or F1 figure for this engine appears anywhere in this
repository, because none has been measured on our data.**

The engine is swappable without touching Django: `extraction_service.py` is the
only backend module that imports `labelextract`, and it resolves pipelines by
name and version. See [`docs/ml-integration.md`](../docs/ml-integration.md).

## PREPROCESSING

`preprocessing/pillow_preprocessor.py`, behind `interfaces.ImagePreprocessor`.
Pillow rather than OpenCV: it is already a backend dependency, so this stage
adds no install for anyone, and OpenCV's extra transforms are ones we cannot
yet show are an improvement.

Applied by default — all geometry-preserving except the rotation:

1. **EXIF orientation.** Phone cameras store a landscape frame plus a rotation
   tag. Tesseract reads pixels and ignores the tag, so a portrait photo arrives
   sideways and recognition collapses. This is the transform that justifies the
   stage existing.
2. **Grayscale.** Colour carries nothing for recognition.
3. **Contrast normalisation** (`autocontrast`, 1% cut-off each end), so one
   specular highlight cannot define "white" for the whole panel.

Available and **off by default**, each for a stated reason:

| Setting | Why it is off |
|---|---|
| `denoise` | A median filter erases the strokes of 6-point print — the size at which net quantity and batch number are printed |
| `max_dimension` / `min_dimension` | Resizing moves bounding boxes into preprocessed-image space, and nothing yet maps them back onto the original for the evidence overlay. The pipeline records both dimension sets in metadata so this is detectable, not silent |

Not implemented: **deskew and perspective correction.** Genuinely useful for
hand-held photos of curved packaging, and not implementable well without
numpy/OpenCV. Stated as a limitation rather than approximated badly.

Intermediates are written to a directory the preprocessor owns and deleted by
`release()` as soon as the pipeline is done. The original is never modified —
it is the evidence a disputed finding is checked against.

## FIELD EXTRACTION

`fields/rule_based.py`, behind `interfaces.FieldExtractor`. Deterministic
keyword-anchored patterns, English only.

Patterns rather than a model, deliberately: a regex is inspectable and
testable, and when it is wrong a person can read it and fix it. A learned
tagger would need annotated Indian label data we do not have, and its mistakes
would be unexplainable in a tool whose output is meant to be evidence.

### Supported today

| Declaration | `LabelFieldKey` | Normalised to |
|---|---|---|
| Net quantity | `net_quantity` | `{quantity, unit, base_quantity, base_unit, measure, pack_count?}` |
| MRP / retail sale price | `retail_sale_price` | `{amount (exact decimal string), currency, inclusive_of_all_taxes?}` — read from the text the MRP keyword introduces, skipping quantities |
| Batch / lot number | `batch_number` | `{batch_number}` |
| Date of manufacture | `date_of_manufacture` | `{date}` or `{year_month}` |
| Date of packing | `date_of_packing` | `{date}` or `{year_month}` |
| Date of import | `date_of_import` | `{date}` or `{year_month}` |
| Best before / use by / expiry | `best_before` | `{date}`, `{year_month}`, or `{duration_value, duration_unit}` |
| Consumer care contact | `consumer_care_contact` | `{emails[], phones[]}` |
| Country of origin | `country_of_origin` | `{country_text}` — certain only from an explicit "Country of Origin" declaration |
| Manufacturer name | `manufacturer_name` | `{name}` — always flagged uncertain |
| Packer name | `packer_name` | `{name}` — always flagged uncertain |
| Importer name | `importer_name` | `{name}` — always flagged uncertain |
| "Marketed by" | `other` | `{name, declaration: "marketed_by"}` |

### NOT supported — do not claim otherwise

| Declaration | Why not |
|---|---|
| **Product / brand name** | No reliable textual anchor. It is the largest text on the front panel, which is a *layout* signal this layer does not have |
| **Common or generic name** (`common_or_generic_name`) | Same problem |
| **Manufacturer address** (`manufacturer_address`) | Spans several lines below the name; needs real layout analysis |
| **Unit sale price** (`unit_sale_price`) | Detected only well enough to *exclude* it from MRP matches |
| Any non-English text | Tesseract recognises Devanagari when `tesseract-ocr-hin` is installed; no pattern here matches it |

`SUPPORTED_KEYS` and `UNSUPPORTED_KEYS` are exported from
`labelextract.fields`, and `UNSUPPORTED_KEYS` is *derived* from the full
vocabulary rather than maintained by hand — so this table cannot silently drift
away from the code. A test asserts the two partition `LabelFieldKey`.

### Precision over recall, on purpose

Most declarations are matched **only when an anchoring keyword is present**. A
bare `500 g` is not reported as a net quantity, because that string also
appears in the nutrition panel next to `per 100 g`.

The reasoning is in
[`docs/evaluation-strategy.md`](../docs/evaluation-strategy.md): a declaration
we wrongly report as *present* makes `field_presence` PASS and hides a real
violation. A declaration we fail to find produces a review flag. The second
failure is recoverable; the first is not. `RuleBasedFieldExtractor(
require_net_quantity_keyword=False)` trades it back explicitly, and marks
everything it gains as uncertain.

### NORMALISATION

**May change presentation. May never change meaning, and may never resolve an
ambiguity by guessing.**

- Whitespace collapsed, Unicode folded to NFKC. **OCR confusions are not
  repaired** — turning `5OO` into `500` would produce a value indistinguishable
  from a correct reading, and the reviewer would lose the only signal that
  anything was wrong.
- Quantities convert to an exact base unit (grams, millilitres). Mass is never
  converted to volume: 500 ml of oil does not weigh 500 g.
- Prices are carried as **exact decimal strings**, never floats. A price that
  drifts by a paise is a defect in a system whose job is checking declarations.
- Dates: `25/12/2025` is unambiguous. `03/04/2025` is not, and comes back with
  `uncertain: true` and both candidates rather than a guess at the Indian
  convention.

### What is flagged uncertain, and what is not emitted at all

Three outcomes, not two, because "we are unsure of this value" and "this is not
a declaration" are different answers:

| Situation | Outcome |
|---|---|
| `Country of Origin: India` | emitted, certain — nothing else is phrased this way |
| `Made in India` | emitted, **uncertain** — the same wording introduces a manufacturing town |
| `Made in a facility that also processes nuts` | **not emitted** — it is prose, not a declaration |
| `MRP for 500 g pack: 250` | emitted as `250`; the quantity is skipped, never taken as the price |
| `MRP incl. of all taxes` (price on another line) | **not emitted** — no guess is made |
| `Best Before 25/12/2026` | emitted, certain |
| `Best Before` / `25/12/2026` on two lines | emitted, **uncertain** — adjacency is an inference, not a reading |

The distinction between "uncertain" and "not emitted" is deliberate and load
bearing: **`field_presence` PASSES on any extracted field regardless of its
uncertainty flag.** So text that is not a declaration must produce no field at
all — emitting it as uncertain would still record a package as having declared
something it never declared. Uncertainty is for a declaration we found but
cannot fully interpret; absence is for something that was never there.
- Shelf life stays a duration. `best before 9 months` is not turned into a
  date; computing one needs a packing date the reading does not contain.

Every normalised mapping carries `uncertain: bool`, plus
`uncertainty_reasons` and often `candidates` when it is true. Structured keys
are **absent** when a value could not be committed to, rather than
present-and-wrong — so consumers must use `.get()` and read absence as "not
determined".

`uncertain` is about *interpretation*. `confidence` is the OCR engine's opinion
of the *characters*. They are different axes: a perfectly recognised
`03/04/2025` is high-confidence and uncertain at once.

## DATA

**No dataset, model weight, or label photograph is committed to this
repository, and none is downloaded at runtime.** `.gitignore` blocks
`ml/data/`, `ml/models/`, `ml/artifacts/` and every common weight extension.

Tesseract's language data is installed by the OS package manager. There is
nothing for this project to host, checksum or version.

Datasets for evaluation are described in
[`docs/data-strategy.md`](../docs/data-strategy.md), which distinguishes four
kinds that must not be conflated: general OCR datasets, packaging/product-label
datasets, Indian/multilingual label datasets, and our own annotated evaluation
set. **A generic scene-text dataset is not a Legal Metrology dataset**, and a
number measured on one says nothing about performance on the other.

## METRICS

**Nothing has been measured. No figure appears anywhere in this repository.**
[`docs/evaluation-strategy.md`](../docs/evaluation-strategy.md) defines what
will be measured — CER, WER, per-field precision/recall/F1, uncertainty
calibration, and latency — and the method.

## LATENCY

`ExtractionRun.processing_ms` and `ExtractionResult.processing_ms` are recorded
on every run, so timing data accumulates from the first real run with no extra
instrumentation. **No latency figure has been measured**, so none is quoted.

What is *known* rather than measured: `TesseractOptions.timeout_seconds`
(default 30) caps a single recognition, so an unbounded run cannot become a
denial of service.

## HARDWARE

CPU only. No GPU, no CUDA, no accelerator. Tesseract's LSTM recogniser runs on
the CPU, and nothing in this package loads a deep-learning runtime.

Requirements are those of the Django backend plus the Tesseract binary and its
language data — a few tens of megabytes on disk. This runs on a laptop.

## LIMITATIONS

Stated because a specific, honest failure mode is more credible than a round
number with no provenance:

- **No OCR system reads every packaging format.** Reflective foil, curved
  surfaces, low contrast, decorative fonts and small print all degrade
  recognition, and Tesseract more than the neural engines.
- **English only at the extraction layer.** Recognition handles Devanagari when
  the language data is installed; no pattern matches non-English declarations.
- **No layout understanding.** Multi-line addresses, values in a column beside
  their label, and declarations wrapped mid-line are missed.
- **One photograph shows one panel.** A declaration absent from a front-panel
  photo may be printed on the back. `ProductImage.view_type` exists so this can
  be reasoned about rather than reported as a violation.
- **Bounding boxes are in source-image space only while resizing is off** (the
  default). Turn on `max_dimension`/`min_dimension` and they move into
  preprocessed space; run metadata makes that detectable.
- **Extraction confidence is not compliance confidence.** Reading `500 g`
  correctly says nothing about whether 500 g was declared correctly.
- **The system assists a reviewer. It does not certify compliance.**

## INTEGRATION

```
backend  ──imports──▶  labelextract        (one direction, enforced by layout)
```

`labelextract` never imports Django, never touches the database, never sees an
HTTP request. The only backend module that imports it is
`backend/apps/extraction/services/extraction_service.py`, which resolves
pipelines by name and version through `registry`.

Switching engines is two values in `.env` and no code change:

```
DEFAULT_EXTRACTION_ENGINE_NAME=tesseract
DEFAULT_EXTRACTION_ENGINE_VERSION=0.1.0
```

`/api/v1/health/` then reports `is_placeholder: false` and the UI's "no OCR
engine is installed" notice disappears on its own.

---

## Package layout

```
ml/
├── pyproject.toml            no required dependencies; [ocr] extra for engines
├── labelextract/
│   ├── contracts.py          the stable data boundary
│   ├── interfaces.py         ImagePreprocessor / OcrEngine / FieldExtractor
│   ├── exceptions.py         stable error codes the frontend branches on
│   ├── pipeline.py           stage ordering and failure policy
│   ├── registry.py           name+version → pipeline
│   ├── cli.py                run a pipeline over one local image
│   ├── baseline/             the null engine (placeholder, reads no pixels)
│   ├── preprocessing/        Pillow preparation
│   ├── ocr/                  Tesseract adapter
│   └── fields/               patterns, normalisation, the rule-based extractor
└── tests/
```

## Install

The contracts install with **no dependencies at all**, which is what lets the
whole test suite run on a machine with no OCR stack:

```bash
pip install -e ./ml
```

To actually run OCR, add the Python extra **and** the Tesseract binary:

```bash
pip install -e "./ml[ocr]"
```

| Platform | Binary |
|---|---|
| Windows | [UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki). Tick the languages you want. It does **not** add itself to `PATH` — either add `C:\Program Files\Tesseract-OCR` yourself, or pass the path to `PytesseractRunner(tesseract_cmd=...)` |
| macOS | `brew install tesseract tesseract-lang` |
| Debian / Ubuntu | `sudo apt install tesseract-ocr tesseract-ocr-hin` |

Confirm it:

```bash
tesseract --version
```

## Run OCR locally

Straight from a file, no database and no web server:

```bash
python -m labelextract.cli path/to/label.jpg
python -m labelextract.cli label.jpg --languages eng+hin
python -m labelextract.cli label.jpg --raw          # include every word
python -m labelextract.cli label.jpg --pipeline null-engine
```

Exit codes: `0` completed, `1` empty, `2` failed, `3` bad arguments.

Through Django, once `.env` selects the engine:

```bash
python backend/manage.py shell
>>> from apps.images.models import ProductImage
>>> from apps.extraction.services import extraction_service
>>> run = extraction_service.run_extraction(ProductImage.objects.first())
>>> run.status, run.recognised_text[:200]
```

## Tests

```bash
cd ml && pytest                       # contracts, preprocessing, OCR, fields, CLI
cd backend && pytest apps/extraction  # the Django seam
```

**No test requires Tesseract, network access, or a downloaded dataset.** The
OCR adapter is tested through an injected fake runner, and field extraction is
given text directly — so the suite measures *our* logic rather than someone
else's recognition, and runs identically on a fresh clone. One smoke test
exercises the real binary and skips when it is absent.

## Adding an engine

See [`docs/ml-integration.md`](../docs/ml-integration.md). In short: implement
`OcrEngine`, register a factory in `registry._register_builtin_pipelines()`,
declare dependencies in the `[ocr]` extra, and import them lazily so a missing
one surfaces as `EngineNotAvailableError` rather than an ImportError at
startup.

Bump the pipeline `VERSION` whenever a change makes two runs incomparable —
different settings, different preprocessing, different patterns. Register the
new version *alongside* the old rather than mutating it, so a comparison across
versions is possible. `ExtractionRun` stores both name and version as plain
text, so old runs stay interpretable for ever.
