# Rule file schema

One JSON object per file, in `rules/definitions/`, named `<code>.json`.
Validated by `backend/apps/rules/loader.py`; the loader rejects the whole file
on any error rather than importing a partially understood rule.

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
| `value_check` | Planned — compare a declaration against an expected value |
| `format_check` | Planned — validate shape (date format, units) |
| `numeric_check` | Planned — range and arithmetic checks |
| `conditional_check` | Planned — apply a check only when another condition holds |
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

The only validator in the base. Asks whether a declaration was found in the
extracted label data. It makes no judgement about whether the value is correct.

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
