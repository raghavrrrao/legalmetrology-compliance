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

## This directory currently ships ZERO rules

`definitions/` contains only `TEMPLATE.json.example`, which the loader ignores
(it reads `*.json` only). That is deliberate, and it is the single most
important thing to understand about this branch.

**We have not verified any rule text against the authoritative source.** This
project makes legal compliance determinations, so a rule that is invented,
half-remembered, or paraphrased from a blog post is worse than no rule at all:
it produces a confident, wrong, official-looking answer.

Until real rules are loaded, the compliance engine cannot return `COMPLIANT`.
With zero applicable rules it returns `REVIEW_REQUIRED` — "nobody has checked
this", not "this is fine". That behaviour is enforced by a test
(`backend/apps/compliance/tests/test_engine.py`).

Populating this directory is the job of `feature/legal-rules-dataset`, working
from the authoritative Gazette text.

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
5. Run `python backend/manage.py load_rules --dry-run` to validate.
6. Open a PR on `feature/legal-rules-dataset`. Rule changes need review from
   someone who has also read the source.

## Adding a new `check_type`

`check_type` names a validator registered in
`backend/apps/rules/checks/`. The base ships one: `field_presence`, which asks
only "was this declaration found in the extracted data?" — a mechanical
question with no legal content.

Adding a comparison or format check means adding a validator there and
registering it. See `backend/apps/rules/checks/__init__.py`.
