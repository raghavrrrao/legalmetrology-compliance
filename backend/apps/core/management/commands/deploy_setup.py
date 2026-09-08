"""`manage.py deploy_setup` - bring a database to a servable state, in order.

    python backend/manage.py deploy_setup

What it is for
--------------
Four commands have to run, in one order, before this API can answer a
compliance request correctly:

    1. migrate                  create the tables
    2. seed_categories          the taxonomy rule files reference by code
    3. load_rules               the checks the engine can execute
    4. load_legal_framework     the clauses, citations and applicability gates

The order is not arbitrary and is pinned by
`apps/rules/tests/test_setup_sequence.py`: `load_rules` rejects a rule naming a
category with no row, so seeding has to come first, and both loaders need the
tables to exist.

Why a command rather than four lines in a deploy script
-------------------------------------------------------
Because of how the fourth one fails. Steps 1-3 fail loudly - a missing table or
an unknown category code stops with a `CommandError` naming the problem. Step 4
does not fail at all when it is skipped: the database is left with a full
complement of rules, healthy-looking counts, and no applicability conditions.
Every finding then cites no clause and no source, and - because a clause gated
on a fact nobody stated has no gate to check - the rule runs anyway and records
a violation. The same photograph answers REVIEW REQUIRED on a correctly loaded
database and PARTIALLY COMPLIANT, with a violation against clause 6(1)(a), on
one missing this step.

A deployment that runs a hand-written list of commands can lose the last one to
a typo, a truncated copy-paste, or a reasonable-looking edit, and nothing
downstream complains. This command exists so there is one thing to run and no
list to get wrong, and so that getting it wrong stops the deployment instead of
changing the verdicts.

Guarantees
----------
* **Ordered.** The sequence is in one place, in code, next to the test that
  pins it.
* **Fail-closed.** Any step's `CommandError` propagates, so the process exits
  non-zero. Railway's pre-deploy command treats that as a failed deployment and
  does not promote the container (docs.railway.com/guides/pre-deploy-command).
* **Verified afterwards.** Running the four commands is not the same as ending
  up in a servable state, so the state is checked rather than assumed. A
  database with zero applicability conditions fails here, loudly, rather than
  serving subtly different verdicts.
* **Idempotent.** Every underlying command is. Re-running creates no duplicate
  category, rule, instrument, requirement or condition, so this is safe on
  every deploy rather than only the first.

Deliberately NOT here: `--dry-run`. A dry run writes nothing, so using it as a
deployment's initialisation would report success over a database that was never
loaded - the exact failure this command exists to prevent.
"""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

#: (command name, extra argv, what a reader should understand it did).
#: The order is the contract. Changing it should break
#: `apps/core/tests/test_deploy_setup.py` before it breaks a deployment.
_SEQUENCE: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("migrate", ("--noinput",), "applied database migrations"),
    ("seed_categories", (), "seeded the commodity category taxonomy"),
    ("load_rules", (), "loaded the executable compliance rules"),
    ("load_legal_framework", (), "loaded the legal framework"),
)


class Command(BaseCommand):
    help = (
        "Run the full deployment initialisation - migrate, seed_categories, "
        "load_rules, load_legal_framework - in the required order, then verify "
        "the database is in a servable state. Idempotent; exits non-zero on "
        "any failure."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--quiet-steps",
            action="store_true",
            help=(
                "Capture each step's own output instead of streaming it. The "
                "summary and any failure are still printed."
            ),
        )

    def handle(self, *args, **options) -> None:
        quiet: bool = options["quiet_steps"]

        self.stdout.write("Running deployment setup.")

        for index, (name, extra, description) in enumerate(_SEQUENCE, start=1):
            self.stdout.write(
                self.style.MIGRATE_HEADING(
                    f"[{index}/{len(_SEQUENCE)}] manage.py {name}"
                )
            )
            step_out = StringIO() if quiet else self.stdout
            try:
                call_command(name, *extra, stdout=step_out, stderr=self.stderr)
            except CommandError as exc:
                # Re-raised, not swallowed. A CommandError exits non-zero, and
                # a non-zero pre-deploy command is what stops the platform from
                # promoting a container onto a half-initialised database.
                raise CommandError(
                    f"Deployment setup failed at step {index}/{len(_SEQUENCE)} "
                    f"({name}): {exc}"
                ) from exc
            self.stdout.write(self.style.SUCCESS(f"      {description}"))

        self._verify()

    # --- the state the four commands were supposed to produce ---------------

    def _verify(self) -> None:
        """Check the result, not just that each command returned.

        Every count below is something a compliance answer depends on. Zero in
        any of them is a database that will still serve requests and still
        return verdicts - wrong ones, or empty ones - which is why this refuses
        rather than warns.

        Imported inside the method so that a failure to import a model surfaces
        as an error from this command rather than at module load, when Django
        is still assembling the command registry.
        """
        from apps.catalog.models import ProductCategory
        from apps.rules.models import (
            ApplicabilityCondition,
            ComplianceRule,
            LegalInstrument,
            RuleRequirement,
        )

        counts = {
            "product categories": ProductCategory.objects.count(),
            "active compliance rules": ComplianceRule.objects.filter(
                is_active=True
            ).count(),
            "legal instruments": LegalInstrument.objects.count(),
            "rule requirements": RuleRequirement.objects.count(),
            "applicability conditions": ApplicabilityCondition.objects.count(),
        }

        empty = sorted(name for name, count in counts.items() if count == 0)
        if empty:
            raise CommandError(
                "Deployment setup ran every command but the database is not in "
                "a servable state - nothing was loaded for: "
                + ", ".join(empty)
                + ".\nThe API would start and answer requests with findings "
                "that cite no clause and no source, and applicability gates "
                "that cannot be evaluated. Refusing to report success."
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Deployment setup complete:\n"
                + "\n".join(
                    f"  {name:<26} {count:>4}" for name, count in counts.items()
                )
            )
        )
        # Said plainly, because the numbers above invite the opposite reading.
        # `load_legal_framework` records what the Rules require; only a subset
        # is evaluated. rules/INVENTORY.md says which, and why for the rest.
        self.stdout.write(
            "A loaded requirement is not an evaluated one - see "
            "rules/INVENTORY.md."
        )
