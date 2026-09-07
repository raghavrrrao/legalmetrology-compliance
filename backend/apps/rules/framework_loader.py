"""Loads the legal framework from `rules/framework/` into the database.

The counterpart to `loader.py`. That module loads the *executable* rule set -
validators bound to categories, which the engine runs. This one loads the
*legal framework* - what the Legal Metrology (Packaged Commodities) Rules, 2011
require, clause by clause and version by version, whether or not this software
can evaluate any of it.

Three files, each a JSON object with one top-level list:

    instruments.json              the Gazette notifications and publications
    applicability_conditions.json the facts that decide whether a clause applies
    rules.json                    rules 1-34, each with its requirements

Loaded in that order, because a requirement names its instrument and its
conditions and a rule owns its requirements.

Validation is strict and fail-fast, for the same reason as in `loader.py`: a
partially understood legal record is worse than none, because it reads as
complete. Every error names the file, the entry and the field.

Idempotent. Re-running upserts on the natural keys - `citation`, `code`,
`rule_number`, and `(clause, version)` for a requirement. Nothing is ever
deleted: a superseded requirement stays on record with its effective window,
which is the whole point of versioning it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dataclass_field
from datetime import date
from pathlib import Path
from typing import Any

from django.db import transaction

from apps.rules.models import (
    ApplicabilityCondition,
    AutomationClass,
    ComplianceRule,
    DetectionMethod,
    ImplementationStatus,
    LegalInstrument,
    LegalRule,
    RequirementApplicability,
    RuleRequirement,
    VerificationStatus,
)

#: Keys beginning with this are documentation inside a file, not data. Same
#: convention as the executable rule files.
_COMMENT_PREFIX = "_"

INSTRUMENTS_FILE = "instruments.json"
CONDITIONS_FILE = "applicability_conditions.json"
RULES_FILE = "rules.json"

_INSTRUMENT_REQUIRED = {"citation", "instrument_type", "verification_status"}
_INSTRUMENT_ALLOWED = _INSTRUMENT_REQUIRED | {
    "title",
    "notified_on",
    "effective_from",
    "source_url",
    "source_sha256",
    "verification_note",
    "is_active",
}

_CONDITION_REQUIRED = {"code", "name", "determination"}
_CONDITION_ALLOWED = _CONDITION_REQUIRED | {
    "description",
    "determination_note",
    "is_active",
}

_RULE_REQUIRED = {"rule_number", "title", "automation_class", "verification_status"}
_RULE_ALLOWED = _RULE_REQUIRED | {
    "chapter",
    "description",
    "notes",
    "is_active",
    "requirements",
}

_REQUIREMENT_REQUIRED = {
    "clause",
    "title",
    "requirement",
    "detection_method",
    "automation_class",
    "implementation_status",
    "verification_status",
}
_REQUIREMENT_ALLOWED = _REQUIREMENT_REQUIRED | {
    "version",
    "supersedes_version",
    "verbatim_text",
    "severity",
    "source",
    "legal_reference",
    "source_note",
    "effective_from",
    "effective_to",
    "is_active",
    "applicability",
    "compliance_rule_codes",
}

_APPLICABILITY_REQUIRED = {"condition", "mode"}
_APPLICABILITY_ALLOWED = _APPLICABILITY_REQUIRED | {"note"}


class FrameworkFileError(ValueError):
    """A framework file is invalid. The message names the file and the field."""


@dataclass
class FrameworkLoadReport:
    """What a load run did. Returned so the command can print an honest summary."""

    instruments_created: list[str] = dataclass_field(default_factory=list)
    instruments_updated: list[str] = dataclass_field(default_factory=list)
    conditions_created: list[str] = dataclass_field(default_factory=list)
    conditions_updated: list[str] = dataclass_field(default_factory=list)
    rules_created: list[str] = dataclass_field(default_factory=list)
    rules_updated: list[str] = dataclass_field(default_factory=list)
    requirements_created: list[str] = dataclass_field(default_factory=list)
    requirements_updated: list[str] = dataclass_field(default_factory=list)
    #: Requirements naming a `compliance_rule_codes` entry that is not loaded.
    #: A warning, not an error: the framework can legitimately be loaded before
    #: the executable rules are.
    unlinked_rule_codes: list[str] = dataclass_field(default_factory=list)
    errors: list[str] = dataclass_field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def requirements_seen(self) -> int:
        return len(self.requirements_created) + len(self.requirements_updated)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _read_json_object(path: Path, list_key: str) -> list[dict[str, Any]]:
    """Read one framework file and return its top-level list of entries."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FrameworkFileError(f"{path.name}: file not found in {path.parent}") from None
    except json.JSONDecodeError as exc:
        raise FrameworkFileError(f"{path.name}: not valid JSON ({exc})") from None
    except OSError as exc:
        raise FrameworkFileError(f"{path.name}: could not be read ({exc})") from None

    if not isinstance(raw, dict):
        raise FrameworkFileError(f"{path.name}: top level must be a JSON object")
    entries = raw.get(list_key)
    if not isinstance(entries, list):
        raise FrameworkFileError(
            f"{path.name}: expected a top-level '{list_key}' list"
        )
    return [_strip_comments(entry, path.name, list_key) for entry in entries]


def _strip_comments(entry: Any, filename: str, list_key: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise FrameworkFileError(
            f"{filename}: every '{list_key}' entry must be a JSON object"
        )
    return {k: v for k, v in entry.items() if not k.startswith(_COMMENT_PREFIX)}


def _check_keys(
    filename: str, label: str, data: dict, required: set[str], allowed: set[str]
) -> None:
    missing = required - data.keys()
    if missing:
        raise FrameworkFileError(
            f"{filename}: {label}: missing required field(s): "
            f"{', '.join(sorted(missing))}"
        )
    unknown = data.keys() - allowed
    if unknown:
        # Rejected rather than ignored, as in loader.py: an unrecognised key is
        # usually a typo in one that was meant to change behaviour.
        raise FrameworkFileError(
            f"{filename}: {label}: unrecognised field(s): "
            f"{', '.join(sorted(unknown))}. See rules/SCHEMA.md."
        )


def _choice(
    filename: str, label: str, field_name: str, value: Any, choices
) -> str:
    valid = [c.value for c in choices]
    if value not in valid:
        raise FrameworkFileError(
            f"{filename}: {label}: '{field_name}' must be one of {valid}, "
            f"got {value!r}"
        )
    return value


def _text(filename: str, label: str, field_name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FrameworkFileError(
            f"{filename}: {label}: '{field_name}' must be a non-empty string"
        )
    return value.strip()


def _date(filename: str, label: str, field_name: str, value: Any) -> date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise FrameworkFileError(
            f"{filename}: {label}: '{field_name}' must be a YYYY-MM-DD string"
        )
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise FrameworkFileError(
            f"{filename}: {label}: '{field_name}' must be a YYYY-MM-DD date, "
            f"got {value!r}"
        ) from None


def _flag(filename: str, label: str, field_name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise FrameworkFileError(
            f"{filename}: {label}: '{field_name}' must be true or false"
        )
    return value


def _require_note_when_verified(
    filename: str, label: str, status: str, note: str, field_name: str
) -> None:
    """The rule that keeps unreviewed legal claims out of the framework.

    Enforced here as well as on the model, so a bad file never reaches the
    database at all - the same belt-and-braces `loader.py` applies to
    `source_note`.
    """
    if status == VerificationStatus.VERIFIED.value and not note.strip():
        raise FrameworkFileError(
            f"{filename}: {label}: '{field_name}' is required when "
            f"verification_status is 'verified': record who checked this "
            f"against which source"
        )


def parse_instruments(directory: Path) -> list[dict[str, Any]]:
    filename = INSTRUMENTS_FILE
    parsed = []
    for entry in _read_json_object(directory / filename, "instruments"):
        label = entry.get("citation", "<no citation>")
        _check_keys(filename, label, entry, _INSTRUMENT_REQUIRED, _INSTRUMENT_ALLOWED)
        note = (entry.get("verification_note") or "").strip()
        status = _choice(
            filename,
            label,
            "verification_status",
            entry["verification_status"],
            VerificationStatus,
        )
        _require_note_when_verified(
            filename, label, status, note, "verification_note"
        )
        parsed.append(
            {
                "citation": _text(filename, label, "citation", entry["citation"]),
                "title": (entry.get("title") or "").strip(),
                "instrument_type": _choice(
                    filename,
                    label,
                    "instrument_type",
                    entry["instrument_type"],
                    LegalInstrument.InstrumentType,
                ),
                "notified_on": _date(
                    filename, label, "notified_on", entry.get("notified_on")
                ),
                "effective_from": _date(
                    filename, label, "effective_from", entry.get("effective_from")
                ),
                "source_url": (entry.get("source_url") or "").strip(),
                "source_sha256": (entry.get("source_sha256") or "").strip(),
                "verification_status": status,
                "verification_note": note,
                "is_active": _flag(
                    filename, label, "is_active", entry.get("is_active", True)
                ),
            }
        )
    return parsed


def parse_conditions(directory: Path) -> list[dict[str, Any]]:
    filename = CONDITIONS_FILE
    parsed = []
    for entry in _read_json_object(directory / filename, "conditions"):
        label = entry.get("code", "<no code>")
        _check_keys(filename, label, entry, _CONDITION_REQUIRED, _CONDITION_ALLOWED)
        parsed.append(
            {
                "code": _text(filename, label, "code", entry["code"]),
                "name": _text(filename, label, "name", entry["name"]),
                "description": (entry.get("description") or "").strip(),
                "determination": _choice(
                    filename,
                    label,
                    "determination",
                    entry["determination"],
                    ApplicabilityCondition.Determination,
                ),
                "determination_note": (entry.get("determination_note") or "").strip(),
                "is_active": _flag(
                    filename, label, "is_active", entry.get("is_active", True)
                ),
            }
        )
    return parsed


def parse_rules(directory: Path) -> list[dict[str, Any]]:
    filename = RULES_FILE
    parsed = []
    for entry in _read_json_object(directory / filename, "rules"):
        label = f"rule {entry.get('rule_number', '<no rule_number>')}"
        _check_keys(filename, label, entry, _RULE_REQUIRED, _RULE_ALLOWED)

        rule_number = _text(filename, label, "rule_number", entry["rule_number"])
        try:
            sort_key = LegalRule.build_sort_key(rule_number)
        except ValueError as exc:
            raise FrameworkFileError(f"{filename}: {label}: {exc}") from None

        raw_requirements = entry.get("requirements", []) or []
        if not isinstance(raw_requirements, list):
            raise FrameworkFileError(
                f"{filename}: {label}: 'requirements' must be a list"
            )

        parsed.append(
            {
                "rule_number": rule_number,
                "sort_key": sort_key,
                "title": _text(filename, label, "title", entry["title"]),
                "chapter": (entry.get("chapter") or "").strip(),
                "description": (entry.get("description") or "").strip(),
                "automation_class": _choice(
                    filename,
                    label,
                    "automation_class",
                    entry["automation_class"],
                    AutomationClass,
                ),
                "verification_status": _choice(
                    filename,
                    label,
                    "verification_status",
                    entry["verification_status"],
                    VerificationStatus,
                ),
                "notes": (entry.get("notes") or "").strip(),
                "is_active": _flag(
                    filename, label, "is_active", entry.get("is_active", True)
                ),
                "requirements": [
                    _parse_requirement(filename, rule_number, item)
                    for item in raw_requirements
                ],
            }
        )
    return parsed


def _parse_requirement(
    filename: str, rule_number: str, entry: Any
) -> dict[str, Any]:
    entry = _strip_comments(entry, filename, "requirements")
    label = f"rule {rule_number} clause {entry.get('clause', '<no clause>')}"
    _check_keys(filename, label, entry, _REQUIREMENT_REQUIRED, _REQUIREMENT_ALLOWED)

    version = entry.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise FrameworkFileError(
            f"{filename}: {label}: 'version' must be an integer of 1 or more"
        )
    supersedes_version = entry.get("supersedes_version")
    if supersedes_version is not None:
        if not isinstance(supersedes_version, int) or supersedes_version >= version:
            raise FrameworkFileError(
                f"{filename}: {label}: 'supersedes_version' must be an integer "
                f"lower than 'version' ({version})"
            )

    status = _choice(
        filename,
        label,
        "verification_status",
        entry["verification_status"],
        VerificationStatus,
    )
    source_note = (entry.get("source_note") or "").strip()
    _require_note_when_verified(filename, label, status, source_note, "source_note")

    effective_from = _date(
        filename, label, "effective_from", entry.get("effective_from")
    )
    effective_to = _date(filename, label, "effective_to", entry.get("effective_to"))
    if effective_from and effective_to and effective_to < effective_from:
        raise FrameworkFileError(
            f"{filename}: {label}: 'effective_to' must not precede 'effective_from'"
        )

    raw_applicability = entry.get("applicability", []) or []
    if not isinstance(raw_applicability, list):
        raise FrameworkFileError(
            f"{filename}: {label}: 'applicability' must be a list"
        )
    applicability = []
    for item in raw_applicability:
        item = _strip_comments(item, filename, "applicability")
        _check_keys(
            filename, label, item, _APPLICABILITY_REQUIRED, _APPLICABILITY_ALLOWED
        )
        applicability.append(
            {
                "condition": _text(filename, label, "condition", item["condition"]),
                "mode": _choice(
                    filename,
                    label,
                    "mode",
                    item["mode"],
                    RequirementApplicability.Mode,
                ),
                "note": (item.get("note") or "").strip(),
            }
        )

    compliance_rule_codes = entry.get("compliance_rule_codes", []) or []
    if not isinstance(compliance_rule_codes, list) or not all(
        isinstance(code, str) for code in compliance_rule_codes
    ):
        raise FrameworkFileError(
            f"{filename}: {label}: 'compliance_rule_codes' must be a list of strings"
        )

    return {
        "clause": _text(filename, label, "clause", entry["clause"]),
        "version": version,
        "supersedes_version": supersedes_version,
        "title": _text(filename, label, "title", entry["title"]),
        "requirement": _text(filename, label, "requirement", entry["requirement"]),
        "verbatim_text": (entry.get("verbatim_text") or "").strip(),
        "detection_method": _choice(
            filename,
            label,
            "detection_method",
            entry["detection_method"],
            DetectionMethod,
        ),
        "automation_class": _choice(
            filename,
            label,
            "automation_class",
            entry["automation_class"],
            AutomationClass,
        ),
        "implementation_status": _choice(
            filename,
            label,
            "implementation_status",
            entry["implementation_status"],
            ImplementationStatus,
        ),
        "severity": _choice(
            filename,
            label,
            "severity",
            entry.get("severity", ComplianceRule.Severity.MAJOR.value),
            ComplianceRule.Severity,
        ),
        "source": (entry.get("source") or "").strip(),
        "legal_reference": (entry.get("legal_reference") or "").strip(),
        "verification_status": status,
        "source_note": source_note,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "is_active": _flag(filename, label, "is_active", entry.get("is_active", True)),
        "applicability": applicability,
        "compliance_rule_codes": compliance_rule_codes,
    }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@transaction.atomic
def load_framework(directory: Path, *, dry_run: bool = False) -> FrameworkLoadReport:
    """Load the whole framework from `directory`.

    Runs in a transaction: if anything is invalid, nothing is written. A
    half-loaded framework would under-report which obligations exist, which is
    the specific failure this project is built to avoid.
    """
    report = FrameworkLoadReport()

    try:
        instruments = parse_instruments(directory)
        conditions = parse_conditions(directory)
        rules = parse_rules(directory)
    except FrameworkFileError as exc:
        report.errors.append(str(exc))
        transaction.set_rollback(True)
        return report

    duplicate = _first_duplicate(item["citation"] for item in instruments)
    if duplicate:
        report.errors.append(f"{INSTRUMENTS_FILE}: duplicate citation: {duplicate}")
    duplicate = _first_duplicate(item["code"] for item in conditions)
    if duplicate:
        report.errors.append(f"{CONDITIONS_FILE}: duplicate condition code: {duplicate}")
    duplicate = _first_duplicate(item["rule_number"] for item in rules)
    if duplicate:
        report.errors.append(f"{RULES_FILE}: duplicate rule_number: {duplicate}")
    duplicate = _first_duplicate(
        f"{requirement['clause']} v{requirement['version']}"
        for rule in rules
        for requirement in rule["requirements"]
    )
    if duplicate:
        report.errors.append(
            f"{RULES_FILE}: duplicate clause/version across the file: {duplicate}"
        )

    if report.errors:
        transaction.set_rollback(True)
        return report

    instrument_rows = _apply_instruments(instruments, report)
    condition_rows = _apply_conditions(conditions, report)

    try:
        _apply_rules(rules, instrument_rows, condition_rows, report)
    except FrameworkFileError as exc:
        report.errors.append(str(exc))
        transaction.set_rollback(True)
        return report

    if dry_run:
        transaction.set_rollback(True)

    return report


def _first_duplicate(values) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


def _apply_instruments(
    items: list[dict[str, Any]], report: FrameworkLoadReport
) -> dict[str, LegalInstrument]:
    rows: dict[str, LegalInstrument] = {}
    for item in items:
        citation = item["citation"]
        row, created = LegalInstrument.objects.update_or_create(
            citation=citation, defaults={k: v for k, v in item.items() if k != "citation"}
        )
        row.full_clean()
        rows[citation] = row
        (report.instruments_created if created else report.instruments_updated).append(
            citation
        )
    return rows


def _apply_conditions(
    items: list[dict[str, Any]], report: FrameworkLoadReport
) -> dict[str, ApplicabilityCondition]:
    rows: dict[str, ApplicabilityCondition] = {}
    for item in items:
        code = item["code"]
        row, created = ApplicabilityCondition.objects.update_or_create(
            code=code, defaults={k: v for k, v in item.items() if k != "code"}
        )
        row.full_clean()
        rows[code] = row
        (report.conditions_created if created else report.conditions_updated).append(
            code
        )
    return rows


def _apply_rules(
    items: list[dict[str, Any]],
    instruments: dict[str, LegalInstrument],
    conditions: dict[str, ApplicabilityCondition],
    report: FrameworkLoadReport,
) -> None:
    #: Requirements already written this run, keyed (clause, version), so a
    #: `supersedes_version` can be resolved without re-querying. Versions are
    #: written in ascending order below, which is what makes that safe.
    written: dict[tuple[str, int], RuleRequirement] = {}

    for item in items:
        rule_number = item["rule_number"]
        requirements = item["requirements"]
        rule, created = LegalRule.objects.update_or_create(
            rule_number=rule_number,
            defaults={
                k: v
                for k, v in item.items()
                if k not in {"rule_number", "requirements"}
            },
        )
        rule.full_clean()
        (report.rules_created if created else report.rules_updated).append(rule_number)

        # Ascending version order, so version 2's `supersedes` target exists.
        for requirement in sorted(requirements, key=lambda r: r["version"]):
            _apply_requirement(
                rule, requirement, instruments, conditions, written, report
            )


def _apply_requirement(
    rule: LegalRule,
    item: dict[str, Any],
    instruments: dict[str, LegalInstrument],
    conditions: dict[str, ApplicabilityCondition],
    written: dict[tuple[str, int], RuleRequirement],
    report: FrameworkLoadReport,
) -> None:
    clause = item["clause"]
    version = item["version"]
    label = f"rule {rule.rule_number} clause {clause} v{version}"

    source = None
    if item["source"]:
        source = instruments.get(item["source"])
        if source is None:
            # Rejected rather than nulled: silently dropping the instrument
            # would leave a requirement whose amendment history reads as
            # "always in force", which is a stronger claim than the file makes.
            raise FrameworkFileError(
                f"{RULES_FILE}: {label}: unknown instrument citation "
                f"{item['source']!r}. Add it to {INSTRUMENTS_FILE} first."
            )

    supersedes = None
    if item["supersedes_version"] is not None:
        supersedes = written.get((clause, item["supersedes_version"]))
        if supersedes is None:
            raise FrameworkFileError(
                f"{RULES_FILE}: {label}: 'supersedes_version' "
                f"{item['supersedes_version']} names a version of {clause} that "
                f"is not defined in this file."
            )

    defaults = {
        k: v
        for k, v in item.items()
        if k
        not in {
            "clause",
            "version",
            "supersedes_version",
            "source",
            "applicability",
            "compliance_rule_codes",
        }
    }
    defaults["rule"] = rule
    defaults["source"] = source
    defaults["supersedes"] = supersedes

    requirement, created = RuleRequirement.objects.update_or_create(
        clause=clause, version=version, defaults=defaults
    )
    requirement.full_clean(exclude=["applicability_conditions"])
    written[(clause, version)] = requirement
    (
        report.requirements_created if created else report.requirements_updated
    ).append(f"{clause} v{version}")

    _apply_applicability(requirement, item["applicability"], conditions, label)
    _link_compliance_rules(requirement, item["compliance_rule_codes"], report)


def _apply_applicability(
    requirement: RuleRequirement,
    items: list[dict[str, Any]],
    conditions: dict[str, ApplicabilityCondition],
    label: str,
) -> None:
    """Replace this requirement's applicability links with the file's.

    Replaced rather than merged so removing a link from the file actually
    removes it. The links are a description of one clause, not accumulated
    history - the history lives in the versioned requirement rows.
    """
    wanted = []
    for item in items:
        condition = conditions.get(item["condition"])
        if condition is None:
            raise FrameworkFileError(
                f"{RULES_FILE}: {label}: unknown applicability condition "
                f"{item['condition']!r}. Add it to {CONDITIONS_FILE} first."
            )
        wanted.append((condition, item["mode"], item["note"]))

    requirement.applicability_links.exclude(
        condition__in=[condition for condition, _, _ in wanted]
    ).delete()
    for condition, mode, note in wanted:
        RequirementApplicability.objects.update_or_create(
            requirement=requirement,
            condition=condition,
            mode=mode,
            defaults={"note": note},
        )


def _link_compliance_rules(
    requirement: RuleRequirement,
    codes: list[str],
    report: FrameworkLoadReport,
) -> None:
    """Point the named executable rules at this requirement.

    A code that is not loaded is reported, not raised. The framework can
    legitimately be loaded before `load_rules` runs - and on a fresh database it
    usually is - so an unresolved code means "not loaded yet", not "wrong".
    """
    for code in codes:
        updated = ComplianceRule.objects.filter(code=code).update(
            rule_requirement=requirement
        )
        if not updated:
            report.unlinked_rule_codes.append(code)
