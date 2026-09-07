"""End-to-end compliance scenarios against the rules this repository ships.

Everything here runs the real engine over the real `rules/definitions/` and
`rules/framework/`, with realistic label readings. Nothing is mocked except the
OCR itself: these tests build `ExtractedLabelField` rows directly, exactly as
the extraction service writes them, and make **no claim about OCR accuracy** -
that is measured in `ml/`, on annotated photographs, and cannot be demonstrated
by a unit test that never runs an engine.

The scenarios are grouped by what they are really testing:

    applicability   a rule that does not govern a package must not judge it
    rule 6          the core declarations, and what is deliberately not checked
    rules 7-13      what the evidence supports, and what it does not
    limits          the things an image cannot establish, at any confidence
"""

from __future__ import annotations

import pytest
from django.conf import settings

from apps.catalog.models import Product, ProductApplicabilityDeclaration
from apps.compliance.models import ComplianceCheck, ComplianceFinding
from apps.compliance.services import engine
from apps.extraction.models import ExtractionRun
from apps.images.models import ProductImage
from apps.rules.framework_loader import load_framework
from apps.rules.loader import load_rules
from apps.rules.models import ApplicabilityCondition

pytestmark = pytest.mark.django_db

Answer = ProductApplicabilityDeclaration.Answer
Status = ComplianceFinding.Status
Result = ComplianceCheck.Result


@pytest.fixture
def shipped(settings, category):
    """The real taxonomy, the real rules, and the real framework.

    Loaded in the deployment order: categories, then rules, then the framework
    that links each rule to its clause.
    """
    from apps.catalog.models import ProductCategory

    root = ProductCategory.objects.create(
        code="packaged-commodity", name="Packaged commodity"
    )
    category.parent = root
    category.save()
    ProductCategory.objects.create(
        code="packaged-non-food", name="Packaged non-food", parent=root
    )
    rules = load_rules(settings.RULES_DEFINITIONS_DIR)
    assert rules.ok, rules.errors
    framework = load_framework(settings.RULES_FRAMEWORK_DIR)
    assert framework.ok, framework.errors
    return rules


@pytest.fixture
def label(shipped, product_image, make_extracted_field):
    """Build a completed extraction run carrying the declarations given.

    `declarations` maps a LabelFieldKey to either a raw string or a
    (raw, normalized) pair - the same shape the extraction service persists.
    """

    def _label(**declarations) -> ExtractionRun:
        run = ExtractionRun.objects.create(
            image=product_image,
            engine_name="stub",
            engine_version="0.0.0",
            status=ExtractionRun.Status.COMPLETED,
            recognised_text="\n".join(
                str(v[0] if isinstance(v, tuple) else v)
                for v in declarations.values()
            ),
        )
        for field_key, value in declarations.items():
            raw, normalised = value if isinstance(value, tuple) else (value, None)
            make_extracted_field(
                run, field_key, raw, normalized_value=normalised, confidence=0.94
            )
        return run

    return _label


@pytest.fixture
def declare(db):
    def _declare(product: Product, code: str, answer: str, note: str = ""):
        return ProductApplicabilityDeclaration.objects.create(
            product=product,
            condition=ApplicabilityCondition.objects.get(code=code),
            answer=answer,
            note=note,
        )

    return _declare


def finding_for(check: ComplianceCheck, rule_code: str) -> ComplianceFinding:
    return check.findings.get(rule_code=rule_code)


#: A realistic Indian retail food label carrying the declarations the active
#: rules ask for. `500 g` is normalised the way `labelextract` normalises it.
COMPLIANT_FOOD_LABEL = {
    "net_quantity": (
        "Net Wt. 500 g",
        {
            "quantity": 500,
            "unit": "g",
            "measure": "mass",
            "base_quantity": 500,
            "base_unit": "g",
            "uncertain": False,
        },
    ),
    "retail_sale_price": (
        "MRP Rs. 120.00 (incl. of all taxes)",
        {"amount": "120.00", "currency": "INR", "uncertain": False},
    ),
    "consumer_care_contact": "Consumer care: care@bharatfoods.example, 1800-000-000",
}


