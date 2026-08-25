"""The rule loader.

Validation is strict on purpose: a rule that is not fully understood must be
rejected, not partially imported. These tests pin that behaviour, especially
the `source_status`/`source_note` pairing that keeps unverified legal claims
out of user-facing findings.
"""

import json

import pytest

from apps.rules.loader import (
    RuleFileError,
    discover_rule_files,
    load_rules,
    parse_rule_file,
)
from apps.rules.models import ComplianceRule

pytestmark = pytest.mark.django_db


VALID = {
    "code": "TEST-0001",
    "title": "A test rule",
    "requirement": "The package must declare something.",
    "source_status": "unverified",
    "check_type": "field_presence",
    "parameters": {"field_key": "net_quantity"},
}


def write_rule(directory, data, name=None):
    path = directory / (name or f"{data.get('code', 'rule')}.json")
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --- discovery --------------------------------------------------------------


def test_template_example_file_is_not_loaded(tmp_path):
    """`TEMPLATE.json.example` is documentation and must never become a rule."""
    (tmp_path / "TEMPLATE.json.example").write_text("{}", encoding="utf-8")
    write_rule(tmp_path, VALID)

    found = discover_rule_files(tmp_path)

    assert [p.name for p in found] == ["TEST-0001.json"]


def test_missing_directory_yields_no_files(tmp_path):
    assert discover_rule_files(tmp_path / "nope") == []


def test_the_shipped_definitions_directory_contains_no_rules(settings):
    """This repository ships zero rules, and that is deliberate.

    If this test fails, someone added a rule file. That is fine - but it must
    come with verified legal sourcing, so this test failing is a prompt to
    check that, not to delete the assertion.
    """
    assert discover_rule_files(settings.RULES_DEFINITIONS_DIR) == []


# --- structural validation --------------------------------------------------


def test_valid_file_parses(tmp_path):
    parsed = parse_rule_file(write_rule(tmp_path, VALID))
    assert parsed["code"] == "TEST-0001"
    assert parsed["is_active"] is True


def test_invalid_json_is_rejected(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RuleFileError, match="not valid JSON"):
        parse_rule_file(path)


@pytest.mark.parametrize("missing", ["code", "title", "requirement", "check_type"])
def test_missing_required_field_is_rejected(tmp_path, missing):
    data = {k: v for k, v in VALID.items() if k != missing}
    with pytest.raises(RuleFileError, match="missing required field"):
        parse_rule_file(write_rule(tmp_path, data, name="r.json"))


def test_unrecognised_field_is_rejected(tmp_path):
    """Usually a typo in a key that was meant to change behaviour."""
    with pytest.raises(RuleFileError, match="unrecognised field"):
        parse_rule_file(write_rule(tmp_path, {**VALID, "sevrity": "major"}))


def test_underscore_prefixed_keys_are_treated_as_comments(tmp_path):
    parsed = parse_rule_file(
        write_rule(tmp_path, {**VALID, "_comment": "explanatory text"})
    )
    assert "_comment" not in parsed


def test_unknown_check_type_is_rejected(tmp_path):
    """Caught at load time, not when a product is being evaluated."""
    with pytest.raises(RuleFileError, match="unknown check_type"):
        parse_rule_file(write_rule(tmp_path, {**VALID, "check_type": "made_up"}))


def test_unknown_field_key_is_rejected(tmp_path):
    with pytest.raises(RuleFileError, match="field_key"):
        parse_rule_file(
            write_rule(tmp_path, {**VALID, "parameters": {"field_key": "invented"}})
        )


def test_planned_check_type_gets_a_distinct_message(tmp_path):
    """"Planned but not built" must not read like a spelling mistake.

    Regression guard for the loader change that replaced a hardcoded
    `if check_type != "field_presence"` with delegation to each check's own
    parameter validator.
    """
    with pytest.raises(RuleFileError, match="planned but not implemented"):
        parse_rule_file(write_rule(tmp_path, {**VALID, "check_type": "visual_check"}))


def test_loader_uses_a_newly_registered_checks_own_parameter_validator(tmp_path):
    """A check type added later must get parameter validation automatically.

    This is the actual regression guard. Previously the loader hardcoded
    `if check_type != "field_presence": return`, so a new check type received
    no validation at all and a bad parameter surfaced only when a real product
    was evaluated. Registering a throwaway check here proves the loader now
    delegates rather than knowing check types itself.
    """
    from apps.rules import checks
    from apps.rules.checks.base import CheckOutcome, CheckStatus, InvalidCheckParameters

    def _validator(parameters, context):
        return CheckOutcome(status=CheckStatus.PASSED, message="stub")

    def _parameter_validator(parameters):
        if "threshold" not in parameters:
            raise InvalidCheckParameters("temp_check requires 'threshold'")

    checks.register_check(
        "temp_check_for_test",
        _validator,
        parameter_validator=_parameter_validator,
        description="Throwaway check registered by a test.",
    )
    try:
        rule = {**VALID, "check_type": "temp_check_for_test", "parameters": {}}
        with pytest.raises(RuleFileError, match="threshold"):
            parse_rule_file(write_rule(tmp_path, rule, name="temp.json"))

        # And the same check accepts a well-formed rule.
        rule["parameters"] = {"threshold": 5}
        assert parse_rule_file(
            write_rule(tmp_path, rule, name="temp.json")
        )["check_type"] == "temp_check_for_test"
    finally:
        # The registry is process-global; leaving it dirty would leak into
        # other tests and make ordering matter.
        checks._CHECKS.pop("temp_check_for_test", None)


