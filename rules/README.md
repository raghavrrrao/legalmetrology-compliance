# `rules/` — compliance rule definitions

This directory holds the compliance rules as **version-controlled data**, not as
Python code. Rules are authored here as JSON files, reviewed through pull
requests like any other change, and loaded into PostgreSQL with:

```bash
python backend/manage.py load_rules
```

## Why rules are data and not `if` statements

The Legal Metrology (Packaged Commodities) Rules, 2011 change by amendment, and
which declarations apply depends on the commodity. Encoding that as branching
Python would mean every amendment is a code change, every rule is invisible to
anyone who does not read Python, and nothing can be audited.

Keeping rules as data buys three things that matter for this project:

- **Reviewable.** A rule change is a diff a non-programmer can read.
- **Auditable.** Every rule carries where it came from and whether that source
  has been verified.
- **Additive.** Adding a rule is a new file plus `load_rules`. No application
  code changes, so `feature/legal-rules-dataset` and
  `feature/compliance-rule-engine` do not collide.

## What this directory currently ships

Twelve rules, from rules 6 and 13 of the Legal Metrology (Packaged Commodities)
Rules, 2011. **Eleven are evaluated; one is recorded but inactive.**

| Code | What it tests | Provision | Active |
|---|---|---|---|
| `LM-PC-0001` | Manufacturer, packer **or** importer name is present | Rule 6(1)(a) | yes |
| `LM-PC-0002` | Common or generic name is present | Rule 6(1)(b) | **no** |
| `LM-PC-0003` | Net quantity is present | Rule 6(1)(c) | yes |
| `LM-PC-0004` | Month and year of manufacture is present | Rule 6(1)(d) | yes |
| `LM-PC-0005` | Retail sale price (MRP) is present | Rule 6(1)(e) | yes |
| `LM-PC-0006` | A consumer-care declaration is present | Rule 6(2) | yes |
| `LM-PC-0007` | Country of origin is present (imported only) | Rule 6(1)(aa) | yes |
| `LM-PC-0008` | Net quantity is in SI units, or by number | Rule 13(5) | yes |
| `LM-PC-0009` | Net quantity uses no dozen, score, gross | Rule 13(4) | yes |
| `LM-PC-0010` | Consumer care states a **telephone number and an e-mail address** | Rule 6(2) | yes |
| `LM-PC-0011` | Manufacture date **resolves to a month and a year** | Rule 6(1)(d) | yes |
| `LM-PC-0012` | Price is **not declared exclusive of all taxes** | Rule 6(1)(e) | yes |

**Each of these tests less than its clause requires**, deliberately, and each
rule file's `requirement` text is narrowed to what is actually tested so a
finding cannot read as a broader claim. `FRAMEWORK.md` has the clause-by-clause
table of what is and is not checked.

Six were activated in Step 2, and none by relaxing a safeguard. Two things
changed underneath them: applicability conditions became collectable, so an
exemption is now a declared fact rather than something the category taxonomy
had to express; and `field_presence_any_of` expresses the disjunction in rule
6(1)(a) that a single-key check could not.

### The three Step 3 rules, and why they are separate files

`LM-PC-0010`, `-0011` and `-0012` each name a clause an earlier rule already
covers. That is deliberate and is what `ComplianceRule.rule_requirement` is
shaped for: presence and manner-of-declaration are separate questions about one
clause, and answering them in one rule would produce one blurred finding
instead of two precise ones. A package that declares a consumer-care phone
number but no e-mail gets a pass on `LM-PC-0006` and a failure on `LM-PC-0010`
naming the e-mail, rather than a single verdict a reader has to interpret.

The three follow the same rule as `LM-PC-0008`/`-0009` when the declaration
they judge is **absent**: they report inconclusive and point at the presence
rule, so one missing declaration is one violation and not two.

What each of them deliberately does **not** decide is the more important half:

- `LM-PC-0010` does not check the **name or the address** of the person or
  office to be contacted. Neither is extracted, and rule 10(1) is the operative
  address provision.
- `LM-PC-0011` enforces **no printed format**, because the clause prescribes
  none. `12/2024` and `DEC 2024` both pass; an ambiguous `03/04/2025`, where
  the year is settled and the month is not, is sent for review and is never
  reported as a violation.
