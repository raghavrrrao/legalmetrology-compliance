"""The one bridge from a label classification to the applicability engine.

    extraction.product_classification          an observation about the label
        -> read_classification()               validated; never trusted beyond its shape
        -> classification policy               settings, naming the artifacts a
           (accepted_policy)                   held-out evaluation has licensed
        -> establish_category()                at most a Product.category, and only
                                               when the policy accepts THIS artifact
        -> the existing applicability engine   DeclarationSet, decide_scope, decide
        -> assess()                            what was proposed, what is in effect,
                                               what a person still has to answer

Three numbers that must never be confused, and are kept apart here by name:

- **classifier confidence** - the model's probability mass behind its category.
  It describes the label text. It is not calibrated on this artifact.
- **legal applicability** - YES / NO / UNKNOWN per condition, decided by
  `applicability.py` from `Product.category` and declaration rows. This module
  can add exactly one input to that decision, a category, and only under an
  accepted policy.
- **compliance** - passed / failed / inconclusive / not applicable per rule,
  decided by the rule engine. Nothing here produces or alters one.

What this module is allowed to do, exhaustively
----------------------------------------------
1. Read the classification off a run and say what state it is in: CONFIDENT
   (committed, and the policy accepts this artifact at this confidence),
   UNCERTAIN (committed, but the policy does not), UNKNOWN (the classifier
   declined) or FAILED (absent, null or malformed).
2. When - and only when - the state is CONFIDENT and no person has stated a
   category, create the `Product` row that carries the classifier's category,
   with `category_source = CLASSIFIER` and the basis written down. That row is
   then evaluated exactly as a row a person created would be. Nothing else is
   written: no declaration row is ever created from a classification.
3. Describe, for a finished check, what the classification proposed, what is in
   effect and from whom, which questions a person still has to answer, and the
   **evidence from the reading** behind the suggestion - so that a person asked
   to confirm a product type can see what the label actually says rather than
   being handed a number.

What it must never do
---------------------
- Turn a subcategory into a declaration. Every subcategory the taxonomy maps to
  a condition (`cosmetics-and-toiletries`, `alcoholic-beverage`,
  `medical-device`, `tobacco-product`, `electronic-product`) exempts a clause or
  withholds the rule 26 exemption. A wrong YES excuses a package from a
  declaration it owes; a wrong NO would assert a fact nobody established. They
  are *proposed* for a person to confirm through `applicability_declarations`,
  under any policy.
- Override a person. A `category_code` in the request, an existing product's
  category and every declaration row outrank the classifier; a proposal that
  disagrees with one is reported as contradicted and changes nothing.
- Guess. UNKNOWN, FAILED and UNCERTAIN all end in the existing path: no
  category, `REVIEW_REQUIRED` with "the commodity category is not known", and
  a question for the person.

Why the policy is a configuration entry and not a threshold constant
-------------------------------------------------------------------
docs/ml/product-classification.md reports, for the shipped artifact, that the
confidences of wrong held-out answers (0.65-0.79) overlap the confidences of
right ones (0.62-0.72) completely, and that `packaged-non-food` was never
predicted for an unseen product. No number in this file could make that
artifact safe to accept automatically, so none is written here. Acceptance is
`settings.AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS`: an entry per artifact
that a held-out evaluation on verified labels has licensed, naming the operating
point and the evaluation. It is empty by default, which makes every committed
classification UNCERTAIN today - a suggestion, confirmed by a person.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from django.conf import settings

from apps.catalog.models import Product, ProductApplicabilityDeclaration, ProductCategory
from apps.compliance.models import ComplianceCheck
from apps.compliance.services import applicability
from apps.extraction.models import ExtractionRun
from apps.extraction.services import extraction_service
from apps.rules.models import ApplicabilityCondition, RequirementApplicability

logger = logging.getLogger(__name__)

#: The value the classifier uses to say "I could not tell". Mirrors
#: `labelextract.contracts.UNKNOWN_CATEGORY`; restated rather than imported
#: because the *decision* below reads the classifier's recorded output, which is
#: JSON. Nothing about the category, the policy or the applicability outcome is
#: decided by importing the ML package. (Evidence gathering does import one
#: module from it - see `_label_signals` - and that import decides nothing.)
UNKNOWN_CATEGORY = "unknown"

#: How many of each kind of evidence reaches a client. Enough for a person to
#: recognise the label; short enough that the card stays readable on a phone.
MAX_LABEL_SIGNALS = 6
MAX_DECLARED_FIELDS = 6
MAX_MODEL_TERMS = 5


#: Subcategory code -> the applicability condition it corresponds to. Mirrors
#: `labelextract.classification.taxonomy` for the same reason as above: the
#: recorded output is what is interpreted, and the mapping must be reviewable
#: here, beside the policy that refuses to act on it automatically. A code
#: absent from this table proposes nothing.
SUBCATEGORY_CONDITIONS: dict[str, str] = {
    "alcoholic-beverage": "alcoholic-beverage",
    "cosmetics-and-toiletries": "cosmetics-and-toiletries",
    "medical-device": "medical-device",
    "tobacco-product": "tobacco-product",
    "electronic-product": "electronic-product",
}


class ClassificationStatus(str, Enum):
    """How far the classification can be relied on for applicability.

    Deliberately not the classifier's own vocabulary. The classifier says
    "category X at 0.72"; whether that is *confident enough to act on* is the
    policy's answer, and this enum carries the policy's answer.
    """

    #: Committed to a category, and the policy accepts this artifact at this
    #: confidence. The category may be established automatically.
    CONFIDENT = "confident"
    #: Committed to a category, but the policy does not accept it - because
    #: the artifact is not licensed at all, or the confidence is below the
    #: floor its evaluation established. Offered for confirmation.
    UNCERTAIN = "uncertain"
    #: The classifier ran and declined to choose.
    UNKNOWN = "unknown"
    #: No usable classification: none recorded, null, or malformed.
    FAILED = "failed"


class Disposition(str, Enum):
    """What became of a proposed fact."""

    ESTABLISHED_AUTOMATICALLY = "established_automatically"
    CONFIRMED_BY_SUBMITTER = "confirmed_by_submitter"
    STATED_BY_SUBMITTER = "stated_by_submitter"
    CONTRADICTED_BY_SUBMITTER = "contradicted_by_submitter"
    NEEDS_CONFIRMATION = "needs_confirmation"
    NOT_PROPOSED = "not_proposed"


# --- 1. reading the classification ------------------------------------------


@dataclass(frozen=True)
class Classification:
    """The classifier's recorded output, checked for shape and nothing more."""

    #: True when a well-formed classification was recorded, whatever it says.
    usable: bool
    #: True when `category` is a real code rather than "unknown".
    committed: bool
    category: str | None = None
    subcategory: str | None = None
    confidence: float | None = None
    subcategory_confidence: float | None = None
    classifier_name: str = ""
    classifier_version: str = ""
    evidence: tuple[str, ...] = ()
    #: Why it is not usable, when it is not.
    problem: str = ""

    @property
    def artifact(self) -> str:
        return f"{self.classifier_name}/{self.classifier_version}"


