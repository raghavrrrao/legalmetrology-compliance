"""The compliance rule catalogue.

Rules are *data*, authored as JSON in `rules/definitions/` and loaded here by
`manage.py load_rules`. Nothing in this project encodes a legal requirement as
Python branching. See `rules/README.md` for why, and `rules/SCHEMA.md` for the
file format.

The single most important field in this module is `source_status`.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class ComplianceRule(TimeStampedModel):
    """One compliance requirement that can be evaluated against a product.

    Identified by `code`, which is stable and never reused: compliance results
    reference it, and renumbering would silently change what a historical
    finding meant.
    """

    class SourceStatus(models.TextChoices):
        """Whether this rule's legal text has been checked against the source.

        This is the mechanism that keeps the system honest while six people
        work in parallel. Someone can draft rules before anyone has verified
        them, and the engine still cannot use a draft to tell a user their
        product is illegal.
        """

        #: A named person checked this against the authoritative text and
        #: recorded it in `source_note`. Only these can produce a violation.
        VERIFIED = "verified", "Verified against source"
        #: Drafted but not yet checked. Evaluated, but can only ever contribute
        #: REVIEW_REQUIRED - never a finding of non-compliance.
        UNVERIFIED = "unverified", "Not yet verified"

    class Severity(models.TextChoices):
        """Triage ranking for the UI. Carries no legal weight of its own."""

        INFO = "info", "Informational"
        MINOR = "minor", "Minor"
        MAJOR = "major", "Major"
        CRITICAL = "critical", "Critical"

    code = models.SlugField(
        max_length=64,
        unique=True,
        help_text="Stable identifier, e.g. 'LM-PC-0001'. Never reused or "
                  "renumbered - results reference it.",
    )
    title = models.CharField(max_length=255)
    requirement = models.TextField(
        help_text="What the package must declare, in plain language a "
                  "non-lawyer can act on.",
    )

    legal_reference = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "The provision exactly as the authoritative text numbers it. "
            "Blank when not certain - a guessed rule number is worse than none."
        ),
    )
    source_status = models.CharField(
        max_length=16,
        choices=SourceStatus.choices,
        default=SourceStatus.UNVERIFIED,
        db_index=True,
    )
    source_note = models.TextField(
        blank=True,
        help_text="Who verified this, against what, and when. Required when "
                  "source_status is 'verified'.",
    )

    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.MAJOR
    )

    check_type = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Names a validator registered in apps.rules.checks. "
                  "Unknown values are rejected at load time.",
    )
    parameters = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Validator configuration, e.g. {'field_key': 'net_quantity'}. "
            "JSON because the shape legitimately differs per check_type; "
            "each validator declares and validates its own."
        ),
    )

    applies_to_categories = models.ManyToManyField(
        "catalog.ProductCategory",
        blank=True,
        related_name="rules",
        help_text=(
            "Categories this rule applies to. EMPTY MEANS EVERY COMMODITY - "
            "a strong claim, so set it deliberately. Relational rather than "
            "JSON because the engine queries applicability by category."
        ),
    )

    effective_from = models.DateField(
        null=True, blank=True, help_text="First date the rule applies."
    )
    effective_to = models.DateField(
        null=True, blank=True, help_text="Last date it applies. Null = in force."
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Set False to keep a rule on record without evaluating it.",
    )

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(
                fields=["is_active", "source_status"], name="rule_active_source_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code}: {self.title}"

    def clean(self) -> None:
        """Enforce the invariants that keep rule data trustworthy."""
        super().clean()
        if self.source_status == self.SourceStatus.VERIFIED and not self.source_note.strip():
            raise ValidationError(
                {
                    "source_note": (
                        "A verified rule must record who checked it against "
                        "what source."
                    )
                }
            )
        if (
            self.effective_from
            and self.effective_to
            and self.effective_to < self.effective_from
        ):
            raise ValidationError(
                {"effective_to": "effective_to must not precede effective_from."}
            )

    @property
    def is_verified(self) -> bool:
        """Whether this rule may produce a finding of non-compliance."""
        return self.source_status == self.SourceStatus.VERIFIED

    def is_in_force_on(self, on_date=None) -> bool:
        """Whether the rule's effective window covers `on_date` (default today)."""
        on_date = on_date or timezone.localdate()
        if self.effective_from and on_date < self.effective_from:
            return False
        if self.effective_to and on_date > self.effective_to:
            return False
        return True

    def applies_to_category_codes(self, codes: list[str]) -> bool:
        """Whether this rule applies to a product matching `codes`.

        An empty `applies_to_categories` means the rule is universal. Otherwise
        the rule applies when any of the product's category codes - including
        inherited ancestors - is targeted.

        Iterates `.all()` rather than calling `.values_list("code", flat=True)`.
        That is not a style choice: `values_list` builds a fresh queryset and
        therefore ignores a `prefetch_related("applies_to_categories")` cache,
        issuing one extra query per rule. Callers that evaluate every active
        rule (see apps.compliance.services.engine.applicable_rules) would turn
        one query into one-per-rule. `.all()` reads the prefetch cache.
        """
        targeted = {category.code for category in self.applies_to_categories.all()}
        if not targeted:
            return True
        return bool(targeted & set(codes))
