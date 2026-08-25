from django.contrib import admin

from apps.images.models import ProductImage


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "image_format", "view_type", "status",
                    "created_at")
    list_filter = ("status", "view_type", "image_format")
    search_fields = ("original_filename", "checksum_sha256")
    # Everything here was measured during validation. Editing it by hand would
    # make the stored metadata disagree with the stored bytes.
    readonly_fields = (
        "id", "original_filename", "content_type", "image_format", "size_bytes",
        "width", "height", "checksum_sha256", "created_at", "updated_at",
    )