def _unit_interval(value: Any) -> float | None:
    """A float in [0, 1], or None for null. Anything else is malformed."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("confidence must be a number or null")
    number = float(value)
    if number != number or not 0.0 <= number <= 1.0:  # NaN, or out of range
        raise ValueError("confidence must lie in [0, 1]")
    return number


def read_classification(run: ExtractionRun | None) -> Classification:
    """Read `metadata.product_classification` off a run, defensively.

    Every malformed shape becomes `usable=False` with a `problem` naming what
    was wrong, never an exception and never a partial reading: a classification
    with a category string but a confidence of "high" is not half usable.
    """
    if run is None:
        return Classification(usable=False, committed=False, problem="no reading")

    raw_output = run.raw_output if isinstance(run.raw_output, dict) else {}
    metadata = raw_output.get("metadata")
    if not isinstance(metadata, dict) or "product_classification" not in metadata:
        return Classification(
            usable=False,
            committed=False,
            problem="no classification was recorded for this reading",
        )

    value = metadata.get("product_classification")
    if value is None:
        return Classification(
            usable=False,
            committed=False,
            problem="the classifier produced no classification for this reading",
        )
    if not isinstance(value, dict):
        return Classification(
            usable=False, committed=False, problem="the recorded classification is malformed (not an object)"
        )

    try:
        category = value.get("category")
        if not isinstance(category, str) or not category.strip():
            raise ValueError("category must be a non-empty string")
        category = category.strip()

        subcategory = value.get("subcategory")
        if subcategory is not None and not isinstance(subcategory, str):
            raise ValueError("subcategory must be a string or null")
        if category == UNKNOWN_CATEGORY and subcategory:
            raise ValueError("a subcategory cannot hang off an unknown category")

        confidence = _unit_interval(value.get("confidence"))
        subcategory_confidence = _unit_interval(value.get("subcategory_confidence"))

        name = value.get("classifier_name")
        version = value.get("classifier_version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("classifier_name and classifier_version must be strings")

        raw_evidence = value.get("evidence") or ()
        if not isinstance(raw_evidence, (list, tuple)):
            raise ValueError("evidence must be a list")
        evidence = tuple(str(item) for item in raw_evidence if isinstance(item, str))
    except ValueError as exc:
        logger.warning(
            "Malformed product classification on extraction run %s ignored: %s",
            run.pk,
            exc,
        )
        return Classification(
            usable=False, committed=False, problem=f"the recorded classification is malformed ({exc})"
        )

    committed = category != UNKNOWN_CATEGORY
    return Classification(
        usable=True,
        committed=committed,
        category=category if committed else None,
        subcategory=subcategory or None,
        confidence=confidence,
        subcategory_confidence=subcategory_confidence,
        classifier_name=name,
        classifier_version=version,
        evidence=evidence,
    )


# --- 2. the policy -----------------------------------------------------------


@dataclass(frozen=True)
class PolicyEntry:
    """One artifact a held-out evaluation has licensed for automatic use."""

    artifact: str
    min_confidence: float
    evaluation: str


def accepted_policy(classification: Classification) -> PolicyEntry | None:
    """The policy entry licensing this classification's artifact, if any.

    Reads `settings.AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS` on every
    call, so a test can assert both positions of the switch and a deployment
    change needs only a restart. A malformed entry is logged and treated as no
    entry: misconfiguration must fail closed, towards asking a person.
    """
    entries = getattr(settings, "AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS", None)
    if not isinstance(entries, dict) or not classification.usable:
        return None
    raw = entries.get(classification.artifact)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        logger.warning(
            "AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS[%r] is not an object; ignored",
            classification.artifact,
        )
        return None
    min_confidence = raw.get("min_confidence")
    evaluation = raw.get("evaluation")
    if (
        isinstance(min_confidence, bool)
        or not isinstance(min_confidence, (int, float))
        or not 0.0 < float(min_confidence) <= 1.0
        or not isinstance(evaluation, str)
        or not evaluation.strip()
    ):
        logger.warning(
            "AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS[%r] must name a "
            "min_confidence in (0, 1] and the evaluation that established it; ignored",
            classification.artifact,
        )
        return None
    return PolicyEntry(
        artifact=classification.artifact,
        min_confidence=float(min_confidence),
        evaluation=evaluation.strip(),
    )


def classify_status(
    classification: Classification, policy: PolicyEntry | None
) -> tuple[ClassificationStatus, str]:
    """The status the policy assigns, with the reason in plain words."""
    if not classification.usable:
        return ClassificationStatus.FAILED, classification.problem.capitalize() + "."
    if not classification.committed:
        why = next(
            (item for item in classification.evidence if not item.startswith(("signal:", "term:"))),
            "the classifier declined to choose a category",
        )
        return ClassificationStatus.UNKNOWN, f"The classifier could not tell what kind of product this is: {why}."
    if policy is None:
        return (
            ClassificationStatus.UNCERTAIN,
            f"The classifier {classification.classifier_name} {classification.classifier_version} "
            f"is not accepted for automatic use: no held-out evaluation on verified labels has "
            f"established an operating point for it, so its category is a suggestion for a "
            f"person to confirm.",
        )
    if classification.confidence is None or classification.confidence < policy.min_confidence:
        reported = "none" if classification.confidence is None else f"{classification.confidence:.2f}"
        return (
            ClassificationStatus.UNCERTAIN,
            f"The classifier's confidence ({reported}) is below the floor of "
            f"{policy.min_confidence:.2f} established by {policy.evaluation}, so its category "
            f"is a suggestion for a person to confirm.",
        )
    return (
        ClassificationStatus.CONFIDENT,
        f"The classifier {classification.classifier_name} {classification.classifier_version} "
        f"is accepted for automatic use at confidence {classification.confidence:.2f} "
        f"(floor {policy.min_confidence:.2f}, established by {policy.evaluation}).",
    )


# --- 3. establishing a category automatically --------------------------------


def _active_category(code: str | None) -> ProductCategory | None:
    if not code:
        return None
    return ProductCategory.objects.filter(code=code, is_active=True).first()


def establish_category(run: ExtractionRun, *, created_by=None) -> Product | None:
    """Create the product row carrying the classifier's category, if the policy allows.

    Called by the API layer only when no person has stated a category and the
    run's image is not already linked to a product - the two cases in which a
    person outranks this function are decided before it is reached. Returns
    None, and writes nothing, unless the classification is CONFIDENT under the
    accepted policy and names a category the catalogue actually has.

    The row it creates is the same kind of row `analysis_service` creates for a
    stated category, evaluated by the same engine; the only difference is the
    provenance written on it. That is the whole design: the classifier gets no
    path to the engine except through a category a person could have supplied.
    """
    classification = read_classification(run)
    policy = accepted_policy(classification)
    status, reason = classify_status(classification, policy)
    if status is not ClassificationStatus.CONFIDENT:
        return None

    category = _active_category(classification.category)
    if category is None:
        logger.info(
            "Classification %r on run %s is not an active product category; not established",
            classification.category,
            run.pk,
        )
        return None

    assert policy is not None  # CONFIDENT is only reachable with a policy
    product = Product.objects.create(
        name="Unidentified submission",
        category=category,
        category_source=Product.CategorySource.CLASSIFIER,
        category_basis=(
            f"Established automatically: {classification.classifier_name} "
            f"{classification.classifier_version} classified the label text as "
            f"'{classification.category}' at confidence {classification.confidence:.2f}; "
            f"accepted under AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS "
            f"(floor {policy.min_confidence:.2f}, evaluation: {policy.evaluation})."
        ),
        created_by=created_by,
    )
    logger.info(
        "Established category %s for run %s automatically from %s (confidence %.2f)",
        category.code,
        run.pk,
        classification.artifact,
        classification.confidence or 0.0,
    )
    return product


def can_establish_category(run: ExtractionRun) -> bool:
    """Whether `establish_category` would create a product for this run.

    Used by request validation: declarations need a product to hang on, and a
    run whose category the policy would establish can carry them without the
    caller restating the category.
    """
    classification = read_classification(run)
    status, _ = classify_status(classification, accepted_policy(classification))
    return status is ClassificationStatus.CONFIDENT and _active_category(classification.category) is not None


# --- 4. explaining what happened ---------------------------------------------


@dataclass(frozen=True)
class LabelSignal:
    """A phrase the reading actually contains, and what it usually indicates.

    `phrase` and `indicative_of` come from `labelextract.classification.signals`
    - a reviewed table of about thirty-five label phrases, which the model
      never reads. `snippet` is the surrounding text from **this run's stored
      reading**, so the person confirming can find it on the photograph.

    "Typically found with" is the whole claim. An ingredients list appears on a
    soap as readily as on a biscuit; the signal says the phrase is there, not
    what the product is.
    """

    phrase: str
    indicative_of: str
    snippet: str


@dataclass(frozen=True)
class DeclaredField:
    """One declaration the extractor read, offered as context for the suggestion.

    Not evidence *for* a category - a net quantity says nothing about whether a
    package is food - but it is what the pipeline actually read, and a person
    deciding whether the system has understood the label at all needs to see it.
    """

    field_key: str
    value: str


@dataclass(frozen=True)
class Evidence:
    """What the reading offers in support of the classifier's suggestion.

    Three lists, kept apart because they are three different kinds of thing:

    - `label_signals` - phrases **in this reading**, checkable against the
      photograph. The evidence a person can act on.
    - `declared_fields` - what the extractor read off the label. Context.
    - `model_terms` - n-grams the model weighed, as the classifier recorded
      them. Model internals, not statements about the product: on a ten-product
      training set these include function words. Reported for a developer
      reading the technical detail, never as a reason the product is anything.

    `has_supporting_evidence` is false when the first two are empty, and the
    client must then say so plainly rather than implying the suggestion is
    unsupported-but-probably-right. Nothing here is generated: every string is
    either a phrase found in the reading, a value the extractor read, or a
    term the classifier itself recorded.
    """

    label_signals: list[LabelSignal]
    declared_fields: list[DeclaredField]
    model_terms: list[str]
    has_supporting_evidence: bool
    note: str


def _label_signals(run: ExtractionRun | None) -> list[LabelSignal]:
    """Phrases the signal table finds in this run's stored reading.

    Asked of `apps.extraction`, which owns the ML seam - see
    `extraction_service.label_phrases` for why the lookup lives there and why
    it runs no engine. Matched against the reading rather than read out of the
    classification's recorded evidence strings, because matching gives the
    position and so the snippet: "signal: soap / bathing bar" says a phrase was
    seen and gives no way to see it, and the snippet is the whole point.

    It decides nothing. No category, no policy outcome and no applicability
    answer depends on the result.
    """
    text = (run.recognised_text or "") if run is not None else ""
    return [
        LabelSignal(
            phrase=found.phrase,
            indicative_of=found.indicative_of,
            snippet=found.snippet,
        )
        for found in extraction_service.label_phrases(text, limit=MAX_LABEL_SIGNALS)
    ]


def _declared_fields(run: ExtractionRun | None) -> list[DeclaredField]:
    """The declarations the extractor read, as it read them.

    `run.fields.all()` reads the prefetch the result serializer already loads
    for the embedded reading, so this costs no query on the response path.
    """
    if run is None:
        return []
    fields: list[DeclaredField] = []
    for field in run.fields.all():
        value = (field.raw_value or "").strip()
        if not value:
            continue
        fields.append(DeclaredField(field_key=field.field_key, value=value))
        if len(fields) >= MAX_DECLARED_FIELDS:
            break
    return fields


def _model_terms(classification: Classification) -> list[str]:
    """The n-grams the classifier recorded as having weighed most.

    Parsed out of the evidence strings the classifier wrote - `term: 'x'
    weighed for y` - so a client can keep them apart from the label phrases in
    the same list. The quoted term is returned on its own; the subcategory it
    was weighed for is not, because a term's contribution to a class the
    classifier did not choose is not something to show beside a suggestion.
    """
    terms: list[str] = []
    for item in classification.evidence:
        if not item.startswith("term: "):
            continue
        quoted = item[len("term: ") :]
        end = quoted.find("' weighed for ")
        term = quoted[1:end] if quoted.startswith("'") and end > 0 else ""
        if term:
            terms.append(term)
        if len(terms) >= MAX_MODEL_TERMS:
            break
    return terms


def gather_evidence(run: ExtractionRun | None, classification: Classification) -> Evidence:
    """What this reading offers in support of the classifier's suggestion."""
    label_signals = _label_signals(run)
    declared_fields = _declared_fields(run)
    supporting = bool(label_signals or declared_fields)

    if supporting:
        note = ""
    elif run is not None and (run.recognised_text or "").strip():
        note = (
            "The label was read, but none of the phrases this system recognises as "
            "indicating a kind of product was found in it, and no declaration was "
            "extracted. There is no evidence from the label behind this suggestion."
        )
    else:
        note = (
            "No text was read from this photograph, so there is no evidence from the "
            "label to support any suggestion about what kind of product this is."
        )

    return Evidence(
        label_signals=label_signals,
        declared_fields=declared_fields,
        model_terms=_model_terms(classification),
        has_supporting_evidence=supporting,
        note=note,
    )


