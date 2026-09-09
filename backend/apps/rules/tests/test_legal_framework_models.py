"""Invariants of the legal-framework layer.

These test the four things the framework exists to guarantee, none of which the
executable `ComplianceRule` could express:

1. A clause can be **versioned**, so an amendment adds a record instead of
   overwriting one.
2. An **effective window** decides which version speaks for a date.
3. Applicability is **honest about what it cannot establish**, so a requirement
   gated on an unknowable fact can never be auto-decided.
4. A requirement records **how it could be evaluated at all**, so a physical or
   administrative obligation is not mistaken for one a photograph settles.
"""

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.rules.models import (
    ApplicabilityCondition,
    AutomationClass,
    ComplianceRule,
    DetectionMethod,
    ImplementationStatus,
    LegalInstrument,
    LegalRule,
    RequirementApplicability,
    RuleRequirement,
    VerificationStatus,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def legal_rule(db) -> LegalRule:
    return LegalRule.objects.create(
        rule_number="6",
        sort_key=LegalRule.build_sort_key("6"),
        title="Declarations to be made on every package",
        chapter="Chapter II - Packages intended for retail sale",
        automation_class=AutomationClass.PARTIALLY_AUTOMATABLE,
        verification_status=VerificationStatus.VERIFIED,
    )


@pytest.fixture
def make_requirement(db, legal_rule):
    """Factory for requirements. Defaults to a verified OCR presence clause."""

    def _make(clause: str = "6(1)(c)", *, version: int = 1, **kwargs) -> RuleRequirement:
        defaults = {
            "rule": legal_rule,
            "clause": clause,
            "version": version,
            "title": kwargs.pop("title", f"Requirement {clause}"),
            "requirement": kwargs.pop("requirement", "A test requirement."),
            "detection_method": kwargs.pop("detection_method", DetectionMethod.OCR),
            "automation_class": kwargs.pop(
                "automation_class", AutomationClass.IMAGE_AUTOMATABLE
            ),
            "implementation_status": kwargs.pop(
                "implementation_status", ImplementationStatus.IMPLEMENTABLE_NOW
            ),
            "verification_status": kwargs.pop(
                "verification_status", VerificationStatus.VERIFIED
            ),
            "source_note": kwargs.pop("source_note", "Fixture requirement."),
        }
        defaults.update(kwargs)
        return RuleRequirement.objects.create(**defaults)

    return _make


@pytest.fixture
def make_condition(db):
    def _make(code: str, determination: str, **kwargs) -> ApplicabilityCondition:
        return ApplicabilityCondition.objects.create(
            code=code,
            name=kwargs.pop("name", code.replace("-", " ").title()),
            determination=determination,
            **kwargs,
        )

    return _make


# ---------------------------------------------------------------------------
# Rules and requirements exist, and relate to each other
# ---------------------------------------------------------------------------


def test_a_requirement_belongs_to_its_rule_and_is_reachable_from_it(
    legal_rule, make_requirement
):
    """The Rule -> Requirement relation both ways round.

    Reading a clause must give the rule it sits in, and reading a rule must
    give every clause recorded under it - that is what makes "what does rule 6
    require?" answerable as a query rather than by grepping a document.
    """
    net_quantity = make_requirement("6(1)(c)")
    consumer_care = make_requirement("6(2)")

    assert net_quantity.rule == legal_rule
    assert set(legal_rule.requirements.values_list("clause", flat=True)) == {
        "6(1)(c)",
        "6(2)",
    }
    assert consumer_care.rule_id == legal_rule.pk


def test_rules_sort_by_number_not_alphabetically(db):
    """Rule 10 must not sort before rule 2, and 32-A must fall between 32 and 33.

    The reason `sort_key` exists at all. A framework listed in the wrong order
    is one a reviewer cannot check against the Rules as printed.
    """
    for number in ["2", "10", "33", "32A", "32", "6"]:
        LegalRule.objects.create(
            rule_number=number,
            sort_key=LegalRule.build_sort_key(number),
            title=f"Rule {number}",
            automation_class=AutomationClass.MANUAL_REVIEW,
        )

    assert list(LegalRule.objects.values_list("rule_number", flat=True)) == [
        "2",
        "6",
        "10",
        "32",
        "32A",
        "33",
    ]


def test_build_sort_key_rejects_a_number_with_no_digits():
    with pytest.raises(ValueError):
        LegalRule.build_sort_key("A")


# ---------------------------------------------------------------------------
# Versioning: amendments add rows, they do not overwrite them
# ---------------------------------------------------------------------------


def test_two_versions_of_one_clause_coexist_and_link(make_requirement, db):
    """The central guarantee of the framework.

    An amendment must leave the earlier text readable. If version 2 replaced
    version 1 in place, a finding recorded under the old text would silently
    start citing the new one.
    """
    inserted = LegalInstrument.objects.create(
        citation="G.S.R. 128(E)", instrument_type=LegalInstrument.InstrumentType.AMENDMENT
    )
    substituted = LegalInstrument.objects.create(
        citation="G.S.R. 312(E)", instrument_type=LegalInstrument.InstrumentType.AMENDMENT
    )

    version_one = make_requirement(
        "6(10A)",
        version=1,
        source=inserted,
        effective_from=date(2026, 7, 1),
        detection_method=DetectionMethod.DIGITAL_ECOMMERCE,
        automation_class=AutomationClass.DIGITAL_ECOMMERCE,
    )
    version_two = make_requirement(
        "6(10A)",
        version=2,
        supersedes=version_one,
        source=substituted,
        effective_from=date(2027, 7, 1),
        detection_method=DetectionMethod.DIGITAL_ECOMMERCE,
        automation_class=AutomationClass.DIGITAL_ECOMMERCE,
    )

    both = RuleRequirement.objects.filter(clause="6(10A)")
    assert both.count() == 2, "the amendment overwrote the earlier version"
    assert version_two.supersedes == version_one
    assert list(version_one.superseded_by.all()) == [version_two]
    # Each version keeps its own instrument: which amendment a finding rested
    # on must stay recoverable after a later one supersedes it.
    assert version_one.source.citation == "G.S.R. 128(E)"
    assert version_two.source.citation == "G.S.R. 312(E)"


def test_the_same_clause_and_version_cannot_be_recorded_twice(make_requirement):
    """Two rows for one version would make "the text as amended" ambiguous."""
    make_requirement("6(1)(c)", version=1)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_requirement("6(1)(c)", version=1, title="A conflicting duplicate")


def test_a_requirement_cannot_supersede_itself(make_requirement):
    requirement = make_requirement("6(1)(c)")
    requirement.supersedes = requirement

    with pytest.raises(ValidationError) as exc:
        requirement.full_clean(exclude=["applicability_conditions"])

    assert "supersedes" in exc.value.message_dict


# ---------------------------------------------------------------------------
# Effective dates
# ---------------------------------------------------------------------------


def test_effective_window_selects_the_version_in_force_on_a_date(make_requirement):
    """A dated question gets a dated answer.

    Version 1 runs from 1 July 2026 with no stated end; version 2 from 1 July
    2027. Before either date nothing is in force; between them only version 1.
    """
    version_one = make_requirement(
        "6(10A)", version=1, effective_from=date(2026, 7, 1)
    )
    version_two = make_requirement(
        "6(10A)", version=2, supersedes=version_one, effective_from=date(2027, 7, 1)
    )

    assert version_one.is_in_force_on(date(2026, 6, 30)) is False
    assert version_one.is_in_force_on(date(2026, 7, 1)) is True
    assert version_two.is_in_force_on(date(2026, 7, 1)) is False
    assert version_two.is_in_force_on(date(2027, 7, 1)) is True


def test_a_closed_effective_window_stops_applying_after_its_end(make_requirement):
    """Rule 5 is the real case: omitted, and on record with an end date."""
    omitted = make_requirement(
        "5",
        effective_from=date(2011, 4, 1),
        effective_to=date(2022, 9, 30),
        is_active=False,
    )

    assert omitted.is_in_force_on(date(2022, 9, 30)) is True
    assert omitted.is_in_force_on(date(2022, 10, 1)) is False


def test_a_null_effective_from_means_as_far_back_as_we_model(make_requirement):
    """A missing start date must not silently mean "not yet in force"."""
    requirement = make_requirement("6(1)(b)", effective_from=None)

    assert requirement.is_in_force_on(date(2011, 4, 1)) is True


def test_reversed_effective_dates_are_rejected(make_requirement):
    requirement = make_requirement("6(1)(c)")
    requirement.effective_from = date(2020, 1, 1)
    requirement.effective_to = date(2019, 1, 1)

    with pytest.raises(ValidationError) as exc:
        requirement.full_clean(exclude=["applicability_conditions"])

    assert "effective_to" in exc.value.message_dict


# ---------------------------------------------------------------------------
# Applicability
# ---------------------------------------------------------------------------


def test_applicability_links_record_which_way_round_a_condition_bites(
    make_requirement, make_condition
):
    """REQUIRES and EXEMPTS are opposite claims and must not be collapsed.

    Rule 6(1)(a) is the real case: it is *triggered* for an imported package
    and *disapplied* for a food article. A bare many-to-many would record that
    both conditions are relevant and lose the difference between requiring a
    declaration and excusing it.
    """
    requirement = make_requirement("6(1)(a)")
    imported = make_condition(
        "imported-product", ApplicabilityCondition.Determination.NOT_DETERMINABLE
    )
    food = make_condition(
        "food-article", ApplicabilityCondition.Determination.PRODUCT_CATEGORY
    )

    RequirementApplicability.objects.create(
        requirement=requirement,
        condition=imported,
        mode=RequirementApplicability.Mode.REQUIRES,
    )
    RequirementApplicability.objects.create(
        requirement=requirement,
        condition=food,
        mode=RequirementApplicability.Mode.EXEMPTS,
        note="Explanation III.",
    )

    by_mode = {
        link.condition.code: link.mode
        for link in requirement.applicability_links.select_related("condition")
    }
    assert by_mode == {
        "imported-product": RequirementApplicability.Mode.REQUIRES,
        "food-article": RequirementApplicability.Mode.EXEMPTS,
    }


def test_one_condition_can_both_require_and_exempt_across_requirements(
    make_requirement, make_condition
):
    """The same fact bites differently on different clauses.

    'Medical device' withholds the rule 26(c) exemption *and* disapplies rule
    33 relaxations. The unique constraint is on the triple, not on the pair, so
    both records can exist.
    """
    condition = make_condition(
        "medical-device", ApplicabilityCondition.Determination.NOT_DETERMINABLE
    )
    exemption_gate = make_requirement("26")
    relaxation = make_requirement("33")

    RequirementApplicability.objects.create(
        requirement=exemption_gate,
        condition=condition,
        mode=RequirementApplicability.Mode.REQUIRES,
    )
    RequirementApplicability.objects.create(
        requirement=relaxation,
        condition=condition,
        mode=RequirementApplicability.Mode.EXEMPTS,
    )

    assert condition.requirement_links.count() == 2


def test_an_undeterminable_condition_makes_applicability_undeterminable(
    make_requirement, make_condition
):
    """The safeguard that stops the engine guessing whether a rule applies.

    This is the difference between "this package breaks rule 6(1)(aa)" and "we
    cannot tell whether rule 6(1)(aa) applies to this package", and the system
    must never make the first claim on the strength of the second.
    """
    requirement = make_requirement("6(1)(aa)")
    RequirementApplicability.objects.create(
        requirement=requirement,
        condition=make_condition(
            "imported-product",
            ApplicabilityCondition.Determination.NOT_DETERMINABLE,
        ),
        mode=RequirementApplicability.Mode.REQUIRES,
    )

    assert requirement.applicability_is_determinable is False
    assert requirement.requires_human_review is True


def test_a_requirement_gated_only_on_determinable_conditions_is_decidable(
    make_requirement, make_condition
):
    """The contrast case, so the previous test is not passing vacuously."""
    requirement = make_requirement("6(1)(a)")
    RequirementApplicability.objects.create(
        requirement=requirement,
        condition=make_condition(
            "food-article", ApplicabilityCondition.Determination.PRODUCT_CATEGORY
        ),
        mode=RequirementApplicability.Mode.EXEMPTS,
    )

    assert requirement.applicability_is_determinable is True
    assert requirement.requires_human_review is False


def test_a_requirement_with_no_conditions_is_not_treated_as_undeterminable(
    make_requirement
):
    """Rule 6(1)(c) has no carve-out. Absence of conditions is not doubt."""
    assert make_requirement("6(1)(c)").applicability_is_determinable is True


def test_conditions_default_to_not_determinable(db):
    """A condition added without thought must not license an automatic verdict."""
    condition = ApplicabilityCondition.objects.create(
        code="something-new", name="Something new"
    )

    assert (
        condition.determination
        == ApplicabilityCondition.Determination.NOT_DETERMINABLE
    )
    assert condition.is_determinable is False


# ---------------------------------------------------------------------------
# Detection method: what a photograph can and cannot settle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method",
    [DetectionMethod.OCR, DetectionMethod.CV, DetectionMethod.OCR_CV],
)
def test_image_based_detection_methods_are_evaluable_from_a_photograph(
    make_requirement, method
):
    requirement = make_requirement("6(1)(c)", detection_method=method)

    assert requirement.is_image_evaluable is True
    assert requirement.requires_human_review is False


