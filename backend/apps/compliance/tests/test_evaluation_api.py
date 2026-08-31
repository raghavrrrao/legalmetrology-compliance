"""`POST /api/v1/compliance/` - a verdict on a reading that already exists.

This is the second half of the two-step path:

    POST /api/v1/extraction/   -> what does the label say?
    POST /api/v1/compliance/   -> what do the rules make of that?

What is asserted here is the endpoint's contract and the boundary it holds:

- a stored run reaches the existing engine and comes back as a full result;
- the photograph is **not** read again, so the reading the caller was shown and
  the reading the findings cite are the same one;
- the response carries the whole trace - findings, violations, evidence, and
  the confidence behind each reading;
- a caller cannot influence which rules run;
- the ML layer decides nothing: with no rules loaded, a perfectly-read label
  still yields REVIEW_REQUIRED.

Recognition is stubbed where a reading is needed, exactly as the extraction
suites do it, so nothing here depends on an OCR binary.
"""

import uuid

import pytest
from django.urls import reverse

from labelextract.contracts import LabelFieldKey

from apps.compliance.models import ComplianceCheck, ComplianceFinding
from apps.extraction.models import ExtractionRun

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    """Run these tests with the demo switch on.

    Its off position is asserted explicitly in
    `test_the_endpoint_denies_anonymous_callers_by_default`.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = True


def _evaluate(client, run, **extra):
    payload = {"extraction_run_id": str(run.pk), **extra}
    return client.post(
        reverse("v1:compliance-evaluate"), payload, content_type="application/json"
    )


# --- a stored reading reaches the engine -------------------------------------


def test_a_stored_run_can_be_evaluated_and_returns_a_full_result(
    client, completed_run, make_rule, make_extracted_field
):
    make_extracted_field(completed_run, LabelFieldKey.NET_QUANTITY.value)
    make_rule("API-PASS", field_key=LabelFieldKey.NET_QUANTITY.value)

    response = _evaluate(client, completed_run)

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["result"] == ComplianceCheck.Result.COMPLIANT
    assert body["result_display"]
    # The explanation is not decoration: a verdict without it can imply a
    # determination the system did not make.
    assert body["summary"]
    assert body["rules_evaluated"] == 1


def test_evaluating_does_not_read_the_photograph_again(
    client, completed_run, make_rule
):
    """The verdict is drawn from the stored reading, not a fresh one.

    If this ever starts re-running extraction, a finding could cite a value the
    caller was never shown - and the two-step flow would silently stop being
    two steps over the same evidence.
    """
    make_rule("API-NOREREAD", field_key=LabelFieldKey.NET_QUANTITY.value)
    runs_before = ExtractionRun.objects.count()

    body = _evaluate(client, completed_run).json()

    assert ExtractionRun.objects.count() == runs_before
    assert body["extraction"]["id"] == str(completed_run.pk)


def test_the_result_can_be_fetched_back_by_id(client, completed_run, make_rule):
    make_rule("API-FETCH", field_key=LabelFieldKey.NET_QUANTITY.value)
    created = _evaluate(client, completed_run).json()

    response = client.get(
        reverse("v1:compliance-detail", kwargs={"pk": created["id"]})
    )

    assert response.status_code == 200
    assert response.json()["result"] == created["result"]
    assert len(response.json()["findings"]) == len(created["findings"])


def test_evaluating_the_same_run_twice_creates_two_checks(
    client, completed_run, make_rule
):
    """Supported, not a mistake to deduplicate.

    Re-evaluating after the rule set changes is how a result from before a rule
    was loaded stays comparable with one from after.
    """
    make_rule("API-TWICE", field_key=LabelFieldKey.NET_QUANTITY.value)

    first = _evaluate(client, completed_run).json()
    second = _evaluate(client, completed_run).json()

    assert first["id"] != second["id"]
    assert ComplianceCheck.objects.count() == 2


# --- the response carries the whole trace ------------------------------------


def test_the_response_lists_every_rule_that_was_examined(
    client, completed_run, make_rule, make_extracted_field
):
    """Not only the failures. A pass and an undecidable rule are both records."""
    make_extracted_field(completed_run, LabelFieldKey.NET_QUANTITY.value)
    make_rule("T-PASS", field_key=LabelFieldKey.NET_QUANTITY.value)
    make_rule("T-FAIL", field_key=LabelFieldKey.MANUFACTURER_NAME.value,
              verified=True)

    body = _evaluate(client, completed_run).json()

    by_code = {finding["rule_code"]: finding for finding in body["findings"]}
    assert set(by_code) == {"T-PASS", "T-FAIL"}
    assert by_code["T-PASS"]["status"] == ComplianceFinding.Status.PASSED
    assert by_code["T-FAIL"]["status"] == ComplianceFinding.Status.FAILED


def test_a_finding_carries_everything_needed_to_check_it_by_hand(
    client, completed_run, make_rule
):
    make_rule(
        "T-TRACE",
        field_key=LabelFieldKey.NET_QUANTITY.value,
        verified=True,
        title="Fixture rule title",
        requirement="The package must declare a fixture requirement.",
        legal_reference="Fixture reference - not legal text",
        severity="major",
    )

    body = _evaluate(client, completed_run).json()

    finding = body["findings"][0]
    assert finding["title"] == "Fixture rule title"
    assert finding["requirement"] == "The package must declare a fixture requirement."
    assert finding["legal_reference"] == "Fixture reference - not legal text"
    assert finding["check_type"] == "field_presence"
    assert finding["severity"] == "major"
    assert finding["field_key"] == LabelFieldKey.NET_QUANTITY.value
    assert finding["message"]
    # What we did read, as the justification for concluding an absence.
    assert finding["evidence_excerpt"]
    # Failed against a verified rule, so it is also a violation.
    assert finding["violation"] is not None


def test_the_ocr_confidence_reaches_the_api(
    client, completed_run, make_rule, make_extracted_field
):
    """A finding built on an uncertain reading must say so to the client."""
    make_extracted_field(
        completed_run, LabelFieldKey.NET_QUANTITY.value, confidence=0.42
    )
    make_rule("T-CONF", field_key=LabelFieldKey.NET_QUANTITY.value)

    body = _evaluate(client, completed_run).json()

    assert body["findings"][0]["extracted_confidence"] == pytest.approx(0.42)


def test_an_unreported_confidence_is_null_not_zero(
    client, completed_run, make_rule, make_extracted_field
):
    make_extracted_field(
        completed_run, LabelFieldKey.NET_QUANTITY.value, confidence=None
    )
    make_rule("T-NULLCONF", field_key=LabelFieldKey.NET_QUANTITY.value)

    body = _evaluate(client, completed_run).json()

    assert body["findings"][0]["extracted_confidence"] is None


def test_violations_and_findings_stay_consistent(client, completed_run, make_rule):
    """`violations` is unchanged; `findings` is the superset around it."""
    make_rule("T-BOTH", field_key=LabelFieldKey.NET_QUANTITY.value, verified=True)

    body = _evaluate(client, completed_run).json()

    violation = body["violations"][0]
    finding = body["findings"][0]
    assert finding["violation"] == violation["id"]
    assert finding["rule_code"] == violation["rule_code"]
    assert violation["evidence"][0]["excerpt"]


# --- uncertain and missing input ---------------------------------------------


def test_an_unreadable_reading_is_review_required_not_non_compliant(
    client, empty_run, make_rule
):
    """A bad photograph is never reported as a missing declaration.

    This is the single most consequential behaviour in the system, so it is
    asserted at the API boundary as well as in the engine's own suite.
    """
    make_rule("T-EMPTY", field_key=LabelFieldKey.NET_QUANTITY.value, verified=True)

    body = _evaluate(client, empty_run).json()

    assert body["result"] == ComplianceCheck.Result.REVIEW_REQUIRED
    assert body["violations"] == []
    assert body["findings"][0]["status"] == ComplianceFinding.Status.INCONCLUSIVE
    assert body["rules_inconclusive"] == 1


def test_a_missing_declaration_on_a_readable_label_is_a_violation(
    client, completed_run, make_rule
):
    """The other side of the same distinction: read the label, found nothing."""
    make_rule("T-MISSING", field_key=LabelFieldKey.NET_QUANTITY.value, verified=True)

    body = _evaluate(client, completed_run).json()

    assert body["result"] == ComplianceCheck.Result.NON_COMPLIANT
    assert body["findings"][0]["status"] == ComplianceFinding.Status.FAILED


def test_an_unverified_rule_cannot_report_a_package_as_non_compliant(
    client, completed_run, make_rule
):
    """A rule nobody has checked against the source flags for review only."""
    make_rule("T-UNVERIFIED", field_key=LabelFieldKey.NET_QUANTITY.value,
              verified=False)

    body = _evaluate(client, completed_run).json()

    assert body["result"] == ComplianceCheck.Result.REVIEW_REQUIRED
    assert body["violations"] == []
    finding = body["findings"][0]
    assert finding["status"] == ComplianceFinding.Status.INCONCLUSIVE
    assert finding["downgraded_from_failed"] is True


def test_without_a_category_no_conclusion_is_drawn(client, completed_run, settings):
    """Null category is the difference between "checked and clean" and "could
    not know which rules apply"."""
    completed_run.image.product.category = None
    completed_run.image.product.save()

    body = _evaluate(client, completed_run).json()

    assert body["result"] == ComplianceCheck.Result.REVIEW_REQUIRED
    assert body["product_category_code"] is None
    assert body["findings"] == []


