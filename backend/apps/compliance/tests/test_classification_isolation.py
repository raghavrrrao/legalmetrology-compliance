"""The product classifier cannot move a verdict, a rule, or an applicability answer.

`docs/ml/product-classification.md` promises that the classification is an
observation beside the reading and that nothing in the decision path reads
it. These tests make that promise checkable: the same reading is evaluated
twice against the real shipped rules and legal framework - once carrying a
classification that *contradicts* the product's actual category at 0.99,
once carrying none - and every recorded outcome must be identical.

Three properties, each with its own test:

1. **Rule selection and verdict.** Same rules evaluated, same statuses, same
   violations, same counts, same result.
2. **Manual YES / NO / UNKNOWN applicability.** A stated declaration keeps
   its answer, an unstated one stays UNKNOWN, and no declaration row appears
   or changes because a classifier suggested a subcategory that shares a
   condition's code.
3. **A missing category stays missing.** A product with no category is
   evaluated as "commodity not known" however confident the classifier is.

A fourth test pins the mechanism: the engine, the applicability resolver and
the check validators never read `raw_output`, which is the only place the
classification lives.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from apps.catalog.models import (
    Product,
    ProductApplicabilityDeclaration,
    ProductCategory,
)
from apps.compliance.models import ComplianceCheck
from apps.compliance.services import applicability, engine
from apps.extraction.models import ExtractionRun
from apps.rules.framework_loader import load_framework
from apps.rules.loader import load_rules
from apps.rules.models import ApplicabilityCondition

pytestmark = pytest.mark.django_db

Answer = ProductApplicabilityDeclaration.Answer

#: A classification that disagrees with the fixture product's real category
#: (`packaged-food`) as loudly as the contract allows, and names a
#: subcategory whose code is also an applicability condition. If anything
#: downstream listened to it, this is the input that would show.
CONTRADICTING = {
    "category": "packaged-non-food",
    "subcategory": "cosmetics-and-toiletries",
    "confidence": 0.99,
    "subcategory_confidence": 0.99,
    "evidence": ["signal: soap / bathing bar (typical of cosmetics-and-toiletries)"],
    "category_scores": {"packaged-food": 0.01, "packaged-non-food": 0.99},
    "subcategory_scores": {"cosmetics-and-toiletries": 0.99, "general-food": 0.01},
    "classifier_name": "tfidf-logreg",
    "classifier_version": "0.1.0",
}

READING = (
    ("net_quantity", "Net Qty: 500 g", {"quantity": 500, "unit": "g", "uncertain": False}),
    ("retail_sale_price", "MRP Rs. 120.00 (incl. of all taxes)", {"amount": "120.00", "uncertain": False}),
    ("manufacturer_name", "Manufactured by Test Foods Pvt Ltd", None),
)


@pytest.fixture
def shipped(settings, category):
    """The real taxonomy, rules and framework, in deployment order."""
    root = ProductCategory.objects.create(code="packaged-commodity", name="Packaged commodity")
    category.parent = root
    category.save()
    ProductCategory.objects.create(code="packaged-non-food", name="Packaged non-food", parent=root)
    assert load_rules(settings.RULES_DEFINITIONS_DIR).ok
    assert load_framework(settings.RULES_FRAMEWORK_DIR).ok


@pytest.fixture
def reading(shipped, product_image, make_extracted_field):
    """Two identical completed readings of one image, differing only in
    whether the run's metadata carries a classification."""

    def _run(classification: dict | None) -> ExtractionRun:
        run = ExtractionRun.objects.create(
            image=product_image,
            engine_name="tesseract",
            engine_version="0.4.0" if classification else "0.3.0",
            status=ExtractionRun.Status.COMPLETED,
            recognised_text="\n".join(raw for _, raw, _ in READING),
            raw_output={
                "engine_raw": {},
                "metadata": {
                    "unread_declarations": [],
                    "product_classification": classification,
                    "classifier_name": "tfidf-logreg" if classification else None,
                    "classifier_version": "0.1.0" if classification else None,
                },
                "block_count": len(READING),
            },
        )
        for key, raw, normalised in READING:
            make_extracted_field(run, key, raw, normalized_value=normalised, confidence=0.9)
        return run

    return _run


def _trace(check: ComplianceCheck) -> dict:
    """Everything the engine recorded, in a comparable shape."""
    return {
        "result": check.result,
        "status": check.status,
        "counts": (
            check.rules_evaluated, check.rules_passed, check.rules_failed,
            check.rules_inconclusive, check.rules_not_applicable,
        ),
        "findings": sorted(
            (f.rule_code, f.status, f.downgraded_from_failed, f.applicability_note, f.message)
            for f in check.findings.all()
        ),
        "violations": sorted(
            (v.rule_code, v.field_key, v.message) for v in check.violations.all()
        ),
    }


