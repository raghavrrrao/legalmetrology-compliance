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

One inspection, several photographs
-----------------------------------
A packaged commodity declares different things on different panels, so an
upload may carry more than one photograph of the same package. They are sent
by **repeating the `image` part** - the ordinary multipart way to send several
values under one name - and `view_type` is repeated alongside it, positionally.

That is why both are `ListField`s below and why neither field was renamed. A
request with exactly one `image` part is byte-for-byte the request this API
has always accepted, and it produces exactly the same inspection; a client that
never learned about sets needs no change. A second field name (`images`) would
have made the single-image form the special case and left two spellings of the
same idea in the contract.

The order of the parts is the order of the photographs, and it is kept: it
becomes `ExtractionRunImage.position`, which is the "Image 2" a person is shown
beside a piece of evidence. `validated_data` carries `images` (the whole set)
and `image` (the first), so code written against the single-image shape reads
the primary photograph and still means what it said.

`ProductImageSerializer` is the response half - the stored facts about a
photograph, as measured from its bytes. It lives here, with the model it
describes, so that the extraction and compliance responses can both embed it
without either app importing the other.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.catalog.models import ProductCategory
from apps.images.constants import MAX_IMAGES_PER_INSPECTION
from apps.images.models import ProductImage


class ImageUploadSerializer(serializers.Serializer):
    """The photographs of one package, and what each one shows.

    The multipart body of `POST /api/v1/extraction/`, and the base of the
    analysis body below.

    Both fields are repeatable and both are read positionally. DRF's
    `ListField` already collects every value of a repeated key out of a
    multipart body, so this needs no parsing of its own - which is the point,
    because a hand-rolled multipart reader here would be a second place for the
    request shape to be decided.
    """

    image = serializers.ListField(
        # The wire name stays `image`, singular and repeated. `source` moves
        # the validated value to `images`, leaving `image` free to be set in
        # `validate()` to the primary photograph - so a caller reading
        # `validated["image"]` gets a file, exactly as it always has.
        source="images",
        child=serializers.FileField(),
        allow_empty=False,
        min_length=1,
        max_length=MAX_IMAGES_PER_INSPECTION,
        help_text=(
            "A photograph of the package label. Repeat the part to send "
            "several photographs of the same package - front, back, a side "
            "panel, a close-up - as one inspection. At most "
            f"{MAX_IMAGES_PER_INSPECTION}. The order is kept and is the "
            "position each photograph is shown at."
        ),
    )
    view_type = serializers.ListField(
        source="view_types",
        child=serializers.ChoiceField(choices=ProductImage.ViewType.choices),
        required=False,
        default=list,
        max_length=MAX_IMAGES_PER_INSPECTION,
        help_text=(
            "Which panel of the package each photograph shows, in the same "
            "order as the `image` parts. Which declarations one can expect to "
            "find depends on it. Fewer values than photographs leaves the rest "
            "`unspecified`; the value is never copied across, because saying "
            "the first photograph is the front says nothing about the second."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        """Expose the primary photograph under the name it has always had.

        `image` is `images[0]`: the first part sent, position 1 of the set, and
        what `ExtractionRun.image` will point at. It is set here rather than
        left to each caller so that "the primary photograph" is decided once.
        """
        images = attrs.get("images") or []
        attrs["image"] = images[0] if images else None
        attrs.setdefault("view_types", [])
        attrs["view_type"] = (
            attrs["view_types"][0]
            if attrs["view_types"]
            else ProductImage.ViewType.UNSPECIFIED
        )
        return attrs


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
