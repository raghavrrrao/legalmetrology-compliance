"""The applicability resolver: does this clause govern this package?

Step 1 recorded applicability as data. These tests cover the module that makes
it decide something, and almost all of them exist to pin one property:

    **An unestablished fact never produces a verdict.**

A condition nobody answered is UNKNOWN, and a clause turning on an UNKNOWN
condition is UNDETERMINED - not applied, not excused. Every branch below either
demonstrates that or demonstrates the contrast case, so the property cannot
pass vacuously.
"""

from __future__ import annotations

import pytest

from apps.catalog.models import Product, ProductApplicabilityDeclaration
from apps.compliance.services.applicability import (
    Applicability,
    DeclarationSet,
    decide,
    decide_scope,
)
from apps.rules.models import (
    ApplicabilityCondition,
    AutomationClass,
    DetectionMethod,
    ImplementationStatus,
    LegalRule,
    RequirementApplicability,
    RuleRequirement,
)

pytestmark = pytest.mark.django_db

Answer = ProductApplicabilityDeclaration.Answer
Determination = ApplicabilityCondition.Determination
Mode = RequirementApplicability.Mode


@pytest.fixture
def legal_rule(db) -> LegalRule:
    return LegalRule.objects.create(
        rule_number="6",
        sort_key=LegalRule.build_sort_key("6"),
        title="Declarations to be made on every package",
        automation_class=AutomationClass.PARTIALLY_AUTOMATABLE,
    )


@pytest.fixture
def make_requirement(db, legal_rule):
    def _make(clause: str, **kwargs) -> RuleRequirement:
        return RuleRequirement.objects.create(
            rule=kwargs.pop("rule", legal_rule),
            clause=clause,
            title=f"Requirement {clause}",
            requirement="A test requirement.",
            detection_method=DetectionMethod.OCR,
            automation_class=AutomationClass.IMAGE_AUTOMATABLE,
            implementation_status=ImplementationStatus.IMPLEMENTABLE_NOW,
            **kwargs,
        )

    return _make


@pytest.fixture
def make_condition(db):
    def _make(code: str, determination=Determination.USER_DECLARED, **kwargs):
        return ApplicabilityCondition.objects.create(
            code=code,
            name=kwargs.pop("name", code.replace("-", " ").capitalize()),
            determination=determination,
            **kwargs,
        )

    return _make


@pytest.fixture
def link(db):
    def _link(requirement, condition, mode, note=""):
        return RequirementApplicability.objects.create(
            requirement=requirement, condition=condition, mode=mode, note=note
        )

    return _link


@pytest.fixture
def declare(db):
    def _declare(product, condition, answer, note=""):
        return ProductApplicabilityDeclaration.objects.create(
            product=product, condition=condition, answer=answer, note=note
        )

    return _declare


# ---------------------------------------------------------------------------
# 1-3. Applicable, not applicable, uncertain
# ---------------------------------------------------------------------------


def test_a_clause_with_no_conditions_applies_to_every_package_in_scope(
    product, make_requirement
):
    """Rule 6(1)(c) has no carve-out. Absence of conditions is not doubt."""
    decision = decide(make_requirement("6(1)(c)"), DeclarationSet(product))

    assert decision.applicability is Applicability.APPLIES
    assert "no applicability conditions" in decision.explain()


def test_a_declared_trigger_makes_the_clause_apply(
    product, make_requirement, make_condition, link, declare
):
    requirement = make_requirement("6(1)(aa)")
    imported = make_condition("imported-product", name="Imported product")
    link(requirement, imported, Mode.REQUIRES)
    declare(product, imported, Answer.YES)

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.APPLIES
    assert "Imported product" in decision.explain()


def test_a_trigger_declared_absent_makes_the_clause_not_apply(
    product, make_requirement, make_condition, link, declare
):
    """A package declared domestic does not owe a country of origin."""
    requirement = make_requirement("6(1)(aa)")
    imported = make_condition("imported-product", name="Imported product")
    link(requirement, imported, Mode.REQUIRES)
    declare(product, imported, Answer.NO)

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.DOES_NOT_APPLY
    assert "applies only to" in decision.explain()