def test_a_category_code_is_used_when_the_image_has_no_product(
    client, product_image, category, make_rule
):
    """A run whose image is not linked to a product can still state its commodity."""
    run = ExtractionRun.objects.create(
        image=product_image,
        engine_name="stub",
        engine_version="0.0.0",
        status=ExtractionRun.Status.COMPLETED,
        recognised_text="Some text read from the package",
    )
    product_image.product = None
    product_image.save()
    make_rule("T-CATEGORY", field_key=LabelFieldKey.NET_QUANTITY.value, verified=True)

    body = _evaluate(client, run, category_code=category.code).json()

    assert body["product_category_code"] == category.code
    assert body["findings"][0]["rule_code"] == "T-CATEGORY"


# --- the ML layer decides nothing --------------------------------------------


def test_a_perfectly_read_label_is_not_compliant_when_no_rules_are_loaded(
    client, completed_run, make_extracted_field
):
    """The architectural guarantee, asserted through the API.

    Every declaration was read, with high confidence, and the verdict is still
    REVIEW_REQUIRED - because compliance comes from rules, not from readings.
    An extraction result can never, on its own, clear a package.
    """
    for key in (
        LabelFieldKey.NET_QUANTITY,
        LabelFieldKey.RETAIL_SALE_PRICE,
        LabelFieldKey.MANUFACTURER_NAME,
    ):
        make_extracted_field(completed_run, key.value, confidence=0.99)

    body = _evaluate(client, completed_run).json()

    assert body["result"] == ComplianceCheck.Result.REVIEW_REQUIRED
    assert body["findings"] == []
    assert body["rules_evaluated"] == 0
    # The reading is still reported in full - it is just not a verdict.
    assert len(body["extraction"]["fields_read"]) == 3


