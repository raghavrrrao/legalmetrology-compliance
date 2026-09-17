"""Automatic product applicability - the classification-to-applicability adapter.

The property under test, stated once: **a classification reaches the rule
engine only as a `Product.category`, only under an accepted policy, only when
no person stated one, and never as a declaration.** Everything else it does is
description - what was proposed, what is in effect, what a person still has to
answer - and description changes no verdict.

The shipped artifact is a ten-product baseline whose wrong held-out answers
are as confident as its right ones (docs/ml/product-classification.md), so the
default policy accepts nothing; the tests that show automatic acceptance
working do so under an explicit policy entry set in the test, exactly as a
deployment would have to.

Scenarios, lettered as in the feature brief:

    A  confident classification (accepted policy)  -> category established automatically
    B  uncertain classification                     -> confirmation, no category, review required
    C  UNKNOWN classification                       -> applicability stays unknown
    D  classifier failure                           -> extraction and evaluation still work
    E  malformed classifier output                  -> safe fallback, nothing written
    F  missing classification metadata              -> existing behaviour, untouched
    G  explicit human declaration                   -> preserved, source submitter
    H  automatic + human                            -> the person wins, deterministically
    I  contradicting classifier input               -> no silent change to the verdict
    J  the engine receives the same facts either way
    K  rule 3 unchanged when facts are unknown
    L  rule 26 unchanged when facts are unknown
    M  isolation: only the adapter can carry a classification to the engine
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.catalog.models import Product, ProductApplicabilityDeclaration, ProductCategory
from apps.compliance.models import ComplianceCheck
from apps.compliance.services import applicability, auto_applicability, engine
from apps.compliance.services.auto_applicability import (
    ClassificationStatus,
    Disposition,
    assess,
    establish_category,
    read_classification,
)
from apps.extraction.models import ExtractionRun
from apps.rules.framework_loader import load_framework
from apps.rules.loader import load_rules
from apps.rules.models import ApplicabilityCondition

pytestmark = pytest.mark.django_db

ARTIFACT = "tfidf-logreg/0.1.0"

#: A policy entry as a deployment would write one - naming the evaluation that
#: licensed the floor. No such evaluation exists for 0.1.0; the tests that use
#: this are exercising the mechanism, not asserting the artifact is safe.
ACCEPT_0_1_0 = {ARTIFACT: {"min_confidence": 0.70, "evaluation": "tests: hypothetical held-out evaluation"}}


def classification(category="packaged-non-food", confidence=0.72, subcategory=None, subcategory_confidence=None, **extra):
    body = {
        "category": category,
        "subcategory": subcategory,
        "confidence": confidence,
        "subcategory_confidence": subcategory_confidence,
        "evidence": ["signal: soap / bathing bar (typical of cosmetics-and-toiletries)"],
        "category_scores": {"packaged-non-food": confidence, "packaged-food": round(1 - confidence, 4)}
        if confidence is not None
        else {},
        "subcategory_scores": {},
        "classifier_name": "tfidf-logreg",
        "classifier_version": "0.1.0",
    }
    body.update(extra)
    return body


READING = (
    ("net_quantity", "Net Qty: 500 g", {"quantity": 500, "unit": "g", "uncertain": False}),
    ("retail_sale_price", "MRP Rs. 120.00 (incl. of all taxes)", {"amount": "120.00", "uncertain": False}),
    ("manufacturer_name", "Manufactured by Test Foods Pvt Ltd", None),
)


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    settings.DEMO_PUBLIC_ANALYSIS_API = True


@pytest.fixture
def accepted(settings):
    """The policy as a deployment that had licensed 0.1.0 would set it."""
    settings.AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS = ACCEPT_0_1_0
    return ACCEPT_0_1_0


@pytest.fixture
def shipped(settings, category):
    """The real taxonomy, rules and framework, in deployment order."""
    root = ProductCategory.objects.create(code="packaged-commodity", name="Packaged commodity")
    category.parent = root
    category.save()
    ProductCategory.objects.create(code="packaged-non-food", name="Packaged non-food", parent=root)
    assert load_rules(settings.RULES_DEFINITIONS_DIR).ok
    assert load_framework(settings.RULES_FRAMEWORK_DIR).ok


@pytest.fixture
def unlinked_image(product_image):
    """An image nobody has attached a product to - the ordinary upload."""
    product_image.product = None
    product_image.save()
    return product_image


@pytest.fixture
def reading(shipped, unlinked_image, make_extracted_field):
    """A completed reading of the unlinked image, with the given classification
    recorded in its metadata (or no metadata key at all for `absent`)."""

    def _run(classification_value=None, *, absent: bool = False, malformed_metadata=None) -> ExtractionRun:
        metadata = {"unread_declarations": []}
        if not absent:
            metadata["product_classification"] = classification_value
        raw_output = {"engine_raw": {}, "metadata": metadata, "block_count": len(READING)}
        if malformed_metadata is not None:
            raw_output = malformed_metadata
        run = ExtractionRun.objects.create(
            image=unlinked_image,
            engine_name="tesseract",
            engine_version="0.4.0",
            status=ExtractionRun.Status.COMPLETED,
            recognised_text="\n".join(raw for _, raw, _ in READING),
            raw_output=raw_output,
        )
        for key, raw, normalised in READING:
            make_extracted_field(run, key, raw, normalized_value=normalised, confidence=0.9)
        return run

    return _run


def _evaluate(client, run, **extra):
    payload = {"extraction_run_id": str(run.pk), **extra}
    return client.post(reverse("v1:compliance-evaluate"), payload, content_type="application/json")


def _trace(check: ComplianceCheck) -> dict:
    return {
        "result": check.result,
        "counts": (
            check.rules_evaluated,
            check.rules_passed,
            check.rules_failed,
            check.rules_inconclusive,
            check.rules_not_applicable,
        ),
        "findings": sorted(
            (f.rule_code, f.status, f.downgraded_from_failed, f.applicability_note) for f in check.findings.all()
        ),
        "violations": sorted((v.rule_code, v.message) for v in check.violations.all()),
    }


# --- reading the classification ---------------------------------------------


class TestReadClassification:
    def test_a_well_formed_classification_is_read_as_committed(self, reading):
        read = read_classification(reading(classification()))
        assert read.usable and read.committed
        assert read.category == "packaged-non-food"
        assert read.confidence == 0.72
        assert read.artifact == ARTIFACT

    def test_unknown_is_usable_but_not_committed(self, reading):
        read = read_classification(
            reading(classification(category="unknown", confidence=None, evidence=["insufficient text: 2 word token(s)"]))
        )
        assert read.usable and not read.committed
        assert read.category is None

    def test_a_null_classification_is_a_failure_not_a_category(self, reading):
        read = read_classification(reading(None))
        assert not read.usable
        assert "produced no classification" in read.problem

    def test_an_absent_key_is_reported_as_absent(self, reading):
        read = read_classification(reading(absent=True))
        assert not read.usable
        assert "no classification was recorded" in read.problem

    @pytest.mark.parametrize(
        "broken",
        [
            "packaged-food",  # not an object
            {"category": 42},
            {"category": ""},
            {"category": "packaged-food", "confidence": "high"},
            {"category": "packaged-food", "confidence": 1.7},
            {"category": "packaged-food", "confidence": True},
            {"category": "unknown", "subcategory": "general-food"},
            {"category": "packaged-food", "classifier_name": None},
            {"category": "packaged-food", "evidence": "not a list"},
        ],
    )
    def test_malformed_output_is_unusable_never_partially_read(self, reading, broken):
        read = read_classification(reading(broken))
        assert not read.usable
        assert read.category is None
        assert "malformed" in read.problem

    def test_metadata_that_is_not_an_object_is_handled(self, reading):
        assert not read_classification(reading(malformed_metadata=["not", "a", "dict"])).usable
        assert not read_classification(reading(malformed_metadata={"metadata": "nope"})).usable
        assert not read_classification(None).usable


# --- the policy ---------------------------------------------------------------


class TestPolicy:
    def test_by_default_no_artifact_is_accepted(self, reading, settings):
        assert settings.AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS == {}
        read = read_classification(reading(classification(confidence=0.99)))
        assert auto_applicability.accepted_policy(read) is None
        status, reason = auto_applicability.classify_status(read, None)
        assert status is ClassificationStatus.UNCERTAIN
        assert "not accepted for automatic use" in reason

    def test_an_accepted_artifact_at_or_above_its_floor_is_confident(self, accepted, reading):
        read = read_classification(reading(classification(confidence=0.70)))
        policy = auto_applicability.accepted_policy(read)
        assert policy is not None and policy.min_confidence == 0.70
        assert auto_applicability.classify_status(read, policy)[0] is ClassificationStatus.CONFIDENT

    def test_an_accepted_artifact_below_its_floor_is_uncertain(self, accepted, reading):
        read = read_classification(reading(classification(confidence=0.69)))
        status, reason = auto_applicability.classify_status(read, auto_applicability.accepted_policy(read))
        assert status is ClassificationStatus.UNCERTAIN
        assert "below the floor of 0.70" in reason

    def test_acceptance_is_per_artifact_version(self, accepted, reading):
        read = read_classification(reading(classification(confidence=0.99, classifier_version="0.2.0")))
        assert auto_applicability.accepted_policy(read) is None

    @pytest.mark.parametrize(
        "entry",
        [
            "yes",
            {"min_confidence": 0.9},  # no evaluation cited
            {"min_confidence": 0.9, "evaluation": ""},
            {"min_confidence": 0, "evaluation": "x"},
            {"min_confidence": 1.5, "evaluation": "x"},
            {"min_confidence": "0.9", "evaluation": "x"},
            {"min_confidence": True, "evaluation": "x"},
        ],
    )
    def test_a_malformed_policy_entry_fails_closed(self, reading, entry, settings):
        settings.AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS = {ARTIFACT: entry}
        read = read_classification(reading(classification(confidence=0.99)))
        assert auto_applicability.accepted_policy(read) is None
        assert auto_applicability.classify_status(read, None)[0] is ClassificationStatus.UNCERTAIN

    def test_the_policy_setting_itself_may_be_malformed(self, reading, settings):
        settings.AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS = "not a dict"
        read = read_classification(reading(classification(confidence=0.99)))
        assert auto_applicability.accepted_policy(read) is None


# --- A. confident -> automatic --------------------------------------------------


class TestConfidentClassificationEstablishesTheCategory:
    @pytest.fixture(autouse=True)
    def _accepted(self, accepted):
        pass

    def test_the_category_is_established_with_its_provenance(self, reading):
        run = reading(classification(confidence=0.72))

        product = establish_category(run)

        assert product is not None
        assert product.category.code == "packaged-non-food"
        assert product.category_source == Product.CategorySource.CLASSIFIER
        assert "tfidf-logreg 0.1.0" in product.category_basis
        assert "0.72" in product.category_basis
        assert "hypothetical held-out evaluation" in product.category_basis
        # Never a declaration row: the category is the only thing written.
        assert ProductApplicabilityDeclaration.objects.filter(product=product).count() == 0

    def test_the_api_evaluates_the_established_category_and_says_so(self, client, reading):
        body = _evaluate(client, reading(classification(confidence=0.72))).json()

        assert body["product_category_code"] == "packaged-non-food"
        assert body["product_category_source"] == "classifier"
        assert body["rules_evaluated"] > 0
        assessment = body["applicability_assessment"]
        assert assessment["status"] == "confident"
        assert assessment["policy"]["accepted"] is True
        assert assessment["category"]["disposition"] == "established_automatically"
        assert assessment["category"]["in_effect"] == "packaged-non-food"
        assert assessment["category"]["in_effect_source"] == "classifier"
        assert assessment["questions"] == []

    def test_the_automatic_category_answers_food_article_exactly_as_a_stated_one_would(self, client, reading):
        """J. The engine sees the same facts whether a person or the policy set
        the category: the trace is identical."""
        run = reading(classification(category="packaged-food", confidence=0.80))
        automatic = ComplianceCheck.objects.get(pk=_evaluate(client, run).json()["id"])
        stated = ComplianceCheck.objects.get(pk=_evaluate(client, run, category_code="packaged-food").json()["id"])

        assert _trace(automatic) == _trace(stated)
        food_article = ApplicabilityCondition.objects.get(code="food-article")
        assert applicability.DeclarationSet(automatic.product).answer(food_article) == applicability.YES
        assert automatic.product.category_source == "classifier"
        assert stated.product.category_source == "submitter"

    def test_a_category_the_catalogue_does_not_have_is_not_established(self, reading):
        run = reading(classification(category="cleaning-product", confidence=0.95))
        assert establish_category(run) is None
        assessment = assess(engine.evaluate(run))
        assert assessment.category.disposition is Disposition.NOT_PROPOSED
        assert "not a product category this installation knows" in assessment.category.reason

    def test_declarations_may_ride_on_an_automatic_category(self, client, reading):
        run = reading(classification(confidence=0.72))

        response = _evaluate(client, run, applicability_declarations={"imported-product": "no"})

        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["product_category_source"] == "classifier"
        assert [(d["code"], d["answer"], d["source"]) for d in body["applicability_declarations"]] == [
            ("imported-product", "no", "submitter")
        ]


# --- B. uncertain -> confirmation ------------------------------------------------


class TestUncertainClassificationAsksAPerson:
    def test_nothing_is_written_and_the_result_is_review_required(self, client, reading):
        run = reading(classification(confidence=0.99))
        before = Product.objects.count()

        body = _evaluate(client, run).json()

        assert Product.objects.count() == before
        assert body["result"] == "review_required"
        assert "not known" in body["summary"]
        assert body["product_category_code"] is None
        assert body["product_category_source"] is None
        assessment = body["applicability_assessment"]
        assert assessment["status"] == "uncertain"
        assert assessment["policy"]["accepted"] is False
        assert assessment["classifier"] == {
            "name": "tfidf-logreg",
            "version": "0.1.0",
            "confidence": 0.99,
            "evidence": ["signal: soap / bathing bar (typical of cosmetics-and-toiletries)"],
        }
        assert assessment["category"]["proposed"] == "packaged-non-food"
        assert assessment["category"]["proposed_name"] == "Packaged non-food"
        assert assessment["category"]["confidence"] == 0.99
        assert assessment["category"]["in_effect"] is None
        assert assessment["category"]["disposition"] == "needs_confirmation"

    def test_exactly_one_question_is_asked_with_the_suggestion_and_the_choices(self, client, reading):
        body = _evaluate(client, reading(classification(confidence=0.99))).json()

        [question] = body["applicability_assessment"]["questions"]
        assert question["kind"] == "category"
        assert question["suggested"] == "packaged-non-food"
        assert "packaged non-food" in question["prompt"]
        assert question["choices"] == [
            {"code": "packaged-food", "name": "Packaged food"},
            {"code": "packaged-non-food", "name": "Packaged non-food"},
        ]

    def test_confirming_the_suggestion_is_recorded_as_a_confirmation(self, client, reading):
        run = reading(classification(confidence=0.99))

        body = _evaluate(client, run, category_code="packaged-non-food").json()

        assert body["product_category_code"] == "packaged-non-food"
        assert body["product_category_source"] == "submitter"
        category = body["applicability_assessment"]["category"]
        assert category["disposition"] == "confirmed_by_submitter"
        assert category["in_effect_source"] == "submitter"
        assert body["applicability_assessment"]["questions"] == []
        assert body["rules_evaluated"] > 0

    def test_a_subcategory_fact_is_proposed_never_recorded(self, client, reading):
        run = reading(classification(confidence=0.99, subcategory="cosmetics-and-toiletries", subcategory_confidence=0.6))

        body = _evaluate(client, run, category_code="packaged-non-food").json()

        [fact] = body["applicability_assessment"]["facts"]
        assert fact["condition"] == "cosmetics-and-toiletries"
        assert fact["proposed_answer"] == "yes"
        assert fact["confidence"] == 0.6
        assert fact["in_effect"] == "unknown"
        assert fact["in_effect_source"] is None
        assert fact["disposition"] == "needs_confirmation"
        assert "6(1)(d): exempts" in fact["affects"]
        assert "6(8): requires" in fact["affects"]
        assert ProductApplicabilityDeclaration.objects.filter(condition__code="cosmetics-and-toiletries").count() == 0
        [question] = body["applicability_assessment"]["questions"]
        assert question == {
            "kind": "condition",
            "code": "cosmetics-and-toiletries",
            "suggested": "yes",
            "prompt": question["prompt"],
            "choices": [],
        }
        # The clauses that turn on it stay undetermined.
        by_code = {f["rule_code"]: f for f in body["findings"]}
        assert any("cosmetics" in f["applicability_note"].lower() for f in by_code.values())

    def test_a_subcategory_fact_is_never_automatic_even_under_an_accepted_policy(self, accepted, client, reading):
        run = reading(classification(confidence=0.99, subcategory="cosmetics-and-toiletries", subcategory_confidence=0.99))

        body = _evaluate(client, run).json()

        assert body["product_category_source"] == "classifier"
        [fact] = body["applicability_assessment"]["facts"]
        assert fact["disposition"] == "needs_confirmation"
        assert fact["in_effect"] == "unknown"
        assert ProductApplicabilityDeclaration.objects.count() == 0


# --- C. unknown ------------------------------------------------------------------


class TestUnknownClassification:
    def test_applicability_stays_unknown_and_the_generic_question_is_asked(self, client, reading):
        run = reading(classification(category="unknown", confidence=None, evidence=["below confidence threshold 0.60: best candidate packaged-food (0.55)"]))

        body = _evaluate(client, run).json()

        assert body["result"] == "review_required"
        assert body["product_category_code"] is None
        assessment = body["applicability_assessment"]
        assert assessment["status"] == "unknown"
        assert "best candidate packaged-food (0.55)" in assessment["reason"]
        assert assessment["category"]["proposed"] is None
        assert assessment["category"]["disposition"] == "not_proposed"
        [question] = assessment["questions"]
        assert question["kind"] == "category"
        assert question["suggested"] is None
        assert question["prompt"] == "What kind of product is this?"
        assert len(question["choices"]) == 2

    def test_unknown_is_never_established_even_under_an_accepted_policy(self, accepted, reading):
        assert establish_category(reading(classification(category="unknown", confidence=None))) is None


# --- D, E, F. failure, malformed, absent ---------------------------------------------


class TestFailedOrMissingClassification:
    def test_a_null_classification_falls_back_to_the_existing_path(self, accepted, client, reading):
        body = _evaluate(client, reading(None)).json()

        assert body["result"] == "review_required"
        assert body["product_category_code"] is None
        assert body["applicability_assessment"]["status"] == "failed"
        assert body["applicability_assessment"]["category"]["disposition"] == "not_proposed"
        assert body["applicability_assessment"]["questions"][0]["suggested"] is None

    def test_malformed_output_writes_nothing_and_evaluates_normally(self, accepted, client, reading):
        run = reading({"category": "packaged-non-food", "confidence": "very", "classifier_name": "tfidf-logreg", "classifier_version": "0.1.0"})
        before = Product.objects.count()

        body = _evaluate(client, run, category_code="packaged-food").json()

        assert Product.objects.count() == before + 1
        assert body["product_category_code"] == "packaged-food"
        assert body["product_category_source"] == "submitter"
        assert body["applicability_assessment"]["status"] == "failed"
        assert "malformed" in body["applicability_assessment"]["reason"]
        assert body["applicability_assessment"]["category"]["disposition"] == "stated_by_submitter"

    def test_a_run_without_the_metadata_key_behaves_exactly_as_before(self, client, reading):
        """F. Older runs and pipelines without a classifier."""
        run = reading(absent=True)

        without = _evaluate(client, run, category_code="packaged-food").json()

        assert without["product_category_code"] == "packaged-food"
        assert without["applicability_assessment"]["status"] == "failed"
        assert "no classification was recorded" in without["applicability_assessment"]["reason"].lower()
        assert without["applicability_assessment"]["facts"] == []
        assert without["applicability_assessment"]["questions"] == []
        assert without["rules_evaluated"] > 0


# --- G, H. human declarations and precedence ------------------------------------------


class TestPrecedence:
    def test_a_human_category_wins_over_a_contradicting_classification(self, client, reading, settings):
        """H, I. Stated food, classified non-food at 0.99: the person's category
        is evaluated and the disagreement is reported, not resolved."""
        run = reading(classification(category="packaged-non-food", confidence=0.99))

        settings.AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS = ACCEPT_0_1_0
        body = _evaluate(client, run, category_code="packaged-food").json()

        assert body["product_category_code"] == "packaged-food"
        assert body["product_category_source"] == "submitter"
        category = body["applicability_assessment"]["category"]
        assert category["disposition"] == "contradicted_by_submitter"
        assert category["proposed"] == "packaged-non-food"
        assert category["in_effect"] == "packaged-food"
        assert body["applicability_assessment"]["status"] == "confident"  # the policy would have accepted it
        assert Product.objects.filter(category_source="classifier").count() == 0

    def test_a_human_declaration_is_preserved_and_wins_over_a_proposed_fact(self, client, reading):
        """G, H. A declared NO on a condition the classifier suggests YES for."""
        run = reading(classification(confidence=0.99, subcategory="cosmetics-and-toiletries", subcategory_confidence=0.9))

        body = _evaluate(
            client, run, category_code="packaged-non-food", applicability_declarations={"cosmetics-and-toiletries": "no"}
        ).json()

        declared = ProductApplicabilityDeclaration.objects.get(condition__code="cosmetics-and-toiletries")
        assert declared.answer == "no" and declared.source == "submitter"
        [fact] = body["applicability_assessment"]["facts"]
        assert fact["in_effect"] == "no"
        assert fact["in_effect_source"] == "submitter"
        assert fact["disposition"] == "contradicted_by_submitter"
        assert body["applicability_assessment"]["questions"] == []

    def test_confirming_a_proposed_fact_is_recorded_as_confirmed(self, client, reading):
        run = reading(classification(confidence=0.99, subcategory="cosmetics-and-toiletries", subcategory_confidence=0.9))

        body = _evaluate(
            client, run, category_code="packaged-non-food", applicability_declarations={"cosmetics-and-toiletries": "yes"}
        ).json()

        [fact] = body["applicability_assessment"]["facts"]
        assert fact["in_effect"] == "yes"
        assert fact["disposition"] == "confirmed_by_submitter"
        assert body["applicability_assessment"]["questions"] == []

    def test_an_image_already_linked_to_a_product_keeps_that_product(self, accepted, client, shipped, product_image, make_extracted_field):
        """The classifier is not consulted for a product a person already identified."""
        run = ExtractionRun.objects.create(
            image=product_image,
            engine_name="tesseract",
            engine_version="0.4.0",
            status=ExtractionRun.Status.COMPLETED,
            recognised_text="text",
            raw_output={"metadata": {"product_classification": classification(category="packaged-non-food", confidence=0.99)}},
        )

        body = _evaluate(client, run).json()

        assert body["product_category_code"] == "packaged-food"
        assert body["product_category_source"] == "submitter"
        assert body["applicability_assessment"]["category"]["disposition"] == "contradicted_by_submitter"
        assert Product.objects.filter(category_source="classifier").count() == 0

    def test_a_later_human_re_check_supersedes_an_automatic_category(self, accepted, client, reading):
        run = reading(classification(category="packaged-non-food", confidence=0.99))

        first = _evaluate(client, run).json()
        second = _evaluate(client, run, category_code="packaged-food").json()

        assert first["product_category_source"] == "classifier"
        assert second["product_category_source"] == "submitter"
        assert second["product_category_code"] == "packaged-food"
        # Two products, two checks: the automatic one is not rewritten.
        assert Product.objects.filter(category_source="classifier").count() == 1


# --- I. contradicting classifier input changes no verdict -------------------------


class TestClassifierCannotChangeAVerdictExceptThroughTheAdapter:
    def test_with_the_default_policy_any_classification_leaves_the_trace_identical(self, client, reading):
        """Same reading, same stated category; wildly different classifications.
        Under the shipped policy the engine's trace does not move."""
        traces = set()
        for value in (
            None,
            classification(category="packaged-food", confidence=0.99),
            classification(category="packaged-non-food", confidence=0.99, subcategory="medical-device", subcategory_confidence=0.99),
            classification(category="unknown", confidence=None),
            {"category": "packaged-non-food", "confidence": "malformed"},
        ):
            run = reading(value)
            check = ComplianceCheck.objects.get(pk=_evaluate(client, run, category_code="packaged-food").json()["id"])
            traces.add(repr(_trace(check)))
        assert len(traces) == 1

    def test_under_an_accepted_policy_the_only_difference_is_the_category_a_person_could_have_stated(self, accepted, client, reading):
        """The adapter's whole effect is a Product.category. Whatever it
        establishes, a person stating the same category produces the same
        trace - there is no second channel."""
        for category in ("packaged-food", "packaged-non-food"):
            run = reading(classification(category=category, confidence=0.9))
            automatic = ComplianceCheck.objects.get(pk=_evaluate(client, run).json()["id"])
            stated = ComplianceCheck.objects.get(pk=_evaluate(client, run, category_code=category).json()["id"])
            assert automatic.product.category_source == "classifier"
            assert _trace(automatic) == _trace(stated)

    def test_the_classifier_never_yields_a_compliance_verdict_directly(self, reading):
        """The adapter's vocabulary has no verdict in it, and it never calls the engine."""
        import inspect

        source = inspect.getsource(auto_applicability)
        for forbidden in ("COMPLIANT", "NON_COMPLIANT", "engine.evaluate(", "ComplianceFinding", "ComplianceViolation"):
            assert forbidden not in source, forbidden
        assert not hasattr(auto_applicability, "evaluate")

    def test_assess_costs_a_bounded_number_of_queries(self, reading, django_assert_max_num_queries):
        """Latency: the assessment is a few small lookups - the category row,
        the choices, the condition, its declaration and its clause links - and
        must stay flat rather than growing with the rule set or the framework."""
        run = reading(classification(confidence=0.99, subcategory="cosmetics-and-toiletries", subcategory_confidence=0.9))
        check = engine.evaluate(run)
        check = ComplianceCheck.objects.select_related("extraction_run", "product__category").get(pk=check.pk)

        with django_assert_max_num_queries(6):
            auto_applicability.as_dict(assess(check))

    def test_assess_writes_nothing(self, client, reading):
        run = reading(classification(confidence=0.99, subcategory="cosmetics-and-toiletries", subcategory_confidence=0.9))
        check = engine.evaluate(run)
        products, declarations = Product.objects.count(), ProductApplicabilityDeclaration.objects.count()

        assess(check)
        assess(check)

        assert (Product.objects.count(), ProductApplicabilityDeclaration.objects.count()) == (products, declarations)


