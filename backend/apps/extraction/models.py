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
        ]

    def __str__(self) -> str:
        return f"{self.field_key}={self.raw_value[:40]!r}"
