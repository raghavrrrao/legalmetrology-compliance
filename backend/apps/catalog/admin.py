from django.contrib import admin

from apps.catalog.models import Product, ProductCategory


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "parent", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("__str__", "brand", "category", "created_at")
    list_filter = ("category",)
    search_fields = ("name", "brand", "barcode")
    # A UUID primary key is not usefully editable, and the audit fields must
    # not be hand-edited.
    readonly_fields = ("id", "created_at", "updated_at")
