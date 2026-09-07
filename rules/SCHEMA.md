# Rule file schema

One JSON object per file, in `rules/definitions/`, named `<code>.json`.
Validated by `backend/apps/rules/loader.py`; the loader rejects the whole file
on any error rather than importing a partially understood rule.

> **This file covers the executable rules only.** The legal framework -
> instruments, applicability conditions, and rules 1-34 as versioned
> clause-level requirements - lives in `rules/framework/` with its own schema
> and its own loader. See [`FRAMEWORK.md`](FRAMEWORK.md).

| Field | Type | Required | Notes |
|---|---|---|---|
| `code` | string | yes | Unique, stable identifier. Uppercase letters, digits and hyphens. Never reused or renumbered — results reference it. |
| `title` | string | yes | Short human-readable name shown in the UI. |
| `requirement` | string | yes | What the package must declare, in plain language a non-lawyer can act on. |
| `legal_reference` | string | no | Provision as the source numbers it. Leave empty if not certain; never guess. |
| `source_status` | enum | yes | `verified` or `unverified`. See below. |
| `source_note` | string | conditional | **Required when `source_status` is `verified`**: who checked it, against what, when. |
| `severity` | enum | yes | `info`, `minor`, `major`, `critical`. Advisory ranking for triage; it carries no legal weight. |
| `check_type` | string | yes | Names a validator registered in `apps.rules.checks`. Unknown values are rejected at load time. |
| `parameters` | object | no | Configuration for the validator. Shape depends on `check_type`. Defaults to `{}`. |
| `applies_to_category_codes` | array of string | no | `ProductCategory.code` values this rule applies to. **Empty means "every commodity"** — a strong claim, so state it deliberately. Unknown codes are rejected. |
| `effective_from` | date `YYYY-MM-DD` | no | First date the rule applies. Null means "as far back as we model". |
| `effective_to` | date `YYYY-MM-DD` | no | Last date it applies. Null means "still in force". Must be after `effective_from`. |
| `is_active` | boolean | no | Defaults to `true`. Set `false` to keep a rule on record without evaluating it. |
| `requires_applicability_conditions` | boolean | no | Defaults to `false`. Set `true` when the rule is only safe to evaluate once its clause's applicability conditions have been resolved — see below. |

## `source_status`

| Value | Loaded? | Can produce a violation? | Effect on the result |
|---|---|---|---|
| `verified` | yes | yes | Can make a product `NON_COMPLIANT`. |
| `unverified` | yes | no | Contributes `REVIEW_REQUIRED` only. |

This split is what lets the team draft rules in parallel with verifying them
without risk of shipping an unverified rule as a legal finding.

## Available and planned check types

Only check types registered in `backend/apps/rules/checks/` may be used. A rule
naming anything else is rejected at load time, not silently skipped.

| `check_type` | Status |
|---|---|
| `field_presence` | **Available** |
| `field_presence_any_of` | **Available** — a disjunction of declarations, for rule 6(1)(a) |
| `si_unit` | **Available** — net quantity in SI units or by number, rule 13(5) |
| `prohibited_counting_unit` | **Available** — dozen, score, gross, great gross, rule 13(4) |
| `value_check` | Planned — compare a declaration against an expected value |
| `format_check` | Planned — validate shape (date format, units) |
| `numeric_check` | Planned — range and arithmetic checks |
| `conditional_check` | Planned — **superseded in practice.** Conditional applicability is now resolved by `apps.compliance.services.applicability` from the framework's conditions, before any validator runs, rather than by a check type. See `FRAMEWORK.md`. |
| `visual_check` | Planned — measure rendered properties such as declaration height |

The planned names are listed in `apps.rules.checks.PLANNED_CHECK_TYPES` purely
so the loader can report "planned but not implemented yet" instead of "unknown
check_type", which reads like a spelling mistake. **None of them is registered
or callable.** Nothing about listing them asserts that a corresponding legal
requirement exists.

### Adding a check type

Each check registers **two** callables together: the validator and a validator
for its own `parameters`.

```python
register_check(
    "format_check",
    check_format,
    parameter_validator=validate_format_parameters,
    description="Validate the shape of a declaration.",
)
```

