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
#: rules ask for, each normalised the way `labelextract` normalises it.
#:
#: The normalised halves are not decoration. Since Step 3 three rules read the
#: structured value rather than merely noting that a field exists - the
#: consumer-care elements (rule 6(2)), whether the date resolves to a month and
#: a year (rule 6(1)(d)), and whether the price is declared exclusive of all
#: taxes (rule 6(1)(e)) - so a fixture carrying a raw string alone would be
#: testing a reading the extraction service never produces.
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
        {
            "amount": "120.00",
            "currency": "INR",
            # Written only because the label printed words the extractor
            # recognised as a tax indication. `currency` is a normaliser
            # DEFAULT and is never evidence about the package - rule 6(1)(e)'s
            # "in Indian currency" limb is not checked against it anywhere.
            "inclusive_of_all_taxes": True,
            "uncertain": False,
        },
    ),
    "consumer_care_contact": (
        "Consumer care: care@bharatfoods.example, 1800-000-000",
        {
            "emails": ["care@bharatfoods.example"],
            "phones": ["1800-000-000"],
            "uncertain": False,
        },
    ),
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


#: The provisos that must be answered NO before rule 6(1)(e) can reach a
#: verdict on a package: proviso (C) for bidi and for administered-price LPG,
#: and alcoholic beverages, where State Excise Laws provide for the
#: declaration instead.
PRICE_PROVISOS = ("bidi", "domestic-lpg-cylinder", "alcoholic-beverage")

#: The provisos and carve-outs that must be answered before rule 6(1)(d) can
#: reach a verdict on a NON-FOOD package. Food is excluded by category instead.
DATE_PROVISOS = (
    "seeds-certified",
    "cosmetics-and-toiletries",
    "bidi",
    "incense-sticks",
    "domestic-lpg-cylinder",
)


@pytest.fixture
def non_food_product(shipped, db):
    """A product in `packaged-non-food`, which rules 6(1)(a) and 6(1)(d) reach.

    The shared `product` fixture is in `packaged-food`, where both clauses
    defer to the Food Safety and Standards Act, 2006 - so a food product can
    never exercise the manufacture-date rules at all.
    """
    from apps.catalog.models import Product, ProductCategory

    return Product.objects.create(
        name="Test detergent",
        category=ProductCategory.objects.get(code="packaged-non-food"),
    )


@pytest.fixture
def non_food_label(non_food_product, png_bytes, media_root, make_extracted_field):
    """A completed reading attached to a non-food product's own image."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.images.models import ProductImage

    def _label(**declarations) -> ExtractionRun:
        image = ProductImage.objects.create(
            product=non_food_product,
            image=SimpleUploadedFile(
                "label.png", png_bytes, content_type="image/png"
            ),
            original_filename="label.png",
            content_type="image/png",
            image_format="png",
            size_bytes=len(png_bytes),
            width=64,
            height=64,
            checksum_sha256="1" * 64,
        )
        run = ExtractionRun.objects.create(
            image=image,
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


# --- rule 6(2), element by element ------------------------------------------


def test_a_consumer_care_declaration_without_an_email_names_the_missing_element(
    product, label, declare
):
    """The precision Step 3 added over the presence check.

    LM-PC-0006 passes - a consumer-care declaration was read. LM-PC-0010 fails,
    and its finding says which of the elements rule 6(2) names was not found,
    rather than reporting that the package is "not compliant".
    """
    declare(product, "imported-product", Answer.NO)
    for code in PRICE_PROVISOS:
        declare(product, code, Answer.NO)
    declarations = {
        **COMPLIANT_FOOD_LABEL,
        "consumer_care_contact": (
            "Consumer care: 1800-000-000",
            {"phones": ["1800-000-000"], "uncertain": False},
        ),
    }

    check = engine.evaluate(label(**declarations))

    assert finding_for(check, "LM-PC-0006").status == Status.PASSED
    missing = finding_for(check, "LM-PC-0010")
    assert missing.status == Status.FAILED
    assert missing.clause == "6(2)"
    assert missing.legal_reference.startswith("Rule 6(2)")
    assert "e-mail address" in missing.message
    assert missing.details["elements_not_found"] == ["e-mail address"]
    assert check.result == Result.NON_COMPLIANT


def test_the_consumer_care_finding_never_claims_the_name_and_address(
    product, label
):
    """Two of the clause's four elements are not checked, and it says so."""
    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    finding = finding_for(check, "LM-PC-0010")
    assert finding.status == Status.PASSED
    assert finding.details["elements_not_checked"] == [
        "name of the person or office to be contacted",
        "address of the person or office to be contacted",
    ]


def test_a_low_confidence_consumer_care_reading_is_reviewed_not_failed(
    product, product_image, make_extracted_field, shipped
):
    """A missing element on a reading nobody trusts is not a violation."""
    run = ExtractionRun.objects.create(
        image=product_image,
        engine_name="stub",
        engine_version="0.0.0",
        status=ExtractionRun.Status.COMPLETED,
        recognised_text="Consumer care 1800-000-000",
    )
    make_extracted_field(
        run,
        "consumer_care_contact",
        "Consumer care: 1800-000-000",
        normalized_value={"phones": ["1800-000-000"], "uncertain": False},
        confidence=0.2,
    )

    check = engine.evaluate(run)

    finding = finding_for(check, "LM-PC-0010")
    assert finding.status == Status.INCONCLUSIVE
    assert finding.violation is None


# --- rule 6(1)(d), month and year -------------------------------------------