@dataclass(frozen=True)
class CategoryAssessment:
    proposed: str | None
    proposed_name: str | None
    confidence: float | None
    in_effect: str | None
    in_effect_source: str | None
    disposition: Disposition
    reason: str


@dataclass(frozen=True)
class FactAssessment:
    condition: str
    name: str
    proposed_answer: str
    confidence: float | None
    basis: str
    #: The clauses this condition bears on, e.g. "6(1)(d): exempts".
    affects: list[str]
    in_effect: str
    in_effect_source: str | None
    disposition: Disposition
    reason: str


@dataclass(frozen=True)
class Question:
    """One thing a person still has to answer. Empty list means nothing.

    `outcome` says what answering does, in the terms the system can actually
    promise: which requirements the answer selects, and that the same stored
    reading is re-checked rather than the photograph read again. It is written
    here rather than in each client so the two cannot describe the same
    mechanism differently.
    """

    kind: str  # "category" | "condition"
    code: str | None
    suggested: str | None
    prompt: str
    outcome: str = ""
    #: For a category question: the categories a person may choose from.
    choices: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Assessment:
    status: ClassificationStatus
    reason: str
    classifier_name: str
    classifier_version: str
    classifier_confidence: float | None
    #: The classifier's own evidence strings, verbatim. Serialised under
    #: `classifier.evidence`, where it has always been. The structured view a
    #: person reads is `evidence` below.
    classifier_evidence: tuple[str, ...]
    policy_accepted: bool
    policy_min_confidence: float | None
    policy_evaluation: str | None
    category: CategoryAssessment
    facts: list[FactAssessment]
    questions: list[Question]
    evidence: Evidence


