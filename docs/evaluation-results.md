# Evaluation results

Measured numbers for the extraction layer, with the dataset, size and date that
produced them. [`evaluation-strategy.md`](evaluation-strategy.md) defines the
method; this file records what came out of it.

Nothing here is a compliance result. Every number below measures whether the
pipeline read what is printed on a photograph of a package. Whether a
declaration was legally required, and whether its value is lawful, is decided
by verified `ComplianceRule` rows in the deterministic engine, and no run
recorded here loads a rule or produces a verdict.

---

## Status of the current baseline

| | |
|---|---|
| Dataset | `our-eval-v0.1-draft` |
| Images | 28 photographs of 10 retail packages |
| Annotated fields | 336 (28 samples × 12 supported declarations) |
| Annotator | `claude-opus-5-vision-draft` — **model-drafted, not yet human-verified** |
| Baseline run | 2026-08-29 |
| Pipeline | `tesseract` 0.2.0 |

**This baseline is provisional.** Its ground truth was drafted by a model
reading the photographs, not by a person. That is a genuine reading of the
images — nothing in it came from OCR output, and the extractor under test was
not consulted while it was written — but it has not been checked by a human, and
until it has, the numbers below are a measurement against an unverified
reference. The verification checklist travels with the dataset
(`ml/data/our-evaluation-set/VERIFICATION.md`). When a person has signed the set
off, it should be re-published as `our-eval-v1` and this page re-measured
against it.

What is *not* provisional: the dataset is frozen (a SHA-256 per image, enforced
by validation), the run is reproducible from two commands, and the pipeline was
not touched before or during the measurement.

---

## 1. Dataset

`our-eval-v0.1-draft`, created 2026-08-29. It lives at
`ml/data/our-evaluation-set/` and, like everything under `ml/data/`, **it is not
in Git** — the repository holds the code that reads it and this report, not the
photographs. A clone gets neither the images nor the annotations.

**28 photographs, 10 products, all JPEG.** One photograph shows one panel, so a
declaration printed on the back is `not_present` on the front — a fact about the
photograph, never about the product.

| Product | Panels | What it is |
|---|---|---|
| product_001 | 6 | Aerosol can, helmet cleaner. Front, back, both sides, and two closeups of the declaration block (one square-on, one rotated so the block runs off frame) |
| product_002 | 4 | Effervescent tablet tube. Declaration face, marketer face, brand face, and the marketer face again in low light |
| product_003 | 4 | Soap carton. Declaration panel, two marketing panels, top flap |
| product_004 | 2 | Masala sachet, Marathi/English, photographed on its side |
| product_005 | 2 | Milk pouch, Latin/Devanagari/Gujarati, creased film |
| product_006–010 | 2 each | Four DMart Premia packs (sugar, chana, soya, lapsi) plus their brand faces |

**Why 28 and not 25.** The brief asked for roughly 25. Every one of the 28
available photographs was kept, because none duplicates another — each is a
distinct panel with distinct printed content — and because the panels that carry
little or nothing are exactly the ones that measure false positives. Eight panels
carry no declaration at all, and 230 of the 336 annotated cells are
`not_present`; every one of those is an opportunity for the extractor to invent
something. Dropping three of the empty panels to reach a round number would have
removed false-positive opportunities and quietly inflated precision. Nothing was
excluded for being hard.

### Annotation scheme

The four states defined in `labelextract.evaluation.schema`, applied per
declaration per photograph:

| State | Count | Share |
|---|---:|---:|
| `not_present` | 230 | 68.5% |
| `present_and_readable` | 83 | 24.7% |
| `present_but_unreadable` | 23 | 6.8% |
| `unknown` | 0 | 0% |

Two reading rules were applied uniformly, and are recorded in the dataset's own
build script:

1. A **scalar** declaration — quantity, price, date, batch code — is
   `present_and_readable` only when the whole value is unambiguously legible
   from that one photograph, without consulting another photograph of the same
   product.
