"""Loads rule definition files from `rules/definitions/` into the database.

Validation is strict and fail-fast by design. A rule file that is not fully
understood is rejected rather than partially imported: a half-loaded rule would
evaluate products against a requirement nobody reviewed.

Every error names the file and the field, because the people editing these
files are not necessarily the people who wrote this loader.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dataclass_field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from django.db import transaction

from apps.catalog.models import ProductCategory
from apps.rules import checks
from apps.rules.checks.base import InvalidCheckParameters
from apps.rules.models import ComplianceRule

#: Keys beginning with this are documentation inside a rule file, not data.
_COMMENT_PREFIX = "_"

_REQUIRED_KEYS = {"code", "title", "requirement", "source_status", "check_type"}

_ALLOWED_KEYS = _REQUIRED_KEYS | {
    "legal_reference",
    "source_note",
    "severity",
    "parameters",
    "applies_to_category_codes",
    "effective_from",
    "effective_to",
    "is_active",
}


class RuleFileError(ValueError):
    """A rule definition file is invalid. Message names the file and field."""


@dataclass
class LoadReport:
    """What a load run did. Returned so the command can print an honest summary."""

    created: list[str] = dataclass_field(default_factory=list)
    updated: list[str] = dataclass_field(default_factory=list)
    unchanged: list[str] = dataclass_field(default_factory=list)
    errors: list[str] = dataclass_field(default_factory=list)

    @property
    def total_seen(self) -> int:
        return len(self.created) + len(self.updated) + len(self.unchanged)

    @property
    def ok(self) -> bool:
        return not self.errors


def discover_rule_files(directory: Path) -> list[Path]:
    """Return the rule files in `directory`, sorted.

    Matches `*.json` only, which is why `TEMPLATE.json.example` is skipped -
    the template is documentation and must never be loaded as a rule.
    """
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def parse_rule_file(path: Path) -> dict[str, Any]:
    """Read and validate one rule file into a normalised dict.

    Raises:
        RuleFileError: the file is unreadable, malformed, or invalid.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuleFileError(f"{path.name}: not valid JSON ({exc})") from None
    except OSError as exc:
        raise RuleFileError(f"{path.name}: could not be read ({exc})") from None

    if not isinstance(raw, dict):
        raise RuleFileError(f"{path.name}: top level must be a JSON object")

    data = {k: v for k, v in raw.items() if not k.startswith(_COMMENT_PREFIX)}

    missing = _REQUIRED_KEYS - data.keys()
    if missing:
        raise RuleFileError(
            f"{path.name}: missing required field(s): {', '.join(sorted(missing))}"
        )

    unknown = data.keys() - _ALLOWED_KEYS
    if unknown:
        # Rejected rather than ignored: an unrecognised key is usually a typo
        # in a key that was meant to change behaviour.
        raise RuleFileError(
            f"{path.name}: unrecognised field(s): {', '.join(sorted(unknown))}. "
            f"See rules/SCHEMA.md."
        )

    return _validate(path.name, data)


