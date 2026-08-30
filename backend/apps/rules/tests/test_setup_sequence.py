"""The setup order that `load_rules` depends on, pinned so it cannot regress.

Rule files name the categories they apply to by `ProductCategory.code`, and
`apps.rules.loader._resolve_categories` rejects a code with no row rather than
silently dropping it - dropping it would widen the rule to every commodity,
the opposite of what the author asked for.

That makes `seed_categories` a hard prerequisite of `load_rules`, and nothing
enforced it. It went unnoticed because `rules/definitions/` was empty: with no
rule files, the loader never resolved a category, so `load_rules --dry-run`
passed on a database with no categories at all. The first real rule turned that
latent ordering bug into a CI failure:

    CommandError: LM-PC-0001: unknown product category code(s): packaged-non-food

Two things are pinned here:

1. The seeded taxonomy actually covers every category the shipped rules name -
   the substantive invariant, checked by running both commands for real.
2. CI runs the two in that order - the process invariant, checked by reading
   the workflow, because a green suite on a developer machine with a populated
   database would otherwise say nothing about a clean CI database.
"""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.catalog.models import ProductCategory
from apps.rules.loader import discover_rule_files, parse_rule_file
from apps.rules.models import ComplianceRule

pytestmark = pytest.mark.django_db


#: The workflow this repository actually runs. Read as text rather than parsed
#: as YAML so this test needs no new dependency for a question this simple.
WORKFLOW = Path(__file__).resolve().parents[4] / ".github" / "workflows" / "ci.yml"


# --- the substantive invariant ----------------------------------------------


def test_seed_categories_then_load_rules_succeeds_on_an_empty_database():
    """The exact sequence CI runs, against the real rule files.

    Starts from a database with no categories, which is what CI has after
    `migrate`. If a rule ever names a category `seed_categories` does not
    create, this fails here rather than in a deployment.
    """
    assert not ProductCategory.objects.exists()

    call_command("seed_categories", stdout=StringIO())
    call_command("load_rules", "--dry-run", stdout=StringIO())


def test_load_rules_without_seeding_fails_loudly():
    """The failure must stay loud - it is the guard, not the bug.

    A loader that shrugged at an unknown category code would widen every rule
    to every commodity. This asserts the ordering requirement is enforced by
    the loader rather than merely documented.
    """
    from django.core.management.base import CommandError

    assert not ProductCategory.objects.exists()

    with pytest.raises(CommandError, match="unknown product category"):
        call_command("load_rules", "--dry-run", stdout=StringIO(), stderr=StringIO())


def test_seeded_categories_cover_every_category_the_rules_name(settings):
    """Names the gap directly, so a failure says which code is missing."""
    call_command("seed_categories", stdout=StringIO())
    seeded = set(ProductCategory.objects.values_list("code", flat=True))

    referenced: set[str] = set()
    for path in discover_rule_files(settings.RULES_DEFINITIONS_DIR):
        referenced.update(parse_rule_file(path)["applies_to_category_codes"])

    assert referenced, "no shipped rule names a category - check the loader"
    assert referenced <= seeded, (
        f"rule files reference categories seed_categories does not create: "
        f"{sorted(referenced - seeded)}"
    )


def test_loading_twice_after_seeding_is_idempotent():
    """CI and a developer both re-run these; neither may drift."""
    call_command("seed_categories", stdout=StringIO())
    call_command("load_rules", stdout=StringIO())
    first = ComplianceRule.objects.count()

    call_command("seed_categories", stdout=StringIO())
    call_command("load_rules", stdout=StringIO())

    assert ComplianceRule.objects.count() == first


# --- the process invariant --------------------------------------------------


def _backend_job_steps() -> list[str]:
    """Step names of the CI `backend` job, in the order the workflow lists them."""
    text = WORKFLOW.read_text(encoding="utf-8")
    backend = text.split("  backend:", 1)[1].split("\n  ml:", 1)[0]
    return re.findall(r"^\s*-\s*name:\s*(.+?)\s*$", backend, flags=re.MULTILINE)


def test_ci_seeds_categories_before_loading_rules():
    """The ordering bug that caused the CI failure, pinned.

    Reordering or deleting the seed step in ci.yml breaks this test rather than
    only the next pull request.
    """
    steps = _backend_job_steps()
    joined = " | ".join(steps)

    seed = next((i for i, s in enumerate(steps) if "Seed product categories" in s), None)
    load = next((i for i, s in enumerate(steps) if "Rule loader" in s), None)

    assert seed is not None, f"CI has no category-seeding step. Steps: {joined}"
    assert load is not None, f"CI has no rule-loader step. Steps: {joined}"
    assert seed < load, (
        f"CI runs the rule loader before seeding categories, so load_rules will "
        f"fail on a clean database. Steps: {joined}"
    )


def test_ci_migrates_before_seeding_categories():
    """`seed_categories` writes rows, so the tables have to exist first."""
    steps = _backend_job_steps()

    migrate = next((i for i, s in enumerate(steps) if "Apply migrations" in s), None)
    seed = next((i for i, s in enumerate(steps) if "Seed product categories" in s), None)

    assert migrate is not None and seed is not None
    assert migrate < seed


def test_the_readme_documents_the_seeding_step():
    """CI and the README must not drift.

    The workflow's own header says it runs the commands the README tells a
    developer to run; the README was missing this step too, so a developer
    following it on a clean database hit the same failure.
    """
    readme = (WORKFLOW.parents[2] / "README.md").read_text(encoding="utf-8")

    assert "manage.py seed_categories" in readme
    assert readme.index("manage.py seed_categories") < readme.index(
        "manage.py load_rules"
    )
