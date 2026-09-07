"""`manage.py load_legal_framework` - import the legal framework from JSON.

The counterpart to `load_rules`. That command loads the executable rules the
engine runs; this one loads the record of what the Legal Metrology (Packaged
Commodities) Rules, 2011 require, including the many requirements this software
cannot evaluate.

Loading a requirement here does **not** make it evaluated. The summary this
command prints says so explicitly, because "34 rules loaded" is exactly the
sentence someone would otherwise repeat as "34 rules implemented".
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.rules.framework_loader import FrameworkFileError, load_framework
from apps.rules.models import ImplementationStatus, RuleRequirement


class Command(BaseCommand):
    help = (
        "Load the Legal Metrology (Packaged Commodities) Rules, 2011 framework "
        "- instruments, applicability conditions, rules and versioned "
        "requirements - from JSON. Idempotent."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--directory",
            type=Path,
            default=None,
            help=(
                "Directory to read framework files from. Defaults to "
                "RULES_FRAMEWORK_DIR (rules/framework/)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report what would change, without writing.",
        )

    def handle(self, *args, **options) -> None:
        directory: Path = options["directory"] or settings.RULES_FRAMEWORK_DIR
        dry_run: bool = options["dry_run"]

        if not directory.is_dir():
            raise CommandError(f"Framework directory does not exist: {directory}")

        try:
            report = load_framework(directory, dry_run=dry_run)
        except FrameworkFileError as exc:
            raise CommandError(str(exc)) from None

        if report.errors:
            self.stderr.write(self.style.ERROR("The legal framework is invalid:"))
            for error in report.errors:
                self.stderr.write(f"  - {error}")
            raise CommandError(
                f"{len(report.errors)} error(s). Nothing was written."
            )

        lead = "[dry run] Would have loaded" if dry_run else "Loaded"
        self.stdout.write(
            self.style.SUCCESS(
                f"{lead} from {directory}:\n"
                f"  instruments   {len(report.instruments_created):>3} created, "
                f"{len(report.instruments_updated):>3} updated\n"
                f"  conditions    {len(report.conditions_created):>3} created, "
                f"{len(report.conditions_updated):>3} updated\n"
                f"  rules         {len(report.rules_created):>3} created, "
                f"{len(report.rules_updated):>3} updated\n"
                f"  requirements  {len(report.requirements_created):>3} created, "
                f"{len(report.requirements_updated):>3} updated"
            )
        )

        if report.unlinked_rule_codes:
            self.stdout.write(
                self.style.WARNING(
                    "\nThese executable rule codes are referenced by a "
                    "requirement but are not loaded: "
                    + ", ".join(sorted(set(report.unlinked_rule_codes)))
                    + "\nRun 'load_rules' and then this command again to link "
                    "them. Until then those requirements have no evaluator."
                )
            )

        if dry_run:
            return

        self._report_honestly()

    def _report_honestly(self) -> None:
        """Print what is evaluated versus merely recorded.

        The whole point of the framework is that the two numbers differ, and by
        a lot. Printing only the load count would invite exactly the claim this
        project refuses to make.
        """
        total = RuleRequirement.objects.filter(is_active=True).count()
        implemented = RuleRequirement.objects.filter(
            is_active=True, implementation_status=ImplementationStatus.IMPLEMENTED
        ).count()
        evaluated = (
            RuleRequirement.objects.filter(
                is_active=True, compliance_rules__is_active=True
            )
            .distinct()
            .count()
        )

        self.stdout.write(
            "\n"
            f"{total} active requirement(s) are now on record. "
            f"{implemented} are marked implemented, and {evaluated} have an "
            f"active executable rule behind them.\n"
            "Recording a requirement does NOT mean the system evaluates it. "
            "Most of this framework is inventoried so that what the system "
            "cannot check is visible rather than absent - see "
            "rules/INVENTORY.md for why each one is not evaluated."
        )
