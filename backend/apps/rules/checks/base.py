"""Types shared by every rule validator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from apps.extraction.models import ExtractedLabelField, ExtractionRun
from apps.images.models import ProductImage


class InvalidCheckParameters(ValueError):
    """A rule's `parameters` do not match what its validator needs.

    A configuration error, never a compliance finding. Raised rather than
    returned so a malformed rule is loud instead of quietly passing every
    product it touches.
    """


class CheckStatus(str, Enum):
    """Outcome of evaluating one rule against one extraction run.

    INCONCLUSIVE is the reason this is not boolean, and it is the most
    important state here. "We could not read the photograph" is not the same as
    "the declaration is missing", and collapsing them would make the system
    report bad photography as a legal violation.

    NOT_APPLICABLE is the fourth state and answers a different question again:
    the rule was not evaluated because it does not govern this package. A 5 g
    sachet is outside the Rules under rule 26; a domestic package is outside
    rule 6(1)(aa). Neither is a pass - nothing about the declarations was
    checked - and neither is an inconclusive reading, because there is no
    uncertainty to resolve. Folding it into PASSED would count exemptions as
    evidence of compliance; folding it into INCONCLUSIVE would send a reviewer
    to look at a rule that never applied.
    """

    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class CheckContext:
    """Everything a validator is allowed to look at.

    Deliberately narrow. A validator sees the extraction run and its fields; it
    has no database session, no request, and no access to other products. That
    keeps validators pure and trivially testable - a validator test needs no
    database at all.
    """

    run: ExtractionRun
    fields_by_key: Mapping[str, ExtractedLabelField]

    @property
    def extraction_was_usable(self) -> bool:
        """Whether the run read the label well enough to draw conclusions from.

        When this is False, a validator must return INCONCLUSIVE rather than
        FAILED for anything it cannot find.
        """
        return self.run.produced_usable_output

    @property
    def image(self) -> ProductImage:
        """The primary photograph - position 1 of the run's image set.

        Part of the contract so a future `visual_check` - measuring declaration
        height for a readability requirement - has a defined way to reach a
        source image and its dimensions, rather than reaching through
        `run.image` and coupling itself to the run's shape. Combined with
        `ExtractedLabelField.bounding_box`, this is what makes font-size
        analysis expressible without a schema change.

        An inspection may carry several photographs. A validator that needs the
        one a particular reading came from asks that reading -
        `context.field(key).image` - rather than this, which answers only "the
        primary photograph of this inspection". A measurement made against the
        wrong panel's dimensions would be wrong in a way nothing downstream
        could detect.
        """
        return self.run.image

    def field(self, key: str) -> ExtractedLabelField | None:
        return self.fields_by_key.get(key)

    @classmethod
    def from_run(cls, run: ExtractionRun) -> CheckContext:
        """Build a context from a run, loading its fields once.

        Called once per compliance check rather than per rule, so evaluating
        fifty rules against one run is one query, not fifty.

        **Where a declaration read twice is resolved.** An inspection may carry
        several photographs of the same package, and a declaration printed on
        an overlapping panel - or a front photograph that also catches the edge
        of the back - can be read more than once. Every reading is stored;
        this picks the one the validators judge against, and it is the only
        place that choice is made, so no two rules can be evaluated against
        different readings of the same declaration.

        **The earliest photograph wins**, by position, then by the order the
        readings were written. Not the highest confidence, and the difference
        matters: OCR confidence is an opinion about characters, not about which
        panel of a package carries the authoritative declaration, and choosing
        by it would let a crisp photograph of a promotional flash outrank a
        softer one of the declaration panel. Position is the order the
        submitter supplied, which is the only ordering anybody stated. It is
        predictable, it is the number the interface shows, and a reviewer
        checking a finding can see exactly which photograph it came from.

        No reading is discarded. The ones not selected stay in `run.fields`
        with their own `image`, so a client can show that the package declared
        a net quantity on two panels, and a future reviewer-facing path can
        compare them. Nothing here judges whether two readings agree - that is
        a question about the package, and this layer makes no claims about
        packages.
        """
        # One query for the memberships, not one per field: `from_run` is
        # called once per check and the engine's query-count test bounds the
        # whole evaluation. A run written before image sets existed, or built
        # directly in a fixture, has no membership rows - every reading then
        # sorts at position 1, which is exactly what it was.
        positions = {
            image_id: position
            for image_id, position in run.run_images.values_list(
                "image_id", "position"
            )
        }

        def source_order(reading: ExtractedLabelField) -> tuple[int, int]:
            return (positions.get(reading.image_id, 1), reading.pk or 0)

        fields: dict[str, ExtractedLabelField] = {}
        for reading in sorted(run.fields.all(), key=source_order):
            fields.setdefault(reading.field_key, reading)
        return cls(run=run, fields_by_key=fields)


@dataclass(frozen=True)
class CheckOutcome:
    """What a validator concluded, and the evidence for it."""

    status: CheckStatus
    #: Human-readable explanation shown to the user. Must say what was observed,
    #: not just that something is wrong - this is the text that turns a verdict
    #: into an explanation.
    message: str
    #: The label declaration this outcome concerns, when applicable.
    field_key: str | None = None
    #: Text read from the label that supports this outcome, when there is any.
    evidence_excerpt: str = ""
    #: Where on the image the evidence was found, when known.
    bounding_box: dict[str, int] | None = None
    #: Validator-specific diagnostics for debugging.
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_violation(self) -> bool:
        return self.status is CheckStatus.FAILED
