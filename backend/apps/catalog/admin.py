from django.contrib import admin

from apps.catalog.models import (
    Product,
    ProductApplicabilityDeclaration,
    ProductCategory,
)


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "parent", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


class ProductApplicabilityDeclarationInline(admin.TabularInline):
    model = ProductApplicabilityDeclaration
    extra = 0
    autocomplete_fields = ("condition",)
    fields = ("condition", "answer", "source", "note")
    verbose_name = "applicability declaration"
    verbose_name_plural = "applicability declarations"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("__str__", "brand", "category", "created_at")
    list_filter = ("category",)
    search_fields = ("name", "brand", "barcode")
    # A UUID primary key is not usefully editable, and the audit fields must
    # not be hand-edited.
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [ProductApplicabilityDeclarationInline]


@admin.register(ProductApplicabilityDeclaration)
class ProductApplicabilityDeclarationAdmin(admin.ModelAdmin):
    """Facts stated about a submission that decide which rules govern it.

    Nothing here is read from the label. These are declarations by the person
    submitting the package, and `source` records who said so. An extracted net
    quantity is the declaration being checked; using it to decide whether the
    check applies would be circular.

    A missing row and an explicit UNKNOWN mean the same thing to the engine -
    not established - and a clause turning on either reaches REVIEW_REQUIRED
    rather than a verdict.
    """

    list_display = ("product", "condition", "answer", "source", "updated_at")
    list_filter = ("answer", "source", "condition")
    search_fields = ("product__name", "condition__code", "note")
    autocomplete_fields = ("product", "condition")
    readonly_fields = ("created_at", "updated_at")