2. A **name or contact** declaration is `present_and_readable` when the value
   text on the declaration's own line is legible, transcribed as far as it is
   legible.

`LabelFieldKey.other` is left unannotated on every sample. It is the extractor's
catch-all — `patterns.py` routes "marketed by" into it and nothing constrains
what else may land there — so a single annotation in that bucket would produce a
precision figure that measures nothing. The schema scores an unannotated key as
excluded, never as a negative.

### Language coverage

| Script | Panels |
|---|---:|
| Latin only | 23 |
| Latin + Devanagari | 3 |
| Devanagari only | 1 |
| Latin + Devanagari + Gujarati | 1 |

The Tesseract installation used for this run has **`eng` and `osd` language data
only**. No Devanagari or Gujarati traineddata is installed, so every non-Latin
declaration in the 5 panels that carry one is unreadable by construction. That
is a property of the environment, not a finding about the engine.

### Known limitations of the dataset

- **28 images is small.** Several per-field denominators are in single figures.
  No confidence interval is quoted below because at these counts one would be
  wider than the estimate.
- **Four of the ten products share one back-of-pack template** (the DMart Premia
  packs). The samples are therefore not independent, and the aggregate is
  weighted toward that one layout.
- **No hand transcription.** No sample carries `reference_text`, so CER and WER
  are unavailable — not zero.
- **One annotator, one pass, no adjudication.** There is no inter-annotator
  agreement figure because there is only one annotator, and that annotator is a
  model.
- **The annotated vocabulary is fixed at the twelve declarations supported when
  the set was frozen.** A declaration the extractor learns to read afterwards
  scores as `unknown` → excluded on every sample, which is correct — an
  un-annotated field is not a negative — but it means new extraction capability
  is unmeasurable against this version by construction. `unit_sale_price` is in
  that position today.

---

## 2. Baseline

