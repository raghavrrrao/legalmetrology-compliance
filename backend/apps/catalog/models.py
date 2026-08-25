"""Products and commodity categories.

This app owns *product identity* only: what the item is and which commodity
category it belongs to. It deliberately does NOT store label declarations
(manufacturer name, net quantity, MRP...). Those are readings taken from a
specific photograph at a specific time, and they live in `apps.extraction`
attached to the run that produced them.

Keeping the two apart is what makes the audit trail work. A product's
"manufacturer" is not a fact we know; it is a string some OCR run read off some
image, with a confidence and a bounding box. Copying it onto `Product` would
turn evidence into an unsourced assertion, and would leave two copies to
disagree once a second photo is analysed.
"""

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel, UUIDPrimaryKeyModel


class ProductCategory(TimeStampedModel):
    """A commodity category, used to decide which rules apply to a product.

    This is the hinge of the whole applicability question: `ComplianceRule`
    rows target categories, so how this tree is shaped determines what can be
    expressed about which commodities.

    Uses a small integer primary key and a stable text `code`. Rule definition
    files in `rules/` reference categories by `code`, so the code is part of a
    reviewed data contract - renaming one invalidates rule files, and the
    loader will reject them rather than silently skip.
    """

    code = models.SlugField(
        max_length=64,
        unique=True,
        help_text=(
            "Stable identifier referenced by rule definition files, "
            "e.g. 'packaged-food'. Do not rename after rules reference it."
        ),
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        help_text=(
            "Optional parent category. PROTECT rather than CASCADE: deleting a "
            "parent must not silently remove the sub-categories that rules and "
            "products point at."
        ),
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "product categories"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    def ancestry_codes(self) -> list[str]:
        """Return this category's code plus every ancestor's, nearest first.

        Rule applicability is inherited: a rule attached to `packaged-food`
        applies to `packaged-food-biscuits` as well. The engine calls this to
        collect the codes a product's category matches.

        Walks with a visited-set guard so a cyclic `parent` chain - which the
        database does not prevent - raises no infinite loop.
        """
        codes: list[str] = []
        seen: set[int] = set()
        node: ProductCategory | None = self
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            codes.append(node.code)
            node = node.parent
        return codes


class Product(UUIDPrimaryKeyModel, TimeStampedModel):
    """A packaged commodity being checked for compliance.

    A UUID primary key because product IDs appear in URLs and API responses.
    Sequential integers would let one user enumerate another user's submissions
    by guessing neighbouring IDs, and would leak how many products the system
    holds.

    Every descriptive field is optional. A product is frequently created from a
    photograph before anyone knows what it is - identification is an outcome of
    analysis, not a precondition for it.
    """

    name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Working name for this submission. Not a label declaration.",
    )
    brand = models.CharField(max_length=255, blank=True)
    category = models.ForeignKey(
        ProductCategory,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="products",
        help_text=(
            "Determines which rules apply. Null means the category is not yet "
            "known, which the compliance engine treats as 'cannot determine "
            "applicability' rather than 'no rules apply'."
        ),
    )
    barcode = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="EAN/UPC if known. Not unique: the same article may be "
                  "submitted more than once, and barcodes are re-used.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
        help_text="Null once the creating user is deleted; the product and its "
                  "compliance history are retained.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="product_created_idx"),
        ]

    def __str__(self) -> str:
        return self.name or f"Product {self.pk}"

    @property
    def applicable_category_codes(self) -> list[str]:
        """Category codes this product matches, for rule applicability.

        Empty when no category is set. The engine must distinguish that from
        "matched no rules" - see apps.compliance.services.engine.
        """
        return self.category.ancestry_codes() if self.category_id else []
