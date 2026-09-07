"""The legal context the engine records on every finding.

`test_findings.py` covers what a finding concludes. These cover what a finding
can be *audited against*: which clause it came from, which amendment
established that clause, what evidence could ever have settled it, and what
about its applicability could not be established.

The theme throughout is that a finding must not be readable as a stronger claim
than the system can support. A rule that passed still carries the caveat that
the package may be outside the Rules entirely.
"""

from datetime import date

import pytest

from apps.compliance.models import ComplianceCheck, ComplianceFinding
from apps.compliance.services import engine
from apps.rules.models import (
    ApplicabilityCondition,
    AutomationClass,
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
def net_quantity_requirement(db) -> RuleRequirement:
    """Rule 6(1)(c), mapped as the shipped framework maps it."""
    rule = LegalRule.objects.create(
        rule_number="6",
        sort_key=LegalRule.build_sort_key("6"),
        title="Declarations to be made on every package",
        automation_class=AutomationClass.PARTIALLY_AUTOMATABLE,
    )
    instrument = LegalInstrument.objects.create(
        citation="G.S.R. 202(E)",
        instrument_type=LegalInstrument.InstrumentType.PRINCIPAL,
        effective_from=date(2011, 4, 1),
    )
    return RuleRequirement.objects.create(
        rule=rule,
        clause="6(1)(c)",
        title="Net quantity",
        requirement="The package must state the net quantity.",
        verbatim_text="The net quantity, in terms of the standard unit ...",
        detection_method=DetectionMethod.OCR,
        automation_class=AutomationClass.IMAGE_AUTOMATABLE,
        implementation_status=ImplementationStatus.IMPLEMENTED,
        source=instrument,
        legal_reference="Rule 6(1)(c) of the LMPC Rules, 2011",
        verification_status=VerificationStatus.VERIFIED,
        source_note="Fixture.",
        effective_from=date(2011, 4, 1),
    )


@pytest.fixture
def mapped_rule(make_rule, net_quantity_requirement):
    rule = make_rule("LM-PC-0003", field_key="net_quantity")
    rule.rule_requirement = net_quantity_requirement
    rule.save()
    return rule


def test_a_finding_records_the_clause_and_the_amendment_behind_it(
    completed_run, mapped_rule, make_extracted_field
):
    """Without these a finding cannot be checked against the source.

    A rule code is an identifier this project invented; a clause number and an
    instrument citation are what a reviewer holding the Gazette can look up.
    """
    make_extracted_field(completed_run, "net_quantity", "500 g")

    check = engine.evaluate(completed_run)

    finding = check.findings.get(rule_code="LM-PC-0003")
    assert finding.clause == "6(1)(c)"
    assert finding.legal_source_citation == "G.S.R. 202(E)"
    assert finding.rule_requirement_id == mapped_rule.rule_requirement_id
    assert finding.legal_reference == mapped_rule.legal_reference


def test_a_finding_records_what_evidence_could_have_settled_it(
    completed_run, mapped_rule, make_extracted_field
):
    """`detection_method` is what tells a reader whether a verdict was even
    possible from a photograph."""
    make_extracted_field(completed_run, "net_quantity", "500 g")

    check = engine.evaluate(completed_run)

    assert check.findings.get().detection_method == DetectionMethod.OCR


def test_a_finding_keeps_the_raw_reading_alongside_the_normalised_one(
    completed_run, mapped_rule, make_extracted_field
):
    """Normalisation must not destroy the original extracted value.

    Both are snapshotted onto the finding, so deleting the extraction run
    cannot leave a finding whose evidence has silently become empty.
    """
    make_extracted_field(
        completed_run,
        "net_quantity",
        "Net Wt. 500 g",
        normalized_value={"magnitude": 500, "unit": "g"},
    )

    check = engine.evaluate(completed_run)

    finding = check.findings.get()
    assert finding.extracted_raw_value == "Net Wt. 500 g"
    assert finding.extracted_normalized_value == {"magnitude": 500, "unit": "g"}


def test_a_missing_normaliser_leaves_null_not_an_empty_value(
    completed_run, mapped_rule, make_extracted_field
):
    """Null means "no normaliser ran", never "the reading was empty"."""
    make_extracted_field(completed_run, "net_quantity", "500 g")

    check = engine.evaluate(completed_run)

    finding = check.findings.get()
    assert finding.extracted_raw_value == "500 g"
    assert finding.extracted_normalized_value is None


def test_a_finding_about_an_absence_records_no_extracted_value(
    completed_run, mapped_rule
):
    """The declaration was not found, so there is nothing read to snapshot.

    The finding still exists and still names its clause - the absence is the
    finding.
    """
    check = engine.evaluate(completed_run)

    finding = check.findings.get()
    assert finding.status == ComplianceFinding.Status.FAILED
    assert finding.extracted_raw_value == ""
    assert finding.extracted_normalized_value is None
    assert finding.clause == "6(1)(c)"


# ---------------------------------------------------------------------------
# Applicability is recorded on the finding, including what is unknown
# ---------------------------------------------------------------------------


def test_every_finding_carries_the_scope_caveat(
    completed_run, mapped_rule, make_extracted_field
):
    """Rules 3 and 26 take packages out of scope on facts nobody collects.

    The caveat is attached to a PASSING finding here on purpose: it is true of
    every result, and a caveat recorded only on failures is one a reader cannot
    rely on the absence of.
    """
    make_extracted_field(completed_run, "net_quantity", "500 g")

    check = engine.evaluate(completed_run)

    finding = check.findings.get()
    assert finding.status == ComplianceFinding.Status.PASSED
    assert "rule 3 and rule 26" in finding.applicability_note
    assert "rule 33" in finding.applicability_note


def test_an_undeterminable_condition_is_named_on_the_finding(
    completed_run, mapped_rule, net_quantity_requirement, make_extracted_field
):
    """A reader must be told *which* fact could not be established.

    "Conditional on something" is not actionable; "conditional on whether this
    package is imported" is.
    """
    RequirementApplicability.objects.create(
        requirement=net_quantity_requirement,
        condition=ApplicabilityCondition.objects.create(
            code="imported-product",
            name="Imported product",
            determination=ApplicabilityCondition.Determination.NOT_DETERMINABLE,
        ),
        mode=RequirementApplicability.Mode.REQUIRES,
    )
    make_extracted_field(completed_run, "net_quantity", "500 g")

    check = engine.evaluate(completed_run)

    note = check.findings.get().applicability_note
    assert "CANNOT be established" in note
    assert "Imported product" in note


def test_a_determinable_condition_is_not_reported_as_unknown(
    completed_run, mapped_rule, net_quantity_requirement, make_extracted_field
):
    """The contrast case, so the previous test is not passing on boilerplate."""
    RequirementApplicability.objects.create(
        requirement=net_quantity_requirement,
        condition=ApplicabilityCondition.objects.create(
            code="food-article",
            name="Food article",
            determination=ApplicabilityCondition.Determination.PRODUCT_CATEGORY,
        ),
        mode=RequirementApplicability.Mode.EXEMPTS,
    )
    make_extracted_field(completed_run, "net_quantity", "500 g")

    check = engine.evaluate(completed_run)

    note = check.findings.get().applicability_note
    assert "CANNOT be established" not in note
    assert "Food article" not in note


def test_an_unmapped_rule_says_so_rather_than_implying_no_legal_basis(
    completed_run, make_rule, make_extracted_field
):
    """A rule with no clause link must not silently produce a bare finding.

    The rule may be perfectly sound - the shipped executable rules predate the
    framework - but a finding that cannot name its clause cannot be audited,
    and saying so is cheaper than a reviewer discovering it.
    """
    make_rule("LM-PC-UNMAPPED", field_key="net_quantity")
    make_extracted_field(completed_run, "net_quantity", "500 g")

    check = engine.evaluate(completed_run)

    finding = check.findings.get(rule_code="LM-PC-UNMAPPED")
    assert finding.clause == ""
    assert finding.detection_method == ""
    assert finding.legal_source_citation == ""
    assert finding.rule_requirement_id is None
    assert "not linked to a clause" in finding.applicability_note
    # The universal caveat still applies to an unmapped rule.
    assert "rule 3 and rule 26" in finding.applicability_note


# ---------------------------------------------------------------------------
# The three compliance statuses the brief requires
# ---------------------------------------------------------------------------


def test_compliant_non_compliant_and_review_required_are_all_reachable(
    product_image, mapped_rule, make_extracted_field, django_assert_max_num_queries
):
    """COMPLIANT / NON_COMPLIANT / REQUIRES_REVIEW, end to end.

    The brief names REQUIRES_REVIEW; this schema has shipped it as
    REVIEW_REQUIRED since before this branch, and the API and frontend both
    read that value. It is the same status under the name already in the
    contract - renaming it would break a shipped client to gain nothing.
    """
    from apps.extraction.models import ExtractionRun

    def run_with(status: str) -> ExtractionRun:
        return ExtractionRun.objects.create(
            image=product_image,
            engine_name="stub",
            engine_version="0.0.0",
            status=status,
            recognised_text="text" if status == ExtractionRun.Status.COMPLETED else "",
        )

    passing = run_with(ExtractionRun.Status.COMPLETED)
    make_extracted_field(passing, "net_quantity", "500 g")
    assert engine.evaluate(passing).result == ComplianceCheck.Result.COMPLIANT

    failing = run_with(ExtractionRun.Status.COMPLETED)
    assert engine.evaluate(failing).result == ComplianceCheck.Result.NON_COMPLIANT

    # An unreadable photograph is never a violation. This is the status that
    # carries the weight: "we could not read it" is not "the declaration is
    # missing".
    unreadable = run_with(ExtractionRun.Status.EMPTY)
    assert engine.evaluate(unreadable).result == ComplianceCheck.Result.REVIEW_REQUIRED


def test_recording_the_legal_context_does_not_add_a_query_per_rule(
    completed_run, category, make_rule, net_quantity_requirement, make_extracted_field,
    django_assert_max_num_queries,
):
    """The new snapshot columns must not reintroduce an N+1.

    Each finding reads its requirement, that requirement's instrument, and its
    applicability conditions. All three are prefetched in `applicable_rules`,
    so evaluating fifteen mapped rules must cost no more than evaluating three.
    """
    make_extracted_field(completed_run, "net_quantity", "500 g")
    for index in range(15):
        rule = make_rule(f"MAPPED-{index:03d}", categories=[category])
        rule.rule_requirement = net_quantity_requirement
        rule.save()

    with django_assert_max_num_queries(30):
        check = engine.evaluate(completed_run)

    assert check.findings.count() == 15
    assert all(finding.clause == "6(1)(c)" for finding in check.findings.all())
