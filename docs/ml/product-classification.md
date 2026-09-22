# Product category classification

The first trained model in this repository, and the one sentence that governs
it:

> **The classifier says what kind of product a label *looks like*. The
> applicability engine decides which requirements apply. The rule engine
> decides compliance. The classifier never touches either.**

Everything below follows from that division. It is the same line
[`ai-ml-strategy.md`](../ai-ml-strategy.md) draws for OCR — *AI decides what
the package says; verified rules decide whether that is compliant* — applied
to a second perception task: not "what is printed here" but "what sort of
product prints this".

---

## Status

| | |
|---|---|
| Pipeline | `tesseract` **0.4.0** = 0.3.0 + this classifier. 0.3.0 stays registered without it. |
| Model | `tfidf-logreg` **0.1.0**: TF-IDF (word uni- and bigrams) + multinomial logistic regression |
| Trained on | `product-classification-seed-v0.1`: **33 texts from 10 products**, labels **model-drafted and unverified** |
| Measured | Leave-one-product-out: category **strict accuracy 0.36**, unknown rate 0.33, `packaged-non-food` **never predicted** when its product is held out — and **below a constant "always food" classifier** (macro F1 0.279 vs 0.389). See [Evaluation](#evaluation) |
| Artifact | 119,535 bytes of JSON, committed, evaluated in plain Python; no scikit-learn at runtime |
| Latency | median **0.62 ms** per text for the whole `classify_text` call, on the development machine, artifact pre-loaded — see [Performance](#performance) for exactly what that covers |
| Consumed by | `POST /api/v1/extraction/` and the `extraction` block of every compliance result, as `product_classification`. **Nothing in `apps.compliance` reads it.** |

**What this is:** a reproducible, honestly measured baseline that establishes
the interface, the dataset discipline, the training pipeline and the UNKNOWN
path, and that runs inside the existing extraction pipeline with no new
runtime dependency.

**What this is not:** a product recogniser. Ten products cannot teach a model
what packaged food is, and the cross-validated numbers say so. The shipped
artifact fits the ten products it was trained on and should be expected to
call most unfamiliar labels `packaged-food` or `unknown`. Do not quote its
resubstitution figures as accuracy.

---

## The problem

The compliance engine answers "which rules apply?" from `Product.category`.
Today that category is supplied by a person, through `category_code` on the
analysis request, or not at all — in which case the engine correctly reports
REVIEW REQUIRED with "the commodity category is not known". The transitional
manual applicability form asks the submitter every question the framework
can ask.

The intended direction is:

```
automatic classification
    -> automatic applicability inference (a suggested category, a suggested
       answer to conditions such as cosmetics-and-toiletries)
    -> a person confirms only what the system is unsure of
```

This feature is the first step: a component that reads the recognised label
text and produces a structured, evidenced, *declinable* answer to "what kind
of product is this", in a vocabulary the applicability layer already speaks.
It does **not** wire that answer into applicability yet. See
[Integration with applicability](#integration-with-applicability) for why,
and what the next step is.

## Where it sits

```
IMAGE
  -> validation                    apps/images
  -> preprocessing                 ml/labelextract/preprocessing
  -> OCR                           ml/labelextract/ocr
  -> field extraction              ml/labelextract/fields
  -> PRODUCT CLASSIFICATION        ml/labelextract/classification      <- this
  -> ExtractionResult              metadata["product_classification"]
  -> ExtractionRun.raw_output      persisted verbatim, no schema change
  -> API                           extraction.product_classification
  ...
  -> applicability                 apps/compliance/services/applicability  (does not read it)
  -> rule engine                   apps/compliance/services/engine         (does not read it)
```

`ProductClassifier` is the fourth component interface in
[`interfaces.py`](../../ml/labelextract/interfaces.py), alongside
`ImagePreprocessor`, `OcrEngine` and `FieldExtractor`. `ExtractionPipeline`
takes an optional `classifier` and runs it last, over the same `OcrResult`
and `fields` the extractor produced. Its output rides in the result's
`metadata` next to `unread_declarations`, for the same reason that does: it
is an observation *about* the reading, not a declaration read off the
package, and a consumer iterating `fields` must never find one.

It is guarded the same way too. A classifier that raises — a bug, a missing
or malformed artifact, an `EngineNotAvailableError` — or that returns
something other than a `ProductClassification`, costs the classification and
never the reading: the run completes, `product_classification` is `null`, and
`classifier_name` in the metadata records that one was configured. A label
that was read perfectly well must not be reported as unreadable because an
optional second model failed. Each of those cases is a test in
`ml/tests/test_classification_pipeline.py`, with the shipped classifier class
and not only a stub, and `backend/apps/extraction/tests/test_product_classification_api.py`
drives the missing-artifact case through `run_extraction` to a stored,
`completed` run.

**One deliberate exception: the health check.** `GET /api/v1/health/` warms
every stage of the configured pipeline, so a `tesseract` 0.4.0 deployment
whose classifier artifact is absent or unreadable reports the pipeline
`available: false` (503, `detail: engine_not_available`) even though uploads
would still return a reading with a `null` classification. The artifact
ships inside the package and a test checks a non-editable install carries
it, so this can only happen with a broken build — and a broken build should
fail its health check rather than run quietly degraded. The behaviour is
pinned by a test so that changing it is a decision, not an accident.

The backend changed in one place. `ExtractionRunSerializer` gained a
`product_classification` method field that reads the stored metadata, exactly
as `get_unread_declarations` does. No model, no migration, no new endpoint,
no import of the ML runtime outside `extraction_service` — the boundary tests
in `test_extraction_integration.py` still pass unchanged.

### What `tesseract` 0.4.0 means, exactly

| | 0.3.0 (`EXTRACTION_ONLY_VERSION`) | 0.4.0 (`VERSION`) |
|---|---|---|
| Preprocessing | `PillowPreprocessor(min_dimension=UPSCALE_TO_DIMENSION)` | identical |
| Engine options | `eng`, psm 3 with fallback psm 11, OEM 3, 30 s timeout, min word confidence 0.0 — now written out explicitly so a later change to a default cannot move it | the same values, taken from `TesseractOptions()` defaults |
| Field extraction | `RuleBasedFieldExtractor()` | identical |
| Classifier | none | `tfidf-logreg` **0.1.0** |
| `ocr`, `fields`, `status`, `unread_declarations` | — | **identical** to 0.3.0 on the same image (asserted with a stub engine in `test_classification_pipeline.py`) |
| `metadata` | `product_classification: null`, `classifier_name: null`, `classifier_version: null` | the classification, `"tfidf-logreg"`, `"0.1.0"` |

So 0.4.0 is a new version for one reason only: it carries new weights, and
[`ml-integration.md`](../ml-integration.md) requires that a change which
would make two runs incomparable gets its own version and leaves the old one
registered. It is not a change to what is read. A run recorded under 0.3.0
before this branch reproduces exactly under 0.3.0 after it; a deployment that
stays on 0.3.0 sees no change at all; a deployment that moves to 0.4.0 gets
one additional, nullable field. Retraining the classifier (a 0.2.0 artifact)
would, by the same rule, be a 0.5.0 pipeline with 0.4.0 left registered.

Two pre-existing caveats carry over unchanged. No pipeline version pins
`fields/patterns.py`, which every version imports from one module — a pattern
fixed today changes what 0.1.0 reads too, and the module docstring in
`tesseract.py` says so. And the CLI picks "the newest registered version" by
sorting version strings, which is correct up to `0.9.0`.

## Input and output

**Input:** the recognised text of one photograph — `OcrResult.full_text`,
every line joined — plus the extracted fields and the image reference, which
the shipped implementation accepts and does not use. They are in the
signature so a later model can weigh which declarations were found, or look
at the pixels, without the interface changing.

**Output:** a `labelextract.contracts.ProductClassification`. This is the
shipped artifact's actual answer for the OCR reading of the Plix "Acne
Fighter" declaration face, verbatim:

```json
{
  "category": "packaged-food",
  "subcategory": "health-supplement",
  "confidence": 0.7232,
  "subcategory_confidence": 0.5517,
  "evidence": [
    "signal: ingredients (typical of packaged-food)",
    "signal: serving size (typical of packaged-food)",
    "signal: food additive code (typical of packaged-food)",
    "signal: consumption directions (typical of health-supplement)",
    "signal: effervescent / tablets / capsules (typical of health-supplement)",
    "signal: vitamin / mineral (typical of health-supplement)",
    "term: 'ins' weighed for health-supplement",
    "term: 'ins <num>' weighed for health-supplement",
    "term: '<num>' weighed for health-supplement",
    "term: 'tablet' weighed for health-supplement",
    "term: 'extract' weighed for health-supplement",
    "term: '<num> ii' weighed for health-supplement"
  ],
  "category_scores": {"packaged-food": 0.7232, "packaged-non-food": 0.2768},
  "subcategory_scores": {
    "cleaning-product": 0.1483, "cosmetics-and-toiletries": 0.1284,
    "general-food": 0.1715, "health-supplement": 0.5517
  },
  "classifier_name": "tfidf-logreg",
  "classifier_version": "0.1.0"
}
```

Four things the contract enforces structurally:

- `category` is a `ProductCategory` code or `"unknown"`. UNKNOWN is a valid,
  expected outcome; the dataclass refuses to attach a subcategory to it.
- `confidence` is the probability mass behind `category`, in `[0, 1]`, or
  `None` when no prediction was attempted. It is never a fabricated number
  and — per the `_check_unit_interval` guard shared with every other
  confidence in `contracts.py` — never out of range.
- `subcategory` may be `None` while `category` is not: "a food, but which kind
  is unclear" is a legitimate answer and a common one.
- `evidence` is never empty. An UNKNOWN says why it declined; a category says
  what in the text supported it.

**`confidence` is the classifier's confidence in its category and nothing
else.** `0.72` means "the text reads like a packaged food with 72% of the
model's probability mass behind that". It says nothing about whether the
package complies with anything, and no compliance figure may be derived from
it — [`api.md`](../api.md) states that no compliance score exists in this API
and none may be computed in a client, and this field does not change that.

## Taxonomy

Not invented for the model. Every code is tied to something the rest of the
system already recognises, so a classification can be consumed downstream
without a translation table that would drift.

**Categories are the `ProductCategory` codes** `seed_categories` creates
below `packaged-commodity`: `packaged-food` and `packaged-non-food`. They are
already a reviewed data contract — every shipped rule file targets one of
them, and the framework's one category-determined condition (`food-article`)
is answered from `packaged-food`. A backend test asserts the classifier's
categories are a subset of the seeded codes. `unknown` is the third value
and is not a category: it is the classifier declining.

**Subcategories reuse applicability-condition codes wherever one exists**, and
a backend test asserts each such code is defined in
`rules/framework/applicability_conditions.json`:

| Category | Subcategory | Applicability condition | Trained in 0.1.0 |
|---|---|---|---|
| `packaged-food` | `general-food` | — (internal) | **yes** — 7 products |
| `packaged-food` | `health-supplement` | — (internal) | **yes** — 1 product |
| `packaged-food` | `alcoholic-beverage` | `alcoholic-beverage` | no |
| `packaged-non-food` | `cosmetics-and-toiletries` | `cosmetics-and-toiletries` | **yes** — 1 product |
| `packaged-non-food` | `cleaning-product` | — (internal) | **yes** — 1 product |
| `packaged-non-food` | `medical-device` | `medical-device` | no |
| `packaged-non-food` | `tobacco-product` | `tobacco-product` | no |
| `packaged-non-food` | `electronic-product` | `electronic-product` | no |
| `packaged-non-food` | `other-non-food` | — (internal) | no |

The framework records `cosmetics-and-toiletries` as sitting "inside
`packaged-non-food` with no narrower category", and `tobacco-product`,
`medical-device`, `alcoholic-beverage` and `electronic-product` as having "no
commodity taxonomy entry". These subcategories are those entries. A
confident subcategory that shares a condition's code is, in a later step, a
*suggestion* a person can confirm as an answer to that condition — never an
answer recorded automatically.

**Defined is not trained.** The artifact records which classes it knows; the
loader refuses a class outside the taxonomy; the vocabulary being wider than
the model is stated rather than hidden. The `TAXONOMY_VERSION` is recorded in
every dataset and artifact, and a mismatch refuses to load.

**What the taxonomy is not.** It is not legal content. Nothing here asserts
that "health supplement" is a category under the Legal Metrology (Packaged
Commodities) Rules, 2011, that a `medical-device` classification makes rule
26(c) apply, or that any declaration is required for anything in it. The
`_DESCRIPTION` `seed_categories` writes onto every category row —
*"Internal grouping used to decide which compliance rules apply. Not a
category defined by the Rules"* — applies to every subcategory here in full.

## Preprocessing

[`preprocessing.py`](../../ml/labelextract/classification/preprocessing.py).
Two functions, deliberately separate:

**`preprocess_text`** changes encoding, case and layout, and nothing else:

1. NFKC normalisation — full-width digits, ligatures, presentation forms fold
   to their canonical characters. `ﬁne` → `fine`, `５００ g` → `500 g`.
2. A small table of typographic quotes, dashes and invisible characters
   (zero-width space, BOM) becomes plain ASCII or nothing.
3. Lowercase.
4. Every run of whitespace, line breaks included, becomes one space.

`FSSAI`, `MRP`, `15N TABLETS`, `120 g`, `200 ml`, `₹350.00`, `INS 330`,
`care@shinexpro.in` and `25°C` all survive it unchanged apart from case; a
test asserts each. It does **not** repair OCR errors — mapping `O` to `0`
would turn an unreliable reading into a confident wrong one, the same rule
`fields/normalisation.py` follows — and the cleaned text is what the evidence
signals are matched against and what a reviewer reads.

**`feature_tokens`** is the one abstraction step. Word tokens are runs of
letters or digits in any script (so Devanagari survives), split at
letter/digit boundaries (`500g` → `500`, `g`; `15n` → `15`, `n`), and every
all-digit token becomes the placeholder `<num>`. The exact digits of a price,
licence number, batch code or phone number say nothing about what kind of
product this is and would give the model one never-recurring feature per
product; the placeholder keeps *that a number was there and what it was next
to*, which is what carries information (`<num> g`, `<num> ml`,
`<num> tablets`, `<num> kcal`). `ngram_features` then forms unigrams and
bigrams from that stream.

Both are pure, deterministic and tested for it. The trainer and the
classifier call the same functions, and the artifact records
`TOKENISER_VERSION`; a mismatch refuses to load rather than scoring a model
against features it never saw.

## Model

**Algorithm:** TF-IDF over word unigrams and bigrams (`min_df=2`, L2 norm,
smoothed IDF, raw term frequency) followed by multinomial logistic regression
(scikit-learn `LogisticRegression`, `lbfgs`, `C=1.0`, `class_weight="balanced"`,
`random_state=0`). The class labels are **subcategories**; the category
probability is the sum of its subcategories' probabilities. One model, two
levels, and the category confidence is always at least the subcategory's.

Chosen because the brief asked for the simplest reproducible baseline and
because it fits this repository's constraints — see the next section. Not
chosen because it is expected to be good: a linear bag-of-n-grams model with
ten training products will lean on whatever separates those ten, and the
evidence lists show it doing exactly that (`'the'`, `'of'`, `'it'` weigh for
`cleaning-product` because the helmet cleaner is the one label in the set
written in prose).

**Hyperparameters were not tuned.** There is no data to tune them on: the
seed set is the only labelled data, and tuning against its cross-validation
would make the reported numbers optimistic. `C=1.0` is scikit-learn's
default; `min_df=2` is the floor at which a feature is more than one
document's noise; `balanced` weighting is what stops a 7-products-to-1
imbalance from becoming a prior for food.

**Why it can be replaced without touching the backend.** The backend sees a
`ProductClassifier` behind `ExtractionPipeline` and a JSON object in
`metadata`. A sentence-embedding model, a fine-tuned transformer, or a
multimodal model that looks at the image implements `classify(ocr, fields,
image)`, returns a `ProductClassification`, and is wired into a new
`tesseract` pipeline version. `train.py`, `model.py` and the artifact format
are specific to this baseline and would be replaced alongside it; the
taxonomy, the contract, the dataset format, the metrics and the tests of the
UNKNOWN path are not.

## Model artifact

**The problem the artifact strategy solves.** `labelextract` installs with no
dependencies and the production image is `python:3.11-slim` with a Tesseract
binary. `.gitignore` blocks `*.pkl`, `*.joblib`, `/ml/artifacts/` and
`/ml/models/`, and [`ml-integration.md`](../ml-integration.md) says never to
commit weights. Loading a pickled scikit-learn pipeline at request time
would mean shipping numpy, scipy and scikit-learn to evaluate a dot product,
tying the artifact to the scikit-learn version that pickled it, and running
whatever code a pickle contains.

**The strategy.** A TF-IDF vectoriser plus a logistic regression *is* a
vocabulary, an IDF vector, a coefficient matrix and an intercept vector. They
are exported to **JSON** —
[`product_classifier_v0.1.0.json`](../../ml/labelextract/classification/artifacts/product_classifier_v0.1.0.json),
119,535 bytes, 1,035 features × 4 classes — and evaluated by
[`model.py`](../../ml/labelextract/classification/model.py) in a hundred
lines of standard-library Python. A test asserts the plain-Python evaluation
reproduces scikit-learn's `predict_proba` to `1e-9` on freshly trained
models whenever scikit-learn is installed.

So the artifact is: trained offline (`python -m labelextract.classification.train`);
versioned by filename and by `model_version` inside it, which the loader
checks against the version the classifier was registered under; committed,
because it is small, human-readable, diffable and executes nothing; shipped
inside the package (`[tool.setuptools.package-data]`, verified against a
non-editable install); loaded once per process on `warmup()` or first use;
replaceable by retraining and bumping `VERSION`.

It carries its own provenance: `trained_on.dataset_version` and
`trained_on.dataset_sha256` name the exact dataset file, and a test asserts
they match the committed seed set — edit the dataset and the suite fails
until the model is retrained. The digest is the SHA-256 of the dataset
file **with CRLF normalised to LF** — the bytes as Git stores them — not of
the bytes on any one disk. That definition was forced by a real failure:
this repository is checked out with `core.autocrlf=true` on Windows, so the
identical committed file was CRLF in the working copy that trained the first
artifact and LF in CI, and a raw-byte digest disagreed between the two
(`4aa0343f…` recorded, `d40c7751…` in CI) while the content was the same.
`dataset.dataset_digest` and two tests in `test_classification_dataset.py`
pin the platform-independent definition, and `train.py` writes its outputs
with LF so the bytes on disk are the bytes Git will store. `training` records every hyperparameter and
the scikit-learn and Python versions. Retraining is deterministic: two runs
on the same data produce byte-identical coefficients.

Retraining needs the optional extra, which is never installed by the backend
or the container:

```bash
pip install -e "./ml[classify-train]"
python -m labelextract.classification.train            # writes the artifact and its .metrics.json
python -m labelextract.classification.train --help
```

**Limit of the strategy.** JSON is right for a linear model with a few
thousand parameters. A transformer's weights are hundreds of megabytes of
floats and do not belong in Git in any format; that model would use the
download-on-demand-with-checksum scheme `ml-integration.md` sketches, and
`model.py` would be replaced rather than extended.

## Dataset

**Format.** One JSON file, header plus `examples`, defined and validated by
[`dataset.py`](../../ml/labelextract/classification/dataset.py). Per example:

| Field | Meaning |
|---|---|
| `example_id` | Unique. `<sample>/ocr` or `<sample>/transcription`. |
| `product_id` | Groups every text from one physical package. **Evaluation splits on this.** |
| `category`, `subcategory` | Taxonomy codes; the loader checks the pair is consistent. |
| `text` | The text. May be empty — a front panel read as nothing is a real outcome. |
| `text_source` | `ocr` (verbatim engine output) or `manual_transcription` (typed from the photograph). |
| `labelled_by`, `label_verified_by` | Who assigned the category, and who checked it — or `null`. |
| `ocr_engine`, `ocr_engine_version` | Required for OCR text, so the sample can be regenerated. |
| `source_dataset`, `source_sample_id`, `image_sha256` | The frozen evaluation-set photograph the text came from. |
| `note` | What the panel is. |

Validation refuses rather than repairs: a dataset that loads with three
examples quietly dropped still reports a count, and that count ends up in a
table.

**The seed set:**
[`seed_v0.1.json`](../../ml/labelextract/classification/datasets/seed_v0.1.json),
`product-classification-seed-v0.1`, digest `d40c7751…` (SHA-256 of the file as Git stores it — see below).

| | |
|---|---|
| Source | The 28 photographs of 10 retail packages in `our-eval-v0.1-draft`, the project's own frozen extraction-evaluation set. Photographs are **not** in the repository; each example carries the manifest's SHA-256 for its image. |
| OCR text | 28 examples: verbatim output of `tesseract` **0.3.0**, regenerated 2026-09-16 with `python -m labelextract.cli <image> --pipeline tesseract --pipeline-version 0.3.0`. |
| Transcriptions | 5 examples: the most legible declaration panels (Plix, ShineXPro, Dove, the namkeen pouch, a DMart pouch) typed from the photograph **by a model** (`claude-opus-5`), not by a person, and flagged so in every note. |
| Labels | Assigned by a model from the photographs and the annotation notes. **`label_verified_by` is `null` on all 33.** |
| Contents | Public print on retail packaging: brand names, ingredient lists, manufacturer addresses, licence numbers, care-line numbers. No user upload, no image, no secret; a test asserts the last. |

| Subcategory | Examples | Products |
|---|---|---|
| `general-food` | 16 | 7 (masala sachet, milk, sugar, namkeen, chana, soya chunks, lapsi rawa) |
| `health-supplement` | 5 | **1** (Plix "Acne Fighter" effervescent tablets) |
| `cleaning-product` | 7 | **1** (ShineXPro helmet cleaner aerosol) |
| `cosmetics-and-toiletries` | 5 | **1** (Dove serum bathing bar) |

**Limitation, stated plainly.** Ten products, three of the four classes
represented by a single product each, and 20 of the 33 texts are front
panels or partial views carrying a handful of tokens. This is not a training
set; it is the format, the provenance discipline and the pipeline,
exercised on the only legitimate labelled text the project holds. No
example was fabricated and none was presented as more than it is. A
classifier worth relying on needs, at minimum, dozens of products per class
with human-verified labels, held out by product — and until it has them,
every number below should be read as a description of the seed set, not of
the classifier.

**Provenance rule for additions.** New examples must record their source the
same way. OCR text from the project's own photographs, with the engine
version. Transcriptions with who typed them. Labels with who assigned them
and — separately — who verified them. Nothing downloaded from a third party
without its licence being read first (`data-strategy.md` §3a).

## Training

`python -m labelextract.classification.train`, in [`train.py`](../../ml/labelextract/classification/train.py):

1. Load and validate the dataset.
2. **Leave-one-product-out cross-validation.** For each of the 10 products,
   fit on the other 9 products' texts (those with ≥ 3 word tokens) and
   classify the held-out product's texts — all of them, including the blank
   ones — through the *same* `TfidfProductClassifier` the pipeline runs,
   thresholds and UNKNOWN included. The number reported is the number the
   system would produce.
3. Fit the final model on every trainable example and export the artifact.
4. Score the final model on its own training data (resubstitution — labelled
   as such in the report and not a generalisation figure).
5. Measure inference latency on the dataset's texts.
6. Write everything to
   [`product_classifier_v0.1.0.metrics.json`](../../ml/labelextract/classification/artifacts/product_classifier_v0.1.0.metrics.json),
   including every individual prediction, so any figure below can be checked.

Splitting by product rather than by example is not optional. Two panels of
one pack share its brand, its address block and its licence numbers; a split
that puts them on opposite sides measures memorisation and reports a number
that predicts nothing.

Fitting the final model took 0.016 s; the ten-fold cross-validation 15.0 s (as recorded in the committed report; earlier runs on the same machine took between 1.8 s and 12.4 s - the figure is wall clock on a shared desktop and says nothing precise).

## Evaluation

Full tables, confusion matrices and per-example predictions are in
[`evaluation-results.md` §13](../evaluation-results.md#13-product-classification--tfidf-logreg-010-on-product-classification-seed-v01)
and in the committed metrics report; the headline figures are repeated here
so this document can be read alone. Metric definitions are in
[`metrics.py`](../../ml/labelextract/classification/metrics.py): an
abstention counts as wrong for *strict accuracy* and as a miss for *recall*,
and does not count as a prediction of any class for *precision*.

### The comparison that matters: a classifier with no features

Added in the evaluation review of 2026-09-22 and now regenerated into every
metrics report (`cross_validation.trivial_baselines`). A constant answer that
never reads the text scores the majority class's share:

| "Model" | Strict accuracy | Macro F1 |
|---|---|---|
| Always `packaged-food` | **0.636** | **0.389** |
| Always `packaged-non-food` | 0.364 | 0.267 |
| Always abstain | 0.000 | 0.000 |
| **The shipped artifact, leave-one-product-out** | **0.364** | **0.279** |

**The shipped classifier scores below a constant.** So does every
configuration tried in the sweep below. That is the single most important
number in this document: on unseen products this artifact has not learned to
read a label, it has learned that two-thirds of the seed set is food — and it
has learned that *worse* than simply saying "food" every time.

`train.py` prints this comparison at the end of every training run and says
so in those words, so the next person to tune a hyperparameter sees it at the
moment they are most likely to over-read an accuracy figure.

### Leave-one-product-out, category level (N = 33 texts, 10 folds)

| | |
|---|---|
| Unknown rate | **0.33** (11 of 33) |
| Strict accuracy | **0.36** (12 of 33) |
| Accuracy on predicted | 0.55 (12 of 22) |
| Macro precision / recall / F1 | 0.27 / 0.29 / 0.28 |
| `packaged-food` P / R / F1 | 0.55 / 0.57 / 0.56 (support 21) |
| `packaged-non-food` P / R / F1 | **0.00 / 0.00 / 0.00** (support 12; never predicted) |

| true \ predicted | food | non-food | unknown |
|---|---|---|---|
| `packaged-food` (21) | 12 | 0 | 9 |
| `packaged-non-food` (12) | **10** | 0 | 2 |

**Subcategory level: unknown rate 1.00.** No held-out text reached the 0.50
subcategory threshold in any fold.

**What this measures.** With one product per non-food class, holding that
product out leaves a training set in which the only non-food examples are a
different single product. The model has nothing to learn "non-food" from,
predicts `packaged-food` for every held-out non-food text, and does so at
0.65–0.79 — *above* the 0.60 threshold. The three folds where this happens
are named in the report under `held_out_classes_absent_from_training`. This
is the honest generalisation estimate for this artifact, and it is the
reason the status table above calls it a baseline and not a classifier.

**The confidences of wrong answers overlap the confidences of right ones
completely.** Correct held-out category predictions ranged 0.62–0.72; wrong
ones 0.65–0.79. No threshold on this model's probability separates them, so
raising `min_category_confidence` would not have made the cross-validated
result safer — it would have made it abstain on more of the right answers.
The probabilities are not calibrated and cannot be, from ten products.

**It is worse than "does not help": raising the bar makes it worse.** The
threshold sweep is now computed into every report
(`cross_validation.threshold_sweep`), and on the shipped artifact accuracy
among committed predictions *falls monotonically* as the confidence bar
rises:

| Minimum confidence | Committed | Correct | Accuracy on predicted | Coverage |
|---|---|---|---|---|
| 0.60 | 22 | 12 | 0.545 | 0.667 |
| 0.65 | 17 | 8 | 0.471 | 0.515 |
| 0.70 | 10 | 2 | **0.200** | 0.303 |
| 0.75 | 7 | 0 | **0.000** | 0.212 |
| ≥ 0.80 | 0 | — | — | 0.000 |

Every prediction this model makes above 0.75 confidence is wrong. A
confidence threshold is the mechanism an acceptance policy would be built
from, and on this artifact confidence is evidence *against* correctness. That
is why `AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS` is empty and why no
number could be put in it honestly — see
[automatic-applicability.md](../automatic-applicability.md).
`test_classification_evaluation.py` pins both readings.

### Resubstitution — the shipped artifact on its own training data

Not a generalisation figure. Reported because it is what the regression
tests pin, and because "can it even fit the seed set" is a question.

| | Category | Subcategory |
|---|---|---|
| Unknown rate | 0.06 (2 of 33) | 0.55 (18 of 33) |
| Strict accuracy | 0.94 | 0.45 |
| Accuracy on predicted | 1.00 | 1.00 |
| Macro F1 | 0.97 | 0.70 |

The two category abstentions are a Devanagari-only brand face and a
three-word side panel. The subcategory abstentions are mostly `general-food`
(14 of 16): with the balanced class weighting the food mass is split between
`general-food` and `health-supplement`, and general food rarely reaches 0.50
on its own. That is the thresholds working as intended — "a food, kind
unclear" — on the very texts the model was fitted to.

### Per-product results, and what they say the problem is

Also regenerated into every report (`cross_validation.per_product`). Held
out one product at a time:

| Product | Class | Correct | Unknown |
|---|---|---|---|
| product_001 | non-food / cleaning-product | 0 / 7 | 0 |
| product_002 | food / health-supplement | 0 / 5 | 5 |
| product_003 | non-food / cosmetics-and-toiletries | 0 / 5 | 2 |
| product_004–010 | food / general-food | 12 / 16 | 4 |

The model is right about `general-food` and about nothing else. Every product
whose **subcategory it has only one example of** — the cleaner, the
supplement, the toiletry — fails completely, and the report's own
`held_out_classes_absent_from_training` says why: holding that product out
leaves a training set with none of its class in it at all.

That is not a modelling failure. With one product per non-food subcategory
there is nothing for any model to generalise from, and no hyperparameter
recovers it.

### Model experiments (2026-09-22), and why none was shipped

Fourteen configurations, all scored leave-one-product-out on the same seed
set, none judged on resubstitution. Representative results:

| Configuration | Strict | Acc. on predicted | Unknown | Macro F1 | Non-food ever predicted |
|---|---|---|---|---|---|
| **Shipped 0.1.0** (word 1–2, min_df 2, C 1.0, balanced) | 0.364 | 0.545 | 0.333 | 0.279 | 0 |
| Unigrams only / word 1–3 / min_df 3 | 0.394 | 0.565 | 0.303 | 0.295 | 0 |
| C = 3.0 | 0.515 | 0.630 | 0.182 | 0.354 | 0 |
| C = 10.0 | **0.576** | 0.655 | 0.121 | **0.380** | 0 |
| `class_weight=None` | 0.576 | 0.655 | 0.121 | 0.380 | 0 |
| min_df = 1 | 0.333 | 0.458 | 0.273 | 0.250 | 1 |
| C = 0.1 / C = 0.3 | **0.000** | 0.000 | 0.55–0.64 | 0.000 | 2–5 |

**Nothing was shipped, and the apparent winner is the reason why.** C = 10.0
looks like a 58 % relative improvement in strict accuracy. It is the model
abstaining less and answering "food" more: it never predicts `packaged-non-food`
for an unseen product even once, so its macro F1 of 0.380 is still **below the
constant-"food" baseline's 0.389**. Shipping it would have been publishing a
worse-than-constant classifier as a large accuracy gain.

The configurations that *do* ever predict non-food (C ≤ 0.3, min_df = 1) score
0.000–0.333 strict accuracy — they are wrong nearly everywhere.

The artifact therefore remains **0.1.0, unchanged and bit-identical**. The
experiment script is not committed: it is a sweep over `TrainingConfig`
values that anyone can reproduce with `--C` and `--min-df`, and a committed
copy would imply the sweep is part of the shipped pipeline.

### Regression anchors

Pinned by `ml/tests/test_classification_regression.py` on the shipped
artifact, from seed-set text (so, resubstitution):

| Text | Category | Subcategory |
|---|---|---|
| Plix "Acne Fighter" declaration face, OCR | `packaged-food` | `health-supplement` (0.55) |
| Plix "Acne Fighter" declaration face, transcription | `packaged-food` | `health-supplement` (0.51) |
| Plix marketer face, OCR | `packaged-food` | — |
| ShineXPro declaration block, OCR | `packaged-non-food` (0.60) | — |
| ShineXPro declaration block, transcription | `packaged-non-food` | `cleaning-product` (0.67) |
| ShineXPro back panel, OCR | `packaged-non-food` | `cleaning-product` (0.57) |
| Dove declaration panel, OCR and transcription | `packaged-non-food` | `cosmetics-and-toiletries` (0.56, 0.58) |
| DMart soya back panel, OCR | `packaged-food` | `general-food` (0.52) |

Also pinned: casing changes leave every score identical; repeating the text
leaves the category unchanged (doubling every count leaves an L2-normalised
vector unchanged); deleting one letter in seven inside words leaves the
category unchanged on all four anchors; empty, one-word, wholly unknown,
punctuation-only and Devanagari-only inputs are UNKNOWN with `confidence`
`null`.

**And one expected failure, recorded rather than hidden:** with every `o`/`O`
read as `0` — a common Tesseract confusion — the model still commits to a
wrong category on two of the four anchors, at about 0.6. The test is marked
`xfail(strict=False)` and will report a pass, and a notice, when a model or
a calibration fixes it.

## Confidence and UNKNOWN

Three gates, in order, all in `ClassifierConfig`:

| Gate | Default | Outcome when tripped |
|---|---|---|
| Fewer than `min_tokens` word tokens | 3 | UNKNOWN — "insufficient text". Confidence `None`. |
| No n-gram of the text is in the vocabulary | — | UNKNOWN — "insufficient evidence". The model's output would be its intercept-only prior, which describes the training set and not this label. |
| Best category mass < `min_category_confidence` | 0.60 | UNKNOWN — "below confidence threshold", with the best candidate and every category score reported as evidence so a reviewer sees how close it was. |
| Best subcategory mass < `min_subcategory_confidence` | 0.50 | Category reported; `subcategory` `None`, with the best candidate in the evidence. |

**The thresholds are initial, configurable baselines and nothing more.**
0.60 is where a two-category answer stops being closer to a coin than to a
finding; 0.50 is where a four-way answer holds a majority of the mass. Neither
was derived from validation data, because there is none, and the evaluation
above shows that on this artifact no threshold separates right from wrong.
They exist so the abstaining path is real, exercised and visible in every
metrics report (as `unknown_rate`), and so a deployment can raise them
without a code change.

**How they should be set once there is data:** on a held-out set of
human-verified labels, split by product, plot accuracy-on-predicted against
unknown rate as the threshold sweeps; choose the operating point the
reviewing workflow can absorb; then check calibration (reliability diagram,
expected calibration error) and apply temperature scaling or isotonic
regression if the probabilities are systematically over- or under-confident.
None of that has been done. Nothing about 0.60 is scientifically or legally
authoritative.

Two properties are worth knowing about the current guards. A memorised brand
name alone can clear the token floor: `D Mart` is three tokens, all in the
vocabulary, and classifies as food at 0.64 because four DMart products are in
the seed set. And a short garbage string whose tokens happen to be in the
vocabulary (`a`, `ed`, `no`) can also clear it and reach the near-prior
0.62. Both are recorded in the test suite's docstrings and are a consequence
of ten products, not of the guard design.

## Evidence

Two kinds, both human-readable strings, both capped by configuration:

- **Signals** — [`signals.py`](../../ml/labelextract/classification/signals.py)
  holds ~35 label phrases (`nutritional information`, `ingredients`,
  `serving size`, `fssai`, `vegetarian mark`, `supplement`, `not for
  medicinal use`, `soap / bathing bar`, `for external use only`,
  `detergent / cleaner`, `spray / aerosol`, `flammable / chemical warning`,
  `medical device`, `sterile / single use`, `tobacco`, …), each with the
  grouping it is *typically* found with. Every one that occurs in the
  cleaned text is reported: `signal: fssai (typical of packaged-food)`.
  **The model never reads this table.** It exists so a classification can
  be checked against the photograph in seconds, and so tests can assert what
  a known label surfaces independently of what the model decides. The backend
  re-matches it against a run's stored reading to build
  `applicability_assessment.evidence`, which is how a person asked to confirm
  a product type sees the phrases *and the words around them* rather than a
  number — see [automatic-applicability.md](../automatic-applicability.md). An
  ingredient list appears on a soap as readily as on a biscuit; the signal
  says the phrase is there, the model weighs the whole text.
- **Terms** — model internals, and surfaced as such: the assessment parses
  them out of these strings into `evidence.model_terms` for a technical
  disclosure, never beside the suggestion. They are the n-grams present in the
  text whose coefficient contributed most to the chosen subcategory's score,
  largest first:
  `term: 'helmet' weighed for cleaning-product`. This is real: for a linear
  model the contribution of a term is exactly its weight times its
  coefficient. It is also revealing — on ten products the top terms include
  function words — and the evidence is deliberately not filtered to hide
  that.

## Performance

**What was measured.** `train.py::measure_inference`, whose figures are in
the committed metrics report under `inference_latency`. For each of the 33
seed texts, 50 times over (1,650 timings per row), `time.perf_counter()`
wall-clock around:

- *preprocessing + tokenising*: `preprocess_text(text)` followed by
  `word_tokens(cleaned)` — the deterministic clean-up and the token split;
- *classification*: one `TfidfProductClassifier.classify_text(text)` call
  end to end — which itself re-runs the preprocessing above, vectorises,
  evaluates the linear model, aggregates categories, matches the evidence
  signals and builds the `ProductClassification`.

The artifact was loaded (`warmup()`) before timing started, so artifact
parsing is not in these numbers; a single process, nothing concurrent; **no
OCR, no HTTP, no database** — this is the classifier stage alone. Machine:
Windows 11, Intel i5 (family 6 model 140), Python 3.11.1, CPU only, as
recorded in the report's `machine` block.

| | mean | median | p95 | max |
|---|---|---|---|---|
| Preprocessing + tokenising | 0.117 ms | 0.099 ms | 0.308 ms | 1.100 ms |
| `classify_text`, end to end | 0.748 ms | 0.624 ms | 2.025 ms | 4.406 ms |

The maxima are single outliers over 1,650 timings on a shared desktop, not
a tail worth engineering for. Against the 2,202 ms median OCR time in
`evaluation-results.md` §3 the classifier is well under a tenth of a percent
of a request. Artifact load is a 120 KB JSON parse once per process; memory
is the parsed artifact - 1,035 × 4 coefficients plus the vocabulary. No GPU
path exists and none is needed. This is comfortably inside the current
Railway deployment and adds no dependency to its image. Nothing has been
measured under concurrent load or inside the container.

## Integration with OCR

The classifier reads `OcrResult.full_text` — every recognised line, joined —
after the pipeline has mapped boxes back to source space and the field
extractor has run. It reads the *whole* text, not the extracted fields: a
label's kind is spread across its ingredient list, its warnings and its
marketing copy, most of which the field extractor deliberately ignores.

Consequences that follow from that:

- **OCR quality bounds classification quality.** A front panel the English
  OCR reads as `A ed no ¢` cannot be classified from that text, whatever the
  model; a Devanagari-only pack is UNKNOWN because Tesseract's `eng` model
  reads it as noise. `evaluation-results.md` §11 records that recognition,
  not interpretation, is the binding constraint on extraction; the same is
  true here.
- **OCR correctness and classification correctness are different problems.**
  The seed set carries both the OCR reading and a clean transcription of the
  same panel for five panels precisely so the two can be told apart. On the
  ShineXPro closeup the OCR reading reaches `packaged-non-food` at 0.60 with
  no subcategory; the transcription reaches `cleaning-product` at 0.67. The
  difference is recognition, not the model.
- **One photograph shows one panel.** A brand face classifies as UNKNOWN or
  on brand memory; the declaration panel carries the signal. Classifying a
  *product* from several photographs — combining panels — is not done and is
  the obvious next improvement to the input.

## Integration with applicability

**Not wired in this step, deliberately.** The applicability engine
([`applicability.py`](../../backend/apps/compliance/services/applicability.py))
answers each condition YES / NO / UNKNOWN from `ProductApplicabilityDeclaration`
rows and from `Product.category`, and its safety property is that *an
unestablished fact never produces a verdict*. A classifier output that
became a YES automatically would break that property in exactly the way the
framework's own comment warns against: "NOTHING HERE MAY BE INFERRED FROM
OCR. A package that omits an importer's name is not thereby domestic."

The path that is now prepared, and the rule for each step:

| Step | What | Status |
|---|---|---|
| Classifier produces a structured fact in the applicability layer's vocabulary | `category` ∈ `ProductCategory` codes; subcategories ∈ condition codes | **Done** |
| The fact reaches the client beside the reading | `extraction.product_classification` on every result | **Done** |
| A client shows it as a *suggestion* for `category_code` and for the matching declaration, for the person to confirm | Web: the assessment card under the verdict; mobile: "Re-check as X" | **Done** — see [automatic-applicability.md](../automatic-applicability.md) |
| A confirmed suggestion is distinguishable from an unprompted statement | Recorded as the person's declaration (`source = submitter`); the response's `applicability_assessment` reports `confirmed_by_submitter` vs `stated_by_submitter` vs `contradicted_by_submitter` by comparing the statement with the proposal | **Done** (as a derived disposition rather than a new `Source` value) |
| An unconfirmed suggestion is never recorded as an answer | `auto_applicability` writes no declaration row under any policy; a suggested condition stays UNKNOWN until a person answers | **Done, and tested** |
| Auto-accept above a calibrated threshold, with the classifier named as source | Only after calibration on verified data, and only for `Product.category`, never for a scope gate | **Mechanism done; no artifact licensed.** `AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS` names the artifact, its floor and the evaluation; it is empty, and stays empty for 0.1.0 |

The last row is the one to be most careful with. `Product.category` today is
a person's statement. Filling it from a model — even a confident one —
changes which rules run against a package, silently, which
[`evaluation-strategy.md`](../evaluation-strategy.md) §3 identifies as "a
failure mode that produces a confident, completely wrong result". The
cross-validation above shows this artifact producing confident wrong
categories on every non-food product it had not seen. It must not be
allowed to fill that field.

## Why the classifier does not determine compliance

Because it cannot, structurally, and because it must not, by design.

*Cannot:* the classifier's output lands in `ExtractionRun.raw_output`
metadata and the API. `apps.compliance.services.engine` reads
`ExtractedLabelField` rows, `Product.category` and declaration rows. There
is no code path from the classification to a finding, a violation or a
verdict. `backend/apps/compliance/tests/test_classification_isolation.py`
makes that checkable against the real shipped rules and framework: the same
reading is evaluated with a classification that contradicts the product's
actual category at 0.99 and again with none, and the verdict, the counts,
every finding's status and applicability note, every violation, and every
manual YES / NO / UNKNOWN declaration are asserted identical; a product with
no category stays "commodity not known"; and a source check asserts the
engine, the applicability resolver and every validator never read
`raw_output`. `test_product_classification_api.py` adds the HTTP view of the
same fact through `POST /api/v1/images/`.

*Must not:* a category is an internal grouping that selects which questions
to ask. Compliance is a claim about a package under the Rules, made from
verified rule text against a reading a person can check. A model's
probability that a label "looks like food" is evidence about the label; it
is not evidence that a declaration was required, present or correct. The
extraction confidence is documented as not being a compliance confidence;
the classification confidence is the same kind of number about a different
question, and the same rule applies.

If a later step lets a classification pre-fill `Product.category` after a
person confirms it, the *person's confirmation* is what makes the category a
fact the engine may use — the same way it is today.

## Limitations

- **Ten products.** Every other limitation is downstream of this one. The
  shipped artifact should be expected to call most unfamiliar labels
  `packaged-food` or `unknown`.
- **`packaged-non-food` has never been predicted for a product the model did
  not see.** Three non-food products, three classes, one each.
- **Probabilities are not calibrated** and wrong answers are as confident as
  right ones. The thresholds are baselines, not safeguards.
- **Labels are model-drafted and unverified**, as are the five transcriptions.
  The project's convention for annotations (`claude-opus-5-vision-draft`,
  pending human verification) applies unchanged.
- **English only.** Devanagari tokens survive preprocessing and would be
  learned if labelled examples existed; none do, and the OCR is `eng`-only.
- **Bag of n-grams.** No word order beyond bigrams, no semantics, no
  robustness to OCR corruption beyond what the training texts happened to
  contain. Heavy corruption produces confident wrong answers (the recorded
  expected failure).
- **Brand memorisation.** Four DMart packs teach the model that `d mart` is
  food. A DMart shampoo would be classified as food on its brand alone.
- **One panel at a time.** No combination across photographs of one product.
- **Five subcategories are defined and untrained**: `alcoholic-beverage`,
  `medical-device`, `tobacco-product`, `electronic-product`, `other-non-food`.
  The vocabulary can express them; the model cannot produce them.
- **Signals are English keyword patterns.** They are evidence, not features,
  and a phrase absent from the table is simply not reported.
- **Not measured:** anything on a held-out set with verified labels; anything
  multilingual; any calibration statistic; agreement with a human reviewer's
  category.
- **Below a constant.** On unseen products the artifact scores worse than a
  function that always answers `packaged-food`. Every metric in this document
  should be read against that floor.
- **Two non-food products, one per non-food subcategory.** This is the binding
  constraint, and it cannot be fixed by modelling. `ml/data/` contains 28
  photographs of 10 products and nothing else; the three evaluation sets
  (`our-`, `usp-`, `hv-`) are the *same* 28 images with successively corrected
  annotations, and all 28 are already in the classifier's seed set. There is no
  unused real product data in the repository.

### What would actually move this

In rough order of value, and none of it is a code change:

1. **More products per class, photographed the same way.** The immediate need
   is non-food: at minimum five to ten distinct products each for
   `cleaning-product`, `cosmetics-and-toiletries` and any other non-food
   subcategory that is to be predicted at all. Until a class has several
   products, leave-one-product-out cannot measure it and no model can learn it.
2. **Human-verified labels.** All 33 seed labels are `claude-opus-5-draft`
   with `label_verified_by: null`. A metric computed against unverified labels
   measures agreement with a drafting model.
3. **A held-out set of verified labels, split by product**, kept apart from
   whatever is used for tuning — the only basis on which a calibration and an
   operating point could be chosen.
4. Only then: calibration (reliability diagram, ECE, temperature scaling) and,
   if and only if accuracy rises with confidence at usable coverage, a proposed
   acceptance-policy entry.

## Files

| | |
|---|---|
| `ml/labelextract/classification/taxonomy.py` | Categories, subcategories, their condition codes, `TAXONOMY_VERSION` |
| `ml/labelextract/classification/preprocessing.py` | `preprocess_text`, `word_tokens`, `feature_tokens`, `ngram_features`, `TOKENISER_VERSION` |
| `ml/labelextract/classification/signals.py` | Evidence phrases |
| `ml/labelextract/classification/model.py` | Artifact format, validation, plain-Python TF-IDF + linear inference |
| `ml/labelextract/classification/classifier.py` | `TfidfProductClassifier`, `ClassifierConfig`, `build_classifier`, `VERSION` |
| `ml/labelextract/classification/dataset.py` | Dataset format, loader, validation |
| `ml/labelextract/classification/metrics.py` | Abstention-aware metrics |
| `ml/labelextract/classification/train.py` | Offline training, cross-validation, export, report |
| `ml/labelextract/classification/artifacts/` | The shipped artifact and its metrics report |
| `ml/labelextract/classification/datasets/` | The seed dataset |
| `ml/labelextract/contracts.py` | `ProductClassification`, `UNKNOWN_CATEGORY` |
| `ml/labelextract/interfaces.py` | `ProductClassifier` |
| `ml/labelextract/pipeline.py` | The optional `classifier` stage |
| `ml/labelextract/ocr/tesseract.py` | `tesseract` 0.4.0 with the classifier; 0.3.0 frozen without |
| `backend/apps/extraction/api/serializers.py` | `product_classification` on the wire |
| `ml/tests/test_classification_*.py` | 202 tests (4 of them the recorded expected failure, in four parametrisations): preprocessing, model, classifier, dataset, metrics, pipeline, regression, training |
| `backend/apps/extraction/tests/test_product_classification_api.py` | The field over HTTP; failure safety through the service and the health check; vocabulary cross-checks |
| `backend/apps/compliance/tests/test_classification_isolation.py` | Same reading with and without a contradicting classification: identical verdicts, findings and declarations against the shipped rules |
