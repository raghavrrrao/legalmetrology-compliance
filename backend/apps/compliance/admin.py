from django.contrib import admin

from apps.compliance.models import (
    ComplianceCheck,
    ComplianceEvidence,
    ComplianceFinding,
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


class ComplianceFindingInline(admin.TabularInline):
    """Every rule that was examined, not only the ones that failed.

    Listed above the violations on a check, because "what was checked" is the
    question a reviewer has before "what was wrong" - and a check with no
    violations is otherwise indistinguishable from one where nothing could be
    decided.
    """

    model = ComplianceFinding
    extra = 0
    fields = ("rule_code", "status", "field_key", "extracted_confidence",
              "downgraded_from_failed", "message")
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(ComplianceFinding)
class ComplianceFindingAdmin(admin.ModelAdmin):
    list_display = ("rule_code", "status", "field_key", "extracted_confidence",
                    "downgraded_from_failed", "compliance_check", "created_at")
    list_filter = ("status", "downgraded_from_failed", "severity", "check_type")
    search_fields = ("rule_code", "message")
    # A finding is a point-in-time record of what a check concluded. Editing
    # one would rewrite what a past evaluation meant.
    readonly_fields = tuple(f.name for f in ComplianceFinding._meta.fields)


@admin.register(ComplianceCheck)
class ComplianceCheckAdmin(admin.ModelAdmin):
    list_display = ("id", "result", "status", "rules_evaluated", "rules_failed",
                    "rules_inconclusive", "created_at")
    list_filter = ("result", "status")
    inlines = [ComplianceFindingInline, ComplianceViolationInline]
    # A compliance result is a point-in-time record. Re-evaluate to get a new
    # one; never edit an old one.
    readonly_fields = tuple(f.name for f in ComplianceCheck._meta.fields)
