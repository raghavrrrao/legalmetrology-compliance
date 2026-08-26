"""The compliance engine's honesty guarantees.

These are the most important tests in the backend. They encode the three
promises the system makes about what it will and will not claim, so that a
future refactor cannot quietly weaken them:

1. No rules checked -> never COMPLIANT.
2. An unverified rule can never produce a violation.
3. An unreadable photograph is never reported as a missing declaration.
"""

import pytest

from apps.compliance.models import ComplianceCheck
from apps.compliance.services import engine

pytestmark = pytest.mark.django_db


# --- guarantee 1: silence is not compliance ---------------------------------


def test_no_rules_loaded_yields_review_required_not_compliant(completed_run):
    """The current state of this repository: zero rules loaded.

    A system with no rules has checked nothing. Reporting COMPLIANT here would
    tell every user their product is fine, which is the single worst failure
    this project could ship.
    """
    check = engine.evaluate(completed_run)

    assert check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    assert check.result != ComplianceCheck.Result.COMPLIANT
    assert check.rules_evaluated == 0
    assert "not a finding that the product complies" in check.summary


def test_unknown_product_category_yields_review_required(completed_run, product):
    """Without knowing the commodity, applicability cannot be determined."""
    product.category = None
    product.save()

    check = engine.evaluate(completed_run, product=product)

    assert check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    assert "category" in check.summary.lower()


def test_product_with_no_category_matches_no_rules(product, make_rule):
    make_rule("R-1")
    product.category = None
    product.save()

    assert engine.applicable_rules(product) == []


# --- guarantee 2: unverified rules cannot fail a product --------------------


def test_unverified_rule_cannot_produce_a_violation(completed_run, make_rule):
    """A rule nobody has checked against the law cannot accuse anyone.

    The declaration is genuinely absent here, so the validator returns FAILED.
    The engine must still downgrade it, because the rule's legal basis is
    unverified.
    """
    make_rule("R-UNVERIFIED", verified=False)

    check = engine.evaluate(completed_run)

    assert check.result != ComplianceCheck.Result.NON_COMPLIANT
    assert check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    assert check.violations.count() == 0
    assert check.rules_failed == 0
    assert check.rules_inconclusive == 1


def test_verified_rule_does_produce_a_violation(completed_run, make_rule):
    """The contrast case: a verified rule works normally."""
    make_rule("R-VERIFIED", verified=True)

    check = engine.evaluate(completed_run)

    assert check.result == ComplianceCheck.Result.NON_COMPLIANT
    assert check.violations.count() == 1
    assert check.rules_failed == 1


# --- guarantee 3: an unreadable image is not a violation --------------------


def test_unreadable_image_is_never_reported_as_a_missing_declaration(
    empty_run, make_rule
):
    """The difference between 'your package is illegal' and 'retake the photo'."""
    make_rule("R-VERIFIED", verified=True)

    check = engine.evaluate(empty_run)

    assert check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    assert check.violations.count() == 0
    assert "readable" in check.summary.lower()


# --- evidence ---------------------------------------------------------------


def test_a_violation_carries_its_rule_reference_and_evidence(
    completed_run, make_rule
):
    """Every finding must be answerable to 'why?'."""
    make_rule("R-EVIDENCE", verified=True, legal_reference="Some provision")

    check = engine.evaluate(completed_run)
    violation = check.violations.get()

    assert violation.rule_code == "R-EVIDENCE"
    assert violation.legal_reference == "Some provision"
    assert violation.field_key == "net_quantity"
    assert violation.message

    evidence = violation.evidence.get()
    assert evidence.image_id == completed_run.image_id
    # For an absent declaration, the evidence is what we DID read.
    assert evidence.excerpt == completed_run.recognised_text


def test_violation_snapshots_severity_so_history_does_not_change(
    completed_run, make_rule
):
    """Amending a rule must not rewrite what a past finding meant."""
    rule = make_rule("R-SNAP", verified=True, severity="minor")
    check = engine.evaluate(completed_run)
    violation = check.violations.get()
    assert violation.severity == "minor"

    rule.severity = "critical"
    rule.save()

    violation.refresh_from_db()
    assert violation.severity == "minor"


# --- passing and mixed results ----------------------------------------------


