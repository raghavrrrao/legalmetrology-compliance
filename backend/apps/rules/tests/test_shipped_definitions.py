"""The rules this repository actually ships in `rules/definitions/`.

Every other test in `apps/rules` builds its own throwaway rule files. These
tests read the real ones, because the shipped set makes legal claims about real
products and the two things that can go wrong with it are not caught anywhere
else:

1. A rule file drifts out of the shape the loader accepts, and `load_rules`
   fails in a deployment rather than in CI.
2. Someone widens a rule's applicability, or flips `is_active`, without the
   verified sourcing that entitles it to produce a finding. One shipped rule -
   LM-PC-0002 - is deliberately inactive, because the extractor does not read
   the declaration it names (see `rules/INVENTORY.md`). Activating it, or
   adding a rule to the shipped set, is a legal decision, so it has to break a
   test rather than pass quietly.
"""

import pytest

from apps.catalog.models import ProductCategory
from apps.compliance.models import ComplianceCheck, ComplianceFinding
from apps.compliance.services import engine
from apps.rules.framework_loader import load_framework
from apps.rules.loader import discover_rule_files, load_rules, parse_rule_file
from apps.rules.models import ComplianceRule

pytestmark = pytest.mark.django_db


#: Evaluated against real products. Each is a verified declaration whose
#: applicability the current schema can express without over-applying, AND
#: whose declaration the extractor actually reads.
#:
#: Six of these were activated in Step 2, and none of them by relaxing this
#: list first. Two things changed underneath them:
#:
#: - `ProductApplicabilityDeclaration` collects the facts the carve-outs turn
#:   on, and `apps.compliance.services.applicability` resolves them BEFORE a
#:   validator runs. LM-PC-0004 and LM-PC-0005 were blocked because bidi, LPG,
#:   alcohol, cosmetics and seeds could not be separated from `packaged-non-food`;
#:   they no longer have to be, because the exemption is now a declared fact and
#:   an undeclared one yields REVIEW_REQUIRED rather than a violation.
#: - `field_presence_any_of` expresses the disjunction in rule 6(1)(a), which is
#:   what LM-PC-0001 was waiting for.
#:
#: LM-PC-0007 (country of origin) applies only to a package DECLARED imported.
#: LM-PC-0008 and LM-PC-0009 are the rule 13 unit checks.
#:
#: Step 3 added three more, none of which asks for a declaration: each judges
#: what a declaration this system already reads actually says, and each names a
#: clause a presence rule above already covers.
#:
#: - LM-PC-0010, rule 6(2): the TELEPHONE and E-MAIL elements of the
#:   consumer-care declaration. The name and address elements stay unchecked.
#: - LM-PC-0011, rule 6(1)(d): whether the manufacture date resolves to a month
#:   and a year. No printed format is enforced - the clause prescribes none.
#: - LM-PC-0012, rule 6(1)(e): whether the price is declared EXCLUSIVE of all
#:   taxes. The absence of an inclusive-of-taxes indication is NOT a violation.
ACTIVE_CODES = {
    "LM-PC-0001",
    "LM-PC-0003",
    "LM-PC-0004",
    "LM-PC-0005",
    "LM-PC-0006",
    "LM-PC-0007",
    "LM-PC-0008",
    "LM-PC-0009",
    "LM-PC-0010",
    "LM-PC-0011",
    "LM-PC-0012",
}

#: Verified text kept on record, but not evaluated. LM-PC-0002 is blocked on
#: something no applicability input fixes: the extractor does not read
#: `common_or_generic_name`, so the rule could only ever return "cannot tell",
#: and activating it would restore a false violation on every readable label.
#: Reactivating it needs measured extraction recall, not a legal decision.
#: See rules/INVENTORY.md.
INACTIVE_CODES = {"LM-PC-0002"}