- `LM-PC-0012` does not treat the **absence** of an "inclusive of all taxes"
  indication as a violation - whether printing "MRP" alone already indicates it
  is a question of legal construction - and does not check "in Indian currency"
  at all, because the normaliser writes the currency as a fixed default rather
  than reading it off the label.

Nothing in Step 3 rests on a legal source that was not already verified for the
rule it sits beside. No new instrument was consulted and no requirement was
widened; each new file narrows an existing verified clause to a further
question the evidence can answer.

Every one of them is `source_status: "verified"` against the Department of
Consumer Affairs' own consolidated publication. What was read, from where, with
what checksum, and quoted verbatim clause by clause, is recorded in
[`SOURCES.md`](SOURCES.md). Read that before changing anything here.

**Twelve rules is not the legal inventory.** [`INVENTORY.md`](INVENTORY.md) records
every requirement of the Rules relevant to this project - rules 3 to 34 - and
for each one whether this software can evaluate it, what blocks it, and which
check type it would need. Read it before proposing a new rule file: most of
what is missing is blocked on applicability data or a check type, not on
someone writing more JSON.

That inventory is now also **data**. [`framework/`](framework/) holds rules 1
to 34 as versioned, clause-level records with their amendments, applicability
conditions and legal sources, loaded by `manage.py load_legal_framework`. It is
a separate directory from `definitions/` because the two answer different
questions: `definitions/` is what the engine *runs*, `framework/` is what the
law *requires* - including the thirty-odd obligations no photograph can decide.
69 requirements are recorded there; 11 executable rules cover 8 of them. See
[`FRAMEWORK.md`](FRAMEWORK.md) for the model, the versioning rules, and the
open gaps in the legal record.

This project makes legal compliance determinations, so a rule that is invented,
half-remembered, or paraphrased from a blog post is worse than no rule at all:
it produces a confident, wrong, official-looking answer. Nothing here is
paraphrased — the statutory wording sits verbatim in each rule's `source_note`.

### `LM-PC-0002` is inactive: the extractor cannot read the declaration

`LM-PC-0002` names `common_or_generic_name`, which is in
`labelextract.fields.UNSUPPORTED_KEYS` — identifying a generic name needs
layout analysis the pattern-matching field layer does not do.

While it was active it reported a violation against **every** product, because
the field is absent from every run the extractor produces. `field_presence`
cannot tell "the extractor does not look for this" apart from "the package does
not declare it", so **`is_active: false` is the only thing preventing that, and
reactivating the rule would restore the bug.**

The legal text, wording and applicability are unchanged and still verified.
The blocker is technical, and closing it properly is separate work outside this
branch: teach the extractor to read the declaration, or give the check a
per-run signal for what the engine actually attempted. Neither is a legal
decision. See [`INVENTORY.md`](INVENTORY.md).

### How the other three were unblocked

`LM-PC-0001`, `LM-PC-0004` and `LM-PC-0005` were inactive until Step 2, each
blocked on something the machinery could not express. None was activated by
editing the flag; the blockers were removed:

- **`LM-PC-0001`** — rule 6(1)(a) is disjunctive: a package satisfies it by
  declaring the manufacturer, *or* the manufacturer and packer, *or* (when
  imported) the importer. `field_presence` tests exactly one `field_key`, so a
  rule keyed on `manufacturer_name` reported a lawfully labelled imported
  package as non-compliant. **`field_presence_any_of` now tests the
  disjunction the clause actually states.**
- **`LM-PC-0004` and `LM-PC-0005`** — rule 6(1)(d) exempts cosmetics, certified
  seeds, bidi, incense sticks and domestic LPG cylinders; rule 6(1)(e) exempts
  bidi and APM-priced LPG, and defers to State Excise Laws for alcohol. All fall
  inside `packaged-non-food` with no narrower category. **They no longer need
  one:** the exemptions are applicability conditions on the clause, declared per
  submission and resolved before the validator runs. An exempt package is
  recorded `NOT_APPLICABLE`; a package whose exempting facts were never declared
  reaches `REVIEW_REQUIRED` rather than a violation. Both rules set
  `requires_applicability_conditions`, so neither can run unmapped.

