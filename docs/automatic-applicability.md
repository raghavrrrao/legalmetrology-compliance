# Automatic product applicability

How a label classification reaches the applicability engine, what it is
allowed to change, and what a person still decides.

```
IMAGE → OCR → FIELD EXTRACTION → PRODUCT CLASSIFICATION
                                        │
                                        ▼
                     apps.compliance.services.auto_applicability
                       read_classification()   shape-checked, never trusted further
                       accepted_policy()       settings: artifacts an evaluation licensed
                       establish_category()    at most ONE thing: Product.category
                                        │
                                        ▼
                     the EXISTING applicability engine (applicability.py)
                       DeclarationSet · decide_scope (rules 3, 26) · decide (per clause)
                                        │
                                        ▼
                     the EXISTING deterministic rule engine → findings → status
                                        │
                                        ▼
                     applicability_assessment on the result: what was proposed,
                     what is in effect and by whom, the evidence from the reading,
                     and what a person must still answer - with what answering does
```

The one-sentence version: **a classification can reach the rule engine only
as a `Product.category`, only under a policy entry that names the artifact and
the evaluation licensing it, only when no person stated a category — and never
as a declaration.** Everything else is description.

## Three things that are kept apart

| | What it is | Who decides | Values |
|---|---|---|---|
| **Classifier confidence** | The model's probability mass behind its category — a statement about the label *text* | `ml/labelextract/classification` | `[0, 1]` or `null`; not calibrated on the shipped artifact |
| **Legal applicability** | Whether a condition of the Rules holds for this package | `applicability.py`, from `Product.category` and declaration rows | `yes` / `no` / `unknown` per condition; `applies` / `does_not_apply` / `undetermined` per clause |
| **Compliance** | Whether an applicable requirement was met | the rule engine, from the reading | `passed` / `failed` / `inconclusive` / `not_applicable` per rule; `compliant` / `partially_compliant` / `non_compliant` / `review_required` overall |

No number flows between the rows. The classifier's confidence never becomes
an applicability answer's strength (answers have none), and never becomes a
compliance figure (there is none in this system).

## The states

`applicability_assessment.status` is the **policy's** verdict on the
classification, not the classifier's own vocabulary:

| Status | Meaning | What happens |
|---|---|---|
| `confident` | Committed to a category, **and** `AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS` accepts this artifact at this confidence | If no person stated a category: a `Product` row is created with that category, `category_source = classifier`, and the basis written on it. Evaluated exactly as a stated category would be. |
| `uncertain` | Committed to a category, but the policy does not accept it — the artifact is not listed, or the confidence is below the floor its evaluation established | Nothing is written. The category is a suggestion; one question is asked. The result is `review_required` ("the commodity category is not known") until a person answers. |
| `unknown` | The classifier ran and declined (too little text, no known n-gram, or below its own threshold) | Nothing proposed. The generic "what kind of product is this?" question is asked. |
| `failed` | No usable classification: none recorded, `null` (the classifier failed or none is configured), or a malformed shape | As `unknown`. Extraction and evaluation are unaffected — a classifier failure costs the classification and nothing else. |

Applicability keeps `yes` / `no` / `unknown`. Compliance keeps its four
statuses. No new verdict vocabulary was introduced.

## The policy, and why it is not a threshold

