# Extraction and normalisation hardening

**Branch:** `feature/extraction-normalization-hardening`
**Field extractor:** `rule-based-fields` 0.1.0 → **0.2.0**
**Pipeline:** `tesseract` 0.4.0, **unchanged**
**Measured on:** `our-eval-v0.3-usp-partial`, 28 photographs of 10 retail packages
**Date:** 2026-09-23

This branch changes what the extractor *reads off a label*. It changes nothing
about what the system *requires* of a label. No rule definition, no check
validator, no applicability code and no classifier code is touched; the whole
diff is inside `ml/labelextract/fields/` and its tests.

---

## 1. What this is, and the three layers it keeps apart

The point of the exercise is a distinction that is easy to state and easy to
lose:

```
OCR recognition   what characters came back off the pixels
field extraction  which of those characters are a declaration, and which one
normalisation     what structured value that declaration has, if any
compliance        whether the package complied
```

They fail separately and they have to be measured separately. Two examples from
this project's own evaluation photographs:

| Reading | What failed |
|---|---|
| OCR returned `MRP €349.00 (INCL. OF ALL TAXES)` and no retail sale price was extracted | **extraction** — the amount is right there |
| OCR returned nothing where the pack prints `₹350` | **OCR** — no extractor can recover it |

A figure that merges them is unactionable. The audit below separates them for
every miss on the frozen set, and the answer turned out to be lopsided.

**Nothing in this document is a compliance claim.** Extraction confidence is
confidence in *characters*; `normalized_value["uncertain"]` is the normaliser's
opinion of the *interpretation*; neither is a legal conclusion, and the
deterministic engine over verified `ComplianceRule` rows remains the only thing
that reaches one.

---

## 2. The audit: where a declaration comes from, and where it goes

Every field the extractor attempts, from recognised text to the checks that
read it. The last column is what makes a change here consequential: a check
listed there changes its outcome when the reading changes.

| Field | Located by | Normalised to | Confidence | Downstream checks |
|---|---|---|---|---|
| `manufacturer_name` | `NAME_DECLARATIONS`, keyword + rest of line, one-line lookahead | `{name}`, always uncertain (the name runs on; the address is not read) | OCR line mean | `LM-PC-0001` `field_presence_any_of` |
| `packer_name` | same | same | same | `LM-PC-0001` |
| `importer_name` | same | same | same | `LM-PC-0001` |
| `common_or_generic_name` | **not attempted** | — | — | `LM-PC-0002`, deactivated for exactly this reason |
| `net_quantity` | `NET_QUANTITY_KEYWORD` + `QUANTITY` on the same line | `{quantity, unit, measure, base_quantity, base_unit, pack_count}` | OCR line mean | `LM-PC-0003` `field_presence`, `LM-PC-0008` `si_unit`, `LM-PC-0009` `prohibited_counting_unit` |
| `retail_sale_price` | `MRP_KEYWORD` then `PRICE`/`BARE_AMOUNT` **after** the keyword | `{amount (string), currency, inclusive_of_all_taxes?}` | OCR line mean | `LM-PC-0005` `field_presence`, `LM-PC-0012` `retail_price_tax_declaration` |
| `unit_sale_price` | `UNIT_SALE_PRICE_KEYWORD` + `PER_UNIT_PRICE` | `{amount, currency, per_unit, per_measure}` | OCR line mean | none active |
| `date_of_manufacture` | `DATE_KEYWORDS` + a date on the line or the one below | `{date}` or `{year_month}` | OCR line mean | `LM-PC-0004` `field_presence`, `LM-PC-0011` `month_year_declaration` |
| `date_of_packing` | same | same | same | none active |
| `date_of_import` | same | same | same | none active |
| `best_before` | same, plus `DURATION` | `{date}`/`{year_month}`/`{duration_value, duration_unit}` | same | none active |
| `consumer_care_contact` | `CONTACT_KEYWORD`, `EMAIL`, `TOLL_FREE_PHONE`, `MOBILE_PHONE`, unioned across every contributing line | `{emails[], phones[]}` | first line carrying a value | `LM-PC-0006` `field_presence`, `LM-PC-0010` `consumer_care_elements` |
| `country_of_origin` | `COUNTRY_OF_ORIGIN_DECLARED` (committed) / `_IMPLIED` (uncertain) | `{country_text}` | OCR line mean | `LM-PC-0007` `field_presence` |
| `batch_number` | `BATCH_NUMBER` | `{batch_number}` | OCR line mean | none active |
| `manufacturer_address` | **not attempted** | — | — | none |

