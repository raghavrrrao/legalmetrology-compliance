"""Deciding whether a requirement governs a package, before evaluating it.

Step 1 recorded applicability as data: which conditions bear on which clause,
which way round, and whether this system could ever establish them. Nothing
read it. Every active rule was evaluated against every submission in its
category, which `rules/INVENTORY.md` names as the widest correctness caveat in
the project - a 5 g sachet, a 30 kg sack and a restaurant takeaway box are all
outside the Rules, and all three were being checked against them.

This module is where that data starts deciding something.

    Product + declarations
        -> resolve each condition          YES / NO / UNKNOWN
        -> combine per requirement         APPLIES / DOES_NOT_APPLY / UNDETERMINED
        -> the engine evaluates, skips, or sends to review

The safety property, which every branch below preserves
-------------------------------------------------------
**An unestablished fact never produces a verdict.** A condition nobody answered
is UNKNOWN, and a requirement whose applicability turns on an UNKNOWN condition
resolves to UNDETERMINED, which the engine records as inconclusive - not as a
pass, and not as a violation. Silence must cost a review, never a verdict.

Nothing here reads the label. An extracted `net_quantity` is the declaration
being checked; using it to decide whether the check applies would be circular,
and a package that omits a declaration would appear exempt from having to make
it. Facts come from `ProductApplicabilityDeclaration`, or they are unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from enum import Enum

from apps.catalog.models import Product, ProductApplicabilityDeclaration
from apps.rules.models import ApplicabilityCondition, RequirementApplicability

#: Answer to "does this condition hold for this package?"
YES = ProductApplicabilityDeclaration.Answer.YES
NO = ProductApplicabilityDeclaration.Answer.NO
UNKNOWN = ProductApplicabilityDeclaration.Answer.UNKNOWN


class Applicability(str, Enum):
    """Whether a requirement governs this package.

    Three values, because two would force the unknown case to masquerade as one
    of the others - and whichever it were folded into would be wrong. Folded
    into APPLIES, an unanswered exemption question produces violations against
    packages the Rules exempt. Folded into DOES_NOT_APPLY, an unanswered
    trigger silently excuses a package from a declaration it owes.
    """

    APPLIES = "applies"
    DOES_NOT_APPLY = "does_not_apply"
    UNDETERMINED = "undetermined"


@dataclass(frozen=True)
class ApplicabilityDecision:
    """Why a requirement was or was not evaluated.

    Carries its reasoning, not just its verdict. The reasons are written onto
    the finding, because "rule 6(1)(e) was not checked" is not something a user
    can act on, while "not checked: you declared this package contains bidi,
    which proviso (C) excuses from the retail sale price declaration" is.
    """

    applicability: Applicability
    #: Short sentences, each naming one condition and what it did.
    reasons: list[str] = dataclass_field(default_factory=list)
    #: Condition codes that could not be established. Empty unless UNDETERMINED.
    unresolved: list[str] = dataclass_field(default_factory=list)

    @property
    def applies(self) -> bool:
        return self.applicability is Applicability.APPLIES

    @property
    def is_undetermined(self) -> bool:
        return self.applicability is Applicability.UNDETERMINED

    def explain(self) -> str:
        return " ".join(self.reasons)


class DeclarationSet:
    """The applicability facts stated about one package.

    Loaded once per compliance check and passed to every requirement, so
    evaluating fifty rules costs one query rather than fifty.

    `answer()` is the only way to ask a question of it, and it returns UNKNOWN
    for a condition with no row. That default is the whole safety property:
    absence of an answer is never absence of the condition.
    """

    def __init__(self, product: Product | None):
        self._product = product
        self._answers: dict[str, str] = {}
        self._notes: dict[str, str] = {}
        #: The product's category code and every ancestor's, so a condition
        #: attached to 'packaged-food' is answered for a product in a
        #: sub-category of it. Empty when no category is set, which correctly
        #: leaves every category-derived condition unknown.
        self._category_codes: set[str] = set(
            product.applicable_category_codes if product is not None else []
        )
        if product is None:
            return
        declarations = (
            ProductApplicabilityDeclaration.objects.filter(product=product)
            .select_related("condition")
            .all()
        )
        for declaration in declarations:
            self._answers[declaration.condition.code] = declaration.answer
            self._notes[declaration.condition.code] = declaration.note

    def answer(self, condition: ApplicabilityCondition) -> str:
        """Return YES, NO or UNKNOWN for `condition`.

        Three sources, in this order:

        1. A condition the framework marks NOT_DETERMINABLE is always UNKNOWN,
           even if a row exists. The framework's judgement that this system
           cannot establish a fact outranks a stated answer to it. Rule 33
           relaxations are the case that matters - nobody can confirm one from
           here, so a submitter's claim must not switch off a check.
        2. An explicit declaration, when one was recorded.
        3. The product's category, for a PRODUCT_CATEGORY condition. A product
           in 'packaged-food' holds 'food-article' without anyone restating it,
           and a product in a category that is known and is *not* that one
           answers NO - the category is positive evidence either way. A product
           with no category answers UNKNOWN, because then nothing is known.

        Declaration before derivation, so a reviewer correcting a
        miscategorised submission is not overridden by the taxonomy.
        """
        if not condition.is_determinable:
            return UNKNOWN

        stated = self._answers.get(condition.code)
        if stated is not None:
            return stated

        if (
            condition.determination
            == ApplicabilityCondition.Determination.PRODUCT_CATEGORY
            and condition.category_code
        ):
            if not self._category_codes:
                return UNKNOWN
            return YES if condition.category_code in self._category_codes else NO

        return UNKNOWN

    def note(self, condition: ApplicabilityCondition) -> str:
        return self._notes.get(condition.code, "")

    @property
    def stated_codes(self) -> set[str]:
        """Condition codes with a stated YES or NO. For diagnostics."""
        return {
            code for code, answer in self._answers.items() if answer in {YES, NO}
        }


#: The decision recorded for a conditional rule the framework has not mapped.
#: Not UNDETERMINED about the package - it is undetermined about the rule
#: itself, which is a deployment fault rather than a fact about the goods.
UNMAPPED_CONDITIONAL = ApplicabilityDecision(
    applicability=Applicability.UNDETERMINED,
    reasons=[
        "This rule applies only to packages meeting conditions recorded in "
        "the legal framework, and it is not linked to a clause of it, so "
        "whether it applies could not be determined."
    ],
)

#: The clauses that remove a package from the Rules, or from Chapter II,
#: rather than from one requirement. Rule 3 gates every requirement of rules
#: 4-23; rule 26 gates the Rules entirely. Both are transcribed verbatim in
#: `rules/framework/rules.json`, and neither can be expressed as a link on the
#: individual clauses it gates - there would be one copy per clause, and they
#: would drift.
SCOPE_GATE_CLAUSES: tuple[str, ...] = ("3", "26")


def decide_scope(declarations: DeclarationSet) -> ApplicabilityDecision:
    """Decide whether the Rules reach this package at all - rules 3 and 26.

    Read the asymmetry here carefully, because it is the load-bearing decision
    in this module.

    **A gate takes effect only when it is affirmatively declared.** A package
    declared as meant for an institutional consumer is out of scope under rule
    3(c), and nothing is checked against it. A package where nobody said either
    way is **still evaluated**, with the uncertainty recorded on every finding.

    The alternative - treating an unanswered gate as UNDETERMINED and refusing
    to evaluate - is the more literal reading, and it is wrong here. Nothing is
    declared by default, so it would turn every existing submission into "we
    cannot tell you anything", which is not a more honest answer than the
    findings plus a stated caveat. It would also make the system useless for
    the ordinary retail package that is the overwhelming majority of its input.

    So the caveat is carried rather than the evaluation refused, and
    `engine._SCOPE_CAVEAT` states it on every finding: an undeclared package
    may have been checked against rules that do not govern it. Declaring the
    facts is what removes the caveat, and that is the incentive this design
    intends.
    """
    from apps.rules.models import RuleRequirement

    gates = (
        RuleRequirement.objects.filter(
            clause__in=SCOPE_GATE_CLAUSES, is_active=True
        )
        .prefetch_related("applicability_links__condition")
        .order_by("clause")
    )

    for gate in gates:
        links = list(gate.applicability_links.all())
        by_mode: dict[str, list[RequirementApplicability]] = {}
        for link in links:
            by_mode.setdefault(link.mode, []).append(link)

        Mode = RequirementApplicability.Mode

        # A proviso that withholds the exemption is checked first: tobacco is
        # not excused by rule 26(a) however small the package, and a medical
        # device declared as a drug is not excused by rule 26(c).
        withheld = _first_holding(
            by_mode.get(Mode.WITHHOLDS_EXEMPTION, []), declarations
        )
        if withheld is not None:
            continue

        held = _first_holding(by_mode.get(Mode.SCOPE_GATE, []), declarations)
        if held is not None:
            return ApplicabilityDecision(
                applicability=Applicability.DOES_NOT_APPLY,
                reasons=[
                    f"This package is outside the scope of rule {gate.clause}: "
                    f"'{held.condition.name}' was declared for it. "
                    f"{held.note}".strip()
                ],
            )

    return ApplicabilityDecision(
        applicability=Applicability.APPLIES,
        reasons=[
            "No scope gate under rule 3 or rule 26 was declared for this "
            "package, so the Rules were treated as applying to it."
        ],
    )


def decide(requirement, declarations: DeclarationSet) -> ApplicabilityDecision:
    """Decide whether `requirement` governs the package `declarations` describes.

    `requirement` is a `RuleRequirement`, or None for an executable rule that
    has not been mapped to a clause. An unmapped rule applies: it carries its
    own category targeting, and refusing to evaluate it would silently disable
    every rule written before the framework existed.

    The four link modes are combined in a fixed order, and the order matters:

    1. **SCOPE_GATE, cancelled by WITHHOLDS_EXEMPTION.** A gate that holds takes
       the package out of the Rules entirely, so it is checked first and nothing
       after it can put the package back in scope. Rule 26(a) exempts a ten-gram
       package; the tobacco proviso withholds that exemption, so tobacco is
       checked first and the gate never fires.
    2. **EXEMPTS.** The clause does not apply to this package - food articles
       under Explanation III to rule 6(1)(a), bidi under proviso (C).
    3. **REQUIRES.** The clause applies only to packages of this kind - rule
       6(1)(aa) binds imported products only.

    At each step an UNKNOWN answer stops the decision and returns UNDETERMINED,
    naming what was not established. It never falls through to a later step,
    because a later step answering "applies" would be asserting the earlier
    question was settled.
    """
    if requirement is None:
        return ApplicabilityDecision(
            applicability=Applicability.APPLIES,
            reasons=[
                "This rule is not mapped to a clause of the Rules, so no "
                "applicability conditions were consulted."
            ],
        )

    links = list(requirement.applicability_links.all())
    if not links:
        return ApplicabilityDecision(
            applicability=Applicability.APPLIES,
            reasons=[
                f"Clause {requirement.clause} carries no applicability "
                f"conditions, so it applies to every package in scope."
            ],
        )

    by_mode: dict[str, list[RequirementApplicability]] = {}
    for link in links:
        by_mode.setdefault(link.mode, []).append(link)

    Mode = RequirementApplicability.Mode

    # --- 1. scope gates, and the provisos that cancel them ------------------
    gates = by_mode.get(Mode.SCOPE_GATE, [])
    if gates:
        withheld = _first_holding(by_mode.get(Mode.WITHHOLDS_EXEMPTION, []), declarations)
        if withheld is not None:
            # A proviso cancels the exemption. The Rules continue to apply, and
            # the gates below are not consulted at all.
            return ApplicabilityDecision(
                applicability=Applicability.APPLIES,
                reasons=[
                    f"An exemption under clause {requirement.clause} was "
                    f"withheld because '{withheld.condition.name}' was declared, "
                    f"so the Rules continue to apply. {withheld.note}".strip()
                ],
            )
        unresolved = _unresolved(
            by_mode.get(Mode.WITHHOLDS_EXEMPTION, []), declarations
        )
        if unresolved:
            return _undetermined(requirement, unresolved, "an exemption proviso")

        gate = _first_holding(gates, declarations)
        if gate is not None:
            return ApplicabilityDecision(
                applicability=Applicability.DOES_NOT_APPLY,
                reasons=[
                    f"Out of scope under clause {requirement.clause}: "
                    f"'{gate.condition.name}' was declared for this package. "
                    f"{gate.note}".strip()
                ],
            )
        unresolved = _unresolved(gates, declarations)
        if unresolved:
            return _undetermined(requirement, unresolved, "a scope gate")

    # --- 2. exemptions ------------------------------------------------------
    exemptions = by_mode.get(Mode.EXEMPTS, [])
    exempt = _first_holding(exemptions, declarations)
    if exempt is not None:
        return ApplicabilityDecision(
            applicability=Applicability.DOES_NOT_APPLY,
            reasons=[
                f"Clause {requirement.clause} does not apply: "
                f"'{exempt.condition.name}' was declared for this package. "
                f"{exempt.note}".strip()
            ],
        )
    unresolved = _unresolved(exemptions, declarations)
    if unresolved:
        return _undetermined(requirement, unresolved, "an exemption")

    # --- 3. triggers --------------------------------------------------------
    triggers = by_mode.get(Mode.REQUIRES, [])
    if triggers:
        holding = _first_holding(triggers, declarations)
        if holding is not None:
            return ApplicabilityDecision(
                applicability=Applicability.APPLIES,
                reasons=[
                    f"Clause {requirement.clause} applies: "
                    f"'{holding.condition.name}' was declared for this package."
                ],
            )
        unresolved = _unresolved(triggers, declarations)
        if unresolved:
            return _undetermined(requirement, unresolved, "a trigger condition")
        # Every trigger was answered NO. The clause binds only packages of a
        # kind this one is not.
        names = ", ".join(sorted(link.condition.name for link in triggers))
        return ApplicabilityDecision(
            applicability=Applicability.DOES_NOT_APPLY,
            reasons=[
                f"Clause {requirement.clause} applies only to: {names}. None "
                f"was declared for this package."
            ],
        )

    return ApplicabilityDecision(
        applicability=Applicability.APPLIES,
        reasons=[
            f"No exemption or scope gate recorded against clause "
            f"{requirement.clause} was declared for this package."
        ],
    )


def _first_holding(
    links: list[RequirementApplicability], declarations: DeclarationSet
) -> RequirementApplicability | None:
    """The first link whose condition was declared YES, if any."""
    for link in links:
        if declarations.answer(link.condition) == YES:
            return link
    return None


def _unresolved(
    links: list[RequirementApplicability], declarations: DeclarationSet
) -> list[RequirementApplicability]:
    """Links whose condition was not established either way."""
    return [
        link for link in links if declarations.answer(link.condition) == UNKNOWN
    ]


def _undetermined(
    requirement, unresolved: list[RequirementApplicability], what: str
) -> ApplicabilityDecision:
    names = sorted(link.condition.name for link in unresolved)
    codes = sorted(link.condition.code for link in unresolved)
    return ApplicabilityDecision(
        applicability=Applicability.UNDETERMINED,
        reasons=[
            f"Whether clause {requirement.clause} applies could not be "
            f"determined: {what} turns on {', '.join(names)}, which "
            f"{'was' if len(names) == 1 else 'were'} not established for this "
            f"package. No conclusion has been drawn about this requirement."
        ],
        unresolved=codes,
    )
