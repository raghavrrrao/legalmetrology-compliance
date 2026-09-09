# The legal framework layer

`rules/framework/` holds the record of **what the Legal Metrology (Packaged
Commodities) Rules, 2011 require** — clause by clause, version by version —
whether or not this software can evaluate any of it.

`rules/definitions/` holds something different: the **executable** rules, each
binding a registered validator to a set of commodity categories. Twelve of those
ship; eleven are evaluated, they reach eight clauses between them, and each
tests less than its clause requires — the table below says exactly how much
less.

Both are data, both are loaded by a management command, and the difference
between them is the point of this document.

---

## Why there are two layers

The executable layer cannot honestly represent most of the Rules.

Rule 22 fixes the maximum permissible error between a declared quantity and the
actual one. Rules 27–30 require registration with a regulator. Rule 32 sets
penalties. These are real obligations, and **no photograph decides any of
them.** Recording them only as `ComplianceRule` rows would force a choice
between two bad options:

- **omit them** — leaving the widest compliance risk invisible, and letting
  "we inventoried the applicable requirements" quietly mean "we listed the six
  we could check"; or
- **include them** — and have the engine try to evaluate a JPEG against a
  weighing obligation.

So the framework records every rule from 1 to 34, and each requirement carries
a `detection_method` saying what evidence could settle it *at all*. Anything
outside `ocr` / `cv` / `ocr_cv` cannot be decided from an image, and the honest
output for it is `REVIEW_REQUIRED` — not because the engine is immature, but
because the evidence is not in the building.

**Recording a requirement here does not mean the system evaluates it.**
`manage.py load_legal_framework` prints that sentence in its own output, because
"35 rules loaded" is exactly the line someone would repeat as "35 rules
implemented".

---

## What currently ships

| | Count |
|---|---:|
| Legal instruments (notifications and publications) | 14 |
| Applicability conditions | 39 |
| Rules recorded (1–34, plus a placeholder for 32-A) | 35 |
| Clause-level requirements | 69 |
| Requirements marked `implemented` | **8** |

The eight implemented requirements, and exactly what each one tests. Three
clauses carry **two** rules: presence and manner-of-declaration are separate
questions, and answering them separately is what makes a finding say which one
failed.

| Clause | Rule | What is checked | What is NOT |
|---|---|---|---|
| 6(1)(a) | `LM-PC-0001` | The manufacturer's, packer's **or** importer's name | The address — that is rule 10(1), and `manufacturer_address` is unextractable |
| 6(1)(aa) | `LM-PC-0007` | Country of origin, on a package **declared imported** | Whether the country named is correct |
| 6(1)(c) | `LM-PC-0003` | A net quantity is declared | Whether it is true — that is a weighing |
| 6(1)(d) | `LM-PC-0004` | A month and year of manufacture is declared | — (presence only) |
| 6(1)(d) | `LM-PC-0011` | That the declaration **resolves to a month and a year** | Its printed format — the clause prescribes none, so none is enforced. An ambiguous date is review, never a violation |
| 6(1)(e) | `LM-PC-0005` | A retail sale price is declared | — (presence only) |
| 6(1)(e) | `LM-PC-0012` | That the price is **not declared exclusive of all taxes** | The *absence* of an inclusive-of-taxes indication, which is legal construction; "in Indian currency", which the normaliser defaults rather than reads; whether the price is the true maximum |
| 6(2) | `LM-PC-0006` | A consumer-care contact is declared | — (presence only) |
| 6(2) | `LM-PC-0010` | That it states a **telephone number and an e-mail address** | The **name and the address** of the person or office — neither is extracted, and rule 10(1) is the operative address provision |
| 13(4) | `LM-PC-0009` | No dozen, score, gross, great gross in the quantity | Units "or the like"; anything outside the quantity declaration |
| 13(5) | `LM-PC-0008` | The quantity's unit is SI, or a unit of number | — |

A manner-of-declaration rule whose declaration is **absent** reports
inconclusive and defers to its presence rule, so one missing declaration
produces one violation rather than two. All three read the *normalised* value
and share one evidence gate: an uncertain interpretation or a low reported OCR
confidence yields review, never a violation. See `rules/SCHEMA.md`.

`LM-PC-0002` (rule 6(1)(b), common or generic name) remains **inactive**, and
no applicability input fixes it: the extractor does not read the declaration, so
the rule could only ever return "cannot tell". Reactivating it needs measured
extraction recall, not a legal decision.

