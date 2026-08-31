"""Findings: the complete record of what the engine actually examined.

`test_engine.py` covers the verdict. This file covers the trace behind it -
one row per rule evaluated, whatever it concluded - and the properties that
make that trace worth trusting:

- every applicable rule gets a finding, not only the ones that failed;
- a finding names the requirement, the check, the declaration, what was read
  and how sure the reader was, so it can be checked by hand;
- `inconclusive` stays distinguishable from both a pass and a violation;
- the "an unverified rule cannot fail a package" downgrade is visible in the
  record rather than inferable;
- adding the trace did not change a single verdict.

Nothing here asserts a legal conclusion. Every rule in these tests is a fixture
rule with a fixture reference, and what is being tested is the machinery.
"""

import pytest

from labelextract.contracts import LabelFieldKey

from apps.compliance.models import ComplianceCheck, ComplianceFinding
from apps.compliance.services import engine

pytestmark = pytest.mark.django_db


def _findings_by_code(check: ComplianceCheck) -> dict[str, ComplianceFinding]:
    return {finding.rule_code: finding for finding in check.findings.all()}


# --- every outcome is recorded, not just the failures ------------------------


def test_a_passing_rule_produces_a_finding(
    completed_run, make_rule, make_extracted_field
):
    """`rules_passed` was a counter; a pass is now a record you can inspect."""
    make_extracted_field(completed_run, LabelFieldKey.NET_QUANTITY.value)
    make_rule("PASS-001", field_key=LabelFieldKey.NET_QUANTITY.value)

    check = engine.evaluate(completed_run)

    finding = _findings_by_code(check)["PASS-001"]
    assert finding.status == ComplianceFinding.Status.PASSED
    assert finding.violation is None
    assert check.rules_passed == 1
    assert check.violations.count() == 0


def test_a_failing_rule_produces_both_a_finding_and_a_violation(
    completed_run, make_rule
):
    """The two records are consistent, and the finding names its violation."""
    make_rule("FAIL-001", field_key=LabelFieldKey.NET_QUANTITY.value, verified=True)

    check = engine.evaluate(completed_run)

    finding = _findings_by_code(check)["FAIL-001"]
    violation = check.violations.get()
    assert finding.status == ComplianceFinding.Status.FAILED
    assert finding.violation_id == violation.pk
    assert finding.is_violation is True
    # Reachable from either end.
    assert violation.finding == finding


def test_an_inconclusive_rule_produces_a_finding(empty_run, make_rule):
    """The state that sends a package to a human is now visible per rule.

    Previously this was a bare `rules_inconclusive` count: a reviewer could see
    that something could not be decided but not which rule, nor about which
    declaration.
    """
    make_rule("INC-001", field_key=LabelFieldKey.NET_QUANTITY.value, verified=True)

    check = engine.evaluate(empty_run)

    finding = _findings_by_code(check)["INC-001"]
    assert finding.status == ComplianceFinding.Status.INCONCLUSIVE
    assert finding.violation is None
    assert finding.field_key == LabelFieldKey.NET_QUANTITY.value
    assert check.result == ComplianceCheck.Result.REVIEW_REQUIRED


def test_every_applicable_rule_gets_exactly_one_finding(
    completed_run, make_rule, make_extracted_field, category
):
    """One row per rule examined - no more, no fewer."""
    make_extracted_field(completed_run, LabelFieldKey.NET_QUANTITY.value)
    make_rule("MIX-PASS", field_key=LabelFieldKey.NET_QUANTITY.value)
    make_rule("MIX-FAIL", field_key=LabelFieldKey.MANUFACTURER_NAME.value)
    make_rule("MIX-UNVERIFIED", field_key=LabelFieldKey.BEST_BEFORE.value,
              verified=False)

    check = engine.evaluate(completed_run)

    findings = _findings_by_code(check)
    assert set(findings) == {"MIX-PASS", "MIX-FAIL", "MIX-UNVERIFIED"}
    assert check.findings.count() == check.rules_evaluated == 3


def test_a_rule_that_does_not_apply_gets_no_finding(
    completed_run, make_rule, category, db
):
    """A finding means "this was examined", so an inapplicable rule has none."""
    from apps.catalog.models import ProductCategory

    other = ProductCategory.objects.create(code="other-goods", name="Other goods")
    make_rule("ELSEWHERE", categories=[other])

    check = engine.evaluate(completed_run)

    assert check.findings.count() == 0


