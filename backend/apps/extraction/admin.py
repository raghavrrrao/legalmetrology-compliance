from django.contrib import admin

from apps.extraction.models import ExtractedLabelField, ExtractionRun


class ExtractedLabelFieldInline(admin.TabularInline):
    model = ExtractedLabelField
    extra = 0
    readonly_fields = ("field_key", "raw_value", "normalized_value", "confidence",
                       "bounding_box")
    can_delete = False


@admin.register(ExtractionRun)
class ExtractionRunAdmin(admin.ModelAdmin):
    list_display = ("id", "engine_name", "engine_version", "status",
                    "is_placeholder", "created_at")
    list_filter = ("status", "is_placeholder", "engine_name")
    inlines = [ExtractedLabelFieldInline]
    # An extraction run is an audit record of what an engine reported. It is
    # never edited after the fact.
    readonly_fields = tuple(
        f.name for f in ExtractionRun._meta.fields
    )