A test asserts that no requirement may be marked `implemented` without an active
`ComplianceRule` behind it.

---

## The applicability engine

`apps/compliance/services/applicability.py`. This is what turns the recorded
conditions into decisions, and it runs **before** any validator.

```
Product + ProductApplicabilityDeclaration
    -> resolve each condition        YES / NO / UNKNOWN
    -> rules 3 and 26, once          in scope, or out of it entirely
    -> per requirement               APPLIES / DOES_NOT_APPLY / UNDETERMINED
    -> evaluate, skip, or review
```

### The safety property

**An unestablished fact never produces a verdict.** A condition nobody answered
is `UNKNOWN`, and a clause turning on an `UNKNOWN` condition is `UNDETERMINED`
— recorded as inconclusive, never as a pass and never as a violation.

Three values rather than two, because whichever way the unknown case were
folded it would be wrong:

- folded into *applies*, an unanswered exemption produces violations against
  packages the Rules exempt;
- folded into *does not apply*, an unanswered trigger silently excuses a
  package from a declaration it owes.

### Where the facts come from

`ProductApplicabilityDeclaration` — one row per (product, condition), with a
**three-valued** answer. A boolean defaulting to false would make "nobody said"
indistinguishable from "no", which is the self-fulfilling inference the whole
design exists to prevent.

Nothing is read from the label. An extracted `net_quantity` is the declaration
being *checked*; using it to decide whether the check applies would be circular,
and a package omitting a declaration would appear exempt from making it. The one
exception is `PRODUCT_CATEGORY` conditions, answered from the product's category
ancestry — `packaged-food` answers `food-article` without anyone restating it.

A declaration is consulted **before** the category, so a reviewer correcting a
miscategorised submission is not overridden by the taxonomy. And a condition the
framework marks `NOT_DETERMINABLE` stays `UNKNOWN` even when declared: rule 33
relaxations cannot be confirmed from here, so a submitter's claim must not
switch a check off.

### The four link modes

| Mode | Meaning | Example |
|---|---|---|
| `REQUIRES` | Applies only when the condition holds | 6(1)(aa) binds imported products |
| `EXEMPTS` | Does not apply when it holds | Explanation III excuses food articles from 6(1)(a) |
| `SCOPE_GATE` | Removes the package from the Chapter, or the Rules | Rule 3(c), rule 26(a) |
| `WITHHOLDS_EXEMPTION` | **Cancels** a scope gate | Rule 26(a) does not reach tobacco |

`WITHHOLDS_EXEMPTION` was added in Step 2. Step 1 had recorded those provisos as
`REQUIRES`, which already means something else — read literally it said the
Rules apply *only* to tobacco and medical devices, the inverse of the proviso
and a reading that would exempt almost every package.

They combine in a fixed order, and the order matters: gates (and the provisos
that cancel them) first, then exemptions, then triggers. An `UNKNOWN` at any
step stops the decision there rather than falling through — a later step
answering "applies" would be asserting the earlier question was settled.

### Rules 3 and 26: an asymmetry worth understanding

These gate everything, so they are evaluated once per check rather than per
clause. **A gate takes effect only when it is affirmatively declared.**

A package declared as meant for an institutional consumer is out of scope, and
nothing is checked. A package where nobody said either way is **still
evaluated**, with the uncertainty recorded on every finding.

The stricter reading — treat an unanswered gate as undetermined and refuse to
evaluate — is more literal and wrong here. Nothing is declared by default, so it
would turn every existing submission into "we cannot tell you anything", which
is not more honest than findings plus a stated caveat, and would make the system
useless for the ordinary retail package that is most of its input.

So the caveat is carried rather than the evaluation refused, and it appears on
every finding: *an undeclared package may have been checked against rules that
do not govern it.* Declaring the facts is what removes it.

### `NOT_APPLICABLE` is a fourth outcome

Not a pass, and not a doubt. The rule does not govern this package, so nothing
about its declarations was examined.

Folding it into `passed` would let a package reach `COMPLIANT` on the strength
of the rules that did not apply to it — so `ComplianceCheck.rules_not_applicable`
is counted separately, and a check where **every** rule was ruled out returns
`REVIEW_REQUIRED`. A set of exemptions is not a clean bill of health.

---

