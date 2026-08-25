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
