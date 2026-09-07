"""The compliance result body, as the shape a client is entitled to rely on.

`test_findings.py` and `test_finding_legal_context.py` assert what the engine
*records*. These assert what reaches the wire, because a field recorded and not
serialized is invisible to every client, and that failure is silent - the UI
simply renders nothing and nobody notices the legal context is gone.

Four things are pinned here that the frontend depends on and that nothing else
covers:

1. **Every field of a finding a reviewer needs is on the wire**, including the
   four that come from the legal framework rather than from the executable
   rule - clause, source citation, detection method, applicability note.
2. **All four finding statuses survive serialization**, `not_applicable`
   included. It is the one a client is most likely to fold into `passed`.
3. **The declarations behind a result come back with it.** They are a third
   kind of evidence - asserted by a person, not read off a photograph - and
   without them a permalinked result cannot show why a clause was excused.
4. **A raw reading and its normalised interpretation both survive**, neither
   standing in for the other.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.catalog.models import (
    ProductApplicabilityDeclaration,
    ProductCategory,
)
from apps.compliance.services import engine
from apps.rules.framework_loader import load_framework
from apps.rules.loader import load_rules
from apps.rules.models import ApplicabilityCondition

pytestmark = pytest.mark.django_db

Answer = ProductApplicabilityDeclaration.Answer

#: Every key `ComplianceFindingSerializer` declares. Written out rather than
#: read from the serializer, so removing a field from the serializer breaks
#: this test instead of silently changing the contract with it.
FINDING_FIELDS = frozenset(
    {
        "id",
        "rule_code",
        "clause",
        "title",
        "requirement",
        "legal_reference",
        "legal_source_citation",
        "check_type",
        "detection_method",
        "severity",
        "status",
        "downgraded_from_failed",
        "applicability_note",
        "field_key",
        "extracted_raw_value",
        "extracted_normalized_value",
        "extracted_confidence",
        "message",
        "evidence_excerpt",
        "bounding_box",
        "details",
        "violation",
    }
)


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    settings.DEMO_PUBLIC_ANALYSIS_API = True


@pytest.fixture
def shipped(settings, category):
    """The real taxonomy, rules and framework, in deployment order."""
    root = ProductCategory.objects.create(
        code="packaged-commodity", name="Packaged commodity"
    )
    category.parent = root
    category.save()
    ProductCategory.objects.create(
        code="packaged-non-food", name="Packaged non-food", parent=root
    )
    assert load_rules(settings.RULES_DEFINITIONS_DIR).ok
    assert load_framework(settings.RULES_FRAMEWORK_DIR).ok


@pytest.fixture
def label(shipped, product_image, make_extracted_field):
    """A completed reading carrying whichever declarations a test names."""

    def _label(**declarations):
        from apps.extraction.models import ExtractionRun

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


def _fetch(client, check):
    response = client.get(
        reverse("v1:compliance-detail", kwargs={"pk": check.pk})
    )
    assert response.status_code == 200
    return response.json()


def _finding(body, rule_code):
    for finding in body["findings"]:
        if finding["rule_code"] == rule_code:
            return finding
    raise AssertionError(f"no finding for {rule_code} in {body['findings']}")


# --- the finding shape -------------------------------------------------------


def test_every_declared_finding_field_reaches_the_wire(client, product, label):
    check = engine.evaluate(label(net_quantity="Net Wt. 500 g"))

    body = _fetch(client, check)

    assert body["findings"]
    for finding in body["findings"]:
        assert set(finding) == FINDING_FIELDS


def test_a_finding_carries_its_clause_source_and_detection_method(
    client, product, label
):
    """The legal context, without which a finding cannot be audited.

    These four come from the framework rather than from the executable rule, so
    they are the ones that silently vanish if the framework is not loaded or
    the serializer forgets them.
    """
    check = engine.evaluate(label(net_quantity="Net Wt. 500 g"))
    body = _fetch(client, check)

    net_quantity = _finding(body, "LM-PC-0003")
    assert net_quantity["clause"] == "6(1)(c)"
    assert net_quantity["legal_reference"].startswith("Rule 6(1)(c)")
    assert net_quantity["detection_method"] == "ocr"
    assert "rule 3 and rule 26" in net_quantity["applicability_note"]
    # Blank, and legitimately so: rule 6(1)(c) stands as it was made and the
    # framework names an instrument only where an amendment is recorded. A
    # client must render that as "no amending instrument", never as missing
    # data.
    assert net_quantity["legal_source_citation"] == ""

    # A clause that WAS amended carries the notification that did it, which is
    # what a reviewer traces the wording back through.
    price = _finding(body, "LM-PC-0005")
    assert price["clause"] == "6(1)(e)"
    assert price["legal_source_citation"] == "G.S.R. 226(E)"


def test_a_finding_carries_the_raw_reading_and_its_normalised_form(
    client, product, label
):
    """Normalisation is an interpretation; the original has to survive it."""
    check = engine.evaluate(
        label(
            net_quantity=(
                "Net Wt. 500 g",
                {"quantity": 500, "unit": "g", "uncertain": False},
            )
        )
    )

    finding = _finding(_fetch(client, check), "LM-PC-0003")

    assert finding["extracted_raw_value"] == "Net Wt. 500 g"
    assert finding["extracted_normalized_value"]["unit"] == "g"
    assert finding["extracted_confidence"] == pytest.approx(0.94)


def test_an_unreported_confidence_is_null_on_the_wire_not_zero(
    client, product, product_image, make_extracted_field, shipped
):
    from apps.extraction.models import ExtractionRun

    run = ExtractionRun.objects.create(
        image=product_image,
        engine_name="stub",
        engine_version="0.0.0",
        status=ExtractionRun.Status.COMPLETED,
        recognised_text="Net Wt. 500 g",
    )
    make_extracted_field(run, "net_quantity", "Net Wt. 500 g", confidence=None)
    check = engine.evaluate(run)

    finding = _finding(_fetch(client, check), "LM-PC-0003")

    assert finding["extracted_confidence"] is None


# --- all four statuses -------------------------------------------------------


def test_a_passed_and_a_failed_finding_are_both_serialized(
    client, product, label, declare_for
):
    declare_for(product, "imported-product", Answer.NO)
    check = engine.evaluate(label(net_quantity="Net Wt. 500 g"))

    body = _fetch(client, check)

    assert _finding(body, "LM-PC-0003")["status"] == "passed"
    consumer_care = _finding(body, "LM-PC-0006")
    assert consumer_care["status"] == "failed"
    assert consumer_care["violation"] is not None


def test_an_inconclusive_finding_is_serialized_and_carries_no_violation(
    client, product, label
):
    """REVIEW REQUIRED is a first-class outcome, not a soft failure.

    Nothing declares whether this package is imported, so rule 6(1)(aa) cannot
    be decided either way. The finding exists, says so, and is not a violation.
    """
    check = engine.evaluate(label(net_quantity="Net Wt. 500 g"))

    finding = _finding(_fetch(client, check), "LM-PC-0007")

    assert finding["status"] == "inconclusive"
    assert finding["violation"] is None
    assert "Imported product" in finding["message"]


def test_a_not_applicable_finding_is_serialized_as_its_own_status(
    client, product, label, declare_for
):
    """The status a client is most likely to fold into `passed`.

    A domestic package owes no country of origin. Nothing about its
    declarations was examined for that clause, so it is not a pass.
    """
    declare_for(product, "imported-product", Answer.NO)
    check = engine.evaluate(label(net_quantity="Net Wt. 500 g"))

    body = _fetch(client, check)
    finding = _finding(body, "LM-PC-0007")

    assert finding["status"] == "not_applicable"
    assert finding["violation"] is None
    assert "applies only to" in finding["message"]
    assert body["rules_not_applicable"] >= 1


def test_the_not_applicable_count_is_separate_from_the_passed_count(
    client, product, label, declare_for
):
    """Counting an exemption as a pass turns carve-outs into a clean bill."""
    declare_for(product, "imported-product", Answer.NO)
    check = engine.evaluate(label(net_quantity="Net Wt. 500 g"))

    body = _fetch(client, check)

    assert body["rules_evaluated"] == (
        body["rules_passed"] + body["rules_failed"] + body["rules_inconclusive"]
    )
    assert body["rules_not_applicable"] > 0


# --- evidence ----------------------------------------------------------------


def test_a_violation_carries_its_evidence_excerpt(client, product, label):
    """What WAS read is the justification for concluding something was absent."""
    check = engine.evaluate(label(net_quantity="Net Wt. 500 g"))

    body = _fetch(client, check)

    violations = {v["rule_code"]: v for v in body["violations"]}
    assert "LM-PC-0006" in violations
    evidence = violations["LM-PC-0006"]["evidence"]
    assert evidence
    assert "Net Wt. 500 g" in evidence[0]["excerpt"]


def test_a_passing_finding_quotes_the_text_it_was_satisfied_by(
    client, product, label
):
    check = engine.evaluate(label(net_quantity="Net Wt. 500 g"))

    finding = _finding(_fetch(client, check), "LM-PC-0003")

    assert finding["evidence_excerpt"] == "Net Wt. 500 g"


# --- the declarations behind the result --------------------------------------


def test_the_declarations_that_shaped_the_result_come_back_with_it(
    client, product, label, declare_for
):
    """A permalinked result has no other way to show what was asserted.

    Without this a reviewer opening `/result/<id>` a week later sees a clause
    recorded NOT APPLICABLE and no way to learn that somebody declared the
    package to be bidi.
    """
    declare_for(product, "bidi", Answer.YES, note="Declared as bidi by the packer.")
    check = engine.evaluate(label(net_quantity="Net Wt. 500 g"))

    body = _fetch(client, check)

    declared = {d["code"]: d for d in body["applicability_declarations"]}
    assert declared["bidi"]["answer"] == "yes"
    assert declared["bidi"]["answer_display"] == "Yes"
    assert declared["bidi"]["name"]
    assert declared["bidi"]["source"] == "submitter"
    assert declared["bidi"]["note"] == "Declared as bidi by the packer."
    assert declared["bidi"]["stated_before_this_check"] is True


def test_a_declaration_recorded_after_the_check_is_flagged_as_such(
    client, product, label, declare_for
):
    """Declarations hang off the product, not off the check.

    A fact stated after an evaluation is still attached to the product it
    describes, and would otherwise appear beside a result it could not have
    influenced.
    """
    check = engine.evaluate(label(net_quantity="Net Wt. 500 g"))
    declare_for(product, "bidi", Answer.YES)

    body = _fetch(client, check)

    declared = {d["code"]: d for d in body["applicability_declarations"]}
    assert declared["bidi"]["stated_before_this_check"] is False


def test_a_result_with_nothing_declared_returns_an_empty_list(
    client, product, label
):
    """The ordinary case, and the client shows it as 'nothing was stated'."""
    check = engine.evaluate(label(net_quantity="Net Wt. 500 g"))

    assert _fetch(client, check)["applicability_declarations"] == []


def test_declarations_posted_with_an_evaluation_appear_on_its_result(
    client, shipped, completed_run
):
    """End to end, over the wire: POST the fact, read it back on the result."""
    response = client.post(
        reverse("v1:compliance-evaluate"),
        {
            "extraction_run_id": str(completed_run.pk),
            "applicability_declarations": {"imported-product": "no"},
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    declared = {d["code"]: d for d in body["applicability_declarations"]}
    assert declared["imported-product"]["answer"] == "no"


@pytest.fixture
def declare_for(db):
    def _declare(product, code, answer, note=""):
        return ProductApplicabilityDeclaration.objects.create(
            product=product,
            condition=ApplicabilityCondition.objects.get(code=code),
            answer=answer,
            note=note,
        )

    return _declare
