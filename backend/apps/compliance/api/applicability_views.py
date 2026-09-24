"""`GET /api/v1/compliance/applicability-conditions/` - what a client may declare.

The discovery half of the contract Step 3 opened. `POST /api/v1/compliance/`
accepts `applicability_declarations` keyed by `ApplicabilityCondition.code`, and
until now a client had no way to learn those codes except by reading
`rules/framework/applicability_conditions.json` out of the repository. A form
built that way is a copy of the legal condition catalogue in JavaScript, and it
goes stale the moment a clause is transcribed or a condition is deactivated,
without anything failing.

So this endpoint answers one question: **which facts, if you stated them, would
change what this installation concludes about a package?**

Why it lives beside the compliance endpoints, not under `rules/`
----------------------------------------------------------------
`config/api_v1.py` reserved the `rules/` prefix for `feature/rule-management`
when this was written, and claiming it for one read-only list would have
preempted that branch; the prefix now serves its rule inventory,
`GET /api/v1/rules/`. Either way, what this returns is not the rule set - it is
the *input vocabulary of the POST next to it*, and the two halves of one
request contract are better owned by one app.

What is returned, and why it is a short list rather than all 39
--------------------------------------------------------------
Three filters, each of which removes questions a submitter must not be asked.

1. **Only conditions that bear on something this installation evaluates.** A
   condition is included when it is linked to a scope gate the engine consults
   for every check (rules 3 and 26), or to a clause behind an **active**
   `ComplianceRule`. A condition attached only to a clause nothing evaluates
   cannot change an outcome, and asking about it would be theatre.

2. **Only `USER_DECLARED` conditions.** That determination means precisely "the
   submitter would have to supply this". A `PRODUCT_CATEGORY` condition is
   already answered by `category_code`; a `DATABASE` one needs a register
   nobody holds; and a `NOT_DETERMINABLE` one is answered UNKNOWN by the
   resolver whatever anybody states, which is the safeguard that stops a
   submitter switching off a check by asserting a rule 33 relaxation.

   The POST is deliberately **more** permissive than this list: it accepts any
   determinable condition, so a reviewer correcting a miscategorised submission
   can still state `food-article` directly. This endpoint describes what a
   submission *form* should ask, not the limit of what the API accepts.

3. **Only active rows**, on both the condition and the requirement.

Nothing here is a legal claim and nothing here decides anything. Every field is
copied from the framework loaded out of `rules/framework/`, including the
verbatim clause note explaining what the condition does to that clause. A client
renders them; it must not restate them.
"""

from __future__ import annotations

from django.db.models import Q
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import ProductApplicabilityDeclaration
from apps.compliance.api.permissions import IsAuthenticatedOrDemoPublic
from apps.compliance.services.applicability import SCOPE_GATE_CLAUSES
from apps.rules.models import (
    ApplicabilityCondition,
    ComplianceRule,
    RequirementApplicability,
)

#: How a condition reaches an evaluation. Two values, because the two behave
#: differently and a form that ran them together would mislead:
#:
#: - `rules_scope`: rule 3 or rule 26. Declaring it YES takes the package out of
#:   the Rules, or out of Chapter II, and NOTHING is checked against it.
#: - `clause`: an exemption from, or a trigger for, one clause. It changes one
#:   finding, not the whole result.
SCOPE_KIND_RULES = "rules_scope"
SCOPE_KIND_CLAUSE = "clause"


class ClauseEffectSerializer(serializers.Serializer):
    """One clause this condition bears on, and what it does to it."""

    clause = serializers.CharField()
    #: REQUIRES / EXEMPTS / SCOPE_GATE / WITHHOLDS_EXEMPTION, from the
    #: framework. The client shows the label, not the raw value.
    mode = serializers.CharField()
    mode_display = serializers.CharField()
    #: The framework's own note on this link - the proviso in its own terms.
    #: Never composed here from the mode and the clause number.
    note = serializers.CharField()
    #: The executable rules that would be affected. Empty for a scope gate,
    #: which affects every rule rather than a named one.
    rule_codes = serializers.ListField(child=serializers.CharField())


class ApplicabilityConditionSerializer(serializers.Serializer):
    """A fact a submitter may state about a package.

    `answers` is served rather than assumed so a client's radio group is built
    from the API's vocabulary. UNKNOWN is in it deliberately and must stay a
    distinct choice: it means "somebody was asked and did not know", which the
    engine treats exactly as it treats an absent answer - not as NO.
    """

    code = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    determination = serializers.CharField()
    determination_note = serializers.CharField()
    scope = serializers.CharField()
    answers = serializers.ListField(child=serializers.CharField())
    affects = ClauseEffectSerializer(many=True)