**Executable compliance inputs** — the fields whose reading can move a verdict
today — are therefore: `manufacturer_name` / `packer_name` / `importer_name`
(as a disjunction), `net_quantity`, `retail_sale_price`,
`date_of_manufacture`, `consumer_care_contact`, `country_of_origin`. The other
five are read and stored and nothing acts on them yet.

Raw OCR is produced in `ml/labelextract/ocr/tesseract.py`, one `TextBlock` per
recognised line with a box and a mean word confidence, and the word-level
detail is kept verbatim in `OcrResult.raw["words"]` so field extraction can be
re-run over a stored reading without paying for OCR again. That is exactly what
the measurements in §5 do.

### Multiple candidates, and where evidence lives

`rule_based._resolve` reduces many candidates to at most one field per
declaration: best-ranked wins (keyword beats pattern, committed beats
uncertain, then OCR confidence, then position), and when a genuinely different
reading was also found the field is flagged uncertain and every competing
reading is listed under `normalized_value["candidates"]`. Evidence is
`ExtractedField.raw_value` — the recognised line, untouched — plus
`ExtractedField.box`. A declaration whose keyword was recognised but whose
value was not becomes an `UnreadDeclaration` in
`metadata["unread_declarations"]`, which is deliberately **not** a field: a
value-less field would pass `field_presence` and turn a possible violation into
a pass.

---

## 3. What the audit found

Replaying the current extractor over the 28 stored readings gave precision
1.000 and recall 0.222 — 20 detections, 70 misses, no false positives.

**Of 94 misses, the annotator's transcription appears verbatim in the
recognised text in 6.** The other 88 were either never recognised at all —
rotated panels (`p004`), a blank recognition (`p002_01_back`), stamped ink lost
to a curved surface, the rupee glyph (`U+20B9` is not in the `eng` LSTM
alphabet) — or came back corrupted past the point where the printed value can
be recovered without inventing characters (`BRDOIFS0033` for `RD02F50033`,
`ie By:` for `Use By:`). The two are not separated further here, because the
extractor's options are the same either way. *Recall on this corpus is bounded
by recognition, not by interpretation*, and no pattern work can move most of
it.

So the useful work was not recall. It was the five **confident wrong
readings** — committed, unflagged values that a reviewer would be shown as
measured, and that `field_presence` passes on:

| Sample | Field | Reported | Actually on the pack |
|---|---|---|---|
| `p006_01_back` | `batch_number` | `Ni` | `BL28I50075` |
| `p003_03_right` | `net_quantity` | `4 units` | `4 UNITS X 125 g + 125 g FREE` |
| `p001_05_declaration_closeup` | `date_of_manufacture` | `2 years` (a duration) | `11/2025` |
| `p001_05_declaration_closeup` | `consumer_care_contact` | `8867162397` | `8867162337` — an OCR digit error, not an extraction defect |
| `p008_01_back` | `consumer_care_contact` | `Uggestion@dmartindia.com` | `suggestion@…` — OCR dropped the `S` |

The first three are extraction defects. Their root causes:

1. **`Batch Ni`.** `p006` and `p010` both print a *legend* line — `MRP Rs.
   (incl. of all taxes), Batch No. & Use By Date` — naming where the
   declarations are rather than declaring anything. The pattern's guard refused
   the qualifier spelt correctly (`No`, `Nos`, `Number`, `Code`) but could not
   refuse it spelt the way OCR read it. Enumerating misreadings of `No.` is a
   losing game.
