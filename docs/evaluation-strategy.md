# Evaluation strategy

How this system will be measured once there is something to measure.

> **No metric values appear in this document, anywhere in this repository, or
> in any commit on this branch.** Every number below is a placeholder to be
> filled in by a measurement someone actually ran. A fabricated accuracy figure
> in a compliance tool is worse than no figure: it is a claim a user might act
> on.

## Why measure in layers

A single end-to-end accuracy number is close to useless here, because it cannot
tell you *what* to fix. If the system reports a wrong verdict, the cause is one
of: OCR misread the text, field extraction mislabelled it, the category was
wrong, or the rule was wrong. These have different owners and different fixes.
Measure each layer, then measure the whole.

```
image ──▶ OCR ──▶ field extraction ──▶ category ──▶ rules ──▶ verdict
          (1)          (2)               (3)         (4)       (5)
```

## 1. OCR performance

| Metric | Definition | Measured |
|---|---|---|
| Character error rate (CER) | `Levenshtein(hypothesis, reference) / len(reference)`, over the concatenated declarations, case-sensitive, whitespace-normalised | **Not measured** |
| Word error rate (WER) | The same at word level, after splitting on whitespace | **Not measured** |
| Text-region recall | Proportion of printed text regions detected (IoU ≥ 0.5 against an annotated box) | **Not measured** |

CER and WER are computed against **kind D** ground truth — our own annotated
Indian packaging — and never against a general scene-text corpus. See
[data-strategy.md](data-strategy.md) for why that distinction decides whether a
number means anything.

Both are computed on the **raw** OCR text, before normalisation. Normalising
first would measure the normaliser as well as the engine and hide the engine's
errors behind it.

Report **per condition**, not just an average — an average over easy and hard
images hides exactly the cases that matter:

- clean flat label vs. curved surface
- matte vs. reflective/foil packaging
- good light vs. low light / glare
- English only vs. multilingual panel
- large print vs. small print

## 2. Field extraction accuracy

Per `LabelFieldKey`, not aggregated. "85% overall" is meaningless when net
quantity is at 98% and consumer-care contact is at 40%.

| Metric | Definition |
|---|---|
| Precision | Of the declarations we reported, how many were correct |
| Recall | Of the declarations actually present, how many we found |
| F1 | Harmonic mean |
| Value accuracy | Of the declarations found, how many had the right *value* |

Report **only the keys the extractor actually attempts.** The unsupported list
is exported from the code as `labelextract.fields.UNSUPPORTED_KEYS`; including
those keys in an aggregate would produce a recall figure that is really a
measure of how many declarations we chose not to implement.

### Uncertainty must be scored separately, not averaged away

The extractor marks a reading `uncertain` when it cannot commit to an
interpretation — an ambiguous `03/04/2025`, two different MRPs on one label, a
company name that runs onto the next line. Scoring those as ordinary
predictions would reward guessing.

| Metric | Definition | Measured |
|---|---|---|
| Uncertain rate | Proportion of extracted fields flagged `uncertain` | **Not measured** |
| Uncertainty precision | Of the fields flagged uncertain, how many really were wrong or ambiguous | **Not measured** |
| Silent-error rate | Fields **not** flagged uncertain that were nonetheless wrong | **Not measured** |

The last one is the number that matters. A confident wrong reading is the
failure this whole design exists to avoid; an uncertain flag on a correct
reading merely costs a reviewer a glance.

**Precision and recall must be reported separately.** They fail in opposite
directions here: low recall means we miss declarations that exist (producing
false violations); low precision means we report declarations that are not
there (hiding real violations). For a compliance tool the second is worse.

## 3. Category classification

Per-category accuracy plus a confusion matrix. Category drives which rules
apply, so a misclassification silently changes the entire rule set applied to a
product — a failure mode that produces a confident, completely wrong result.

## 4. Compliance findings

Measured against a human reviewer's determination on the same images, not
against the system's own output.

