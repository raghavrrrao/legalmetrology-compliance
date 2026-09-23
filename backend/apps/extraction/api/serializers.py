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

3. **A classification is an observation, and is labelled as one.** The
   pipeline's product classifier records what kind of product the label text
   reads like into `raw_output["metadata"]["product_classification"]`, and
   `get_product_classification` surfaces it unchanged - category, confidence
   and evidence, or `null` when the configured pipeline has no classifier.
   Its confidence is the classifier's confidence in the *category*. It is not
   a compliance figure, it decides nothing, and nothing in `apps.compliance`
   reads it.

Bodies are `snake_case` per `docs/api.md`; the frontend maps to camelCase in
one place at its own boundary.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.extraction.models import (
    ExtractedLabelField,
    ExtractionRun,
    ExtractionRunImage,
)
from apps.images.api.serializers import ProductImageSerializer


class ExtractedFieldSerializer(serializers.ModelSerializer):
    """One declaration read off the label, with the evidence for it.

    `raw_value` is what the OCR engine saw; `normalized_value` is what
    `labelextract.fields.normalisation` made of it, and carries the extractor's
    own `uncertain` flag when it was not sure. Both are exposed because a
    reviewer checking a finding needs the reading, not only its interpretation.

    `image_id` says which photograph of the package this was read from, and is
    what lets an interface put a declaration and a piece of evidence against
    the right panel. It matches one of the `images[].image.id` values in the
    same response.

    **`null` means the source was not recorded, never that no photograph was
    involved.** Every reading made before a run could hold more than one
    photograph has a null here, and so does one whose image row has since been
    deleted. A client must not render null as "no image": the honest rendering
    is to say nothing about which image, and the run's own image set is still
    the set the reading came from.

    An inspection may report the **same `field_key` more than once** - a
    declaration printed on two panels, photographed twice. Each row is a real
    reading with its own image and its own confidence, and none of them is the
    "wrong" one. Which reading the rule engine judged against is a separate
    question, answered on the finding, which links to the exact reading it
    used.
    """

    image_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="The photograph this declaration was read from, or null.",
    )

    class Meta:
        model = ExtractedLabelField
        fields = [
            "field_key",
            "raw_value",
            "normalized_value",
            "confidence",
            "bounding_box",
            "image_id",
        ]
        read_only_fields = fields


class RunImageSerializer(serializers.ModelSerializer):
    """One photograph of the inspection, and how reading that one went.

    `position` is 1-based and is the number an interface shows: "Evidence ·
    Image 2" means the entry whose `position` is 2. It is the order the
    submitter sent the photographs in, not a ranking.

    `status`, `error_code` and `error_message` are about **this photograph
    alone**. They are not the run's - and the distinction is the point of the
    row. A run whose `status` is `completed` may still hold a photograph that
    was too blurred to read: the package was read well enough to judge against,
    *and* one of the submitter's photographs contributed nothing. Reporting
    only the run's status would hide the second; reporting only the
    photographs' would make an inspection look failed because one close-up was
    out of focus.
    """

    image = ProductImageSerializer(read_only=True)

    class Meta:
        model = ExtractionRunImage
        fields = [
            "position",
            "status",
            "error_code",
            "error_message",
            "processing_ms",
            "image",
        ]
        read_only_fields = fields


def run_image_entries(run: ExtractionRun) -> list[dict]:
    """Every photograph a run read, in the order it was submitted.

    Always at least one entry, and `entries[0]["image"]` is the run's primary
    photograph. A client counting photographs counts this list; a client
    resolving a reading's `image_id` or a piece of evidence's `image_id` looks
    it up here.

    A module-level function rather than a method, because the extraction
    response and the compliance result both publish this list and neither may
    disagree with the other about how many photographs an inspection had. The
    alternative - the compliance serializer rendering a whole
    `ExtractionRunSerializer` to pull one key out of it - would serialise every
    declaration of the run a second time for nothing.

    Falls back to describing the primary photograph alone when a run has no
    membership rows. That is not a hypothetical: a run built directly in a test
    or a fixture has none, and a response must still describe the photograph it
    read rather than claim it read none. Runs that existed before the set was
    modelled were backfilled by migration, so they have real rows.
    """
    links = list(run.run_images.all())
    if links:
        return RunImageSerializer(links, many=True).data
    return [
        {
            "position": 1,
            # The run's own status, because for a single photograph the two
            # statements are the same statement. Not a guess: this branch is
            # only reached when the run read exactly one image.
            "status": (
                run.status
                if run.status
                in {
                    ExtractionRun.Status.COMPLETED,
                    ExtractionRun.Status.EMPTY,
                    ExtractionRun.Status.FAILED,
                }
                else ExtractionRunImage.Status.FAILED
            ),
            "error_code": run.error_code or "",
            "error_message": run.error_message or "",
            "processing_ms": run.processing_ms,
            "image": ProductImageSerializer(run.image).data,
        }
    ]


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
    images = serializers.SerializerMethodField()
    unread_declarations = serializers.SerializerMethodField()
    product_classification = serializers.SerializerMethodField()
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
            "images",
            "unread_declarations",
            "product_classification",
        ]
        read_only_fields = fields

    def get_images(self, run: ExtractionRun) -> list[dict]:
        return run_image_entries(run)

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

    def get_product_classification(self, run: ExtractionRun) -> dict | None:
        """Read the classifier's observation out of the run's raw output.

        Passed through in the shape `labelextract.contracts.ProductClassification.as_dict`
        already defines - `category`, `subcategory`, `confidence`,
        `subcategory_confidence`, `evidence`, `category_scores`,
        `subcategory_scores`, `classifier_name`, `classifier_version` - for
        the same reason `unread_declarations` is: the vocabulary belongs to
        the ml/ package and a second statement of it here would drift.

        `null` is the ordinary case for every run made before the classifier
        existed, for every run of a pipeline without one (`tesseract` 0.3.0
        and earlier, `null-engine`), and for a run whose classifier failed.
        A client must treat `null` as "no classification was made", never
        as a category. `category: "unknown"` is different: the classifier
        ran and declined to choose.

        Nothing here is consulted by the compliance engine. Which rules apply
        is still answered from `Product.category` and the stated
        applicability declarations; this field is what a client may show a
        person as a *suggestion* for that category.
        """
        raw_output = run.raw_output or {}
        metadata = raw_output.get("metadata") or {}
        classification = metadata.get("product_classification")
        if not isinstance(classification, dict):
            return None
        if not isinstance(classification.get("category"), str):
            return None
        return classification


class ExtractionResponseSerializer(ExtractionRunSerializer):
    """The body of `POST /api/v1/extraction/`: a run, plus the image it read.

    The image is embedded rather than linked because the client has just
    uploaded it and has no other way to learn what was stored - the measured
    format and dimensions, and the id it will need to refer to the photograph
    again.

    `image` is the **primary** photograph, position 1 of the set. `images`, on
    the run above, is all of them. Both are present and neither is redundant:
    `image` is what this endpoint has always returned and what
    `ExtractionRun.image` points at, and a client written before inspections
    could carry several photographs keeps working unchanged against a
    single-image upload.

    There is deliberately no `compliance` key, and there never should be. A
    caller that wants a verdict calls `POST /api/v1/images/`, which runs the
    rule engine; mixing the two here would let a reading start to look like a
    determination.
    """

    image = ProductImageSerializer(read_only=True)

    class Meta(ExtractionRunSerializer.Meta):
        fields = ExtractionRunSerializer.Meta.fields + ["image"]
        read_only_fields = fields
