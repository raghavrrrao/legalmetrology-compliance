"""Request and response shapes for an uploaded photograph.

Two request serializers, in a deliberate inheritance rather than side by side:

- `ImageUploadSerializer` is everything an upload needs on its own - the file,
  and which panel of the package it shows. `POST /api/v1/extraction/` uses
  exactly this, because reading a label needs nothing else.
- `ImageAnalysisRequestSerializer` adds `category_code`, which selects *which
  rules apply*. That is a compliance question, so it is an addition made by the
  endpoint that asks one, not a field every upload has to carry.

Neither of them validates *the image itself*. That is `apps.images.validators`,
reached through the ingestion service, and `docs/api.md` is explicit that a
view must never write a `ProductImage` outside that path: the validator is the
only thing standing between an unvalidated file and storage, and a second,
weaker copy of its checks here would be a way around it.

So there is no `ImageField` below. A DRF `ImageField` would run Pillow's own
lightweight check and, by passing, imply the file had been vetted - when the
real checks (size before decode, decompression bombs, format allowlist,
checksum) happen later. `FileField` keeps this layer honest about doing only
transport-level validation.

`ProductImageSerializer` is the response half - the stored facts about a
photograph, as measured from its bytes. It lives here, with the model it
describes, so that the extraction and compliance responses can both embed it
without either app importing the other.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.catalog.models import ProductCategory
from apps.images.models import ProductImage


class ImageUploadSerializer(serializers.Serializer):
    """A photograph, and what it is a photograph of.

    The multipart body of `POST /api/v1/extraction/`, and the base of the
    analysis body below.
    """

    image = serializers.FileField(
        help_text="The photograph of the package label.",
    )
    view_type = serializers.ChoiceField(
        choices=ProductImage.ViewType.choices,
        required=False,
        default=ProductImage.ViewType.UNSPECIFIED,
        help_text=(
            "Which panel of the package this photograph shows. Which "
            "declarations one can expect to find depends on it."
        ),
    )


class ImageAnalysisRequestSerializer(ImageUploadSerializer):
    """The multipart body of `POST /api/v1/images/`."""

    category_code = serializers.SlugField(
        required=False,
        allow_blank=True,
        help_text=(
            "ProductCategory.code for the commodity, when it is known. "
            "Determines which rules apply. Omitting it is honest and "
            "supported: the result then says the category was unknown rather "
            "than assuming one."
        ),
    )

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


class ProductImageSerializer(serializers.ModelSerializer):
    """The photograph a reading or a result is about.

    Every field here was measured from the bytes during validation, not taken
    from what the upload claimed about itself. `original_filename` is the
    sanitised client name, kept for display only - it never reached a path.
    """

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
