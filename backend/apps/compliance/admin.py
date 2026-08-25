from django.contrib import admin

from apps.compliance.models import (
    ComplianceCheck,
    ComplianceEvidence,
    ComplianceViolation,
)


class ComplianceEvidenceInline(admin.TabularInline):
    model = ComplianceEvidence
    extra = 0
    readonly_fields = ("extracted_field", "image", "excerpt", "bounding_box", "note")
    can_delete = False


@admin.register(ComplianceViolation)
class ComplianceViolationAdmin(admin.ModelAdmin):
    list_display = ("rule_code", "severity", "field_key", "compliance_check", "created_at")
    list_filter = ("severity",)
    search_fields = ("rule_code", "message")
    inlines = [ComplianceEvidenceInline]
    readonly_fields = tuple(f.name for f in ComplianceViolation._meta.fields)


class ComplianceViolationInline(admin.TabularInline):
    model = ComplianceViolation
    extra = 0
    fields = ("rule_code", "severity", "field_key", "message")
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(ComplianceCheck)
class ComplianceCheckAdmin(admin.ModelAdmin):
    list_display = ("id", "result", "status", "rules_evaluated", "rules_failed",
                    "rules_inconclusive", "created_at")
    list_filter = ("result", "status")
    inlines = [ComplianceViolationInline]
    # A compliance result is a point-in-time record. Re-evaluate to get a new
    # one; never edit an old one.
    readonly_fields = tuple(f.name for f in ComplianceCheck._meta.fields)
