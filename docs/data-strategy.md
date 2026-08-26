# Data strategy

What data this project needs, where each kind comes from, and what must never
enter the repository.

**Current state: no datasets exist in this repository.** No training data, no
evaluation set, no demo images are committed, and nothing is downloaded at
runtime. The OCR engine that ships (Tesseract) is **untrained by us** — it uses
language data installed by the operating system's package manager, so there is
no weight file for this project to host, version or checksum.

This document is the plan the data-owning work follows, not a description of
files you will find in a clone.

## Five kinds of data, kept separate

Mixing these is the mistake that makes evaluation meaningless — a model
evaluated on images it was tuned against reports a number that predicts nothing.

| Kind | Purpose | In Git? | Owner |
|---|---|---|---|
| Legal reference | The authoritative rule text | Citation only | `feature/legal-rules-dataset` |
| Training | Fitting or tuning a model | **Never** | `feature/ocr-processing` |
| Evaluation | Measuring performance honestly | **Never** (manifest only) | `feature/ocr-processing` |
| Demo | The SIH demonstration | Small set, with permission | `feature/frontend-dashboard` |
| Synthetic / fixtures | Deterministic tests | Yes, tiny | every branch |

## 1. Legal reference data

The compliance rules themselves.

**Source: the authoritative published text of the Legal Metrology (Packaged
Commodities) Rules, 2011, including amendments.** Not a summary, not a
consultancy blog post, not a language model's recollection.

What is committed is the *structured rule*, not a copy of the legislation: a
`legal_reference` string citing the provision, a plain-language `requirement`,
and a `source_note` recording who checked it, against what, and when. See
[`rules/SCHEMA.md`](../rules/SCHEMA.md).

Any rule whose text has not been checked stays `source_status: "unverified"`,
and the engine cannot use it to mark a product non-compliant — only to flag it
for review. That is what lets rule drafting proceed in parallel with legal
verification without risking a wrong legal claim.

**This repository currently ships zero rules.** That is deliberate and is
asserted by a test.

## 2. Training data

Photographs of packaged commodities used to fit or fine-tune a model.

- **Never committed.** `.gitignore` blocks `ml/data/` and `ml/artifacts/`. A
  dataset in Git history is in all six clones permanently.
- Stored outside the repository; a committed manifest records where it lives
  and its checksum.
- Provenance must be recorded per image: where it came from and on what basis
  it may be used. Photographs of retail packaging carry third-party trade dress
  and, occasionally, incidental personal data.
- The first OCR engine **is** off-the-shelf, so there is currently **no
  training data at all**. That is a legitimate outcome, not a gap to fill, and
  it should be stated plainly rather than papered over with a downloaded corpus
  nobody trained on.

## 3. Evaluation data

The held-out set that produces the numbers we report.

- **Never used for training or tuning.** If a threshold was adjusted by looking
  at these images, they are no longer evaluation data.
- Needs ground-truth annotation: for each image, the true text of each
  declaration and its location.
- Must include the hard cases deliberately, not only clean studio shots:
  reflective foil, curved surfaces, low light, partial glare, small print,
  multilingual panels, and damaged or worn labels.
- Size matters less than honesty about size. Fifty carefully annotated images
  with a stated confidence interval beat a thousand guessed labels.

## 3a. OCR datasets: four kinds that must not be conflated

The single most common way an OCR claim becomes dishonest is quoting a number
measured on one of these as if it described another. **A generic scene-text
dataset is not a Legal Metrology dataset.** Reading a shop sign in a
photograph and reading a 6-point net-quantity declaration off foil packaging
are different problems with different failure modes.

Every number we ever publish must name which kind it came from.

### A. General OCR / scene-text datasets

Photographs containing text of any sort — signage, posters, street scenes.

| Example | Where | Notes |
|---|---|---|
| ICDAR Robust Reading (2013 focused, 2015 incidental) | `rrc.cvc.uab.es` | Registration required |
| COCO-Text | `bgshih.github.io/cocotext` | Annotations over MS-COCO images |
| Total-Text, CTW1500 | authors' GitHub repositories | Curved and irregular text |
| SynthText | `robots.ox.ac.uk/~vgg/data/scenetext` | Synthetic |

**Used for:** sanity-checking that an engine works at all, and comparing
engines against each other on a neutral corpus.

**NOT used to claim:** anything about our system's performance on packaged
commodities. Not one of these contains a Legal Metrology declaration.

### B. Packaging / product-label datasets

Photographs of retail products, usually built for product *recognition* rather
than text reading.

| Example | Where | Notes |
|---|---|---|
| Grocery Store Dataset (Klasson et al.) | `github.com/marcusklasson/GroceryStoreDataset` | Product images plus some label crops |
| Freiburg Groceries | `github.com/PhilJd/freiburg_groceries_dataset` | Category classification |
| RPC (Retail Product Checkout) | `pinlab.org` / authors' release | Checkout-style imagery |
| SKU110K | `github.com/eg4000/SKU110K_CVPR19` | Shelf detection; **no text annotation** |

**Used for:** realistic packaging imagery — glare, curvature, foil, clutter —
to see where preprocessing and recognition break.