| | |
|---|---|
| Pipeline | `tesseract` 0.2.0 (`labelextract.registry`) |
| OCR engine | Tesseract 5.4.0.20240606, leptonica 1.84.1, `eng` only |
| Preprocessing | `PillowPreprocessor` with upscaling to `UPSCALE_TO_DIMENSION` |
| Page segmentation | the 0.2.0 mode (0.1.0's PSM 6 is registered separately) |
| Field extraction | `RuleBasedFieldExtractor` — regex patterns, no model |
| Runtime | Python 3.11.1, Windows, CPU only |
| Trained model | none. No model was trained, fine-tuned or downloaded |

Reproduce with:

```bash
cd ml
python -m labelextract.evaluation.cli validate data/our-evaluation-set
python -m labelextract.evaluation.cli run data/our-evaluation-set \
    --pipeline tesseract --pipeline-version 0.2.0 \
    --report data/our-evaluation-set/baseline-report-v0.2.0.json
```

Nothing in `ocr/`, `fields/patterns.py`, `fields/rule_based.py`,
`preprocessing/` or the contracts was changed before, during or after this run.
The baseline is the branch as it stands.

---

## 3. Metrics — `tesseract` 0.2.0 on `our-eval-v0.1-draft` (N=28)

28 of 28 samples ran. 26 returned `completed`, 2 returned `empty` (nothing
usable recognised); 0 crashed, so nothing was excluded from scoring.

### Aggregate, micro-averaged over the twelve annotated declarations

| Metric | Value | Counts |
|---|---:|---|
| Precision | **0.944** | 17 / 18 |
| Recall | **0.205** | 17 / 83 |
| F1 | **0.337** | |
| Value accuracy | **0.588** | 10 correct of 17 detected |
| Fabricated values | **1** | a value produced where a person could read none |
| Correct unread | **0** | of 23 `present_but_unreadable` declarations |
| Missed unread | **22** | declaration present-but-unreadable, pipeline saw nothing |

Read the shape, not the headline: **the pipeline is trustworthy when it speaks
and mostly silent.** It reports few declarations, and the ones it reports are
almost always really there — but it finds one readable declaration in five, and
when it does commit to a value that value is right only about three times in
five.

### Per declaration

| Key | TP | FP | FN | TN | fab | CU | MU | Precision | Recall | F1 | Value acc. |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `batch_number` | 2 | 1 | 6 | 16 | 1 | 0 | 3 | 0.667 | 0.250 | 0.364 | 0.000 |
| `best_before` | 2 | 0 | 8 | 14 | 0 | 0 | 4 | 1.000 | 0.200 | 0.333 | 1.000 |
| `consumer_care_contact` | 1 | 0 | 11 | 14 | 0 | 0 | 2 | 1.000 | 0.083 | 0.154 | 0.000 |
| `country_of_origin` | 2 | 0 | 2 | 24 | 0 | 0 | 0 | 1.000 | 0.500 | 0.667 | 1.000 |
| `date_of_manufacture` | 1 | 0 | 3 | 20 | 0 | 0 | 4 | 1.000 | 0.250 | 0.400 | 0.000 |
| `date_of_packing` | 1 | 0 | 4 | 23 | 0 | 0 | 0 | 1.000 | 0.200 | 0.333 | 1.000 |
| `manufacturer_name` | 2 | 0 | 10 | 15 | 0 | 0 | 1 | 1.000 | 0.167 | 0.286 | 0.500 |
| `net_quantity` | 3 | 0 | 13 | 9 | 0 | 0 | 3 | 1.000 | 0.188 | 0.316 | 0.333 |
| `packer_name` | 0 | 0 | 2 | 26 | 0 | 0 | 0 | — | 0.000 | — | — |
| `retail_sale_price` | 3 | 0 | 7 | 13 | 0 | 0 | 5 | 1.000 | 0.300 | 0.462 | 1.000 |
| `date_of_import` | 0 | 0 | 0 | 28 | 0 | 0 | 0 | — | — | — | — |
| `importer_name` | 0 | 0 | 0 | 28 | 0 | 0 | 0 | — | — | — | — |

`date_of_import` and `importer_name` are not declared on any panel in this set —
all 28 are domestically packed. They are unmeasured, not perfect.

`unit_sale_price` became a supported declaration *after* this set was frozen, so
it has **no row above and no metric at all**. Every one of its 28 cells is
`unknown` → excluded, because the annotations cover the twelve declarations that
were supported when they were written. Re-running the baseline with the detector
in place reproduces every number in this table unchanged and adds one committed
reading — `₹2.91 per gram` off `p001_05_declaration_closeup`, confidence 0.83 —
that nothing scores. **One correct reading is not a measurement.** A precision
or recall figure for this declaration requires annotating the key across the set
and re-freezing it as a new `dataset_version`; the frozen set was not edited to
produce a number. See `ml/data/our-evaluation-set/VERIFICATION.md`.

### Uncertainty

The three rates do not share a denominator; each is stated with its own.

| Metric | Value | Denominator |
|---|---:|---|
| `uncertain_rate` | 0.500 | 11 of 22 emitted fields flagged uncertain |
| `uncertainty_precision` | 0.429 | 3 of 7 flagged **committed** readings really were wrong |
| `silent_error_rate` | **0.455** | 5 of 11 **unflagged** committed readings were wrong |

**`silent_error_rate` = 0.455 is the number that matters, and it is bad.** Nearly
half of the readings this pipeline offered without any hedge were wrong. The
uncertainty flag is currently close to uninformative: a flagged reading is wrong
43% of the time and an unflagged one 45% of the time, so the flag barely
separates the two populations on this set. The architecture's central promise —
that a confident reading can be trusted and an unsure one is marked — is not met
by the current implementation.

### Character and word accuracy

**Unavailable.** No sample carries a hand-transcribed `reference_text`, so CER
and WER cannot be computed. The harness reports them as `null` with that reason
attached rather than estimating them from something cheaper. They are
unavailable, not zero.

### Latency

Wall-clock per image, single CPU, as recorded by the pipeline:

| | ms |
|---|---:|
| Minimum | 1002 |
| Median | 2202 |
| Mean | 2039 |
| Maximum | 3309 |
| Total for 28 images | 57.1 s |

Measured on the development machine described in `ml/README.md` (i5, 8 GB RAM,
no GPU used). Tesseract is CPU-only here and no GPU path exists.

---

## 4. Results by condition

Conditions are free-form labels recorded per sample by the annotator. Counts are
field-outcomes within the images carrying that label, re-aggregated from the
same per-sample outcomes the harness scored; a field can appear under several
conditions.

| Condition | Images | TP | FP | FN | TN | Precision | Recall | F1 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| `declaration_closeup` | 2 | 5 | 0 | 4 | 10 | 1.000 | **0.556** | **0.714** |
| `embossed` / `symbol_indirection` | 1 | 3 | 0 | 4 | 5 | 1.000 | 0.429 | 0.600 |
| `low_light` | 1 | 1 | 0 | 2 | 8 | 1.000 | 0.333 | 0.500 |
| `stamped_ink` | 3 | 5 | 0 | 13 | 17 | 1.000 | 0.278 | 0.435 |
| `curved_surface` | 10 | 6 | 0 | 22 | 74 | 1.000 | 0.214 | 0.353 |
| `bilingual` / `devanagari` | 4 | 3 | 1 | 11 | 31 | 0.750 | 0.214 | 0.333 |
| `unlabelled_value` | 4 | 5 | 0 | 23 | 20 | 1.000 | 0.179 | 0.303 |
| `glare` | 12 | 8 | 1 | 37 | 97 | 0.889 | 0.178 | 0.296 |
| `plastic_film` | 8 | 5 | 0 | 26 | 65 | 1.000 | 0.161 | 0.278 |
| `full_panel` | 11 | 9 | 1 | 50 | 57 | 0.900 | 0.153 | 0.261 |
| `small_print` | 8 | 5 | 0 | 43 | 37 | 1.000 | 0.104 | 0.189 |
| `partial_crop` | 4 | 0 | 0 | 10 | 21 | — | **0.000** | — |
| `rotated_90` | 4 | 0 | 0 | 9 | 39 | — | **0.000** | — |
| `crinkled_film` | 3 | 0 | 0 | 12 | 21 | — | **0.000** | — |
| `branding_panel` | 13 | 0 | **0** | 3 | 151 | — | 0.000 | — |
| `false_positive_trap` | 2 | 0 | **0** | 3 | 19 | — | 0.000 | — |

Four things stand out.

**Framing dominates everything else.** A closeup of the declaration block scores
F1 0.714; the same declarations photographed as a full panel score 0.261.
Nothing else in this table moves the number as far. On present evidence the
cheapest available improvement is not a better engine but a better photograph —
which is a product decision (guide the user's camera) before it is an ML one.

**Three conditions score zero recall.** Cropped declarations, packs photographed
on their side, and creased film produced no correct detection at all. The
`rotated_90` result is the most actionable: Tesseract has `osd` installed and
the pipeline does not use it, so four images of legible print returned nothing
for want of an orientation step.

**Almost no false positives where there is nothing to find.** The thirteen
panels labelled `branding_panel` — eight of which carry no declaration at all —
produced 151 true negatives and zero false positives, including both deliberate
traps: the Dove panel whose promotional copy reads "…BATHING BAR 125 g AND GET
1 UNIT FREE" did not yield a net quantity. Across the whole set only one false
positive occurred in 230 `not_present` and 23 `present_but_unreadable` cells. The
extractor's refusal to guess is working where it is easiest to check.

**Devanagari is unmeasured, not failed.** The `devanagari_only` panel returned 12
characters of noise. With no Hindi or Marathi traineddata installed there was
nothing this configuration could have done, and the bilingual row should be read
as "the Latin half only".

---

## 5. Failure analysis

Every disagreement the harness recorded, by kind:

| Kind | Count |
|---|--:|
| `missed_readable_declaration` | 66 |
| `missed_unread_declaration` | 22 |
| `wrong_value` | 7 |
| `fabricated_value` | 1 |

### OCR failures

Two samples returned `empty` — `p002_01_back` (tube, small print curving away)
and `p006_02_front` (glossy film over a printed insert). Recognition on the rest
ranged from 12 characters (the Devanagari-only panel) to 2445.

Where OCR did read the line, single-character substitutions were the failure
mode, and they land on exactly the fields where a character matters:

- `p001_05` consumer care number read `8867162397` for **8867162337** — one digit.
- `p001_05` net quantity read `…(125 mt)` for **(125 mL)**.
- `p003_03` net contents read `4 UNITS X 125 9 + 125 g FREE` for **125 g**.

The last two were still normalised to the correct primary quantity (120 g,
4 units); they are counted as value errors because the comparison is a strict
one, deliberately. Value accuracy of 0.588 should be read as a lower bound for
that reason, just as the harness's own `_value_matches` documentation warns it
is an upper bound in the other direction.

### Extraction failures

- **Keyword collision.** `p001_05` `date_of_manufacture` matched the line "BEST
  BEFORE 2 YEARS FROM MFG. DT." — the substring "MFG. DT." — instead of the
  stamped `11/2025` beside the printed `MFG. DT.:` label. A best-before sentence
  was read as a manufacture date.
- **Declaration-pointer sentences captured as declarations.** On two DMart packs
  `batch_number` matched the boxed note "…MRP Rs. (incl. of all taxes), Batch
  No. & Use By Date" — a sentence that *points at* the declarations — instead of
  the unlabelled code stamped above it. The four DMart packs print the batch
  code with no adjacent label, and the rule-based extractor has no way to reach
  a value that its keyword does not sit beside.
- **Label/value split across lines.** `p002_03` prints four label names in a left
  column and their four ink-stamped values in a right column, so no single line
  contains both. All five declarations on that panel were missed, despite 532
  characters being recognised and the panel being one of the most legible in the
  set. Line-scoped regex matching cannot express this layout.
- **Stray-glyph capture.** `p007_01` `manufacturer_name` captured `#` from
  "Manufactured by: #" rather than "SWAMI SMARTH FOODS" on the following line —
  the same one-line limitation, plus no plausibility check on a one-character
  company name.

### Normalisation

No failure was attributable to normalisation in this run. Where a value reached
normalisation it was normalised correctly, including `120 GRAMS` → 120 g and
`4 UNITS` → count 4.

### Unreadable declarations — the largest single gap

Of 23 declarations a person could see were printed but could not read, the
pipeline correctly reported **zero** as unread. Twenty-two produced nothing at
all, and one produced a fabricated value. The `unread_declarations` channel —
the mechanism this architecture relies on to say "a declaration is here and I
could not read it", and the thing that should separate "not declared" from "not
legible" downstream — did not fire once on real photographs.

This matters more than the recall figure. A missing declaration and an illegible
one have different consequences: one is a potential contravention, the other is
a request for a better photograph. On this set the pipeline cannot currently
tell a reviewer which it is looking at.

### False positives

One, and it is instructive. `p007_01` prints "Batch No. :" with **nothing
stamped against it** — a blank declaration. The extractor produced the value
`No` (from the label text itself), unflagged and confident. Ground truth for a
printed-but-valueless declaration is `present_but_unreadable`, so the harness
scores this as `fabricated` — its worst category, and correctly: a package that
declared no batch number became one that declared "No".

### False negatives

66 readable declarations missed, dominated by `consumer_care_contact` (11),
`net_quantity` (13) and `manufacturer_name` (10). The causes are those above —
full-panel framing, one-line matching, and unlabelled or split values — not, on
the evidence here, an inability to recognise the characters.

---

## 6. Limitations

- **The ground truth is not yet human-verified.** Everything above is measured
  against a model-drafted reference. This is the single largest caveat on the
  page.
- **N = 28, from 10 products, 4 of which share one template.** Per-field
  denominators run as low as 2. No confidence interval is quoted because at
  these counts it would be wider than the estimate, and quoting one would lend
  the numbers a precision they do not have.
- **Latin only.** With `eng` traineddata alone, the Devanagari and Gujarati
  content in the 5 of 28 panels that carry it was unreadable by construction.
  Nothing here measures multilingual performance.
- **CER and WER do not exist for this system.** No transcription has been made.
- **Value accuracy is a strict comparison.** Two of the seven value errors are
  cases a human would call substantially correct.
- **One environment, one machine.** Windows, Python 3.11.1, Tesseract 5.4.0.
  Latency in particular will not transfer.
- **No trained model, no training pipeline, no fine-tuning.** Tesseract is used
  as shipped. Nothing here is evidence about what a trained model would do.
- **This measures extraction only.** No compliance verdict was produced or
  scored. Measuring findings against a human reviewer's determination is a
  different exercise requiring verified rules the repository does not yet have.

---

## 7. Reference: pipeline 0.1.0 on the same frozen set

`tesseract` 0.1.0 is the frozen earlier configuration (PSM 6, no upscaling),
still registered so a change can be re-measured rather than taken on trust. Both
ran against the same 28 bytes-identical images.

| | 0.1.0 | 0.2.0 |
|---|---:|---:|
| Precision | 0.875 | **0.944** |
| Recall | 0.169 | **0.205** |
| F1 | 0.283 | **0.337** |
| Value accuracy | **0.714** | 0.588 |
| Silent error rate | **0.273** | 0.455 |
| Uncertainty precision | **0.600** | 0.429 |
| Fabricated | 1 | 1 |
| Correct unread | 0 | 0 |
| `empty` results | **0** | 2 |
| Median latency | **769 ms** | 2202 ms |

0.2.0 finds more (recall 0.169 → 0.205) and its detections are cleaner
(precision 0.875 → 0.944), but the values it commits to are *less* often right
(0.714 → 0.588), its confident readings are wrong more often (0.273 → 0.455), it
returns `empty` on two images where 0.1.0 returned text, and it costs about 2.9×
the time per image. On this set the upgrade is a trade, not a clear win, and it
is the first time either configuration has been measured against ground truth at
all.

---

## 8. Baseline conclusion

A measured baseline now exists where none did: `tesseract` 0.2.0 on
`our-eval-v0.1-draft`, precision 0.944, recall 0.205, F1 0.337, value accuracy
0.588, silent error rate 0.455, median 2.2 s per image, CER/WER unavailable.

**This system is nowhere near good enough to be relied on for a legal
determination, and the good-looking number on this page is the one most likely
to mislead.** Precision of 0.944 does not mean the system is 94% right. It means
that on the rare occasions it reports a declaration, it has usually found a real
one — while missing four readable declarations in five, never once correctly
flagging an unreadable declaration as unread, and being wrong about half the
time when it speaks without hedging. A compliance engine fed this layer's output
today would be reasoning mostly about declarations it never saw.

The architecture's separation is holding: ML reports what a package appears to
say, the deterministic engine decides compliance, and nothing in this run
produced or scored a verdict. But the perception layer's own contract — commit
when sure, say "unread" when not — is not yet met in practice, and
`silent_error_rate` and `correct_unread` are the two numbers that say so.

Nothing was tuned to produce these figures. The next step is a comparison
against the OCR-robustness work on this same frozen dataset, so that any claimed
improvement is a measured difference rather than an impression — and, before
that comparison is quoted anywhere, human verification of the ground truth.
