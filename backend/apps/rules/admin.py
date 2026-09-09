from django.contrib import admin

from apps.rules.models import (
    ApplicabilityCondition,
    ComplianceRule,
    LegalInstrument,
    LegalRule,
    RequirementApplicability,
    RuleRequirement,
)

#: Repeated on every framework admin. Both loaders upsert on a natural key, so
#: an edit made here survives only until the next load - and unlike a change to
#: a JSON file, it leaves nothing for anyone to review.
_AUTHORED_AS_DATA = (
    "Authored as JSON in rules/framework/ and loaded with "
    "`manage.py load_legal_framework`. Editing here is for inspection and "
    "emergencies: a change made in the admin is overwritten the next time the "
    "framework is loaded, and it leaves no diff for anyone to review."
)


@admin.register(ComplianceRule)
class ComplianceRuleAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "source_status", "severity", "check_type",
                    "is_active")
    list_filter = ("source_status", "severity", "is_active", "check_type")
    search_fields = ("code", "title", "legal_reference")
    filter_horizontal = ("applies_to_categories",)
    autocomplete_fields = ("rule_requirement",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("code", "title", "requirement", "is_active")}),
        (
            "Legal source",
            {
                "fields": (
                    "legal_reference",
                    "rule_requirement",
                    "source_status",
                    "source_note",
                ),
                "description": (
                    "Rules are authored as files in rules/definitions/ and loaded "
                    "with `manage.py load_rules`. Editing here is for inspection "
                    "and emergencies - a change made in the admin is overwritten "
                    "the next time the rule file is loaded, and it leaves no diff "
                    "for anyone to review. 'Rule requirement' links this "
                    "executable rule to the clause of the Rules it evaluates; it "
                    "is set by `manage.py load_legal_framework`."
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


@admin.register(LegalInstrument)
class LegalInstrumentAdmin(admin.ModelAdmin):
    list_display = (
        "citation",
        "instrument_type",
        "notified_on",
        "effective_from",
        "verification_status",
    )
    list_filter = ("instrument_type", "verification_status", "is_active")
    search_fields = ("citation", "title", "verification_note")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("citation", "title", "instrument_type", "is_active")}),
        (
            "Dates",
            {
                "fields": ("notified_on", "effective_from"),
                "description": (
                    "These are different facts and are frequently years apart. "
                    "A null effective_from means the source consulted did not "
                    "establish one, or that the instrument commences different "
                    "clauses on different dates - never that it is not in force."
                ),
            },
        ),
        (
            "Provenance",
            {
                "fields": ("source_url", "source_sha256", "verification_status",
                           "verification_note"),
                "description": _AUTHORED_AS_DATA,
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )


class RuleRequirementInline(admin.TabularInline):
    model = RuleRequirement
    extra = 0
    fields = ("clause", "version", "title", "implementation_status",
              "detection_method", "verification_status", "is_active")
    readonly_fields = fields
    show_change_link = True
    can_delete = False

    def has_add_permission(self, request, obj) -> bool:
        # Read-only: requirements are authored in rules/framework/rules.json.
        return False


@admin.register(LegalRule)
class LegalRuleAdmin(admin.ModelAdmin):
    list_display = (
        "rule_number",
        "title",
        "chapter",
        "automation_class",
        "verification_status",
        "is_active",
    )
    list_filter = ("chapter", "automation_class", "verification_status", "is_active")
    search_fields = ("rule_number", "title", "description", "notes")
    ordering = ("sort_key",)
    readonly_fields = ("sort_key", "created_at", "updated_at")
    inlines = [RuleRequirementInline]
    fieldsets = (
        (
            None,
            {
                "fields": ("rule_number", "sort_key", "title", "chapter",
                           "description", "is_active"),
                "description": _AUTHORED_AS_DATA,
            },
        ),
        (
            "Classification",
            {
                "fields": ("automation_class", "verification_status", "notes"),
                "description": (
                    "automation_class is a headline for the rule as a whole. "
                    "It says how far automation could EVER get, not how far "
                    "this system has got - see each requirement's "
                    "implementation_status for that."
                ),
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(ApplicabilityCondition)
class ApplicabilityConditionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "determination", "is_active")
    list_filter = ("determination", "is_active")
    search_fields = ("code", "name", "description", "determination_note")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            None,
            {
                "fields": ("code", "name", "description", "is_active"),
                "description": _AUTHORED_AS_DATA,
            },
        ),
        (
            "How this fact could be established",
            {
                "fields": ("determination", "determination_note"),
                "description": (
                    "'Cannot be established by this system' is the common and "
                    "correct value. A requirement gated on such a condition "
                    "must reach the user as REVIEW_REQUIRED - it must never be "
                    "inferred from OCR output, which would make the rule "
                    "self-fulfilling."
                ),
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )


class RequirementApplicabilityInline(admin.TabularInline):
    model = RequirementApplicability
    extra = 0
    fields = ("condition", "mode", "note")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj) -> bool:
        return False


@admin.register(RuleRequirement)
class RuleRequirementAdmin(admin.ModelAdmin):
    list_display = (
        "clause",
        "version",
        "title",
        "implementation_status",
        "detection_method",
        "verification_status",
        "effective_from",
        "effective_to",
        "is_active",
    )
    list_filter = (
        "implementation_status",
        "detection_method",
        "automation_class",
        "verification_status",
        "is_active",
        "rule__chapter",
    )
    search_fields = ("clause", "title", "requirement", "verbatim_text",
                     "legal_reference", "source_note")
    # Required by ComplianceRuleAdmin.autocomplete_fields.
    ordering = ("rule__sort_key", "clause", "version")
    autocomplete_fields = ("rule", "source", "supersedes")
    inlines = [RequirementApplicabilityInline]
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            None,
            {
                "fields": ("rule", "clause", "version", "supersedes", "title",
                           "is_active"),
                "description": _AUTHORED_AS_DATA,
            },
        ),
        (
            "What is required",
            {
                "fields": ("requirement", "verbatim_text"),
                "description": (
                    "'Requirement' is a plain-language restatement; "
                    "'verbatim text' is the quotation. WHERE THEY DISAGREE THE "
                    "QUOTATION GOVERNS. A blank verbatim text means nobody has "
                    "transcribed the clause - it is not licence to write one."
                ),
            },
        ),
        (
            "How it could be evaluated",
            {
                "fields": ("detection_method", "automation_class",
                           "implementation_status", "severity"),
                "description": (
                    "A detection method other than OCR, CV or OCR+CV means no "
                    "photograph can settle this requirement, however good the "
                    "engine becomes."
                ),
            },
        ),
        (
            "Legal source",
            {
                "fields": ("source", "legal_reference", "verification_status",
                           "source_note"),
            },
        ),
        (
            "Effective window",
            {
                "fields": ("effective_from", "effective_to"),
                "description": (
                    "Amending a clause ADDS a version; it never edits one. A "
                    "null effective_to means still in force - or, where the "
                    "verification status is 'requires review', that the source "
                    "did not settle when it stops. See rule 6(10A)."
                ),
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )
