"""`manage.py load_rules` - import rule definitions from rules/definitions/."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.rules.loader import RuleFileError, load_rules


class Command(BaseCommand):
    help = (
        "Load compliance rule definitions from JSON files into the database. "
        "Idempotent: re-running updates existing rules by code."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--directory",
            type=Path,
            default=None,
            help=(
                "Directory to read rule files from. Defaults to "
                "RULES_DEFINITIONS_DIR (rules/definitions/)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate the files and report what would change, without writing.",
        )

    def handle(self, *args, **options) -> None:
        directory: Path = options["directory"] or settings.RULES_DEFINITIONS_DIR
        dry_run: bool = options["dry_run"]

        if not directory.is_dir():
            raise CommandError(f"Rules directory does not exist: {directory}")

        try:
            report = load_rules(directory, dry_run=dry_run)
        except RuleFileError as exc:
            raise CommandError(str(exc)) from None

        if report.errors:
            self.stderr.write(self.style.ERROR("Rule definitions are invalid:"))
            for error in report.errors:
                self.stderr.write(f"  - {error}")
            raise CommandError(
                f"{len(report.errors)} error(s). Nothing was written."
            )

        if report.total_seen == 0:
            # Not an error, and worth stating plainly: this is the expected
            # state of the repository until feature/legal-rules-dataset lands.
            self.stdout.write(
                self.style.WARNING(
                    f"No rule files found in {directory}.\n"
                    "The rule set is empty, so the compliance engine cannot "
                    "return COMPLIANT for any product - it will report "
                    "REVIEW_REQUIRED. See rules/README.md."
                )
            )
            return

        prefix = "[dry run] Would have" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix} created {len(report.created)}, "
                f"updated {len(report.updated)} rule(s) from {directory}."
            )
        )
        for code in report.created:
            self.stdout.write(f"  + {code}")
        for code in report.updated:
            self.stdout.write(f"  ~ {code}")