def _category_choices() -> list[dict[str, str]]:
    """The categories a person may choose between.

    Every active category below a root - the shipped taxonomy's
    `packaged-food` and `packaged-non-food` under `packaged-commodity`. An
    installation whose categories are flat gets all of them; an empty list
    would leave the person with a question and no way to answer it.
    """
    active = ProductCategory.objects.filter(is_active=True).order_by("code")
    below_root = [category for category in active if category.parent_id is not None]
    return [{"code": category.code, "name": category.name} for category in (below_root or list(active))]


def _affects(condition: ApplicabilityCondition) -> list[str]:
    links = (
        RequirementApplicability.objects.filter(condition=condition, requirement__is_active=True)
        .select_related("requirement")
        .order_by("requirement__clause")
    )
    return [f"{link.requirement.clause}: {link.mode}" for link in links]


def assess(check: ComplianceCheck) -> Assessment:
    """Describe the classification's part in a finished check.

    Read-only. Reads the check's run, its product and its declaration rows;
    consults the policy as it stands now. For a stored check evaluated under
    an earlier policy the category's provenance is on the product row, which
    is what the `in_effect_source` reports.
    """
    run = check.extraction_run
    product = check.product
    classification = read_classification(run)
    policy = accepted_policy(classification)
    status, reason = classify_status(classification, policy)

    # --- the category ------------------------------------------------------
    proposed = classification.category if classification.committed else None
    proposed_row = _active_category(proposed)
    in_effect = product.category.code if product is not None and product.category_id else None
    in_effect_source = product.category_source if in_effect else None

    if in_effect:
        if in_effect_source == Product.CategorySource.CLASSIFIER:
            disposition = Disposition.ESTABLISHED_AUTOMATICALLY
            category_reason = product.category_basis or "Established automatically from the classifier."
        elif proposed and proposed == in_effect:
            disposition = Disposition.CONFIRMED_BY_SUBMITTER
            category_reason = (
                f"A person stated '{in_effect}', which agrees with the classifier's suggestion."
            )
        elif proposed:
            disposition = Disposition.CONTRADICTED_BY_SUBMITTER
            category_reason = (
                f"A person stated '{in_effect}'; the classifier suggested '{proposed}'. "
                f"The person's statement is what was evaluated."
            )
        else:
            disposition = Disposition.STATED_BY_SUBMITTER
            category_reason = f"A person stated '{in_effect}'."
    elif proposed and proposed_row is not None:
        disposition = Disposition.NEEDS_CONFIRMATION
        category_reason = reason
    elif proposed:
        disposition = Disposition.NOT_PROPOSED
        category_reason = (
            f"The classifier answered '{proposed}', which is not a product category this "
            f"installation knows, so nothing was proposed."
        )
    else:
        disposition = Disposition.NOT_PROPOSED
        category_reason = reason

    category = CategoryAssessment(
        proposed=proposed if proposed_row is not None else None,
        proposed_name=proposed_row.name if proposed_row is not None else None,
        confidence=classification.confidence if classification.committed else None,
        in_effect=in_effect,
        in_effect_source=in_effect_source,
        disposition=disposition,
        reason=category_reason,
    )

    # --- the conditions a subcategory suggests --------------------------------
    facts: list[FactAssessment] = []
    condition_code = SUBCATEGORY_CONDITIONS.get(classification.subcategory or "")
    if classification.committed and condition_code:
        condition = ApplicabilityCondition.objects.filter(code=condition_code, is_active=True).first()
        if condition is not None:
            declared = None
            if product is not None:
                declared = (
                    ProductApplicabilityDeclaration.objects.filter(product=product, condition=condition)
                    .first()
                )
            if declared is not None and declared.answer != ProductApplicabilityDeclaration.Answer.UNKNOWN:
                fact_in_effect = declared.answer
                fact_source = declared.source
                if declared.answer == ProductApplicabilityDeclaration.Answer.YES:
                    fact_disposition = Disposition.CONFIRMED_BY_SUBMITTER
                    fact_reason = "A person confirmed it."
                else:
                    fact_disposition = Disposition.CONTRADICTED_BY_SUBMITTER
                    fact_reason = "A person answered no; the person's answer is what was evaluated."
            elif not condition.is_determinable:
                fact_in_effect = applicability.UNKNOWN
                fact_source = None
                fact_disposition = Disposition.NOT_PROPOSED
                fact_reason = (
                    "The legal framework records this fact as one this system cannot establish, "
                    "so no answer to it can take effect."
                )
            else:
                fact_in_effect = applicability.UNKNOWN
                fact_source = None
                fact_disposition = Disposition.NEEDS_CONFIRMATION
                fact_reason = (
                    "This fact exempts or triggers requirements, so it is never taken from the "
                    "classifier. It stays unknown until a person confirms it."
                )
            facts.append(
                FactAssessment(
                    condition=condition.code,
                    name=condition.name,
                    proposed_answer=applicability.YES,
                    confidence=classification.subcategory_confidence,
                    basis=(
                        f"The classifier's subcategory '{classification.subcategory}' corresponds "
                        f"to this condition."
                    ),
                    affects=_affects(condition),
                    in_effect=fact_in_effect,
                    in_effect_source=fact_source,
                    disposition=fact_disposition,
                    reason=fact_reason,
                )
            )

    # --- what a person still has to answer -----------------------------------
    questions: list[Question] = []
    if not in_effect:
        if category.proposed:
            prompt = (
                f"The label reads like {category.proposed_name.lower() if category.proposed_name else category.proposed}. "
                f"Is that right?"
            )
        else:
            prompt = "What kind of product is this?"
        questions.append(
            Question(
                kind="category",
                code=category.proposed,
                suggested=category.proposed,
                prompt=prompt,
                outcome=(
                    "Answering selects the requirements loaded for that product type and "
                    "checks them against this same reading. The photograph is not uploaded "
                    "or read again, and the answer is recorded as yours. Leaving it "
                    "unanswered is a supported choice: the result then says the product "
                    "type was not known rather than assuming one."
                ),
                choices=_category_choices(),
            )
        )
    for fact in facts:
        if fact.disposition is Disposition.NEEDS_CONFIRMATION:
            clauses = ", ".join(sorted({entry.split(":")[0] for entry in fact.affects}))
            questions.append(
                Question(
                    kind="condition",
                    code=fact.condition,
                    suggested=fact.proposed_answer,
                    prompt=f"Is this package {fact.name.lower()}? The label suggests it may be.",
                    outcome=(
                        (
                            f"Answering decides whether clause {clauses} is checked against "
                            f"this package, on this same reading. "
                            if clauses
                            else "Answering is recorded against this package, on this same reading. "
                        )
                        + "The answer is recorded as yours, not as the classifier's. "
                        "Left unanswered, the requirements that turn on it stay undecided "
                        "and are reported as needing review."
                    ),
                )
            )

    return Assessment(
        evidence=gather_evidence(run, classification),
        status=status,
        reason=reason,
        classifier_name=classification.classifier_name,
        classifier_version=classification.classifier_version,
        classifier_confidence=classification.confidence if classification.usable else None,
        classifier_evidence=classification.evidence,
        policy_accepted=policy is not None,
        policy_min_confidence=policy.min_confidence if policy else None,
        policy_evaluation=policy.evaluation if policy else None,
        category=category,
        facts=facts,
        questions=questions,
    )