# --- K, L. rules 3 and 26 unchanged where facts are unknown -----------------------


class TestScopeGatesAreUntouched:
    def test_no_scope_gate_condition_is_ever_answered_from_a_classification(self, accepted, client, reading):
        """K, L. Rule 3 and rule 26 turn on facts the classifier cannot state;
        an automatic category leaves every one of them UNKNOWN and the scope
        caveat on every finding."""
        run = reading(classification(category="packaged-non-food", confidence=0.99, subcategory="tobacco-product", subcategory_confidence=0.99))
        body = _evaluate(client, run).json()
        check = ComplianceCheck.objects.get(pk=body["id"])

        declarations = applicability.DeclarationSet(check.product)
        gates = ApplicabilityCondition.objects.filter(
            requirement_links__requirement__clause__in=applicability.SCOPE_GATE_CLAUSES
        ).distinct()
        assert gates.count() > 0
        for condition in gates:
            assert declarations.answer(condition) == applicability.UNKNOWN, condition.code
        assert applicability.decide_scope(declarations).applies
        for finding in body["findings"]:
            assert "scope gates in rule 3 and rule 26" in finding["applicability_note"]
        # Tobacco was suggested, not recorded: rule 26's proviso stays unanswered.
        [fact] = body["applicability_assessment"]["facts"]
        assert fact["condition"] == "tobacco-product" and fact["in_effect"] == "unknown"
        assert "26: withholds_exemption" in fact["affects"]


# --- N. backward compatibility ---------------------------------------------------------


class TestBackwardCompatibility:
    def test_the_existing_request_shape_still_works_unchanged(self, client, reading):
        run = reading(classification(confidence=0.99))
        body = _evaluate(client, run, category_code="packaged-food", applicability_declarations={"imported-product": "no"}).json()
        assert body["product_category_code"] == "packaged-food"
        assert body["applicability_declarations"][0]["code"] == "imported-product"

    def test_declarations_without_any_category_are_still_refused_under_the_default_policy(self, client, reading):
        response = _evaluate(client, reading(classification(confidence=0.99)), applicability_declarations={"imported-product": "no"})
        assert response.status_code == 400
        assert "category_code" in response.json()["error"]["details"]["applicability_declarations"][0]

    def test_the_stored_result_reports_the_same_assessment_when_fetched_back(self, client, reading):
        run = reading(classification(confidence=0.99))
        created = _evaluate(client, run).json()

        fetched = client.get(reverse("v1:compliance-detail", kwargs={"pk": created["id"]})).json()

        assert fetched["applicability_assessment"] == created["applicability_assessment"]
        assert fetched["product_category_source"] is None
