"""Interpretation of recognised text into label declarations.

Three modules, split by what changes them:

    patterns        what a declaration looks like in print
    normalisation   how a printed value becomes a structured one
    rule_based      the extractor that applies both

`patterns` is edited when someone finds a phrasing we miss. `normalisation` is
edited when a value can be structured more usefully. Keeping them apart means a
new abbreviation for "batch number" is a one-line, reviewable change that
cannot alter how a date is parsed.

Nothing here decides compliance. Locating a declaration says nothing about
whether it was required or whether its value is correct.
"""

from labelextract.fields.normalisation import (
    REASONS_KEY,
    UNCERTAIN_KEY,
    is_uncertain,
    normalise_text,
)
from labelextract.fields.rule_based import (
    NAME,
    SUPPORTED_KEYS,
    UNSUPPORTED_KEYS,
    VERSION,
    RuleBasedFieldExtractor,
)

__all__ = [
    "NAME",
    "REASONS_KEY",
    "SUPPORTED_KEYS",
    "UNCERTAIN_KEY",
    "UNSUPPORTED_KEYS",
    "VERSION",
    "RuleBasedFieldExtractor",
    "is_uncertain",
    "normalise_text",
]