## The models

All in `backend/apps/rules/models.py`, below the `ComplianceRule` it extends.

```
LegalInstrument        one Gazette notification or official publication
      │
      │ source
      ▼
LegalRule ──────────▶ RuleRequirement ──────────▶ RequirementApplicability
  rule 1..34            one clause,                 REQUIRES / EXEMPTS /
  + 32A                 one version                 SCOPE_GATE
                             │                             │
                             │ supersedes (self)           ▼
                             │                    ApplicabilityCondition
                             ▲                      determination:
                             │                      can we establish this?
                    ComplianceRule.rule_requirement
                     (the executable layer)
```

### `LegalInstrument`

One notification or publication. A table rather than a string on each
requirement, because an amendment is a **shared** fact: G.S.R. 629(E) changes
eight clauses recorded here, and its date of effect is one fact, not eight
copies that can drift apart.

`notified_on` and `effective_from` are separate columns and frequently years
apart — G.S.R. 312(E) is notified in April 2026 and commences in July 2027.
`effective_from` is null where an instrument commences different clauses on
different dates (G.S.R. 385(E)); the per-clause date lives on the requirement.

`source_sha256` pins exactly which bytes a claim was read from, so
re-verification is a comparison rather than an argument.

### `LegalRule`

Rules 1 to 34. A container, not an obligation — rule 6 is not something a
package can fail; rule 6(1)(c) is. `sort_key` is a zero-padded derived value
(`006`, `032A`) so rule 10 does not sort before rule 2 and 32-A falls between
32 and 33.

### `RuleRequirement`

The versioned unit. A row is not "rule 6(10A)" — it is *"rule 6(10A) as
inserted by G.S.R. 128(E)"*.

`requirement` is a plain-language restatement; `verbatim_text` is the
quotation. **Where they disagree the quotation governs.** A blank
`verbatim_text` means nobody has transcribed the clause — it is never filled
from paraphrase or memory, and roughly a dozen requirements ship blank for
exactly that reason.

### `ApplicabilityCondition`

The facts that decide whether a requirement applies: is this imported? a
wholesale package? bought by an institutional consumer?

`determination` is the field that matters, and for most conditions it is
`not_determinable`. That is the honest state of the system, and storing it
makes the caveat queryable instead of a paragraph in a document.

**Nothing here may be inferred from OCR.** A package that omits an importer's
name is not thereby domestic — it may be unlawful, or badly photographed.
`INVENTORY.md` makes the point against rule 6(1)(aa): inferring import status
from the presence of `importer_name` would make the rule self-fulfilling,
because a package omitting both would look exempt.

### `RequirementApplicability`

A through model, because the **direction** matters and is not recoverable from
the pair. "Imported product" *triggers* rule 6(1)(aa); "food article"
*disapplies* rule 6(1)(a). A bare link would record that the two are related
and lose the difference between requiring a declaration and excusing it.

`SCOPE_GATE` is the third mode: rules 3 and 26 remove a package from the
Chapter, or from the Rules entirely.

---

## Versioning

**An amendment adds a row. It never edits one.**

Past `ComplianceFinding` rows snapshot what they evaluated, and a requirement
rewritten in place would silently change what a finding recorded a year ago
meant. Versions coexist, each with its own `source`, its own effective window,
and a `supersedes` link back to the version it replaces.

`is_in_force_on(date)` answers which version speaks for a given date. Callers
that care about a date **must pass it** — `LegalInstrument` records notification
and commencement separately precisely because they differ.

### Rule 6(10A) — and a transition that is deliberately left open

This is the worked example, and the one place where the framework's honesty
costs something.

| Version | Instrument | In force from | `effective_to` |
|---|---|---|---|
| 1 | G.S.R. 128(E), notified 13 Feb 2026 | 2026-07-01 | **null** |
| 2 | G.S.R. 312(E), notified 27 Apr 2026 | 2027-07-01 | null |

Both notifications were retrieved and read in full. Neither states **when
version 1 ceases to apply.** The obvious inference — that it runs to 30 June
2027 — is an interpretation the sources do not establish, so `effective_to` is
left null and **both rows are flagged `REQUIRES_REVIEW`**.

The consequence: from 1 July 2027 *both* versions report as in force. That is
not a bug. It is the correct representation of an unresolved transition, and a
test asserts it so that a future change quietly closing version 1's window to
"tidy things up" has to fail and be justified against the Gazette instead.