def test_present_declaration_passes(completed_run, make_rule, make_extracted_field):
    make_rule("R-PASS", verified=True, field_key="net_quantity")
    make_extracted_field(completed_run, "net_quantity", "500 g")

    check = engine.evaluate(completed_run)

    assert check.result == ComplianceCheck.Result.COMPLIANT
    assert check.rules_passed == 1
    # Even a pass states its limits rather than implying certification.
    assert "not a certification" in check.summary


def test_mixed_verified_failure_and_unverified_rule_is_partially_compliant(
    completed_run, make_rule
):
    make_rule("R-A", verified=True, field_key="net_quantity")
    make_rule("R-B", verified=False, field_key="retail_sale_price")

    check = engine.evaluate(completed_run)

    assert check.result == ComplianceCheck.Result.PARTIALLY_COMPLIANT
    assert check.rules_failed == 1
    assert check.rules_inconclusive == 1


# --- applicability ----------------------------------------------------------


def test_rule_with_no_categories_applies_to_every_commodity(product, make_rule):
    make_rule("R-UNIVERSAL", categories=[])
    assert [r.code for r in engine.applicable_rules(product)] == ["R-UNIVERSAL"]


def test_rule_for_another_category_does_not_apply(product, make_rule, db):
    from apps.catalog.models import ProductCategory

    other = ProductCategory.objects.create(code="cosmetics", name="Cosmetics")
    make_rule("R-OTHER", categories=[other])

    assert engine.applicable_rules(product) == []


def test_rule_applies_through_category_inheritance(product, make_rule, category, db):
    """A rule on a parent category applies to its children."""
    from apps.catalog.models import ProductCategory

    child = ProductCategory.objects.create(
        code="packaged-food-biscuits", name="Biscuits", parent=category
    )
    product.category = child
    product.save()
    make_rule("R-PARENT", categories=[category])

    assert [r.code for r in engine.applicable_rules(product)] == ["R-PARENT"]


def test_inactive_rule_is_not_evaluated(product, make_rule):
    make_rule("R-OFF", is_active=False)
    assert engine.applicable_rules(product) == []


def test_expired_rule_is_not_evaluated(product, make_rule):
    from datetime import date

    make_rule("R-EXPIRED", effective_to=date(2020, 1, 1))
    assert engine.applicable_rules(product) == []


def test_a_broken_rule_does_not_crash_the_whole_check(completed_run, make_rule):
    """One malformed rule must not make every product unevaluable.

    It is skipped and logged - and importantly, not counted as a pass.
    """
    make_rule("R-BROKEN", verified=True, parameters={})  # missing field_key

    check = engine.evaluate(completed_run)

    assert check.status == ComplianceCheck.Status.COMPLETED
    assert check.rules_passed == 0
    assert check.result != ComplianceCheck.Result.COMPLIANT


# --- guarantee 3, second half: a declaration named but not read -------------
#
# `empty_run` above covers the whole photograph being unreadable. This covers
# the narrower and more common case: the photograph is fine, other declarations
# were read from it, and one panel was caught edge-on so a single declaration's
# value is illegible.
#
# Before unread declarations crossed into the check context this produced
# NON_COMPLIANT with a violation on the record - the system telling a user
# their package lacks a declaration that is printed on it, in a photograph they
# can see. These tests exist so it cannot go back.
#
# The rules used here are the test fixture's own placeholder rules. Nothing in
# this file states a requirement of the Legal Metrology (Packaged Commodities)
# Rules, 2011; the repository ships no such rule, and this integration adds
# none.


def test_a_named_but_unread_declaration_yields_review_required(
    completed_run, make_rule, make_unread_declaration
):
    """The outcome the whole integration exists to produce."""
    make_rule("R-UNREAD", verified=True, field_key="retail_sale_price")
    make_unread_declaration(
        completed_run, "retail_sale_price", evidence_text="MRP"
    )

    check = engine.evaluate(completed_run)

    assert check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    assert check.rules_inconclusive == 1


def test_a_named_but_unread_declaration_is_never_non_compliant(
    completed_run, make_rule, make_unread_declaration
):
    """The regression, stated as the thing that must not happen.

    A verified rule and an absent field is normally NON_COMPLIANT - the test
    directly above `guarantee 2` asserts exactly that. The only difference here
    is the unread row.
    """
    make_rule("R-UNREAD", verified=True, field_key="retail_sale_price")
    make_unread_declaration(
        completed_run, "retail_sale_price", evidence_text="MRP"
    )

    check = engine.evaluate(completed_run)

    assert check.result != ComplianceCheck.Result.NON_COMPLIANT
    assert check.violations.count() == 0
    assert check.rules_failed == 0


