# `ml/data/` — local product-label images

Where a developer puts real photographs of packaged commodities so the OCR
pipeline can be run against them by hand.

**Nothing in this directory is committed.** `.gitignore` ignores every file
under `ml/data/` and re-includes exactly three things: this README, the
`.gitkeep` placeholders that keep the empty folders on disk, and the folders
themselves. Drop a JPEG anywhere below and Git will not see it. Check with:

```bash
git status --short          # your images must not appear
git check-ignore -v ml/data/raw/products/product_0001_front.jpg
```

The images are yours, they stay on your machine, and a teammate cloning this
repository gets the empty structure and this file.

---

## Layout

```
ml/data/
├── README.md                      committed
├── raw/
│   └── products/                  every photograph you take, unsorted
└── evaluation/
    ├── compliant/                 ground truth known: compliant
    ├── non_compliant/             ground truth known: non-compliant
    └── requires_review/           ground truth known: genuinely inconclusive
```

`raw/products/` is the inbox. Everything lands there first. An image moves into
`evaluation/` only once a human has established what the correct answer for it
actually is — see [Classifying an image](#classifying-an-image) below, which is
the part of this document most worth reading.

### How this relates to `docs/data-strategy.md`

[`docs/data-strategy.md`](../../docs/data-strategy.md) describes four kinds of
OCR dataset that must not be conflated, and names directories for external
corpora (`general-ocr/`, `product-labels/`, `indian-multilingual/`). Those are
for datasets downloaded from a third party under that third party's licence.

`raw/` and `evaluation/` here are **our own photographs** — kind D, "our own
annotated evaluation set", the only kind whose numbers may ever be presented as
measuring this system. Nothing in this repository downloads a dataset, and this
directory is not a place to unpack one without reading its licence first.

## Where to put images

| You have | Put it in |
|---|---|
| A photo you just took of a product | `raw/products/` |
| A photo whose true compliance status a person has established | the matching `evaluation/` folder |
| A photo you are unsure about | leave it in `raw/products/` |

Copy files in; do not move them out of `raw/products/` unless you are keeping a
record of which image is which. The pipeline never writes to these folders —
preprocessing intermediates go to a temporary directory the preprocessor owns
and deletes, and the original bytes are never modified. The original is the
evidence a disputed reading is checked against.

## Supported formats

**JPEG, PNG and WebP only.** This is the same allowlist the backend enforces at
upload (`backend/apps/images/constants.py`) and the same one
`labelextract.imageio` checks, and the format is decided from the file's
leading bytes — renaming `label.heic` to `label.jpg` gets it rejected, not
misread.

Practical limits, matching the backend's defaults: **10 MB** per file and
**50 megapixels**. A phone photo is comfortably inside both. HEIC (the iPhone
default) is not supported — set the camera to "Most Compatible", or convert
before copying in.

## Naming convention

Human convenience only. **Nothing in the code parses these filenames**, and
nothing should start to: see [below](#the-folder-is-not-a-source-of-truth-about-the-law).

Raw photographs — one number per physical product, one file per panel:

```
product_0001_front.jpg
product_0001_back.jpg
product_0001_side.jpg
product_0002_front.jpg
```

Evaluation images — a separate sequence, with the known status in the name so a
person can see at a glance what a folder contains:

```
eval_0001_compliant_front.jpg
eval_0002_non_compliant_back.jpg
eval_0003_requires_review.jpg
```

Rules of thumb: zero-padded numbers so they sort; lowercase; underscores, no
spaces; the panel name last when it applies. One product photographed from
three sides is three files sharing one number, because **one photograph shows
one panel** — a declaration missing from a front-panel shot may be printed on
the back, and that is a fact about the photograph, not about the product.

## Classifying an image

**Sort an image into `evaluation/` only when its ground-truth status is
actually known** — that is, a person has read the physical package against the
verified rule text and can say what the correct answer is.

If you have not done that, the image belongs in `raw/products/`. A guess placed
in `compliant/` is worse than no image at all: it becomes ground truth that
nobody remembers guessing, and every number later measured against it inherits
the guess.

`requires_review/` is not a bin for "don't know". It is for images where
**inconclusive is the correct answer** — a blurred or glare-blown panel, a
declaration cut off by the frame, a photograph where the right system behaviour
is to ask for a better picture rather than to reach a verdict. Measuring that
path matters as much as measuring the other two.

### The folder is not a source of truth about the law

The folder name and the filename are labels a human wrote. They are not
findings, and they must never become an input to the system:

- **Compliance conclusions come from verified `ComplianceRule` rows** in
  [`rules/`](../../rules/README.md), evaluated by the deterministic engine —
  never from a directory name, a filename, or the OCR layer's opinion.
- `labelextract` reports **what is printed on a package**. Locating a net
  quantity says nothing about whether one was required or whether the declared
  value is correct.
- Do not add code that reads `_compliant_` out of a filename and treats it as a
  result. If a comparison script is ever written, it must take ground truth
  from an explicit annotation file that records *who* decided and *against what
  provision*, and the folder stays a convenience for humans.

## Privacy and provenance

Photographs of retail packaging carry third-party trade dress, and photographs
taken in shops catch things nobody intended to photograph.

- **Crop or exclude unnecessary personal information** before copying an image
  in: faces and bystanders, your own name and address on a delivery label, a
  receipt or bill in frame, a phone screen, a handwritten note. A consumer care
  phone number *printed on the package* is a declaration and part of what is
  being read; anything identifying a private individual is not.
- Photograph packaging you own, or that you have permission to photograph. Some
  shops do not allow it.
- Keep a note of where an image came from if you intend anyone else to rely on
  it. Provenance that lives only in one person's memory is not provenance.

Never commit an image, even a "harmless" one — a file in Git history is in
every clone, permanently, and removing it means rewriting history for everyone.

## This is a development set, not a training set

These folders exist so that a person can run the pipeline over real labels and
see where it breaks. That is **evaluation and development**, and it is not the
same as either of the two things it is easy to mistake it for:

- **It is not a training set.** No model is trained in this repository, and
  there is no training pipeline. Tesseract is used as shipped, with language
  data installed by the operating system's package manager.
- **It is not yet a held-out evaluation set either.** An evaluation set is
  frozen and annotated *before* measuring, and is never used for tuning — if
  you adjusted a pattern after looking at an image, that image no longer
  measures anything. The method is in
  [`docs/evaluation-strategy.md`](../../docs/evaluation-strategy.md); these
  folders are the raw material for it, not a substitute for following it.

**No accuracy, CER, WER or F1 figure for this system has been measured, and
none may be quoted from a run against these images.** Running the CLI over a
folder tells you what the pipeline does. It measures nothing until ground truth
exists, the set is frozen, and the size and date are reported with the number.

## Running OCR against an image here

From the **repository root**, with the package installed (`pip install -e
"./ml[ocr]"`) and the Tesseract binary on `PATH`:

```bash
python -m labelextract.cli ml/data/raw/products/product_0001_front.jpg
```

The CLI takes a path and resolves it against your current directory, so the
same command works from inside `ml/` with the `ml/` prefix dropped:

```bash
cd ml
python -m labelextract.cli data/raw/products/product_0001_front.jpg
```

Other forms:

```bash
# Include every recognised word and the engine's raw diagnostics. Large.
python -m labelextract.cli ml/data/raw/products/product_0001_back.jpg --raw

# Bilingual panel; needs the Hindi language data installed.
python -m labelextract.cli ml/data/raw/products/product_0002_front.jpg --languages eng+hin

# Exercise the plumbing without Tesseract installed. Reads no pixels and
# always returns EMPTY - it proves the path works, nothing more.
python -m labelextract.cli ml/data/raw/products/product_0001_front.jpg --pipeline null-engine
```

Exit codes: `0` completed, `1` empty (nothing usable recognised), `2` failed
(the JSON carries `error_code`), `3` bad arguments. A whole folder, from the
repository root:

```bash
for f in ml/data/raw/products/*.jpg; do
  echo "== $f"
  python -m labelextract.cli "$f"
done
```

If every image comes back `failed` with `error_code: "engine_not_available"`,
Tesseract is not installed or not on `PATH` — see the install table in
[`ml/README.md`](../README.md). That is an environment problem, not a reading
of your labels.

`EMPTY` is not an error. It means the image was read and nothing usable was
recognised, which for a blurred or blank photograph is the correct answer.