Version 1's `verbatim_text` is also empty: `SOURCES.md` records what G.S.R.
128(E) *does*, not what it *says*, and a quotation must not be reconstructed
from a description of effect.

---

## Classification vocabularies

Three enums, all on `RuleRequirement`, answering three different questions.

**`detection_method` — what evidence could settle this at all?**

`ocr` · `cv` · `ocr_cv` · `database` · `user_input` · `digital_ecommerce` ·
`physical_inspection` · `administrative` · `manual_review` · `not_applicable`

Only the first three are `DetectionMethod.image_evaluable()`. Everything else
names evidence this pipeline does not have.

**`automation_class` — how far could automation ever get?**

`image_automatable` · `partially_automatable` · `digital_ecommerce` ·
`physical_measurement` · `administrative` · `manual_review`

Distinct from detection method. Rule 7 is `ocr_cv` yet only
`partially_automatable`: glyph geometry is measurable from an image, the
millimetre scale a photograph does not carry is not.

**`implementation_status` — what stands between it and evaluation today?**

The vocabulary is `INVENTORY.md`'s, kept word for word so the document and the
database cannot drift, plus `implemented`.

---

## Compliance statuses

The engine's verdicts are unchanged by this work:

| Result | Meaning |
|---|---|
| `COMPLIANT` | Every applicable rule was evaluated and passed. Not a certification. |
| `PARTIALLY_COMPLIANT` | Some rules failed, others could not be determined. |
| `NON_COMPLIANT` | Verified rules were not met, with evidence. |
| `REVIEW_REQUIRED` | Nothing could responsibly be concluded. **The default.** |

The Step 1 brief names this third state `REQUIRES_REVIEW`. This schema has
shipped it as `REVIEW_REQUIRED` since before this branch, and the API, the
frontend and every stored row use that value. It is the same status under the
name already in the contract; renaming it would break a shipped client to gain
nothing. `VerificationStatus.REQUIRES_REVIEW`, on the framework layer, is a
different axis — it describes the state of the *legal record*, not of a verdict.

---

## What a finding now carries

`ComplianceFinding` gained the legal context needed to audit an outcome against
the source:

| Field | Why |
|---|---|
| `rule_requirement` | The clause this outcome came from. Null when the rule is unmapped. |
| `clause` | `6(1)(c)`. Snapshotted, so filtering by clause needs no string-parsing of a citation. |
| `legal_source_citation` | `G.S.R. 629(E)`. Which amendment the finding rested on, kept legible after a later one supersedes it. |
| `detection_method` | Whether a photograph could ever have settled this. |
| `applicability_note` | Why the rule was applied, and **what about that could not be established.** |
| `extracted_raw_value` | The text exactly as recognised. |
| `extracted_normalized_value` | The interpretation of it. Null means no normaliser ran — never that the reading was empty. |

Raw and normalised are stored **side by side**. Normalisation is an
interpretation, and a reviewer needs the original to check it against.

`applicability_note` is written for **every** finding, including passing ones,
and always carries the scope caveat: applicability is decided from the commodity
category alone, the facts rules 3 and 26 turn on are not collected, and any
rule 33 relaxation is invisible here. A caveat recorded only when someone
remembers to record it is one a reader cannot rely on the absence of.

---

## Loading

```bash
python backend/manage.py seed_categories          # commodity taxonomy
python backend/manage.py load_rules               # executable rules
python backend/manage.py load_legal_framework     # this framework
```

Order matters only for the link between the layers: `load_legal_framework`
points named `ComplianceRule` rows at their requirement, and a code it cannot
find is **reported, not fatal** — on a fresh database the framework is often
loaded first. Re-run it after `load_rules` to complete the links.

Both loaders are idempotent, transactional, and strict: an unrecognised key is
rejected rather than ignored, because it is usually a typo in one that was
meant to change behaviour. If any file is invalid, nothing is written.

`--dry-run` validates and reports without writing.

---

## Authoring

Three files, each a JSON object with one top-level list.

### `instruments.json` → `{"instruments": [...]}`

| Field | Required | Notes |
|---|---|---|
| `citation` | yes | Unique. `G.S.R. 128(E)`. |
| `instrument_type` | yes | `principal` · `amendment` · `consolidated_publication` |
| `verification_status` | yes | `verified` · `unverified` · `requires_review` |
| `verification_note` | **when verified** | Who read it, when, and what they could not establish. |
| `title`, `notified_on`, `effective_from`, `source_url`, `source_sha256`, `is_active` | no | |