Activating a rule is still a legal decision, not a configuration tweak, so
`backend/apps/rules/tests/test_shipped_definitions.py` pins the active set and
fails if it changes.

### What is deliberately not modelled

- **Rule 9(1)(a)** — "every declaration … shall be legible and prominent" is a
  property of rendering, not of presence. It needs `visual_check`, which is
  listed in `apps.rules.checks.PLANNED_CHECK_TYPES` and is **not registered**;
  the loader rejects any rule naming it. Expressing it with `field_presence`
  would silently answer a different question.
- **Rule 3 and rule 26 scope limits — now partly closed, and worth reading
  carefully.** Packages over 25 kg / 25 L, goods for industrial or institutional
  consumers, packages of 10 g / 10 ml or less, restaurant fast food, DPCO
  formulations. These turn on net quantity and on who the buyer is, neither of
  which is a `ProductCategory`, so no rule file can encode them — but they are
  now *declarable* per submission, and a declared gate takes the package out of
  scope entirely.

  What has **not** changed: a gate nobody answered does not bite, so an
  undeclared package is still evaluated against rules that may not govern it.
  Refusing to evaluate instead would turn every existing submission into "we
  cannot tell you anything". The caveat is carried on every finding's
  `applicability_note` rather than the evaluation refused. See
  [`FRAMEWORK.md`](FRAMEWORK.md).
- **Every active rule is an approximation, all under-claiming.** Step 3
  narrowed three of the gaps and left the rest open, on purpose:

  - **Rule 6(2)** requires name, address, telephone number *and* e-mail
    address. `LM-PC-0006` asks whether a consumer-care declaration was read;
    `LM-PC-0010` now checks the **telephone number and the e-mail address**
    individually. The **name and the address are still not checked** — neither
    is extracted, and rule 10(1) is the operative address provision.
  - **Rule 6(1)(e)** requires the price to be "clearly indicated as the maximum
    retail price inclusive of all taxes in Indian currency". `LM-PC-0005`
    checks that a price is present; `LM-PC-0012` now reports a price declared
    **exclusive** of all taxes. The **absence** of an inclusive-of-taxes
    indication is recorded but is **not** a violation, and "in Indian currency"
    is not checked at all — see the rule file for why each is left alone.
  - **Rule 6(1)(d)** requires a month and a year. `LM-PC-0004` checks that a
    date declaration is present; `LM-PC-0011` now checks that it **resolves to
    a month and a year**, enforcing no printed format because the clause
    prescribes none.
  - **Rule 6(1)(a)** covers the name *and address*; `LM-PC-0001` checks the
    name only, because `manufacturer_address` is unextractable and rule 10(1)
    is the operative address provision. **Unchanged in Step 3.**

  Each rule file's `requirement` text is narrowed to what is actually tested,
  so a finding cannot read as the fuller claim.
- **Rules 7 to 13 gained nothing in Step 3, and that is the finding.** Every
  remaining candidate is blocked by something no amount of JSON fixes: rules 7
  and 8(1) need a millimetre scale a photograph does not carry; rule 9(4) needs
  an extractor that reads Devanagari, without which a wholly Hindi label reads
  as unreadable rather than as compliant; rule 10(1) needs addresses, which are
  not extracted; and rules 11(2)–(4), 12(6) and 13(2)–(3) have **empty or
  summarised `verbatim_text`** in `framework/rules.json` — 12(6)'s candidate
  word list is recorded there as coming from the *pre-2011* text. Coding any of
  those would mean writing a requirement from a summary, or enforcing a
  repealed instrument. Each is left for a named reviewer to transcribe.
- **Best-before/use-by, dimensions, unit sale price** — each is conditional on
  a fact the system does not hold, or needs a declaration the extractor does not
  read. `SOURCES.md` quotes each provision and says why no file exists. Country
  of origin is no longer on this list: rule 6(1)(aa) is `LM-PC-0007`, applied
  only to a package **declared** imported.

### Two review items are still open

Recorded here so they are not lost between branches:

1. **Amendment-chain gap.** The consolidated source's footnotes stop at
   G.S.R. 226(E) (28 March 2022), while the February 2026 Gazette states the
   principal rules were last amended by G.S.R. 881(E) (2 December 2025). The
   notifications in that window could not be retrieved. Treat `verified` here
   as "verified against the Department's consolidated publication", not
   "verified against every notification in force".
