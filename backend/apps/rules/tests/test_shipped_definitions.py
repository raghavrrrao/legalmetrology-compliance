"""The rules this repository actually ships in `rules/definitions/`.

Every other test in `apps/rules` builds its own throwaway rule files. These
tests read the real ones, because the shipped set makes legal claims about real
products and the two things that can go wrong with it are not caught anywhere
else:

1. A rule file drifts out of the shape the loader accepts, and `load_rules`
   fails in a deployment rather than in CI.
2. Someone widens a rule's applicability, or flips `is_active`, without the
   verified sourcing that entitles it to produce a finding. Four of the six
   shipped rules are deliberately inactive - three because `field_presence`
   cannot express their carve-outs safely (see `rules/SOURCES.md`), and
   LM-PC-0002 because the extractor does not read the declaration it names
   (see `rules/INVENTORY.md`). Activating one is a legal decision, so it has
   to break a test rather than pass quietly.
"""

import pytest

from apps.catalog.models import ProductCategory
from apps.compliance.models import ComplianceCheck
from apps.compliance.services import engine
from apps.rules.loader import discover_rule_files, load_rules, parse_rule_file
from apps.rules.models import ComplianceRule

pytestmark = pytest.mark.django_db


#: Evaluated against real products. Each is a verified declaration whose
#: applicability the current schema can express without over-applying, AND
#: whose declaration the extractor actually reads.
ACTIVE_CODES = {"LM-PC-0003", "LM-PC-0006"}

#: Verified text kept on record, but not evaluated. Three are blocked on
#: applicability the schema cannot express - `rules/SOURCES.md` says which
#: exemption blocks which. LM-PC-0002 is blocked on something different: the
#: extractor does not read `common_or_generic_name`, so the rule could only
#: ever return "cannot tell". See rules/INVENTORY.md.
INACTIVE_CODES = {"LM-PC-0001", "LM-PC-0002", "LM-PC-0004", "LM-PC-0005"}

#: The declarations the active rules require, and the LabelFieldKey each uses.
ACTIVE_FIELD_KEYS = {
    "LM-PC-0003": "net_quantity",
    "LM-PC-0006": "consumer_care_contact",
}


@pytest.fixture
def shipped(settings):
    """Every shipped rule file, parsed, keyed by code."""
    paths = discover_rule_files(settings.RULES_DEFINITIONS_DIR)
    return {parsed["code"]: parsed for parsed in map(parse_rule_file, paths)}


@pytest.fixture
def taxonomy(category):
    """The hierarchy `seed_categories` creates, built around `category`.

    The shared `category` fixture is `packaged-food` with no parent, which is
    not the shape the shipped rules target: they attach to
    `packaged-commodity`, and reach food and non-food through
    `ProductCategory.ancestry_codes()`. Giving the shared fixture its real
    parent here keeps `product`, `product_image` and `completed_run` usable
    without duplicating them.
    """
    root = ProductCategory.objects.create(
        code="packaged-commodity", name="Packaged commodity"
    )
    category.parent = root
    category.save()
    non_food = ProductCategory.objects.create(
        code="packaged-non-food", name="Packaged non-food", parent=root
    )
    return root, category, non_food


@pytest.fixture
def loaded_rules(settings, taxonomy):
    """The shipped rules, loaded into the database for real."""
    report = load_rules(settings.RULES_DEFINITIONS_DIR)
    assert report.ok, report.errors
    return report


# --- the files themselves ---------------------------------------------------


def test_the_shipped_rule_set_is_exactly_what_was_reviewed(shipped):
    """A new rule file must come with review, so it must break this test."""
    assert set(shipped) == ACTIVE_CODES | INACTIVE_CODES


def test_every_shipped_rule_is_verified_with_a_source_note(shipped):
    """`unverified` cannot fail a product, so shipping one would be dead weight.

    The loader already rejects `verified` without a note; asserting it here
    covers the shipped files specifically rather than the loader's behaviour.
    """
    for code, rule in shipped.items():
        assert rule["source_status"] == "verified", code
        assert rule["source_note"].strip(), code
        assert rule["legal_reference"].strip(), code


def test_only_the_reviewed_rules_are_active(shipped):
    """Flipping `is_active` is a legal decision, not a configuration tweak.

    If this fails because a rule was activated, the question to answer is what
    was unblocked: an exemption the categories can now express (LM-PC-0001,
    -0004, -0005, see rules/SOURCES.md), or an extractor that now reads the
    declaration (LM-PC-0002).
    """
    active = {code for code, rule in shipped.items() if rule["is_active"]}

    assert active == ACTIVE_CODES
    assert set(shipped) - active == INACTIVE_CODES