def test_an_unanswered_trigger_is_undetermined_not_assumed_either_way(
    product, make_requirement, make_condition, link
):
    """THE central test of this module.

    Nothing is declared. The clause is not applied - which would fail a
    domestic package for a declaration it never owed - and not excused - which
    would let an imported one off a declaration it does owe.
    """
    requirement = make_requirement("6(1)(aa)")
    imported = make_condition("imported-product", name="Imported product")
    link(requirement, imported, Mode.REQUIRES)

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.UNDETERMINED
    assert decision.unresolved == ["imported-product"]
    assert "not established" in decision.explain()


def test_an_explicit_unknown_is_treated_as_unanswered(
    product, make_requirement, make_condition, link, declare
):
    """Being asked and not knowing is the same as not being asked.

    Both mean the fact is not established. A row recording UNKNOWN exists so a
    reviewer can see the question was put, not so it can count as an answer.
    """
    requirement = make_requirement("6(1)(aa)")
    imported = make_condition("imported-product", name="Imported product")
    link(requirement, imported, Mode.REQUIRES)
    declare(product, imported, Answer.UNKNOWN)

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.UNDETERMINED


# ---------------------------------------------------------------------------
# 4-8. Exemptions, categories, special categories
# ---------------------------------------------------------------------------


def test_a_declared_exemption_excuses_the_clause(
    product, make_requirement, make_condition, link, declare
):
    """Proviso (C) to rule 6(1): a package containing bidi owes no retail price."""
    requirement = make_requirement("6(1)(e)")
    bidi = make_condition("bidi", name="Package containing bidi")
    link(requirement, bidi, Mode.EXEMPTS, note="Proviso (C)(i).")
    declare(product, bidi, Answer.YES)

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.DOES_NOT_APPLY
    assert "Package containing bidi" in decision.explain()
    assert "Proviso (C)(i)." in decision.explain()


def test_an_unanswered_exemption_is_undetermined(
    product, make_requirement, make_condition, link
):
    """Nobody said whether this is bidi, so the clause cannot be applied.

    The conservative direction: an exemption that might hold must not be
    steamrollered into a violation.
    """
    requirement = make_requirement("6(1)(e)")
    link(requirement, make_condition("bidi", name="Bidi"), Mode.EXEMPTS)

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.UNDETERMINED
    assert decision.unresolved == ["bidi"]


def test_an_exemption_declared_absent_leaves_the_clause_applying(
    product, make_requirement, make_condition, link, declare
):
    requirement = make_requirement("6(1)(e)")
    bidi = make_condition("bidi", name="Bidi")
    link(requirement, bidi, Mode.EXEMPTS)
    declare(product, bidi, Answer.NO)

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.APPLIES


def test_a_category_derived_condition_needs_no_declaration(
    product, make_requirement, make_condition, link
):
    """`product` is in `packaged-food`, so the food carve-out answers itself.

    The one determination that does not depend on anybody stating anything.
    """
    requirement = make_requirement("6(1)(a)")
    food = make_condition(
        "food-article",
        determination=Determination.PRODUCT_CATEGORY,
        name="Food article",
        category_code="packaged-food",
    )
    link(requirement, food, Mode.EXEMPTS, note="Explanation III.")

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.DOES_NOT_APPLY
    assert "Food article" in decision.explain()


def test_a_category_that_is_known_answers_no_rather_than_unknown(
    product, make_requirement, make_condition, link
):
    """A known category is positive evidence in both directions.

    `product` is food, so a condition keyed on non-food resolves NO - not
    UNKNOWN. Treating it as unknown would send every food product to review
    over a carve-out that plainly does not reach it.
    """
    requirement = make_requirement("6(1)(a)")
    non_food = make_condition(
        "non-food-article",
        determination=Determination.PRODUCT_CATEGORY,
        name="Non-food article",
        category_code="packaged-non-food",
    )
    link(requirement, non_food, Mode.EXEMPTS)

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.APPLIES


def test_a_product_with_no_category_leaves_a_category_condition_unknown(
    db, make_requirement, make_condition, link
):
    requirement = make_requirement("6(1)(a)")
    food = make_condition(
        "food-article",
        determination=Determination.PRODUCT_CATEGORY,
        name="Food article",
        category_code="packaged-food",
    )
    link(requirement, food, Mode.EXEMPTS)
    uncategorised = Product.objects.create(name="Unknown commodity")

    decision = decide(requirement, DeclarationSet(uncategorised))

    assert decision.applicability is Applicability.UNDETERMINED


