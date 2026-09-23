"""Records of OCR/ML runs and the label declarations they read.

Schema decisions worth understanding before extending this
----------------------------------------------------------
**One run per attempt, many runs per image.** `ExtractionRun` is a foreign key
to `ProductImage`, not a one-to-one. Re-running a better OCR engine over an old
image must produce a *new* run, leaving the old one intact - otherwise the
compliance results that cited it now reference readings that no longer exist.

**The engine is recorded on the run, not baked into the schema.** Every run
stores `engine_name` and `engine_version` as plain text. Nothing here is
coupled to a particular OCR implementation, so swapping engines needs no
migration and old runs stay interpretable.

**Declarations are rows, not a JSON blob.** `ExtractedLabelField` is relational
because the compliance engine queries it by field key, and evidence links point
at individual readings. The one place JSON is used is `ExtractionRun.raw_output`
- genuinely unstructured, engine-specific diagnostic output whose shape we
cannot know in advance, kept so field extraction can be re-run without
re-running OCR.

**One run may read several photographs of the same package.** A packaged
commodity declares different things on different panels, so an inspection is a
set of images, not one. That set is modelled as `ExtractionRunImage` rows
hanging off the run rather than as several runs, because the alternative -
one run per photograph - would mean one `ComplianceCheck` per photograph, and
a package whose net quantity is on the back would be reported as failing the
check made against its front. The rule engine judges the *package*, so it has
to see every declaration at once.

`ExtractionRun.image` is kept, and is the image at position 1. It is the
primary photograph, not the only one: every query, index and serializer
written before the set existed still means what it meant, and a single-image
inspection is exactly a set of one. `ExtractedLabelField.image` records which
photograph each declaration was actually read from, which is what lets a
finding cite "image 2" rather than "the package".
"""

from django.db import models

from apps.core.models import TimeStampedModel, UUIDPrimaryKeyModel