| Metric | Definition | Why it matters |
|---|---|---|
| False positive | Flagged non-compliant, actually compliant | Wrongly accuses a manufacturer |
| False negative | Passed, actually non-compliant | Misses a real violation |
| `REVIEW_REQUIRED` rate | Proportion sent to a human | Too high = useless; too low = overconfident |
| Agreement rate | Verdict matches the reviewer | Overall usefulness |

### False positives and false negatives are not symmetric

State the trade-off explicitly rather than optimising a single number:

- A **false positive** tells someone their product breaks the law when it does
  not. That is a serious accusation from an automated tool.
- A **false negative** misses a violation — the status quo without the tool.

This system is deliberately biased toward `REVIEW_REQUIRED` over both. The
engine cannot return `COMPLIANT` without a verified rule actually passing, and
an unverified rule can never produce a violation. **A high
`REVIEW_REQUIRED` rate is the expected early result and should be reported as
such**, not tuned away by loosening those guarantees.

## 5. Operational metrics

| Metric | Definition | Measured |
|---|---|---|
| Processing time per image | Upload → verdict, wall clock | **Not measured** |
| OCR time | Time inside the extraction pipeline (`ExtractionRun.processing_ms`) | **Not measured** |
| Preprocessing time | Share of the above spent before recognition | **Not measured** |
| Extraction failure rate | Runs ending `FAILED`, broken down by `error_code` | **Not measured** |
| Empty extraction rate | Runs ending `EMPTY` (unreadable) | **Not measured** |

Report latency with the hardware and the image size. Tesseract is CPU-only, so
a number from a developer laptop and a number from a server are different
claims, and a 12 MP phone photo and a cropped panel are different workloads.

`ExtractionRun.processing_ms` and `ComplianceCheck.processing_ms` already
record timings, so this data accumulates from the first real run without extra
instrumentation.

## Method

1. **Freeze an evaluation set** before measuring. Held out, never used for
   tuning. See [data-strategy.md](data-strategy.md).
2. **Annotate ground truth** independently of the system's output. Annotating
   by correcting the system's guesses biases toward the system.
3. **Record the exact versions measured** — `engine_name`, `engine_version`,
   `ENGINE_VERSION` of the compliance engine, and the rule set. The schema
   already stores all four per run, so a result stays interpretable later.
4. **Report the set size and date** alongside every number. "94% on 50 images"
   is a useful claim; "94%" is not.
5. **Report where it fails.** A named failure mode is more credible than a
   round number.

## Running the method: `labelextract.evaluation`

The method above is now executable. `ml/labelextract/evaluation/` holds the
infrastructure — schema, loader, scoring, runner and CLI — and
[`ml/data/README.md`](../ml/data/README.md) documents the annotation format.

**The infrastructure is not a measurement.** No frozen set exists in this
repository, no annotation has been written, and every "Not measured" in this
document is still accurate. What changed is that measuring is now a matter of
annotating images rather than of writing code first.

```bash
cd ml
python -m labelextract.evaluation.cli validate data/our-evaluation-set
python -m labelextract.evaluation.cli run data/our-evaluation-set \
    --pipeline tesseract --report evaluation-report.json
```

### How each numbered requirement above is enforced

| Requirement | Mechanism |
|---|---|
| 1. Freeze the set before measuring | `MANIFEST.json` carries a `dataset_version` and a SHA-256 per image. An edited photograph fails validation and names the remedy: publish a new version. |
| 2. Annotate independently of the system | Ground truth (`schema.py`) and predictions (`prediction.py`) are separate types with no constructor between them. A test asserts the only annotation constructor is `from_dict`. |
| 3. Record the exact versions measured | Every report embeds pipeline name, pipeline version, the placeholder flag, a `report_version` for the scoring itself, and the run date. |
| 4. Report set size and date | `dataset_version`, `created_on` and `sample_count` are embedded in every report; they are not optional and cannot be omitted. |
| 5. Report where it fails | Every scored disagreement is listed individually with both sides — expected value, what was read, and whether it was flagged uncertain. |