def test_a_broken_rule_produces_no_finding(completed_run, make_rule):
    """A rule that could not be evaluated was not examined, so it has no outcome.

    It must also not be recorded as a pass - `test_engine.py` asserts the
    verdict side of that; this asserts the trace does not invent a row.
    """
    make_rule("BROKEN", check_type="field_presence", parameters={})

    check = engine.evaluate(completed_run)

    assert check.findings.count() == 0
    assert check.rules_evaluated == 0


# --- a finding carries enough to be checked by hand --------------------------


def test_a_finding_carries_the_requirement_and_its_legal_reference(
    completed_run, make_rule
):
    """A rule code alone means nothing to a reviewer; the requirement does."""
    make_rule(
        "TRACE-001",
        field_key=LabelFieldKey.NET_QUANTITY.value,
        verified=True,
        title="Fixture rule title",
        requirement="The package must declare a fixture requirement.",
        legal_reference="Fixture reference - not legal text",
        severity="major",
    )

    check = engine.evaluate(completed_run)

    finding = _findings_by_code(check)["TRACE-001"]
    assert finding.title == "Fixture rule title"
    assert finding.requirement == "The package must declare a fixture requirement."
    assert finding.legal_reference == "Fixture reference - not legal text"
    assert finding.severity == "major"
    assert finding.check_type == "field_presence"
    assert finding.message


def test_a_finding_links_to_the_reading_it_was_drawn_from(
    completed_run, make_rule, make_extracted_field
):
    """Extracted field -> check -> finding, traceable in the database."""
    field = make_extracted_field(
        completed_run, LabelFieldKey.NET_QUANTITY.value, raw_value="Net Qty: 500 g"
    )
    make_rule("LINK-001", field_key=LabelFieldKey.NET_QUANTITY.value)

    check = engine.evaluate(completed_run)

    finding = _findings_by_code(check)["LINK-001"]
    assert finding.extracted_field_id == field.pk
    assert finding.evidence_excerpt == "Net Qty: 500 g"


def test_a_finding_about_an_absence_links_to_no_reading(completed_run, make_rule):
    """There is no reading behind "we did not find this"."""
    make_rule("ABSENT-001", field_key=LabelFieldKey.NET_QUANTITY.value, verified=True)

    check = engine.evaluate(completed_run)

    finding = _findings_by_code(check)["ABSENT-001"]
    assert finding.extracted_field is None
    assert finding.extracted_confidence is None
    # What we DID read is still attached, as the justification for the absence.
    assert finding.evidence_excerpt == completed_run.recognised_text


# --- confidence reaches the finding, and is not silently laundered -----------


def test_the_ocr_confidence_behind_a_finding_is_recorded(
    completed_run, make_rule, make_extracted_field
):
    make_extracted_field(
        completed_run, LabelFieldKey.NET_QUANTITY.value, confidence=0.87
    )
    make_rule("CONF-001", field_key=LabelFieldKey.NET_QUANTITY.value)

    check = engine.evaluate(completed_run)

    assert _findings_by_code(check)["CONF-001"].extracted_confidence == pytest.approx(
        0.87
    )


def test_an_unreported_confidence_stays_null_rather_than_becoming_zero(
    completed_run, make_rule, make_extracted_field
):
    """Null means "the engine did not say". Zero would be a claim nobody made."""
    make_extracted_field(
        completed_run, LabelFieldKey.NET_QUANTITY.value, confidence=None
    )
    make_rule("CONF-002", field_key=LabelFieldKey.NET_QUANTITY.value)

    check = engine.evaluate(completed_run)

    assert _findings_by_code(check)["CONF-002"].extracted_confidence is None


