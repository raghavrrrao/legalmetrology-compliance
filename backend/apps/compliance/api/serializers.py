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

from apps.catalog.models import ProductCategory
from apps.compliance.models import (
    ComplianceCheck,
    ComplianceEvidence,
    ComplianceFinding,
    ComplianceViolation,
)
from apps.extraction.api.serializers import (
    ExtractedFieldSerializer,
    ExtractionRunSerializer,
)
from apps.extraction.models import ExtractionRun
from apps.images.api.serializers import ProductImageSerializer

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

    No confidence here, deliberately. It would mean following
    `extracted_field` per evidence row - a query each on the POST paths, which
    do not prefetch - to reach a number `ComplianceFinding` already snapshots
    as a plain column. A client that wants the confidence behind a violation
    reads that violation's finding, which is linked to it.
    """

    class Meta:
        model = ComplianceEvidence
        fields = ["excerpt", "bounding_box", "note"]
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

    Three of these are easy to misread and are worth stating plainly:

    - **`status` is three-valued.** `inconclusive` is not a soft fail. It means
      the check could not be decided - usually because the photograph was not
      readable - and treating it as either a pass or a violation is the single
      most damaging thing a client can do with this data.
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
    """

    class Meta:
        model = ComplianceFinding
        fields = [
            "id",
            "rule_code",
            "title",
            "requirement",
            "legal_reference",
            "check_type",
            "severity",
            "status",
            "downgraded_from_failed",
            "field_key",
            "extracted_confidence",
            "message",
            "evidence_excerpt",
            "bounding_box",
            "details",
            "violation",
        ]
        read_only_fields = fields


class ComplianceEvaluationRequestSerializer(serializers.Serializer):
    """The JSON body of `POST /api/v1/compliance/`.

    Two fields, and what is *absent* from them is the important part. There is
    no rule code, no check type, no severity, no engine name and no threshold.
    A caller cannot choose which rules run or how strictly - applicability is
    answered by `engine.applicable_rules` from the loaded rule set and the
    commodity's category, and nothing in a request reaches that decision.

    That is not defensive coding for its own sake. A compliance verdict a
    client could steer by picking its own rules would be worth nothing.
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


class ComplianceCheckSerializer(serializers.ModelSerializer):
    """The full result: verdict, explanation, findings, and what was read.

    `result` is the verdict the UI shows. `result_display` is its human label,
    taken from the model's own choices rather than restated here, so the two
    cannot drift.

    `summary` is not decoration. It is the engine's plain-language explanation
    of *why* this verdict was reached - including "no rules are loaded, so
    nothing was checked" - and a UI that shows the verdict without it can imply
    a determination the system did not make.
    """

    result_display = serializers.CharField(
        source="get_result_display", read_only=True
    )
    violations = ViolationSerializer(many=True, read_only=True)
    findings = ComplianceFindingSerializer(many=True, read_only=True)
    extraction = ExtractionRunSerializer(source="extraction_run", read_only=True)
    image = ProductImageSerializer(source="extraction_run.image", read_only=True)
    product_category_code = serializers.SerializerMethodField()

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
            "processing_ms",
            "completed_at",
            "product_category_code",
            "violations",
            "findings",
            "extraction",
            "image",
        ]
        read_only_fields = fields

    def get_product_category_code(self, check: ComplianceCheck) -> str | None:
        """The category whose rules were considered, or null if none was known.

        See `_product_category_code`, which the list serializer shares.
        """
        return _product_category_code(check)


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