def test_a_named_but_unread_declaration_is_never_compliant(
    completed_run, make_rule, make_unread_declaration
):
    """The opposite error, which would be worse.

    Suppressing the failure must not be mistaken for satisfying the rule. An
    unread declaration is a reason to look again, never a pass.
    """
    make_rule("R-UNREAD", verified=True, field_key="retail_sale_price")
    make_unread_declaration(
        completed_run, "retail_sale_price", evidence_text="MRP"
    )

    check = engine.evaluate(completed_run)

    assert check.result != ComplianceCheck.Result.COMPLIANT
    assert check.rules_passed == 0


def test_the_summary_explains_that_nothing_was_concluded(
    completed_run, make_rule, make_unread_declaration
):
    """A user has to be told why there is no verdict, not just that there isn't."""
    make_rule("R-UNREAD", verified=True, field_key="retail_sale_price")
    make_unread_declaration(
        completed_run, "retail_sale_price", evidence_text="MRP"
    )

    check = engine.evaluate(completed_run)

    assert "could not be determined" in check.summary
    assert "no compliance conclusion has been drawn" in check.summary


def test_an_unread_declaration_alongside_a_real_failure_is_partially_compliant(
    completed_run, make_rule, make_unread_declaration
):
    """One panel being illegible must not erase a violation found elsewhere.

    The engine already routes failed + inconclusive to PARTIALLY_COMPLIANT.
    This asserts an unread declaration feeds that path rather than short-
    circuiting it, so a genuine finding still reaches the user.
    """
    make_rule("R-MISSING", verified=True, field_key="country_of_origin")
    make_rule("R-UNREAD", verified=True, field_key="retail_sale_price")
    make_unread_declaration(
        completed_run, "retail_sale_price", evidence_text="MRP"
    )

    check = engine.evaluate(completed_run)

    assert check.result == ComplianceCheck.Result.PARTIALLY_COMPLIANT
    assert check.rules_failed == 1
    assert check.rules_inconclusive == 1
    assert check.violations.get().field_key == "country_of_origin"


def test_a_declaration_that_was_read_still_passes_beside_an_unread_one(
    completed_run,
    make_rule,
    make_extracted_field,
    make_unread_declaration,
):
    """Per declaration, not per run - checked at the verdict level.

    One illegible panel must not stop the system reporting what it did
    establish about the rest of the label.
    """
    make_rule("R-READ", verified=True, field_key="net_quantity")
    make_rule("R-UNREAD", verified=True, field_key="retail_sale_price")
    make_extracted_field(completed_run, "net_quantity", "500 g")
    make_unread_declaration(
        completed_run, "retail_sale_price", evidence_text="MRP"
    )

    check = engine.evaluate(completed_run)

    assert check.rules_passed == 1
    assert check.rules_inconclusive == 1
    assert check.rules_failed == 0
    assert check.result == ComplianceCheck.Result.REVIEW_REQUIRED


def test_an_unrelated_unread_declaration_does_not_rescue_a_missing_one(
    completed_run, make_rule, make_unread_declaration
):
    """The suppression is keyed, and must not become a blanket amnesty.

    An illegible MRP says nothing about the country of origin. If it did, a
    single unread row anywhere would silence every rule on the label.
    """
    make_rule("R-MISSING", verified=True, field_key="country_of_origin")
    make_unread_declaration(
        completed_run, "retail_sale_price", evidence_text="MRP"
    )

    check = engine.evaluate(completed_run)

    assert check.result == ComplianceCheck.Result.NON_COMPLIANT
    assert check.violations.get().field_key == "country_of_origin"


def test_an_unverified_rule_over_an_unread_declaration_is_still_review_required(
    completed_run, make_rule, make_unread_declaration
):
    """Guarantee 2 and the new branch must compose, not fight.

    Both routes lead to review. This pins that an unverified rule does not
    somehow re-acquire the ability to fail a product through this path.
    """
    make_rule("R-UNVERIFIED", verified=False, field_key="retail_sale_price")
    make_unread_declaration(
        completed_run, "retail_sale_price", evidence_text="MRP"
    )

    check = engine.evaluate(completed_run)

    assert check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    assert check.violations.count() == 0