def _validate(filename: str, data: dict[str, Any]) -> dict[str, Any]:
    def fail(message: str) -> None:
        raise RuleFileError(f"{filename}: {message}")

    for key in ("code", "title", "requirement"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            fail(f"'{key}' must be a non-empty string")

    source_status = data.get("source_status")
    valid_statuses = [c.value for c in ComplianceRule.SourceStatus]
    if source_status not in valid_statuses:
        fail(f"'source_status' must be one of {valid_statuses}")

    source_note = data.get("source_note", "") or ""
    if (
        source_status == ComplianceRule.SourceStatus.VERIFIED.value
        and not source_note.strip()
    ):
        # The rule that keeps unreviewed legal claims out of user-facing
        # findings. Enforced here as well as on the model so a bad file never
        # reaches the database.
        fail(
            "'source_note' is required when source_status is 'verified': record "
            "who checked this rule against which source"
        )

    severity = data.get("severity", ComplianceRule.Severity.MAJOR.value)
    valid_severities = [c.value for c in ComplianceRule.Severity]
    if severity not in valid_severities:
        fail(f"'severity' must be one of {valid_severities}")

    check_type = data.get("check_type")
    if not checks.is_registered(check_type):
        if check_type in checks.PLANNED_CHECK_TYPES:
            # Distinguishing "planned" from "typo" saves a rule author from
            # hunting for a spelling mistake that is not there.
            fail(
                f"check_type {check_type!r} is planned but not implemented yet "
                f"({checks.PLANNED_CHECK_TYPES[check_type]}). Implement it in "
                f"apps/rules/checks/ first - see rules/SCHEMA.md. Currently "
                f"available: {sorted(checks.available_check_types())}"
            )
        fail(
            f"unknown check_type {check_type!r}. Available: "
            f"{sorted(checks.available_check_types())}"
        )

    parameters = data.get("parameters", {}) or {}
    if not isinstance(parameters, dict):
        fail("'parameters' must be a JSON object")
    _validate_parameters(filename, check_type, parameters)

    categories = data.get("applies_to_category_codes", []) or []
    if not isinstance(categories, list) or not all(
        isinstance(c, str) for c in categories
    ):
        fail("'applies_to_category_codes' must be a list of strings")

    effective_from = _parse_date(filename, data.get("effective_from"), "effective_from")
    effective_to = _parse_date(filename, data.get("effective_to"), "effective_to")
    if effective_from and effective_to and effective_to < effective_from:
        fail("'effective_to' must not precede 'effective_from'")

    is_active = data.get("is_active", True)
    if not isinstance(is_active, bool):
        fail("'is_active' must be true or false")

    return {
        "code": data["code"].strip(),
        "title": data["title"].strip(),
        "requirement": data["requirement"].strip(),
        "legal_reference": (data.get("legal_reference") or "").strip(),
        "source_status": source_status,
        "source_note": source_note.strip(),
        "severity": severity,
        "check_type": check_type,
        "parameters": parameters,
        "applies_to_category_codes": categories,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "is_active": is_active,
    }


def _validate_parameters(filename: str, check_type: str, parameters: dict) -> None:
    """Validate parameters using the validator registered for `check_type`.

    Delegates rather than branching on the check type. The previous version
    hardcoded `if check_type != "field_presence": return`, which meant every
    check type added later would silently receive no parameter validation and a
    typo would surface only when a real product was evaluated. Each check now
    registers its own parameter validator, so this cannot be forgotten.
    """
    try:
        checks.validate_parameters(check_type, parameters)
    except InvalidCheckParameters as exc:
        raise RuleFileError(f"{filename}: {exc}") from None


def _parse_date(filename: str, value: Any, field_name: str) -> date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise RuleFileError(f"{filename}: '{field_name}' must be a YYYY-MM-DD string")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise RuleFileError(
            f"{filename}: '{field_name}' must be a YYYY-MM-DD date, got {value!r}"
        ) from None


@transaction.atomic
def load_rules(directory: Path, *, dry_run: bool = False) -> LoadReport:
    """Load every rule file in `directory` into the database.

    Upserts on `code`, so re-running is safe and idempotent. Rules already in
    the database but absent from `directory` are left alone - deleting them
    would break the compliance results that reference them. Retire a rule by
    setting `is_active: false`, not by deleting its file.

    Runs in a transaction: if any file is invalid, nothing is written. A
    partial rule set would silently change what products are evaluated against.
    """
    report = LoadReport()

    paths = discover_rule_files(directory)
    parsed: list[dict[str, Any]] = []
    for path in paths:
        try:
            parsed.append(parse_rule_file(path))
        except RuleFileError as exc:
            report.errors.append(str(exc))

    codes = [item["code"] for item in parsed]
    duplicates = {code for code in codes if codes.count(code) > 1}
    if duplicates:
        report.errors.append(
            f"duplicate rule code(s) across files: {', '.join(sorted(duplicates))}"
        )

    if report.errors:
        transaction.set_rollback(True)
        return report

    for item in parsed:
        _apply(item, report)

    if dry_run:
        transaction.set_rollback(True)

    return report


def _apply(item: dict[str, Any], report: LoadReport) -> None:
    category_codes = item.pop("applies_to_category_codes")
    code = item["code"]

    rule, created = ComplianceRule.objects.update_or_create(
        code=code, defaults=item
    )
    rule.full_clean(exclude=["applies_to_categories"])

    categories = _resolve_categories(code, category_codes)
    rule.applies_to_categories.set(categories)

    if created:
        report.created.append(code)
    else:
        report.updated.append(code)


def _resolve_categories(code: str, category_codes: Iterable[str]):
    codes = list(category_codes)
    if not codes:
        return []
    found = list(ProductCategory.objects.filter(code__in=codes))
    missing = set(codes) - {c.code for c in found}
    if missing:
        # Rejected rather than skipped: silently dropping an unknown category
        # would widen the rule to every commodity, which is the opposite of
        # what the author asked for.
        raise RuleFileError(
            f"{code}: unknown product category code(s): "
            f"{', '.join(sorted(missing))}"
        )
    return found
