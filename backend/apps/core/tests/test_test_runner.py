"""`manage.py test` must not report success on a run that executed nothing.

Pinned here for the same reason `test_setup_sequence.py` pins the setup order:
it is a process invariant that nothing else enforces, and it has already gone
wrong once.

This project's tests are pytest functions. Django's `DiscoverRunner` is
unittest-based and collects only `TestCase` subclasses, so `manage.py test`
found nothing - and, because unittest treats an empty run as success, printed:

    Ran 0 tests in 0.000s
    OK

Someone reasonably read that as "the suite is fine". In a project whose
compliance engine refuses to return COMPLIANT unless a rule actually passed, a
test runner returning OK unless a test actually ran is the same bug in a
different place. `config.test_runner.PytestAwareDiscoverRunner` refuses it.

These tests assert the guard, not the suite. What actually runs the suite is
`pytest -q` from `backend/`, per `.github/workflows/ci.yml`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management.base import CommandError

from config.test_runner import PytestAwareDiscoverRunner

#: Repository root, reached the same way `apps/rules/tests/test_setup_sequence.py`
#: reaches it - this file sits at the same depth. Not taken from settings,
#: which expose `BACKEND_DIR`/`REPO_ROOT` but are the thing under test here.
REPOSITORY = Path(__file__).resolve().parents[4]


def test_settings_use_the_guarding_runner():
    """A plain DiscoverRunner here would restore the silent 'OK'."""
    assert settings.TEST_RUNNER == "config.test_runner.PytestAwareDiscoverRunner"


def test_an_empty_discovery_is_refused_rather_than_reported_as_ok(tmp_path):
    """The behaviour that was wrong: zero tests must not be a pass.

    Pointed at an empty directory, so discovery genuinely finds nothing -
    exactly the state `manage.py test` was in against this repository.
    """
    runner = PytestAwareDiscoverRunner(verbosity=0)

    with pytest.raises(CommandError) as exc:
        runner.build_suite([str(tmp_path)])

    message = str(exc.value)
    assert "pytest" in message, "the error must name the command that works"
    assert "zero tests" in message


def test_a_real_testcase_is_still_discovered_and_run(tmp_path):
    """The guard must not lock unittest out.

    If someone later adds a genuine `TestCase` - a migration test, say - it has
    to run. Only the *empty* result is refused, so this writes a real test
    module and checks discovery still returns it.
    """
    module = tmp_path / "test_discoverable.py"
    module.write_text(
        "import unittest\n"
        "\n"
        "class ExampleTests(unittest.TestCase):\n"
        "    def test_one(self):\n"
        "        self.assertTrue(True)\n",
        encoding="utf-8",
    )

    runner = PytestAwareDiscoverRunner(verbosity=0)
    suite = runner.build_suite([str(tmp_path)])

    assert suite.countTestCases() == 1


def test_the_suite_really_is_pytest_only():
    """The premise the guard rests on, asserted rather than assumed.

    If a `TestCase` is ever added, this fails and whoever added it decides
    deliberately whether the project now has two runners - rather than the
    guard's docstring quietly becoming untrue.
    """
    backend = REPOSITORY / "backend"
    offenders = [
        path.relative_to(backend).as_posix()
        for path in backend.glob("apps/**/test_*.py")
        if re.search(r"^\s*class\s+\w+\(.*TestCase.*\):", path.read_text(encoding="utf-8"), re.M)
    ]

    assert offenders == [], (
        f"these files define unittest TestCase subclasses: {offenders}. The "
        f"project is pytest-only; see config/test_runner.py."
    )


def test_ci_runs_pytest_and_not_manage_py_test():
    """The process half, read from the workflow rather than trusted.

    A green local pytest run says nothing about what CI executes. The command
    in the workflow is the one that gates a pull request, so it is the one this
    project's test claims rest on.
    """
    workflow = REPOSITORY / ".github" / "workflows" / "ci.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "pytest -q" in text
    assert "manage.py test" not in text, (
        "CI now invokes `manage.py test`, which cannot see this project's "
        "pytest tests. It would pass without running anything."
    )


def test_documentation_points_at_the_command_that_works():
    """CONTRIBUTING and README are where someone looks before running tests.

    They already said `pytest`; this keeps them from drifting to a command that
    silently runs nothing.
    """
    repository = REPOSITORY
    for name in ("CONTRIBUTING.md", "README.md"):
        text = (repository / name).read_text(encoding="utf-8")
        assert "pytest" in text, f"{name} does not say how to run the tests"
        assert "manage.py test" not in text, (
            f"{name} tells a reader to run `manage.py test`, which discovers "
            f"no tests in this project."
        )