# ---------------------------------------------------------------------------
# Applicability drives evaluation
# ---------------------------------------------------------------------------


def test_a_package_out_of_scope_under_rule_3_is_not_judged(
    product, label, declare
):
    """A consignment for an institutional consumer is outside Chapter II.

    Every rule is recorded NOT_APPLICABLE, and - critically - the overall
    result is REVIEW_REQUIRED, not COMPLIANT. Nothing about the declarations
    was examined, and a set of exemptions is not a clean bill of health.
    """
    declare(product, "institutional-consumer", Answer.YES, "Bulk supply to a hospital.")

    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    assert check.result == Result.REVIEW_REQUIRED
    assert check.rules_evaluated == 0
    assert check.rules_not_applicable > 0
    assert all(f.status == Status.NOT_APPLICABLE for f in check.findings.all())
    assert "rule 3" in finding_for(check, "LM-PC-0003").message


def test_a_ten_gram_sachet_is_exempt_under_rule_26(product, label, declare):
    """Rule 26(a): nothing in the Rules applies to a package of ten gram or less."""
    declare(product, "quantity-10g-10ml-or-less", Answer.YES)

    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    assert check.result == Result.REVIEW_REQUIRED
    assert check.rules_not_applicable > 0
    assert "rule 26" in finding_for(check, "LM-PC-0003").message


def test_a_ten_gram_tobacco_sachet_is_not_exempt(product, label, declare):
    """The proviso inserted by G.S.R. 385(E): clause (a) does not reach tobacco.

    The contrast with the test above, and the reason
    `WITHHOLDS_EXEMPTION` exists as a mode of its own.
    """
    declare(product, "quantity-10g-10ml-or-less", Answer.YES)
    declare(product, "tobacco-product", Answer.YES)

    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    assert finding_for(check, "LM-PC-0003").status == Status.PASSED
    assert check.rules_evaluated > 0


def test_an_undeclared_package_is_still_evaluated_with_the_caveat_recorded(
    product, label
):
    """The default path, and the one the prototype depends on.

    Nothing is declared. Refusing to evaluate would make the system useless for
    the ordinary retail package that is most of its input, so the rules run and
    the uncertainty is carried on every finding instead.
    """
    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    assert check.rules_not_applicable == 0
    net_quantity = finding_for(check, "LM-PC-0003")
    assert net_quantity.status == Status.PASSED
    assert "rule 3 and rule 26" in net_quantity.applicability_note


# ---------------------------------------------------------------------------
# Rule 6
# ---------------------------------------------------------------------------


def test_a_complete_food_label_meets_every_rule_that_applies(product, label):
    """No violations, and the result is REVIEW_REQUIRED rather than COMPLIANT.

    Two clauses remain undetermined because nothing declares the facts they
    turn on - whether the package is imported (6(1)(aa)) and whether proviso
    (C) excuses the price declaration (6(1)(e)). Declaring those is what earns
    a clean result, which is exactly the incentive intended.
    """
    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    assert check.violations.count() == 0
    assert check.rules_failed == 0
    assert finding_for(check, "LM-PC-0003").status == Status.PASSED
    assert finding_for(check, "LM-PC-0006").status == Status.PASSED
    assert check.result == Result.REVIEW_REQUIRED


def test_a_fully_declared_compliant_package_reaches_compliant(
    product, label, declare
):
    """The clean path, and the only route to COMPLIANT.

    With import status and the price provisos declared, every applicable rule
    is decided and every one passes.
    """
    declare(product, "imported-product", Answer.NO)
    for code in ("bidi", "domestic-lpg-cylinder", "alcoholic-beverage"):
        declare(product, code, Answer.NO)

    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    assert check.result == Result.COMPLIANT
    assert check.rules_failed == 0
    assert check.rules_inconclusive == 0
    assert check.rules_passed >= 4


def test_a_missing_net_quantity_is_a_violation(product, label, declare):
    declare(product, "imported-product", Answer.NO)
    label_without = {
        k: v for k, v in COMPLIANT_FOOD_LABEL.items() if k != "net_quantity"
    }

    check = engine.evaluate(label(**label_without))

    finding = finding_for(check, "LM-PC-0003")
    assert finding.status == Status.FAILED
    assert finding.violation is not None
    assert finding.clause == "6(1)(c)"
    assert finding.legal_reference.startswith("Rule 6(1)(c)")


