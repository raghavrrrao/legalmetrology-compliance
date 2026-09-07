"""The compliance rule catalogue and the legal framework behind it.

Rules are *data*, authored as JSON and loaded by management commands. Nothing
in this project encodes a legal requirement as Python branching. See
`rules/README.md` for why, and `rules/SCHEMA.md` for the file formats.

This module holds two layers, and the distinction between them is the point:

**The executable layer** - `ComplianceRule`. One row binds a registered
validator to a set of commodity categories, and the compliance engine runs it
against an extraction run. Authored in `rules/definitions/`, loaded by
`manage.py load_rules`. Six rows ship; two are evaluated.

**The legal framework** - `LegalInstrument`, `LegalRule`, `RuleRequirement`,
`ApplicabilityCondition`, `RequirementApplicability`. What the Legal Metrology
(Packaged Commodities) Rules, 2011 require, clause by clause and version by
version, **whether or not this software can evaluate any of it**. Authored in
`rules/framework/`, loaded by `manage.py load_legal_framework`.

The second layer exists because the first cannot honestly represent rule 32
(penalties) or rules 19-23 (physical inspection and permissible error). Those
are real obligations that no photograph decides. Recording them only as
executable rules would force a choice between hiding them - leaving the widest
compliance risk invisible - and having the engine try to evaluate an image
against them. `ComplianceRule.rule_requirement` is the one link between the
layers, and it is nullable in both directions of meaning: a requirement with no
rule is inventoried but not evaluated, which is the normal state.

The single most important field in the executable layer is `source_status`; in
the framework layer it is `ApplicabilityCondition.determination`, because a
requirement whose applicability the system cannot establish must never be
auto-decided.
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

    requires_applicability_conditions = models.BooleanField(
        default=False,
        help_text=(
            "True when this rule is only safe to evaluate once its clause's "
            "applicability conditions have been resolved - i.e. it was unblocked "
            "BY applicability rather than despite it.\n\n"
            "The failure this prevents: rule 6(1)(aa) binds imported packages "
            "only. With the legal framework not loaded, `rule_requirement` is "
            "null, no trigger condition is found, and the rule would apply to "
            "every package - failing every domestic one for want of a country "
            "of origin it never had to declare. That is the same shape of bug "
            "as LM-PC-0002, which reported a violation against every product.\n\n"
            "So the engine records INCONCLUSIVE rather than evaluating such a "
            "rule unmapped. Set it for any rule whose activation depended on a "
            "trigger or an exemption."
        ),
    )
    rule_requirement = models.ForeignKey(
        "RuleRequirement",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="compliance_rules",
        help_text=(
            "The clause-level legal requirement this executable rule evaluates. "
            "The single link between the executable layer and the legal "
            "framework below. Nullable, and its absence is not an oversight: a "
            "rule may be drafted before the clause it implements has been "
            "transcribed and verified. PROTECT, so a requirement that rules and "
            "findings cite cannot be deleted out from under them. A requirement "
            "may have several rules - presence and format are separate checks "
            "of one clause - so the key sits here, not there."
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


# ---------------------------------------------------------------------------
# The legal-framework layer
#
# Everything above this line is the *executable* rule set: a `ComplianceRule`
# binds a registered validator to a set of categories, and the engine runs it.
# Everything below is the *legal* framework: what the Legal Metrology (Packaged
# Commodities) Rules, 2011 actually require, clause by clause, version by
# version, whether or not this software can evaluate any of it.
#
# They are separate layers on purpose, and `ComplianceRule.rule_requirement` is
# the one link between them. Collapsing them would force a choice nobody should
# have to make: either record only the rules we can check - hiding the 30-odd
# obligations we cannot, which is where the real compliance risk sits - or
# create a `ComplianceRule` row for rule 32 (penalties) and have the engine try
# to evaluate a photograph against it.
#
# The vocabularies are defined once, at module level, because several models
# and the framework loader all need the same words.
# ---------------------------------------------------------------------------


class VerificationStatus(models.TextChoices):
    """Whether a piece of legal content has been checked against its source.

    A superset of `ComplianceRule.SourceStatus`, which stays two-valued on
    purpose: that enum gates whether a rule may call a product non-compliant,
    and adding a third value to it would change the meaning of every rule row
    already stored. This one describes *knowledge*, not evaluation permission.

    REQUIRES_REVIEW is the value that carries the weight. It marks content read
    from a genuine source whose effect that source does not settle - an
    amendment whose transition the notification leaves open, most importantly.
    It is never a synonym for "probably fine", and nothing downstream may treat
    it as VERIFIED.
    """

    VERIFIED = "verified", "Verified against source"
    UNVERIFIED = "unverified", "Not yet verified"
    REQUIRES_REVIEW = "requires_review", "Requires human review"


class DetectionMethod(models.TextChoices):
    """What kind of evidence could settle a requirement *at all*.

    This exists because the most dangerous claim this project could make is
    that a photograph decides a question it cannot decide. A requirement tagged
    PHYSICAL_INSPECTION or ADMINISTRATIVE is not one waiting for somebody to
    write a validator - it is one no image-based validator can ever decide, and
    the honest output for it is REVIEW_REQUIRED.

    Recorded on the requirement rather than inferred from `check_type`, because
    most requirements in this framework have no `check_type` at all: they are
    inventoried, not implemented, and *why* they are not implemented is exactly
    what this field records.
    """

    OCR = "ocr", "OCR - text read from the label"
    CV = "cv", "Computer vision - a rendered or geometric property"
    OCR_CV = "ocr_cv", "OCR and computer vision together"
    DATABASE = "database", "Lookup against a reference dataset"
    USER_INPUT = "user_input", "Supplied by the submitter, not read from the image"
    DIGITAL_ECOMMERCE = (
        "digital_ecommerce",
        "The e-commerce listing, not the physical package",
    )
    PHYSICAL_INSPECTION = (
        "physical_inspection",
        "Physical handling, weighing or measurement of the package",
    )
    ADMINISTRATIVE = (
        "administrative",
        "An administrative or registration record held by a regulator",
    )
    MANUAL_REVIEW = "manual_review", "Human legal judgement"
    NOT_APPLICABLE = (
        "not_applicable",
        "Not an obligation this system assesses at all",
    )

    @classmethod
    def image_evaluable(cls) -> set[str]:
        """The methods a submitted photograph can, in principle, satisfy.

        Anything outside this set must reach the user as REVIEW_REQUIRED rather
        than as a verdict, however confident any model is about the pixels.
        """
        return {cls.OCR.value, cls.CV.value, cls.OCR_CV.value}


class AutomationClass(models.TextChoices):
    """How far automation could ever get with a requirement.

    Separate from `DetectionMethod` because they answer different questions.
    Detection method says *what evidence* would settle the requirement;
    automation class says *how far* automation gets once that evidence exists.
    Rule 7 is OCR_CV yet only PARTIALLY_AUTOMATABLE - glyph geometry is
    measurable from an image, the millimetre scale a photograph does not carry
    is not.

    Seeding a rule into the database changes nothing about this field. A
    requirement is IMAGE_AUTOMATABLE because someone established that an image
    decides it, never because a row now exists for it.
    """

    IMAGE_AUTOMATABLE = (
        "image_automatable",
        "Decidable from a label photograph",
    )
    PARTIALLY_AUTOMATABLE = (
        "partially_automatable",
        "Partly decidable; some element needs input the image does not carry",
    )
    DIGITAL_ECOMMERCE = (
        "digital_ecommerce",
        "Concerns an online listing rather than the package",
    )
    PHYSICAL_MEASUREMENT = (
        "physical_measurement",
        "Needs weighing, measuring or physical sampling",
    )
    ADMINISTRATIVE = (
        "administrative",
        "Needs a regulator's administrative record",
    )
    MANUAL_REVIEW = (
        "manual_review",
        "Needs human legal judgement and must not be automated",
    )


class ImplementationStatus(models.TextChoices):
    """What stands between a requirement and being evaluated today.

    The vocabulary is `rules/INVENTORY.md`'s, kept word for word so the
    document and the database cannot drift apart. One value is added:
    IMPLEMENTED, for a requirement an executable `ComplianceRule` actually
    evaluates. Storing this rather than writing it down turns that file's
    roll-up table into a query.
    """

    IMPLEMENTED = "implemented", "Implemented and evaluated"
    IMPLEMENTABLE_NOW = "implementable_now", "Implementable with existing machinery"
    IMPLEMENTABLE_WITH_NEW_CHECK = (
        "implementable_with_new_check",
        "Needs a check type that does not exist",
    )
    BLOCKED_BY_MISSING_APPLICABILITY_DATA = (
        "blocked_by_missing_applicability_data",
        "The system does not collect the fact that decides whether it applies",
    )
    BLOCKED_BY_MISSING_EXTRACTION_FIELD = (
        "blocked_by_missing_extraction_field",
        "The declaration is not in the extractor's supported set",
    )
    LEGAL_REVIEW_REQUIRED = (
        "legal_review_required",
        "Wording or applicability needs a qualified human first",
    )
    NOT_APPLICABLE_TO_PROJECT_SCOPE = (
        "not_applicable_to_project_scope",
        "A real obligation, but not one a label checker can assess",
    )


class LegalInstrument(TimeStampedModel):
    """One Gazette notification or official publication the rules come from.

    A table rather than a string on each requirement because an amendment is a
    *shared* fact. G.S.R. 629(E) changes eight clauses recorded in this
    framework; its date of effect is one fact about the notification, not eight
    facts repeated across eight rows that can be edited apart and disagree.

    `source_sha256` is not decoration. `rules/SOURCES.md` records that several
    official hosts were unreachable and that one HTTP client rejected the
    certificate chain serving the primary source. The digest pins exactly which
    bytes a claim was read from, so re-verification is a comparison rather than
    an argument.
    """

    class InstrumentType(models.TextChoices):
        PRINCIPAL = "principal", "Principal rules"
        AMENDMENT = "amendment", "Amending notification"
        CONSOLIDATED_PUBLICATION = (
            "consolidated_publication",
            "Departmental consolidated publication",
        )

    citation = models.CharField(
        max_length=128,
        unique=True,
        help_text="The instrument as it cites itself, e.g. 'G.S.R. 128(E)'. "
                  "Stable - requirements reference it.",
    )
    title = models.CharField(max_length=255, blank=True)
    instrument_type = models.CharField(
        max_length=32,
        choices=InstrumentType.choices,
        default=InstrumentType.AMENDMENT,
        db_index=True,
    )

    notified_on = models.DateField(
        null=True,
        blank=True,
        help_text="Date of the notification itself. Distinct from when it "
                  "comes into force: for G.S.R. 312(E) the two are fourteen "
                  "months apart, and conflating them would date a requirement "
                  "wrong by that much.",
    )
    effective_from = models.DateField(
        null=True,
        blank=True,
        help_text="Date the instrument comes into force. Null when the source "
                  "consulted does not establish one - never guessed.",
    )

    source_url = models.URLField(max_length=500, blank=True)
    source_sha256 = models.CharField(
        max_length=64,
        blank=True,
        help_text="Digest of the exact document that was read, so a later "
                  "reviewer can confirm they hold the same bytes.",
    )

    verification_status = models.CharField(
        max_length=16,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
        db_index=True,
    )
    verification_note = models.TextField(
        blank=True,
        help_text="Who read this, when, and what they could NOT establish. "
                  "Required when verification_status is 'verified'.",
    )

    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["notified_on", "citation"]

    def __str__(self) -> str:
        return self.citation

    def clean(self) -> None:
        super().clean()
        if (
            self.verification_status == VerificationStatus.VERIFIED
            and not self.verification_note.strip()
        ):
            raise ValidationError(
                {
                    "verification_note": (
                        "A verified instrument must record who read it and "
                        "against what."
                    )
                }
            )


class LegalRule(TimeStampedModel):
    """One numbered rule of the Legal Metrology (Packaged Commodities) Rules, 2011.

    A container, not an obligation. Rule 6 is not something a package can pass
    or fail - rule 6(1)(c) is. What lives here is what is true of the whole
    rule: its number, its chapter, and an honest headline of how automatable
    its contents are.

    Recorded for every rule in the Rules, including the many this software will
    never evaluate. Rule 32 (penalties) and rules 19-23 (inspection and maximum
    permissible error) are present precisely so that asking "what about rule
    32?" returns a recorded, sourced *no* rather than a silence that reads like
    an oversight.
    """

    rule_number = models.CharField(
        max_length=8,
        unique=True,
        help_text="As the Rules number it: '6', '32A'. A string rather than an "
                  "integer, because rule 32-A exists.",
    )
    sort_key = models.CharField(
        max_length=8,
        db_index=True,
        help_text="Zero-padded number plus any suffix ('006', '032A'), so rule "
                  "32-A sorts between 32 and 33 and rule 10 does not sort "
                  "before rule 2. Derived by the loader, never authored.",
    )
    chapter = models.CharField(
        max_length=80,
        blank=True,
        help_text="Chapter of the Rules, e.g. 'Chapter II - Packages intended "
                  "for retail sale'.",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(
        blank=True,
        help_text="What the rule covers, in plain language. Never a substitute "
                  "for the verbatim text held on each requirement.",
    )

    automation_class = models.CharField(
        max_length=32,
        choices=AutomationClass.choices,
        db_index=True,
        help_text="Headline classification for the rule as a whole. Individual "
                  "requirements may differ, and theirs governs.",
    )
    verification_status = models.CharField(
        max_length=16,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
        db_index=True,
    )
    notes = models.TextField(blank=True)

    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["sort_key"]

    def __str__(self) -> str:
        return f"Rule {self.rule_number}: {self.title}"

    @staticmethod
    def build_sort_key(rule_number: str) -> str:
        """Return the sortable form of `rule_number`: '6' -> '006', '32A' -> '032A'.

        Kept beside the field it fills so the loader and any later author derive
        it the same way rather than each inventing a padding convention.
        """
        digits = "".join(character for character in rule_number if character.isdigit())
        suffix = "".join(
            character
            for character in rule_number
            if character.isalpha()
        ).upper()
        if not digits:
            raise ValueError(f"rule_number contains no digits: {rule_number!r}")
        return f"{int(digits):03d}{suffix}"


class ApplicabilityCondition(TimeStampedModel):
    """One fact about a package that decides whether a requirement applies.

    "Is this an imported package?", "is this a wholesale package?", "is the
    buyer an institutional consumer?" - the questions rules 3, 24, 25 and 26
    turn on before any declaration is looked at.

    `determination` is why this is a model and not a list of strings. It records
    **how the fact could be established**, and for most conditions here the
    answer today is NOT_DETERMINABLE. `rules/INVENTORY.md` calls that the single
    widest correctness caveat in the project; storing it makes the caveat
    queryable instead of a paragraph someone must remember to read.

    Nothing here may be inferred from OCR output. A package that omits an
    importer's name is not thereby domestic - it may simply be unlawful, or
    badly photographed. A requirement gated on a NOT_DETERMINABLE condition
    must reach the user as REVIEW_REQUIRED; see
    `RuleRequirement.applicability_is_determinable`.
    """

    class Determination(models.TextChoices):
        """How this fact could be established, if at all."""

        PRODUCT_CATEGORY = (
            "product_category",
            "Derivable from the product category taxonomy",
        )
        USER_DECLARED = (
            "user_declared",
            "Would have to be supplied by the submitter; not collected today",
        )
        DATABASE = "database", "Needs a reference dataset the system does not hold"
        #: The system has no way to establish this fact, and must not guess it.
        NOT_DETERMINABLE = (
            "not_determinable",
            "Cannot be established by this system",
        )

    code = models.SlugField(
        max_length=64,
        unique=True,
        help_text="Stable identifier, e.g. 'imported-product'. Referenced by "
                  "the framework seed files.",
    )
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)

    determination = models.CharField(
        max_length=32,
        choices=Determination.choices,
        default=Determination.NOT_DETERMINABLE,
        db_index=True,
        help_text="Defaults to NOT_DETERMINABLE so a condition added without "
                  "thought cannot silently license an automatic verdict.",
    )
    determination_note = models.TextField(
        blank=True,
        help_text="Why it is or is not determinable, and what would change that.",
    )
    category_code = models.SlugField(
        max_length=64,
        blank=True,
        help_text=(
            "For a PRODUCT_CATEGORY condition, the `ProductCategory.code` whose "
            "ancestry answers it: a product in 'packaged-food', or any "
            "descendant of it, holds the 'food-article' condition. Blank for "
            "every other determination, and required for this one - without it "
            "PRODUCT_CATEGORY would be a label with nothing behind it, and the "
            "resolver would report the fact unknown for a product whose "
            "category already settles it."
        ),
    )

    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    def clean(self) -> None:
        super().clean()
        if (
            self.determination == self.Determination.PRODUCT_CATEGORY
            and not self.category_code.strip()
        ):
            raise ValidationError(
                {
                    "category_code": (
                        "A condition determined from the product category must "
                        "name the category code that answers it."
                    )
                }
            )
        if (
            self.category_code.strip()
            and self.determination != self.Determination.PRODUCT_CATEGORY
        ):
            raise ValidationError(
                {
                    "category_code": (
                        "Only a PRODUCT_CATEGORY condition may name a category "
                        "code; this one is determined some other way."
                    )
                }
            )

    @property
    def is_determinable(self) -> bool:
        return self.determination != self.Determination.NOT_DETERMINABLE


class RuleRequirement(TimeStampedModel):
    """One clause-level obligation, as it stood under one instrument.

    This is the versioned unit of the framework. A row is not "rule 6(10A)" -
    it is "rule 6(10A) as inserted by G.S.R. 128(E)", and the row for "rule
    6(10A) as substituted by G.S.R. 312(E)" sits beside it with its own
    effective window and its own `source`. Amending a clause **adds a row**; it
    never edits one. `ComplianceFinding` snapshots what it evaluated, and a
    requirement rewritten in place would silently change what a finding
    recorded a year ago meant.

    `verbatim_text` is deliberately separate from `requirement`. `requirement`
    is a plain-language restatement someone can act on; `verbatim_text` is the
    quotation, and where the two ever disagree the quotation governs. A blank
    `verbatim_text` means nobody has transcribed the clause - it is not licence
    to write one from memory.
    """

    rule = models.ForeignKey(
        LegalRule, on_delete=models.PROTECT, related_name="requirements"
    )
    clause = models.CharField(
        max_length=32,
        db_index=True,
        help_text="Sub-rule or clause as the Rules number it: '6(1)(c)', "
                  "'6(10A)', '9(1)(a)'. The bare rule number when the whole "
                  "rule is the unit.",
    )
    version = models.PositiveSmallIntegerField(
        default=1,
        help_text="Increments per amendment of this clause. Version 1 is the "
                  "earliest text this framework records, which is not "
                  "necessarily the clause as first enacted.",
    )
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by",
        help_text="The version this one replaces. PROTECT: deleting an earlier "
                  "version would orphan the history that explains this one.",
    )

    title = models.CharField(max_length=255)
    requirement = models.TextField(
        help_text="What is required, in plain language a non-lawyer can act on."
    )
    verbatim_text = models.TextField(
        blank=True,
        help_text="The clause quoted from the source. Blank when nobody has "
                  "transcribed it - never filled from paraphrase or memory.",
    )

    detection_method = models.CharField(
        max_length=32,
        choices=DetectionMethod.choices,
        db_index=True,
        help_text="What evidence could settle this requirement. Anything "
                  "outside DetectionMethod.image_evaluable() cannot be decided "
                  "from a photograph.",
    )
    automation_class = models.CharField(
        max_length=32, choices=AutomationClass.choices, db_index=True
    )
    implementation_status = models.CharField(
        max_length=48,
        choices=ImplementationStatus.choices,
        db_index=True,
        help_text="What stands between this requirement and evaluation today.",
    )
    severity = models.CharField(
        max_length=16,
        choices=ComplianceRule.Severity.choices,
        default=ComplianceRule.Severity.MAJOR,
        help_text="Triage ranking, sharing ComplianceRule's vocabulary. Carries "
                  "no legal weight of its own.",
    )

    applicability_conditions = models.ManyToManyField(
        ApplicabilityCondition,
        through="RequirementApplicability",
        blank=True,
        related_name="requirements",
    )

    source = models.ForeignKey(
        LegalInstrument,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="requirements",
        help_text="The instrument that established this version of the clause.",
    )
    legal_reference = models.CharField(
        max_length=255,
        blank=True,
        help_text="Citable form, e.g. 'Rule 6(1)(c) of the Legal Metrology "
                  "(Packaged Commodities) Rules, 2011'.",
    )
    verification_status = models.CharField(
        max_length=16,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
        db_index=True,
    )
    source_note = models.TextField(
        blank=True,
        help_text="Who checked this against what, and anything the source did "
                  "NOT settle. Required when verification_status is 'verified'.",
    )

    effective_from = models.DateField(
        null=True,
        blank=True,
        help_text="First date this version applies. Null when the source "
                  "consulted does not establish one.",
    )
    effective_to = models.DateField(
        null=True,
        blank=True,
        help_text="Last date it applies. Null means still in force - or, when "
                  "verification_status is 'requires_review', that the source "
                  "did not settle when it stops. The two are told apart by "
                  "source_note, never by inventing a date.",
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False keeps a requirement on record without treating it as "
                  "part of the present framework - rule 5, omitted, is the "
                  "case this exists for.",
    )

    class Meta:
        ordering = ["rule__sort_key", "clause", "version"]
        constraints = [
            models.UniqueConstraint(
                fields=["clause", "version"], name="requirement_clause_version_uniq"
            ),
        ]
        indexes = [
            models.Index(
                fields=["implementation_status", "automation_class"],
                name="requirement_status_auto_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Rule {self.clause} v{self.version}"

    def clean(self) -> None:
        super().clean()
        if (
            self.verification_status == VerificationStatus.VERIFIED
            and not self.source_note.strip()
        ):
            raise ValidationError(
                {
                    "source_note": (
                        "A verified requirement must record who checked it "
                        "against which source."
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
        if self.supersedes_id and self.supersedes_id == self.pk:
            raise ValidationError(
                {"supersedes": "A requirement cannot supersede itself."}
            )

    def is_in_force_on(self, on_date=None) -> bool:
        """Whether this version's effective window covers `on_date` (default today).

        Mirrors `ComplianceRule.is_in_force_on`, including treating a null
        `effective_from` as "as far back as we model". Kept as its own method
        rather than shared, because the two models are versioned differently
        and a shared helper would invite one to pick up the other's semantics
        by accident.
        """
        on_date = on_date or timezone.localdate()
        if self.effective_from and on_date < self.effective_from:
            return False
        if self.effective_to and on_date > self.effective_to:
            return False
        return True

    @property
    def is_image_evaluable(self) -> bool:
        """Whether a label photograph could, in principle, settle this.

        False for every physical, administrative and e-commerce requirement.
        The engine must not return a verdict on one of those from an image;
        REVIEW_REQUIRED is the only honest output.
        """
        return self.detection_method in DetectionMethod.image_evaluable()

    @property
    def applicability_is_determinable(self) -> bool:
        """Whether every condition gating this requirement can be established.

        False when any attached condition is NOT_DETERMINABLE - the common
        case, and the reason so much of this framework is inventoried rather
        than evaluated. A requirement for which this is False must not be
        auto-decided: the system cannot tell whether it even applies.
        """
        return all(
            condition.is_determinable
            for condition in self.applicability_conditions.all()
        )

    @property
    def requires_human_review(self) -> bool:
        """Whether this requirement can only responsibly reach REVIEW_REQUIRED.

        True when the evidence is not obtainable from an image, when its
        applicability cannot be established, or when the legal content itself
        is flagged REQUIRES_REVIEW. The three independent reasons are read in
        one place so a caller cannot check one and forget the others.
        """
        return (
            not self.is_image_evaluable
            or not self.applicability_is_determinable
            or self.verification_status == VerificationStatus.REQUIRES_REVIEW
        )


class RequirementApplicability(TimeStampedModel):
    """How one condition bears on one requirement.

    A through model rather than a plain many-to-many because the *direction*
    matters and is not recoverable from the pair alone. "Imported product"
    triggers rule 6(1)(aa) and exempts nothing; "food article" exempts rule
    6(1)(a) and triggers nothing. A bare link would record that the two are
    related and lose which way round - the difference between requiring a
    declaration and excusing it.
    """

    class Mode(models.TextChoices):
        #: The requirement applies only when the condition holds.
        REQUIRES = "requires", "Applies only when this condition holds"
        #: The requirement does not apply when the condition holds.
        EXEMPTS = "exempts", "Does not apply when this condition holds"
        #: The condition removes the package from the Chapter, or from the
        #: Rules altogether - rule 3 and rule 26.
        SCOPE_GATE = "scope_gate", "Removes the package from scope entirely"
        #: The condition cancels a SCOPE_GATE on the same requirement, so the
        #: Rules continue to apply. A separate value because it is the exact
        #: opposite of SCOPE_GATE and was previously recorded as REQUIRES,
        #: which already means something else on this model.
        #:
        #: Two provisos in rule 26 work this way and are the reason it exists:
        #: clause (a) exempts packages of ten gram or less, but not tobacco;
        #: clause (c) exempts DPCO formulations, but not medical devices
        #: declared as drugs. Reading either as REQUIRES would say the Rules
        #: apply *only* to tobacco and medical devices - the inverse of the
        #: proviso, and a reading that would exempt almost every package.
        WITHHOLDS_EXEMPTION = (
            "withholds_exemption",
            "Cancels an exemption, so the Rules continue to apply",
        )

    requirement = models.ForeignKey(
        RuleRequirement, on_delete=models.CASCADE, related_name="applicability_links"
    )
    condition = models.ForeignKey(
        ApplicabilityCondition,
        on_delete=models.PROTECT,
        related_name="requirement_links",
    )
    mode = models.CharField(max_length=24, choices=Mode.choices, db_index=True)
    note = models.TextField(
        blank=True,
        help_text="The proviso or explanation this link comes from, quoted or "
                  "cited.",
    )

    class Meta:
        verbose_name_plural = "requirement applicability"
        ordering = ["requirement_id", "condition_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["requirement", "condition", "mode"],
                name="requirement_condition_mode_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.requirement} {self.mode} {self.condition_id}"