**NOT used to claim:** field-extraction accuracy. Almost none of these carry
ground-truth text for the declarations, and most are not Indian packaging.

### C. Indian / multilingual scene-text datasets

| Example | Where | Notes |
|---|---|---|
| ICDAR MLT 2017 / 2019 | `rrc.cvc.uab.es` | Multilingual, includes Devanagari and Bangla |
| IIIT-ILST (Indian Language Scene Text) | CVIT, IIIT Hyderabad | Hindi, Telugu, Malayalam |
| Bharat Scene Text Dataset | IIIT-H / public GitHub release | Multiple Indian scripts |

**Used for:** deciding whether the Devanagari language data is worth enabling,
and measuring how badly a bilingual panel degrades English recognition.

**NOT used to claim:** that our field extractor handles Hindi. It does not —
recognition and interpretation are separate layers, and **the extractor matches
English only** (see [`../ml/README.md`](../ml/README.md)).

### D. Our own annotated evaluation set — the only one that can support a claim

Photographs of Indian packaged commodities that **we** collect and annotate.

- **The only dataset whose numbers we may present as measuring this system.**
- Ground truth per image: the true text of each declaration, its
  `LabelFieldKey`, and its location.
- Deliberately includes the hard cases: reflective foil, curved surfaces, low
  light, glare, small print, bilingual panels, worn labels — and photographs
  that *should* be rejected, so the `EMPTY` path is measured too.
- Annotated **independently of the system's output**. Correcting the system's
  guesses biases the ground truth toward the system.
- Fifty carefully annotated images with a stated confidence interval beat a
  thousand guessed labels.

### Licensing — check, do not assume

Every dataset above has its own terms, several are research-use-only, and some
are annotations over images under separate third-party licences. **Read the
licence on the source page before downloading anything**, and record what it
permits in the manifest. Do not rely on the table above, this document, or a
model's recollection for a licensing decision.

Retail packaging additionally carries third-party trade dress, and photographs
taken in shops can capture incidental personal data. Both are reasons these
files stay out of Git regardless of licence.

### Where datasets live, and how to get them

Everything is **outside the repository**, in git-ignored directories:

```
ml/data/                      git-ignored — nothing here is ever committed
├── general-ocr/              kind A
├── product-labels/           kind B
├── indian-multilingual/      kind C
└── our-evaluation-set/       kind D — the only one that supports a claim
    ├── images/
    ├── annotations/          one JSON per image: declarations + boxes
    └── MANIFEST.json         committed? NO. See below.
```

A developer obtains a dataset by downloading it from its source page, accepting
that source's terms, and unpacking it into the matching directory. **There is
no download script in this repository, and nothing fetches a dataset
automatically** — an automatic download is how an unlicensed corpus ends up on
six machines without anybody reading the terms.

What *may* be committed is a small manifest describing a dataset we use: its
name, source URL, version, licence, SHA-256 of the archive, and the date and
name of whoever checked the licence. The data never is.

## 4. Demo data

Images used in the SIH demonstration.

- A small set, committed only with permission and only if genuinely needed.
- **Must include failure cases.** A demo that only shows successes invites the
  question "what happens when it fails?" with no answer prepared. Showing a
  blurred photo producing `REVIEW_REQUIRED` — rather than a wrong verdict — is
  the strongest thing this architecture can demonstrate.
- Never presented as evaluation results. A demo shows behaviour; it measures
  nothing.

## 5. Synthetic and fixture data

Deterministic inputs for tests.

Already in use: `backend/conftest.py` and `ml/tests/conftest.py` each build a
valid PNG byte-by-byte, with no image library involved. That is deliberate — a
test asserting "Pillow accepts this" must not construct its input with Pillow,
or it proves nothing.

Guidelines: keep fixtures tiny, generate them in code where possible, and never
download anything during a test run.

## What must never be committed

- Training or evaluation datasets of any size
- Model weights (`.pt`, `.onnx`, `.h5`, `.traineddata`, …), including Tesseract
  language data — install it with the OS package manager instead
- Uploaded user images — `backend/media/` is git-ignored
- Any image containing a real person's identifiable details
- Real `.env` files or database dumps

`.gitignore` covers these, but treat it as a safety net rather than a control.
Check `git status` before committing.

## Handling of uploaded images at runtime

- Stored under a generated filename; the client-supplied name never touches a
  filesystem path.
- SHA-256 recorded per image, so a compliance result is tied to the exact bytes
  analysed and later tampering is detectable.
- Served by Django only when `DEBUG=True`; a deployment serves them behind
  access control.
- **Retention is currently undefined** — uploads are kept indefinitely and
  nothing deletes them. A real deployment needs a retention policy and a
  deletion path. Owned by `feature/security-hardening`.

## Open questions for the team

Worth settling before the data-owning branches start, not after:

1. Where does evaluation data physically live, and who annotates it?
1a. Who has read and recorded the licence of each external dataset we use?
2. What is the minimum annotated set size we will accept before publishing any
   number?
3. Do we have permission for the packaging photographs we intend to demo?
4. What is the retention period for uploaded images?
5. Who is accountable for verifying each rule against the Gazette text?
