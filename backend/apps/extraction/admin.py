from django.contrib import admin

from apps.extraction.models import (
    ExtractedLabelField,
    ExtractionRun,
    UnreadLabelDeclaration,
)


class ExtractedLabelFieldInline(admin.TabularInline):
    model = ExtractedLabelField
    extra = 0
    readonly_fields = ("field_key", "raw_value", "normalized_value", "confidence",
                       "bounding_box")
    can_delete = False


class UnreadLabelDeclarationInline(admin.TabularInline):
    """Declarations the label named that the engine could not read.

    Shown beside the readings rather than mixed into them: a reviewer looking
    at a run needs to see "this panel says MRP and we could not read it" as a
    different thing from a declaration that was read.
    """

    model = UnreadLabelDeclaration
    extra = 0
    readonly_fields = ("field_key", "evidence_text", "confidence", "bounding_box")
    can_delete = False


@admin.register(ExtractionRun)
class ExtractionRunAdmin(admin.ModelAdmin):
    list_display = ("id", "engine_name", "engine_version", "status",
                    "is_placeholder", "created_at")
    list_filter = ("status", "is_placeholder", "engine_name")
    inlines = [ExtractedLabelFieldInline, UnreadLabelDeclarationInline]
    # An extraction run is an audit record of what an engine reported. It is
    # never edited after the fact.
    readonly_fields = tuple(
        f.name for f in ExtractionRun._meta.fields
    )
