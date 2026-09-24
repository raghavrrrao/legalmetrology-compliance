"""The rule inventory's response shape - one row per `ComplianceRule`.

Read-only. Nothing here accepts input, so nothing here validates any.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.rules.models import ComplianceRule


class ComplianceRuleInventorySerializer(serializers.ModelSerializer):
    """One executable rule, as the inventory lists it.

    Enough to name a rule, say where it comes from, and say whether this
    installation evaluates it - and nothing a client could evaluate a package
    with. The fields are listed one by one rather than drawn from the model, so
    a column added to `ComplianceRule` later does not appear on a public
    response because nobody thought to leave it out.

        code                    the stable identifier a finding cites
        title                   the rule's own name for the requirement
        legal_reference         the provision as the source numbers it; ""
                                when not established - never guessed
        clause                  the linked `RuleRequirement.clause`, or null
        source_status           verified / unverified - only a verified rule
                                can report a package as non-compliant
        is_active               whether the engine considers the rule at all
        effective_from/_to      the rule's own effective window, or null

    Left out, and why:

    - `check_type`, `parameters` - validator configuration, including values
      a client could mistake for legal thresholds. A client that held them
      could re-implement a check; the compliance engine is the only thing that
      applies them.
    - `applies_to_categories`, `requires_applicability_conditions` - how
      applicability is decided. Applicability is resolved per package by the
      engine, and serving its inputs would invite a client to resolve it too.
    - `source_note` - who verified the rule and against what. An audit note for
      reviewers of the rule files, not display content.
    - `requirement`, `severity` - not part of the agreed contract. `severity`
      carries no legal weight (`rules/SCHEMA.md`), and a rule's full wording
      reaches a client on the findings of an actual evaluation.

    `clause` is `rule.rule_requirement.clause` - the same link the engine
    snapshots onto every finding - and `null` when the rule is not mapped to a
    clause of the Rules. It is never derived from `legal_reference`: a clause
    read out of prose would be a guess presented as a mapping.
    """

    clause = serializers.SerializerMethodField()

    class Meta:
        model = ComplianceRule
        fields = [
            "code",
            "title",
            "legal_reference",
            "clause",
            "source_status",
            "is_active",
            "effective_from",
            "effective_to",
        ]
        read_only_fields = fields

    def get_clause(self, rule: ComplianceRule) -> str | None:
        requirement = rule.rule_requirement
        return requirement.clause if requirement is not None else None
