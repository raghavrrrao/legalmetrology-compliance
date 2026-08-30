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

Six rules, drawn from rule 6 of the Legal Metrology (Packaged Commodities)
Rules, 2011. **Three of them are evaluated; three are recorded but inactive.**

| Code | Declaration | Provision | Active |
|---|---|---|---|
| `LM-PC-0001` | Manufacturer, packer or importer | Rule 6(1)(a) | **no** |
| `LM-PC-0002` | Common or generic name | Rule 6(1)(b) | yes |
| `LM-PC-0003` | Net quantity | Rule 6(1)(c) | yes |
| `LM-PC-0004` | Month and year of manufacture | Rule 6(1)(d) | **no** |
| `LM-PC-0005` | Retail sale price (MRP) | Rule 6(1)(e) | **no** |
| `LM-PC-0006` | Consumer care details | Rule 6(2) | yes |

Every one of them is `source_status: "verified"` against the Department of
Consumer Affairs' own consolidated publication. What was read, from where, with
what checksum, and quoted verbatim clause by clause, is recorded in
[`SOURCES.md`](SOURCES.md). Read that before changing anything here.

This project makes legal compliance determinations, so a rule that is invented,
half-remembered, or paraphrased from a blog post is worse than no rule at all:
it produces a confident, wrong, official-looking answer. Nothing here is
paraphrased — the statutory wording sits verbatim in each rule's `source_note`.

### Why three rules are inactive

`is_active: false` means the rule is on record and loaded, but never evaluated.
Each of the three is blocked on something the current machinery cannot express,
and **none of them may be activated by editing the flag alone**:

- **`LM-PC-0001`** — rule 6(1)(a) is disjunctive: a package satisfies it by
  declaring the manufacturer, *or* the manufacturer and packer, *or* (when
  imported) the importer. `field_presence` tests exactly one `field_key`, so a
  rule keyed on `manufacturer_name` would report a lawfully labelled imported
  package as non-compliant. Needs a check type that can test a disjunction.
- **`LM-PC-0004`** — rule 6(1)(d) exempts cosmetics, certified seeds, bidi,
  incense sticks and domestic LPG cylinders. All fall inside
  `packaged-non-food` and there is no narrower category to attach the rule to.
- **`LM-PC-0005`** — rule 6(1)(e) exempts bidi and APM-priced LPG cylinders,
  and defers to State Excise Laws for alcoholic beverages. Same problem.

Activating one is a legal decision, not a configuration tweak, so
`backend/apps/rules/tests/test_shipped_definitions.py` pins the active set and
fails if it changes.

### What is deliberately not modelled

- **Rule 9(1)(a)** — "every declaration … shall be legible and prominent" is a
  property of rendering, not of presence. It needs `visual_check`, which is
  listed in `apps.rules.checks.PLANNED_CHECK_TYPES` and is **not registered**;
  the loader rejects any rule naming it. Expressing it with `field_presence`
  would silently answer a different question.
- **Rule 3 and rule 26 scope limits** — packages over 25 kg / 25 L, goods for
  industrial or institutional consumers, packages of 10 g / 10 ml or less,
  restaurant fast food, DPCO formulations. These turn on net quantity and on
  who the buyer is, neither of which is a `ProductCategory`, so no rule file
  can encode them. An active rule will therefore be applied to a package that
  is in fact outside the rules.
- **`LM-PC-0006` is an approximation.** Rule 6(2) requires name, address,
  telephone number *and* e-mail address. `field_presence` asks only whether a
  consumer care declaration was read. It under-claims, which is the safe
  direction, but it is not the full requirement.
- **Country of origin, best-before/use-by, dimensions, unit sale price** — each
  is conditional on a fact the system does not hold. `SOURCES.md` quotes each
  provision and says why no file exists.

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
(`backend/apps/compliance/tests/test_engine.py`).

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
