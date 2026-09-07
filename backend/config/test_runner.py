"""The test runner `manage.py test` uses.

Why this file exists
--------------------
This project's tests are pytest tests: module-level `test_*` functions using
fixtures from `conftest.py` and `pytest.mark.django_db`. There is not a single
`unittest.TestCase` subclass in the repository, and that is deliberate - the
fixtures in `conftest.py` (real PNG bytes, throwaway rule files, per-test
throttle budgets) are what make the suite readable.

Django's `manage.py test` runs `DiscoverRunner`, which is unittest-based and
collects **only** `TestCase` subclasses. Bare pytest functions are invisible to
it. So `manage.py test` discovered nothing, and - because unittest treats "no
tests" as success - reported:

    Ran 0 tests in 0.000s
    OK

That "OK" is the problem this class exists to remove. A green result from a run
that executed nothing is a false pass, and someone reasonably read it as "the
suite is fine". In a project whose compliance engine refuses to return
COMPLIANT without a rule having actually passed, a test runner that returns OK
without a test having actually run is the same bug in a different place.

What it does
------------
Fails loudly, and names the command that does work. It does not disable
anything: if someone later adds a genuine `TestCase`, discovery finds it and
the run proceeds as normal. Only the empty run is refused.

`pytest -q` from `backend/` remains the project's test command - it is what
`.github/workflows/ci.yml` runs, what `CONTRIBUTING.md` and `README.md`
document, and what `pytest.ini` configures.
"""

from django.core.management.base import CommandError
from django.test.runner import DiscoverRunner

_NO_TESTS_FOUND = """\
Django's test runner found no tests, and that is expected: this project's
tests are pytest tests, not unittest.TestCase subclasses, so `manage.py test`
cannot see them.

Run the suite with pytest instead:

    cd backend  && pytest -q         # the Django suite; needs PostgreSQL running
    cd ml       && pytest -q         # ML contracts; no database needed
    cd frontend && npm test          # frontend

This is what .github/workflows/ci.yml runs on every pull request, and what
CONTRIBUTING.md and README.md document. See backend/pytest.ini for the
configuration.

Refusing rather than reporting "OK": a run that executed zero tests is not a
passing suite, and reporting it as one has already misled someone once.\
"""


class PytestAwareDiscoverRunner(DiscoverRunner):
    """`DiscoverRunner` that refuses to report success on an empty run.

    Hooked in through `TEST_RUNNER` in `config/settings.py`. It affects
    `manage.py test` only - nothing about the application at runtime, and
    nothing about how pytest collects or runs.
    """

    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        if suite.countTestCases() == 0:
            raise CommandError(_NO_TESTS_FOUND)
        return suite
