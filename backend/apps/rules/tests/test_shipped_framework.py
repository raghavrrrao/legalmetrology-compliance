"""The legal framework this repository actually ships in `rules/framework/`.

`test_framework_loader.py` tests the loader against throwaway files. These
tests read the real ones, because the shipped framework makes claims about
Indian law and three things can go wrong with it that nothing else catches:

1. A framework file drifts out of the shape the loader accepts, and
   `load_legal_framework` fails in a deployment rather than in CI.
2. Someone fills in a `verbatim_text` that nobody transcribed, or marks a
   requirement `verified` without recording who checked it. Both turn an honest
   gap into a fabricated legal claim, which is the failure this project exists
   to avoid.
3. Someone marks a requirement `implemented` that no active rule evaluates, or
   claims a physical or administrative obligation is automatable from an image.

The counts here are deliberately expressed as inequalities or as exact sets of
*names*, not as magic totals: adding a newly transcribed clause should not
break a test, but silently dropping rule 22 should.
"""

import pytest
from django.conf import settings

from apps.rules.framework_loader import load_framework
from apps.rules.models import (
    ApplicabilityCondition,
    AutomationClass,
    DetectionMethod,
    ImplementationStatus,
    LegalInstrument,
    LegalRule,
    RuleRequirement,
    VerificationStatus,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def shipped_framework(db):
    """Load the real `rules/framework/` into the test database."""
    report = load_framework(settings.RULES_FRAMEWORK_DIR)
    assert report.ok, f"the shipped framework does not load: {report.errors}"
    return report


def test_the_shipped_framework_loads(shipped_framework):
    """The regression this file exists for: a file drifting out of shape."""
    assert shipped_framework.requirements_seen > 0


def test_every_rule_from_1_to_34_is_recorded(shipped_framework):
    """The Step 1 brief asks for rules 1-34 to be represented.

    Asserted as a set of names rather than a count, so a missing rule 22 names
    itself in the failure instead of showing up as an off-by-one.
    """
    recorded = set(LegalRule.objects.values_list("rule_number", flat=True))
    expected = {str(number) for number in range(1, 35)}

    assert expected - recorded == set(), (
        f"rules missing from the framework: {sorted(expected - recorded, key=int)}"
    )


def test_rule_32a_is_recorded_as_an_open_question_not_as_a_rule(shipped_framework):
    """The brief asks for rule 32-A 'where applicable'.

    No provision numbered 32-A appears in the project's verified material, so
    it is recorded inactive, flagged for review, and carrying NO requirement.
    Were it ever given a requirement without a source, this would fail - which
    is the point.
    """
    rule = LegalRule.objects.get(rule_number="32A")

    assert rule.is_active is False
    assert rule.verification_status == VerificationStatus.REQUIRES_REVIEW
    assert rule.requirements.count() == 0, (
        "rule 32-A has acquired a requirement. Nothing in rules/SOURCES.md or "
        "rules/INVENTORY.md establishes its content - a requirement here would "
        "be invented."
    )


def test_rules_are_ordered_by_number_with_32a_between_32_and_33(shipped_framework):
    numbers = list(LegalRule.objects.values_list("rule_number", flat=True))

    assert numbers.index("32") < numbers.index("32A") < numbers.index("33")
    assert numbers.index("2") < numbers.index("10")


# ---------------------------------------------------------------------------
# Rule 6(10A): the versioned clause and its unresolved transition
# ---------------------------------------------------------------------------


def test_rule_6_10a_has_both_amendment_versions_on_record(shipped_framework):
    """The centrepiece of the versioning requirement.

    G.S.R. 128(E) inserts the clause with effect from 1 July 2026; G.S.R.
    312(E) substitutes it with effect from 1 July 2027. Both must be readable,
    each with its own instrument.
    """
    versions = {
        row.version: row
        for row in RuleRequirement.objects.select_related("source").filter(
            clause="6(10A)"
        )
    }

    assert set(versions) == {1, 2}
    assert versions[1].source.citation == "G.S.R. 128(E)"
    assert versions[2].source.citation == "G.S.R. 312(E)"
    assert versions[2].supersedes_id == versions[1].pk
    assert str(versions[1].effective_from) == "2026-07-01"
    assert str(versions[2].effective_from) == "2027-07-01"


def test_the_6_10a_transition_is_flagged_for_review_not_invented(shipped_framework):
    """The brief: do NOT invent a transition the source does not establish.

    Neither notification states when version 1 ceases to apply. The obvious
    inference - that it runs to 30 June 2027 - is an interpretation, so
    `effective_to` is left null and BOTH rows are flagged REQUIRES_REVIEW.

    The consequence is that both versions report in force from 1 July 2027.
    That is asserted here deliberately: it is the correct representation of an
    unresolved transition, and a future change that quietly closes version 1's
    window to make this "tidy" must fail this test and be justified against the
    Gazette instead.
    """
    from datetime import date

    versions = {
        row.version: row for row in RuleRequirement.objects.filter(clause="6(10A)")
    }

    assert versions[1].effective_to is None, (
        "an end date has been given to rule 6(10A) version 1. Neither G.S.R. "
        "128(E) nor G.S.R. 312(E) states one - see rules/SOURCES.md."
    )
    for version in versions.values():
        assert version.verification_status == VerificationStatus.REQUIRES_REVIEW
        assert version.requires_human_review is True

    in_force = {
        version for version, row in versions.items() if row.is_in_force_on(date(2027, 7, 1))
    }
    assert in_force == {1, 2}, (
        "the overlap on 2027-07-01 has been resolved silently. Resolving it is "
        "a legal decision for a named reviewer, not a data tidy-up."
    )


def test_version_1_of_6_10a_has_no_verbatim_text(shipped_framework):
    """rules/SOURCES.md records what G.S.R. 128(E) *does*, not what it *says*.

    A quotation must never be reconstructed from a description of effect.
    """
    version_one = RuleRequirement.objects.get(clause="6(10A)", version=1)

    assert version_one.verbatim_text == "", (
        "a verbatim quotation has appeared for rule 6(10A) as inserted. The "
        "project's sources describe that notification's effect but do not "
        "transcribe the clause."
    )


# ---------------------------------------------------------------------------
# Honesty of the legal record
# ---------------------------------------------------------------------------


def test_every_verified_requirement_records_who_checked_it(shipped_framework):
    """Model-enforced, but asserted over the shipped data too.

    `full_clean` runs in the loader, so this would already fail there - it is
    restated as a test because it is the single invariant that keeps an
    unreviewed legal claim out of a user-facing finding.
    """
    unsourced = [
        row.clause
        for row in RuleRequirement.objects.filter(
            verification_status=VerificationStatus.VERIFIED
        )
        if not row.source_note.strip()
    ]

    assert unsourced == []


def test_every_verified_instrument_records_who_read_it(shipped_framework):
    unsourced = [
        row.citation
        for row in LegalInstrument.objects.filter(
            verification_status=VerificationStatus.VERIFIED
        )
        if not row.verification_note.strip()
    ]

    assert unsourced == []


def test_the_two_directly_retrieved_gazette_notifications_are_verified(
    shipped_framework
):
    """G.S.R. 128(E) and 312(E) were retrieved and read in full.

    They are the only two instruments that may be marked verified, because
    every other one is known through the Department's consolidated publication
    or, worse, through a press release. If a third ever appears here it must be
    because someone actually retrieved it.
    """
    verified = set(
        LegalInstrument.objects.filter(
            verification_status=VerificationStatus.VERIFIED
        ).values_list("citation", flat=True)
    )

    assert "G.S.R. 128(E)" in verified
    assert "G.S.R. 312(E)" in verified
    for citation in verified:
        instrument = LegalInstrument.objects.get(citation=citation)
        assert instrument.source_url or instrument.source_sha256, (
            f"{citation} is marked verified but records neither a URL nor a "
            f"digest for what was read."
        )


def test_the_unretrieved_amendment_chain_is_recorded_as_an_open_gap(
    shipped_framework
):
    """G.S.R. 881(E) is known only from a recital in a later notification.

    rules/SOURCES.md calls the 2022-2025 amendment chain the biggest open item
    in the legal record. Recording it as REQUIRES_REVIEW rather than omitting
    it is what makes the gap visible to anyone querying the framework.
    """
    gap = LegalInstrument.objects.get(citation="G.S.R. 881(E)")

    assert gap.verification_status == VerificationStatus.REQUIRES_REVIEW
    assert gap.notified_on is not None
    assert "not retrieved" in gap.verification_note.lower()


def test_no_requirement_claims_a_source_it_does_not_name(shipped_framework):
    """A requirement dated by an amendment must say which amendment.

    An effective date with no instrument behind it is a date somebody chose.
    """
    dated_without_source = [
        row.clause
        for row in RuleRequirement.objects.select_related("source")
        if row.effective_from is not None
        and row.source is None
        and row.effective_from.year > 2011
    ]

    assert dated_without_source == [], (
        f"these clauses carry a post-commencement effective date with no "
        f"instrument to justify it: {dated_without_source}"
    )


# ---------------------------------------------------------------------------
# Classification: no over-claiming of what can be automated
# ---------------------------------------------------------------------------


def test_only_requirements_with_an_active_rule_are_marked_implemented(
    shipped_framework, category
):
    """"Implemented" must mean evaluated, not merely entered in the database.

    Loading the executable rules first, so the link exists. The two implemented
    clauses are rule 6(1)(c) and rule 6(2) - the only two this system checks -
    and marking a third would need an active `ComplianceRule` behind it.
    """
    from apps.catalog.models import ProductCategory
    from apps.rules.loader import load_rules

    for code in ("packaged-commodity", "packaged-food", "packaged-non-food"):
        ProductCategory.objects.get_or_create(code=code, defaults={"name": code})
    load_rules(settings.RULES_DEFINITIONS_DIR)
    load_framework(settings.RULES_FRAMEWORK_DIR)

    implemented = RuleRequirement.objects.filter(
        implementation_status=ImplementationStatus.IMPLEMENTED
    )

    # Six clauses were added in Step 2. Listed rather than counted, so adding a
    # seventh has to be a deliberate edit here and not a number nudged upward.
    assert set(implemented.values_list("clause", flat=True)) == {
        "6(1)(a)",   # LM-PC-0001, via the field_presence_any_of disjunction
        "6(1)(aa)",  # LM-PC-0007, imported packages only
        "6(1)(c)",   # LM-PC-0003
        "6(1)(d)",   # LM-PC-0004
        "6(1)(e)",   # LM-PC-0005, presence only
        "6(2)",      # LM-PC-0006
        "13(4)",     # LM-PC-0009
        "13(5)",     # LM-PC-0008
    }
    for requirement in implemented:
        assert requirement.compliance_rules.filter(is_active=True).exists(), (
            f"{requirement.clause} is marked implemented but no active "
            f"ComplianceRule evaluates it."
        )


def test_physical_and_administrative_requirements_are_never_image_automatable(
    shipped_framework
):
    """The image-only limitation, asserted over the shipped classifications.

    Rule 22 (maximum permissible error) and rules 27-30 (registration) are the
    cases that matter: no photograph settles a weighing or a regulator's
    register, so neither may be classified as decidable from an image.
    """
    over_claimed = [
        (row.clause, row.detection_method, row.automation_class)
        for row in RuleRequirement.objects.filter(
            detection_method__in=[
                DetectionMethod.PHYSICAL_INSPECTION,
                DetectionMethod.ADMINISTRATIVE,
                DetectionMethod.DIGITAL_ECOMMERCE,
            ]
        )
        if row.automation_class == AutomationClass.IMAGE_AUTOMATABLE
    ]

    assert over_claimed == []


def test_maximum_permissible_error_requires_human_review(shipped_framework):
    """Named explicitly, because it is the requirement most likely to be
    wrongly automated: a label reading of '500 g' is not a weighing."""
    rule_22 = RuleRequirement.objects.get(clause="22")

    assert rule_22.detection_method == DetectionMethod.PHYSICAL_INSPECTION
    assert rule_22.automation_class == AutomationClass.PHYSICAL_MEASUREMENT
    assert rule_22.is_image_evaluable is False
    assert rule_22.requires_human_review is True


def test_registration_rules_require_human_review(shipped_framework):
    """Rules 27-30: nothing on a package evidences a registration."""
    for clause in ("27", "28", "29", "30"):
        requirement = RuleRequirement.objects.get(clause=clause)
        assert requirement.detection_method == DetectionMethod.ADMINISTRATIVE
        assert requirement.requires_human_review is True


def test_penalties_are_not_modelled_as_something_to_evaluate(shipped_framework):
    """The project makes no legal determination and computes no penalty.

    Rule 32's verbatim text is deliberately empty: transcribing a schedule of
    fines invites exactly the use this project refuses.
    """
    rule_32 = RuleRequirement.objects.get(clause="32")

    assert (
        rule_32.implementation_status
        == ImplementationStatus.NOT_APPLICABLE_TO_PROJECT_SCOPE
    )
    assert rule_32.verbatim_text == ""
    assert rule_32.requires_human_review is True


def test_the_scope_gates_are_answerable_only_by_declaration(shipped_framework):
    """Rules 3 and 26 are the widest correctness caveat in the project.

    Step 2 changed what this test can assert, and the change is worth stating
    precisely. Before, every condition behind these gates was NOT_DETERMINABLE:
    the system had no way to know a package was a 30 kg sack or an
    institutional consignment, so the gates could never bite and every rule was
    applied to every submission.

    They are now USER_DECLARED - answerable, but only by the submitter, and
    never from the package. That is the narrow claim this test pins:

    - no gate condition is derived from the label, from OCR, or from an
      extracted net quantity, which would be circular; and
    - no gate condition is silently assumed, which is enforced by
      `DeclarationSet.answer` returning UNKNOWN for anything unstated.

    What has NOT changed is that an undeclared package is still evaluated
    against rules that may not govern it. `engine._SCOPE_CAVEAT` states that on
    every finding, and `applicability.decide_scope` explains why refusing to
    evaluate would be the worse answer.
    """
    from apps.rules.models import ApplicabilityCondition

    answerable = ApplicabilityCondition.Determination.USER_DECLARED
    for clause in ("3", "26"):
        gate = RuleRequirement.objects.get(clause=clause)
        determinations = {
            condition.determination
            for condition in gate.applicability_conditions.all()
        }
        assert determinations, f"rule {clause} has no scope conditions at all"
        assert determinations <= {answerable}, (
            f"a condition behind rule {clause} is determined some way other "
            f"than by the submitter declaring it: {sorted(determinations)}. "
            f"None of these facts may be read off the label - inferring the "
            f"net quantity gate from the extracted net quantity would use the "
            f"declaration under test to decide whether to test it."
        )


def test_rule_33_relaxations_are_recorded_as_unknowable(shipped_framework):
    """A relaxation makes an otherwise-correct finding wrong, and the system
    cannot know one exists. Every finding is conditional on this."""
    condition = ApplicabilityCondition.objects.get(code="rule-33-relaxation-granted")

    assert condition.is_determinable is False
    assert condition.requirement_links.exists()


def test_special_categories_from_the_brief_are_representable(shipped_framework):
    """The Step 1 brief lists the applicability categories that must exist.

    They exist as *vocabulary*. Several carry no requirement link, because the
    project's verified material establishes no clause for them - which their
    determination_note says explicitly.
    """
    required = {
        "imported-product",
        "medical-device",
        "pan-masala",
        "electronic-product",
        "combination-package",
        "group-package",
        "multi-piece-package",
        "wholesale-package",
        "export-package",
        "ecommerce-listing",
        "loose-commodity-via-ecommerce",
        "industrial-consumer",
        "institutional-consumer",
    }
    present = set(ApplicabilityCondition.objects.values_list("code", flat=True))

    assert required - present == set()


def test_conditions_with_no_verified_clause_carry_no_requirement_link(
    shipped_framework
):
    """The honest half of the previous test.

    Pan masala, AEO bonded warehouses and electronic products are named in the
    brief but appear NOWHERE in the project's verified material. They are
    recorded as vocabulary so the gap is visible, and attaching a requirement
    to one without a source would be inventing law.
    """
    for code in ("pan-masala", "aeo-bonded-warehouse", "electronic-product"):
        condition = ApplicabilityCondition.objects.get(code=code)
        assert condition.requirement_links.count() == 0, (
            f"'{code}' has acquired a requirement link. No clause in "
            f"rules/SOURCES.md or rules/INVENTORY.md turns on it - see its "
            f"determination_note."
        )
        assert "vocabulary only" in condition.determination_note.lower()


def test_requirements_without_a_transcription_are_not_marked_image_automatable(
    shipped_framework
):
    """A clause nobody has transcribed cannot be known to be checkable.

    Guards the combination that would matter: an empty `verbatim_text` and a
    claim that an image decides it. Presence checks derived from a quoted
    clause are unaffected.
    """
    over_claimed = [
        row.clause
        for row in RuleRequirement.objects.filter(
            automation_class=AutomationClass.IMAGE_AUTOMATABLE,
            implementation_status__in=[
                ImplementationStatus.IMPLEMENTED,
                ImplementationStatus.IMPLEMENTABLE_NOW,
            ],
        )
        if not row.verbatim_text.strip()
    ]

    assert over_claimed == [], (
        f"these clauses are claimed to be checkable from an image but have no "
        f"transcribed text to check against: {over_claimed}"
    )
