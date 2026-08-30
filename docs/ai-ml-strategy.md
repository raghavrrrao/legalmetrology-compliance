# AI/ML strategy

The single most important sentence in this document:

> **AI decides what the package *says*. Verified rules decide whether that is
> *compliant*.**

Everything below follows from that division. It is not a stylistic preference —
it is what makes the system's output defensible. An extraction mistake produces
a wrong reading that a human can see and correct against the photograph. A
model deciding legality produces a confident legal claim nobody can audit.

## What AI does

| Responsibility | Status | Implementation |
|---|---|---|
| Image preprocessing (orientation, grayscale, contrast) | **Implemented** | `ml/labelextract/preprocessing/` — Pillow |
| Image preprocessing (deskew, perspective) | Not implemented; stated as a limitation | needs numpy/OpenCV |
| OCR — recognise characters and their position | **Implemented** | `ml/labelextract/ocr/` — Tesseract 5 via pytesseract |
| Field extraction — map recognised text to declarations | **Implemented, English, partial** | `ml/labelextract/fields/` — deterministic patterns |
| Product/category classification | Not started; no interface yet | `feature/product-classification` |

These are **perception** tasks. They answer "what is printed here, and where?"

The placeholder `null-engine` has not been removed and is still the shipped
default. Switching to Tesseract is a deliberate two-line `.env` change made
once the binary is installed — never a silent default that fails on a
teammate's first upload. Both pipelines stay registered, and `ExtractionRun`
records which one produced each result.

Everything the OCR layer promises, refuses, and cannot yet do is set out in
[`../ml/README.md`](../ml/README.md), including the full list of declarations
that are **not** extracted.

## What AI does not do

- **It does not decide compliance.** No model output can create a violation.
  Violations come from a `ComplianceRule` row whose legal text a named person
  verified against the authoritative source.
- **It does not interpret the law.** No LLM is asked "is this package legal?"
  There is no LLM in this system at all. The extraction layer is Tesseract plus
  deterministic regular expressions — every decision it makes is one a person
  can read in the source and disagree with.
- **It does not fill in missing declarations.** A field extractor that did not
  find a declaration reports nothing. Inventing one to complete a set would
  silently turn a non-compliant package into a compliant one.
- **It does not override `REVIEW_REQUIRED`.** When evidence is insufficient,
  the answer is "a human must look at this", and no confidence score changes
  that.

### If an LLM is added later

It may only be used for perception-adjacent work — normalising messy OCR text,
suggesting which `LabelFieldKey` a string looks like. Its output must land in
`ExtractedLabelField` as an *observation with a source*, never as a compliance
verdict. It must never be given the rule text and asked to judge. If that
constraint is ever relaxed, the guarantees in
`backend/apps/compliance/tests/test_engine.py` are what will break, and they
should be treated as the thing protecting the project, not an obstacle.

## The boundary in code

```
backend  ──imports──▶  labelextract        (one direction, enforced by layout)
```

`ml/labelextract` never imports Django. The only backend module that runs an
engine is `backend/apps/extraction/services/extraction_service.py`; the
dependency-free `labelextract.contracts` vocabulary is also imported by
`backend/apps/rules/checks/field_presence.py`, so a rule and a reading name a
field identically. Engines are
resolved by name and version through a registry, so swapping OCR
implementations is a settings change plus a registration — no backend code, no
migration.

See [ml-integration.md](ml-integration.md) for how to add an engine.

## Confidence and uncertainty

Rules the contracts enforce structurally, not by convention:

- **Confidence is `Optional` everywhere.** `TextBlock.confidence`,
  `ExtractedField.confidence` and `ExtractedLabelField.confidence` all default
  to `None` and are nullable in the database.
- **`None` means "this engine does not report confidence".** It never means
  zero, and it never means certainty. Any code that treats `None` as a number
  is a bug.
- **Values are range-checked.** `contracts._check_unit_interval` rejects
  anything outside `[0.0, 1.0]` at construction time, so an engine reporting a
  percentage by mistake fails immediately rather than silently skewing results.
- **Confidence is not comparable across engines.** Two engines' 0.8 mean
  different things. Never threshold on it without calibrating that engine.
  Tesseract's 0–100 score is rescaled to `[0, 1]` at the adapter boundary and
  its `-1` sentinel becomes `None`, never `0.0`.
- **Low-confidence words are kept, not filtered.** Discarding them would hide
  exactly the misreadings a reviewer needs to see. The confidence travels with
  the block instead.

### Uncertainty of *interpretation* is a separate axis

`confidence` is the OCR engine's opinion of the **characters**. It says nothing
about whether we read the right *meaning* into them. So every value the field
extractor normalises carries its own flag:

```json
{ "uncertain": true,
  "uncertainty_reasons": ["both DD/MM and MM/DD are valid readings of this date"],
  "candidates": ["2025-04-03", "2025-03-04"] }
```

