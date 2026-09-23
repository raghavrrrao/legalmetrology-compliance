"""Response shapes for a compliance result.

These serializers are read-only. They shape rows the services already wrote;
none of them creates, updates or decides anything. Bodies are `snake_case` per
`docs/api.md`; the frontend maps to camelCase in one place at its own boundary.

**What was read is not described here.** `ExtractedFieldSerializer` and
`ExtractionRunSerializer` belong to `apps.extraction.api.serializers`, and
`ProductImageSerializer` to `apps.images.api.serializers` - each with the app
that owns the rows. They are imported below and embedded unchanged, so the
reading in a compliance result is byte-for-byte the reading
`POST /api/v1/extraction/` returns, and there is one place to change it.

That direction matters beyond tidiness. A reading is an observation about a
photograph; a violation is a claim about a package under the Rules. Compliance
may depend on extraction, because a finding is made *from* a reading. Extraction
must never depend on compliance, or a reading starts to be shaped by what a rule
wants it to say.

The one thing this file is careful about on its own account: **nothing is
fabricated to make a result look complete.** A value that was not measured is
`null`, never a plausible-looking default - `processing_ms`, `bounding_box` and
`product_category_code` are all genuinely absent sometimes, and the last of
those is load-bearing.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.catalog.models import ProductApplicabilityDeclaration, ProductCategory
from apps.compliance.models import (
    ComplianceCheck,
    ComplianceEvidence,
    ComplianceFinding,
    ComplianceViolation,
)
from apps.compliance.services import auto_applicability
from apps.extraction.api.serializers import (
    ExtractedFieldSerializer,
    ExtractionRunSerializer,
    run_image_entries,
)
from apps.extraction.models import ExtractionRun
from apps.images.api.serializers import ProductImageSerializer
from apps.rules.models import ApplicabilityCondition

__all__ = [
    "ComplianceCheckListSerializer",
    "ComplianceCheckSerializer",
    "ComplianceEvaluationRequestSerializer",
    "ComplianceFindingSerializer",
    "EvidenceSerializer",
    "ExtractedFieldSerializer",
    "ExtractionRunSerializer",
    "ProductImageSerializer",
    "ViolationSerializer",
]


def _product_category_code(check: ComplianceCheck) -> str | None:
    """The category whose rules were considered, or None if none was known.

    Shared by the list and detail serializers so the two cannot drift. Null is
    load-bearing: it is the difference between "we checked the rules for
    packaged food and found nothing wrong" and "we did not know what this
    commodity is, so we could not know which rules apply". The engine reports
    the second as REVIEW_REQUIRED and a client needs to be able to say why.
    """
    product = check.product
    if product is None or product.category_id is None:
        return None
    return product.category.code


class EvidenceSerializer(serializers.ModelSerializer):
    """What was read from the image that supports a finding.

    Attached even to a finding of absence: the text we *did* read is the
    justification for concluding a declaration was not there.

    `image_id` is the photograph this evidence should be shown against, and
    matches one of the `images[].image.id` values on the same result. When the
    evidence is a reading, it is the photograph that reading came from - so an
    interface can say "Evidence · Image 2" and mean it, and a bounding box is
    drawn over the panel it was measured on rather than over whichever
    photograph happened to be first.

    For a finding of **absence** it is the primary photograph, because there is
    no reading to have a source and no single photograph is more the evidence
    than another: the declaration was absent from the whole set. A client must
    not turn that into a claim that the declaration should have been on that
    panel - "image 1 is missing the net quantity" is a statement this system
    has not made and cannot make.

    No confidence here, deliberately. It would mean following
    `extracted_field` per evidence row - a query each on the POST paths, which
    do not prefetch - to reach a number `ComplianceFinding` already snapshots
    as a plain column. A client that wants the confidence behind a violation
    reads that violation's finding, which is linked to it.
    """

    image_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="The photograph this evidence should be shown against.",
    )

    class Meta:
        model = ComplianceEvidence
        fields = ["excerpt", "bounding_box", "note", "image_id"]
        read_only_fields = fields


class ViolationSerializer(serializers.ModelSerializer):
    """One rule that was not met, with its snapshotted legal provenance.

    `rule_code`, `legal_reference` and `severity` are read from the violation
    row rather than followed through to the live `ComplianceRule`, because the
    model snapshots them deliberately: an amended rule must not silently change
    what a past finding meant.

    `severity` is a triage ranking with no legal weight - `rules/SCHEMA.md`
    says so, and the UI must not present it as one.
    """

    evidence = EvidenceSerializer(many=True, read_only=True)

    class Meta:
        model = ComplianceViolation
        fields = [
            "id",
            "rule_code",
            "legal_reference",
            "severity",
            "field_key",
            "message",
            "evidence",
        ]
        read_only_fields = fields


class ComplianceFindingSerializer(serializers.ModelSerializer):
    """One rule's outcome, with everything needed to check it by hand.

    The complete trace, not only the failures: a rule that passed and a rule
    that could not be decided each get a row here. `violations` remains the
    list of things found wrong with the package; this is the list of what was
    actually examined.

    Reading one finding answers, in order:

        rule_code, title, requirement   what was required, and by whose words
        legal_reference                 where that requirement comes from
        check_type                      which deterministic check asked it
        field_key                       which declaration it concerns
        evidence_excerpt, bounding_box  what was read, and where on the image
        extracted_confidence            how sure the reader was
        status                          what the check concluded
        message                         why, in plain language
        severity                        triage ranking only, no legal weight

    Four further fields come from the legal framework rather than from the
    executable rule, and are blank when the rule is not mapped to a clause:

        clause                  the sub-rule this concerns, e.g. '6(1)(c)'
        legal_source_citation   the instrument that established it
        detection_method        what evidence could settle it at all
        applicability_note      why it was applied, and what could not be
                                established about whether it applies

    Five of these are easy to misread and are worth stating plainly:

    - **`status` is four-valued.** `inconclusive` is not a soft fail: it means
      the check could not be decided - usually because the photograph was not
      readable, or because a fact deciding whether the rule applies was never
      declared - and treating it as either a pass or a violation is the single
      most damaging thing a client can do with this data. `not_applicable` is
      different again: the rule does not govern this package, so nothing about
      its declarations was examined. It is not a pass, and a client that counts
      it as one turns a set of exemptions into a clean bill of health.
    - **`extracted_confidence` is recorded, not enforced.** No rule in this
      repository conditions its outcome on it, so a `passed` finding built on a
      low-confidence reading is still `passed`. The number is exposed precisely
      so that cannot happen silently: a client showing a finding should show
      what the reading behind it was worth. `null` means the OCR engine did not
      report a confidence, and is not zero.
    - **`downgraded_from_failed` means the check failed but the rule is not
      verified** against the authoritative legal text, so the engine recorded
      it as inconclusive rather than as a violation. It is surfaced because a
      reviewer needs to see the safeguard fire, not infer it from a rule code.
    - **`detection_method` says whether a photograph could ever have settled
      this.** Anything other than `ocr`, `cv` or `ocr_cv` names evidence this
      pipeline does not have - a physical weighing, a regulator's register, an
      e-commerce listing - and a finding carrying one of those is a prompt for
      human review whatever its `status` reads.
    - **`applicability_note` is not boilerplate.** It carries the caveat that
      applies to every result: applicability is decided from the commodity
      category alone, and the facts rules 3 and 26 turn on are not collected,
      so a rule may have been applied to a package outside the Rules. A client
      that hides this is presenting a narrower claim than the data supports.

    `extracted_raw_value` and `extracted_normalized_value` are both present and
    neither replaces the other. The raw text is what was recognised; the
    normalised value is an interpretation of it, and is `null` when no
    normaliser ran - never because the reading was empty.
    """

    class Meta:
        model = ComplianceFinding
        fields = [
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
        ]
        read_only_fields = fields


class AppliedDeclarationSerializer(serializers.ModelSerializer):
    """One fact stated about the package, as it stood when the result was read.

    The third kind of evidence in a result, and it must not be confused with
    the other two. An `ExtractedLabelField` is something the pipeline *read off
    the photograph*. A `ComplianceFinding` is what a rule *concluded*. This is
    something a **person asserted** about the goods - that the package contains
    bidi, that it is imported - which no photograph could establish and which
    the Rules make decisive.

    Surfaced on the result because a finding's `applicability_note` explains
    the reasoning but not the inputs, and a reviewer opening a permalinked
    result days later has no other way to see what was declared or by whom.

    `stated_before_this_check` is the honest part. Declarations hang off the
    `Product`, not off the check, so a fact recorded *after* an evaluation is
    still attached to the product it describes and would appear here. Rather
    than snapshot every answer onto every check - a migration, and a second
    copy of the same fact - the row is compared against the check's own start
    time, so a client can mark the rare declaration that could not have
    influenced the result it is being shown beside.
    """

    code = serializers.CharField(source="condition.code", read_only=True)
    name = serializers.CharField(source="condition.name", read_only=True)
    answer_display = serializers.CharField(
        source="get_answer_display", read_only=True
    )
    source_display = serializers.CharField(
        source="get_source_display", read_only=True
    )
    stated_before_this_check = serializers.SerializerMethodField()

    class Meta:
        model = ProductApplicabilityDeclaration
        fields = [
            "code",
            "name",
            "answer",
            "answer_display",
            "source",
            "source_display",
            "note",
            "stated_before_this_check",
        ]
        read_only_fields = fields

    def get_stated_before_this_check(self, declaration) -> bool | None:
        """Whether this answer already stood when the check was evaluated.

        `updated_at`, not `created_at`: re-declaring a condition corrects the
        row in place, so an answer created before the check and changed after
        it is not the answer the check saw.

        None when the check never recorded a start time, which is not something
        to guess at - a client showing "yes" there would be asserting a
        comparison nobody made.
        """
        check = self.context.get("compliance_check")
        started = getattr(check, "started_at", None)
        if started is None:
            return None
        return declaration.updated_at <= started


class ComplianceEvaluationRequestSerializer(serializers.Serializer):
    """The JSON body of `POST /api/v1/compliance/`.

    Three fields, and what is *absent* from them is the important part. There is
    no rule code, no check type, no severity, no engine name and no threshold.
    A caller cannot choose which rules run or how strictly - applicability is
    answered by `engine.applicable_rules` from the loaded rule set and the
    commodity's category, and nothing in a request reaches that decision.

    That is not defensive coding for its own sake. A compliance verdict a
    client could steer by picking its own rules would be worth nothing.

    `applicability_declarations` is not an exception to that, and the
    distinction is the whole reason it is safe to accept. It does not say which
    rules to run. It states **facts about the goods** - this package contains
    bidi, this package is imported - which the Rules themselves make decisive
    and which no photograph can establish. The engine still decides what those
    facts mean, from conditions loaded out of the verified framework. A caller
    who lies is making a false declaration about their own product, recorded
    against it with its source, which is a different thing from steering the
    rule set.
    """

    extraction_run_id = serializers.UUIDField(
        help_text=(
            "The reading to evaluate, as returned by "
            "POST /api/v1/extraction/. The verdict is drawn from this stored "
            "reading; the photograph is not read again."
        ),
    )
    category_code = serializers.SlugField(
        required=False,
        allow_blank=True,
        help_text=(
            "ProductCategory.code for the commodity, when it is known. "
            "Determines which rules apply. Ignored when the run's image is "
            "already linked to a product - that product's category wins, and "
            "silently reassigning it would rewrite a record the caller did "
            "not ask to change. Omitting it is honest and supported: the "
            "result then says the category was unknown rather than assuming "
            "one."
        ),
    )

    applicability_declarations = serializers.DictField(
        required=False,
        child=serializers.ChoiceField(
            choices=ProductApplicabilityDeclaration.Answer.choices
        ),
        help_text=(
            "Facts about the package that decide whether a clause applies to "
            "it, as {condition_code: yes|no|unknown}. Condition codes are "
            "`ApplicabilityCondition.code` values loaded from "
            "rules/framework/applicability_conditions.json - for example "
            "'imported-product', 'bidi', 'domestic-lpg-cylinder'. "
            "Optional, and omitting it is the honest default: an unstated fact "
            "stays unestablished, and a clause whose applicability turns on one "
            "reaches REVIEW_REQUIRED rather than a verdict. Sending 'unknown' "
            "is the same as not sending the code at all, and is accepted so a "
            "form can record that somebody was asked. "
            "Recorded against the product this reading belongs to, with source "
            "'submitter', and visible on every finding the answer influenced. "
            "Nothing here is read from the label: using an extracted value to "
            "decide whether to check for it would be circular."
        ),
    )

    def validate_extraction_run_id(self, value):
        """Resolve the run now, so an unknown id is a 400 and not a 500.

        Returns the row rather than the id: the view would otherwise fetch it
        again, and a second lookup is a second chance for the two to disagree.
        """
        try:
            return ExtractionRun.objects.select_related(
                "image", "image__product", "image__product__category"
            ).get(pk=value)
        except ExtractionRun.DoesNotExist:
            raise serializers.ValidationError(
                f"No extraction run with id {value}."
            ) from None

    def validate_category_code(self, value: str) -> str:
        """Reject a category that does not exist, rather than ignoring it.

        A typo'd code that was silently dropped would produce a
        REVIEW_REQUIRED result reading "the commodity category is not known" -
        which looks identical to not having sent one, and would send the user
        looking for the problem in the photograph instead of in their request.
        """
        if not value:
            return ""
        if not ProductCategory.objects.filter(code=value, is_active=True).exists():
            raise serializers.ValidationError(
                f"No active product category with code {value!r}. Load "
                f"categories with `manage.py seed_categories`."
            )
        return value

    def validate_applicability_declarations(self, value: dict) -> dict:
        """Reject a code the framework does not define, or cannot use.

        Two rejections, and the second is the one worth explaining.

        An **unknown code** is rejected rather than dropped, for the reason a
        typo'd category code is: silently ignoring it produces a result reading
        "this could not be determined", which looks identical to not having sent
        the fact at all and sends the user looking in the wrong place.

        A code the framework marks **not determinable** is rejected too, even
        though it is a real condition. `applicability.DeclarationSet.answer`
        returns UNKNOWN for those whatever anyone states - the framework's
        judgement that this system cannot establish a fact outranks a claim
        about it, which is what stops a submitter switching off a check by
        asserting a rule 33 relaxation nobody can confirm. Accepting the answer
        and then ignoring it would let a caller believe they had declared
        something. Saying so is the honest response.
        """
        if not value:
            return {}

        conditions = {
            condition.code: condition
            for condition in ApplicabilityCondition.objects.filter(
                code__in=list(value), is_active=True
            )
        }
        unknown = sorted(set(value) - set(conditions))
        if unknown:
            raise serializers.ValidationError(
                f"No active applicability condition with code(s) "
                f"{', '.join(repr(code) for code in unknown)}. Codes come from "
                f"rules/framework/applicability_conditions.json; load them with "
                f"`manage.py load_legal_framework`."
            )

        undeterminable = sorted(
            code
            for code, condition in conditions.items()
            if not condition.is_determinable
        )
        if undeterminable:
            raise serializers.ValidationError(
                f"Condition(s) {', '.join(repr(c) for c in undeterminable)} are "
                f"recorded in the legal framework as facts this system cannot "
                f"establish, so an answer to them cannot affect any check and is "
                f"not accepted. See ApplicabilityCondition.determination_note."
            )

        return value

    def validate(self, attrs: dict) -> dict:
        """Refuse declarations that would have nowhere to be recorded.

        Declarations hang off `Product`, and a product is what carries the
        commodity category. With neither an existing product on the run's image
        nor a `category_code` to make one from, no rule applies to this
        submission at all - the result is REVIEW_REQUIRED because the commodity
        is unknown - and the declarations would be silently discarded. Saying so
        is more useful than accepting them and returning a result they had no
        part in.
        """
        declarations = attrs.get("applicability_declarations")
        if not declarations:
            return attrs
        run = attrs["extraction_run_id"]
        if (
            run.image.product is None
            and not attrs.get("category_code")
            # A category the accepted classification policy will establish
            # is a product to hang them on too - see auto_applicability.
            and not auto_applicability.can_establish_category(run)
        ):
            raise serializers.ValidationError(
                {
                    "applicability_declarations": (
                        "Applicability declarations are recorded against the "
                        "product this reading belongs to, and this reading's "
                        "image has no product. Send 'category_code' as well, so "
                        "the commodity is known - without it no rule applies and "
                        "the declarations could not affect the result."
                    )
                }
            )
        return attrs


class ComplianceCheckSerializer(serializers.ModelSerializer):
    """The full result: verdict, explanation, findings, and what was read.

    `result` is the verdict the UI shows. `result_display` is its human label,
    taken from the model's own choices rather than restated here, so the two
    cannot drift.

    `summary` is not decoration. It is the engine's plain-language explanation
    of *why* this verdict was reached - including "no rules are loaded, so
    nothing was checked" - and a UI that shows the verdict without it can imply
    a determination the system did not make.

    **Three kinds of evidence come back here and a client must keep them
    apart.** `extraction` is what the pipeline read off the photograph;
    `findings` are what the rules concluded from it; `applicability_declarations`
    are facts a *person asserted* about the goods, which no photograph could
    establish and which decide whether a clause governs the package at all.
    Presenting the third as though it were the first would show a submitter's
    claim as a measurement.
    """

    result_display = serializers.CharField(
        source="get_result_display", read_only=True
    )
    violations = ViolationSerializer(many=True, read_only=True)
    findings = ComplianceFindingSerializer(many=True, read_only=True)
    extraction = ExtractionRunSerializer(source="extraction_run", read_only=True)
    image = ProductImageSerializer(source="extraction_run.image", read_only=True)
    images = serializers.SerializerMethodField()
    product_category_code = serializers.SerializerMethodField()
    product_category_source = serializers.SerializerMethodField()
    applicability_declarations = serializers.SerializerMethodField()
    applicability_assessment = serializers.SerializerMethodField()

    class Meta:
        model = ComplianceCheck
        fields = [
            "id",
            "status",
            "result",
            "result_display",
            "summary",
            "engine_version",
            "rules_evaluated",
            "rules_passed",
            "rules_failed",
            "rules_inconclusive",
            "rules_not_applicable",
            "processing_ms",
            "completed_at",
            "product_category_code",
            "product_category_source",
            "applicability_declarations",
            "applicability_assessment",
            "violations",
            "findings",
            "extraction",
            "image",
            "images",
        ]
        read_only_fields = fields

    def get_images(self, check: ComplianceCheck) -> list:
        """Every photograph this one inspection was made from, in order.

        **One result, several photographs.** This is a set of images that were
        read together into one reading and judged once, not a set of results
        shown side by side. A client should say "3 images checked" and show one
        verdict; showing three verdicts would be describing something this
        system did not do.

        `image` above is the primary photograph and stays for the clients that
        predate the set. It is `images[0].image`, always.

        The same list the embedded `extraction` carries, surfaced at the top
        level beside `image` so that a result screen does not have to reach
        through the reading to count the photographs it was made from. Built by
        the same function, so the two can never disagree.
        """
        return run_image_entries(check.extraction_run)

    def get_applicability_declarations(self, check: ComplianceCheck) -> list:
        """The facts stated about this package, as evidence beside the findings.

        Empty when the check has no product - a submission whose commodity was
        never identified has nothing to hang a declaration on - and empty when
        nobody declared anything, which is the ordinary case and is exactly
        what a client should show: "no facts were stated, so the clauses that
        turn on them could not be decided."
        """
        if check.product_id is None:
            return []
        declarations = (
            ProductApplicabilityDeclaration.objects.filter(product_id=check.product_id)
            .select_related("condition")
            .order_by("condition__code")
        )
        return AppliedDeclarationSerializer(
            declarations,
            many=True,
            context={**self.context, "compliance_check": check},
        ).data

    def get_product_category_code(self, check: ComplianceCheck) -> str | None:
        """The category whose rules were considered, or null if none was known.

        See `_product_category_code`, which the list serializer shares.
        """
        return _product_category_code(check)

    def get_product_category_source(self, check: ComplianceCheck) -> str | None:
        """Who set the category: `submitter`, `reviewer` or `classifier`.

        Null when there is no category. The one word that tells a reader
        whether the rules that ran were chosen by a person or, under an
        accepted policy, by the label classifier.
        """
        if _product_category_code(check) is None:
            return None
        return check.product.category_source

    def get_applicability_assessment(self, check: ComplianceCheck) -> dict:
        """What the label classification proposed, and what became of it.

        The fourth kind of evidence on a result, and the one most easily
        mistaken for the others: a *suggestion* from a model, with the model's
        own confidence attached. It is kept in its own key so a client cannot
        render it as a reading, a declaration or a finding by accident, and it
        says in `status` whether the policy accepted it (`confident`), offered
        it for confirmation (`uncertain`), or had nothing to offer (`unknown`,
        `failed`). `questions` is what a person still has to answer; empty
        means nothing. See docs/automatic-applicability.md.
        """
        return auto_applicability.as_dict(auto_applicability.assess(check))


class ComplianceCheckListSerializer(serializers.ModelSerializer):
    """One row of inspection history - the verdict and how to reach the rest.

    Deliberately **not** `ComplianceCheckSerializer`. That serializer embeds
    every finding, every violation, each violation's evidence, the whole
    reading, and the image metadata; a history page of twenty results would
    return a few hundred kilobytes of evidence excerpts and bounding boxes that
    a list cannot display, to answer a question ("what was checked, when, and
    what came out?") that needs none of it.

    So this exposes only what a history row shows or navigates by:

        id                              the link to the full result
        result, result_display          the verdict, and its human label
        status                          lifecycle of the evaluation itself
        created_at, completed_at        when it was asked for, and finished
        product_category_code           whose rules were considered, or null
        engine_version                  which engine produced it
        extraction_run_id               the reading it was drawn from
        findings_count                  rules examined
        violations_count                rules the package failed

    `status` and `result` are the two different questions the model already
    separates and the list keeps separate: `status` says whether the evaluation
    ran, `result` says what it concluded. A row whose status is `failed` has no
    verdict to show, and collapsing the two here would invent one.

    The two counts are **annotated on the queryset**, not read from the stored
    `rules_*` columns and not counted per row in Python. They count the rows the
    detail endpoint would actually return, which is the honest answer for a
    check written before `ComplianceFinding` existed - its stored
    `rules_evaluated` is non-zero and it has no findings.

    Everything omitted here is on `GET /api/v1/compliance/<uuid>/`, which stays
    the single source of the full trace: `summary`, `findings`, `violations`,
    evidence excerpts, bounding boxes, confidences, and the reading itself.
    """

    result_display = serializers.CharField(
        source="get_result_display", read_only=True
    )
    extraction_run_id = serializers.UUIDField(read_only=True)
    product_category_code = serializers.SerializerMethodField()
    # Populated by ComplianceCheckListView.get_queryset. Declared read-only
    # integers rather than left implicit so the response shape is stated here,
    # with the rest of the contract, and not only in the view's annotation.
    findings_count = serializers.IntegerField(read_only=True)
    violations_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ComplianceCheck
        fields = [
            "id",
            "status",
            "result",
            "result_display",
            "created_at",
            "completed_at",
            "engine_version",
            "extraction_run_id",
            "product_category_code",
            "findings_count",
            "violations_count",
        ]
        read_only_fields = fields

    def get_product_category_code(self, check: ComplianceCheck) -> str | None:
        """See `_product_category_code`, shared with the detail serializer."""
        return _product_category_code(check)
