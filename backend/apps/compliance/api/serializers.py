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

from apps.compliance.models import (
    ComplianceCheck,
    ComplianceEvidence,
    ComplianceViolation,
)
from apps.extraction.api.serializers import (
    ExtractedFieldSerializer,
    ExtractionRunSerializer,
)
from apps.images.api.serializers import ProductImageSerializer

__all__ = [
    "ComplianceCheckSerializer",
    "EvidenceSerializer",
    "ExtractedFieldSerializer",
    "ExtractionRunSerializer",
    "ProductImageSerializer",
    "ViolationSerializer",
]


class EvidenceSerializer(serializers.ModelSerializer):
    """What was read from the image that supports a finding.

    Attached even to a finding of absence: the text we *did* read is the
    justification for concluding a declaration was not there.
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
            "extraction",
            "image",
        ]
        read_only_fields = fields

    def get_product_category_code(self, check: ComplianceCheck) -> str | None:
        """The category whose rules were considered, or null if none was known.

        Null is load-bearing: it is the difference between "we checked the
        rules for packaged food and found nothing wrong" and "we did not know
        what this commodity is, so we could not know which rules apply". The
        engine reports the second as REVIEW_REQUIRED and the UI needs to be
        able to say why.
        """
        product = check.product
        if product is None or product.category_id is None:
            return None
        return product.category.code