### The outcome table

Four ground-truth states meet four prediction outcomes. Flattening them would
hide the two failures that matter most:

|  | predicted value | withheld / unread | nothing |
|---|---|---|---|
| `present_and_readable` | true positive | false negative | false negative |
| `present_but_unreadable` | **fabricated** | correct | missed unread |
| `not_present` | false positive | false positive | true negative |
| `unknown` | excluded | excluded | excluded |

**Fabricated** — a value produced for a declaration a person could not read —
is counted as a false positive *and* reported on its own line. It is the
failure the whole architecture exists to prevent: `field_presence` passes on
any extracted field regardless of its uncertainty flag, so a fabricated value
turns a package that declared nothing readable into one that declared
something.

**Excluded** is not a negative. Counting an un-annotated field as
`not_present` would charge the extractor for every gap in the annotation
effort, and precision would *fall* as annotation improved.

### What the infrastructure refuses to compute

Honesty here is enforced in code, not by convention:

- **CER and WER** require a hand transcription (`reference_text`). Without one
  they are reported as `null` with a stated reason, never as `0.0`.
- **Any rate with no denominator** is `null`, not zero. "Not measured" and
  "measured as zero" are different claims and only one of them is damning.
- **Unsupported keys** are excluded from every aggregate, per the rule above
  that a recall figure including them really measures how many declarations we
  chose not to implement.
- **A sample whose pipeline run crashed** is recorded under `failures` and
  excluded from scoring. Counting it as a miss would improve the number every
  time a bug was fixed.
- **Value comparison is shallow and documented**: normalised exact match, or
  containment in the evidence line. It does not know that `1 kg` and `1000 g`
  are the same quantity — that would be a per-field metric definition, and this
  document defines none — so such a case is listed as a disagreement for a
  human to judge.

### Text-region recall is still not implemented

The OCR table above names it. The annotation schema records no bounding boxes,
so it cannot be computed and is not reported. Adding boxes to the schema is the
work that would unlock it; estimating it from anything else would not.

## Reporting rules

Non-negotiable, for the same reason the rest of this project is built the way
it is:

- Never quote a metric from a paper, a vendor, or a model's recollection as if
  it were measured on our data.
- Never report a number without its dataset, size and date.
- Never round a measurement upward for a slide.
- If a metric has not been measured, say **"not measured yet"**. It is a
  complete and respectable answer for a base branch.
- Distinguish demo behaviour from measured performance. A demo shows what the
  system does; it measures nothing.

## Current status

| Layer | Status |
|---|---|
| OCR | **Not measured.** Tesseract 5 is now installed and selectable, and no CER or WER for it has been computed on any dataset |
| Field extraction | **Not measured.** A deterministic English extractor now exists; no precision, recall or F1 has been computed |
| Uncertainty calibration | **Not measured.** Fields carry `uncertain` flags; nobody has checked whether they land on the right readings |
| Classification | **Not measured** — not implemented |
| Compliance findings | **Not measured** — zero verified rules loaded |
| Operational | **Not measured** — timing fields exist and are populated; no run against an evaluation set has been recorded |

**An engine being installed is not an engine being measured.** The status above
did not improve when Tesseract landed, and it will not until somebody runs the
method in this document against an annotated set.

What *is* measured today are the engineering properties, and those are real:
automated tests across the three suites (run them to get today's numbers —
a count written into a document is stale the next time anyone adds one);
query-count regression
bounds on the compliance engine; and a browser-to-database request path
verified in a real browser.

Of the ML tests, one needs the Tesseract binary and skips without it, and 35
need the optional `[ocr]` extra. The remaining 194 pass on a clone with no
dependencies installed at all, which CI checks by running the suite twice —
once before the extra is installed and once after.

That count is a fact about this branch on the date it was written, not a
quality metric. Do not cite it as one. In particular it says nothing about how
well the system reads a label: that is the row of **Not measured** above.