class ExtractionRun(UUIDPrimaryKeyModel, TimeStampedModel):
    """One attempt to read the label off one image."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        #: Ran and recognised text. Zero fields is a valid completed outcome.
        COMPLETED = "completed", "Completed"
        #: Ran but recognised nothing usable - unreadable or blank photograph.
        #: Distinct from COMPLETED-with-no-fields, and from FAILED.
        EMPTY = "empty", "Empty"
        #: Could not run. See error_code.
        FAILED = "failed", "Failed"

    image = models.ForeignKey(
        "images.ProductImage",
        on_delete=models.CASCADE,
        related_name="extraction_runs",
        help_text=(
            "The primary photograph - position 1 of this run's image set. Not "
            "the only one: see ExtractionRunImage. Kept as a direct foreign "
            "key so that every query, index and serializer written before a "
            "run could read more than one photograph still resolves."
        ),
    )

    engine_name = models.CharField(
        max_length=64,
        help_text="Pipeline name as resolved from the labelextract registry.",
    )
    engine_version = models.CharField(max_length=32)
    is_placeholder = models.BooleanField(
        default=False,
        help_text=(
            "True when this run came from a placeholder engine that performs "
            "no real recognition. Surfaced through the API so the UI can never "
            "present wiring output as a genuine reading."
        ),
    )

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    processing_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Wall-clock time inside the extraction pipeline.",
    )

    error_code = models.CharField(
        max_length=64,
        blank=True,
        help_text="Stable code from labelextract.exceptions when status is "
                  "failed. The frontend branches on this, not on the message.",
    )
    error_message = models.TextField(blank=True)

    raw_output = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Verbatim engine diagnostics. Shape is engine-specific and is "
            "deliberately not modelled. Kept so field extraction can be re-run "
            "without re-running OCR."
        ),
    )
    recognised_text = models.TextField(
        blank=True,
        help_text="All recognised text, joined. Stored for display and search; "
                  "the authoritative per-block data lives in raw_output.",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["image", "-created_at"], name="run_image_recent_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.engine_name}@{self.engine_version} on {self.image_id} ({self.status})"

    @property
    def produced_usable_output(self) -> bool:
        """True when this run read the label well enough to judge against.

        The compliance engine uses this to decide whether an absent declaration
        is evidence of a missing declaration, or merely evidence of a bad
        photograph. Getting this backwards would report unreadable photos as
        legal violations.
        """
        return self.status == self.Status.COMPLETED


class ExtractionRunImage(TimeStampedModel):
    """One photograph in one run's image set, and how reading it went.

    The membership row for a multi-image inspection. It exists rather than a
    plain `ManyToManyField` because two things about the membership are worth
    recording and a bare join table has nowhere to put them:

    **`position`** is the number a person sees. The interface labels evidence
    "Image 2", and that number has to mean the same thing on every screen and
    after every reload, so it is stored rather than derived from an ordering
    that a new index could quietly change. It is 1-based because it is read by
    people, and position 1 is always `ExtractionRun.image`.

    **The per-image outcome.** One photograph of a set can be unreadable while
    the others are fine. The run's own `status` answers "was this label read
    well enough to judge against", which is a question about the set; these
    columns answer "what happened to this photograph", which is what tells a
    submitter that image 3 was too blurred to use and the other two were read.
    Collapsing the two would either fail an inspection over one bad photograph
    or hide the bad photograph entirely.

    Uses the default integer primary key: these rows are always reached through
    their run and never addressed in a URL.
    """

    class Status(models.TextChoices):
        """What the pipeline made of this one photograph.

        A subset of `ExtractionRun.Status` - there is no PENDING or RUNNING,
        because a row is written only once the image has been through the
        pipeline or the pipeline has refused it.
        """

        #: Read, and text was recognised.
        COMPLETED = "completed", "Completed"
        #: Ran and recognised nothing usable.
        EMPTY = "empty", "Empty"
        #: Could not be read at all. See `error_code`.
        FAILED = "failed", "Failed"

    run = models.ForeignKey(
        ExtractionRun,
        on_delete=models.CASCADE,
        related_name="run_images",
    )
    image = models.ForeignKey(
        "images.ProductImage",
        on_delete=models.CASCADE,
        related_name="run_memberships",
    )

    position = models.PositiveSmallIntegerField(
        help_text=(
            "1-based place of this photograph in the set, as the submitter "
            "supplied it. Position 1 is the run's primary image. Stored, not "
            "derived: it is the number the interface shows beside a piece of "
            "evidence."
        ),
    )

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.COMPLETED,
        help_text="What the pipeline made of this photograph on its own.",
    )
    error_code = models.CharField(
        max_length=64,
        blank=True,
        help_text=(
            "Stable code from labelextract.exceptions when this photograph "
            "failed, even though others in the set may have been read."
        ),
    )
    error_message = models.TextField(blank=True)
    processing_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Wall-clock time the pipeline spent on this photograph.",
    )

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "position"], name="run_image_position_unique"
            ),
            models.UniqueConstraint(
                fields=["run", "image"], name="run_image_member_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"Image {self.position} of {self.run_id} ({self.status})"


class ExtractedLabelField(TimeStampedModel):
    """One declaration read off the label during a run.

    This is an observation - "we read this string, here, with this confidence"
    - not an assertion that the value is correct or that it was required.

    Uses the default integer primary key: these rows are always reached through
    their run and never addressed directly in a URL.
    """

    run = models.ForeignKey(
        ExtractionRun,
        on_delete=models.CASCADE,
        related_name="fields",
    )
    image = models.ForeignKey(
        "images.ProductImage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="extracted_fields",
        help_text=(
            "The photograph this declaration was read from. The link that "
            "lets a finding say which image supplied its evidence, rather "
            "than only that the package showed it somewhere.\n\n"
            "Null means the source was not recorded - every reading made "
            "before a run could hold more than one photograph, and any "
            "reading whose image row has since been deleted. Null is never a "
            "claim that no image was involved, and a client must not present "
            "it as one.\n\n"
            "SET_NULL rather than CASCADE: deleting an image must not delete "
            "the reading that was made from it, because findings snapshot "
            "that reading and would lose their evidence with it."
        ),
    )
    field_key = models.CharField(
        max_length=64,
        db_index=True,
        help_text=(
            "A labelextract.contracts.LabelFieldKey value. Choices are not "
            "enumerated at the database level on purpose: the vocabulary is "
            "owned by the ml/ package, and duplicating it here would create "
            "two lists to keep in sync. Validated in the service layer."
        ),
    )
    raw_value = models.TextField(
        help_text="Text exactly as recognised. Never cleaned in place, so the "
                  "original reading stays auditable."
    )
    normalized_value = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "Structured interpretation, e.g. {'quantity': 500, 'unit': 'g'}. "
            "Null when no normaliser exists for this key yet. JSON because the "
            "shape differs per field type."
        ),
    )
    confidence = models.FloatField(
        null=True,
        blank=True,
        help_text=(
            "Engine confidence in [0, 1], or NULL when the engine does not "
            "report one. NULL means 'unknown' and must never be treated as "
            "zero or as certainty."
        ),
    )
    bounding_box = models.JSONField(
        null=True,
        blank=True,
        help_text="{'x','y','width','height'} in source-image pixels, or null. "
                  "Lets the UI show where on the package this was read.",
    )

    class Meta:
        ordering = ["field_key"]
        indexes = [
            models.Index(fields=["run", "field_key"], name="field_run_key_idx"),
            # `CheckContext.from_run` reads every field of a run and resolves
            # duplicate keys by the position of the image each came from.
            models.Index(fields=["run", "image"], name="field_run_image_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.field_key}={self.raw_value[:40]!r}"
