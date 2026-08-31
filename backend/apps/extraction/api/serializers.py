"""Response shapes for one reading of one photograph.

These serializers describe an **observation**, never a judgement. An
`ExtractionRun` says "this is the text we read off this image, here, with this
confidence"; whether a declaration was legally required, and whether its
absence is a contravention, is answered only by `apps.compliance` against a
verified rule. Nothing in this file has an opinion about either, and no field
below is named for a legal outcome.

They live in this app rather than in `apps.compliance.api` - where they were
first written - so that the extraction endpoint does not have to import the
compliance app to describe its own output. Compliance imports them instead,
which is the direction the layering already runs everywhere else.

Two properties this file is careful about, both of which are the difference
between an honest reading and a misleading one:

1. **Nothing is fabricated to make a response look complete.** A value that was
   not measured is `null`, never a plausible-looking default. `confidence`,
   `bounding_box` and `processing_ms` are all genuinely absent sometimes, and a
   `null` confidence means "this engine does not report one" - never zero.

2. **"Not found" and "could not be read" stay distinguishable.** The pipeline
   records declarations it saw named on the label but could not read into
   `ExtractionRun.raw_output["metadata"]["unread_declarations"]`, and
   `get_unread_declarations` surfaces that channel unchanged. One asks for a
   better photograph; the other is a possible contravention. Collapsing them
   would turn the first into the second.

Bodies are `snake_case` per `docs/api.md`; the frontend maps to camelCase in
one place at its own boundary.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.extraction.models import ExtractedLabelField, ExtractionRun
from apps.images.api.serializers import ProductImageSerializer


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


class ExtractionRunSerializer(serializers.ModelSerializer):
    """One run of the pipeline over one image, and what it read.

    `is_placeholder` is exposed for the same reason the health endpoint exposes
    it: while it is true, no text was read at all, and a UI that does not say
    so is presenting wiring output as a reading.

    `status` and `produced_usable_output` are both present and are not the same
    question. `status` says what happened (`completed` / `empty` / `failed`);
    `produced_usable_output` says whether the label was read well enough to be
    judged against at all. A client must branch on the second before treating
    an absent declaration as absent from the *package* rather than from the
    *photograph*.
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


class ExtractionResponseSerializer(ExtractionRunSerializer):
    """The body of `POST /api/v1/extraction/`: a run, plus the image it read.

    The image is embedded rather than linked because the client has just
    uploaded it and has no other way to learn what was stored - the measured
    format and dimensions, and the id it will need to refer to the photograph
    again.

    There is deliberately no `compliance` key, and there never should be. A
    caller that wants a verdict calls `POST /api/v1/images/`, which runs the
    rule engine; mixing the two here would let a reading start to look like a
    determination.
    """

    image = ProductImageSerializer(read_only=True)

    class Meta(ExtractionRunSerializer.Meta):
        fields = ExtractionRunSerializer.Meta.fields + ["image"]
        read_only_fields = fields
