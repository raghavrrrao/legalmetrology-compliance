# Data strategy

What data this project needs, where each kind comes from, and what must never
enter the repository.

**Current state: no datasets exist.** No training data, no evaluation set, no
demo images are committed. This document is the plan the data-owning branches
work to, not a description of files you will find.

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
- If the first OCR engine is used off-the-shelf, there may be **no training
  data at all**. That is a legitimate outcome, not a gap to fill.

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
- Model weights (`.pt`, `.onnx`, `.h5`, `.traineddata`, …)
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
2. What is the minimum annotated set size we will accept before publishing any
   number?
3. Do we have permission for the packaging photographs we intend to demo?
4. What is the retention period for uploaded images?
5. Who is accountable for verifying each rule against the Gazette text?
