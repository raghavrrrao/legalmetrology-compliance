# AI/ML strategy

The single most important sentence in this document:

> **AI decides what the package *says*. Verified rules decide whether that is
> *compliant*.**

Everything below follows from that division. It is not a stylistic preference —
it is what makes the system's output defensible. An extraction mistake produces
a wrong reading that a human can see and correct against the photograph. A
model deciding legality produces a confident legal claim nobody can audit.

## What AI does

| Responsibility | Status | Owner |
|---|---|---|
| Image preprocessing (deskew, denoise, contrast) | Interface defined, no implementation | `feature/image-processing` |
| OCR — recognise characters and their position | Interface defined, no implementation | `feature/ocr-processing` |
| Field extraction — map recognised text to declarations | Interface defined, no implementation | `feature/label-field-extraction` |
| Product/category classification | Not started; no interface yet | `feature/product-classification` |

These are **perception** tasks. They answer "what is printed here, and where?"

## What AI does not do

- **It does not decide compliance.** No model output can create a violation.
  Violations come from a `ComplianceRule` row whose legal text a named person
  verified against the authoritative source.
- **It does not interpret the law.** No LLM is asked "is this package legal?"
  There is no LLM in this system at all.
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

`ml/labelextract` never imports Django. The only backend module that imports it
is `backend/apps/extraction/services/extraction_service.py`. Engines are
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

## Metrics to be measured later

**No metric values exist yet, and none are published anywhere in this
repository.** The list below is what will be measured once a real engine lands,
not a claim about anything. See [evaluation-strategy.md](evaluation-strategy.md)
for how.

- OCR: character error rate, word error rate
- Field extraction: per-field precision, recall, F1
- Classification: per-category accuracy, confusion matrix
- End-to-end: agreement with a human reviewer's compliance determination
- Operational: processing time per image, failure rate, `REVIEW_REQUIRED` rate

## Known limitations to state openly

These are properties of the problem, not gaps to be apologised for. Stating
them is more credible than a round number with no provenance:

- **No OCR system reads every packaging format.** Reflective foil, curved
  surfaces, low contrast, decorative fonts and multilingual labels all degrade
  recognition.
- **Indian packaging is multilingual.** English, Hindi and regional scripts
  frequently appear on the same panel. Engine choice must account for this.
- **One photograph shows one panel.** A declaration absent from a front-panel
  photo may be printed on the back. `ProductImage.view_type` exists so the
  engine can reason about this rather than reporting a framing choice as a
  violation.
- **Extraction confidence is not compliance confidence.** Reading "500 g"
  correctly says nothing about whether 500 g was declared correctly.
- **The system assists a reviewer. It does not certify compliance**, and it is
  not authoritative merely because it is automated.
