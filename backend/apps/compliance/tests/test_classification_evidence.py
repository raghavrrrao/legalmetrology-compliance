"""The evidence behind a suggestion, and what confirming it will do.

When the policy cannot establish a category automatically - which today is
always - the person is asked. This suite pins what they are shown when that
happens, and the rule under all of it: **every string offered as evidence is
either a phrase found in this reading, a value the extractor read, or a term
the classifier itself recorded.** Nothing is generated, and nothing is
inferred from the model's behaviour and narrated back.

    label_signals    phrases in THIS reading, with a snippet to find them by
    declared_fields  what the extractor read off the label
    model_terms      n-grams the model weighed - internals, kept apart
    has_supporting_evidence / note   an explicit "there is nothing" state

The suggestion stays a suggestion throughout: no evidence list, however long,
moves `category.in_effect` or any compliance status.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.catalog.models import Product, ProductCategory
from apps.compliance.models import ComplianceCheck
from apps.compliance.services import auto_applicability, engine
from apps.compliance.services.auto_applicability import (
    gather_evidence,
    read_classification,
)
from apps.extraction.models import ExtractionRun
from apps.rules.framework_loader import load_framework
from apps.rules.loader import load_rules

pytestmark = pytest.mark.django_db

ARTIFACT = "tfidf-logreg/0.1.0"
ACCEPT = {ARTIFACT: {"min_confidence": 0.70, "evaluation": "tests: hypothetical held-out evaluation"}}

#: A cosmetics label. Every phrase here is one the shipped signal table
#: recognises, so the evidence a test asserts is evidence the table produces.
SOAP_TEXT = (
    "DOVE BEAUTY BATHING BAR\n"
    "Moisturising cream with 1/4 moisturising milk\n"
    "For external use only. Keep out of reach of children.\n"
    "Net Qty: 100 g\n"
    "MRP Rs. 65.00 (incl. of all taxes)\n"
)

#: A reading with no recognisable phrase and no extractable declaration.
BARE_TEXT = "ACME\nlorem ipsum dolor\n"


def classification(category="packaged-non-food", confidence=0.72, subcategory=None, evidence=None, **extra):
    body = {
        "category": category,
        "subcategory": subcategory,
        "confidence": confidence,
        "subcategory_confidence": 0.56 if subcategory else None,
        "evidence": [
            "signal: soap / bathing bar (typical of cosmetics-and-toiletries)",
            "term: 'bathing' weighed for cosmetics-and-toiletries",
            "term: 'bar' weighed for cosmetics-and-toiletries",
        ]
        if evidence is None
        else evidence,
        "category_scores": (
            {"packaged-non-food": confidence, "packaged-food": round(1 - confidence, 4)}
            if confidence is not None
            else {}
        ),
        "subcategory_scores": {},
        "classifier_name": "tfidf-logreg",
        "classifier_version": "0.1.0",
    }
    body.update(extra)
    return body


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    settings.DEMO_PUBLIC_ANALYSIS_API = True


@pytest.fixture
def shipped(settings, category):
    root = ProductCategory.objects.create(code="packaged-commodity", name="Packaged commodity")
    category.parent = root
    category.save()
    ProductCategory.objects.create(code="packaged-non-food", name="Packaged non-food", parent=root)
    assert load_rules(settings.RULES_DEFINITIONS_DIR).ok
    assert load_framework(settings.RULES_FRAMEWORK_DIR).ok


@pytest.fixture
def unlinked_image(product_image):
    product_image.product = None
    product_image.save()
    return product_image


@pytest.fixture
def reading(shipped, unlinked_image, make_extracted_field):
    """A completed reading of the unlinked image, with the text and the
    declarations a test needs, and a classification in its metadata."""

    def _run(classification_value=None, *, text: str = SOAP_TEXT, fields=(("net_quantity", "Net Qty: 100 g"),)) -> ExtractionRun:
        run = ExtractionRun.objects.create(
            image=unlinked_image,
            engine_name="tesseract",
            engine_version="0.4.0",
            status=ExtractionRun.Status.COMPLETED,
            recognised_text=text,
            raw_output={
                "engine_raw": {},
                "metadata": {"unread_declarations": [], "product_classification": classification_value},
                "block_count": 1,
            },
        )
        for key, raw in fields:
            make_extracted_field(run, key, raw, confidence=0.9)
        return run

    return _run


def _evaluate(client, run, **extra):
    payload = {"extraction_run_id": str(run.pk), **extra}
    return client.post(reverse("v1:compliance-evaluate"), payload, content_type="application/json")


def _assessment(client, run, **extra):
    return _evaluate(client, run, **extra).json()["applicability_assessment"]


# --- 6. the evidence that exists is surfaced ----------------------------------


class TestLabelEvidence:
    def test_a_phrase_is_offered_only_with_the_reading_that_contains_it(self, client, reading):
        body = _assessment(client, reading(classification()))

        evidence = body["evidence"]
        assert evidence["has_supporting_evidence"] is True
        assert evidence["note"] == ""

        phrases = {signal["phrase"]: signal for signal in evidence["label_signals"]}
        assert "soap / bathing bar" in phrases
        assert "for external use only" in phrases

        # Every phrase comes with the surrounding reading, so a person can find
        # it on the photograph - and every snippet really is from this reading.
        cleaned = SOAP_TEXT.lower()
        for signal in evidence["label_signals"]:
            assert signal["snippet"]
            body_text = signal["snippet"].strip("…")
            assert body_text in " ".join(cleaned.split()), signal
            assert signal["indicative_of"]

    def test_the_declarations_the_extractor_read_are_shown_as_context(self, client, reading):
        run = reading(classification(), fields=(("net_quantity", "Net Qty: 100 g"), ("retail_sale_price", "MRP Rs. 65.00")))

        evidence = _assessment(client, run)["evidence"]

        assert evidence["declared_fields"] == [
            {"field_key": "net_quantity", "value": "Net Qty: 100 g"},
            {"field_key": "retail_sale_price", "value": "MRP Rs. 65.00"},
        ]

    def test_model_terms_are_reported_apart_from_label_phrases(self, client, reading):
        """The n-grams are the model's internals, not statements about the
        product. They are parsed out of the classifier's own strings, and the
        class each was weighed for is not carried alongside the suggestion."""
        evidence = _assessment(client, reading(classification()))["evidence"]

        assert evidence["model_terms"] == ["bathing", "bar"]
        assert all("weighed for" not in term for term in evidence["model_terms"])
        assert all(not phrase["phrase"].startswith("term") for phrase in evidence["label_signals"])

    def test_the_classifier_s_own_evidence_strings_are_still_passed_through(self, client, reading):
        """Backward compatibility: `classifier.evidence` is unchanged."""
        assessment = _assessment(client, reading(classification()))

        assert assessment["classifier"]["evidence"] == [
            "signal: soap / bathing bar (typical of cosmetics-and-toiletries)",
            "term: 'bathing' weighed for cosmetics-and-toiletries",
            "term: 'bar' weighed for cosmetics-and-toiletries",
        ]

    def test_evidence_is_capped(self, client, reading):
        run = reading(
            classification(evidence=[f"term: 'w{i}' weighed for x" for i in range(20)]),
            text=SOAP_TEXT + "ingredients nutritional information protein energy fssai serving size vegetarian\n",
            fields=tuple((f"field_{i}", f"value {i}") for i in range(10)),
        )

        evidence = _assessment(client, run)["evidence"]

        assert len(evidence["label_signals"]) <= auto_applicability.MAX_LABEL_SIGNALS
        assert len(evidence["declared_fields"]) <= auto_applicability.MAX_DECLARED_FIELDS
        assert len(evidence["model_terms"]) <= auto_applicability.MAX_MODEL_TERMS


# --- 7. missing evidence is handled safely ------------------------------------


class TestMissingEvidence:
    def test_a_reading_with_no_recognisable_phrase_says_so_plainly(self, client, reading):
        run = reading(classification(), text=BARE_TEXT, fields=())

        evidence = _assessment(client, run)["evidence"]

        assert evidence["label_signals"] == []
        assert evidence["declared_fields"] == []
        assert evidence["has_supporting_evidence"] is False
        assert "no evidence from the label behind this suggestion" in evidence["note"]

    def test_an_unreadable_photograph_says_that_instead(self, client, reading):
        run = reading(classification(), text="   ", fields=())

        evidence = _assessment(client, run)["evidence"]

        assert evidence["has_supporting_evidence"] is False
        assert "No text was read from this photograph" in evidence["note"]

    def test_nothing_is_invented_when_the_classifier_recorded_no_evidence(self, client, reading):
        run = reading(classification(evidence=[]), text=BARE_TEXT, fields=())

        evidence = _assessment(client, run)["evidence"]

        assert evidence == {
            "has_supporting_evidence": False,
            "note": evidence["note"],
            "label_signals": [],
            "declared_fields": [],
            "model_terms": [],
        }

    @pytest.mark.parametrize(
        "broken",
        [
            ["term: no closing quote"],
            ["term: ''"],
            ["term: "],
            [42],
            ["signal: a phrase with no parenthesis"],
        ],
    )
    def test_malformed_evidence_strings_are_dropped_not_rendered(self, client, reading, broken):
        run = reading(classification(evidence=broken))

        evidence = _assessment(client, run)["evidence"]

        assert evidence["model_terms"] == []
        # The reading still supplies its own evidence, independently.
        assert evidence["has_supporting_evidence"] is True

    def test_evidence_is_present_even_when_the_classification_is_malformed(self, client, reading):
        """12. A malformed classification costs the suggestion, not the reading:
        the person is still shown what the label says."""
        run = reading({"category": "packaged-non-food", "confidence": "very"})

        assessment = _assessment(client, run)

        assert assessment["status"] == "failed"
        assert assessment["category"]["proposed"] is None
        assert assessment["evidence"]["has_supporting_evidence"] is True
        assert any(s["phrase"] == "soap / bathing bar" for s in assessment["evidence"]["label_signals"])

    def test_evidence_survives_a_missing_classification_entirely(self, client, reading):
        run = reading(None)

        assessment = _assessment(client, run)

        assert assessment["status"] == "failed"
        assert assessment["evidence"]["label_signals"] != []
        assert assessment["evidence"]["model_terms"] == []


# --- 3. unknown fabricates nothing ---------------------------------------------


class TestUnknownFabricatesNoSuggestion:
    def test_no_category_is_proposed_and_the_evidence_is_still_shown(self, client, reading):
        run = reading(
            classification(
                category="unknown",
                confidence=None,
                evidence=["below confidence threshold 0.60: best candidate packaged-non-food (0.55)"],
            )
        )

        assessment = _assessment(client, run)

        assert assessment["status"] == "unknown"
        assert assessment["category"]["proposed"] is None
        assert assessment["category"]["proposed_name"] is None
        assert assessment["category"]["confidence"] is None
        [question] = assessment["questions"]
        assert question["suggested"] is None
        assert question["prompt"] == "What kind of product is this?"
        # The label evidence is still worth showing: it is what the person will
        # use to answer, and it belongs to the reading rather than to the model.
        assert assessment["evidence"]["has_supporting_evidence"] is True
        assert "best candidate packaged-non-food (0.55)" in assessment["reason"]


# --- what answering will do -----------------------------------------------------


class TestTheOutcomeOfAnswering:
    def test_a_category_question_says_what_confirming_does(self, client, reading):
        [question] = _assessment(client, reading(classification()))["questions"]

        assert question["kind"] == "category"
        assert "selects the requirements loaded for that product type" in question["outcome"]
        assert "not uploaded or read again" in question["outcome"]
        assert "recorded as yours" in question["outcome"]
        assert "not known rather than assuming one" in question["outcome"]

    def test_a_condition_question_names_the_clauses_it_decides(self, client, reading):
        run = reading(classification(subcategory="cosmetics-and-toiletries"))

        questions = _assessment(client, run, category_code="packaged-non-food")["questions"]

        [question] = [q for q in questions if q["kind"] == "condition"]
        assert question["code"] == "cosmetics-and-toiletries"
        assert "6(1)(d)" in question["outcome"]
        assert "6(8)" in question["outcome"]
        assert "recorded as yours, not as the classifier" in question["outcome"]

    def test_a_settled_assessment_asks_nothing(self, client, reading, settings):
        settings.AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS = ACCEPT

        assessment = _assessment(client, reading(classification()))

        assert assessment["status"] == "confident"
        assert assessment["questions"] == []
        # 1. An accepted classification behaves exactly as before: established,
        #    with the evidence beside it rather than instead of it.
        assert assessment["category"]["disposition"] == "established_automatically"
        assert assessment["evidence"]["has_supporting_evidence"] is True


# --- the boundary: evidence changes nothing -------------------------------------


class TestEvidenceDecidesNothing:
    def test_evidence_does_not_move_the_category_or_the_verdict(self, client, reading):
        """2, 13, 14. However much the label says 'soap', the suggestion stays a
        suggestion: no category in effect, the deterministic engine produces the
        verdict, and no compliance status comes from the classifier."""
        rich = reading(classification())
        bare = reading(classification(), text=BARE_TEXT, fields=())

        rich_body = _evaluate(client, rich).json()
        bare_body = _evaluate(client, bare).json()

        assert rich_body["applicability_assessment"]["evidence"]["has_supporting_evidence"] is True
        assert bare_body["applicability_assessment"]["evidence"]["has_supporting_evidence"] is False
        for body in (rich_body, bare_body):
            assert body["product_category_code"] is None
            assert body["product_category_source"] is None
            assert body["result"] == ComplianceCheck.Result.REVIEW_REQUIRED
            assert body["applicability_assessment"]["category"]["in_effect"] is None
        assert Product.objects.filter(category_source="classifier").count() == 0

    def test_gathering_evidence_writes_nothing_and_needs_no_extra_query(self, reading, django_assert_max_num_queries):
        run = reading(classification())
        check = engine.evaluate(run)
        products = Product.objects.count()

        with django_assert_max_num_queries(2):
            evidence = gather_evidence(run, read_classification(run))

        assert evidence.has_supporting_evidence is True
        assert Product.objects.count() == products

    def test_the_assessment_still_costs_a_bounded_number_of_queries(self, reading, django_assert_max_num_queries):
        run = reading(classification(subcategory="cosmetics-and-toiletries"))
        check = engine.evaluate(run)
        check = ComplianceCheck.objects.select_related("extraction_run", "product__category").get(pk=check.pk)

        with django_assert_max_num_queries(8):
            auto_applicability.as_dict(auto_applicability.assess(check))

    def test_no_label_text_reaches_the_logs(self, reading, caplog):
        """10. The reading is third-party trade dress; the snippets go to the
        person who uploaded it, never to the server log."""
        import logging

        run = reading(classification())
        with caplog.at_level(logging.DEBUG):
            gather_evidence(run, read_classification(run))

        assert "bathing" not in caplog.text.lower()
        assert "dove" not in caplog.text.lower()