2. **`4 units`.** `QUANTITY.search()` returns the *leftmost* match. A line
   carrying several quantities silently became one, and the choice was
   presented as a measurement.
3. **`2 years` as a manufacture date.** The next-line lookahead, written for a
   keyword printed above its value, walked into a line that was itself a whole
   best-before declaration. A package is manufactured on a day, never "two
   years from" anything.

A fourth gap had no metric consequence on this set but is the brief's own
example: a date OCR mangled to `1142025` produced **nothing at all** — no
field, and no unread observation either, because the manufacture and packing
keywords were excluded from the unread-anchor list (their stems `manufactured`
and `packed` also open the *name* declarations). The declaration simply
vanished, indistinguishable from a package that never dated itself.

---

## 4. What changed

All of it in `ml/labelextract/fields/`.

### Extraction

- **Every quantity on a line is now a candidate**, not the leftmost. Competing
  readings surface through the existing `_resolve` machinery: the best-ranked
  one is still emitted, the field is flagged uncertain, and both readings are
  listed under `candidates`. A line whose matches all normalise to the same
  value produces one signature and stays committed.
- **A batch code must contain a digit.** One test in place of an unwinnable
  enumeration. It costs a batch code made of letters alone; every code in the
  frozen set carries digits.
- **A shelf life is a value only for `best_before`.** `_DURATION_IS_A_VALUE_FOR`.
- **The next-line date lookahead stops at a line naming a different date
  declaration.** Compared by pattern identity, so a *wrapped* line — the same
  keyword continuing — still reads, which is what the lookahead is for.
- **`date_of_manufacture` and `date_of_packing` gained unread anchors**
  (`patterns.DATE_ANCHORS`), the strict half of their keywords: only phrasings
  that name a *date* (`Date of Manufacture`, `MFG. DT.`, `Packing Date`, `Pkd.
  On`). `MFG. BY LAKME LEVER PVT. LTD.` and `Packed by BAZINGA MEDIA` do not
  match, which is the whole point — an unread observation is a positive claim
  about what the label says. Same split, same reasoning, as the existing
  `NET_QUANTITY_ANCHOR` and `BATCH_NUMBER_ANCHOR`.
- **`Packed & Marketed by` / `Manufactured & Marketed by` are name
  declarations.** `p005_01_back` prints the first and it was being recorded as
  a marketing declaration while the packer the label names went unread.

### Patterns and normalisation

- **`per` no longer needs a trailing word boundary**, so `perg` reads as `per
  g`. Every character of the declaration was recognised and only the space
  between two of them was lost; the unit's own `\b` still closes the token, so
  `per 100 g` stays unreachable.
- **`EMAIL` tolerates one space at the `@`**, and `normalise_email` closes the
  gap in the structured value. The recognised line survives untouched in
  `raw_value`, so the repair stays visible.

### What was deliberately **not** changed

These are the decisions worth arguing with, so they are written down rather
than left implicit.

- **`g` misread as `9` is not repaired.** `p010_01_back` prints `500 g` and OCR
  returned `Net Quantity: 5009`; `p009_01_back` returned `200 9`. A
  net-quantity keyword on the line says a quantity is declared. It does not say
  the trailing `9` was a `g`, and `5009` reads as five thousand and nine just
  as well. Committing would put a measurement the label never printed in front
  of a reviewer, indistinguishable afterwards from one that was read. Both are
  reported **unread** instead — "this panel declares a net quantity and we
  could not read its value", which is a retake, not a violation. Cost: 2
  detections not gained.
- **A missing dot in an e-mail is not put back.** `p009_01_back` returned
  `suggestion @dmartindia com` and `p006_01_back` returned `On@dmartnda, com`.
  A space is a separator OCR added; a dot is a character nobody read.