#: The declarations the active rules require, and the LabelFieldKey each uses.
#: LM-PC-0001 is absent because it is a disjunction over three keys, and
#: LM-PC-0008 through LM-PC-0012 because they judge what a declaration says
#: rather than asking for one - both are asserted separately below.
ACTIVE_FIELD_KEYS = {
    "LM-PC-0003": "net_quantity",
    "LM-PC-0004": "date_of_manufacture",
    "LM-PC-0005": "retail_sale_price",
    "LM-PC-0006": "consumer_care_contact",
    "LM-PC-0007": "country_of_origin",
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
    """The shipped rules AND the legal framework, loaded for real.

    The framework is loaded too, and in this order, because that is the
    deployment sequence and because since Step 2 the two are not independent:
    `load_legal_framework` links each executable rule to the clause it
    evaluates, and applicability is resolved from that clause's conditions
    before any validator runs. Loading only the rules would exercise a
    configuration that does not ship - and would leave the rules marked
    `requires_applicability_conditions` unmapped, which the engine correctly
    refuses to evaluate.
    """
    report = load_rules(settings.RULES_DEFINITIONS_DIR)
    assert report.ok, report.errors
    framework = load_framework(settings.RULES_FRAMEWORK_DIR)
    assert framework.ok, framework.errors
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
    for code in FOOD_CARVE_OUT_CODES:
        assert shipped[code]["applies_to_category_codes"] == ["packaged-non-food"], code


def test_no_shipped_rule_claims_every_commodity(shipped):
    """An empty category list is a universal claim; none of these makes one."""
    for code, rule in shipped.items():
        assert rule["applies_to_category_codes"], code


def test_the_shipped_files_load(loaded_rules):
    assert set(loaded_rules.created) == ACTIVE_CODES | INACTIVE_CODES
    assert ComplianceRule.objects.count() == len(ACTIVE_CODES | INACTIVE_CODES)


# --- applicability ----------------------------------------------------------


def test_only_active_rules_are_applicable_to_a_food_product(loaded_rules, product):
    """`product` is in `packaged-food`, which inherits from the root category.

    The food carve-out rules are excluded here by category, not by being
    inactive: LM-PC-0001 and LM-PC-0004 target `packaged-non-food` because
    Explanation III and the rule 6(1)(d) provisos defer to the Food Safety and
    Standards Act, 2006 for food articles.
    """
    codes = {rule.code for rule in engine.applicable_rules(product)}

    assert codes == ACTIVE_CODES - FOOD_CARVE_OUT_CODES


def test_the_non_food_rules_do_not_apply_to_a_food_product(loaded_rules, product):
    """The carve-out has to hold at the query, not just in the file.

    Checked directly on the rule rather than through `applicable_rules`, so
    that it still holds if one of them is deactivated and reactivated later.
    """
    for code in FOOD_CARVE_OUT_CODES:
        rule = ComplianceRule.objects.get(code=code)
        assert not rule.applies_to_category_codes(product.applicable_category_codes)


def test_the_non_food_rules_do_apply_to_a_non_food_product(loaded_rules, taxonomy):
    """The contrast case: the carve-out is a food carve-out, not a mute rule."""
    _, _, non_food = taxonomy

    for code in FOOD_CARVE_OUT_CODES:
        rule = ComplianceRule.objects.get(code=code)
        assert rule.applies_to_category_codes(non_food.ancestry_codes())


def test_no_rule_applies_to_a_product_of_unknown_category(loaded_rules, product):
    product.category = None
    product.save()

    assert engine.applicable_rules(product) == []


# --- evaluation -------------------------------------------------------------


#: Presence rules that reach a verdict on a food product with NOTHING
#: declared about it. The set is small on purpose, and the three exclusions are
#: the whole Step 2 story:
#:
#: - LM-PC-0001, LM-PC-0004 and LM-PC-0011 are excluded by CATEGORY. All defer
#:   to the Food Safety and Standards Act, 2006 for food articles.
#: - LM-PC-0005 (retail sale price) is excluded by APPLICABILITY. Proviso (C)
#:   excuses bidi and administered-price LPG, and nothing declares whether this
#:   package is either, so the clause reaches REVIEW_REQUIRED rather than a
#:   verdict.
#: - LM-PC-0007 (country of origin) likewise: it binds imported packages only,
#:   and import status is not declared.
#:
#: Declaring those facts is what moves a rule out of review, which is exactly
#: the incentive the applicability design intends.
UNCONDITIONAL_PRESENCE_CODES = {"LM-PC-0003", "LM-PC-0006"}

#: Rules that judge what a declaration SAYS rather than asking for one. With
#: the declaration absent they are inconclusive, not failures - whether it is
#: required at all is the corresponding presence rule's finding. Keeping that
#: split is what stops one clause producing two violations for one defect.
FORM_CODES = {
    "LM-PC-0008",
    "LM-PC-0009",
    "LM-PC-0010",
    "LM-PC-0011",
    "LM-PC-0012",
}

#: Rules disapplied to packages containing food articles, which defer to the
#: Food Safety and Standards Act, 2006. Rule 6(1)(a) through Explanation III,
#: rule 6(1)(d) through its first proviso.
FOOD_CARVE_OUT_CODES = {"LM-PC-0001", "LM-PC-0004", "LM-PC-0011"}


def test_an_absent_declaration_produces_a_violation(loaded_rules, completed_run):
    """`completed_run` read text but found no declarations at all.

    This is the state that separates "the declaration is missing" from "we
    could not read the photo", so every presence rule that applies must fail.

    Since Step 2 the result is PARTIALLY_COMPLIANT rather than NON_COMPLIANT,
    and the change is the point: rule 6(1)(aa) binds imported packages only,
    nothing declares whether this one is imported, and the engine now says so
    instead of silently applying the clause. A failure plus an undetermined
    rule is partial compliance, not outright non-compliance.
    """
    check = engine.evaluate(completed_run)

    assert check.result == ComplianceCheck.Result.PARTIALLY_COMPLIANT
    assert check.rules_failed == len(UNCONDITIONAL_PRESENCE_CODES)
    assert {v.rule_code for v in check.violations.all()} == (
        UNCONDITIONAL_PRESENCE_CODES
    )

    for violation in check.violations.all():
        assert violation.legal_reference.startswith("Rule 6")
        assert violation.field_key == ACTIVE_FIELD_KEYS[violation.rule_code]


def test_an_undeclared_import_status_is_never_assumed_domestic(
    loaded_rules, completed_run
):
    """Rule 6(1)(aa) must not be silently skipped, nor silently applied.

    The finding for it exists, is inconclusive, and says what was not
    established. Assuming the package domestic would excuse it from a
    declaration it may owe; assuming it imported would fail a package the
    clause never bound.
    """
    check = engine.evaluate(completed_run)

    finding = check.findings.get(rule_code="LM-PC-0007")
    assert finding.status == ComplianceFinding.Status.INCONCLUSIVE
    assert finding.violation is None
    assert "Imported product" in finding.message


def test_a_present_declaration_produces_no_missing_field_violation(
    loaded_rules, completed_run, make_extracted_field
):
    make_extracted_field(completed_run, "net_quantity", raw_value="500 g")
    for code in UNCONDITIONAL_PRESENCE_CODES - {"LM-PC-0003"}:
        make_extracted_field(completed_run, ACTIVE_FIELD_KEYS[code])

    check = engine.evaluate(completed_run)

    assert check.violations.count() == 0
    assert check.rules_failed == 0
    # Not COMPLIANT, and the undetermined rules are named rather than counted,
    # because each is undetermined for a different and instructive reason:
    #
    #   LM-PC-0005  rule 6(1)(e)  - nothing declares whether proviso (C)
    #                               (bidi, administered-price LPG) excuses it
    #   LM-PC-0007  rule 6(1)(aa) - nothing declares whether it is imported
    #   LM-PC-0008  rule 13(5)    - the reading carries no NORMALISED unit, so
    #                               the unit could not be placed. A raw string
    #                               is not a unit, and guessing one from it
    #                               would put the rules layer in the
    #                               normaliser's job.
    #   LM-PC-0010  rule 6(2)     - the consumer-care field these fixtures write
    #                               carries no normalised value, so neither a
    #                               telephone number nor an e-mail address was
    #                               read from it. A located declaration nobody
    #                               could read anything out of is a photograph
    #                               problem, not a package one.
    #   LM-PC-0012  rule 6(1)(e)  - no price was read at all, so how the price
    #                               is declared could not be examined. Whether
    #                               one is required is LM-PC-0005's finding,
    #                               and it is undetermined for its own reason
    #                               above.
    #
    # LM-PC-0011 is absent because it does not apply to a food product at all -
    # rule 6(1)(d) defers to the Food Safety and Standards Act, 2006.
    assert check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    inconclusive = {
        finding.rule_code
        for finding in check.findings.filter(
            status=ComplianceFinding.Status.INCONCLUSIVE
        )
    }
    assert inconclusive == {
        "LM-PC-0005",
        "LM-PC-0007",
        "LM-PC-0008",
        "LM-PC-0010",
        "LM-PC-0012",
    }


def test_one_present_declaration_removes_only_its_own_violation(
    loaded_rules, completed_run, make_extracted_field
):
    """A pass on one rule must not suppress the others' findings."""
    make_extracted_field(completed_run, "net_quantity", raw_value="500 g")

    check = engine.evaluate(completed_run)

    assert check.result == ComplianceCheck.Result.PARTIALLY_COMPLIANT
    assert {v.rule_code for v in check.violations.all()} == (
        UNCONDITIONAL_PRESENCE_CODES - {"LM-PC-0003"}
    )


def test_an_unreadable_image_yields_no_violation(loaded_rules, empty_run):
    """The shipped rules must not turn a bad photograph into a legal finding."""
    check = engine.evaluate(empty_run)

    assert check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    assert check.violations.count() == 0
