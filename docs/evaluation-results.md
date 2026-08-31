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

> **Sections are cumulative, and the latest run is [§11](#11-ocr-robustness--tesseract-030-on-our-eval-v03-usp-partial):
> `tesseract` **0.3.0** on `our-eval-v0.3-usp-partial`, 2026-08-31.** §3 below
> records the first baseline (`tesseract` 0.2.0 on `our-eval-v0.1-draft`) and
> stays as written — it is an accurate record of a run against an artefact that
> still exists and still validates. Everything after it supersedes rather than
> invalidates: §9 adds `unit_sale_price`, §10 adds the first human corrections,
> §11 measures an OCR-robustness change against §10's numbers.

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

> **Superseded by §10, not invalidated.** These numbers are an accurate record of
> a real run against `our-eval-v0.1-draft`, which still exists and still
> validates. One cell of its ground truth was later corrected by a human
> verifier; the corrected successor is measured in §10. Nothing below has been
> recalculated.

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
it has **no row above and no metric at all** against `our-eval-v0.1-draft`.
Every one of its 28 cells is `unknown` → excluded, because the annotations cover
the twelve declarations that were supported when they were written. That field
is measured against a separate dataset version — see §9 — and this table is
unchanged by it.

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

---

## 9. `unit_sale_price` on `our-eval-v0.2-usp-draft`

> **Superseded by §10, not invalidated.** An accurate record of a real run
> against `our-eval-v0.2-usp-draft`, which is preserved unchanged. Three cells of
> its `unit_sale_price` ground truth were later corrected by a human verifier;
> the corrected successor is measured in §10. Nothing below has been
> recalculated, and the "NOT YET DEFENSIBLE" verdict it reaches still stands.

### Why a second dataset version

`unit_sale_price` entered `SUPPORTED_KEYS` after `our-eval-v0.1-draft` was
frozen, and that set annotates twelve declarations rather than thirteen. The
scorer therefore excluded all 28 of its cells and the field had **no metric of
any kind** — correct behaviour, since an un-annotated field is not a negative,
but it left a capability unmeasured.

`our-eval-v0.2-usp-draft` exists to close that. It is `v0.1` **plus one
column**: the same 28 photographs with byte-identical images and digests, the
twelve existing annotations carried through verbatim, and `unit_sale_price`
added. `v0.1` was not edited and its baseline above is untouched — carrying the
twelve columns over unchanged is precisely what makes a difference in any of
them a regression rather than a dataset change. On this run there was none:
**all twelve carried-over per-field results are identical.**

| | |
|---|---|
| Dataset | `our-eval-v0.2-usp-draft`, created 2026-08-30 |
| Images | 28 photographs, 10 products — the same files as `v0.1` |
| Annotator | `claude-opus-5-vision-draft` — **model-drafted, not human-verified** |
| Pipeline | `tesseract` 0.2.0, unchanged; no OCR, model or preprocessing setting was touched |
| Frozen | Yes — SHA-256 per image, enforced by validation |

### Ground truth

Six of the ten products declare a unit sale price and four do not. Notably the
four DMart Premia packs **do not share** the declaration: the 200 g and 500 g
packs carry it and name it in their legend box, while both 1 kg packs omit both.

| State | Cells |
|---|---:|
| `present_and_readable` | 7 |
| `present_but_unreadable` | 4 |
| `not_present` | 17 |

### Measured

| Metric | Value | Denominator |
|---|---:|---|
| True positives | 1 | |
| False positives | 0 | |
| False negatives | 6 | |
| True negatives | 17 | |
| Fabricated | **0** | |
| `correct_unread` | 0 | |
| `missed_unread` | 4 | |
| Precision | 1.000 | **1 detection** |
| Recall | **0.143** | 7 readable declarations |
| F1 | 0.250 | |
| Value accuracy | 1.000 | **1 detection** |

Uncertainty is reported across the whole run and is not separable per field; the
one new committed reading moved `silent_error_rate` from 0.455 to 0.417 and
`uncertain_rate` from 0.500 to 0.478 purely by joining the denominator —
`confident_and_wrong` stayed at 5.

**Read the three columns separately.** *Detection*: 1 of 7. *Normalised value*:
the single detection was correct — `{amount: "2.91", currency: "INR", per_unit:
"gram", per_measure: "mass"}`. *Uncertainty behaviour*: zero fabrications, and
zero correct-unread — on four panels that name the declaration and hide its
value, the pipeline reported nothing rather than reporting it unread.

### Why the two good-looking numbers mean almost nothing

Precision 1.000 and value accuracy 1.000 both have a denominator of **one**.
Worse, the negatives never tested anything: across all 17 `not_present` panels
OCR surfaced **no unit-price-like candidate text at all**, including
`p005_01_back`, which prints `Bunback Price (Empty clean pouch) ₹ 1.00 / Ltr` —
a real per-unit rupee price that is not this declaration and is the best
false-positive trap in the set. It was never recognised, so the detector was
never offered the chance to fail it.

Quote neither figure. The only defensible statement from this run is the recall
one, and even that rests on seven cells.

### Error analysis — all ten misses

Only **2 of the 11 positive cells** produced any unit-price-like text from OCR
at all, so nine of the ten failures are upstream of the field extractor.

| Sample | Outcome | Cause | Evidence |
|---|---|---|---|
| `p001_05` | **TP, value correct** | — | `UNIT SALE PRICE : ¥2.91 PER GRAM` — the ₹ glyph misread as ¥, which the extractor correctly does not propagate (it emits `currency: INR`) |
| `p001_02` | FN | **OCR failure** | 37 blocks recognised, none from the declaration block — 6-point print at arm's length on a curved can |
| `p001_04` | missed unread | **OCR failure** | 14 blocks; the truncated line never recognised |
| `p001_06` | missed unread | **OCR failure** | left half of every line outside the frame |
| `p002_01` | missed unread | **OCR total failure** | **0 blocks** recognised from the whole photograph |
| `p002_04` | missed unread | **OCR failure** | 58 blocks, declaration block not among them (low light) |
| `p002_03` | FN | **layout/association + unsupported unit** | label column (`USP (Per Tablet) ₹`) and value column (`350.00/23.33`) are separate OCR lines, and a line-oriented extractor cannot pair them. Even paired, `tablet` is not in the unit vocabulary |
| `p003_03` | FN | **character confusion + layout** | embossed line read as `OH 8465 /-%0.93/9` — ₹→`%` and the trailing `g`→`9`, so no unit matches; and the `USP` keyword sits on a different line (symbol indirection) |
| `p004_01` | FN | **orientation** | pack photographed on its side; `psm 3` runs with no orientation detection, so the table returns as mirrored text (`‘Ag 2s/n ales yun`) |
| `p009_01` | FN | **OCR failure** | faint stamp on yellow film; 57 blocks, the rate line absent |
| `p010_01` | FN | **currency glyph + keyword anchoring** | OCR read `Z 0.08 perg` — ₹→`Z`, so no currency token — and the `Unit Sale Price` keyword lives in a separate legend box. With neither anchor the detector declines **by design** |

The pattern is not subtle, and it is not about the detector: **eight of ten
failures are recognition, not interpretation.** Three sub-patterns are worth
naming because each is a fixable engineering task rather than a limit:

1. **The ₹ glyph is unreliable.** It was misread on three of the four panels
   where it mattered (`¥`, `%`, `Z`). Since the no-keyword branch requires a
   currency token, a lost ₹ turns a readable rate into a silent miss.
2. **The keyword and the value are routinely on different lines.** Three of the
   six declaring products use a legend box, a label column or symbol
   indirection. A line-oriented extractor cannot reach any of them.
3. **Orientation is not detected.** `osd` is installed; `psm 3` does not use it.

None of these was acted on. Changing OCR configuration to improve this metric is
exactly what a measurement run must not do; they are recorded as candidates for
a separate, separately measured change.

### Limitations

- **Model-drafted, unverified.** The column was read by a model, not a person.
  A per-sample verification worksheet now exists at
  `ml/data/usp-evaluation-set/VERIFICATION-RECORD.md`: current state, evidence
  location, whether the amount and the per-unit basis are each readable, and a
  recommended verified state for all 28 photographs.
- **Known contamination.** v0.1's reading rule 1 requires each photograph to be
  judged without consulting another of the same product. Seven of the eleven
  positive cells were drafted after the annotator had already read the value off
  a closeup of the same panel. `ml/data/usp-evaluation-set/VERIFICATION.md`
  names them and gives the order a verifier must work in.
- **One cell is a known defect.** `p002_04_right` was annotated
  `present_but_unreadable` *without the photograph being opened*, by inference
  from a sister photograph. Re-inspection shows only an unidentifiable numeric
  fragment, so presence cannot be established and `unknown` is the right state.
  It was left in place rather than silently corrected, so that what was measured
  and what is documented remain the same thing; correcting it changes no
  headline metric (`missed_unread` 4 → 3 only).
- **The four annotation states cannot express "inspected, indeterminate".**
  `unknown` is documented as *not yet annotated*, and using it for a cell a
  person examined and could not resolve conflates two different facts. It gives
  the correct scoring behaviour (excluded) and is what the record recommends,
  but it is a real schema limitation and is written up in the record rather than
  worked around.
- **Some photographs contain more than one package.** Neighbouring products are
  in frame on at least `p006_02_front` and `p009_02_front`. OCR read none of
  that text on this run, but a higher-recall engine could read a price off a
  package that is not the subject and be charged a false positive against a
  correctly annotated `not_present` cell.
- **Seven readable positives across four independent label designs.** Four of
  the positive cells are one panel photographed four ways; three more are one
  tube photographed three ways.
- **The negatives are untested**, as above.
- **One cell moves the headline, in the flattering direction.** If a verifier
  disagrees with `p001_02` — the most arguable cell, and one v0.1 already called
  unreadable one line higher — it becomes `present_but_unreadable`, the readable
  denominator drops to 6, and recall **rises** to 1/6 = 0.167. The per-sample
  audit in `ml/data/usp-evaluation-set/VERIFICATION-RECORD.md` recommends
  exactly that change and deliberately leaves it for a human to apply, precisely
  because the drafting annotator would be improving its own score.

### Conclusion

**`unit_sale_price` metric: NOT YET DEFENSIBLE.** A precision or value-accuracy
figure resting on one detection, against negatives that surfaced no candidate
text, drafted by a model that had already seen the answer on a sister
photograph, is not a number to publish or to put in a pitch.

What this run *does* establish, and what it was worth doing for:

- the field is now measurable at all, and the framework needed no change to do it;
- the extractor **fabricated nothing** — on four panels naming a declaration it
  could not read, it stayed silent rather than inventing a rate;
- recall is poor and the reason is **recognition, not interpretation**, which
  points the next piece of work at OCR rather than at patterns.

**The gating next action is human verification, and the worksheet for it exists:**
`ml/data/usp-evaluation-set/VERIFICATION-RECORD.md` carries all 28 cells with an
evidence location, separate amount / per-unit readability fields, a contamination
flag, a non-binding recommendation and a blank decision slot. Nine cells are
flagged as requiring independent judgement. Working through it makes **recall**
indicative; it does not make precision, F1 or value accuracy quotable, because
no negative in this set surfaces candidate text — only more photographs fix that.

This section measures extraction only. It says nothing about whether any package
complies with rule 6(11); that requires the net-quantity band and a comparison
against the retail sale price, both of which belong to the rules layer and need
check types that are not registered.

---

## 10. First human corrections — `our-eval-v0.3-usp-partial`

| | |
|---|---|
| Dataset | `our-eval-v0.3-usp-partial`, created 2026-08-31 |
| Size | 28 photographs, **364 annotated fields** (28 × 13 declarations) |
| Predecessors | `our-eval-v0.1-draft` and `our-eval-v0.2-usp-draft`, both **preserved unchanged** |
| Pipeline | `tesseract` 0.2.0 — unchanged; no OCR, model or preprocessing setting was touched |
| Run | 2026-08-31, 28/28 samples, **0 failures** |
| Verification | **PARTIAL** — 34 of 364 cells reviewed by a person |

### Why v0.3 exists

A human verifier worked through the arguable cells of `our-eval-v0.2-usp-draft`
across twelve recorded sessions and made **four ground-truth corrections**. The
project's versioning contract forbids editing a published version in place —
v0.1's README: *"Do not edit this version. Publish a new `dataset_version`
instead"* — so the corrections were published as a successor rather than applied
to either predecessor.

**Both predecessors are intact.** v0.1's and v0.2's images, annotations,
manifests and version labels are byte-unchanged, and §3 and §9 above remain
accurate records of what was measured against them. Those sections are
**superseded by v0.3, not invalidated**: they describe real runs against real
artefacts that still exist and still validate.

### The four human corrections

| Session | Cell | Model draft | Human decision |
|---|---|---|---|
| 1 | `p007_01_back / date_of_manufacture` | `present_but_unreadable`, no value | `present_and_readable`, **`10 JUN 2026`** |
| 2 | `p001_02_back_clean / unit_sale_price` | `present_and_readable`, `2.91 PER GRAM` | `present_but_unreadable`, no value |
| 3 | `p001_04_right_clean / unit_sale_price` | `present_but_unreadable`, no value | `not_present`, no value |
| 7 | `p002_04_right / unit_sale_price` | `present_but_unreadable`, no value | `not_present`, no value |

One touches the twelve declarations inherited from v0.1; three touch the
`unit_sale_price` column introduced by v0.2. A build-time assertion refuses to
apply a correction to a cell that does not still hold the drafted value the log
records, and a separate check confirms that **exactly** these four cells differ
from v0.2, that **exactly one** twelve-column cell differs from v0.1, and that
no other cell moved. Per-cell provenance, including every draft, decision,
objection and correction, is in `ml/data/human-verification/VERIFICATION-LOG.md`.

### Verification coverage — what is and is not human-reviewed

| Provenance | v0.1 declarations | `unit_sale_price` | Total |
|---|---:|---:|---:|
| Human-confirmed | 20 | 8 | **28** |
| Human-changed | 1 | 3 | **4** |
| Human-reviewed, unresolved | 2 | 0 | **2** |
| **Model-drafted, not reviewed** | **313** | **17** | **330** |
| Basis | 336 | 28 | 364 |

**This is not a human-verified ground-truth release.** 330 of 364 cells — 91% —
remain as `claude-opus-5-vision-draft` wrote them. What *is* human-reviewed is
the part that carries the `unit_sale_price` metric: all nine cells flagged for
independent judgement, and all twelve cells where that declaration is present
either readably or unreadably.

### Two cells reviewed and deliberately left unresolved

Neither has been converted into a confirmed value, and neither should be.

- **`p007_01_back / batch_number`** — the pack prints `Batch No. :` with nothing
  stamped against it. "Declared but blank" has no state in the four-state
  schema. Held pending a policy decision; not converted to `not_present`, and no
  batch number invented.
- **`p004_01_back / consumer_care_contact`** — presence confirmed; the drafted
  value `brand.sawai@pkmfoods.com` has **not** been confirmed character-for-character
  against the photograph. The cell's *state* is human-confirmed, its *value
  string* is still model-drafted. The schema cannot record that split, so it is
  recorded in the log.

### Provenance caveat — `p010_01_back / unit_sale_price`

The cell holds `0.08 per g`, matching the model draft, and is recorded as
human-confirmed. **It must not be described as an independently blinded human
verification**, for three reasons documented in Session 12:

1. The drafted value had already been disclosed to the verifier before judgement
   — the session was expressly non-blind.
2. The first human decision for the cell was wrong (a carry-forward of the
   previous session's value) and survived an explicit re-check.
3. The correction followed the assistant naming distinguishing features of the
   panel, so the final value arrived after a material intervention by the party
   whose draft was under review.

The value is very probably right. **"Probably right" and "independently
verified" are different claims**, and only the first is available here.
Re-verification by a second person who has not seen the log is recommended
before any account describes the `unit_sale_price` column as human-verified. It
is a documentation matter, not a dataset defect: the value matches the draft, so
there is nothing to apply.

### The 17 model-drafted negatives

Seventeen `unit_sale_price` cells annotated `not_present` remain **model-drafted
and unreviewed**. They were not verified, and nothing here should be read as
saying they were.

They do not alter the figures below. The extractor produces **no
`unit_sale_price` output on any of them**, so all score `true_negative` and
`false_positive` is 0 regardless of what a review would conclude. The one thing
a review could change is the recall denominator, if a cell annotated absent in
fact carried a readable declaration. Of the seventeen, nine were re-inspected
directly during the phase-15 audit and eight rest on v0.1's panel notes plus an
OCR check finding no currency or price token; every declaration-bearing panel
among them was directly inspected, and the eight are brand faces.

**That is an assumption underneath the recall denominator, not a verified fact.**

### Measured on v0.3

Ten of the twelve previously scored declarations are **byte-identical** to their
v0.2 values. Two moved, and only because ground truth was corrected:

| Field | Counts (TP/FP/FN/TN/fab/CU/MU) | Precision | Recall | F1 | Value acc. |
|---|---|---:|---:|---:|---:|
| `date_of_manufacture` | 1 / 0 / 4 / 20 / 0 / 0 / 3 | 1.000 | **0.200** | 0.333 | 0.000 |
| `unit_sale_price` | 1 / 0 / 5 / 19 / 0 / 0 / 3 | 1.000 | **0.167** | 0.286 | 1.000 |

Against v0.2 those were `date_of_manufacture` recall 0.250 and `unit_sale_price`
recall 0.143. **One correction moved a metric down and one moved it up** —
`date_of_manufacture` fell because a cell the pipeline had missed *as unread* is
now a readable declaration it missed outright.

Aggregates, micro-averaged, computed with the same definitions §3 uses.

> **Important evaluation limitation — read with the table, not after it.** These
> figures are measured on `our-eval-v0.3-usp-partial`, where only **34 of 364
> cells (9.3%) were human-reviewed** and **330 of 364 remain model-drafted and
> unreviewed**. They therefore describe this partial-verification evaluation
> artefact. **They must not be interpreted as performance against a fully
> human-verified ground truth**, and no figure below should be quoted without
> this sentence attached.

| Metric | Over all 13 declarations | Over the twelve v0.1 declarations |
|---|---:|---:|
| Precision | **0.947** (18 / 19) | 0.944 (17 / 18) |
| Recall | **0.200** (18 / 90) | 0.202 (17 / 84) |
| F1 | **0.330** | 0.333 |
| Value accuracy | **0.611** (11 of 18) | 0.588 (10 of 17) |
| Fabricated | 1 | 1 |
| Correct unread | **0** | 0 |
| Missed unread | 24 | 21 |

Uncertainty, unchanged from the v0.2 run because no cell carrying a prediction
changed truth state: `uncertain_rate` 0.478, `uncertainty_precision` 0.429,
**`silent_error_rate` 0.417**. CER and WER remain **unavailable** — no sample
carries a `reference_text`.

### What v0.3 does and does not license

**It supports:** reporting `unit_sale_price` recall as **1 of 6 readable
declarations (0.167)** on partially human-verified ground truth; stating that
**no fabricated value and no false-positive detection were observed for that
declaration in this 364-cell dataset** — an observation about this evaluation,
not a property of the extractor, and one that does not generalise, since the
dataset as a whole carries one fabrication and one false positive, both in
`batch_number`; and reporting the twelve-declaration aggregate on ground truth
one cell better than v0.1's.

**It does not support:** calling the dataset human-verified; calling the
`unit_sale_price` column independently verified; quoting precision, F1 or value
accuracy for `unit_sale_price`, which still rest on a single detection against
negatives that surface no candidate text; or any claim about legal compliance.

This section measures extraction only. Whether a package complies with rule
6(11) requires the net-quantity band and a comparison against the retail sale
price — decisions for the rules layer, needing check types that are not
registered.

---

## 11. OCR robustness — `tesseract` 0.3.0 on `our-eval-v0.3-usp-partial`

Branch `feature/ocr-recognition-robustness`, run 2026-08-31 on the same 28
photographs and the same 364 annotated cells §10 uses.

> **The same evaluation limitation applies to every figure in this section.**
> `our-eval-v0.3-usp-partial` is **partially** human-verified: **34 of 364 cells
> (9.3%) were reviewed by a person and 330 remain model-drafted and
> unreviewed.** These numbers describe this artefact. They are not performance
> against a fully human-verified ground truth, and no figure below should be
> quoted without this sentence attached. Provenance is in
> `ml/data/human-verification/VERIFICATION-LOG.md`.

### 11.1 Baseline, reproduced before anything was changed

`tesseract` 0.2.0 re-run against the stored §10 report: **byte-identical scores
and an identical 13,929 recognised characters.** That is what makes the
comparisons below comparisons rather than two unrelated runs.

| | Baseline (0.2.0) |
|---|---:|
| Precision | 0.947 (18/19) |
| Recall | 0.200 (18/90) |
| F1 | 0.330 |
| Value accuracy | 0.611 (11/18) |
| Silent error rate | 0.417 (5/12) |
| Fabricated values | 1 |
| Correct unread / missed unread | 0 / 24 |
| Photographs returning EMPTY | 2 of 28 |
| Recognised characters | 13,929 |
| Median latency | 1,126 ms |
| CER / WER | unavailable — no sample carries a hand transcription |

### 11.2 Diagnosis before experiment — is each failure OCR or extraction?

All 97 scored disagreements were triaged by asking one question of each: **does
the annotator's transcription appear in what OCR actually read?**

| Verdict | Count | What it means |
|---|---:|---|
| OCR read nothing resembling the value | 55 | recognition failure |
| Ground truth carries no value (`present_but_unreadable`) | 25 | not a value error |
| OCR read the value exactly, extraction did not use it | 9 | **extraction / layout** |
| OCR read every token of the value | 6 | extraction, or a mangled keyword |
| OCR read part of the value | 9 | recognition, partially |

**Recall on this set is dominated by recognition, not interpretation** — 55 of
97. That is why the work below spends most of its experiments on OCR and keeps
the extraction changes narrow. It is also why the recall gain is small: the
extraction layer can only use text the engine produced.

### 11.3 The ₹ glyph is a character-set limitation, not an image-quality one

The reported failure "₹ recognised as `Z`" was reproduced and then isolated.

`₹ 0.08 per g` on `p010_01_back` was re-OCR'd from its own bounding box at 2×,
4× and 6× the source scale under `--psm 6`, `7` and `13`. The glyph came back
as `%`, `<`, `&` or nothing — **never as `₹`**. The same string was then
*rendered* at 64 px in Arial, Calibri and Segoe UI Symbol — clean synthetic
type, no photograph involved — and read back as `= 0.08 per g`, `O 0.08 per g`,
`= 0.08 per g`.

**Tesseract's `eng` model cannot output `₹` at all.** No preprocessing,
upscaling or segmentation setting can fix that, and no character substitution
should be written to paper over it: a rule turning `Z` into `₹` would
manufacture a currency the engine never read. The installed language data on
this machine is `eng` and `osd` only.

Consequence, stated rather than worked around: the extractor's rule "a per-unit
rate with no keyword is a price only if a currency token was read" **can never
fire on a label that prints the symbol rather than `Rs.`**. That is a real and
general limitation of the current engine configuration, and the honest next
step is to measure a language pack or a second engine that carries the glyph —
not to guess it. See §11.12.

### 11.4 Orientation was measured, and the measurement rejected it

Every image in the set is upright: EXIF orientation is `1` or absent on all 28,
confirmed visually. Tesseract's own orientation-and-script detection was then
run over all 28:

| OSD verdict | Count |
|---|---:|
| `Rotate: 0` (correct) | 14 |
| OSD failed outright | 7 |
| `Rotate: 180` or `270` on an **upright** photograph | 7 |

The wrong verdicts came with orientation confidences of 0.07–1.30 and script
guesses of Arabic, Katakana and Han. The *correct* verdicts came with
confidences of 0.15–5.69. **The two ranges overlap, so no confidence threshold
separates them on this data.**

Applied, that is what it costs:

| | Recall | Value acc. | Silent err. | Median ms |
|---|---:|---:|---:|---:|
| No rotation | 0.211 | 0.684 | 0.300 | 1,134 |
| Rotate whenever OSD says so | 0.200 | 0.556 | 0.400 | 1,743 |
| Rotate only when confidence ≥ 2.0 | 0.211 | 0.684 | 0.300 | 1,660 |

Blind rotation loses a true positive, a fifth of the value accuracy and a third
more silent errors, for +54% latency. The confidence-gated variant changes
**nothing at all** and still pays for the OSD pass. Both rejected. Sideways
text remains a real failure mode on other photographs; what is rejected is
*this mechanism* for handling it, on this evidence.

### 11.5 Experiment record

Every run below is over all 28 photographs and all 364 cells. Negative results
are kept.

**Group A — OCR and preprocessing, measured against the 0.2.0 baseline.**

| # | Change | R | P | Value acc | Silent err | Fab | Chars | EMPTY | Median ms | Decision |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| — | Baseline | 0.200 | 0.947 | 0.611 | 0.417 | 1 | 13,929 | 2 | 1,126 | baseline |
| E1 | `--psm 6` | 0.233 | 0.913 | 0.429 | 0.571 | 2 | 19,944 | 0 | 1,230 | **reject** — +43% characters, and more of them wrong |
| E2 | `--psm 4` | 0.189 | 0.944 | 0.529 | 0.500 | 1 | 10,881 | 6 | 1,014 | reject |
| E3 | `--psm 11` | 0.156 | 0.933 | 0.714 | 0.300 | 1 | 18,150 | 0 | 1,229 | reject — costs four true positives |
| E4 | `--psm 12` | 0.178 | 0.941 | 0.562 | 0.455 | 1 | 20,365 | 0 | 1,531 | reject |
| E5 | Upscale cap 2× → 3× | 0.200 | 0.947 | 0.611 | 0.429 | 1 | 14,058 | 2 | 1,244 | reject — identical scores, +10% time |
| E6 | Denoise on | 0.178 | 0.941 | 0.688 | 0.273 | 1 | 13,119 | 1 | 1,354 | reject — confirms the 0.2.0 finding at 28 images |
| E7 | Autocontrast off | 0.211 | 0.950 | 0.579 | 0.385 | 1 | 13,524 | 4 | 1,127 | reject — doubles the EMPTY count |
| E8 | `--oem 1` (LSTM only) | 0.200 | 0.947 | 0.611 | 0.417 | 1 | 13,929 | 2 | 1,044 | reject — **byte-identical**; confirms `--oem 3` resolves to LSTM here |
| E9 | RGB instead of grayscale | 0.244 | 0.917 | 0.591 | 0.286 | 1 | 13,306 | 7 | 2,258 | **reject** — best recall of any run, at 7 of 28 photographs unread and 2× latency |

**Group B — extraction, applied incrementally.** Each row includes the rows
above it.

| # | Change | R | P | Value acc | Silent err | Fab | CU | Decision |
|---|---|---:|---:|---:|---:|---:|---:|---|
| X1 | A batch keyword may not be its own value | 0.189 | **1.000** | 0.647 | 0.300 | **0** | 1 | keep |
| X6 | + a name must contain a letter | 0.178 | 1.000 | 0.688 | 0.300 | 0 | 1 | keep |
| X7 | + a name keyword ending its line reads the line below | 0.200 | 1.000 | 0.667 | 0.300 | 0 | 1 | keep |
| X8 | + toll-free numbers printed in three or four groups | **0.211** | 1.000 | **0.684** | 0.300 | 0 | 1 | keep |

**Group C — the empty-result segmentation retry, measured at the X1 point.**

| # | Fallback mode | R | P | Fab | Chars | EMPTY | Median ms | Decision |
|---|---|---:|---:|---:|---:|---:|---:|---|
| X5 | 4 | 0.189 | 1.000 | 0 | 13,929 | 2 | 1,098 | reject — mode 4 reads nothing on those two images either |
| X2 | 6 | 0.189 | 0.944 | **1** | 15,273 | 0 | 1,166 | **reject** — see below |
| X3 | **11** | 0.189 | 1.000 | 0 | 14,805 | 0 | 1,119 | **keep** |
| X4 | 12 | 0.189 | 1.000 | 0 | 14,772 | 0 | 1,126 | reject — same effect, fewer characters |

Mode 6 recovers the most characters and was rejected for it. Among the extra
text it finds on `p002_01_back` — a cylindrical tube shot side-on — is the line
`4 rs ne rm`, which the price detector's speculative no-keyword branch reads as
a retail sale price of **4**, on a panel whose price a human annotator recorded
as unreadable. That is a fabricated value: the single failure mode the
three-valued design exists to prevent. Mode 11 recovers 65% as many characters
and produced no such reading.

**Group D — local illumination flattening (rejected), measured against X8.**
The largest documented preprocessing gap is that one global histogram stretch
cannot serve a cylindrical can lit from one side. A pure-Pillow shading
correction — estimate the illumination with a wide Gaussian blur, subtract it,
then autocontrast — was implemented to test that without adding numpy or
OpenCV. (The first attempt had the operands reversed and produced an inverted
image; the numbers below are from the corrected version.)

| # | Blur radius | R | P | Value acc | Silent err | Chars | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| — | (none) | 0.211 | 1.000 | 0.684 | 0.300 | 14,805 | keep |
| G1 | 15 px | 0.233 | 0.955 | 0.619 | **0.429** | 20,318 | reject |
| G2 | 25 px | 0.167 | 1.000 | 0.667 | 0.400 | 17,976 | reject |
| G3 | 50 px | 0.211 | 1.000 | 0.684 | 0.364 | 18,795 | reject |

It works, in the narrow sense that it recovers up to **37% more characters**.
It is rejected anyway, because the extra characters are not extra *reliable*
declarations: G1 buys +0.022 recall for +0.129 silent error rate and a false
positive, and G3 buys nothing and still raises silent errors. It is the
clearest result in this exercise that **characters recognised is not the
metric.**

**Also measured and rejected: tolerating a lost space in `per g`.** OCR read
`₹ 0.08 per g` as `Z 0.08 perg`, and `PER_UNIT_PRICE` requires a word boundary
after `per`. Allowing the glued form is safe, but a search of all 674 recognised
lines found it on exactly one line — the one already suppressed for carrying no
currency token and no keyword. **No measured effect, so not kept.**

### 11.6 Baseline versus final

`tesseract` 0.2.0 → **0.3.0**, same dataset, same machine, same day.

| Metric | Baseline 0.2.0 | Final 0.3.0 | Change |
|---|---:|---:|---|
| Precision | 0.947 (18/19) | **1.000** (19/19) | +0.053 |
| Recall | 0.200 (18/90) | **0.211** (19/90) | +0.011 |
| F1 | 0.330 | **0.349** | +0.018 |
| Value accuracy | 0.611 (11/18) | **0.684** (13/19) | +0.073 |
| **Silent error rate** | 0.417 (5/12) | **0.300** (3/10) | **−0.117** |
| **Fabricated values** | 1 | **0** | −1 |
| Correct unread | 0 | **1** | +1 |
| Missed unread | 24 | 24 | — |
| Photographs returning EMPTY | 2 of 28 | **0 of 28** | −2 |
| Recognised characters | 13,929 | 14,805 | +876 |
| Median latency | 1,126 ms | 1,081 ms | −45 ms (run-to-run noise) |
| Mean / p90 / max latency | 1,198 / 1,645 / 2,448 ms | 1,171 / 1,635 / 2,376 ms | unchanged |
| Uncertain rate | 0.478 | 0.545 | +0.067 |
| CER / WER | unavailable | unavailable | — |

Per declaration, as TP/FP/FN/TN/fabricated/correct-unread/missed-unread:

| Declaration | Baseline | Final | Recall | Value acc. |
|---|---|---|---|---|
| `batch_number` | 2/1/6/16/1/0/3 | 1/0/7/16/**0**/**1**/3 | 0.250 → 0.125 | 0.000 → 0.000 |
| `consumer_care_contact` | 1/0/11/14/0/0/2 | **2**/0/10/14/0/0/2 | 0.083 → 0.167 | 0.000 → 0.500 |
| `manufacturer_name` | 2/0/10/15/0/0/1 | **3**/0/9/15/0/0/1 | 0.167 → 0.250 | 0.500 → 0.667 |
| `best_before` | 2/0/8/14/0/0/4 | unchanged | 0.200 | 1.000 |
| `country_of_origin` | 2/0/2/24/0/0/0 | unchanged | 0.500 | 1.000 |
| `date_of_manufacture` | 1/0/4/20/0/0/3 | unchanged | 0.200 | 0.000 |
| `date_of_packing` | 1/0/4/23/0/0/0 | unchanged | 0.200 | 1.000 |
| `net_quantity` | 3/0/13/9/0/0/3 | unchanged | 0.188 | 0.333 |
| `retail_sale_price` | 3/0/7/13/0/0/5 | unchanged | 0.300 | 1.000 |
| `unit_sale_price` | 1/0/5/19/0/0/3 | unchanged | 0.167 | 1.000 |
| `packer_name` | 0/0/2/26/0/0/0 | unchanged | 0.000 | — |
| `date_of_import`, `importer_name`, `other` | no annotated positives | unchanged | — | — |

**`batch_number` recall fell from 0.250 to 0.125, and that is the change
working.** Both of its baseline "true positives" carried the value `No` or
`Ni` — the label's own abbreviation of *number*, captured because the pattern's
optional qualifier group let the value group backtrack onto it. Both were
scored `uncertain: False`, so `field_presence` passed on a package whose batch
code nobody had read, and one of the two was the dataset's only fabricated
value. The metric rewards a detection carrying a wrong value exactly as much as
one carrying a right value; removing these two costs recall and is
unambiguously correct.

### 11.7 Regression check by condition

`docs/evaluation-strategy.md` requires results per condition, because an
average over easy and hard images hides exactly the cases that matter. Counting
scored disagreements per condition label, baseline → final:

| Condition | n | Disagreements | Characters | EMPTY |
|---|---:|---:|---:|---:|
| `full_panel` | 11 | 74 → **72** | 9,162 → 9,572 | 1 → 0 |
| `small_print` | 8 | 61 → 61 | 7,177 → 7,587 | 1 → 0 |
| `curved_surface` | 10 | 47 → 47 | 4,783 → 5,193 | 1 → 0 |
| `glare` | 12 | 45 → **43** | 6,965 → 7,431 | 1 → 0 |
| `plastic_film` | 8 | 30 → 30 | 3,651 → 4,117 | 1 → 0 |
| `partial_crop` | 4 | 29 → 29 | 1,213 → 1,623 | 1 → 0 |
| `unlabelled_value` | 4 | 27 → 27 | unchanged | 0 → 0 |
| `stamped_ink` | 3 | 19 → 19 | unchanged | 0 → 0 |
| `crinkled_film` | 3 | 16 → 16 | unchanged | 0 → 0 |
| `devanagari` | 4 | 16 → **14** | unchanged | 0 → 0 |
| `bilingual` | 2 | 15 → **13** | unchanged | 0 → 0 |
| `declaration_closeup` | 2 | 13 → 13 | unchanged | 0 → 0 |
| `declaration_panel` | 2 | 12 → **11** | unchanged | 0 → 0 |
| **`rotated_90`** | 4 | **10 → 10** | unchanged | 0 → 0 |
| `tilted` | 1 | 8 → 8 | unchanged | 0 → 0 |
| `symbol_indirection` / `embossed` | 1 | 6 → **5** | unchanged | 0 → 0 |
| `label_value_split` | 1 | 6 → 6 | unchanged | 0 → 0 |
| `blank_declaration` | 1 | 5 → **3** | unchanged | 0 → 0 |
| `branding_panel` | 13 | 5 → 5 | 1,316 → 1,782 | 1 → 0 |
| every other label | — | unchanged | unchanged | 0 → 0 |

**No condition got worse on any of the three counts.** The two that improved
most are the two the changes were aimed at: `blank_declaration` (the pack that
prints `Batch No. :` and stamps nothing) and `declaration_panel`.

**`rotated_90` is unchanged, and that is the honest headline for orientation.**
Four photographs carry text running at 90° to the frame; they contribute ten
scored disagreements and this branch recovered none of them. §11.4 explains why
the obvious mechanism was rejected rather than shipped.

### 11.8 Which change did what

Running pipeline **0.2.0** (no retry) against the new extraction rules
separates the two halves cleanly:

| | Recall | Precision | Value acc. | Silent err. | Fab | Chars | EMPTY |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline 0.2.0, old rules | 0.200 | 0.947 | 0.611 | 0.417 | 1 | 13,929 | 2 |
| 0.2.0, new extraction rules | 0.211 | 1.000 | 0.684 | 0.300 | 0 | 13,929 | 2 |
| 0.3.0 (adds the retry) | 0.211 | 1.000 | 0.684 | 0.300 | 0 | **14,805** | **0** |

**Every scored improvement came from the extraction layer.** The OCR change
recovered 876 characters and moved two photographs out of EMPTY while changing
no scored metric. That is a real improvement for a reviewer — EMPTY means "we
could not read this photograph", COMPLETED with no fields means "we read it and
these declarations were not on it" — and it should not be presented as more.

### 11.9 What changed in the code

| Change | Layer | Why |
|---|---|---|
| `TesseractOptions.fallback_page_segmentation_mode = 11` | OCR | one extra pass, **only when the primary mode recognised nothing at all**. Zero is the trigger, not a threshold: a threshold would be a number nobody measured and would re-segment images that read fine |
| `patterns._NOT_A_BATCH_VALUE` | extraction | `no`, `nos`, `number` and `code` belong to the batch keyword, never to its value. Word-bounded, so `Batch: NO123` and `Batch Code: CODE45` still match |
| `patterns.BATCH_NUMBER_ANCHOR` | extraction | a named batch declaration with no readable code is now reported as an *unread declaration*. Requires the explicit qualifier, because `batch` and `lot` are ordinary English words |
| `rule_based._could_be_a_name` | extraction | a name contains at least one letter. Aimed at exactly one failure — `Manufactured by: #` — and deliberately no stronger |
| `RuleBasedFieldExtractor(read_name_from_next_line=True)` | extraction | a name keyword that ends its line takes the line below, always flagged uncertain with the reason attached. The same mechanism `_dates` already uses |
| `patterns.TOLL_FREE_PHONE` | extraction | two *or three* groups after `1800`, matching the printed groupings. The leading word boundary keeps FSSAI licence numbers out |
| Pipeline version 0.2.0 → 0.3.0 | registry | 0.2.0 and 0.1.0 stay registered, so a stored run stays re-runnable and each change can be isolated on any image |

### 11.10 Remaining failure modes, classified

Of the 71 remaining false negatives and 24 missed unread declarations:

| Cause | Examples | Fixable by |
|---|---|---|
| **OCR recognition** (dominant) | `500 g` → `5009` and `200 g` → `200 9` on three packs — the `g` read as `9`; `1 kg` → `i`; batch code `GN30A60040` → `B GN30AG00d"` | a better engine or better language data, not a pattern |
| **OCR recognition — character set** | every `₹` on every pack | §11.3. `eng` cannot emit the glyph |
| **OCR recognition — mangled keyword** | `MANUFACTURED` → `WANUFACTURED`; `Use By` → `ie By` and `Use @ By` | ditto. Loosening the keyword to match these would match prose |
| **Layout association** | `p003_03_right` prints `MRP (INCL. OF ALL TAXES), USP, #MFD. & @USE BEFORE: SEE BELOW` and then `#12/25 @04/28` — a legend defining symbols, resolved two rows down | column and legend analysis this layer does not have. Standing ruling 9 in the verification log expressly declines to apply positional pairing to symbol indirection |
| **Layout association** | `p010_01_back` names `Unit Sale Price` in a legend box and prints the rate in a stack above it | ditto |
| **Extraction** | `BEST BEFORE TWO MONTHS AFTER PACK` — `DURATION` matches digits, not spelled-out numbers | a pattern change. Not made: it was found by reading one photograph, and one cell is not evidence that it generalises |
| **Extraction** | `Batch Ni` still yields the value `Ni` | the keyword guard covers `no`/`nos`/`number`/`code`; extending it to OCR misspellings of those would be tuning to this dataset |
| **Preprocessing** | full-frame photographs give the declaration panel ~10% of the pixels | region detection — still absent, still not faked |

### 11.11 What this section does and does not license

**It supports:** stating that precision reached 1.000 and the fabricated-value
count reached 0 **on this 364-cell partially verified artefact**; that the
silent error rate fell from 0.417 to 0.300 across ten committed unhedged
readings; that no photograph in the set now returns EMPTY; and that the ₹
limitation and the OSD limitation are measured facts about this engine
configuration.

**It does not support:** calling the dataset human-verified; quoting precision
1.000 as a property of the extractor — the denominator is 19 detections over 28
photographs of 10 products, four of which share a back-of-pack template;
quoting the silent error rate as reliable on a denominator of 10; any claim
that recall improved materially, because +0.011 is one cell; or any claim about
legal compliance. Recall remains **0.211**: the pipeline still misses roughly
four readable declarations in five, and §11.2 says why — the text is not being
recognised in the first place.

### 11.12 Recommended next task

Measure a second engine, or additional language data, against this same frozen
set, and publish the comparison here:

- **PROBLEM** — recognition, not interpretation, is the binding constraint: 55
  of 97 disagreements are values the engine never read, and `₹` is unreadable
  by construction.
- **INPUT / OUTPUT** — unchanged. `interfaces.OcrEngine` already isolates this,
  and `registry` is keyed by name and version so two engines can be compared on
  the same images.
- **DATA** — `our-eval-v0.3-usp-partial`, unchanged and unedited. Re-verify
  `p010_01_back` with a second person first (§10).
- **MODEL / CANDIDATES** — `tesseract-ocr-hin` (an OS package install, no
  weights in Git, and it carries `₹`) is the cheapest test and should be run
  before any neural engine. PaddleOCR and docTR ship weights that would have to
  be fetched, cached and checksummed, and their install cost falls on six people
  across three operating systems.
- **PREPROCESSING** — unchanged, so the engine is the only variable.
- **METRICS** — the ones in this file, plus CER and WER, which need
  `reference_text` on at least a few samples and do not exist yet.
- **LATENCY / HARDWARE** — the current median is ~1.1 s per image on CPU.
  Anything materially slower needs its own justification against the demo
  budget.
- **LIMITATIONS** — a language pack changes what every stored run would produce,
  so it needs a new pipeline version rather than a configuration tweak.
- **INTEGRATION** — none required beyond registration:
  `extraction_service.py` resolves pipelines by name and version and imports
  nothing else from this package.