def test_a_missing_retail_sale_price_is_a_violation_once_the_provisos_are_answered(
    product, label, declare
):
    """Rule 6(1)(e) can only fail a package once its exemptions are excluded."""
    for code in ("bidi", "domestic-lpg-cylinder", "alcoholic-beverage"):
        declare(product, code, Answer.NO)
    label_without = {
        k: v for k, v in COMPLIANT_FOOD_LABEL.items() if k != "retail_sale_price"
    }

    check = engine.evaluate(label(**label_without))

    finding = finding_for(check, "LM-PC-0005")
    assert finding.status == Status.FAILED
    assert finding.clause == "6(1)(e)"


def test_an_unanswered_proviso_sends_the_price_rule_to_review_not_to_violation(
    product, label
):
    """The safeguard. A package that might be bidi is not called unlawful."""
    label_without = {
        k: v for k, v in COMPLIANT_FOOD_LABEL.items() if k != "retail_sale_price"
    }

    check = engine.evaluate(label(**label_without))

    finding = finding_for(check, "LM-PC-0005")
    assert finding.status == Status.INCONCLUSIVE
    assert finding.violation is None


def test_a_missing_consumer_care_contact_is_a_violation(product, label):
    label_without = {
        k: v for k, v in COMPLIANT_FOOD_LABEL.items() if k != "consumer_care_contact"
    }

    check = engine.evaluate(label(**label_without))

    finding = finding_for(check, "LM-PC-0006")
    assert finding.status == Status.FAILED
    assert finding.clause == "6(2)"


def test_an_imported_package_must_declare_its_country_of_origin(
    product, label, declare
):
    """Rule 6(1)(aa), which applicability is what unblocked."""
    declare(product, "imported-product", Answer.YES, "Imported from Malaysia.")

    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    finding = finding_for(check, "LM-PC-0007")
    assert finding.status == Status.FAILED
    assert finding.clause == "6(1)(aa)"
    assert finding.violation is not None


def test_an_imported_package_declaring_country_of_origin_passes(
    product, label, declare
):
    declare(product, "imported-product", Answer.YES)

    check = engine.evaluate(
        label(**COMPLIANT_FOOD_LABEL, country_of_origin="Country of origin: Malaysia")
    )

    assert finding_for(check, "LM-PC-0007").status == Status.PASSED


def test_a_domestic_package_owes_no_country_of_origin(product, label, declare):
    """The clause binds imported products only. A domestic package is
    NOT_APPLICABLE - not passed, because nothing was examined."""
    declare(product, "imported-product", Answer.NO)

    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    finding = finding_for(check, "LM-PC-0007")
    assert finding.status == Status.NOT_APPLICABLE
    assert finding.violation is None
    assert "applies only to" in finding.message


def test_import_status_is_never_inferred_from_the_importer_name(product, label):
    """The self-fulfilling inference `rules/INVENTORY.md` warns against.

    An importer name on the label does NOT make the package imported for
    applicability purposes: a package omitting both would then look exempt from
    a declaration it owes.
    """
    check = engine.evaluate(
        label(**COMPLIANT_FOOD_LABEL, importer_name="Acme Imports Pvt Ltd")
    )

    finding = finding_for(check, "LM-PC-0007")
    assert finding.status == Status.INCONCLUSIVE
    assert "Imported product" in finding.message


def test_the_food_carve_out_keeps_rule_6_1_a_off_a_food_product(product, label):
    """Explanation III defers to the Food Safety and Standards Act, 2006.

    `product` is in `packaged-food`, so LM-PC-0001 is not even selected.
    """
    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    assert not check.findings.filter(rule_code="LM-PC-0001").exists()


# ---------------------------------------------------------------------------
# Rules 7-13
# ---------------------------------------------------------------------------


def test_a_net_quantity_in_grams_satisfies_rule_13_5(product, label):
    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    finding = finding_for(check, "LM-PC-0008")
    assert finding.status == Status.PASSED
    assert finding.clause == "13(5)"


