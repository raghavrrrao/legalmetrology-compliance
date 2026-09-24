"""`GET /api/v1/rules/` - the inventory of loaded executable rules.

What these tests pin is less "the endpoint returns JSON" than the properties
that keep an inventory from turning into something else:

    every rule is listed, inactive ones included, in a total order
    each row names the rule and nothing a client could evaluate a package with
    it is read-only, guarded like the other legal-framework metadata endpoint
    it carries no user data, and reading it changes nothing the engine reads

and, against the rule files that actually ship, that it reports the rows the
database holds rather than a copy of what the repository says.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest
from django.db import connection
from django.forms.models import model_to_dict
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse
from rest_framework.throttling import AnonRateThrottle

from apps.catalog.models import ProductCategory
from apps.compliance.models import ComplianceCheck, ComplianceFinding
from apps.compliance.services import engine
from apps.rules.api.views import ComplianceRuleListView
from apps.rules.framework_loader import load_framework
from apps.rules.loader import load_rules
from apps.rules.models import (
    AutomationClass,
    ComplianceRule,
    DetectionMethod,
    ImplementationStatus,
    LegalRule,
    RuleRequirement,
    VerificationStatus,
)

pytestmark = pytest.mark.django_db

#: The agreed contract, field for field. A change here is a change to a public
#: response shape and belongs in docs/api.md in the same commit.
DOCUMENTED_FIELDS = {
    "code",
    "title",
    "legal_reference",
    "clause",
    "source_status",
    "is_active",
    "effective_from",
    "effective_to",
}

#: On the model, and deliberately never on the response - see
#: `ComplianceRuleInventorySerializer` for why each one is left out.
EXCLUDED_FIELDS = {
    "id",
    "requirement",
    "source_note",
    "severity",
    "check_type",
    "parameters",
    "applies_to_categories",
    "requires_applicability_conditions",
    "rule_requirement",
    "created_at",
    "updated_at",
}


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    """Read with the demo switch on; its off position is asserted below."""
    settings.DEMO_PUBLIC_ANALYSIS_API = True


@pytest.fixture
def make_requirement(db):
    """A clause-level requirement, under a rule of its own number."""

    def _make(clause: str = "6(1)(c)", **kwargs) -> RuleRequirement:
        number = clause.split("(", 1)[0]
        legal_rule, _ = LegalRule.objects.get_or_create(
            rule_number=number,
            defaults={
                "sort_key": LegalRule.build_sort_key(number),
                "title": f"Rule {number}",
                "automation_class": AutomationClass.PARTIALLY_AUTOMATABLE,
            },
        )
        return RuleRequirement.objects.create(
            rule=legal_rule,
            clause=clause,
            title=kwargs.pop("title", f"Requirement {clause}"),
            requirement=kwargs.pop("requirement", "A test requirement."),
            detection_method=DetectionMethod.OCR,
            automation_class=AutomationClass.IMAGE_AUTOMATABLE,
            implementation_status=ImplementationStatus.IMPLEMENTED,
            verification_status=VerificationStatus.VERIFIED,
            source_note="Fixture requirement.",
            **kwargs,
        )

    return _make


def _list(client, **params):
    return client.get(reverse("v1:rule-list"), params)


def _row(body: dict, code: str) -> dict:
    matches = [row for row in body["results"] if row["code"] == code]
    assert len(matches) == 1, f"{code} listed {len(matches)} times"
    return matches[0]


# --- the route and the envelope -----------------------------------------------


def test_the_route_is_the_reserved_rules_prefix():
    assert reverse("v1:rule-list") == "/api/v1/rules/"
    assert resolve("/api/v1/rules/").func.view_class is ComplianceRuleListView


def test_an_empty_rule_set_is_an_empty_page_not_an_error(client):
    """A server that never ran `load_rules` says so with a zero, not a 404."""
    response = _list(client)

    assert response.status_code == 200
    assert response.json() == {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    }


def test_the_envelope_is_the_standard_paginated_one(client, make_rule):
    make_rule("LM-PC-0001")

    body = _list(client).json()

    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 1


def test_a_row_carries_exactly_the_documented_fields(client, make_rule):
    make_rule("LM-PC-0001")

    (row,) = _list(client).json()["results"]

    assert set(row) == DOCUMENTED_FIELDS


def test_validator_internals_and_applicability_are_not_exposed(
    client, make_rule, category
):
    """Nothing a client could evaluate a package with, under any key.

    Checked against the raw body as well as the keys: a value leaking under a
    renamed field would pass a key check and fail this one.
    """
    rule = make_rule(
        "LM-PC-0001",
        check_type="field_presence",
        parameters={"field_key": "net_quantity", "threshold_marker": 7931.25},
        requirement="Requirement wording marker 5b1e.",
        requires_applicability_conditions=True,
        categories=[category],
    )
    # `make_rule` writes its own note; this one is recognisable in a body.
    ComplianceRule.objects.filter(pk=rule.pk).update(
        source_note="Verified by reviewer marker c0ffee against the Gazette."
    )

    response = _list(client)
    (row,) = response.json()["results"]
    raw = response.content.decode()

    assert not set(row) & EXCLUDED_FIELDS
    for leaked in (
        "field_presence",
        "net_quantity",
        "threshold_marker",
        "7931.25",
        "marker 5b1e",
        "marker c0ffee",
        category.code,
    ):
        assert leaked not in raw, f"{leaked!r} reached the rule inventory"


# --- methods ---------------------------------------------------------------------


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_write_methods_are_rejected_and_change_nothing(client, make_rule, method):
    """Read-only: rules are loaded from files, never edited over the API."""
    rule = make_rule("LM-PC-0001")
    before = model_to_dict(ComplianceRule.objects.get(pk=rule.pk))

    response = getattr(client, method)(
        reverse("v1:rule-list"),
        {"code": "LM-PC-9999", "title": "Injected", "is_active": False},
        content_type="application/json",
    )

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert ComplianceRule.objects.count() == 1
    assert model_to_dict(ComplianceRule.objects.get(pk=rule.pk)) == before


def test_only_read_methods_are_advertised(client):
    response = client.post(reverse("v1:rule-list"))

    allowed = {method.strip() for method in response["Allow"].split(",")}
    assert allowed == {"GET", "HEAD", "OPTIONS"}


def test_options_describes_no_write_action(client):
    """DRF lists an `actions` schema only for a method that accepts input."""
    response = client.options(reverse("v1:rule-list"))

    assert response.status_code == 200
    assert "actions" not in response.json()


def test_head_is_answered_like_get(client, make_rule):
    make_rule("LM-PC-0001")

    assert client.head(reverse("v1:rule-list")).status_code == 200


# --- what each row says ----------------------------------------------------------


def test_results_are_ordered_by_code(client, make_rule):
    for code in ("LM-PC-0010", "LM-PC-0002", "LM-PC-0012", "LM-PC-0001"):
        make_rule(code)

    codes = [row["code"] for row in _list(client).json()["results"]]

    assert codes == ["LM-PC-0001", "LM-PC-0002", "LM-PC-0010", "LM-PC-0012"]


def test_active_and_inactive_rules_are_both_listed(client, make_rule):
    """A rule recorded but not evaluated is listed, and says so."""
    make_rule("LM-PC-0001", is_active=True)
    make_rule("LM-PC-0002", is_active=False)

    body = _list(client).json()

    assert body["count"] == 2
    assert _row(body, "LM-PC-0001")["is_active"] is True
    assert _row(body, "LM-PC-0002")["is_active"] is False


def test_active_means_the_flag_not_the_window_or_the_category(
    client, make_rule, category
):
    """Whether an active rule runs for a package is the engine's question.

    A rule whose window has closed, and one targeting a category no product
    has, are still listed with their flag as stored - the inventory reports
    rows, it does not pre-compute applicability.
    """
    other = ProductCategory.objects.create(code="packaged-other", name="Other")
    make_rule(
        "LM-PC-0001",
        effective_from=datetime.date(2011, 4, 1),
        effective_to=datetime.date(2012, 1, 1),
    )
    make_rule("LM-PC-0002", categories=[other])

    body = _list(client).json()

    assert body["count"] == 2
    assert _row(body, "LM-PC-0001")["is_active"] is True
    assert _row(body, "LM-PC-0002")["is_active"] is True


def test_source_status_is_reported_as_stored(client, make_rule):
    make_rule("LM-PC-0001", verified=True)
    make_rule("LM-PC-0002", verified=False)

    body = _list(client).json()

    assert _row(body, "LM-PC-0001")["source_status"] == "verified"
    assert _row(body, "LM-PC-0002")["source_status"] == "unverified"


def test_legal_reference_is_reported_verbatim_and_blank_stays_blank(
    client, make_rule
):
    """A blank reference means "not established" and must not become null or a guess."""
    reference = (
        "Rule 6(1)(c) of the Legal Metrology (Packaged Commodities) Rules, 2011"
    )
    make_rule("LM-PC-0001", legal_reference=reference)
    make_rule("LM-PC-0002", legal_reference="")

    body = _list(client).json()

    assert _row(body, "LM-PC-0001")["legal_reference"] == reference
    assert _row(body, "LM-PC-0002")["legal_reference"] == ""


def test_title_is_reported_as_stored(client, make_rule):
    make_rule("LM-PC-0001", title="Net quantity of the commodity")

    (row,) = _list(client).json()["results"]

    assert row["title"] == "Net quantity of the commodity"


def test_a_linked_requirement_reports_its_clause(client, make_rule, make_requirement):
    make_rule("LM-PC-0001", rule_requirement=make_requirement("6(1)(aa)"))

    (row,) = _list(client).json()["results"]

    assert row["clause"] == "6(1)(aa)"


def test_an_unlinked_rule_reports_a_null_clause_never_a_derived_one(
    client, make_rule
):
    """No requirement, no clause - even when the reference text names one.

    Reading "6(1)(c)" out of `legal_reference` would present a guess as a
    mapping to the legal framework that does not exist.
    """
    make_rule(
        "LM-PC-0001",
        legal_reference=(
            "Rule 6(1)(c) of the Legal Metrology (Packaged Commodities) Rules, 2011"
        ),
        rule_requirement=None,
    )

    (row,) = _list(client).json()["results"]

    assert row["clause"] is None


def test_effective_dates_are_iso_dates_or_null(client, make_rule):
    make_rule(
        "LM-PC-0001",
        effective_from=datetime.date(2011, 4, 1),
        effective_to=datetime.date(2030, 12, 31),
    )
    make_rule("LM-PC-0002", effective_from=None, effective_to=None)

    body = _list(client).json()

    dated = _row(body, "LM-PC-0001")
    assert dated["effective_from"] == "2011-04-01"
    assert dated["effective_to"] == "2030-12-31"
    open_ended = _row(body, "LM-PC-0002")
    assert open_ended["effective_from"] is None
    assert open_ended["effective_to"] is None


# --- pagination --------------------------------------------------------------------


def _make_rules(make_rule, count: int) -> list[str]:
    codes = [f"LM-PC-{number:04d}" for number in range(1, count + 1)]
    for code in reversed(codes):
        make_rule(code)
    return codes


def test_the_page_size_can_be_chosen_and_the_count_is_the_total(client, make_rule):
    _make_rules(make_rule, 5)

    body = _list(client, page_size=2).json()

    assert body["count"] == 5
    assert len(body["results"]) == 2


def test_the_pages_together_are_the_whole_inventory_in_order(client, make_rule):
    codes = _make_rules(make_rule, 5)

    seen = []
    for page in (1, 2, 3):
        body = _list(client, page_size=2, page=page).json()
        seen.extend(row["code"] for row in body["results"])

    assert seen == codes


def test_next_and_previous_walk_the_pages(client, make_rule):
    _make_rules(make_rule, 5)

    first = _list(client, page_size=2).json()
    last = _list(client, page_size=2, page=3).json()

    assert first["previous"] is None
    assert first["next"] is not None and "page=2" in first["next"]
    assert last["next"] is None
    assert last["previous"] is not None


def test_the_default_page_size_is_the_shared_one(client, make_rule):
    _make_rules(make_rule, 21)

    body = _list(client).json()

    assert body["count"] == 21
    assert len(body["results"]) == 20


def test_a_page_past_the_end_is_a_404_in_the_standard_envelope(client, make_rule):
    _make_rules(make_rule, 2)

    response = _list(client, page=5)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def _queries_for_listing(client) -> int:
    with CaptureQueriesContext(connection) as captured:
        assert _list(client).status_code == 200
    return len(captured.captured_queries)


def test_listing_does_not_issue_a_query_per_rule(client, make_rule, make_requirement):
    """`clause` is joined in, not looked up per row.

    If this fails, the `select_related` in the view has gone. Do not raise the
    bound to make it pass.
    """
    for code in ("LM-PC-0001", "LM-PC-0002"):
        make_rule(code, rule_requirement=make_requirement(f"6(1)({code[-1]})"))
    with_two = _queries_for_listing(client)

    for number in range(3, 13):
        make_rule(
            f"LM-PC-{number:04d}",
            rule_requirement=make_requirement(f"13({number})"),
        )
    with_twelve = _queries_for_listing(client)

    assert with_two == with_twelve
    assert with_twelve <= 2


# --- permissions -------------------------------------------------------------------


def test_the_inventory_denies_anonymous_callers_by_default(
    client, make_rule, settings
):
    """Adding an endpoint must not add an unguarded one."""
    settings.DEMO_PUBLIC_ANALYSIS_API = False
    make_rule("LM-PC-0001")

    response = _list(client)

    assert response.status_code in (401, 403)
    assert response.json()["error"]["code"] in (
        "not_authenticated",
        "permission_denied",
    )


def test_an_authenticated_user_is_allowed_with_the_switch_off(
    client, make_rule, settings, user
):
    settings.DEMO_PUBLIC_ANALYSIS_API = False
    client.force_login(user)
    make_rule("LM-PC-0001")

    response = _list(client)

    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_the_demo_switch_opens_the_inventory_to_anonymous_callers(
    client, make_rule, settings
):
    """The documented relaxation, asserted in its on position too."""
    settings.DEMO_PUBLIC_ANALYSIS_API = True
    make_rule("LM-PC-0001")

    assert _list(client).status_code == 200


def test_the_demo_switch_does_not_open_writes(client, settings):
    """Anonymous read is the whole of what the switch adds here."""
    settings.DEMO_PUBLIC_ANALYSIS_API = True

    response = client.post(
        reverse("v1:rule-list"), {"code": "X"}, content_type="application/json"
    )

    assert response.status_code == 405
    assert ComplianceRule.objects.count() == 0


def test_anonymous_reads_are_still_rate_limited(client, make_rule, monkeypatch):
    """Opened by the demo switch, metered by the anonymous throttle all the same.

    Set where DRF actually reads the rate - see the matching test in
    `apps/core/tests/test_demo_mode_scope.py` for why REST_FRAMEWORK is not it.
    """
    monkeypatch.setitem(AnonRateThrottle.THROTTLE_RATES, "anon", "2/min")
    make_rule("LM-PC-0001")

    statuses = [_list(client).status_code for _ in range(4)]

    assert statuses[0] == 200
    assert 429 in statuses, statuses


# --- no user data, and no effect on evaluation -------------------------------------


def test_every_caller_sees_the_same_inventory(client, make_rule, user):
    """Nothing here is scoped to a caller, because nothing here belongs to one."""
    make_rule("LM-PC-0001")
    make_rule("LM-PC-0002", is_active=False)

    anonymous = _list(client).json()
    client.force_login(user)
    signed_in = _list(client).json()

    assert anonymous == signed_in


def test_no_inspection_data_is_exposed(
    client, make_rule, completed_run, product, user
):
    """A stored inspection - image, reading, result - never reaches this list.

    The check is created by the real engine, requested by a named user, so every
    kind of private row exists: the upload, the reading, the result and its
    findings. The inventory must still be exactly the rule rows.
    """
    make_rule("LM-PC-0001")
    check = engine.evaluate(completed_run, product=product, requested_by=user)
    assert ComplianceFinding.objects.filter(compliance_check=check).exists()
    image = completed_run.image

    for as_user in (False, True):
        if as_user:
            client.force_login(user)
        response = _list(client)
        raw = response.content.decode()

        assert response.json()["count"] == ComplianceRule.objects.count() == 1
        for private in (
            str(check.pk),
            str(completed_run.pk),
            str(image.pk),
            image.original_filename,
            image.checksum_sha256,
            completed_run.recognised_text,
            user.username,
            check.result,
        ):
            assert private not in raw, f"{private!r} reached the rule inventory"


def test_listing_rules_changes_nothing_the_engine_reads(
    client, make_rule, make_requirement
):
    """A read is a read: every rule row, and the absence of checks, survive it."""
    make_rule("LM-PC-0001", rule_requirement=make_requirement("6(1)(c)"))
    make_rule("LM-PC-0002", is_active=False)
    before = [
        (model_to_dict(rule), rule.updated_at)
        for rule in ComplianceRule.objects.order_by("code")
    ]

    _list(client)
    _list(client, page_size=1, page=2)

    after = [
        (model_to_dict(rule), rule.updated_at)
        for rule in ComplianceRule.objects.order_by("code")
    ]
    assert after == before
    assert ComplianceCheck.objects.count() == 0


def test_the_engine_concludes_the_same_before_and_after_a_listing(
    client, make_rule, completed_run, product
):
    """The endpoint is beside the engine, not in front of it."""
    make_rule("LM-PC-0001", field_key="net_quantity")
    make_rule("LM-PC-0002", field_key="mrp", is_active=False)

    def outcome():
        check = engine.evaluate(completed_run, product=product)
        return check.result, sorted(
            check.findings.values_list("rule_code", "status")
        )

    first = outcome()
    _list(client)
    second = outcome()

    assert first == second
    # And the inactive rule the inventory lists was not evaluated either time.
    assert all(code != "LM-PC-0002" for code, _ in first[1])


# --- the rules that actually ship ---------------------------------------------------


@pytest.fixture
def shipped(settings, category):
    """The real taxonomy, rule files and framework, in deployment order."""
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


def _definition_files(settings) -> dict[str, dict]:
    files = sorted(Path(settings.RULES_DEFINITIONS_DIR).glob("*.json"))
    assert files, "no rule definition files found - the test would be vacuous"
    definitions = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    return {definition["code"]: definition for definition in definitions}


def test_the_shipped_rules_are_served_as_the_database_holds_them(client, shipped):
    """Every loaded row, field for field, from the rows - not from a fixture."""
    body = _list(client, page_size=100).json()
    rows = {row["code"]: row for row in body["results"]}

    stored = ComplianceRule.objects.select_related("rule_requirement").order_by("code")
    assert body["count"] == stored.count()
    assert [row["code"] for row in body["results"]] == [rule.code for rule in stored]
    for rule in stored:
        row = rows[rule.code]
        assert row["title"] == rule.title
        assert row["legal_reference"] == rule.legal_reference
        assert row["source_status"] == rule.source_status
        assert row["is_active"] is rule.is_active
        assert row["clause"] == (
            rule.rule_requirement.clause if rule.rule_requirement else None
        )
        assert row["effective_from"] == (
            rule.effective_from.isoformat() if rule.effective_from else None
        )
        assert row["effective_to"] == (
            rule.effective_to.isoformat() if rule.effective_to else None
        )


def test_the_shipped_rules_match_the_repository_definitions(client, shipped, settings):
    """What the files say is what a freshly loaded server reports.

    Including the inactive one: LM-PC-0002 ships switched off, and the
    inventory must say so rather than leave it out.
    """
    definitions = _definition_files(settings)
    body = _list(client, page_size=100).json()

    assert [row["code"] for row in body["results"]] == sorted(definitions)
    for row in body["results"]:
        definition = definitions[row["code"]]
        assert row["is_active"] is definition["is_active"]
        assert row["source_status"] == definition["source_status"]
        assert row["legal_reference"] == definition["legal_reference"]
    assert _row(body, "LM-PC-0002")["is_active"] is False


def test_the_framework_maps_the_shipped_rules_to_clauses(client, shipped):
    """After `load_legal_framework`, a mapped rule carries the clause it evaluates."""
    body = _list(client, page_size=100).json()

    mapped = [row for row in body["results"] if row["clause"] is not None]
    assert mapped, "the shipped framework maps no rule - the test would be vacuous"
    for row in mapped:
        rule = ComplianceRule.objects.get(code=row["code"])
        assert row["clause"] == rule.rule_requirement.clause
