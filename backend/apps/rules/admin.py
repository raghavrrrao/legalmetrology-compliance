from django.contrib import admin

from apps.rules.models import ComplianceRule


@admin.register(ComplianceRule)
class ComplianceRuleAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "source_status", "severity", "check_type",
                    "is_active")
    list_filter = ("source_status", "severity", "is_active", "check_type")
    search_fields = ("code", "title", "legal_reference")
    filter_horizontal = ("applies_to_categories",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("code", "title", "requirement", "is_active")}),
        (
            "Legal source",
            {
                "fields": ("legal_reference", "source_status", "source_note"),
                "description": (
                    "Rules are authored as files in rules/definitions/ and loaded "
                    "with `manage.py load_rules`. Editing here is for inspection "
                    "and emergencies - a change made in the admin is overwritten "
                    "the next time the rule file is loaded, and it leaves no diff "
                    "for anyone to review."
                ),
            },
        ),
        ("Evaluation", {"fields": ("check_type", "parameters", "severity")}),
        (
            "Applicability",
            {
                "fields": ("applies_to_categories", "effective_from", "effective_to"),
                "description": (
                    "An empty category list means the rule applies to EVERY "
                    "commodity."
                ),
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )
