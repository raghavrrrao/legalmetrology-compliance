"""`manage.py deploy_setup` - the deployment's one initialisation command.

What is worth testing here is not that four commands can be called. It is the
three properties a deployment actually relies on:

1. the order, which `load_rules` depends on and which nothing else enforces at
   deploy time;
2. that a database left in an unservable state is reported as a failure rather
   than as success - specifically the `load_legal_framework` case, which is the
   one failure mode that is otherwise silent;
3. idempotence, because this runs on every deploy and not only the first.

The setup *sequence* itself, and the fact that CI runs it in that order, are
pinned separately in `apps/rules/tests/test_setup_sequence.py`. This file is
about the command that wraps it.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.catalog.models import ProductCategory
from apps.core.management.commands import deploy_setup
from apps.rules.models import (
    ApplicabilityCondition,
    ComplianceRule,
    LegalInstrument,
    RuleRequirement,
)

pytestmark = pytest.mark.django_db


def _run(**kwargs) -> str:
    out = StringIO()
    call_command("deploy_setup", stdout=out, stderr=StringIO(), **kwargs)
    return out.getvalue()


# --- the order --------------------------------------------------------------


def test_the_sequence_is_the_documented_one_in_the_documented_order():
    """Read off the command's own table, so a reordering fails here.

    `load_rules` rejects a rule naming a category with no row, so seeding has to
    precede it; both loaders need migrated tables. Asserting the literal list is
    blunt on purpose - this is a contract, and a test that merely checked "all
    four are present" would pass on the order that breaks a clean database.
    """
    assert [name for name, _, _ in deploy_setup._SEQUENCE] == [
        "migrate",
        "seed_categories",
        "load_rules",
        "load_legal_framework",
    ]


def test_no_step_uses_dry_run():
    """A dry run writes nothing, so it would report success over an empty
    database - the exact failure this command exists to prevent."""
    for name, extra, _ in deploy_setup._SEQUENCE:
        assert "--dry-run" not in extra, f"{name} would not write anything"


# --- what it produces on a clean database -----------------------------------


def test_a_clean_database_ends_up_servable():
    """The whole point: one command, and the database can answer correctly.

    Every assertion below is something a compliance answer depends on. The last
    one is the one that matters most - applicability conditions are what a
    clause gated on a stated fact is checked against, and a database without
    them returns different verdicts rather than obviously broken ones.
    """
    assert not ProductCategory.objects.exists()

    _run()

    assert ProductCategory.objects.exists()
    assert ComplianceRule.objects.filter(is_active=True).exists()
    assert LegalInstrument.objects.exists()
    assert RuleRequirement.objects.exists()
    assert ApplicabilityCondition.objects.exists()


def test_it_reports_the_counts_it_verified():
    """An operator reading deploy logs should see the numbers, not just 'ok'.

    A summary of what was loaded is how "the framework was never loaded" is
    noticed in a deploy log rather than during a demonstration.
    """
    output = _run()

    assert "applicability conditions" in output
    assert "active compliance rules" in output
    # And the caveat that stops the numbers being read as a capability claim.
    assert "INVENTORY.md" in output


# --- fail-closed ------------------------------------------------------------


def test_it_fails_when_the_framework_was_not_loaded(monkeypatch):
    """The silent failure, made loud.

    Simulates the one step whose omission changes verdicts instead of raising:
    the database gets its migrations, categories and rules, and nothing else.
    Without the verification in `_verify`, the command would print four ticks
    and exit zero over a database that answers PARTIALLY COMPLIANT where a
    correctly loaded one answers REVIEW REQUIRED.

    A `CommandError` is what makes this a deployment failure: it exits
    non-zero, and a non-zero pre-deploy command stops the platform from
    promoting the container.
    """
    monkeypatch.setattr(
        deploy_setup,
        "_SEQUENCE",
        tuple(
            step for step in deploy_setup._SEQUENCE
            if step[0] != "load_legal_framework"
        ),
    )

    with pytest.raises(CommandError, match="applicability conditions"):
        _run()


def test_the_failure_message_says_what_is_missing_and_why_it_matters():
    """A deploy log is read in a hurry. It has to name the consequence."""
    from apps.core.management.commands.deploy_setup import Command

    command = Command()
    command.stdout = StringIO()

    # Nothing has been loaded, so every count is zero.
    with pytest.raises(CommandError) as caught:
        command._verify()

    message = str(caught.value)
    assert "applicability conditions" in message
    assert "product categories" in message
    assert "Refusing to report success" in message


def test_a_failing_step_aborts_and_names_the_step(monkeypatch):
    """A step that fails must stop the run, not be logged and stepped over."""
    def explode(*args, **kwargs):
        raise CommandError("rule files are invalid")

    monkeypatch.setattr(deploy_setup, "call_command", explode)

    with pytest.raises(CommandError) as caught:
        _run()

    message = str(caught.value)
    assert "step 1/4" in message
    assert "migrate" in message
    assert "rule files are invalid" in message


# --- idempotence ------------------------------------------------------------


def test_running_it_twice_changes_nothing():
    """It runs on every deploy, so the second run must be a no-op.

    Counted across all five tables rather than only rules: a loader that
    duplicated instruments or conditions while leaving rules alone would still
    corrupt the framework, and would still pass a rules-only assertion.
    """
    _run()
    first = {
        "categories": ProductCategory.objects.count(),
        "rules": ComplianceRule.objects.count(),
        "instruments": LegalInstrument.objects.count(),
        "requirements": RuleRequirement.objects.count(),
        "conditions": ApplicabilityCondition.objects.count(),
    }

    _run()

    assert {
        "categories": ProductCategory.objects.count(),
        "rules": ComplianceRule.objects.count(),
        "instruments": LegalInstrument.objects.count(),
        "requirements": RuleRequirement.objects.count(),
        "conditions": ApplicabilityCondition.objects.count(),
    } == first


def test_quiet_steps_still_reports_the_summary():
    """The flag suppresses each step's chatter, never the verification."""
    output = _run(quiet_steps=True)

    assert "Deployment setup complete" in output
    assert "applicability conditions" in output