Bundling them is deliberate. Parameter validation used to live in the loader
behind `if check_type != "field_presence"`, which meant any check added later
would silently receive no validation, and a bad parameter would surface only
when a real product was being evaluated. Registering the pair makes that
impossible to forget.

A `visual_check` reaches the source image through `CheckContext.image` and
declaration geometry through `ExtractedLabelField.bounding_box` — both already
exist, so readability and font-size analysis need no schema change.

## `check_type: field_presence`

Asks whether a declaration was found in the extracted label data. It makes no
judgement about whether the value is correct.

```json
"check_type": "field_presence",
"parameters": { "field_key": "net_quantity" }
```

`field_key` must be a member of `labelextract.contracts.LabelFieldKey`.

Three-way outcome, which matters more than it looks:

| Extraction state | Outcome |
|---|---|
| Field present | pass |
| Field absent, extraction succeeded and read text | fail |
| Field absent, extraction was `empty` or `failed` | **inconclusive** → `REVIEW_REQUIRED` |

A blurred photo must never be reported as a missing declaration. That is the
difference between "your package is illegal" and "we could not read your photo".

## Versioning rules over time

To amend a rule, add a new file with a new `code` and set `effective_from` on
the new one and `effective_to` on the old one. Do not edit a rule in place:
past `ComplianceCheck` rows point at the rule that was evaluated, and rewriting
it would silently change what those historical results meant.

The legal framework versions the same way and for the same reason, but keys on
`(clause, version)` rather than on a new `code`, and links the versions with
`supersedes`. See [`FRAMEWORK.md`](FRAMEWORK.md) — rule 6(10A), which two 2026
notifications amend in succession, is the worked example, including why its
transition is left deliberately unresolved.

## `requires_applicability_conditions`

Set `true` when a rule was unblocked **by** applicability rather than despite
it — i.e. it applies only to packages meeting a condition, or is excused by
one.

The failure this prevents: rule 6(1)(aa) binds imported packages only. With the
legal framework not loaded, the rule has no linked clause, so no trigger
condition is found and the rule applies to everything — failing every domestic
package for want of a country of origin it never had to declare. That is the
same shape of bug as `LM-PC-0002`, which reported a violation against every
product.

So the engine records **inconclusive** rather than evaluating such a rule while
it is unmapped, and says to run `load_legal_framework`. Three shipped rules set
it: `LM-PC-0004`, `LM-PC-0005` and `LM-PC-0007`.

## `check_type: field_presence_any_of`

Was **at least one** of several alternative declarations found? For a
disjunctive clause.

```json
"check_type": "field_presence_any_of",
"parameters": {
  "field_keys": ["manufacturer_name", "packer_name", "importer_name"]
}
```

At least two keys are required — one is not a disjunction, and expressing it
this way would hide a plain `field_presence` rule behind a failure message
about alternatives that do not exist. Duplicates and unknown keys are rejected
at load time.

Same three-way outcome as `field_presence`. The pass reports **which**
alternative satisfied the clause, which is what a reviewer checking a
disjunctive requirement against the source needs.

## `check_type: si_unit` and `check_type: prohibited_counting_unit`

Both take **no parameters** and are fixed to the `net_quantity` declaration,
because rule 13 concerns the net quantity specifically. A stray parameter is
rejected at load time.

Both read the **normalised** reading rather than re-parsing OCR text.
`labelextract` already decided what the unit was; re-deriving it here would
give two answers that can disagree.

`si_unit` (rule 13(5)) is **three-way, and the third branch is the important
one**:

| Declared unit | Outcome |
|---|---|
| An SI unit (`g`, `kg`, `ml`, `l`, …) | pass |
| A unit of number (`n`, `pcs`, …) — rule 13(5)(ii) | pass |
| A unit known not to be SI (`oz`, `lb`, `pint`, …) | **fail** |
| Anything else, or no normalised unit | **inconclusive** |

An unplaceable unit is not evidence of an unlawful declaration — `oz` misread
from a smudged `g` is indistinguishable from a genuine ounce, and reporting it
as a violation would turn an OCR defect into a legal finding.

`prohibited_counting_unit` (rule 13(4)) under-claims deliberately, twice: the
clause also bars units "or the like", which is open-ended and no list can
close; and it reaches anything "specified or indicated on any package", while
only the net-quantity declaration is scanned — matching the whole recognised
text would flag "Gross Weight", which is lawful.