2. **No named human reviewer.** Each `source_note` ends with an explicit
   note that human counter-review is outstanding. A reviewer who has read the
   source should replace it with their own name.

With no *applicable* rule, the compliance engine still cannot return
`COMPLIANT`. It returns `REVIEW_REQUIRED` — "nobody has checked this", not
"this is fine". That behaviour is enforced by a test
(`backend/apps/compliance/tests/test_engine.py`), and again at the API boundary
in `test_evaluation_api.py`, where a label whose every declaration was read at
0.99 confidence still comes back `review_required` because no rule was loaded
to check it against. A reading is not a verdict.

## What a rule produces when it is evaluated

Every applicable rule leaves a `ComplianceFinding` — a row naming the rule, the
requirement in its own words, the declaration it concerns, what was read, the
OCR confidence behind that reading, what the check concluded, and why. Rules
that pass and rules that could not be decided get one too, which is what makes
"what was actually checked?" answerable rather than a count.

A finding is **not** a legal conclusion on its own. It is the output of one
deterministic check against one reading of one photograph. The overall verdict
is derived from all of them together by
`backend/apps/compliance/services/engine.py`, under the three guarantees
documented at the top of that file.

## Rule file format

One rule per file, named `<code>.json`. See `TEMPLATE.json.example` for a
commented skeleton and `SCHEMA.md` for the field-by-field specification.

```json
{
  "code": "LM-PC-0001",
  "title": "Short human-readable name",
  "requirement": "What the package must declare, in plain language.",
  "legal_reference": "Rule <n>(<sub>) of the Legal Metrology (Packaged Commodities) Rules, 2011",
  "source_status": "verified",
  "source_note": "Checked against the Gazette text on 2026-08-25 by <name>.",
  "severity": "major",
  "check_type": "field_presence",
  "parameters": { "field_key": "net_quantity" },
  "applies_to_category_codes": ["packaged-food"],
  "effective_from": "2011-04-01",
  "effective_to": null,
  "is_active": true
}
```

## The `source_status` field is not optional bookkeeping

Every rule declares whether its legal text has been checked against the
authoritative source:

| Value | Meaning |
|---|---|
| `verified` | A named person checked this against the Gazette text and recorded it in `source_note`. |
| `unverified` | Drafted but not yet checked. **Loaded, but never used to fail a product.** |

The engine treats `unverified` rules as `REVIEW_REQUIRED` rather than as
violations. An unverified rule can flag a product for a human to look at. It can
never, on its own, tell a user their product breaks the law.

When that downgrade happens it is recorded, not merely applied: the rule's
`ComplianceFinding` is stored with `status: inconclusive` and
`downgraded_from_failed: true`, and the API returns both. A reviewer can see
that the check *did* fail and that the safeguard is the only reason it is not a
violation — rather than having to infer it from the rule code.

Do not set `source_status` to `verified` without filling in `source_note` with
who checked it and against what. The loader rejects the file if you do.

## Authoring workflow

1. Read the authoritative text of the rule. Not a summary of it.
2. Copy `TEMPLATE.json.example` to `definitions/<code>.json`.
3. Fill in `legal_reference` exactly as the source numbers it. Do not invent or
   guess a rule number — leave it blank and use `source_status: "unverified"`
   if you are not certain.
4. Choose the narrowest `applies_to_category_codes` that is correct. An empty
   list means the rule applies to every commodity, which is a strong claim.
5. Record the provenance in [`SOURCES.md`](SOURCES.md): the document, its URL
   and checksum, when it was retrieved, and the clause quoted verbatim.
6. Run `python backend/manage.py load_rules --dry-run` to validate.
7. Open a PR on `feature/legal-rules-dataset`. Rule changes need review from
   someone who has also read the source.

## Adding a new `check_type`

`check_type` names a validator registered in
`backend/apps/rules/checks/`. The base ships one: `field_presence`, which asks
only "was this declaration found in the extracted data?" — a mechanical
question with no legal content.

Adding a comparison or format check means adding a validator there and
registering it. See `backend/apps/rules/checks/__init__.py`.
