"""The health endpoint, which is what a teammate checks first when stuck."""

import pytest
from django.urls import reverse
from rest_framework import status


@pytest.mark.django_db
def test_health_endpoint_reports_ok(client):
    response = client.get(reverse("v1:health"))

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["status"] == "ok"
    assert body["api_version"] == "v1"
    assert body["dependencies"]["database"] == "ok"
    assert body["dependencies"]["extraction_engine"] == "ok"


@pytest.mark.django_db
def test_health_endpoint_is_public(client):
    """It must answer before login: the frontend calls it on first load."""
    response = client.get(reverse("v1:health"))
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_health_reports_the_extraction_engine_as_a_placeholder(client):
    """The system must never hide that it is running on wiring, not OCR.

    When a real engine is configured this assertion is expected to change - and
    changing it should be a deliberate, reviewed act.
    """
    body = client.get(reverse("v1:health")).json()

    assert body["extraction_engine"]["name"] == "null-engine"
    assert body["extraction_engine"]["is_placeholder"] is True


@pytest.mark.django_db
def test_health_reports_zero_verified_rules_on_a_fresh_database(client):
    """A fresh clone has no verified rules, and the endpoint says so.

    This is what tells the team the compliance engine cannot yet find anything
    non-compliant, without them having to read the code to find out.
    """
    body = client.get(reverse("v1:health")).json()

    assert body["compliance_rules"]["verified"] == 0
    assert body["compliance_rules"]["active_total"] == 0
    assert body["compliance_rules"]["applicability_conditions"] == 0


@pytest.mark.django_db
def test_health_does_not_leak_configuration(client):
    """It must be useful to us without being useful to a scanner."""
    raw = client.get(reverse("v1:health")).content.decode()

    for leaked in ("SECRET", "PASSWORD", "postgres", "DATABASE", "Traceback"):
        assert leaked not in raw


def test_health_reports_the_applicability_condition_count(client, db):
    """A rule set with no framework behind it must be visible here.

    `load_rules` without `load_legal_framework` leaves a database whose rule
    counts look entirely healthy and whose findings carry no clause, no source
    citation, and - because a clause gated on an undeclared fact then has no
    gate to check - a different verdict. The count is the only thing on this
    endpoint that distinguishes the two states, which is why it is asserted
    rather than left to be noticed.
    """
    from apps.rules.models import ApplicabilityCondition

    body = client.get(reverse("v1:health")).json()
    assert body["compliance_rules"]["applicability_conditions"] == 0

    ApplicabilityCondition.objects.create(
        code="imported-package",
        name="Imported package",
        description="Test row.",
    )

    body = client.get(reverse("v1:health")).json()
    assert body["compliance_rules"]["applicability_conditions"] == 1


# --- can the configured engine actually run? --------------------------------
#
# `is_placeholder` answers "is this wiring?". It does not answer "can this run
# here?", and a deployment fails on the second question far more often than the
# first: the image is built without the Tesseract binary, the pipeline is real
# and reports `is_placeholder: false`, and nothing in the old response
# distinguished that container from a working one until uploads started
# failing. `available` is that second question.


@pytest.mark.django_db
def test_health_reports_the_engine_as_available_when_it_can_run(client):
    """The default pipeline has nothing to install, so it must report available."""
    body = client.get(reverse("v1:health")).json()

    assert body["extraction_engine"]["available"] is True
    assert body["extraction_engine"]["detail"] == ""
    assert body["dependencies"]["extraction_engine"] == "ok"


@pytest.mark.django_db
def test_health_is_degraded_when_the_engine_binary_is_missing(client, monkeypatch):
    """A configured engine that cannot run is an outage, and must answer 503.

    This is the deployment failure this assertion exists for: a container built
    without `tesseract` on PATH. The pipeline resolves, so it is not a
    placeholder and not a missing registration - every previous signal on this
    endpoint stays green. Only `available` moves.

    503 rather than 200-with-a-flag because a platform health check reads the
    status code, and a container that cannot perform the one thing it is for
    should not be promoted.
    """
    from apps.extraction.services import extraction_service

    monkeypatch.setattr(
        extraction_service,
        "default_pipeline_status",
        lambda: extraction_service.PipelineStatus(
            name="tesseract",
            version="0.3.0",
            is_placeholder=False,
            is_available=False,
            detail="engine_not_available",
        ),
    )

    response = client.get(reverse("v1:health"))
    body = response.json()

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert body["status"] == "degraded"
    assert body["dependencies"]["extraction_engine"] == "unavailable"
    assert body["extraction_engine"]["available"] is False
    # Not a placeholder - which is exactly why `available` had to be added.
    assert body["extraction_engine"]["is_placeholder"] is False
    assert body["extraction_engine"]["detail"] == "engine_not_available"


@pytest.mark.django_db
def test_health_does_not_leak_engine_internals_when_it_fails(client, monkeypatch):
    """`detail` is a short code from the ml/ layer, never a path or traceback.

    The endpoint is public. "The binary is missing" is a fact worth reporting;
    where we looked for it is a fact worth keeping.
    """
    from apps.extraction.services import extraction_service

    def explode():
        raise RuntimeError(r"C:\secret\path\tesseract.exe is missing")

    monkeypatch.setattr(extraction_service, "default_pipeline_status", explode)

    raw = client.get(reverse("v1:health")).content.decode()

    assert "secret" not in raw
    assert "tesseract.exe" not in raw
    assert "Traceback" not in raw
    assert "extraction_service_unavailable" in raw
