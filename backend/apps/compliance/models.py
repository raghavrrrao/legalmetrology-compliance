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


class ComplianceFinding(TimeStampedModel):
    """The outcome of evaluating **one rule** against one extraction run.

    One row per applicable rule, whatever it concluded - passed, failed, or
    could not be decided. `ComplianceViolation` records only failures, which
    left `rules_passed` and `rules_inconclusive` as bare integers: a user could
    see that two rules could not be determined but not *which* two, against
    which declaration, or why. Inconclusive is the state that sends a package
    to a human, so it is the one that most needed a record.

    Why this exists alongside `ComplianceViolation` rather than replacing it
    ---------------------------------------------------------------------
    They answer different questions and have different lifetimes.

    A violation is the **legal finding of record**: it snapshots the rule, its
    `rule` foreign key is PROTECTed so the justification can never dangle, and
    the API and frontend already treat `violations` as the list of things wrong
    with a package. A finding is the **complete evaluation trace**, including
    every rule that passed and every rule that could not be decided.

    Replacing violations with findings would have meant migrating a shipped API
    contract to gain nothing a `status` filter does not already give. So the
    violation is left exactly as it was and points back at the finding it came
    from, and the overlapping snapshot columns are the price of keeping the two
    answers independently readable.

    This model decides nothing. Every column is copied from a `CheckOutcome`
    that `apps.rules.checks` already produced, or from the rule row as it stood
    when it was evaluated.
    """

    class Status(models.TextChoices):
        """Mirrors `apps.rules.checks.base.CheckStatus`.

        A separate enum rather than a shared one, for the same reason
        `ExtractionRun.Status` is separate from `ExtractionStatus`: this is a
        database vocabulary that must stay readable for stored rows, and the
        checks package owns a runtime vocabulary that is free to change.
        `engine._FINDING_STATUS` maps between them in one place.

        INCONCLUSIVE is the value that carries the weight. "We could not read
        the photograph" is not "the declaration is missing", and a finding that
        collapsed the two would report bad photography as a legal violation.
        """

        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        INCONCLUSIVE = "inconclusive", "Inconclusive"

    compliance_check = models.ForeignKey(
        ComplianceCheck, on_delete=models.CASCADE, related_name="findings"
    )
    rule = models.ForeignKey(
        "rules.ComplianceRule",
        on_delete=models.PROTECT,
        related_name="findings",
        help_text="PROTECT, for the same reason as on ComplianceViolation: a "
                  "rule with recorded outcomes must not be deletable.",
    )
    # A string reference: ComplianceViolation is defined below, because the
    # finding is the record the violation is derived from and reads first.
    violation = models.OneToOneField(
        "ComplianceViolation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="finding",
        help_text="The violation this finding was recorded as, when it failed "
                  "and the rule was verified. Null for a pass, for an "
                  "inconclusive outcome, and for a failure that was downgraded "
                  "because the rule is unverified.",
    )

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        db_index=True,
        help_text="What the registered validator concluded.",
    )
    downgraded_from_failed = models.BooleanField(
        default=False,
        help_text=(
            "True when the validator returned FAILED but the rule is not "
            "verified against the authoritative legal text, so the engine "
            "recorded it as inconclusive instead. Surfaced because the "
            "downgrade is a deliberate legal safeguard, and a reviewer needs "
            "to see that it happened rather than infer it."
        ),
    )

    # --- snapshot of the rule as it was when evaluated ---
    rule_code = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=255, blank=True)
    requirement = models.TextField(
        blank=True,
        help_text="What the package must declare, in the rule's own words. "
                  "Snapshotted so a finding stays readable on its own - this "
                  "is the 'expected requirement' half of the finding, and "
                  "without it a rule code means nothing to a user.",
    )
    legal_reference = models.CharField(max_length=255, blank=True)
    severity = models.CharField(
        max_length=16,
        help_text="Triage ranking copied from the rule. Carries no legal "
                  "weight - see rules/SCHEMA.md.",
    )
    check_type = models.CharField(
        max_length=32,
        blank=True,
        help_text="Which registered validator produced this outcome.",
    )

    # --- what was actually read, and how sure the reader was ---
    field_key = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="The label declaration this outcome concerns, if any.",
    )
    extracted_field = models.ForeignKey(
        "extraction.ExtractedLabelField",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="findings",
        help_text="The specific reading this outcome was drawn from, when the "
                  "declaration was found. Null when the finding is about an "
                  "absence. This is the link that makes a finding traceable "
                  "back to the pixels it came from.",
    )
    extracted_confidence = models.FloatField(
        null=True,
        blank=True,
        help_text=(
            "The OCR/ML confidence for the reading behind this finding, in "
            "[0, 1], or NULL when the engine did not report one or the finding "
            "is about an absence. NULL means 'unknown' and must never be read "
            "as zero or as certainty. Snapshotted rather than followed through "
            "`extracted_field` so it survives the reading being deleted. "
            "Recorded, not thresholded: no rule in this repository conditions "
            "its outcome on it."
        ),
    )

    message = models.TextField(
        help_text="What was observed and why, in plain language. Written by "
                  "the validator, copied verbatim."
    )
    evidence_excerpt = models.TextField(
        blank=True,
        help_text="Text read from the label supporting this outcome. For an "
                  "absence, what WAS read instead.",
    )
    bounding_box = models.JSONField(
        null=True,
        blank=True,
        help_text="{'x','y','width','height'} in source-image pixels, or null.",
    )
    details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Validator diagnostics, verbatim from CheckOutcome.details. "
                  "Shape is validator-specific and deliberately not modelled.",
    )

    class Meta:
        ordering = ["rule_code"]
        indexes = [
            models.Index(
                fields=["compliance_check", "status"],
                name="finding_check_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.rule_code}: {self.status}"

    @property
    def is_violation(self) -> bool:
        """Whether this outcome was recorded as a violation.

        Not the same as `status == FAILED`: a failure against an unverified
        rule is downgraded and produces no violation. Reading the link rather
        than the status is what keeps the two consistent.
        """
        return self.violation_id is not None


class ComplianceViolation(TimeStampedModel):
    """One rule that a product failed, with the evidence for the finding.

    Only rules with `source_status = verified` can produce a violation. An
    unverified rule contributes to `rules_inconclusive` and pushes the result
    to REVIEW_REQUIRED instead - enforced in
    `apps.compliance.services.engine`.

    The full evaluation trace, including rules that passed and rules that could
    not be decided, is `ComplianceFinding`. Each violation is reachable from
    its finding through `ComplianceFinding.violation`; see that model for why
    both exist.
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
