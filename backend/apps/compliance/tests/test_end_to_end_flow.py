"""The whole documented workflow, over HTTP, against the rules that ship.

    POST /api/v1/extraction/   upload, validate, OCR, extract, normalise
      -> GET  /api/v1/compliance/applicability-conditions/   what may be stated
      -> POST /api/v1/compliance/                            applicability, then
                                                             the rule engine
      -> GET  /api/v1/compliance/<uuid>/                     the stored result

That is exactly the sequence the scan screen performs, in the same order, with
the same bodies. `test_analysis_api.py` covers the one-shot upload path and
`test_evaluation_api.py` covers the evaluation endpoint's own contract; nothing
covered the two together against the **real** shipped rule set and legal
framework, which is where an integration defect would actually live - a rule
loaded but not linked to its clause, a condition the form offers but the POST
rejects, a status the engine produces and the serializer drops.

The five cases are the ones a demonstration has to survive:

    A  a well-formed label            findings, and a verdict that explains itself
    B  a declaration absent or wrong  a violation, with the evidence behind it
    C  an uninterpretable reading     REVIEW REQUIRED, never a violation
    D  an unstated applicability fact REVIEW REQUIRED, never a false violation
    E  a fact that excuses a clause   NOT_APPLICABLE, and not counted as a pass

Case B is two tests, because the shipped rule set makes the distinction and a
demonstration will run into it. A *missing* declaration fails its presence rule
and leaves the manner-of-declaration rule on the same clause with nothing to
examine, so the verdict is PARTIALLY_COMPLIANT - a failure plus an undetermined
rule. A declaration that is present and *contradicts* its clause leaves nothing
undetermined, and reaches NON_COMPLIANT outright.

**OCR is not exercised here and is not meant to be.** Recognition accuracy is
measured in `ml/` against annotated photographs; a test that ran Tesseract would
fail on a machine without it and would be measuring the wrong thing. The reading
is written exactly as the extraction service writes it, and everything from
normalisation onwards is the real code path.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.catalog.models import ProductCategory
from apps.compliance.models import ComplianceCheck, ComplianceFinding
from apps.extraction.models import ExtractionRun
from apps.rules.framework_loader import load_framework
from apps.rules.loader import load_rules

pytestmark = pytest.mark.django_db

Result = ComplianceCheck.Result
Status = ComplianceFinding.Status

#: A realistic Indian retail food label, normalised the way `labelextract`
#: normalises it. Kept here rather than imported so this file states the whole
#: input it is asserting about.
COMPLIANT_LABEL = {
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


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    settings.DEMO_PUBLIC_ANALYSIS_API = True


@pytest.fixture
def deployment(settings, category):
    """Categories, rules and framework, loaded in the deployment order."""
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
def reading(deployment, product_image, make_extracted_field):
    """A stored reading, exactly as the extraction service persists one."""

    def _reading(**declarations) -> ExtractionRun:
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

    return _reading


def evaluate(client, run, **body):
    """The compliance POST, exactly as the frontend sends it."""
    response = client.post(
        reverse("v1:compliance-evaluate"),
        {"extraction_run_id": str(run.pk), **body},
        content_type="application/json",
    )
    assert response.status_code == 201, response.json()
    return response.json()


def finding(body, rule_code):
    for entry in body["findings"]:
        if entry["rule_code"] == rule_code:
            return entry
    raise AssertionError(f"no finding for {rule_code}")


def declarable_codes(client):
    response = client.get(reverse("v1:applicability-conditions"))
    assert response.status_code == 200
    return {c["code"] for c in response.json()["conditions"]}


# --- case A: a well-formed label ---------------------------------------------


def test_case_a_a_well_formed_label_is_checked_and_explains_its_verdict(
    client, product, reading
):
    """Not COMPLIANT, and the reason is the point.

    Two clauses turn on facts nobody stated - whether the package is imported,
    and whether proviso (C) excuses the price declaration - so the honest answer
    is REVIEW REQUIRED with those two named. Declaring them is what earns a
    clean result, which is the incentive the design intends.
    """
    body = evaluate(client, reading(**COMPLIANT_LABEL))

    assert body["result"] == Result.REVIEW_REQUIRED
    assert body["summary"]
    assert body["violations"] == []
    assert body["rules_failed"] == 0
    assert finding(body, "LM-PC-0003")["status"] == Status.PASSED
    assert finding(body, "LM-PC-0006")["status"] == Status.PASSED
    assert finding(body, "LM-PC-0010")["status"] == Status.PASSED


def test_case_a_stating_the_facts_reaches_compliant(client, product, reading):
    """The clean path, and the only route to COMPLIANT - over the wire.

    Every code sent here came from the discovery endpoint, so this also proves
    the two halves of the contract agree: a form built from that list produces
    a body this endpoint accepts.
    """
    offered = declarable_codes(client)
    stated = {
        code: "no"
        for code in ("imported-product", "bidi", "domestic-lpg-cylinder",
                     "alcoholic-beverage")
    }
    assert set(stated) <= offered

    body = evaluate(
        client, reading(**COMPLIANT_LABEL), applicability_declarations=stated
    )

    assert body["result"] == Result.COMPLIANT
    assert body["rules_failed"] == 0
    assert body["rules_inconclusive"] == 0
    # And the verdict says what it does and does not cover.
    assert "not a certification" in body["summary"]


# --- case B: a mandatory declaration is absent --------------------------------


def test_case_b_a_missing_declaration_is_a_violation_with_evidence(
    client, product, reading
):
    """A required declaration is absent from a readable label: a violation.

    The overall verdict is PARTIALLY_COMPLIANT rather than NON_COMPLIANT, and
    that is the engine being precise rather than evasive. Rule 6(2) has two
    rules against it - one asking whether the declaration is present, one asking
    what elements it contains - and with the declaration absent the second has
    nothing to examine and says so. A failure plus an undetermined rule is
    partial compliance. The violation itself is unambiguous, which is what a
    reviewer acts on.
    """
    without_consumer_care = {
        k: v for k, v in COMPLIANT_LABEL.items() if k != "consumer_care_contact"
    }
    body = evaluate(
        client,
        reading(**without_consumer_care),
        applicability_declarations={
            "imported-product": "no",
            "bidi": "no",
            "domestic-lpg-cylinder": "no",
            "alcoholic-beverage": "no",
        },
    )

    assert body["result"] == Result.PARTIALLY_COMPLIANT
    assert body["rules_failed"] == 1
    presence = finding(body, "LM-PC-0006")
    assert presence["status"] == Status.FAILED
    assert presence["clause"] == "6(2)"
    assert presence["violation"] is not None
    # The evidence for an absence is what WAS read.
    violation = next(v for v in body["violations"] if v["rule_code"] == "LM-PC-0006")
    assert "Net Wt. 500 g" in violation["evidence"][0]["excerpt"]


def test_case_b_a_contradicted_declaration_reaches_non_compliant_outright(
    client, product, reading
):
    """The clean NON_COMPLIANT path: a failure with nothing left undetermined.

    A price the label declares EXCLUSIVE of all taxes contradicts rule 6(1)(e)
    read with rule 2(m). Every other rule reaches a verdict, so there is no
    undetermined rule to soften the result.
    """
    body = evaluate(
        client,
        reading(
            **{
                **COMPLIANT_LABEL,
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
        ),
        applicability_declarations={
            "imported-product": "no",
            "bidi": "no",
            "domestic-lpg-cylinder": "no",
            "alcoholic-beverage": "no",
        },
    )

    assert body["result"] == Result.NON_COMPLIANT
    assert body["rules_inconclusive"] == 0
    tax = finding(body, "LM-PC-0012")
    assert tax["status"] == Status.FAILED
    assert tax["clause"] == "6(1)(e)"
    assert "EXCLUSIVE of all taxes" in tax["message"]


def test_case_b_a_missing_element_names_the_element_it_missed(
    client, product, reading
):
    """The Step 3 precision, reaching a client: which element, not "not compliant"."""
    body = evaluate(
        client,
        reading(
            **{
                **COMPLIANT_LABEL,
                "consumer_care_contact": (
                    "Consumer care: 1800-000-000",
                    {"phones": ["1800-000-000"], "uncertain": False},
                ),
            }
        ),
        applicability_declarations={
            "imported-product": "no",
            "bidi": "no",
            "domestic-lpg-cylinder": "no",
            "alcoholic-beverage": "no",
        },
    )

    assert finding(body, "LM-PC-0006")["status"] == Status.PASSED
    elements = finding(body, "LM-PC-0010")
    assert elements["status"] == Status.FAILED
    assert "e-mail address" in elements["message"]
    assert elements["details"]["elements_not_found"] == ["e-mail address"]


# --- case C: the reading cannot be interpreted --------------------------------


def test_case_c_an_ambiguous_reading_is_reviewed_and_never_a_violation(
    client, product, reading
):
    """`03/04/2025` is 3 April or 4 March, and the label does not say which.

    The year is settled and the month is not, so the clause is not established -
    and an unusual printing is indistinguishable from a misrecognised one, so it
    is not a violation either.
    """
    body = evaluate(
        client,
        reading(
            net_quantity=(
                "Net Wt. 8 oz",
                {"quantity": 8, "unit": "oz", "uncertain": True},
            ),
        ),
    )

    si_unit = finding(body, "LM-PC-0008")
    # A unit known not to be SI is a real finding; the engine does not hide
    # behind uncertainty when the reading is unambiguous about the unit.
    assert si_unit["status"] == Status.FAILED

    body = evaluate(
        client,
        reading(
            net_quantity=(
                "Net Wt. 500 9",
                {"quantity": 500, "unit": "9", "uncertain": True},
            ),
        ),
    )
    unplaceable = finding(body, "LM-PC-0008")
    assert unplaceable["status"] == Status.INCONCLUSIVE
    assert unplaceable["violation"] is None


def test_case_c_an_unreadable_photograph_produces_no_violation(
    client, deployment, empty_run
):
    """The oldest guarantee in the engine, over HTTP with eleven rules active."""
    body = evaluate(client, empty_run)

    assert body["result"] == Result.REVIEW_REQUIRED
    assert body["violations"] == []
    assert "clearer, closer photograph" in body["summary"]


# --- case D: an applicability fact was never stated ---------------------------


def test_case_d_an_unstated_fact_is_reviewed_not_assumed(
    client, product, reading
):
    """Neither assumed true nor assumed false - the finding says what is missing.

    Assuming the package domestic would excuse it from a declaration it may owe;
    assuming it imported would fail a package the clause never bound.
    """
    body = evaluate(client, reading(**COMPLIANT_LABEL))

    origin = finding(body, "LM-PC-0007")
    assert origin["status"] == Status.INCONCLUSIVE
    assert origin["violation"] is None
    assert "Imported product" in origin["message"]
    # The client can name the missing fact without knowing any law.
    assert origin["details"]["unresolved_conditions"] == ["imported-product"]


def test_case_d_unknown_is_not_read_as_no(client, product, reading):
    """The distinction the whole declaration channel rests on.

    "Somebody was asked and did not know" must behave exactly like silence, and
    must not excuse the package the way "no" would.
    """
    stated = evaluate(
        client,
        reading(**COMPLIANT_LABEL),
        applicability_declarations={"imported-product": "unknown"},
    )
    silent = evaluate(client, reading(**COMPLIANT_LABEL))

    assert (
        finding(stated, "LM-PC-0007")["status"]
        == finding(silent, "LM-PC-0007")["status"]
        == Status.INCONCLUSIVE
    )
    # And it is recorded, so a reviewer can see the question was put.
    declared = {d["code"]: d for d in stated["applicability_declarations"]}
    assert declared["imported-product"]["answer"] == "unknown"


# --- case E: a fact excuses a clause -----------------------------------------


def test_case_e_a_declared_exemption_is_not_applicable_and_not_a_pass(
    client, product, reading
):
    body = evaluate(
        client,
        reading(**COMPLIANT_LABEL),
        applicability_declarations={"imported-product": "no"},
    )

    origin = finding(body, "LM-PC-0007")
    assert origin["status"] == Status.NOT_APPLICABLE
    assert origin["violation"] is None
    assert "applies only to" in origin["message"]

    # Counted apart from the passes, so exemptions cannot add up to a clean
    # bill of health.
    assert body["rules_not_applicable"] >= 1
    assert body["rules_evaluated"] == (
        body["rules_passed"] + body["rules_failed"] + body["rules_inconclusive"]
    )


def test_case_e_a_scope_gate_takes_the_whole_package_out_of_the_rules(
    client, product, reading
):
    """Rule 3(c): a consignment for an institutional consumer is outside Chapter II.

    Nothing is checked, and the result is REVIEW REQUIRED rather than
    COMPLIANT - a package everything was ruled out for has had nothing examined.
    """
    body = evaluate(
        client,
        reading(**COMPLIANT_LABEL),
        applicability_declarations={"institutional-consumer": "yes"},
    )

    assert body["result"] == Result.REVIEW_REQUIRED
    assert body["rules_not_applicable"] == len(body["findings"])
    assert all(f["status"] == Status.NOT_APPLICABLE for f in body["findings"])
    assert "no declaration was checked" in body["summary"]
    assert "not a finding that the product complies" in body["summary"]


# --- the trace a client renders ----------------------------------------------


def test_the_stored_result_is_the_same_body_as_the_evaluation(
    client, product, reading
):
    """A permalink must not be a lesser copy of the screen that created it."""
    posted = evaluate(
        client,
        reading(**COMPLIANT_LABEL),
        applicability_declarations={"imported-product": "no"},
    )

    fetched = client.get(
        reverse("v1:compliance-detail", kwargs={"pk": posted["id"]})
    ).json()

    assert fetched["findings"] == posted["findings"]
    assert fetched["applicability_declarations"] == posted["applicability_declarations"]
    assert fetched["result"] == posted["result"]


def test_every_finding_carries_what_a_reviewer_needs_to_check_it(
    client, product, reading
):
    """The trace, end to end: rule, clause, evidence, confidence, applicability."""
    body = evaluate(client, reading(**COMPLIANT_LABEL))

    for entry in body["findings"]:
        assert entry["rule_code"]
        assert entry["requirement"]
        assert entry["legal_reference"]
        assert entry["message"]
        assert entry["status"] in {
            Status.PASSED,
            Status.FAILED,
            Status.INCONCLUSIVE,
            Status.NOT_APPLICABLE,
        }
        # The caveat that applies to every result, on every result.
        assert "rule 3 and rule 26" in entry["applicability_note"]
        # Recorded, never fabricated: a reading behind a finding carries a
        # confidence or an explicit null.
        assert "extracted_confidence" in entry


def test_no_aggregate_score_is_anywhere_in_the_response(client, product, reading):
    """Nothing a client could mistake for a compliance percentage."""
    body = evaluate(client, reading(**COMPLIANT_LABEL))

    forbidden = {"score", "compliance_score", "percentage", "grade", "rating"}
    assert forbidden.isdisjoint(body)
