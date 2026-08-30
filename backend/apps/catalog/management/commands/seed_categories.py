"""Create the minimum commodity categories the analysis flow needs.

    python backend/manage.py seed_categories

Why this exists
---------------
Rule applicability is answered from `Product.category`. With no category on a
submission, `applicable_rules()` returns an empty list and the compliance
engine reports REVIEW_REQUIRED with "the commodity category is not known" -
correctly, but it means the applicability machinery cannot be exercised or
demonstrated at all until at least one category row exists. This command
creates that row.

What this is NOT
----------------
**These codes are an internal taxonomy, not legal content.** A category code is
an identifier this system uses to group commodities so that a rule can say
which commodities it covers. Nothing here asserts that a category exists in the
Legal Metrology (Packaged Commodities) Rules, 2011, that it is the right way to
carve up commodities under them, or that any particular declaration is required
for anything in it. That claim can only be made by a verified `ComplianceRule`,
and `rules/definitions/` ships none - see `rules/README.md`.

The set below is therefore deliberately shallow and generic: one root that
restates the problem statement's own subject, plus two obvious sub-groupings
present to prove the inheritance in `ProductCategory.ancestry_codes()` works.
Whoever takes `feature/legal-rules-dataset` should expect to replace this
taxonomy with one derived from the authoritative text, and is free to: no rule
file references these codes yet, so nothing breaks when they change.

Idempotent. Safe to re-run; it never renames or deletes an existing category,
because `rules/README.md` notes that renaming a code invalidates rule files
that reference it.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.catalog.models import ProductCategory

#: (code, name, parent_code). Ordered so a parent is always created first.
_CATEGORIES: tuple[tuple[str, str, str | None], ...] = (
    (
        "packaged-commodity",
        "Packaged commodity",
        None,
    ),
    (
        "packaged-food",
        "Packaged food",
        "packaged-commodity",
    ),
    (
        "packaged-non-food",
        "Packaged non-food",
        "packaged-commodity",
    ),
)

_DESCRIPTION = (
    "Internal grouping used to decide which compliance rules apply. Not a "
    "category defined by the Legal Metrology (Packaged Commodities) Rules, "
    "2011; see apps/catalog/management/commands/seed_categories.py."
)


class Command(BaseCommand):
    help = "Create the baseline product categories used for rule applicability."

    def handle(self, *args, **options) -> None:
        created_count = 0

        for code, name, parent_code in _CATEGORIES:
            parent = (
                ProductCategory.objects.get(code=parent_code)
                if parent_code
                else None
            )
            _, created = ProductCategory.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "parent": parent,
                    "description": _DESCRIPTION,
                },
            )
            created_count += int(created)
            self.stdout.write(
                f"  {'created' if created else 'exists '}  {code}"
            )

        total = ProductCategory.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"{created_count} categor{'y' if created_count == 1 else 'ies'} "
                f"created; {total} now present."
            )
        )
        self.stdout.write(
            "These are grouping identifiers only. No compliance rule is "
            "loaded by this command, and none ships in rules/definitions/ - "
            "so every product will still be reported as REVIEW_REQUIRED."
        )