The obvious rule — "confidence ≥ 0.8 means trusted" — is exactly what the
repository's own evaluation of the shipped classifier forbids
([product-classification.md § Evaluation](ml/product-classification.md#evaluation)):

- leave-one-product-out strict accuracy **0.36**, unknown rate 0.33, macro F1 0.28;
- `packaged-non-food` **never predicted** for a product the model had not seen;
- **wrong answers are as confident as right ones** — correct held-out
  predictions ranged 0.62–0.72, wrong ones 0.65–0.79. No threshold on this
  model's probability separates them.

So acceptance is not a number in the code. It is a configuration entry per
artifact, and the entry must cite the evaluation that established it:

```bash
# root .env — empty is the correct value for the shipped artifact
AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS={}

# what an entry looks like, once an evaluation exists
AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS={"tfidf-logreg/0.2.0": {"min_confidence": 0.85, "evaluation": "docs/ml/evaluations/2026-10-tfidf-0.2.0.md"}}
```

Rules the code enforces (`auto_applicability.py`):

1. **Empty by default.** Today every committed classification is `uncertain`.
2. **Per artifact, by name and version.** An entry for `0.2.0` says nothing
   about `0.1.0`.
3. **A malformed entry fails closed** — logged, and treated as no entry.
4. **Only the category, never a subcategory.** The subcategories the taxonomy
   maps to conditions (`cosmetics-and-toiletries`, `alcoholic-beverage`,
   `medical-device`, `tobacco-product`, `electronic-product`) exempt clauses
   (6(1)(d), 6(1)(e), 7, 33), trigger one (6(8)), or withhold the rule 26
   exemption. A wrong YES excuses a package from a declaration it owes; a
   wrong NO asserts a fact nobody established. They are **proposed** for a
   person to confirm through `applicability_declarations`, under any policy.
5. **Never a scope gate.** No condition gating rule 3 or rule 26 is derivable
   from a classification; `decide_scope` sees only what a person declared.
6. **Never over a person.** A `category_code` in the request, an image already
   linked to a product, and every declaration row outrank the classifier. A
   proposal that disagrees is reported as `contradicted_by_submitter` and
   changes nothing.

What licensing an artifact requires — none of which has been done for
`tfidf-logreg 0.1.0`: a held-out set of human-verified labels split by
product; the accuracy-on-predicted / unknown-rate curve as the threshold
sweeps; a chosen operating point the reviewing workflow can absorb;
calibration checked and corrected. Then the entry names the floor and the
document, and `Product.category_basis` on every automatically categorised
submission cites both.

## The flows

**Routine case, today (policy empty):**

```
upload → reading (+ classification: packaged-non-food, 0.72)
       → POST /compliance/ {run}           status: uncertain
       → REVIEW_REQUIRED, category not known
       → assessment.questions: [ "The label reads like packaged non-food. Is that right?"
                                  choices: packaged-food | packaged-non-food ]
person taps "Yes, packaged non-food"
       → POST /compliance/ {run, category_code: packaged-non-food}   (same reading, no re-upload)
       → rules for packaged-non-food evaluated; category.disposition: confirmed_by_submitter
```

**Routine case, under an accepted policy:**

```
upload → reading (+ classification, above the artifact's floor)   status: confident
       → Product(category=…, category_source=classifier, category_basis="… evaluation: …")
       → rules evaluated; assessment.questions: []
       → result says: product_category_source = "classifier"; the UI says a model chose the rule set
person disagrees → POST /compliance/ {run, category_code: other}  → a new product, source submitter; the automatic one is not rewritten
```

**Exception handling, any policy:** `unknown` or `failed` → the generic
question; a subcategory suggestion → one condition question, answered
`yes` / `no` / `unknown` and recorded as the person's declaration.

**Precedence when both exist**, deterministic and in this order:
stated `category_code` → existing product's category → automatic (if
accepted) → none. For conditions: declaration row → nothing (a proposal is
never an answer).

## Traceability

For every automatically established category the system can say, from stored
rows and the response:

| Question | Where |
|---|---|
| Which classification produced it, at what confidence, with what evidence | `applicability_assessment.classifier`, and `extraction.product_classification` (unchanged) |
| Under which policy entry | `Product.category_basis`; `applicability_assessment.policy` |
| Whether it was automatic, confirmed, stated, contradicted, or still open | `product_category_source`; `applicability_assessment.category.disposition` |
| Which condition a suggestion bears on and which clauses that affects | `applicability_assessment.facts[].condition`, `.affects` (e.g. `6(1)(d): exempts`) |
| What each rule concluded and why it applied | the findings, unchanged: `applicability_note` on every one |

## The evidence behind a suggestion

A person asked to confirm a product type needs to see what the label says, not
a number. `applicability_assessment.evidence` carries three lists, kept apart
because they are three different kinds of thing:

| Key | What it is | Where it comes from |
|---|---|---|
| `label_signals[]` | Phrases **this reading contains** — `{phrase, indicative_of, snippet}` | `labelextract.classification.signals`, re-matched against the run's stored `recognised_text`. The snippet is the surrounding words, so the phrase can be found on the photograph. |
| `declared_fields[]` | Declarations the extractor read — `{field_key, value}` | The run's `ExtractedLabelField` rows, from the prefetch the result already loads. |
| `model_terms[]` | n-grams the model weighed | Parsed out of the classifier's own `evidence` strings (`term: 'x' weighed for y`). **Model internals**, reported for a developer in the technical disclosure — never as a statement about the product. |

Two properties, both load-bearing:

- **Nothing is generated.** Every string is a phrase found in the reading, a
  value the extractor read, or a term the classifier recorded. There is no
  narrated explanation of the model's reasoning, and nothing an LLM wrote.
- **"No evidence" is a state, stated.** `has_supporting_evidence` is false when
  the first two lists are empty, and `note` says which case it was — the label
  was read but contained no recognised phrase and no extractable declaration,
  or nothing was read at all. A client must show that sentence; an empty panel
  reads as reassurance.

`signals.py` is an explainability table of about thirty-five reviewed label
phrases which the model never reads, so matching it is not running the
classifier a second time. It is a regex pass over text already in memory: no
second OCR, no second model, no artifact load. A phrase is *typically* found
on a kind of product — an ingredients list appears on a soap as readily as on
a biscuit — and both clients say so next to the list.

Each open question also carries `outcome`: what answering does, in the terms
the system can promise — which requirements the answer selects (by clause, for
a condition), that the same stored reading is re-checked rather than the
photograph read again, that the answer is recorded as the person's, and that
leaving it unanswered is supported. It is written once in the backend so the
two clients cannot describe the same mechanism differently.

## API

Additive, on the compliance result body (`POST /compliance/`, `POST /images/`,
`GET /compliance/<uuid>/`); nothing existing moved. See
[api.md](api.md#the-compliance-result-body) for the field-by-field contract:

- `product_category_source`: `submitter` | `reviewer` | `classifier` | `null`.
- `applicability_assessment`: `status`, `reason`, `classifier`, `policy`,
  `category`, `facts[]`, `questions[]` (each with `outcome`), `evidence`.

One request-side relaxation: `applicability_declarations` without a
`category_code` is accepted when the policy will establish a category for the
run (they need a product to hang on). With the default policy the request is
refused exactly as before.

## Clients

- **Web**: a card under the verdict ("What kind of product this is") shows the
  status, the type in effect and who set it, the suggestion under a
  *"Suggested product type"* term with the classifier's confidence under a
  *"Classifier confidence"* term (labelled as not a compliance figure), a
  **"What the label says"** panel with the phrases and the declarations, what
  answering will do, and the open questions as buttons. Model terms and the
  policy detail sit in a "How this suggestion was produced" disclosure. Status
  is never carried by colour alone: every state has a word in the badge and a
  sentence in the body. Confirming re-checks the same reading through the
  existing manual path (`category_code` / `applicability_declarations`).
- **Mobile**: the classification card now also carries the backend's reason,
  up to three label phrases with their snippets (or the "no evidence" sentence),
  and what confirming would do. It renders `questions` as the existing
  "Re-check as X" button and does not present the condition questions.

## Testing strategy

`backend/apps/compliance/tests/test_auto_applicability.py` (55 tests) and
`test_auto_applicability_end_to_end.py` (4, over the real pipeline and the
shipped artifact) cover every scenario in the feature brief: confident /
uncertain / unknown / failed / malformed / absent classifications, human
declarations preserved, precedence, contradiction, the engine receiving the
same facts either way, rules 3 and 26 untouched, and backward compatibility.
The pre-existing `test_classification_isolation.py` still greps the engine,
the resolver, the composition service and every validator for
`raw_output|product_classification|classifier` — and still finds none: the
adapter is a separate module called from the API layer, and the only thing it
can hand the engine is a category row a person could have supplied. Two tests
make that explicit: with the default policy, five different classifications
of one reading leave the engine's trace identical; under an accepted policy
the automatic trace equals the trace of a person stating the same category.

Frontend: `ApplicabilityAssessment.test.jsx`, the mapping tests in
`complianceService.test.js`, and the confirmation loop in `ScanPage.test.jsx`
(confirming re-checks the same run, never re-uploads, sends only what the
person chose; the classifier's percentage is the only one on the page besides
OCR confidence and is labelled as not a compliance figure).

## Limitations

- The shipped artifact remains a baseline; **no entry should be added for it**.
  The automatic path is exercised by tests under a hypothetical entry and is
  otherwise dormant.
- `unknown` with a best candidate below the classifier's own threshold is not
  turned into a suggestion; the person gets the generic question.
- Subcategory suggestions come only from the five mapped codes; the shipped
  model can produce two of them (`cosmetics-and-toiletries`,
  `alcoholic-beverage` is defined but untrained).
- No reviewer path: `category_source = reviewer` exists as a value and is not
  yet written by any endpoint.
- The mobile client renders only the category question (as "Re-check as X");
  condition questions are web-only.
- Label signals are English keyword patterns. A phrase absent from the table is
  simply not reported, and their absence is not evidence about the product.
- `declared_fields` is context, not evidence of a product type: a net quantity
  says nothing about whether a package is food.