def test_the_food_carve_out_rules_never_target_food(shipped):
    """Rule 6(1)(a) and 6(1)(d) are disapplied to packages containing food.

    Both defer to the Food Safety and Standards Act, 2006 for food articles, so
    neither may be attached to `packaged-food` or to the root category that
    food inherits from.
    """
    for code in ("LM-PC-0001", "LM-PC-0004"):
        assert shipped[code]["applies_to_category_codes"] == ["packaged-non-food"], code


def test_no_shipped_rule_claims_every_commodity(shipped):
    """An empty category list is a universal claim; none of these makes one."""
    for code, rule in shipped.items():
        assert rule["applies_to_category_codes"], code


def test_the_shipped_files_load(loaded_rules):
    assert set(loaded_rules.created) == ACTIVE_CODES | INACTIVE_CODES
    assert ComplianceRule.objects.count() == 6


# --- applicability ----------------------------------------------------------


def test_only_active_rules_are_applicable_to_a_food_product(loaded_rules, product):
    """`product` is in `packaged-food`, which inherits from the root category."""
    codes = {rule.code for rule in engine.applicable_rules(product)}

    assert codes == ACTIVE_CODES


def test_the_non_food_rules_do_not_apply_to_a_food_product(loaded_rules, product):
    """The carve-out has to hold at the query, not just in the file.

    Checked directly on the rule rather than through `applicable_rules`, so
    that it still holds if LM-PC-0001 or LM-PC-0004 is activated later.
    """
    for code in ("LM-PC-0001", "LM-PC-0004"):
        rule = ComplianceRule.objects.get(code=code)
        assert not rule.applies_to_category_codes(product.applicable_category_codes)


def test_the_non_food_rules_do_apply_to_a_non_food_product(loaded_rules, taxonomy):
    """The contrast case: the carve-out is a food carve-out, not a mute rule."""
    _, _, non_food = taxonomy

    for code in ("LM-PC-0001", "LM-PC-0004"):
        rule = ComplianceRule.objects.get(code=code)
        assert rule.applies_to_category_codes(non_food.ancestry_codes())


def test_no_rule_applies_to_a_product_of_unknown_category(loaded_rules, product):
    product.category = None
    product.save()

    assert engine.applicable_rules(product) == []


# --- evaluation -------------------------------------------------------------


def test_an_absent_declaration_produces_a_violation(loaded_rules, completed_run):
    """`completed_run` read text but found no declarations at all.

    This is the state that separates "the declaration is missing" from "we
    could not read the photo", so every active rule must fail here.
    """
    check = engine.evaluate(completed_run)

    assert check.result == ComplianceCheck.Result.NON_COMPLIANT
    assert check.rules_evaluated == len(ACTIVE_CODES)
    assert check.rules_failed == len(ACTIVE_CODES)
    assert {v.rule_code for v in check.violations.all()} == ACTIVE_CODES

    for violation in check.violations.all():
        assert violation.legal_reference.startswith("Rule 6")
        assert violation.field_key == ACTIVE_FIELD_KEYS[violation.rule_code]


def test_a_present_declaration_produces_no_missing_field_violation(
    loaded_rules, completed_run, make_extracted_field
):
    for field_key in ACTIVE_FIELD_KEYS.values():
        make_extracted_field(completed_run, field_key)

    check = engine.evaluate(completed_run)

    assert check.violations.count() == 0
    assert check.rules_failed == 0
    assert check.rules_passed == len(ACTIVE_CODES)
    assert check.result == ComplianceCheck.Result.COMPLIANT


def test_one_present_declaration_removes_only_its_own_violation(
    loaded_rules, completed_run, make_extracted_field
):
    """A pass on one rule must not suppress the others' findings."""
    make_extracted_field(completed_run, "net_quantity", raw_value="500 g")

    check = engine.evaluate(completed_run)

    assert check.result == ComplianceCheck.Result.NON_COMPLIANT
    assert {v.rule_code for v in check.violations.all()} == ACTIVE_CODES - {
        "LM-PC-0003"
    }


def test_an_unreadable_image_yields_no_violation(loaded_rules, empty_run):
    """The shipped rules must not turn a bad photograph into a legal finding."""
    check = engine.evaluate(empty_run)

    assert check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    assert check.violations.count() == 0
