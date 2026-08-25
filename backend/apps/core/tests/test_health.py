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


@pytest.mark.django_db
def test_health_does_not_leak_configuration(client):
    """It must be useful to us without being useful to a scanner."""
    raw = client.get(reverse("v1:health")).content.decode()

    for leaked in ("SECRET", "PASSWORD", "postgres", "DATABASE", "Traceback"):
        assert leaked not in raw