def as_dict(assessment: Assessment) -> dict[str, Any]:
    """The JSON shape of `applicability_assessment` in a compliance result."""
    return {
        "status": assessment.status.value,
        "reason": assessment.reason,
        "classifier": {
            "name": assessment.classifier_name,
            "version": assessment.classifier_version,
            "confidence": assessment.classifier_confidence,
            "evidence": list(assessment.classifier_evidence),
        },
        "policy": {
            "accepted": assessment.policy_accepted,
            "min_confidence": assessment.policy_min_confidence,
            "evaluation": assessment.policy_evaluation,
        },
        "category": {
            "proposed": assessment.category.proposed,
            "proposed_name": assessment.category.proposed_name,
            "confidence": assessment.category.confidence,
            "in_effect": assessment.category.in_effect,
            "in_effect_source": assessment.category.in_effect_source,
            "disposition": assessment.category.disposition.value,
            "reason": assessment.category.reason,
        },
        "facts": [
            {
                "condition": fact.condition,
                "name": fact.name,
                "proposed_answer": fact.proposed_answer,
                "confidence": fact.confidence,
                "basis": fact.basis,
                "affects": fact.affects,
                "in_effect": fact.in_effect,
                "in_effect_source": fact.in_effect_source,
                "disposition": fact.disposition.value,
                "reason": fact.reason,
            }
            for fact in assessment.facts
        ],
        "questions": [
            {
                "kind": question.kind,
                "code": question.code,
                "suggested": question.suggested,
                "prompt": question.prompt,
                "outcome": question.outcome,
                "choices": question.choices,
            }
            for question in assessment.questions
        ],
        "evidence": {
            "has_supporting_evidence": assessment.evidence.has_supporting_evidence,
            "note": assessment.evidence.note,
            "label_signals": [
                {
                    "phrase": signal.phrase,
                    "indicative_of": signal.indicative_of,
                    "snippet": signal.snippet,
                }
                for signal in assessment.evidence.label_signals
            ],
            "declared_fields": [
                {"field_key": field_.field_key, "value": field_.value}
                for field_ in assessment.evidence.declared_fields
            ],
            "model_terms": list(assessment.evidence.model_terms),
        },
    }
