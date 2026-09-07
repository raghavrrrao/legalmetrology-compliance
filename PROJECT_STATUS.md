# Project status

What works today, what does not, and what the system is careful **not** to
claim. Written to be read before a demonstration, so that nothing on screen has
to be explained away afterwards.

Companion documents: [`ARCHITECTURE.md`](ARCHITECTURE.md) for how it is built,
[`docs/api.md`](docs/api.md) for the contract, [`rules/README.md`](rules/README.md)
for what the rule set actually checks, and
[`rules/SOURCES.md`](rules/SOURCES.md) for where the law came from.

---

## The one-line version

An end-to-end pipeline — upload a label photograph, read it, check it against
**eleven** executable rules drawn from the Legal Metrology (Packaged
Commodities) Rules, 2011, and show every finding with the clause behind it and
the evidence it rests on.

**It does not automate the Rules.** Sixty-nine clause-level requirements are on
record; eleven executable rules reach eight of them, and every one of those
eleven checks *less* than its clause requires. The rest are inventoried
precisely so what the software cannot check is visible rather than absent.

---

## The pipeline, stage by stage

| Stage | State | Where |
|---|---|---|
| Upload & validation | Working. Content-type, size, decodability and dimensions are measured from the bytes, never trusted from the request. | `apps/images/` |
| OCR | Working with Tesseract 5. A placeholder engine is configurable and is flagged all the way to the UI so its output can never be shown as a real reading. | `ml/labelextract/ocr/` |
| Field extraction | Working for 14 declarations. Two — common/generic name and address — are **not attempted**, and their absence carries no information. | `ml/labelextract/fields/` |
| Normalisation | Working. Refuses to resolve an ambiguity: `03/04/2025` is emitted with both candidates and marked uncertain rather than guessed. | `ml/labelextract/fields/normalisation.py` |
| Applicability | Working. Rules 3 and 26 scope gates, then each clause's own conditions, resolved from stated facts **before** any rule is evaluated. | `apps/compliance/services/applicability.py` |
| Rule engine | Working. Seven registered deterministic checks; no LLM anywhere in the decision path. | `apps/rules/checks/` |
| Findings & result | Working. One finding per rule examined, with clause, source, evidence, confidence and applicability. | `apps/compliance/services/engine.py` |
| Frontend | Working. Scan, result, permalink and history screens against the real API, with the declaration form and the full finding trace. | `frontend/src/` |
| Mobile client | **Not built.** The API is client-agnostic and intended to serve one. | — |
| Authentication UI | **Not built.** Session auth and deny-by-default permissions exist; there is no login screen, so a demonstration switch (`DEMO_PUBLIC_ANALYSIS_API`, default off) opens the analysis endpoints locally. | — |

---

## What the rule engine actually checks

Eleven active rules over eight clauses. Each tests less than its clause
requires, and each rule file's own `requirement` text is narrowed to match so a
finding cannot read as a broader claim.

| Clause | What is checked | What is **not** |
|---|---|---|
| 6(1)(a) | Manufacturer, packer **or** importer name is present | The address — that is rule 10(1), and addresses are not extracted |
| 6(1)(aa) | Country of origin, on a package **declared** imported | Whether the country named is correct |
| 6(1)(c) | A net quantity is declared | Whether it is true — that needs a weighing |
| 6(1)(d) | A date is declared; that it resolves to a month and a year | Its printed format — the clause prescribes none |
| 6(1)(e) | A price is declared; that it is not declared *exclusive* of taxes | Whether "MRP" alone indicates tax inclusion (legal construction); "in Indian currency" |
| 6(2) | A consumer-care contact is declared; that it states a telephone **and** an e-mail | The **name and address** of the person or office |
| 13(4) | No dozen, score, gross or great gross in the quantity | Units "or the like"; anything outside the quantity declaration |
| 13(5) | The quantity's unit is SI, or a unit of number | — |

**Not automated, and deliberately so:** rules 7, 8(1) and 9(1)(b) need a
millimetre scale a photograph does not carry; rule 9(4) needs Devanagari OCR,
without which a Hindi label reads as *unreadable* rather than compliant; rule
10(1) needs addresses; rules 11(2)–(4), 12(6) and 13(2)–(3) have empty or
summarised clause text in the framework and must be transcribed by a named
reviewer first; rules 19–23 are physical inspection.

---

## The four outcomes, and why the third one matters

| Result | Meaning |
|---|---|
| `COMPLIANT` | Every applicable rule was evaluated and passed. **Not a certification** — it covers only the loaded rules and only what was legible. |
| `NON_COMPLIANT` | Verified rules were not met, with evidence. |
| `PARTIALLY_COMPLIANT` | Some rules failed, others could not be determined. |
| `REVIEW_REQUIRED` | Nothing could responsibly be concluded. **The default, and a first-class outcome.** |

Per finding there is a fourth status, `NOT_APPLICABLE`: the rule does not govern
this package, so nothing about its declarations was examined. It is **not** a
pass, and it is counted outside `rules_evaluated` for that reason.

Five engine guarantees, each covered by a test:

1. No rules checked → never `COMPLIANT`.
2. An unverified rule can never produce a violation.
3. An unreadable photograph is never a missing declaration.
4. An unestablished fact never produces a verdict.
5. A reading the extractor would not commit to, or one with a low reported
   confidence, never produces a violation.

**There is no compliance score.** No percentage, no grade, no aggregate
confidence — in the API or in the UI. A number would imply that partial
compliance with a labelling requirement is partial credit.

---

## Open items that a reviewer must know about

1. **The amendment chain has a gap.** The Department's consolidated publication
   annotates amendments up to G.S.R. 226(E) (28 March 2022), while G.S.R. 128(E)
   records the principal rules as last amended by G.S.R. 881(E) (2 December
   2025). The notifications in that window could not be retrieved. Read
   "verified" in this repository as *verified against the Department's
   consolidated publication*, not against every notification in force.
2. **No named human reviewer.** Every rule's `source_note` ends by saying human
   counter-review is outstanding. A qualified reviewer who has read the source
   should replace that with their name.
3. **Rules 3 and 26 do not bite unless declared.** A gate nobody answered leaves
   the package evaluated, with the caveat carried on every finding's
   `applicability_note`. Declaring the facts is what removes it.
4. **Ownership is not enforced.** Any caller allowed through the analysis
   endpoints can read any stored result. That belongs to the authentication
   work, not to a list view.
5. **`LM-PC-0002` is inactive** because the extractor does not read the
   declaration it names. Reactivating it needs measured extraction recall, not a
   legal decision.

---

## What this system is not

- **Not a legal authority.** It assists a human reviewer. Every finding is the
  output of one deterministic check against one reading of one photograph.
- **Not an enforcement instrument.** It computes no penalty and makes no
  determination under the Act.
- **Not an LLM deciding compliance.** AI/OCR assists with *extraction only*. The
  legal requirements live in versioned data and a deterministic engine; no model
  output reaches a verdict.
- **Not complete.** Any relaxation granted under rule 33 is invisible to it,
  whatever anybody declares.

---

## Verification

```bash
cd backend  && pytest -q      # 762 passing
cd ../ml    && pytest -q      # 575 passing
cd ../frontend && npm test    # 202 passing
```

Counts are as of the Step 4 integration work and are stated so a drift is
noticeable, not as a quality claim: a passing suite bounds what is checked, not
what is correct.