@pytest.mark.parametrize(
    "method",
    [
        DetectionMethod.PHYSICAL_INSPECTION,
        DetectionMethod.ADMINISTRATIVE,
        DetectionMethod.DIGITAL_ECOMMERCE,
        DetectionMethod.DATABASE,
        DetectionMethod.USER_INPUT,
        DetectionMethod.MANUAL_REVIEW,
        DetectionMethod.NOT_APPLICABLE,
    ],
)
def test_non_image_detection_methods_force_human_review(make_requirement, method):
    """Rule 22 (maximum permissible error) is why this matters.

    A system that read '500 g' off a label and called the package compliant
    with rule 22 would be asserting a weighing it never performed. No engine
    improvement changes that, so it is a property of the requirement, not of
    the current implementation.
    """
    requirement = make_requirement("22", detection_method=method)

    assert requirement.is_image_evaluable is False
    assert requirement.requires_human_review is True


def test_requires_review_verification_status_forces_human_review(make_requirement):
    """The third independent route to review, tested on its own.

    An OCR-evaluable requirement with fully determinable applicability still
    needs a human when the legal content itself is unsettled - rule 6(10A)'s
    transition being the shipped case.
    """
    requirement = make_requirement(
        "6(10A)",
        detection_method=DetectionMethod.OCR,
        verification_status=VerificationStatus.REQUIRES_REVIEW,
    )

    assert requirement.is_image_evaluable is True
    assert requirement.applicability_is_determinable is True
    assert requirement.requires_human_review is True