def test_bad_date_is_rejected(tmp_path):
    with pytest.raises(RuleFileError, match="YYYY-MM-DD"):
        parse_rule_file(write_rule(tmp_path, {**VALID, "effective_from": "01-04-2011"}))


def test_reversed_effective_dates_are_rejected(tmp_path):
    with pytest.raises(RuleFileError, match="must not precede"):
        parse_rule_file(
            write_rule(
                tmp_path,
                {**VALID, "effective_from": "2020-01-01", "effective_to": "2019-01-01"},
            )
        )


# --- the verification guarantee ---------------------------------------------


def test_verified_rule_without_a_source_note_is_rejected(tmp_path):
    """Nobody can mark a rule verified without saying who verified it."""
    with pytest.raises(RuleFileError, match="source_note"):
        parse_rule_file(write_rule(tmp_path, {**VALID, "source_status": "verified"}))


def test_verified_rule_with_a_source_note_is_accepted(tmp_path):
    parsed = parse_rule_file(
        write_rule(
            tmp_path,
            {
                **VALID,
                "source_status": "verified",
                "source_note": "Checked against the Gazette text by A. Reviewer.",
            },
        )
    )
    assert parsed["source_status"] == "verified"


def test_invalid_source_status_is_rejected(tmp_path):
    with pytest.raises(RuleFileError, match="source_status"):
        parse_rule_file(write_rule(tmp_path, {**VALID, "source_status": "probably"}))


# --- loading ----------------------------------------------------------------


def test_load_creates_rules(tmp_path):
    write_rule(tmp_path, VALID)
    report = load_rules(tmp_path)

    assert report.ok
    assert report.created == ["TEST-0001"]
    assert ComplianceRule.objects.get(code="TEST-0001").title == "A test rule"


def test_load_is_idempotent(tmp_path):
    write_rule(tmp_path, VALID)
    load_rules(tmp_path)
    report = load_rules(tmp_path)

    assert report.updated == ["TEST-0001"]
    assert ComplianceRule.objects.count() == 1


def test_load_updates_an_existing_rule(tmp_path):
    write_rule(tmp_path, VALID)
    load_rules(tmp_path)
    write_rule(tmp_path, {**VALID, "title": "Amended title"})
    load_rules(tmp_path)

    assert ComplianceRule.objects.get(code="TEST-0001").title == "Amended title"


def test_dry_run_writes_nothing(tmp_path):
    write_rule(tmp_path, VALID)
    report = load_rules(tmp_path, dry_run=True)

    assert report.created == ["TEST-0001"]
    assert ComplianceRule.objects.count() == 0


def test_one_invalid_file_prevents_the_whole_load(tmp_path):
    """A partial rule set would silently change what products are checked against."""
    write_rule(tmp_path, VALID)
    write_rule(tmp_path, {**VALID, "code": "TEST-0002", "check_type": "nope"})

    report = load_rules(tmp_path)

    assert not report.ok
    assert ComplianceRule.objects.count() == 0


def test_duplicate_codes_across_files_are_rejected(tmp_path):
    write_rule(tmp_path, VALID, name="a.json")
    write_rule(tmp_path, VALID, name="b.json")

    report = load_rules(tmp_path)

    assert not report.ok
    assert any("duplicate" in e for e in report.errors)


def test_unknown_category_code_is_rejected(tmp_path):
    """Silently dropping it would widen the rule to every commodity."""
    write_rule(tmp_path, {**VALID, "applies_to_category_codes": ["no-such-category"]})

    with pytest.raises(RuleFileError, match="unknown product category"):
        load_rules(tmp_path)


def test_known_category_code_is_linked(tmp_path, category):
    write_rule(tmp_path, {**VALID, "applies_to_category_codes": [category.code]})
    load_rules(tmp_path)

    rule = ComplianceRule.objects.get(code="TEST-0001")
    assert list(rule.applies_to_categories.values_list("code", flat=True)) == [
        category.code
    ]


def test_empty_directory_loads_nothing_without_error(tmp_path):
    report = load_rules(tmp_path)
    assert report.ok
    assert report.total_seen == 0
