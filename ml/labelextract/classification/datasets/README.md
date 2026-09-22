# Classifier datasets, and how a label becomes verified

Three files, and they answer three different questions.

| File | Question it answers |
|---|---|
| `seed_v0.1.json` | What text, with what labels, from what photographs |
| `label_verification_ledger.json` | Who checked a label, when, and against what |
| `REGISTRY.json` | Which dataset versions exist, and the digest of each |

No image bytes are here. Each example carries the SHA-256 of the photograph it
came from; the photographs themselves live under `ml/data/`, which is
gitignored in full. That split is deliberate — see `ml/data/README.md`.

## Current state

**33 examples, 10 products, 28 images, 0 verified.** Every label was drafted by
a model reading a photograph, and every row says so. The ledger is empty
because nothing has been verified — not because verification is untracked.

```bash
cd ml
python -m labelextract.classification.validation
```

prints the coverage table, every finding, and exits 0 (no errors; the thin
coverage and the unverified labels are warnings). `--require-verified` promotes
the unverified-label warning to an error; the seed set does not pass it and is
not meant to.

## Verifying a product — the procedure

Verification is **per product**, not per example, because the thing being
established is what a package is. All of its panels move together.

### 1. Get a worksheet

```python
from labelextract.classification import dataset, verification
import json

data = dataset.load_dataset()
print(json.dumps(verification.entry_template(data, "product_004", ref="s13"), indent=2))
```

It fills in only what the dataset already knows — which example rows and which
photographs belong to that product. `verifier`, `verified_on`,
`product_identity`, `category`, `subcategory` and `outcome` come back **blank
on purpose**. Pre-filling them from the drafted label is exactly how a draft
becomes a verification without anybody deciding anything.

### 2. Open the photographs and decide

Every digest in `image_sha256` resolves to a file under
`ml/data/our-evaluation-set/images/`. Look at the package, not at the drafted
label in `note`.

Establish four things, all of them:

1. **Product identity** — what it actually is, in words.
2. **Category** — `packaged-food` or `packaged-non-food`.
3. **Subcategory** — the taxonomy code.
4. **Source** — the photographs and example rows you read.

Then one outcome:

| `outcome` | Meaning | Effect |
|---|---|---|
| `confirmed` | The drafted label is right | Rows become verified |
| `changed` | The drafted label is wrong; the entry carries the correct one | Rows become verified **and** relabelled, together |
| `unresolved` | You looked and deliberately did not decide | Recorded; **never** applied; rows stay unverified |

`unresolved` is a real answer. A package whose category is genuinely arguable
should be recorded as arguable, not forced into whichever class reads as
closest.

### 3. Append the entry, and apply it

Add the completed object to `entries` in `label_verification_ledger.json`.
Then:

```python
from pathlib import Path
from labelextract.classification import verification

document = json.loads(Path("labelextract/classification/datasets/seed_v0.1.json").read_text("utf-8"))
ledger = verification.load_ledger()
updated = verification.apply(document, ledger, dataset_version="product-classification-v0.2")
```

`apply` is pure — it writes nothing. It **requires** a new `dataset_version`,
because applying a verification changes the digest, and `seed_v0.1` is the set
`tfidf-logreg 0.1.0` was trained against. Editing it in place would silently
change what every published figure refers to. Write the result to a new file,
add a row to `REGISTRY.json`, and re-run validation.

Applying a verification is **not** a reason to retrain. That is a separate,
separately justified experiment — see `docs/ml/product-classification.md`.

## What may never verify a label

A machine. `verifier` and `label_verified_by` are both checked against
`dataset.MACHINE_LABELLER_MARKERS`, and there is no flag to override it.

The case that matters most is the classifier itself. A model that confirms its
own training labels produces agreement with itself, and a metric computed
against those labels measures nothing. The drafting model is refused for the
same reason: it is the thing being checked.

## What is missing, and it is not code

Eight of the taxonomy's nine subcategories cannot be measured from this
dataset — five have no example at all, and three have exactly one product.
That is a data-collection gap. No amount of validation, verification or
modelling closes it; photographing more packages does.
