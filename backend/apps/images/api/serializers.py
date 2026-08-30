"""Request shape for an image upload.

This serializer validates *the request* - that a file was sent, that the stated
view type and category exist. It deliberately does **not** validate the image
itself. That is `apps.images.validators`, reached through the ingestion
service, and `docs/api.md` is explicit that a view must never write a
`ProductImage` outside that path: the validator is the only thing standing
between an unvalidated file and storage, and a second, weaker copy of its
checks here would be a way around it.

So there is no `ImageField` below. A DRF `ImageField` would run Pillow's own
lightweight check and, by passing, imply the file had been vetted - when the
real checks (size before decode, decompression bombs, format allowlist,
checksum) happen later. `FileField` keeps this layer honest about doing only
transport-level validation.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.catalog.models import ProductCategory
from apps.images.models import ProductImage


class ImageUploadSerializer(serializers.Serializer):
    """The multipart body of `POST /api/v1/images/`."""

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
