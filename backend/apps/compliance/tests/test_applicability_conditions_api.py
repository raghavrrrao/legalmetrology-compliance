"""`GET /api/v1/compliance/applicability-conditions/` - the declarable facts.

The discovery half of the POST's contract. Without it a client builds its
declaration form from a copy of the legal condition catalogue in JavaScript,
which goes stale the moment a clause is transcribed or a rule is deactivated,
with nothing failing.

So what these tests pin is not "the endpoint returns JSON" but the three
filters that keep it honest and short:

    only facts a SUBMITTER can state
    only facts that bear on something this installation actually evaluates
    only active rows

and the property that makes it safe: a client can render the list without
knowing any law, because every explanatory string on it comes from the loaded
framework rather than from the client.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.catalog.models import ProductCategory
from apps.rules.framework_loader import load_framework
from apps.rules.loader import load_rules
from apps.rules.models import ApplicabilityCondition, ComplianceRule

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    """Read with the demo switch on; its off position is asserted below."""
    settings.DEMO_PUBLIC_ANALYSIS_API = True


@pytest.fixture
def framework(settings, category):
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


def _get(client):
    return client.get(reverse("v1:applicability-conditions"))


def _codes(body):
    return {condition["code"] for condition in body["conditions"]}


# --- what comes back ---------------------------------------------------------


def test_the_shipped_framework_yields_the_declarable_facts(client, framework):
    """A short, specific list - not the whole condition catalogue.

    The framework defines 39 conditions. Most are `not_determinable` and a few
    are answered from the product category, and asking a submitter about any of
    those would be theatre at best and a way to switch off a check at worst.
    """
    body = _get(client).json()

    assert body["framework_loaded"] is True
    codes = _codes(body)
    assert "imported-product" in codes
    assert "bidi" in codes
    assert "institutional-consumer" in codes
    assert len(codes) < ApplicabilityCondition.objects.count()


def test_a_fact_the_system_cannot_establish_is_never_offered(client, framework):
    """The safeguard, at the discovery layer.

    `rule-33-relaxation-granted` is recorded as not determinable, and the
    resolver answers UNKNOWN for it whatever anybody states. Offering it on a
    form would invite a submitter to believe they had switched off a check.
    """
    codes = _codes(_get(client).json())

    assert "rule-33-relaxation-granted" not in codes
    assert "genetically-modified-food" not in codes


def test_a_fact_answered_by_the_product_category_is_not_asked_again(
    client, framework
):
    """`food-article` comes from `category_code`, which is its own field."""
    assert "food-article" not in _codes(_get(client).json())


def test_only_facts_bearing_on_an_evaluated_clause_are_offered(client, framework):
    """A condition attached to nothing evaluated cannot change an outcome.

    `perishable-commodity` is user-declarable and is on rule 6(1)(da), which
    has no executable rule behind it. Asking about it would imply the answer
    mattered.
    """
    assert "perishable-commodity" not in _codes(_get(client).json())


def test_deactivating_the_last_rule_behind_a_clause_withdraws_its_question(
    client, framework
):
    """The list follows what is loaded, which is the whole point of serving it.

    `seeds-certified` bears only on rule 6(1)(d). With both of that clause's
    rules inactive there is nothing for an answer to affect, and the question
    disappears without anyone editing a form.
    """
    assert "seeds-certified" in _codes(_get(client).json())

    ComplianceRule.objects.filter(code__in=["LM-PC-0004", "LM-PC-0011"]).update(
        is_active=False
    )

    assert "seeds-certified" not in _codes(_get(client).json())


# --- what each entry carries -------------------------------------------------


def test_a_scope_gate_is_distinguished_from_a_clause_exemption(client, framework):
    """They behave differently and a form that ran them together would mislead.

    Declaring an institutional consumer takes the package out of Chapter II and
    NOTHING is checked. Declaring bidi excuses two clauses and leaves the rest
    of the check standing.
    """
    conditions = {c["code"]: c for c in _get(client).json()["conditions"]}

    assert conditions["institutional-consumer"]["scope"] == "rules_scope"
    assert conditions["bidi"]["scope"] == "clause"


def test_each_condition_names_the_clauses_and_rules_it_would_affect(
    client, framework
):
    """So a client can say what an answer does without knowing any law."""
    bidi = {c["code"]: c for c in _get(client).json()["conditions"]}["bidi"]

    affected = {entry["clause"]: entry for entry in bidi["affects"]}
    assert set(affected) == {"6(1)(d)", "6(1)(e)"}
    assert affected["6(1)(e)"]["mode"] == "exempts"
    assert affected["6(1)(e)"]["mode_display"]
    # The framework's own note on the link, not a sentence composed here.
    assert "proviso" in affected["6(1)(e)"]["note"].lower()
    assert "LM-PC-0005" in affected["6(1)(e)"]["rule_codes"]


def test_the_three_answers_and_their_meanings_come_from_the_api(
    client, framework
):
    """UNKNOWN must stay a distinct choice, and must not be described locally.

    A client that writes its own explanation of UNKNOWN will eventually write a
    wrong one - most likely that it means "no".
    """
    body = _get(client).json()

    assert body["conditions"][0]["answers"] == ["yes", "no", "unknown"]
    assert set(body["answer_semantics"]) == {"yes", "no", "unknown"}
    assert "never read as 'no'" in body["answer_semantics"]["unknown"]
    assert "REVIEW REQUIRED" in body["answer_semantics"]["unknown"]


def test_every_offered_code_is_accepted_by_the_evaluation_endpoint(
    client, framework, completed_run
):
    """The two halves of the contract must agree.

    A form built from this list must not be able to produce a 400. This walks
    every offered code through the POST that consumes it.
    """
    codes = _codes(_get(client).json())
    response = client.post(
        reverse("v1:compliance-evaluate"),
        {
            "extraction_run_id": str(completed_run.pk),
            "applicability_declarations": {code: "unknown" for code in codes},
        },
        content_type="application/json",
    )

    assert response.status_code == 201, response.json()


# --- deployment states and permissions ---------------------------------------


def test_an_unloaded_framework_says_so_rather_than_looking_empty(client):
    """An empty list and a missing framework look identical without this."""
    body = _get(client).json()

    assert body["conditions"] == []
    assert body["framework_loaded"] is False


def test_the_endpoint_denies_anonymous_callers_by_default(
    client, framework, settings
):
    """Adding an endpoint must not add an unguarded one."""
    settings.DEMO_PUBLIC_ANALYSIS_API = False

    response = _get(client)

    assert response.status_code in (401, 403)


def test_an_authenticated_user_is_allowed_with_the_switch_off(
    client, framework, settings, user
):
    settings.DEMO_PUBLIC_ANALYSIS_API = False
    client.force_login(user)

    assert _get(client).status_code == 200