# ---------------------------------------------------------------------------
# Verification and provenance
# ---------------------------------------------------------------------------


def test_a_verified_requirement_must_record_its_source(make_requirement):
    """The same safeguard `ComplianceRule` applies, on the framework layer."""
    requirement = make_requirement("6(1)(c)")
    requirement.source_note = "   "

    with pytest.raises(ValidationError) as exc:
        requirement.full_clean(exclude=["applicability_conditions"])

    assert "source_note" in exc.value.message_dict


def test_an_unverified_requirement_needs_no_source_note(make_requirement):
    """Drafting must not require verifying first - rules 19-23 are recorded
    this way, by subject, with nothing transcribed."""
    requirement = make_requirement(
        "22",
        verification_status=VerificationStatus.UNVERIFIED,
        source_note="",
        detection_method=DetectionMethod.PHYSICAL_INSPECTION,
        automation_class=AutomationClass.PHYSICAL_MEASUREMENT,
        implementation_status=ImplementationStatus.NOT_APPLICABLE_TO_PROJECT_SCOPE,
    )

    requirement.full_clean(exclude=["applicability_conditions"])  # must not raise


def test_a_verified_instrument_must_record_who_read_it(db):
    instrument = LegalInstrument(
        citation="G.S.R. 999(E)",
        instrument_type=LegalInstrument.InstrumentType.AMENDMENT,
        verification_status=VerificationStatus.VERIFIED,
        verification_note="",
    )

    with pytest.raises(ValidationError) as exc:
        instrument.full_clean()

    assert "verification_note" in exc.value.message_dict