def test_a_declaration_overrides_the_category(
    product, make_requirement, make_condition, link, declare
):
    """A reviewer correcting a miscategorised submission must win.

    The taxonomy records how a submission was filed, not an adjudication of
    what is in the package.
    """
    requirement = make_requirement("6(1)(a)")
    food = make_condition(
        "food-article",
        determination=Determination.PRODUCT_CATEGORY,
        name="Food article",
        category_code="packaged-food",
    )
    link(requirement, food, Mode.EXEMPTS)
    declare(product, food, Answer.NO, note="Reviewed: this is a cleaning product.")

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.APPLIES


def test_a_not_determinable_condition_stays_unknown_even_when_declared(
    product, make_requirement, make_condition, link, declare
):
    """The framework's judgement outranks a submitter's claim.

    Rule 33 is the case this protects. There is no register of relaxations
    available here, so a submitter asserting one must not switch off a check -
    it sends the clause to review instead, which is where such a claim belongs.
    """
    requirement = make_requirement("33")
    relaxation = make_condition(
        "rule-33-relaxation-granted",
        determination=Determination.NOT_DETERMINABLE,
        name="Relaxation granted under rule 33",
    )
    link(requirement, relaxation, Mode.SCOPE_GATE)
    declare(product, relaxation, Answer.YES, note="We were granted one, honest.")

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.UNDETERMINED


# ---------------------------------------------------------------------------
# Ordering of the modes
# ---------------------------------------------------------------------------


def test_a_proviso_withholding_an_exemption_beats_the_scope_gate(
    product, make_requirement, make_condition, link, declare
):
    """Rule 26(a) exempts a ten-gram package - but not tobacco.

    Both conditions hold. The proviso must win, or a 5 g tobacco sachet would
    be excused by the very clause that names it as an exception.
    """
    requirement = make_requirement("26")
    tiny = make_condition("quantity-10g-10ml-or-less", name="Ten gram or less")
    tobacco = make_condition("tobacco-product", name="Tobacco product")
    link(requirement, tiny, Mode.SCOPE_GATE)
    link(requirement, tobacco, Mode.WITHHOLDS_EXEMPTION, note="Proviso to clause (a).")
    declare(product, tiny, Answer.YES)
    declare(product, tobacco, Answer.YES)

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.APPLIES
    assert "withheld" in decision.explain()


def test_the_scope_gate_holds_when_no_proviso_withholds_it(
    product, make_requirement, make_condition, link, declare
):
    """The contrast: a ten-gram package that is not tobacco is exempt."""
    requirement = make_requirement("26")
    tiny = make_condition("quantity-10g-10ml-or-less", name="Ten gram or less")
    tobacco = make_condition("tobacco-product", name="Tobacco product")
    link(requirement, tiny, Mode.SCOPE_GATE)
    link(requirement, tobacco, Mode.WITHHOLDS_EXEMPTION)
    declare(product, tiny, Answer.YES)
    declare(product, tobacco, Answer.NO)

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.DOES_NOT_APPLY


def test_an_unanswered_proviso_blocks_the_gate_from_firing(
    product, make_requirement, make_condition, link, declare
):
    """A gate must not be applied while the exception to it is unknown.

    Declaring a package tiny while nobody says whether it is tobacco cannot
    exempt it: the answer decides whether the exemption exists at all.
    """
    requirement = make_requirement("26")
    tiny = make_condition("quantity-10g-10ml-or-less", name="Ten gram or less")
    tobacco = make_condition("tobacco-product", name="Tobacco product")
    link(requirement, tiny, Mode.SCOPE_GATE)
    link(requirement, tobacco, Mode.WITHHOLDS_EXEMPTION)
    declare(product, tiny, Answer.YES)

    decision = decide(requirement, DeclarationSet(product))

    assert decision.applicability is Applicability.UNDETERMINED
    assert decision.unresolved == ["tobacco-product"]


def test_an_unmapped_rule_applies_and_says_so(product):
    """A rule with no clause must still be evaluated.

    The executable rules predate the framework, and refusing to evaluate an
    unmapped one would silently disable them.
    """
    decision = decide(None, DeclarationSet(product))

    assert decision.applicability is Applicability.APPLIES
    assert "not mapped to a clause" in decision.explain()


