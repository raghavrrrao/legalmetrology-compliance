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

| Metric | Definition | Target |
|---|---|---|
| Character error rate (CER) | Levenshtein distance / reference length | TBD |
| Word error rate (WER) | Word-level equivalent | TBD |
| Text-region recall | Proportion of printed text regions detected | TBD |

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

| Metric | Definition | Target |
|---|---|---|
| Processing time per image | Upload → verdict, wall clock | TBD |
| OCR time | Time inside the extraction pipeline | TBD |
| Extraction failure rate | Runs ending `FAILED` | TBD |
| Empty extraction rate | Runs ending `EMPTY` (unreadable) | TBD |

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
| OCR | **Not measured** — no engine installed |
| Field extraction | **Not measured** — no extractor installed |
| Classification | **Not measured** — not implemented |
| Compliance findings | **Not measured** — zero verified rules loaded |
| Operational | **Not measured** — timing fields exist and are populated, but no run has used a real engine |

What *is* measured today are the engineering properties, and those are real:
211 automated tests (136 backend, 29 ML, 46 frontend); query-count regression
bounds on the compliance engine; and a browser-to-database request path
verified in a real browser.

That count is a fact about this branch on the date it was written, not a
quality metric. Do not cite it as one.