- **No next-line lookahead for the MRP.** Tried against the corpus and
  rejected: on `p003_03_right` the line below the MRP legend is `OH 8465
  /-%0.93/9`, where the pack prints `₹465/-`. A one-line lookahead there would
  have committed to **8465** — a fabricated price, confidently, on a pack whose
  real MRP is 465.
- **No tax indication from an adjacent line.** `p007_01_back` prints `M.R.P
  %:120f` above `(Incl. of all taxes) %`. A person reads them as one
  declaration; this extractor reads lines, and adjacency is a layout guess it
  cannot check. `inclusive_of_all_taxes` stays **absent** (meaning "not
  observed") rather than inferred, because `LM-PC-0012` tests that key against
  rule 6(1)(e) and manufacturing its evidence is the one thing that check must
  never be fed.
- **No length units (`cm`, `m`) for net quantity.** They would be correct, but
  no package in the frozen set declares one, so the change would be unmeasured
  — and `_SI_UNITS` in `apps/rules/checks/quantity_units.py` mirrors the
  extractor's vocabulary under a drift test, so it would pull a rules-layer
  edit into an extraction branch for no measured gain.
- **No Indian landline pattern.** The three landlines in this corpus are all
  corrupted (`022- "71230555`, `2-712305 955`, a 9-digit `907963574`), and the
  same panels are crowded with 14-digit FSSAI licence numbers that a loose
  STD-code pattern matches. Precision loss for zero measured recall.
- **No model-based extractor.** Deterministic extraction is not yet the binding
  constraint: recall on this corpus is bounded by *recognition*, and the
  measured extraction defects were three specific rule bugs, all fixed with
  rules. A learned tagger would also need annotated Indian label data this
  project does not have, and its mistakes would be unexplainable in a tool
  whose output is meant to be evidence.

---

## 5. Measured results

Both runs are the real end-to-end pipeline — `python -m
labelextract.evaluation.cli run ml/data/hv-evaluation-set --pipeline
tesseract` — on the same machine, same Tesseract, same 28 photographs,
differing only in the field-extractor commit.

**The dataset is 364 annotated cells of which 34 are human-reviewed and 330 are
model-drafted.** These figures measure the pipeline against a *partially
verified* artefact and must not be quoted as performance against human ground
truth.

| | fields 0.1.0 | **fields 0.2.0** |
|---|---:|---:|
| Precision | 1.000 (20/20) | **1.000** (19/19) |
| Recall | 0.222 (20/90) | **0.211** (19/90) |
| F1 | 0.364 | **0.349** |
| Value accuracy | 0.650 (13/20) | **0.684** (13/19) |
| **Silent error rate** | 0.385 (5/13) | **0.273** (3/11) |
| Uncertainty precision | 0.286 (2/7) | **0.375** (3/8) |
| Uncertain rate | 0.409 (9/22) | 0.476 (10/21) |
| Fabricated values | 0 | 0 |
| Correct unread | 1 of 25 | 1 of 25 |
| `EMPTY` photographs | 0 of 28 | 0 of 28 |
| Median latency | 1,129 ms | 1,056 / 1,071 ms |
| CER / WER | unavailable | unavailable |

The two latency figures are two runs of the identical build. They are quoted as
a pair because the spread between them is larger than the gap to the "before"
number, so **no latency change should be read from this table** — see §7, where
the layer that actually changed is timed on its own.

**Read the shape, not the headline.** Recall went *down* by one cell and that
is the intended result: both detections removed were wrong values (`Ni` for a
batch code, a duration for a manufacture date), and a detection with the wrong
value was never worth having. What improved is the failure behaviour — **two
fewer confident wrong readings in five**, value accuracy up 3.4 points, and the
hedging the extractor does now correlates better with being wrong.

Per-field, the four cells that moved:

| Field | Change | Why |
|---|---|---|
| `batch_number` | TP 1→0, value_incorrect 1→0 | the only detection was `Ni` |
| `date_of_manufacture` | TP 1→0, value_incorrect 1→0 | the only detection was a duration; now reported unread |
| `packer_name` | TP 0→1, recall 0.000→0.500 | `Packed & Marketed by` |
| `net_quantity` | unchanged counts | `4 units` stays the best-ranked reading but is now flagged with both candidates |

Unread observations across the corpus: 11 → 12, the new one being
`date_of_manufacture` on `p001_05_declaration_closeup`, replacing the
fabricated duration.

### OCR quality, extraction quality and normalisation quality, separated

- **OCR recognition:** unchanged, byte for byte. No engine setting, preprocessing
  step or segmentation mode was touched. 674 recognised lines across 28
  photographs, median line 18 characters, longest 103. CER/WER remain
  **unavailable** — no sample carries a hand-transcribed reference text — and
  are reported as unavailable, not as zero.
- **Field extraction:** 20 → 19 detections, 0 false positives throughout. Of 94
  misses, 6 have the annotator's transcription verbatim in the recognised text
  — those 6 are the whole of what better patterns could reach on this corpus.
- **Normalisation:** value accuracy 0.650 → 0.684 over detections; the
  ambiguity mechanisms (`candidates`, `uncertainty_reasons`) carry two more
  readings than before.
- **Compliance verdicts:** not measured here and not claimed. The runner loads
  no rule and imports no `ComplianceRule`; measuring findings against a human
  reviewer's determination is a separate exercise needing verified rules.

---

## 6. Regression cases

`ml/tests/test_extraction_hardening.py`, 92 cases. **Every input string is
recognised text this project actually produced**, copied from the stored
readings under `ml/data/evaluation/ocr_runs/after/` and named with the sample
it came off. No label was drafted and no OCR output was invented.

The thirteen properties it pins:

1. an MRP OCR read is extracted whatever became of the rupee glyph (`€`, `%`, `=`)
2. `inclusive_of_all_taxes` is written only where the line carries the words
3. a net quantity OCR read is normalised, across spacing and casing variants
4. every contact element on a panel reaches the reading; a space at the `@` does not cost the address
5. an address missing a character, and a phone missing a digit, are not completed
6. a valid month/year normalises to `year_month`, never padded to a day
7. `1142025` produces no date and **is reported unread with its evidence line**
8. a shelf life below a manufacture keyword is not the manufacture date
9. several prices on one label land on the right declarations
10. several quantities on one line are all reported, and one quantity printed twice is not a disagreement
11. OCR corruption behaves safely — `Batch Ni`, `5009`, `200 9`, `349O`, a bare `MRP`
12. an absent declaration stays absent; an empty reading produces nothing
13. the raw line, the box, the reasons and the engine's confidence all survive onto the field, and no normalised mapping carries a word of compliance vocabulary

Backward compatibility, classifier isolation and the stability of compliance
results are pinned where they already were:
`backend/apps/extraction/tests/test_pipeline_contract.py` (a reading survives
into the database and back unchanged; an unread observation is never a stored
field), `backend/apps/compliance/tests/test_classification_isolation.py` (the
decision path never reads run metadata), and
`backend/apps/rules/tests/test_quantity_units.py` (the SI vocabulary matches
the extractor's).

---

## 7. Performance

Field extraction is timed on its own, because the end-to-end figure is almost
entirely Tesseract and cannot show a change in the interpretation layer.
Replayed over the same 28 stored readings (674 lines), 20 passes, median:

| | before | after |
|---|---:|---:|
| Field extraction, per image | 0.67 ms | **0.70 ms** |
| Full pipeline, median per image | 1,129 ms | 1,056–1,071 ms |

**+0.03 ms per image, about 0.003 % of end-to-end time.** No second OCR pass,
no extra full-text scan, no model load, no database call was added. The one
extra scan — `QUANTITY.finditer` in place of `.search` on net-quantity lines —
was measured directly and costs the same as `.search` at every input size,
because the scan cost is paid per start position either way.

`patterns.QUANTITY` is quadratic on a pathological input (≈250 ms on 3,200
characters of digits followed by units). That is pre-existing and unchanged:
`finditer` and `search` measure within noise of each other at every size
tested. Real recognised lines top out at 103 characters, where the whole
674-line corpus costs 23 µs per line.

---

## 8. Security

- **No new logging.** The diff adds no `logger` call, no `print`, and no file
  or network I/O. Raw images and OCR text are logged exactly as much as before,
  which is not at all.
- **No new dependencies.** `ml/pyproject.toml` is untouched; `labelextract`
  keeps its zero-runtime-dependency guarantee. The diff adds no module-level
  import.
- **No client-controlled patterns.** Every regex is a module-level constant.
  Nothing in the request path configures, composes or compiles a pattern, and
  no extraction behaviour is parameterised by anything a caller sends.
- **Upload validation untouched.** `apps/images/` is not in the diff; uploaded
  content is validated by the same pipeline as before.
- **No secrets.**

---

## 9. Compatibility

- `ExtractionResult`, `ExtractedField`, `UnreadDeclaration`, `OcrResult` and
  `ProductClassification` are unchanged. No field was added or removed from any
  contract.
- No new key appears in `normalized_value`. The mappings emitted use the same
  vocabulary as before — `candidates` and `uncertainty_reasons` are existing
  keys the extractor already wrote on other paths.
- No API serializer, endpoint, response shape or status code changed. No
  migration is needed (`makemigrations --check`: no changes).
- Web and mobile clients are untouched and pass unchanged.
- The registered pipeline versions are deliberately unchanged, for the reason
  `labelextract/ocr/tesseract.py` states: a pipeline version pins engine and
  preprocessing *configuration*, and explicitly does not pin
  `labelextract.fields`, which every registered pipeline imports from one
  module. `rule-based-fields` 0.2.0 is how this correction is named; the commit
  is what reproduces a reading exactly.

### What a consumer may observe differently

Nothing breaks, but three readings change shape, and a client that renders them
should expect it:

- a `net_quantity` read off a line carrying several quantities now arrives
  `uncertain: true` with `candidates`;
- a `batch_number` whose value has no digit is no longer emitted;
- a `date_of_manufacture` or `date_of_packing` may now appear in
  `metadata["unread_declarations"]` where previously neither a field nor an
  observation was produced.

The third is additive. The first two remove claims the system should not have
been making.

---

## 10. Remaining limitations

- **Recall is bounded by recognition on this corpus, not by extraction.** In 88
  of 94 misses the printed value was either not recognised or came back too
  corrupted to recover without inventing characters. The rupee glyph is
  unreadable by construction — `U+20B9` is not in the `eng` LSTM alphabet.
- **`p004_01_back` is recognised upside down.** Orientation detection is not
  applied; every declaration on that panel is lost.
- **`p002_01_back` recognises nothing at all.**
- **Symbol legends are not resolved.** `p003_03_right` prints `#MFD. & @USE
  BEFORE: SEE BELOW.` and, two lines down, `#12/25 @04/28`. A person follows
  the markers. This extractor reads lines and does not.
- **Layout is still not understood.** Multi-line addresses, values in a column
  beside their label, and text wrapped mid-declaration are all missed. The
  one-line lookahead is the whole of the layout reasoning and it is always
  flagged.
- **`Date of Packaging` is matched by no pattern.** `pack(?:ing|ed)?\b` does
  not reach `Packaging`, and neither the detector nor the new anchor matches
  it. Consistent — the extractor never looks for that spelling, so it never
  reports one unread either — but a real phrasing, appearing on two packs in
  the frozen set. Widening both is unmeasured recall work; a regression test
  records the limitation so it is not rediscovered.
- **Devanagari is not matched by any pattern**, though the OCR layer recognises
  it when the language data is installed.
- **`common_or_generic_name` and `manufacturer_address` are still not
  attempted**, and `LM-PC-0002` stays deactivated for that reason.
- **The ground truth is 330/364 model-drafted.** Every figure here is against a
  partially verified artefact.
- **No compliance-verdict quality is measured** by this work, and none is
  claimed.