# ---------------------------------------------------------------------------
# Rules 3 and 26 as global scope gates
# ---------------------------------------------------------------------------


def test_scope_is_open_when_no_gate_is_declared(product, db):
    """The default, and the behaviour the prototype depends on.

    Nothing is declared about an ordinary submission, and refusing to evaluate
    it would make the system useless for its main input. The uncertainty is
    carried as a caveat on each finding instead.
    """
    decision = decide_scope(DeclarationSet(product))

    assert decision.applicability is Applicability.APPLIES
    assert "No scope gate" in decision.explain()


def test_a_declared_rule_3_gate_takes_the_package_out_of_scope(
    product, make_requirement, make_condition, link, declare
):
    """Rule 3(c): a package meant for an institutional consumer."""
    gate = make_requirement("3")
    institutional = make_condition(
        "institutional-consumer", name="Institutional consumer"
    )
    link(gate, institutional, Mode.SCOPE_GATE, note="Rule 3(c).")
    declare(product, institutional, Answer.YES)

    decision = decide_scope(DeclarationSet(product))

    assert decision.applicability is Applicability.DOES_NOT_APPLY
    assert "rule 3" in decision.explain()
    assert "Institutional consumer" in decision.explain()


def test_a_declared_rule_26_gate_takes_the_package_out_of_scope(
    product, make_requirement, make_condition, link, declare
):
    gate = make_requirement("26")
    tiny = make_condition("quantity-10g-10ml-or-less", name="Ten gram or less")
    link(gate, tiny, Mode.SCOPE_GATE, note="Rule 26(a).")
    declare(product, tiny, Answer.YES)

    decision = decide_scope(DeclarationSet(product))

    assert decision.applicability is Applicability.DOES_NOT_APPLY
    assert "rule 26" in decision.explain()


def test_the_tobacco_proviso_keeps_a_tiny_package_in_scope(
    product, make_requirement, make_condition, link, declare
):
    """The rule 26(a) proviso, at the level of the global gate."""
    gate = make_requirement("26")
    tiny = make_condition("quantity-10g-10ml-or-less", name="Ten gram or less")
    tobacco = make_condition("tobacco-product", name="Tobacco product")
    link(gate, tiny, Mode.SCOPE_GATE)
    link(gate, tobacco, Mode.WITHHOLDS_EXEMPTION)
    declare(product, tiny, Answer.YES)
    declare(product, tobacco, Answer.YES)

    decision = decide_scope(DeclarationSet(product))

    assert decision.applicability is Applicability.APPLIES


def test_an_inactive_gate_requirement_does_not_bite(
    product, make_requirement, make_condition, link, declare
):
    """Retiring a gate must actually retire it - rule 5 is the precedent."""
    gate = make_requirement("3", is_active=False)
    institutional = make_condition(
        "institutional-consumer", name="Institutional consumer"
    )
    link(gate, institutional, Mode.SCOPE_GATE)
    declare(product, institutional, Answer.YES)

    decision = decide_scope(DeclarationSet(product))

    assert decision.applicability is Applicability.APPLIES


# ---------------------------------------------------------------------------
# DeclarationSet
# ---------------------------------------------------------------------------


def test_a_declaration_set_for_no_product_answers_nothing(db, make_condition):
    """A submission with no product cannot have facts stated about it."""
    condition = make_condition("imported-product")

    assert DeclarationSet(None).answer(condition) == Answer.UNKNOWN


def test_one_product_cannot_hold_two_answers_to_one_condition(
    product, make_condition, declare
):
    """The unique constraint, which keeps a contradiction out of the record."""
    from django.db import IntegrityError, transaction

    condition = make_condition("imported-product")
    declare(product, condition, Answer.YES)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            declare(product, condition, Answer.NO)


def test_a_declaration_defaults_to_unknown(product, make_condition):
    """A row created without an answer must not assert one."""
    declaration = ProductApplicabilityDeclaration.objects.create(
        product=product, condition=make_condition("imported-product")
    )

    assert declaration.answer == Answer.UNKNOWN
    assert declaration.is_established is False