def test_a_resolved_manufacture_date_passes_rule_6_1_d(
    non_food_product, non_food_label, declare
):
    for code in DATE_PROVISOS:
        declare(non_food_product, code, Answer.NO)

    check = engine.evaluate(
        non_food_label(
            date_of_manufacture=(
                "MFG: 12/2024",
                {"year_month": "2024-12", "uncertain": False},
            )
        )
    )

    assert finding_for(check, "LM-PC-0004").status == Status.PASSED
    resolved = finding_for(check, "LM-PC-0011")
    assert resolved.status == Status.PASSED
    assert resolved.clause == "6(1)(d)"


def test_an_ambiguous_manufacture_date_is_reviewed_not_failed(
    non_food_product, non_food_label, declare
):
    """The case the presence check cannot see.

    LM-PC-0004 passes: a date declaration was read. LM-PC-0011 cannot say the
    clause is met, because the month is 3 or 4 and the label does not say
    which - and it does not say the package is unlawful either, because an
    unusual printing and a misrecognised one look identical from here.
    """
    for code in DATE_PROVISOS:
        declare(non_food_product, code, Answer.NO)

    check = engine.evaluate(
        non_food_label(
            date_of_manufacture=(
                "MFG: 03/04/2025",
                {
                    "uncertain": True,
                    "uncertainty_reasons": [
                        "both DD/MM and MM/DD are valid readings of this date"
                    ],
                    "candidates": ["2025-04-03", "2025-03-04"],
                },
            )
        )
    )

    assert finding_for(check, "LM-PC-0004").status == Status.PASSED
    ambiguous = finding_for(check, "LM-PC-0011")
    assert ambiguous.status == Status.INCONCLUSIVE
    assert ambiguous.violation is None
    assert check.result in {Result.REVIEW_REQUIRED, Result.PARTIALLY_COMPLIANT}


def test_an_undeclared_proviso_keeps_the_date_rules_off_a_verdict(
    non_food_product, non_food_label
):
    """Nothing declares whether this is bidi, incense or a certified seed.

    Both rule 6(1)(d) rules must reach review, not a verdict - the safeguard
    Step 2 built and Step 3 must not erode.
    """
    check = engine.evaluate(non_food_label(net_quantity="500 g"))

    for code in ("LM-PC-0004", "LM-PC-0011"):
        finding = finding_for(check, code)
        assert finding.status == Status.INCONCLUSIVE
        assert finding.violation is None


def test_rule_6_1_d_is_not_evaluated_at_all_on_a_food_package(product, label):
    """The first proviso defers to the Food Safety and Standards Act, 2006."""
    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    assert not check.findings.filter(rule_code="LM-PC-0011").exists()


# --- rule 6(1)(e), the tax indication ---------------------------------------


def test_a_price_declared_exclusive_of_taxes_is_a_violation(
    product, label, declare
):
    """The one determination rule 6(1)(e) supports beyond presence."""
    declare(product, "imported-product", Answer.NO)
    for code in PRICE_PROVISOS:
        declare(product, code, Answer.NO)
    declarations = {
        **COMPLIANT_FOOD_LABEL,
        "retail_sale_price": (
            "Price Rs. 100 (excl. of all taxes)",
            {
                "amount": "100",
                "currency": "INR",
                "inclusive_of_all_taxes": False,
                "uncertain": False,
            },
        ),
    }

    check = engine.evaluate(label(**declarations))

    assert finding_for(check, "LM-PC-0005").status == Status.PASSED
    finding = finding_for(check, "LM-PC-0012")
    assert finding.status == Status.FAILED
    assert finding.clause == "6(1)(e)"
    assert finding.violation is not None


def test_a_price_with_no_tax_wording_is_not_reported_as_a_violation(
    product, label, declare
):
    """The restraint that keeps this rule defensible.

    Whether "MRP Rs. 120" alone clearly indicates a price inclusive of all
    taxes - rule 2(m) defines the retail sale price as inclusive - is a
    question of legal construction. The system records what it observed and
    does not decide it.
    """
    declare(product, "imported-product", Answer.NO)
    for code in PRICE_PROVISOS:
        declare(product, code, Answer.NO)
    declarations = {
        **COMPLIANT_FOOD_LABEL,
        "retail_sale_price": (
            "MRP Rs. 120",
            {"amount": "120", "currency": "INR", "uncertain": False},
        ),
    }

    check = engine.evaluate(label(**declarations))

    finding = finding_for(check, "LM-PC-0012")
    assert finding.status == Status.PASSED
    assert finding.details["tax_indication_observed"] == "not_observed"
    assert check.result == Result.COMPLIANT


def test_an_unanswered_price_proviso_reaches_review_for_the_tax_rule_too(
    product, label
):
    """Applicability gates the new rule exactly as it gates the presence one."""
    declarations = {
        **COMPLIANT_FOOD_LABEL,
        "retail_sale_price": (
            "Price Rs. 100 (excl. of all taxes)",
            {
                "amount": "100",
                "inclusive_of_all_taxes": False,
                "uncertain": False,
            },
        ),
    }

    check = engine.evaluate(label(**declarations))

    finding = finding_for(check, "LM-PC-0012")
    assert finding.status == Status.INCONCLUSIVE
    assert finding.violation is None
    assert "could not be determined" in finding.applicability_note
    assert "were not established for this package" in finding.applicability_note


def test_a_bidi_package_is_not_judged_on_its_price_by_either_rule(
    product, label, declare
):
    """Proviso (C) excuses bidi from the retail sale price declaration.

    NOT_APPLICABLE, not passed: nothing about the price was examined.
    """
    declare(product, "bidi", Answer.YES, "Declared as a package of bidi.")

    check = engine.evaluate(label(**COMPLIANT_FOOD_LABEL))

    for code in ("LM-PC-0005", "LM-PC-0012"):
        finding = finding_for(check, code)
        assert finding.status == Status.NOT_APPLICABLE
        assert finding.violation is None


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