#: Stated on the response rather than left to the client to write. A form that
#: invents its own explanation of what UNKNOWN means will eventually invent a
#: wrong one.
_SEMANTICS = {
    "yes": (
        "The fact holds for this package. The engine applies whatever the "
        "clause says about it - which may take the package out of scope, "
        "excuse it from a declaration, or make a declaration required."
    ),
    "no": (
        "The fact does not hold. The clause is applied as if the exemption or "
        "trigger were absent."
    ),
    "unknown": (
        "Not established. Identical in effect to sending nothing: a clause "
        "whose applicability turns on it is recorded as undetermined and "
        "reaches REVIEW REQUIRED. It is never read as 'no'."
    ),
}


class ApplicabilityConditionListView(APIView):
    """The facts a submitter can state that would change an evaluation.

    Read-only, unpaginated, and small by construction - see the module
    docstring for the three filters that keep it small.

    Permissions match the compliance endpoints beside it. Nothing here is
    user data: it is the loaded legal framework, the same content that ships in
    `rules/framework/` in the repository.

    An empty `conditions` list is a real answer and the client must handle it:
    it means the legal framework has not been loaded, so no declaration could
    affect anything. `framework_loaded` says which, rather than leaving a
    client to infer a deployment fault from an empty array.
    """

    permission_classes = [IsAuthenticatedOrDemoPublic]

    def get(self, request, *args, **kwargs) -> Response:
        links = self._relevant_links()

        by_condition: dict[str, list[RequirementApplicability]] = {}
        for link in links:
            by_condition.setdefault(link.condition.code, []).append(link)

        rule_codes = self._rule_codes_by_requirement()

        conditions = [
            self._describe(links[0].condition, links, rule_codes)
            for links in (
                by_condition[code] for code in sorted(by_condition)
            )
        ]

        return Response(
            {
                "conditions": ApplicabilityConditionSerializer(
                    conditions, many=True
                ).data,
                "answer_semantics": _SEMANTICS,
                # Distinguishes "nothing is declarable" from "the framework was
                # never loaded", which look identical in an empty list.
                "framework_loaded": ApplicabilityCondition.objects.filter(
                    is_active=True
                ).exists(),
            }
        )

    @staticmethod
    def _relevant_links() -> list[RequirementApplicability]:
        """Links that could actually change an outcome in this installation.

        One query. `requirement__compliance_rules` is the reverse of
        `ComplianceRule.rule_requirement`, so the second half of the filter
        reads "this clause has at least one active executable rule behind it".
        """
        return list(
            RequirementApplicability.objects.filter(
                condition__is_active=True,
                condition__determination=(
                    ApplicabilityCondition.Determination.USER_DECLARED
                ),
                requirement__is_active=True,
            )
            .filter(
                # A scope gate is consulted for every check whether or not any
                # rule names it, so it qualifies on its clause alone. Anything
                # else has to have an active executable rule behind its clause,
                # or answering it could not change a thing.
                Q(requirement__clause__in=SCOPE_GATE_CLAUSES)
                | Q(requirement__compliance_rules__is_active=True)
            )
            .select_related("condition", "requirement")
            .order_by("condition__code", "requirement__clause", "mode")
            .distinct()
        )

    @staticmethod
    def _rule_codes_by_requirement() -> dict[int, list[str]]:
        """Active executable rules per clause, so a client can name them.

        One query for the whole response rather than one per link.
        """
        mapping: dict[int, list[str]] = {}
        rows = ComplianceRule.objects.filter(
            is_active=True, rule_requirement__isnull=False
        ).values_list("rule_requirement_id", "code")
        for requirement_id, code in rows:
            mapping.setdefault(requirement_id, []).append(code)
        for codes in mapping.values():
            codes.sort()
        return mapping

    @staticmethod
    def _describe(
        condition: ApplicabilityCondition,
        links: list[RequirementApplicability],
        rule_codes: dict[int, list[str]],
    ) -> dict:
        modes = dict(RequirementApplicability.Mode.choices)
        affects = [
            {
                "clause": link.requirement.clause,
                "mode": link.mode,
                "mode_display": modes.get(link.mode, link.mode),
                "note": link.note,
                "rule_codes": rule_codes.get(link.requirement_id, []),
            }
            for link in links
        ]
        scope = (
            SCOPE_KIND_RULES
            if any(
                link.requirement.clause in SCOPE_GATE_CLAUSES for link in links
            )
            else SCOPE_KIND_CLAUSE
        )
        return {
            "code": condition.code,
            "name": condition.name,
            "description": condition.description,
            "determination": condition.determination,
            "determination_note": condition.determination_note,
            "scope": scope,
            "answers": [
                choice.value for choice in ProductApplicabilityDeclaration.Answer
            ],
            "affects": affects,
        }
