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

**That trade-off has now been measured once**, on 28 annotated photographs — see
[`docs/evaluation-results.md`](../docs/evaluation-results.md) and the summary
under [METRICS](#metrics). The measurement supports the concern: recall is 0.205,
and the conditions that describe most hand-photographed retail packaging —
cropped declarations, packs shot on their side, creased film — scored zero
recall. CER and WER remain unmeasured.

The engine is swappable without touching Django: `extraction_service.py` is the
only backend module that reaches the runtime here - `registry`, `pipeline`,
`exceptions` or an engine - and it resolves pipelines by name and version. Only
the dependency-free `contracts` vocabulary is imported elsewhere in the backend. See [`docs/ml-integration.md`](../docs/ml-integration.md).

## PREPROCESSING

`preprocessing/pillow_preprocessor.py`, behind `interfaces.ImagePreprocessor`.
Pillow rather than OpenCV: it is already a backend dependency, so this stage
adds no install for anyone, and OpenCV's extra transforms are ones we cannot
yet show are an improvement.

### What the `tesseract` pipeline applies, in order

1. **EXIF orientation.** Phone cameras store a landscape frame plus a rotation
   tag. Tesseract reads pixels and ignores the tag, so a portrait photo arrives
   sideways and recognition collapses. This is the transform that justifies the
   stage existing.
2. **Grayscale.** Colour carries nothing for recognition.
3. **Upscale to a 3200 px longest side, capped at 2×** (`min_dimension`,
   `max_upscale_factor`). Added in pipeline 0.2.0. Messaging apps re-encode a
   phone photo down to roughly 900×1600, and at that size the declaration block
   on a 120 ml can is 8–10 px tall — below the ~20 px x-height Tesseract's LSTM
   recogniser expects. A full-resolution phone photo is already past 3200 px
   and is left alone, so this only fires on the images that need it.
4. **Contrast normalisation** (`autocontrast`, 1% cut-off each end), so one
   specular highlight cannot define "white" for the whole panel.

Upscaling is requested by `tesseract.build_pipeline()`, not defaulted inside
`PreprocessingConfig` — a bare `PillowPreprocessor()` stays conservative,
because it is this *combination* (these transforms plus `--psm 3`) that was
measured, not the transform on its own.

### Bounding boxes come back in source-image space

Resizing used to be unusable for exactly one reason: it moved every box into
the intermediate's coordinate system, so an evidence overlay drawn on the
original photograph would point at the wrong part of the package — and nothing
would fail while it did.

`ExtractionPipeline` now maps boxes back before field extraction runs, using
the two dimension sets it already holds. `metadata["bounding_box_space"]` says
which space the boxes are in (`"source"`, or `"preprocessed"` when a
preprocessor did not report its dimensions and no honest mapping was possible)
and `metadata["preprocessing_scale"]` records the factors applied. Consumers
should read that key rather than assume.

The engine's `raw` word geometry is deliberately left in engine space: `raw` is
documented as verbatim engine output, and rewriting coordinates inside it would
make the orchestrator depend on which engine ran.

### Measured and rejected

Each of these was run over the six Product 001 photographs and either made the
result worse or changed nothing. They are recorded so nobody repeats the
experiment:

| Technique | Outcome |
|---|---|
| **Sharpening** (unsharp mask) | Fewer declarations recovered on the close-up at every page-segmentation mode tried. Not implemented |
| **Binarisation** (global Otsu) | Neutral to worse. One global threshold cannot serve a cylindrical can lit from one side. A *local* threshold might, and needs numpy |
| **Denoising** (`denoise`, still available, off) | Recovered nothing new and cost recognised characters. It erases the strokes of 6-point print — the size at which net quantity and batch number are printed |
| **3× upscaling** | Worse than 2×, and ~40% slower again. Enlarging invents no detail |
| **RGB instead of grayscale** | Worse, and roughly 1.5× the time |

Not implemented: **deskew and perspective correction.** Genuinely useful for
hand-held photos of curved packaging, and not implementable well without
numpy/OpenCV. Stated as a limitation rather than approximated badly.

Not implemented: **cropping to the label.** The largest single failure on the
Product 001 set is that a full-frame photograph gives the declaration panel
~10% of the pixels, and no tonal transform recovers it. The fix is region
detection — a component this package does not have and must not fake.

Intermediates are written to a directory the preprocessor owns and deleted by
`release()` as soon as the pipeline is done. The original is never modified —
it is the evidence a disputed finding is checked against.

## PAGE SEGMENTATION

`--psm 3` (fully automatic segmentation) since pipeline 0.2.0, configurable via
`TesseractOptions.page_segmentation_mode`.

It was `--psm 6` ("a single uniform block of text"), which is right for an
already-cropped panel and wrong for what people actually upload: a product
standing on a desk, where mode 6 lets the desk, the laptop and the window take
part in the line structure.

**No mode is universally best, and these were compared rather than assumed.**
Modes 3, 4, 6, 11 and 12 were each run over all six photographs:

| Mode | What happened |
|---|---|
| 3 — automatic | Chosen. Best on the declaration close-up **once upscaling precedes it**. At the original size it found no text at all on two of the six images |
| 4 — single column | Consistently between 3 and 6; never best at anything |
| 6 — single block | The previous default. Reads more characters on cluttered frames, and more of them are wrong |
| 11 / 12 — sparse text | Fragmented the declaration block into 2–3× as many lines and cost extracted fields |

Mode 3 and the upscaling were chosen together and should be changed together —
mode 3 on un-upscaled images is worse than what it replaced.

Those five modes were re-measured over all **28** photographs of
`our-eval-v0.3-usp-partial` in pipeline 0.3.0, and mode 3 remains the right
primary mode. The full table is
[`docs/evaluation-results.md`](../docs/evaluation-results.md) §11.5; the short
version is that mode 6 reads 43% more characters and more of them are wrong
(value accuracy 0.611 → 0.429, silent error rate 0.417 → 0.571), and mode 11
raises value accuracy to 0.714 by finding four fewer true positives.

### One retry, and only when nothing at all was recognised

Mode 3 does not degrade gracefully. On a photograph whose layout it cannot
resolve it returns **zero** words rather than a poor reading, and the pipeline
reports `EMPTY` — which tells a reviewer nothing except "take another photo".
It did that on 2 of the 28 photographs: a cylindrical tube shot side-on and a
glare-lit printed film.

Since 0.3.0, an empty first pass is retried once with `--psm 11`
(`TesseractOptions.fallback_page_segmentation_mode`). Three things make this
safe rather than a second guess at the right mode:

- **The trigger is zero recognised blocks**, not "few" or "low confidence". A
  threshold would be a number nobody measured and would re-segment images the
  primary mode read perfectly well. Zero is the one case where there is nothing
  to lose, because the alternative outcome is already "we recognised no text".
- **It cannot chain.** The retry runs with its own fallback cleared.
- **It is recorded.** `OcrResult.raw` carries
  `requested_page_segmentation_mode`, the mode that actually produced the
  result, and `used_fallback_segmentation`.

**11, not 6, and the difference was measured.** Mode 6 recovers the most
characters of the four candidates and was rejected for it: among the extra text
it finds on the side-on tube is the line `4 rs ne rm`, which the price
detector's speculative no-keyword branch reads as a retail sale price of 4 —
on a panel whose price a human annotator recorded as unreadable. Mode 11
recovers 876 characters, moves both photographs out of `EMPTY`, and **changed no
scored outcome at all**. Median latency over the set was unchanged, because the
retry only ever runs where the first pass produced nothing.

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
| Unit sale price | `unit_sale_price` | `{amount (exact decimal string), currency, per_unit, per_measure}` — the unit **as printed**; no base conversion. **Recall 1/6 on `our-eval-v0.3-usp-partial` — see below** |
| Batch / lot number | `batch_number` | `{batch_number}` — the keyword's own `No.` / `Number` / `Code` is never taken as the value; a named batch declaration with no readable code is reported unread instead |
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

Two rules apply to every name in that list, both added in 0.3.0 and both
measured (`docs/evaluation-results.md` §11.5):

- **A name contains at least one letter.** `Manufactured by: #` is not a
  manufacturer called `#`; it is a keyword whose value line was not recognised.
  Deliberately no stronger than that — no word list, no length floor, no
  capitalisation rule — because `3M India`, `S. K. Foods` and `A1 Foods` are all
  real and every stricter rule drops one of them.
- **A name keyword that ends its line takes the line below**, and says so:
  the field carries `the name was read from the line after the keyword; it may
  belong to a different declaration`, and `raw_value` quotes both lines. The
  same one-line lookahead `_dates` already uses, for the same layout. It is a
  guess about layout, which is why it is never committed to silently, and it is
  turned off with `RuleBasedFieldExtractor(read_name_from_next_line=False)`.

### NOT supported — do not claim otherwise

| Declaration | Why not |
|---|---|
| **Product / brand name** | No reliable textual anchor. It is the largest text on the front panel, which is a *layout* signal this layer does not have |
| **Common or generic name** (`common_or_generic_name`) | Same problem. A keyword-anchored detector (`COMMODITY :`, `Name of Commodity`) was investigated and **not** built: measured across the 674 lines the current pipeline reads from the 28 frozen photographs, such a keyword appears on **1 panel of 28**. `rules/INVENTORY.md` names entry into `SUPPORTED_KEYS` as the condition for reactivating `LM-PC-0002`, so shipping 3.6 % recall as "supported" would invite exactly the false `NON_COMPLIANT` on 27 of 28 panels that deactivating the rule was meant to prevent |
| **Manufacturer address** (`manufacturer_address`) | Spans several lines below the name; needs real layout analysis. Distinguishing it from the packer, importer and consumer-care addresses needs the same. Measured on the frozen set: a manufacturer-name anchor appears on 4 of 28 panels and a 6-digit PIN on 5, and one panel prints `IN CASE OF CONSUMER COMPLAINTS, CONTACT: ADDRESS MENTIONED AT MANUFACTURED BY` — proof the roles are distinct in practice |
| Any non-English text | Tesseract recognises Devanagari when `tesseract-ocr-hin` is installed; no pattern here matches it |

`SUPPORTED_KEYS` and `UNSUPPORTED_KEYS` are exported from
`labelextract.fields`, and `UNSUPPORTED_KEYS` is *derived* from the full
vocabulary rather than maintained by hand — so this table cannot silently drift
away from the code. A test asserts the two partition `LabelFieldKey`.

### "Supported" means attempted, not measured, and never means compliant

Three separate claims, and a row in the table above makes only the first:

1. **The extractor attempts this declaration.** That is all `SUPPORTED_KEYS`
   asserts. It is a statement about our code, not about any package.
2. **The extractor reads it reliably.** A *separate* claim, and one only an
   evaluation run can make. Twelve of the fourteen supported keys are annotated
   in `our-eval-v0.1-draft` and appear in the per-declaration table in
   [`docs/evaluation-results.md`](../docs/evaluation-results.md).
   **`unit_sale_price` is not one of them**, because it was added after that set
   was frozen. It is now measured against **`our-eval-v0.3-usp-partial`**, the
   successor carrying the first human corrections; §10 of that document reports
   the run in full, and §9 records the earlier `our-eval-v0.2-usp-draft` run it
   supersedes. The short version, and the only part safe to repeat:

   > **Recall 1 of 6 readable declarations (0.167).** No fabricated value and no
   > false-positive detection were observed **for this declaration** in the
   > evaluated 364-cell dataset — an observation on partially verified ground
   > truth (34 of 364 cells human-reviewed), not a property of the extractor.
   > The dataset as a whole carries one of each, in `batch_number`. **Precision
   > and value accuracy are both 1.000 on a denominator of one detection, and
   > the negatives surfaced no candidate text at all, so neither figure means
   > anything.**

   Most of the misses are OCR failures rather than extraction failures. Quote the
   recall, with its denominator; quote neither of the other two.

   **Three things that are not the same claim**, and the distinction matters more
   than the number:

   - **Evaluation baseline** — `our-eval-v0.3-usp-partial` is the dataset the
     figures above are measured against. That is all "baseline" means.
   - **Partial human verification** — 34 of its 364 cells have been reviewed by a
     person, including every cell that carries this metric. The other 330 remain
     model-drafted. **The dataset is not human-verified**, and must not be
     described as such.
   - **Independent human verification** — stricter still, and *not* claimed for
     this column: `p010_01_back`'s value was confirmed only after the verifier
     had been exposed to panel-distinguishing information, and 17 negatives were
     never reviewed at all. See the caveats in §10.

   Per-cell provenance for every decision, objection and correction is in
   `ml/data/human-verification/VERIFICATION-LOG.md`.
3. **The corresponding legal requirement can now be evaluated.** Not implied by
   either of the above, and **not true for rule 6(11)**. Reading a unit sale
   price off a label says nothing about whether one was required — that turns
   on the net-quantity band, and the rule exempts a package whose retail sale
   price equals its unit sale price. Both are decisions for the rules layer,
   both need `format_check` and `numeric_check`, and neither check type is
   registered. This package extracts evidence; `apps.rules` decides what it
   means. See `rules/INVENTORY.md` for the requirement's status.

Nothing on this branch activated a legal rule. `LM-PC-0002` and every other
inactive rule remain `is_active: false`, and extraction work is never on its own
a reason to change that.

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
| `UNIT SALE PRICE : ₹2.91 PER GRAM` | emitted, certain — and **not** also emitted as a retail sale price |
| `₹0.08 per g` | emitted, **uncertain** — a rate with no keyword naming the declaration |
| `0.08 per g` | **not emitted** — no currency and no keyword is not enough to call it a price |
| `MRP ₹200/kg` | emitted as a retail sale price only. One declaration written as a rate, not two |
| `Ascorbic Acid USP` | **not emitted, and not reported unread** — on a supplement label `USP` is *United States Pharmacopeia* |
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

### When a declaration is named but its value cannot be read

There is a third outcome, and it is the one an empty `fields` tuple used to
hide.

On `04_right_clean` — the can photographed side-on — OCR returned the single
line `MRP` and nothing else, because the rest of that line curves away from the
camera and was never recognised. The extractor did the right thing and emitted
no field: a keyword is not a price, and inventing `0` or guessing at the digits
would be worse than saying nothing.

But "no MRP field" then meant two opposite things at once:

| What happened | What a rule engine sees today |
|---|---|
| The package carries no MRP at all | no `retail_sale_price` field |
| The MRP is printed and we could not read it | no `retail_sale_price` field |

The first is a potential violation. The second means *photograph the panel
again*. Nothing in the output told them apart.

`ExtractionResult.metadata["unread_declarations"]` now does. Each entry names
the declaration, quotes the line the keyword was read from, and carries that
line's box and confidence:

```json
"unread_declarations": [
  {"key": "retail_sale_price", "evidence_text": "MRP",
   "box": {"x": 513, "y": 1240, "width": 28, "height": 12}, "confidence": 0.93}
]
```

**It carries no value, and it is deliberately not an `ExtractedField`.** A
presence check passes on any extracted field regardless of its uncertainty
flag, so a value-less field here would record the package as having declared an
MRP nobody could read — turning a possible violation into a pass. Absence of a
field stays absence; this is a separate observation alongside it.

It reports **only what is unambiguous**, which costs recall on purpose:

| Line | Reported? |
|---|---|
| `MRP` | yes — nothing else is phrased this way |
| `Net Qty:`, `Best Before`, `Date of Import` | yes |
| `NET` alone | **no** — the keyword needs a following word (`net qty`, `net weight`); `NET` on its own could begin any of them, or nothing |
| `the quantity supplied may vary` | **no** — "quantity" is an ordinary English word and appears in prose. Extraction still reads `Quantity: 500 g`, because there a number and a unit are present; only *bare-keyword evidence* uses the stricter `NET_QUANTITY_ANCHOR` |
| `Packed by BAZINGA MEDIA` | **no** — the packing-date keyword matches the bare stem `packed`, so reporting `date_of_packing` here would claim a declaration the label does not make |
| `Manufactured by …` | **no** — same collision with `manufactured` |
| `Customer Care` with no number | **no** — the extractor already emits a keyword-only field marked uncertain, so it is not unresolved |
| `MANUPACTYD. is .` | **no** — misrecognised text names nothing |

**This is a lower bound, not a list of everything that was missed.** It can only
report a keyword that was itself recognised. On `02_back_clean` the MRP is
printed on the package and the keyword was never read, so nothing is reported —
the output is silent about a declaration that is genuinely there.

Nothing here is a legal claim. That a keyword was printed says nothing about
whether the declaration was required, or whether its value would have been
correct. **No compliance rule consumes this yet**; it exists so that a
deterministic engine can eventually distinguish "absent" from "unreadable"
instead of guessing.

## DATA

**No dataset, model weight, or label photograph is committed to this
repository, and none is downloaded at runtime.** `.gitignore` blocks
`ml/models/`, `ml/artifacts/`, every common weight extension, and everything
under `ml/data/` except its README and the `.gitkeep` files holding the empty
folders open.

Local photographs for hand-running the pipeline go in `ml/data/raw/products/`.
[`ml/data/README.md`](data/README.md) covers where images go, how to name them,
what must not be in frame, and the exact CLI command.

Tesseract's language data is installed by the OS package manager. There is
nothing for this project to host, checksum or version.

Datasets for evaluation are described in
[`docs/data-strategy.md`](../docs/data-strategy.md), which distinguishes four
kinds that must not be conflated: general OCR datasets, packaging/product-label
datasets, Indian/multilingual label datasets, and our own annotated evaluation
set. **A generic scene-text dataset is not a Legal Metrology dataset**, and a
number measured on one says nothing about performance on the other.

## METRICS

**A first baseline has been measured. CER and WER still have not.** The full
report — dataset, per-field and per-condition results, failure analysis and
limitations — is [`docs/evaluation-results.md`](../docs/evaluation-results.md).
[`docs/evaluation-strategy.md`](../docs/evaluation-strategy.md) defines the
method it follows.

### Latest — `tesseract` 0.3.0 on `our-eval-v0.3-usp-partial`, 2026-08-31

28 photographs, 364 annotated cells, **34 of them human-reviewed and 330
model-drafted**. That last clause is not a footnote: these figures measure the
pipeline against a *partially verified* artefact and must never be quoted as
performance against human ground truth.

| | 0.2.0 | **0.3.0** |
|---|---:|---:|
| Precision | 0.947 (18/19) | **1.000** (19/19) |
| Recall | 0.200 (18/90) | **0.211** (19/90) |
| F1 | 0.330 | **0.349** |
| Value accuracy | 0.611 | **0.684** |
| Silent error rate | 0.417 (5/12) | **0.300** (3/10) |
| Fabricated values | 1 | **0** |
| Correct unread | 0 of 24 | **1** of 25 |
| Photographs returning `EMPTY` | 2 of 28 | **0 of 28** |
| Median latency | 1,126 ms | 1,081 ms |
| CER / WER | unavailable | unavailable |

Read the shape, not the headline. **Precision 1.000 does not mean the system is
right**: it means that across 19 detections on 28 photographs it did not report
a declaration that was not there, while still missing roughly four readable
declarations in five. The recall gain is one cell. What actually improved is the
*failure behaviour* — no fabricated value, one fewer confident wrong reading in
three, and no photograph that comes back saying nothing at all.

Where the remaining recall is lost was measured before anything was changed:
**55 of the 97 scored disagreements are values OCR never read**, against 9 it
read exactly and the extractor did not use. `₹` is unreadable by construction —
Tesseract's `eng` model cannot emit the glyph, reproduced on clean synthetic
type as well as on the photographs. `docs/evaluation-results.md` §11 has the
diagnosis, the full experiment record including the rejected experiments, and
the next task.

### First baseline — `tesseract` 0.2.0 on `our-eval-v0.1-draft`, 2026-08-29

28 photographs of 10 packages:

| | |
|---|---:|
| Precision | 0.944 (17/18) |
| Recall | 0.205 (17/83) |
| F1 | 0.337 |
| Value accuracy | 0.588 |
| Silent error rate | 0.455 |
| Correct unread | 0 of 23 |
| Median latency | 2202 ms |
| CER / WER | unavailable — no hand transcription exists |

Read that shape before the headline. Precision 0.944 does **not** mean the system
is 94% right: it means that on the rare occasions it reports a declaration it has
usually found a real one, while missing four readable declarations in five, never
once correctly flagging an unreadable declaration as unread, and being wrong
about half the time when it commits without hedging. Three caveats bound every
number: the ground truth was drafted by a model and is **not yet
human-verified**; N is 28, from 10 products, four of which share one
back-of-pack template; and the Tesseract installation had `eng` data only, so the
Devanagari and Gujarati content in 5 of 28 panels was unreadable by
construction.

### The apparatus, and how to re-run it

`labelextract.evaluation` implements the method that document describes: a
frozen dataset with a version and a checksum per image, hand-written
annotations kept structurally apart from the pipeline's output, and scoring
that reports a metric as unavailable rather than estimating it.

```bash
cd ml
# The first baseline, against the v0.1 artefact.
python -m labelextract.evaluation.cli validate data/our-evaluation-set
python -m labelextract.evaluation.cli run data/our-evaluation-set \
    --pipeline tesseract --pipeline-version 0.2.0 \
    --report data/our-evaluation-set/baseline-report-v0.2.0.json

# The current run, against the partially human-verified v0.3 artefact.
python -m labelextract.evaluation.cli validate data/hv-evaluation-set
python -m labelextract.evaluation.cli run data/hv-evaluation-set \
    --pipeline tesseract --pipeline-version 0.3.0 \
    --report data/hv-evaluation-set/report-v0.3.0.json
```

Three pipeline versions stay registered — 0.1.0, 0.2.0 and 0.3.0 — so a stored
run keeps resolving and any single change can be isolated on one image:

```bash
python -m labelextract.cli LABEL.jpg --pipeline-version 0.2.0   # no retry
python -m labelextract.cli LABEL.jpg --pipeline-version 0.3.0   # with it
```

A version pins the **engine and preprocessing configuration** written out in
each factory. It does not pin `fields/patterns.py`, which every registered
pipeline imports from one module: a pattern corrected today changes what 0.1.0
reads too. That has always been true and is stated rather than implied — a run
whose extraction rules must be reproduced exactly needs the commit, not the
version string.

**The dataset is not in this repository.** `ml/data/` is git-ignored in full, so
`our-eval-v0.1-draft` exists on one machine; what is committed is this code, the
tests that pin the format, and the report. None of the tests is a measurement —
they run over synthetic manifests and PNGs the tests build byte-by-byte. The
format is documented in [`ml/data/README.md`](data/README.md).

## PRODUCT 001 — what changed between 0.1.0 and 0.2.0

Six photographs of one product: four full-frame views, one close-up of the
declaration panel, one angled close-up with the panel clipped at the frame
edge. All are 899×1599 (messaging-app re-encoded, ~1.4 MP).

**Ground truth was transcribed by a human reading the images** — that is a
manual assessment, not an annotation pipeline, and it covers one product.

"Declarations" below counts how many of 17 hand-transcribed declaration
fragments appear verbatim in the recognised text. "Fields" counts what
`RuleBasedFieldExtractor` actually returned.

| Image | Declarations before → after | Mean block confidence | Fields | Time (ms) |
|---|---|---|---|---|
| `01_front_clean` | 0/6 → 0/6 | 0.38 → **0.87** | 0 → 0 | 380 → 720 |
| `02_back_clean` | 1/17 → 1/17 | 0.43 → 0.56 | 0 → 0 | 867 → 1429 |
| `03_left_clean` | n/a (no declarations visible) | 0.28 → 0.33 | 0 → 0 | 312 → 780 |
| `04_right_clean` | 0/17 → 0/17 | 0.36 → 0.52 | 0 → 0 | 545 → 907 |
| `05_declaration_closeup` | 13/17 → 13/17 | 0.56 → **0.67** | **5 → 6** | 760 → 1300 |
| `06_declaration_closeup_angled` | 0/17 → 0/17 | 0.53 → **0.75** | 0 → 0 | 573 → 988 |

**The fragment count barely moves, and it is the wrong thing to look at.** What
changed is whether the values are *right* — on `05`, the one image whose
declarations are legible at all:

| Declaration | 0.1.0 | 0.2.0 | Truth |
|---|---|---|---|
| MRP | `8349.00`, flagged **certain** | `349.00` | ₹349.00 |
| Street number | `5/2` | `5/1` | 5/1 |
| Customer care | `38671625` (8 digits) | `8867162397` (10 digits, one wrong) | 8867162337 |
| Best before | not extracted | extracted, certain | 2 years from MFG. DT. |
| Village | `MADANAYAKANAHALLL` | `MADANAYAKANAHALLI` | MADANAYAKANAHALLI |

The MRP is the one that matters. 0.1.0 read the ₹ sign as an `8` and reported
**₹8349.00 as a certain value** — a 24× error on the most legally significant
number on the package, with nothing to signal it. At 2× the ₹ is recognised as
a currency symbol rather than a digit, and the amount parses correctly.

Two changes that the fragment count also misses, both manual assessment:

- `01_front_clean` went from `- i / fy) [CLEANE? / Z N sovancl` (noise at 0.38)
  to `ADVANCED FO / FORMULA / KILLS ODOUR / BACTERIA / SAFE FOR SK / LEAvEs A
  PL / FRAGRANCE` (0.87). Readable, still truncated where the text curves round
  the can — which is why the strict fragment count still scores it 0/6.
- `03_left_clean` now reads `SHINE X PRO` off the vertical logo; before, noise.

**The cost is time**: 3.4 s → 6.1 s for six images, ~78% slower, from
recognising 4× the pixels. On a laptop, per uploaded image, that is 0.6 s →
1.0 s.

**What did not improve at all:** `02` and `04` still yield zero declarations.
On a full-frame photo the declaration panel is ~10% of the image and its text
is 8–10 px tall, curving round a cylinder. No preprocessing tried recovers it,
and the honest answer for those photographs is that the panel needs to be
photographed closer — which is what `EMPTY`/review exists to say.

Reproduce any of this with the commands under
[Evaluating Product 001](#evaluating-product-001).

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
- **Recognising a keyword is not reading a declaration.** `04_right_clean`
  returns the lines `NET` and `MRP` and no values at all. `MRP` is reported in
  `unread_declarations`; `NET` is not, because the bare word names nothing
  unambiguously. Both are cases where the label plainly carries a declaration
  and this system cannot report what it says.
- **A declaration panel photographed from across the table cannot be read.**
  Measured on Product 001: at ~10% of the frame and 8–10 px of text height,
  every configuration tried returned zero declarations from the full-frame
  views while happily returning the marketing paragraph above them. Nothing
  warns the user that the *legally relevant* part of the label is the part that
  was missed.
- **The rupee sign is unreliable.** It has been read as `8` and as `€`. When it
  is read as a digit the amount is wrong *and* certain, which is the worst
  combination this system can produce. Nothing repairs OCR confusions by
  design — see NORMALISATION — so a reviewer is the only guard.
- **Bounding boxes are mapped back to source space** whenever the preprocessor
  reports its dimensions; when it does not, they stay in preprocessed space and
  `metadata["bounding_box_space"]` says so. The engine's `raw` word geometry is
  always in engine space.
- **Recognition cost scales with pixels.** Upscaling roughly doubles per-image
  time. Measured on one laptop, on one product: ~0.6 s → ~1.0 s per image.
- **Extraction confidence is not compliance confidence.** Reading `500 g`
  correctly says nothing about whether 500 g was declared correctly.
- **The system assists a reviewer. It does not certify compliance.**

## CONFIDENCE

Unchanged by the 0.2.0 preprocessing work, and worth restating because it is
what keeps a bad reading visible:

- Every `TextBlock` carries the engine's score in `[0.0, 1.0]`, or `None` when
  the engine reported none. **`None` means "not reported" and must never be
  read as zero** — the contract and the database column are both nullable for
  that reason.
- A line's confidence is the mean of its words'. A line whose words all lack a
  score stays `None` rather than being given a number nobody measured.
- Mapping a box between coordinate systems never touches confidence. Geometry
  is corrected; a measurement is not.
- `minimum_word_confidence` stays **0** — everything Tesseract reported is kept.
  Filtering low-confidence words would hide exactly the misreadings a reviewer
  needs to see, and the score travels with each block anyway.
- `confidence` (the engine's opinion of the *characters*) and `uncertain` (the
  extractor's opinion of the *interpretation*) are different axes and are never
  combined. A perfectly recognised `03/04/2025` is high-confidence and
  uncertain at once.

**Low confidence is never turned into a compliance finding, and no legal
conclusion is drawn from a confidence value.** The compliance engine decides
deterministically from normalised values and verified rules; recognition
confidence is evidence shown to a reviewer, not an input to a verdict.

## INTEGRATION

```
backend  ──imports──▶  labelextract        (one direction, enforced by layout)
```

`labelextract` never imports Django, never touches the database, never sees an
HTTP request. The only backend module that runs an engine is
`backend/apps/extraction/services/extraction_service.py`, which resolves
pipelines by name and version through `registry`. `contracts` is the one module
imported more widely - `apps.rules.checks.field_presence` reads `LabelFieldKey`
from it - because a shared vocabulary is the point of it.

Switching engines is two values in `.env` and no code change:

```
DEFAULT_EXTRACTION_ENGINE_NAME=tesseract
DEFAULT_EXTRACTION_ENGINE_VERSION=0.2.0
```

`/api/v1/health/` then reports `is_placeholder: false` and the UI's "no OCR
engine is installed" notice disappears on its own.

`0.1.0` still resolves and still works — it is the frozen baseline. Selecting
it for a deployment would mean deliberately running the configuration that read
₹349.00 as ₹8349.00.

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
│   ├── fields/               patterns, normalisation, the rule-based extractor
│   └── evaluation/           frozen-dataset schema, scoring and runner
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

A bare `--pipeline tesseract` runs the **newest** registered version. Both are
resolvable, so any change can be re-measured rather than taken on trust:

```bash
python -m labelextract.cli label.jpg --pipeline-version 0.1.0   # frozen baseline
python -m labelextract.cli label.jpg --pipeline-version 0.2.0   # current
```

`0.1.0` is frozen on purpose and should not be tuned again — it is what a
change is compared against, and it keeps runs recorded before 0.2.0
reproducible.

## Evaluating Product 001

Put the photographs in `ml/data/raw/products/product_001/` (git-ignored — see
[`ml/data/README.md`](data/README.md)) and run both versions over each one from
the repository root:

```bash
for f in ml/data/raw/products/product_001/*.jpeg; do
  echo "== $f"
  python -m labelextract.cli "$f" --pipeline tesseract --pipeline-version 0.1.0
  python -m labelextract.cli "$f" --pipeline tesseract --pipeline-version 0.2.0
done
```

A single image, which is the usual case:

```bash
python -m labelextract.cli ml/data/raw/products/product_001/05_declaration_closeup.jpeg
```

What to compare — and what not to:

- **Compare the `fields` array and the values inside it** against the physical
  package. That is the output the compliance engine consumes.
- **Do not compare character counts.** More recognised text is not better text;
  the 0.1.0 run on `02_back_clean` returned the most characters of any run in
  the set and zero declarations.
- **`processing_ms` is a single timing on one machine**, not a benchmark.
- **Nothing here produces an accuracy figure.** Reporting one needs the frozen
  annotated set described in
  [`docs/evaluation-strategy.md`](../docs/evaluation-strategy.md).

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