def test_a_net_quantity_in_ounces_violates_rule_13_5(product, label):
    check = engine.evaluate(
        label(
            net_quantity=(
                "Net Wt. 8 oz",
                {"quantity": 8, "unit": "oz", "uncertain": True},
            )
        )
    )

    finding = finding_for(check, "LM-PC-0008")
    assert finding.status == Status.FAILED
    assert "International System of Units" in finding.message


def test_an_unrecognisable_unit_is_reviewed_not_failed(product, label):
    """An OCR defect must not become a legal finding."""
    check = engine.evaluate(
        label(
            net_quantity=(
                "Net Wt. 500 9",
                {"quantity": 500, "unit": "9", "uncertain": True},
            )
        )
    )

    finding = finding_for(check, "LM-PC-0008")
    assert finding.status == Status.INCONCLUSIVE
    assert finding.violation is None


def test_a_dozen_declaration_violates_rule_13_4(product, label):
    check = engine.evaluate(
        label(net_quantity=("1 dozen", {"quantity": 1, "unit": "dozen"}))
    )

    finding = finding_for(check, "LM-PC-0009")
    assert finding.status == Status.FAILED
    assert finding.clause == "13(4)"


def test_a_missing_quantity_leaves_the_rule_13_checks_inconclusive(
    product, label
):
    """Whether a quantity is required at all is rule 6(1)(c)'s finding.

    Rule 13 governs how a quantity is expressed, so with none read it has
    nothing to say - and must not report a pass.
    """
    check = engine.evaluate(
        label(consumer_care_contact="care@bharatfoods.example")
    )

    for code in ("LM-PC-0008", "LM-PC-0009"):
        assert finding_for(check, code).status == Status.INCONCLUSIVE


def test_rules_7_and_8_are_not_evaluated_at_all(product, label):
    """No PDP geometry, no millimetre scale, so no font-size or placement check.

    The requirements are on record in the framework as
    IMPLEMENTABLE_WITH_NEW_CHECK; what must NOT exist is an executable rule
    claiming to decide them from a photograph.
    """
    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    clauses = {f.clause for f in check.findings.all()}
    assert "7" not in clauses
    assert "8(1)" not in clauses


# ---------------------------------------------------------------------------
# Limits: what an image cannot establish
# ---------------------------------------------------------------------------


def test_no_rule_claims_to_measure_the_physical_quantity(product, label):
    """Rule 22 is the case that matters.

    A label reading of '500 g' is not a weighing, and no active rule may claim
    otherwise. The clause exists in the framework with a physical_inspection
    detection method and no evaluator.
    """
    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    assert not check.findings.filter(clause="22").exists()
    for finding in check.findings.all():
        assert finding.detection_method in {"ocr", "ocr_cv", "cv", ""}


def test_an_unreadable_photograph_produces_no_violation(shipped, empty_run):
    """The oldest guarantee in the engine, re-checked with eight rules active."""
    check = engine.evaluate(empty_run)

    assert check.result == Result.REVIEW_REQUIRED
    assert check.violations.count() == 0


def test_findings_preserve_the_raw_reading_and_its_normalised_form(
    product, label
):
    """Normalisation is an interpretation; the original must survive it."""
    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    finding = finding_for(check, "LM-PC-0003")
    assert finding.extracted_raw_value == "Net Wt. 500 g"
    assert finding.extracted_normalized_value["unit"] == "g"
    assert finding.extracted_confidence == pytest.approx(0.94)


def test_a_not_applicable_finding_is_never_counted_as_a_pass(
    product, label, declare
):
    """The arithmetic that stops exemptions reading as compliance."""
    declare(product, "imported-product", Answer.NO)

    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    not_applicable = check.findings.filter(status=Status.NOT_APPLICABLE)
    assert not_applicable.exists()
    assert check.rules_not_applicable == not_applicable.count()
    assert check.rules_passed == check.findings.filter(status=Status.PASSED).count()
    assert check.rules_evaluated == (
        check.rules_passed + check.rules_failed + check.rules_inconclusive
    )