def _declarations(product: Product) -> list[tuple[str, str, str]]:
    return sorted(
        (d.condition.code, d.answer, d.source)
        for d in ProductApplicabilityDeclaration.objects.filter(product=product)
    )


# --- 1. rule selection and verdict -------------------------------------------


def test_a_contradicting_classification_changes_no_rule_and_no_verdict(reading, product):
    with_classification = engine.evaluate(reading(CONTRADICTING), product=product)
    without = engine.evaluate(reading(None), product=product)

    assert _trace(with_classification) == _trace(without)
    # ...and the comparison is not vacuous: real rules ran against the reading.
    assert with_classification.rules_evaluated > 0
    assert with_classification.findings.count() > 0


def test_the_rules_selected_come_from_the_product_category_alone(reading, product):
    """`packaged-non-food` at 0.99 must not pull in the non-food-only rule."""
    rules_with = {rule.code for rule in engine.applicable_rules(product)}
    check = engine.evaluate(reading(CONTRADICTING), product=product)

    assert {f.rule_code for f in check.findings.all()} == rules_with
    assert product.category.code == "packaged-food"


# --- 2. manual YES / NO / UNKNOWN ---------------------------------------------


def test_manual_declarations_keep_their_answers_and_gain_no_new_rows(reading, product):
    conditions = {
        c.code: c for c in ApplicabilityCondition.objects.filter(
            code__in=["imported-product", "wholesale-package", "cosmetics-and-toiletries"]
        )
    }
    assert len(conditions) == 3
    ProductApplicabilityDeclaration.objects.create(
        product=product, condition=conditions["imported-product"], answer=Answer.YES
    )
    ProductApplicabilityDeclaration.objects.create(
        product=product, condition=conditions["wholesale-package"], answer=Answer.NO
    )
    # cosmetics-and-toiletries deliberately NOT declared: the classifier
    # names exactly that subcategory at 0.99 and must not answer it.
    before = _declarations(product)

    with_classification = engine.evaluate(reading(CONTRADICTING), product=product)
    without = engine.evaluate(reading(None), product=product)

    assert _trace(with_classification) == _trace(without)
    assert _declarations(product) == before
    resolved = applicability.DeclarationSet(product)
    assert resolved.answer(conditions["imported-product"]) == Answer.YES
    assert resolved.answer(conditions["wholesale-package"]) == Answer.NO
    assert resolved.answer(conditions["cosmetics-and-toiletries"]) == Answer.UNKNOWN


def test_food_article_is_answered_from_the_category_not_the_classifier(reading, product):
    """The one category-derived condition. The product is packaged-food, so
    `food-article` is YES - and stays YES when the classifier says non-food."""
    food_article = ApplicabilityCondition.objects.get(code="food-article")
    engine.evaluate(reading(CONTRADICTING), product=product)

    assert applicability.DeclarationSet(product).answer(food_article) == Answer.YES


# --- 3. a missing category stays missing -------------------------------------


def test_a_confident_classification_cannot_supply_a_missing_category(reading, product):
    product.category = None
    product.save()

    check = engine.evaluate(reading(CONTRADICTING), product=product)

    assert check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    assert check.rules_evaluated == 0
    assert check.findings.count() == 0
    product.refresh_from_db()
    assert product.category is None
    assert _trace(check) == _trace(engine.evaluate(reading(None), product=product))


# --- 4. the mechanism ---------------------------------------------------------


def test_the_decision_path_never_reads_the_run_metadata():
    """`raw_output` is the only place a classification lives. The engine, the
    applicability resolver and every registered validator must not read it,
    or a future edit could start consuming the classification without any
    test above changing - this one would."""
    backend_root = Path(__file__).resolve().parents[3]
    decision_path = [
        backend_root / "apps/compliance/services/engine.py",
        backend_root / "apps/compliance/services/applicability.py",
        backend_root / "apps/compliance/services/analysis_service.py",
        *sorted((backend_root / "apps/rules/checks").glob("*.py")),
    ]
    reads_metadata = re.compile(r"raw_output|product_classification|classifier")
    offenders = [
        path.relative_to(backend_root).as_posix()
        for path in decision_path
        if reads_metadata.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_the_declaration_set_is_built_from_the_product_only():
    """No run, no reading, no metadata reaches the resolver's constructor."""
    import inspect

    parameters = list(inspect.signature(applicability.DeclarationSet.__init__).parameters)
    assert parameters == ["self", "product"]