def test_the_request_cannot_choose_which_rules_run(
    client, completed_run, make_rule
):
    """Unknown fields are ignored by DRF, so what is asserted is that they
    changed nothing.

    A verdict a client could steer by naming its own rules, severities or
    thresholds would be worth nothing. Applicability comes from the loaded rule
    set and the commodity's category alone.
    """
    make_rule("T-APPLIES", field_key=LabelFieldKey.NET_QUANTITY.value, verified=True)
    make_rule("T-ALSO", field_key=LabelFieldKey.BEST_BEFORE.value, verified=True)

    body = _evaluate(
        client,
        completed_run,
        rule_codes=["T-APPLIES"],
        check_type="field_presence",
        severity="info",
        min_confidence=0.99,
    ).json()

    assert {finding["rule_code"] for finding in body["findings"]} == {
        "T-APPLIES",
        "T-ALSO",
    }


# --- bad requests -------------------------------------------------------------


def test_a_missing_run_id_is_a_400_naming_the_field(client):
    response = client.post(
        reverse("v1:compliance-evaluate"), {}, content_type="application/json"
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "extraction_run_id" in error["details"]


def test_an_unknown_run_id_is_a_400_not_a_500(client):
    response = client.post(
        reverse("v1:compliance-evaluate"),
        {"extraction_run_id": str(uuid.uuid4())},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "extraction_run_id" in response.json()["error"]["details"]
    assert not ComplianceCheck.objects.exists()


def test_a_malformed_run_id_is_a_400(client):
    response = client.post(
        reverse("v1:compliance-evaluate"),
        {"extraction_run_id": "not-a-uuid"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_an_unknown_category_code_is_rejected_rather_than_ignored(
    client, completed_run
):
    """Silently dropping it would look identical to not sending one."""
    response = _evaluate(client, completed_run, category_code="no-such-category")

    assert response.status_code == 400
    assert "category_code" in response.json()["error"]["details"]
    assert not ComplianceCheck.objects.exists()


def test_a_get_on_the_collection_is_a_405_in_the_standard_envelope(client):
    response = client.get(reverse("v1:compliance-evaluate"))

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


# --- permissions --------------------------------------------------------------


def test_the_endpoint_denies_anonymous_callers_by_default(
    client, completed_run, settings
):
    """Adding an endpoint must not add an unguarded one."""
    settings.DEMO_PUBLIC_ANALYSIS_API = False

    response = _evaluate(client, completed_run)

    assert response.status_code in (401, 403)
    assert response.json()["error"]["code"] in (
        "not_authenticated",
        "permission_denied",
    )
    assert not ComplianceCheck.objects.exists()


def test_an_authenticated_user_is_allowed_with_the_switch_off(
    client, completed_run, settings, user
):
    settings.DEMO_PUBLIC_ANALYSIS_API = False
    client.force_login(user)

    response = _evaluate(client, completed_run)

    assert response.status_code == 201
    assert ComplianceCheck.objects.get().requested_by_id == user.pk
