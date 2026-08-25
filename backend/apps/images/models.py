"""Uploaded product images.

An image is the evidence base for everything downstream: extraction reads it,
compliance results cite it, and a user disputing a finding needs to see the
exact file that produced it. So images are immutable once stored - re-analysing
means a new `ExtractionRun` against the same image, never editing the image row.
"""

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel, UUIDPrimaryKeyModel
from apps.images.storage import product_image_upload_path


class ProductImage(UUIDPrimaryKeyModel, TimeStampedModel):
    """One uploaded photograph of a packaged commodity.

    `product` is nullable because the real workflow is upload-then-identify:
    a user photographs a package and the system works out what it is. Requiring
    a product up front would force the UI to ask questions the user is using
    this system to answer.
    """

    class ViewType(models.TextChoices):
        """Which panel of the package this photograph shows.

        Which declarations one can expect to find depends on the panel: an
        absent net quantity on a photo of the *front* panel is not evidence
        that the package lacks one. The compliance engine needs this to avoid
        reporting a framing choice as a violation.
        """

        UNSPECIFIED = "unspecified", "Unspecified"
        FRONT = "front", "Front panel"
        BACK = "back", "Back panel"
        PRINCIPAL_DISPLAY = "principal_display", "Principal display panel"
        LABEL = "label", "Label close-up"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        """Where this image is in the processing lifecycle."""

        UPLOADED = "uploaded", "Uploaded"
        PROCESSING = "processing", "Processing"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    product = models.ForeignKey(
        "catalog.Product",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="images",
        help_text="Null until the product is identified. CASCADE: deleting a "
                  "product removes its images and their analyses.",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_images",
    )

    image = models.FileField(
        upload_to=product_image_upload_path,
        max_length=255,
        help_text="Stored under a generated name; see apps.images.storage.",
    )

    # --- facts measured during validation, not claims from the upload ---
    # Stored rather than recomputed: the file may later be moved to object
    # storage where opening it to answer "how big was it?" is a network call.
    original_filename = models.CharField(
        max_length=255,
        help_text="Sanitised client-supplied name, for display only. Never "
                  "used to build a filesystem path.",
    )
    content_type = models.CharField(max_length=64)
    image_format = models.CharField(
        max_length=16,
        help_text="Canonical format as decoded (jpeg/png/webp), not as claimed.",
    )
    size_bytes = models.PositiveBigIntegerField()
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    checksum_sha256 = models.CharField(
        max_length=64,
        db_index=True,
        help_text="SHA-256 of the uploaded bytes. Ties a compliance result to "
                  "the exact file analysed, and makes tampering detectable.",
    )

    view_type = models.CharField(
        max_length=32,
        choices=ViewType.choices,
        default=ViewType.UNSPECIFIED,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.UPLOADED,
        db_index=True,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product", "view_type"], name="image_product_view_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.original_filename} ({self.image_format}, {self.pk})"

    @property
    def pixel_count(self) -> int:
        return self.width * self.height