`verified` means **the instrument itself was read.** Only G.S.R. 128(E) and
G.S.R. 312(E) meet that bar today; a test enforces that a verified instrument
records a URL or a digest.

### `applicability_conditions.json` → `{"conditions": [...]}`

| Field | Required | Notes |
|---|---|---|
| `code` | yes | Unique slug. Referenced by requirements. |
| `name` | yes | |
| `determination` | yes | `product_category` · `user_declared` · `database` · `not_determinable` |
| `description`, `determination_note`, `is_active` | no | |

### `rules.json` → `{"rules": [...]}`

Each rule: `rule_number`, `title`, `automation_class`, `verification_status`
required; `chapter`, `description`, `notes`, `is_active`, `requirements`
optional. `sort_key` is derived, never authored.

Each entry in `requirements`:

| Field | Required | Notes |
|---|---|---|
| `clause` | yes | `6(1)(c)`. Unique with `version`. |
| `title`, `requirement` | yes | |
| `detection_method`, `automation_class`, `implementation_status` | yes | |
| `verification_status` | yes | |
| `source_note` | **when verified** | |
| `version` | no | Defaults to 1. |
| `supersedes_version` | no | Must name a lower version of the same clause, in the same file. |
| `verbatim_text` | no | **Leave empty rather than paraphrase.** |
| `source` | no | An instrument `citation`. Unknown citations are rejected. |
| `severity`, `legal_reference`, `effective_from`, `effective_to`, `is_active` | no | |
| `applicability` | no | `[{condition, mode, note}]`, mode ∈ `requires`/`exempts`/`scope_gate`. |
| `compliance_rule_codes` | no | Executable rules that evaluate this clause. |

Keys beginning `_` are documentation, not data — the same convention the
executable rule files use.

---

## Rules on authoring legal content

These are enforced by tests, not just convention.

1. **Never invent a requirement.** If `SOURCES.md` and `INVENTORY.md` do not
   establish it, it does not go in. Rule 32-A ships as an inactive placeholder
   with **no requirement** for exactly this reason: the Step 1 brief asks for
   it, and nothing in the project's verified material describes it.
2. **Never reconstruct a quotation from a summary.** `verbatim_text` empty is a
   fact about our knowledge. Filling it is a fabrication.
3. **Never invent a transition.** See rule 6(10A).
4. **A condition code is not a legal claim.** `pan-masala`,
   `aeo-bonded-warehouse` and `electronic-product` exist as vocabulary because
   the brief names them; no clause in the verified material turns on any of
   them, so none carries a requirement link, and a test enforces that.
5. **`verified` requires a named source note.** Enforced on the model and in
   the loader, so no path bypasses it.

---

## Known gaps — read before relying on any of this

- **The 2022–2025 amendment chain is not verified.** The Department's
  consolidated publication annotates amendments only to G.S.R. 226(E)
  (28 March 2022), while G.S.R. 128(E) states the rules were last amended by
  **G.S.R. 881(E), 2 December 2025** — a notification whose text could not be
  retrieved, because the hosts carrying it were unreachable or served expired
  certificates. G.S.R. 881(E) is on record as `requires_review` so the gap is
  visible. **Any requirement dated before December 2025 may have been amended
  without this framework knowing.**
- **No named human has counter-reviewed any of it.** Every `verified`
  requirement's `source_note` says so.
- **The Amendment Rules, 2025** (medical devices) are known only from a Press
  Information Bureau release, not the Gazette. Its G.S.R. number is unknown.
  Two applicability links cite it and both say so.
- **Rule 3 and rule 26 are not enforced.** Every active rule is applied to some
  packages the Rules do not govern — a 30 kg sack, a 5 g sachet, a restaurant
  takeaway box. No rule file can close this; it needs applicability inputs the
  system does not collect.
- **Rule 33 relaxations are invisible.** A relaxation makes an otherwise
  correct finding wrong, and there is no register available here. Every finding
  is conditional on none applying.

See [`SOURCES.md`](SOURCES.md) for the full provenance record and
[`INVENTORY.md`](INVENTORY.md) for the requirement-by-requirement analysis this
framework was built from.
