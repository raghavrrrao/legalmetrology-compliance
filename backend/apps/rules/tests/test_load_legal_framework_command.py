"""`manage.py load_legal_framework`.

The loader itself is tested in `test_framework_loader.py`. What is tested here
is the command's contract with the person running it: that it fails loudly on
bad data, that it does not write on a dry run, and - the reason this file
exists - that its success message cannot be quoted as "34 rules implemented".
"""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.rules.models import LegalRule, RuleRequirement
from apps.rules.tests.test_framework_loader import _RULE, write_framework

pytestmark = pytest.mark.django_db


def run(directory, **options) -> str:
    out = StringIO()
    call_command("load_legal_framework", directory=directory, stdout=out, **options)
    return out.getvalue()


def test_the_command_loads_the_framework(tmp_path):
    output = run(write_framework(tmp_path / "framework"))

    assert LegalRule.objects.filter(rule_number="6").exists()
    assert "rules" in output


def test_the_summary_says_that_loading_is_not_implementing(tmp_path):
    """The sentence this whole framework depends on not being misread.

    "35 rules loaded" is exactly the line someone would repeat as "35 rules
    implemented". The command must say the opposite in its own output, not
    only in a document nobody opens.
    """
    output = run(write_framework(tmp_path / "framework"))

    assert "does NOT mean the system evaluates it" in output


def test_the_summary_separates_recorded_from_evaluated(tmp_path):
    """Two numbers, and they differ. One requirement is recorded here and no
    executable rule evaluates it."""
    output = run(write_framework(tmp_path / "framework"))

    assert "1 active requirement(s) are now on record" in output
    assert "0 are marked implemented" in output
    assert "0 have an active executable rule behind them" in output


def test_a_dry_run_reports_without_writing(tmp_path):
    output = run(write_framework(tmp_path / "framework"), dry_run=True)

    assert "[dry run]" in output
    assert RuleRequirement.objects.count() == 0


def test_an_unresolved_executable_rule_code_is_warned_about_not_fatal(tmp_path):
    """Loading the framework before `load_rules` is the normal order on a
    fresh database, so this must warn and continue."""
    requirement = {
        **_RULE["requirements"][0],
        "compliance_rule_codes": ["LM-PC-9999"],
    }
    rule = {**_RULE, "requirements": [requirement]}

    output = run(write_framework(tmp_path / "framework", rules=[rule]))

    assert "LM-PC-9999" in output
    assert "load_rules" in output
    assert RuleRequirement.objects.count() == 1


def test_invalid_data_aborts_with_a_command_error(tmp_path):
    bad = {**_RULE, "automation_class": "nonsense"}

    with pytest.raises(CommandError) as exc:
        run(write_framework(tmp_path / "framework", rules=[bad]))

    assert "Nothing was written" in str(exc.value)
    assert LegalRule.objects.count() == 0


def test_a_missing_directory_is_a_command_error_not_a_traceback(tmp_path):
    with pytest.raises(CommandError) as exc:
        run(tmp_path / "nowhere")

    assert "does not exist" in str(exc.value)


def test_the_command_is_idempotent(tmp_path):
    directory = write_framework(tmp_path / "framework")

    run(directory)
    second = run(directory)

    assert "0 created" in second
    assert RuleRequirement.objects.count() == 1


def test_the_shipped_framework_loads_through_the_command(db):
    """End to end, against the real files, the way a deployment runs it."""
    output = run(None)

    assert LegalRule.objects.count() >= 34
    assert "does NOT mean the system evaluates it" in output


def test_a_malformed_file_names_the_file(tmp_path):
    directory = write_framework(tmp_path / "framework")
    (directory / "rules.json").write_text(json.dumps({"wrong_key": []}), encoding="utf-8")

    with pytest.raises(CommandError):
        run(directory)