A perfectly recognised `03/04/2025` is high-confidence and uncertain at the same
time. Committing to 3 April because that is the Indian convention would produce
a date that looks measured, flows into a compliance finding, and cannot later be
told apart from one that was genuinely unambiguous. When a value cannot be
committed to, the structured key is **absent** rather than present-and-wrong.

Uncertainty survives into `ExtractedLabelField.normalized_value` unflattened,
and a backend test asserts it — if it were lost at the persistence layer, an
ambiguous date would reach the UI looking exactly like a confident one.

### The placeholder is labelled at every layer

`null-engine` reads no pixels and returns nothing. `is_placeholder=True`
travels from the ML contract → `ExtractionRun.is_placeholder` → the health API
→ a visible notice in the UI. It is asserted at each layer by a test, so the
label cannot be lost in the middle.

## Three-valued outcomes, everywhere

The system distinguishes:

| | Meaning |
|---|---|
| Extraction `COMPLETED` | Text was read. An absent declaration is evidence. |
| Extraction `EMPTY` | Nothing readable. An absent declaration is **not** evidence. |
| Extraction `FAILED` | The pipeline could not run at all. |

A blurred photograph must never be reported as a missing declaration. That is
the difference between telling a user "your package is illegal" and "retake the
photo", and it is enforced in `apps/rules/checks/field_presence.py` and tested
in `test_engine.py::test_unreadable_image_is_never_reported_as_a_missing_declaration`.

## Precision over recall, and why that direction

The field extractor reports most declarations **only when an anchoring keyword
is present**. A bare `500 g` is not reported as a net quantity, because that
string also appears in the nutrition panel beside `per 100 g`.

This costs recall, deliberately. A declaration wrongly reported as *present*
makes `field_presence` PASS and hides a real violation. A declaration we fail to
find produces a review flag. The second failure is recoverable by a human; the
first is invisible. See [evaluation-strategy.md](evaluation-strategy.md).

## Metrics

**Field extraction and operational metrics have been measured once; the rest
have not.** Published values, with their dataset, size and date, live in
[evaluation-results.md](evaluation-results.md) and nowhere else. See
[evaluation-strategy.md](evaluation-strategy.md) for the method.

| Metric | Status |
|---|---|
| OCR: character error rate, word error rate | **Not measured.** No hand transcription exists; the harness reports them unavailable rather than estimating them |
| Field extraction: per-field precision, recall, F1 | **Measured** on `our-eval-v0.1-draft` (28 images, 10 products, 2026-08-29): micro precision 0.944, recall 0.205, F1 0.337 |
| Uncertainty: uncertain rate, uncertainty precision, silent error rate | **Measured**: 0.500, 0.429, 0.455 |
| Classification: per-category accuracy, confusion matrix | **Not measured.** No classifier exists |
| End-to-end: agreement with a human reviewer's compliance determination | **Not measured**, and out of reach until verified `ComplianceRule` rows exist. Nothing measured so far touches compliance |
| Operational: processing time per image, failure rate, `REVIEW_REQUIRED` rate | **Partly measured**: median 2202 ms per image, 0 crashes in 28, 2 of 28 `empty`. `REVIEW_REQUIRED` is a compliance-engine outcome and is not measured |

The measured figures carry three caveats that must travel with them: the ground
truth was drafted by a model and is **not yet human-verified**; N is 28, from 10
products, four sharing one back-of-pack template; and the run had `eng` language
data only. The number most worth attention is not the 0.944 precision but the
0.455 silent error rate — nearly half of the readings the pipeline offered
without hedging were wrong — and the fact that it correctly reported **zero** of
23 present-but-unreadable declarations as unread.

## Known limitations to state openly

These are properties of the problem, not gaps to be apologised for. Stating
them is more credible than a round number with no provenance:

- **No OCR system reads every packaging format.** Reflective foil, curved
  surfaces, low contrast, decorative fonts and multilingual labels all degrade
  recognition.
- **Indian packaging is multilingual.** English, Hindi and regional scripts
  frequently appear on the same panel. Tesseract recognises Devanagari when
  `tesseract-ocr-hin` is installed, but **the field extractor matches English
  only** — so a Hindi-only declaration is recognised as text and then not
  interpreted.
- **Several declarations are not extracted at all.** Product and brand name,
  generic name and manufacturer address need layout understanding this layer
  does not have. The unsupported list is derived from the code, not maintained
  by hand, so it cannot drift.
- **Tesseract is weaker than the neural engines on hard packaging** — foil,
  curved surfaces, decorative type. It was chosen for being free, offline,
  weightless and installable by six people on three operating systems, with the
  intention of measuring it and adding a second engine alongside if the numbers
  justify one.
- **One photograph shows one panel.** A declaration absent from a front-panel
  photo may be printed on the back. `ProductImage.view_type` exists so the
  engine can reason about this rather than reporting a framing choice as a
  violation.
- **Extraction confidence is not compliance confidence.** Reading "500 g"
  correctly says nothing about whether 500 g was declared correctly.
- **The system assists a reviewer. It does not certify compliance**, and it is
  not authoritative merely because it is automated.
