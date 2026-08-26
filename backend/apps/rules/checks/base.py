"""Types shared by every rule validator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from apps.extraction.models import (
    ExtractedLabelField,
    ExtractionRun,
    UnreadLabelDeclaration,
)
from apps.images.models import ProductImage


class InvalidCheckParameters(ValueError):
    """A rule's `parameters` do not match what its validator needs.

    A configuration error, never a compliance finding. Raised rather than
    returned so a malformed rule is loud instead of quietly passing every
    product it touches.
    """


class CheckStatus(str, Enum):
    """Outcome of evaluating one rule against one extraction run.

    INCONCLUSIVE is the reason this is three-valued rather than boolean, and it
    is the most important state here. "We could not read the photograph" is not
    the same as "the declaration is missing", and collapsing them would make
    the system report bad photography as a legal violation.
    """

    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class CheckContext:
    """Everything a validator is allowed to look at.

    Deliberately narrow. A validator sees the extraction run, the declarations
    read from it, and the declarations the label named that could not be read.
    It has no database session, no request, and no access to other products.
    That keeps validators pure and trivially testable - a validator test needs
    no database at all.

    The two collections are separate and must stay separate. `fields_by_key`
    holds readings; `unread_by_key` holds observations that a declaration was
    *named* and its value was not legible. Merging them would let a presence
    check pass on the strength of something nobody could read.
    """

    run: ExtractionRun
    fields_by_key: Mapping[str, ExtractedLabelField]
    #: Declarations named on the label whose values were not read, keyed the
    #: same way. Defaults to empty so a `CheckContext` built by hand - in a
    #: test, or by code written before this existed - keeps working unchanged.
    unread_by_key: Mapping[str, UnreadLabelDeclaration] = field(
        default_factory=dict
    )

    @property
    def extraction_was_usable(self) -> bool:
        """Whether the run read the label well enough to draw conclusions from.

        When this is False, a validator must return INCONCLUSIVE rather than
        FAILED for anything it cannot find.
        """
        return self.run.produced_usable_output

    @property
    def image(self) -> ProductImage:
        """The image these readings came from.

        Part of the contract so a future `visual_check` - measuring declaration
        height for a readability requirement - has a defined way to reach the
        source image and its dimensions, rather than reaching through
        `run.image` and coupling itself to the run's shape. Combined with
        `ExtractedLabelField.bounding_box`, this is what makes font-size
        analysis expressible without a schema change.
        """
        return self.run.image

    def field(self, key: str) -> ExtractedLabelField | None:
        return self.fields_by_key.get(key)

    def unread(self, key: str) -> UnreadLabelDeclaration | None:
        """The observation that `key` was named on the label but not read.

        None means no such observation - which is *not* the same as the
        declaration being absent. `field(key) is None and unread(key) is None`
        is "we read the label and this declaration is not on it";
        `field(key) is None and unread(key) is not None` is "the label names
        this declaration and we could not read what it says". A validator that
        treats those two the same reports bad photography as a violation.
        """
        return self.unread_by_key.get(key)

    @classmethod
    def from_run(cls, run: ExtractionRun) -> CheckContext:
        """Build a context from a run, loading its readings once.

        Called once per compliance check rather than per rule, so evaluating
        fifty rules against one run is two queries, not a hundred.

        A run recorded before unread declarations were persisted simply has
        none, and every validator behaves for it exactly as it did before.
        """
        fields = {f.field_key: f for f in run.fields.all()}
        unread = {u.field_key: u for u in run.unread_declarations.all()}
        return cls(run=run, fields_by_key=fields, unread_by_key=unread)


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