def test_an_instrument_separates_notification_from_commencement(db):
    """G.S.R. 312(E) is notified in April 2026 and commences in July 2027.

    Conflating the two would date a requirement wrong by fourteen months.
    """
    instrument = LegalInstrument.objects.create(
        citation="G.S.R. 312(E)",
        instrument_type=LegalInstrument.InstrumentType.AMENDMENT,
        notified_on=date(2026, 4, 27),
        effective_from=date(2027, 7, 1),
    )

    assert instrument.notified_on != instrument.effective_from


# ---------------------------------------------------------------------------
# The link to the executable layer
# ---------------------------------------------------------------------------


def test_an_executable_rule_can_be_linked_to_the_clause_it_evaluates(
    make_rule, make_requirement
):
    requirement = make_requirement("6(1)(c)")
    rule = make_rule("LM-PC-TEST")
    rule.rule_requirement = requirement
    rule.save()

    rule.refresh_from_db()
    assert rule.rule_requirement == requirement
    assert list(requirement.compliance_rules.all()) == [rule]


def test_a_requirement_may_have_several_executable_rules(
    make_rule, make_requirement
):
    """Presence and format are separate checks of one clause.

    The reason the foreign key sits on `ComplianceRule` rather than the other
    way round.
    """
    requirement = make_requirement("6(1)(e)")
    for code in ("LM-PC-PRESENCE", "LM-PC-FORMAT"):
        rule = make_rule(code)
        rule.rule_requirement = requirement
        rule.save()

    assert requirement.compliance_rules.count() == 2


def test_an_executable_rule_needs_no_requirement(make_rule):
    """An unmapped rule must still be creatable and evaluable.

    Rules can be drafted before the clause they implement is transcribed, and
    the shipped executable rules predate this framework entirely.
    """
    rule = make_rule("LM-PC-UNMAPPED")

    rule.full_clean(exclude=["applies_to_categories"])  # must not raise
    assert rule.rule_requirement is None


def test_a_requirement_with_findings_cannot_be_deleted(make_rule, make_requirement):
    """PROTECT, for the same reason as on the rule: a recorded outcome must
    keep its justification."""
    requirement = make_requirement("6(1)(c)")
    rule = make_rule("LM-PC-PROTECTED")
    rule.rule_requirement = requirement
    rule.save()

    from django.db.models import ProtectedError

    with pytest.raises(ProtectedError):
        requirement.delete()


def test_severity_vocabulary_is_shared_with_the_executable_layer(make_requirement):
    """One triage vocabulary, so a requirement and its rule cannot disagree."""
    requirement = make_requirement("26", severity=ComplianceRule.Severity.CRITICAL)

    assert requirement.severity in {c.value for c in ComplianceRule.Severity}