def test_a_low_confidence_reading_still_passes_but_says_what_it_was_worth(
    completed_run, make_rule, make_extracted_field
):
    """The documented behaviour, asserted so a change to it is deliberate.

    `field_presence` asks whether a declaration was found, and does not
    threshold on confidence - thresholding would be a policy this repository
    has no verified source for. What stops a barely-read value from quietly
    becoming an authoritative fact is that the number travels with the finding,
    so a client can show it. If a confidence threshold is ever introduced it
    must come from a rule, and this test should be the thing that fails.
    """
    make_extracted_field(
        completed_run, LabelFieldKey.NET_QUANTITY.value, confidence=0.05
    )
    make_rule("CONF-003", field_key=LabelFieldKey.NET_QUANTITY.value)

    check = engine.evaluate(completed_run)

    finding = _findings_by_code(check)["CONF-003"]
    assert finding.status == ComplianceFinding.Status.PASSED
    assert finding.extracted_confidence == pytest.approx(0.05)


def test_validator_diagnostics_are_kept(empty_run, make_rule):
    """`details` was computed and discarded before findings existed."""
    make_rule("DETAIL-001", field_key=LabelFieldKey.NET_QUANTITY.value, verified=True)

    check = engine.evaluate(empty_run)

    details = _findings_by_code(check)["DETAIL-001"].details
    assert details["extraction_status"] == empty_run.status
    assert details["is_placeholder_engine"] is False


# --- the unverified-rule safeguard is visible in the record ------------------


def test_a_downgraded_failure_is_recorded_as_inconclusive_and_says_so(
    completed_run, make_rule
):
    """The safeguard fires; the finding shows that it fired.

    Without the flag this is indistinguishable from a rule that could not be
    decided because the photograph was bad - which is a different problem with
    a different remedy.
    """
    make_rule("UNVERIFIED-001", field_key=LabelFieldKey.NET_QUANTITY.value,
              verified=False)

    check = engine.evaluate(completed_run)

    finding = _findings_by_code(check)["UNVERIFIED-001"]
    assert finding.status == ComplianceFinding.Status.INCONCLUSIVE
    assert finding.downgraded_from_failed is True
    assert finding.violation is None
    assert check.violations.count() == 0
    assert "has not been verified" in finding.message


def test_an_ordinary_inconclusive_outcome_is_not_flagged_as_downgraded(
    empty_run, make_rule
):
    """The flag must mean the safeguard, not "inconclusive for any reason"."""
    make_rule("INC-002", field_key=LabelFieldKey.NET_QUANTITY.value, verified=True)

    check = engine.evaluate(empty_run)

    assert _findings_by_code(check)["INC-002"].downgraded_from_failed is False


# --- the trace did not change the verdict ------------------------------------


def test_recording_findings_did_not_change_the_verdict_logic(
    completed_run, make_rule, make_extracted_field, category
):
    """The counters and the result still match what the buckets say.

    Findings are a record of the decision, not an input to it. If adding them
    had perturbed the verdict, this is where it would show.
    """
    make_extracted_field(completed_run, LabelFieldKey.NET_QUANTITY.value)
    make_rule("V-PASS", field_key=LabelFieldKey.NET_QUANTITY.value)
    make_rule("V-FAIL", field_key=LabelFieldKey.MANUFACTURER_NAME.value,
              verified=True)
    make_rule("V-DOWNGRADE", field_key=LabelFieldKey.BEST_BEFORE.value,
              verified=False)

    check = engine.evaluate(completed_run)

    assert check.result == ComplianceCheck.Result.PARTIALLY_COMPLIANT
    assert (check.rules_passed, check.rules_failed, check.rules_inconclusive) == (
        1,
        1,
        1,
    )

    by_status: dict[str, int] = {}
    for finding in check.findings.all():
        by_status[finding.status] = by_status.get(finding.status, 0) + 1
    assert by_status == {
        ComplianceFinding.Status.PASSED: 1,
        ComplianceFinding.Status.FAILED: 1,
        ComplianceFinding.Status.INCONCLUSIVE: 1,
    }


def test_findings_are_written_in_one_query_regardless_of_rule_count(
    completed_run, make_rule, category, django_assert_max_num_queries
):
    """The trace must not reintroduce the N+1 `test_engine_queries.py` guards.

    Every rule here fails, which is the worst case: a violation and an evidence
    row each, plus the findings. If this fails after a change, findings are
    being inserted one at a time - do not raise the bound to make it pass.
    """
    for index in range(8):
        make_rule(f"BULK-{index:03d}", verified=True, categories=[category])

    with django_assert_max_num_queries(30):
        check = engine.evaluate(completed_run)

    assert check.findings.count() == 8
    assert check.violations.count() == 8
