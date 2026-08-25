"""Compliance checks, violations and the evidence behind them.

The design goal for this app is one sentence: **a user must always be able to
ask "why?" and get a real answer.** Every violation points at the rule it came
from, the declaration it concerns, and the text and image region it was read
from. "The AI says non-compliant" is not an output this schema can produce.

Two schema decisions follow from that:

**Results are snapshots, not live joins.** `ComplianceViolation` copies the
rule's severity and message at evaluation time. That is not redundancy - rules
get amended, and a result from last month must keep meaning what it meant last
month. The `rule` foreign key is PROTECTed so the reference can never dangle.

**Many checks per extraction.** `ComplianceCheck` is a foreign key, not a
one-to-one, so re-evaluating after the rule set is updated adds a new check and
leaves the history intact.
"""

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel, UUIDPrimaryKeyModel


class ComplianceCheck(UUIDPrimaryKeyModel, TimeStampedModel):
    """One evaluation of one extraction run against the rule set."""

    class Status(models.TextChoices):
        """Lifecycle of the evaluation itself, not its verdict."""

        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Result(models.TextChoices):
        """The verdict.

        REVIEW_REQUIRED is the honest default and the most important value
        here. It is returned whenever the system cannot responsibly say
        anything: no verified rules exist, the product's category is unknown,
        the photograph was unreadable, or every applicable rule was
        inconclusive. It means "a human needs to look at this", never "this is
        fine".

        COMPLIANT is deliberately hard to reach: it requires at least one
        verified rule to have actually been evaluated and passed. Absence of
        findings is not compliance.
        """

        COMPLIANT = "compliant", "Compliant"
        PARTIALLY_COMPLIANT = "partially_compliant", "Partially compliant"
        NON_COMPLIANT = "non_compliant", "Non-compliant"
        REVIEW_REQUIRED = "review_required", "Review required"

    product = models.ForeignKey(
        "catalog.Product",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="compliance_checks",
        help_text="Null when the image has not been linked to a product yet.",
    )
    extraction_run = models.ForeignKey(
        "extraction.ExtractionRun",
        on_delete=models.CASCADE,
        related_name="compliance_checks",
        help_text="The readings this check was evaluated against.",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="compliance_checks",
    )

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    result = models.CharField(
        max_length=32,
        choices=Result.choices,
        default=Result.REVIEW_REQUIRED,
        db_index=True,
        help_text="Defaults to REVIEW_REQUIRED so an incomplete check can "
                  "never read as a clean bill of health.",
    )

    engine_version = models.CharField(
        max_length=32,
        help_text="Version of the compliance engine that produced this result, "
                  "so a verdict stays interpretable after the engine changes.",
    )

    rules_evaluated = models.PositiveIntegerField(
        default=0, help_text="Applicable rules that were actually evaluated."
    )
    rules_passed = models.PositiveIntegerField(default=0)
    rules_failed = models.PositiveIntegerField(default=0)
    rules_inconclusive = models.PositiveIntegerField(
        default=0,
        help_text="Rules that could not be decided, usually because the image "
                  "was not readable.",
    )

    summary = models.TextField(
        blank=True,
        help_text="Plain-language explanation of how this result was reached, "
                  "including what could NOT be determined.",
    )

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    processing_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product", "-created_at"], name="check_product_idx"),
            models.Index(fields=["result"], name="check_result_idx"),
        ]

    def __str__(self) -> str:
        return f"Check {self.pk}: {self.result}"


class ComplianceViolation(TimeStampedModel):
    """One rule that a product failed, with the evidence for the finding.

    Only rules with `source_status = verified` can produce a violation. An
    unverified rule contributes to `rules_inconclusive` and pushes the result
    to REVIEW_REQUIRED instead - enforced in
    `apps.compliance.services.engine`.
    """

    # Named `compliance_check`, not `check`: Django reserves `Model.check()`
    # as a system-check hook, and a field of that name shadows it (models.E020).
    compliance_check = models.ForeignKey(
        ComplianceCheck, on_delete=models.CASCADE, related_name="violations"
    )
    rule = models.ForeignKey(
        "rules.ComplianceRule",
        on_delete=models.PROTECT,
        related_name="violations",
        help_text="PROTECT: a rule with recorded findings must not be "
                  "deletable, or the findings lose their justification.",
    )

    # --- snapshot of the rule as it was when evaluated ---
    severity = models.CharField(
        max_length=16,
        help_text="Copied from the rule at evaluation time. Not redundant: "
                  "rules are amended, and past findings must not silently "
                  "change meaning.",
    )
    rule_code = models.CharField(max_length=64, db_index=True)
    legal_reference = models.CharField(max_length=255, blank=True)

    field_key = models.CharField(
        max_length=64,
        blank=True,
        help_text="The label declaration this finding concerns, if any.",
    )
    message = models.TextField(
        help_text="What was observed and why it was flagged, in plain language."
    )

    class Meta:
        ordering = ["rule_code"]
        indexes = [
            models.Index(
                fields=["compliance_check", "severity"],
                name="violation_check_sev_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.rule_code} ({self.severity})"


class ComplianceEvidence(TimeStampedModel):
    """What a violation was based on: the text read, and where it came from.

    Kept in a separate table rather than as columns on the violation because
    one finding can rest on several observations - a wrong net-quantity
    declaration may cite both the quantity text and the unit text, read from
    different parts of the package.
    """

    violation = models.ForeignKey(
        ComplianceViolation, on_delete=models.CASCADE, related_name="evidence"
    )
    extracted_field = models.ForeignKey(
        "extraction.ExtractedLabelField",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="evidence",
        help_text="The specific reading, when the evidence is a declaration "
                  "that WAS found. Null when the evidence is an absence.",
    )
    image = models.ForeignKey(
        "images.ProductImage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="evidence",
        help_text="The image this was read from, so the UI can show it.",
    )

    excerpt = models.TextField(
        blank=True,
        help_text="The recognised text supporting the finding. For an absent "
                  "declaration, what WAS read instead.",
    )
    bounding_box = models.JSONField(
        null=True,
        blank=True,
        help_text="{'x','y','width','height'} in source-image pixels, so the "
                  "UI can highlight the region. Null when not localised.",
    )
    note = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "compliance evidence"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"Evidence for {self.violation_id}"
