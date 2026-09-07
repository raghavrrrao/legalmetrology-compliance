"""The framework loader's validation and upsert behaviour.

Built on throwaway framework files in `tmp_path`, so these test the loader
rather than the shipped data - `test_shipped_framework.py` does the latter.

The loader is strict on purpose: a partially understood legal record is worse
than none, because it reads as complete. Most of what follows checks that a bad
file is rejected loudly rather than imported in part.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from apps.rules.framework_loader import (
    CONDITIONS_FILE,
    INSTRUMENTS_FILE,
    RULES_FILE,
    FrameworkFileError,
    load_framework,
)
from apps.rules.models import (
    ApplicabilityCondition,
    LegalInstrument,
    LegalRule,
    RequirementApplicability,
    RuleRequirement,
)

pytestmark = pytest.mark.django_db


_INSTRUMENT = {
    "citation": "G.S.R. 202(E)",
    "instrument_type": "principal",
    "notified_on": "2011-03-07",
    "effective_from": "2011-04-01",
    "verification_status": "unverified",
}

_CONDITION = {
    "code": "imported-product",
    "name": "Imported product",
    "determination": "not_determinable",
}

_REQUIREMENT = {
    "clause": "6(1)(c)",
    "title": "Net quantity",
    "requirement": "The package must state the net quantity.",
    "detection_method": "ocr",
    "automation_class": "image_automatable",
    "implementation_status": "implementable_now",
    "verification_status": "unverified",
}

_RULE = {
    "rule_number": "6",
    "title": "Declarations to be made on every package",
    "automation_class": "partially_automatable",
    "verification_status": "unverified",
    "requirements": [_REQUIREMENT],
}


def write_framework(
    directory: Path,
    *,
    instruments=None,
    conditions=None,
    rules=None,
) -> Path:
    """Write a complete, valid-by-default framework into `directory`."""
    directory.mkdir(parents=True, exist_ok=True)
    payloads = {
        INSTRUMENTS_FILE: {
            "instruments": [_INSTRUMENT] if instruments is None else instruments
        },
        CONDITIONS_FILE: {
            "conditions": [_CONDITION] if conditions is None else conditions
        },
        RULES_FILE: {"rules": [_RULE] if rules is None else rules},
    }
    for name, payload in payloads.items():
        (directory / name).write_text(json.dumps(payload), encoding="utf-8")
    return directory


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_a_valid_framework_loads_every_layer(tmp_path):
    report = load_framework(write_framework(tmp_path / "framework"))

    assert report.ok, report.errors
    assert LegalInstrument.objects.count() == 1
    assert ApplicabilityCondition.objects.count() == 1
    assert LegalRule.objects.get(rule_number="6").sort_key == "006"
    assert RuleRequirement.objects.get(clause="6(1)(c)").rule.rule_number == "6"


def test_loading_twice_updates_rather_than_duplicates(tmp_path):
    """Idempotence. Re-running must be safe: it is how an amendment is applied."""
    directory = write_framework(tmp_path / "framework")

    first = load_framework(directory)
    second = load_framework(directory)

    assert len(first.requirements_created) == 1
    assert len(second.requirements_created) == 0
    assert len(second.requirements_updated) == 1
    assert RuleRequirement.objects.count() == 1


def test_a_dry_run_validates_without_writing(tmp_path):
    report = load_framework(write_framework(tmp_path / "framework"), dry_run=True)

    assert report.ok, report.errors
    assert len(report.requirements_created) == 1, "the dry run reported nothing"
    assert RuleRequirement.objects.count() == 0, "a dry run wrote to the database"


def test_underscore_prefixed_keys_are_documentation_not_data(tmp_path):
    """The `_comment` convention the executable rule files already use."""
    requirement = {**_REQUIREMENT, "_comment": "Why this clause is recorded."}
    rule = {**_RULE, "_note": "Free-form.", "requirements": [requirement]}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert report.ok, report.errors
    assert RuleRequirement.objects.filter(clause="6(1)(c)").exists()


def test_dates_and_defaults_are_parsed_onto_the_requirement(tmp_path):
    requirement = {
        **_REQUIREMENT,
        "effective_from": "2018-01-01",
        "effective_to": "2022-09-30",
        "is_active": False,
    }
    rule = {**_RULE, "requirements": [requirement]}

    load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    row = RuleRequirement.objects.get(clause="6(1)(c)")
    assert row.effective_from == date(2018, 1, 1)
    assert row.effective_to == date(2022, 9, 30)
    assert row.is_active is False
    # Defaulted, not authored.
    assert row.version == 1
    assert row.severity == "major"


# ---------------------------------------------------------------------------
# Versioning through the loader
# ---------------------------------------------------------------------------


def test_supersedes_version_resolves_within_the_file(tmp_path):
    """A second version links to the first without the file naming a database id."""
    version_one = {**_REQUIREMENT, "clause": "6(10A)", "version": 1}
    version_two = {
        **_REQUIREMENT,
        "clause": "6(10A)",
        "version": 2,
        "supersedes_version": 1,
        "effective_from": "2027-07-01",
    }
    # Deliberately out of order, to prove the loader sorts by version rather
    # than relying on the author to.
    rule = {**_RULE, "requirements": [version_two, version_one]}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert report.ok, report.errors
    second = RuleRequirement.objects.get(clause="6(10A)", version=2)
    assert second.supersedes == RuleRequirement.objects.get(
        clause="6(10A)", version=1
    )


def test_superseding_a_version_that_does_not_exist_is_rejected(tmp_path):
    orphan = {**_REQUIREMENT, "clause": "6(10A)", "version": 2, "supersedes_version": 1}
    rule = {**_RULE, "requirements": [orphan]}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert not report.ok
    assert "supersedes_version" in report.errors[0]
    assert RuleRequirement.objects.count() == 0, "a bad file was partially imported"


def test_superseding_a_later_version_is_rejected(tmp_path):
    """Version 1 cannot supersede version 2 - amendment history runs one way."""
    backwards = {**_REQUIREMENT, "version": 1, "supersedes_version": 3}
    rule = {**_RULE, "requirements": [backwards]}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert not report.ok
    assert "supersedes_version" in report.errors[0]


def test_the_same_clause_and_version_twice_in_one_file_is_rejected(tmp_path):
    duplicate = {**_REQUIREMENT}
    rule = {**_RULE, "requirements": [_REQUIREMENT, duplicate]}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert not report.ok
    assert "duplicate clause/version" in report.errors[0]


# ---------------------------------------------------------------------------
# Applicability through the loader
# ---------------------------------------------------------------------------


def test_applicability_links_are_created_with_their_mode(tmp_path):
    requirement = {
        **_REQUIREMENT,
        "applicability": [
            {
                "condition": "imported-product",
                "mode": "requires",
                "note": "Applies to imported products only.",
            }
        ],
    }
    rule = {**_RULE, "requirements": [requirement]}

    load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    link = RequirementApplicability.objects.get()
    assert link.condition.code == "imported-product"
    assert link.mode == RequirementApplicability.Mode.REQUIRES
    assert link.note.startswith("Applies to imported")


def test_an_unknown_condition_is_rejected_rather_than_dropped(tmp_path):
    """Silently dropping a link would widen the requirement, not narrow it."""
    requirement = {
        **_REQUIREMENT,
        "applicability": [{"condition": "no-such-condition", "mode": "requires"}],
    }
    rule = {**_RULE, "requirements": [requirement]}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert not report.ok
    assert "no-such-condition" in report.errors[0]
    assert RuleRequirement.objects.count() == 0


def test_removing_a_link_from_the_file_removes_it_from_the_database(tmp_path):
    """The links describe one clause; they are not accumulated history."""
    with_link = {
        **_REQUIREMENT,
        "applicability": [{"condition": "imported-product", "mode": "requires"}],
    }
    directory = write_framework(
        tmp_path / "framework", rules=[{**_RULE, "requirements": [with_link]}]
    )
    load_framework(directory)
    assert RequirementApplicability.objects.count() == 1

    write_framework(directory, rules=[_RULE])
    load_framework(directory)

    assert RequirementApplicability.objects.count() == 0


def test_an_unknown_instrument_citation_is_rejected(tmp_path):
    """Nulling it would make the clause read as always in force."""
    requirement = {**_REQUIREMENT, "source": "G.S.R. 000(E)"}
    rule = {**_RULE, "requirements": [requirement]}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert not report.ok
    assert "G.S.R. 000(E)" in report.errors[0]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    ["clause", "title", "requirement", "detection_method", "automation_class",
     "implementation_status", "verification_status"],
)
def test_a_requirement_missing_a_required_field_is_rejected(tmp_path, missing):
    requirement = {k: v for k, v in _REQUIREMENT.items() if k != missing}
    rule = {**_RULE, "requirements": [requirement]}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert not report.ok
    assert missing in report.errors[0]


def test_an_unrecognised_field_is_rejected_rather_than_ignored(tmp_path):
    """Usually a typo in a key that was meant to change behaviour."""
    requirement = {**_REQUIREMENT, "detecton_method": "ocr"}
    rule = {**_RULE, "requirements": [requirement]}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert not report.ok
    assert "detecton_method" in report.errors[0]


@pytest.mark.parametrize(
    "field,value",
    [
        ("detection_method", "telepathy"),
        ("automation_class", "fully_automatic"),
        ("implementation_status", "done"),
        ("verification_status", "probably_fine"),
        ("severity", "catastrophic"),
    ],
)
def test_a_value_outside_the_vocabulary_is_rejected(tmp_path, field, value):
    requirement = {**_REQUIREMENT, field: value}
    rule = {**_RULE, "requirements": [requirement]}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert not report.ok
    assert field in report.errors[0]


def test_a_verified_requirement_without_a_source_note_is_rejected(tmp_path):
    """The safeguard that keeps unreviewed legal claims out of the framework.

    Enforced in the loader as well as on the model, so a bad file never reaches
    the database at all.
    """
    requirement = {**_REQUIREMENT, "verification_status": "verified"}
    rule = {**_RULE, "requirements": [requirement]}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert not report.ok
    assert "source_note" in report.errors[0]


def test_a_verified_instrument_without_a_verification_note_is_rejected(tmp_path):
    instrument = {**_INSTRUMENT, "verification_status": "verified"}

    report = load_framework(
        write_framework(tmp_path / "framework", instruments=[instrument])
    )

    assert not report.ok
    assert "verification_note" in report.errors[0]


def test_a_malformed_date_is_rejected(tmp_path):
    requirement = {**_REQUIREMENT, "effective_from": "01-07-2026"}
    rule = {**_RULE, "requirements": [requirement]}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert not report.ok
    assert "effective_from" in report.errors[0]


def test_reversed_effective_dates_are_rejected(tmp_path):
    requirement = {
        **_REQUIREMENT,
        "effective_from": "2022-01-01",
        "effective_to": "2021-01-01",
    }
    rule = {**_RULE, "requirements": [requirement]}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert not report.ok
    assert "effective_to" in report.errors[0]


def test_a_rule_number_with_no_digits_is_rejected(tmp_path):
    rule = {**_RULE, "rule_number": "six"}

    report = load_framework(write_framework(tmp_path / "framework", rules=[rule]))

    assert not report.ok
    assert "digits" in report.errors[0]


def test_duplicate_rule_numbers_are_rejected(tmp_path):
    report = load_framework(write_framework(tmp_path / "framework", rules=[_RULE, _RULE]))

    assert not report.ok
    assert "duplicate rule_number" in report.errors[0]


def test_invalid_json_is_reported_with_the_filename(tmp_path):
    directory = write_framework(tmp_path / "framework")
    (directory / RULES_FILE).write_text("{not json", encoding="utf-8")

    report = load_framework(directory)

    assert not report.ok
    assert RULES_FILE in report.errors[0]


def test_a_missing_file_is_reported_rather_than_treated_as_empty(tmp_path):
    """An empty framework would read as "the Rules require nothing"."""
    directory = write_framework(tmp_path / "framework")
    (directory / CONDITIONS_FILE).unlink()

    report = load_framework(directory)

    assert not report.ok
    assert CONDITIONS_FILE in report.errors[0]


def test_nothing_is_written_when_any_file_is_invalid(tmp_path):
    """The transaction guarantee, asserted across layers.

    The instruments file is valid here and the rules file is not. If the load
    were not atomic, the instruments would land and the framework would be
    silently half-present.
    """
    bad_rule = {**_RULE, "automation_class": "nonsense"}

    report = load_framework(
        write_framework(tmp_path / "framework", rules=[bad_rule])
    )

    assert not report.ok
    assert LegalInstrument.objects.count() == 0
    assert ApplicabilityCondition.objects.count() == 0
    assert LegalRule.objects.count() == 0


# ---------------------------------------------------------------------------
# The link to the executable layer
# ---------------------------------------------------------------------------


def test_a_named_executable_rule_is_linked_to_its_requirement(tmp_path, make_rule):
    rule_row = make_rule("LM-PC-0003")
    requirement = {**_REQUIREMENT, "compliance_rule_codes": ["LM-PC-0003"]}

    report = load_framework(
        write_framework(tmp_path / "framework", rules=[{**_RULE, "requirements": [requirement]}])
    )

    assert report.ok, report.errors
    rule_row.refresh_from_db()
    assert rule_row.rule_requirement.clause == "6(1)(c)"


def test_an_executable_rule_that_is_not_loaded_is_reported_not_raised(tmp_path):
    """The framework can legitimately be loaded before `load_rules` runs.

    An unresolved code means "not loaded yet", not "wrong", so it must warn
    rather than abort - on a fresh database this is the normal order.
    """
    requirement = {**_REQUIREMENT, "compliance_rule_codes": ["LM-PC-9999"]}

    report = load_framework(
        write_framework(tmp_path / "framework", rules=[{**_RULE, "requirements": [requirement]}])
    )

    assert report.ok, report.errors
    assert report.unlinked_rule_codes == ["LM-PC-9999"]
    assert RuleRequirement.objects.filter(clause="6(1)(c)").exists()


def test_load_framework_raises_for_a_directory_that_is_not_there(tmp_path):
    report = load_framework(tmp_path / "nowhere")

    assert not report.ok
    assert INSTRUMENTS_FILE in report.errors[0]


def test_framework_file_error_is_the_public_exception_type():
    """Named so the management command can catch it and print, not traceback."""
    assert issubclass(FrameworkFileError, ValueError)
