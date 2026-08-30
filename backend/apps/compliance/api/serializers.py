"""Response shapes for a compliance result.

These serializers are read-only. They shape rows the services already wrote;
none of them creates, updates or decides anything. Bodies are `snake_case` per
`docs/api.md`; the frontend maps to camelCase in one place at its own boundary.

Two things this file is careful about, both of which are the difference between
an honest result and a misleading one:

1. **Nothing is fabricated to make a response look complete.** A value that was
   not measured is `null`, never a plausible-looking default. `confidence`,
   `bounding_box` and `processing_ms` are all genuinely absent sometimes.

2. **"Not found" and "could not be read" stay distinguishable.** The pipeline
   records declarations it saw named on the label but could not read into
   `ExtractionRun.raw_output["metadata"]["unread_declarations"]`.
   `UnreadDeclarationSerializer` surfaces that channel to the UI so a reviewer
   can tell a possible contravention from a request for a better photograph.
   Nothing here interprets it - reading it is all this does.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.compliance.models import (
    ComplianceCheck,
    ComplianceEvidence,
    ComplianceViolation,
)
from apps.extraction.models import ExtractedLabelField, ExtractionRun
from apps.images.models import ProductImage


class ExtractedFieldSerializer(serializers.ModelSerializer):
    """One declaration read off the label, with the evidence for it.

    `raw_value` is what the OCR engine saw; `normalized_value` is what
    `labelextract.fields.normalisation` made of it, and carries the extractor's
    own `uncertain` flag when it was not sure. Both are exposed because a
    reviewer checking a finding needs the reading, not only its interpretation.
    """

    class Meta:
        model = ExtractedLabelField
        fields = [
            "field_key",
            "raw_value",
            "normalized_value",
            "confidence",
            "bounding_box",
        ]
        read_only_fields = fields


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


class ExtractionRunSerializer(serializers.ModelSerializer):
    """The reading this check was evaluated against.

    `is_placeholder` is exposed for the same reason the health endpoint exposes
    it: while it is true, no text was read at all, and a UI that does not say
    so is presenting wiring output as a reading.
    """

    fields_read = ExtractedFieldSerializer(
        source="fields", many=True, read_only=True
    )
    unread_declarations = serializers.SerializerMethodField()
    produced_usable_output = serializers.BooleanField(read_only=True)

    class Meta:
        model = ExtractionRun
        fields = [
            "id",
            "engine_name",
            "engine_version",
            "is_placeholder",
            "status",
            "produced_usable_output",
            "processing_ms",
            "recognised_text",
            "error_code",
            "error_message",
            "fields_read",
            "unread_declarations",
        ]
        read_only_fields = fields

    def get_unread_declarations(self, run: ExtractionRun) -> list[dict]:
        """Read the unread-declaration channel out of the run's raw output.

        Passed through in the shape `labelextract.contracts.UnreadDeclaration`
        already defines - `key`, `evidence_text`, `box`, `confidence` - rather
        than restated as a serializer here. The vocabulary belongs to the ml/
        package, and a second declaration of it in the API layer would be a
        second thing to keep in step with the first.

        Defensive throughout because `raw_output` is a JSON column holding
        engine-shaped data: an older run, a different engine or a failed run may
        legitimately have no metadata at all. An empty list means "the engine
        reported none", which on the current extractor is the usual case - see
        docs/evaluation-results.md, where this channel did not fire once on real
        photographs. It does not mean every declaration was read.
        """
        raw_output = run.raw_output or {}
        metadata = raw_output.get("metadata") or {}
        declarations = metadata.get("unread_declarations") or []
        if not isinstance(declarations, list):
            return []
        return [item for item in declarations if isinstance(item, dict)]


class ProductImageSerializer(serializers.ModelSerializer):
    """The photograph a result is about."""

    class Meta:
        model = ProductImage
        fields = [
            "id",
            "original_filename",
            "image_format",
            "width",
            "height",
            "size_bytes",
            "view_type",
            "status",
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
