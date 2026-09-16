"""Label phrases that indicate what kind of product a package is.

**These do not classify anything.** The classifier is the trained model in
`model.py`; the model never reads this file. Signals exist for three narrower
purposes:

- *Explainability.* A classification that says only `packaged-food 0.81` is
  unfalsifiable. One that adds "the text mentions 'nutritional information',
  'ingredients' and 'fssai'" is something a reviewer can check against the
  photograph in seconds.
- *Tests.* A regression test can assert that a known label surfaces the
  signals a person would expect, independently of what the model decides.
- *Reading the dataset.* Matching signals across the seed dataset is how the
  category distribution was sanity-checked against the labels.

Each signal names the grouping it is *typically* associated with. That is a
display hint, not a rule: an ingredient list appears on a soap as readily as
on a biscuit, and a warning to keep out of reach of children appears on a
supplement as readily as on a cleaner. The model weighs the whole text;
these tell a reviewer what it might have been looking at.

Patterns are applied to `preprocess_text` output, so they are written in
lowercase and against single-spaced text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from labelextract.classification.taxonomy import PACKAGED_FOOD, PACKAGED_NON_FOOD


@dataclass(frozen=True)
class Signal:
    """One recognisable phrase and what it usually indicates."""

    label: str
    #: A category or subcategory code this phrase is typically found with.
    indicative_of: str
    pattern: re.Pattern

    def matches(self, cleaned: str) -> bool:
        return self.pattern.search(cleaned) is not None


def _signal(label: str, indicative_of: str, pattern: str) -> Signal:
    return Signal(label, indicative_of, re.compile(pattern))


SIGNALS: tuple[Signal, ...] = (
    # --- food ---------------------------------------------------------------
    _signal(
        "nutritional information", PACKAGED_FOOD,
        r"\bnutrition(?:al)?\s+(?:information|info|facts?|value)\b",
    ),
    _signal("ingredients", PACKAGED_FOOD, r"\bingredients?\b"),
    _signal("serving size", PACKAGED_FOOD, r"\bserving\s+size\b|\bper\s+serving\b|\bservings?\s+per\b"),
    _signal("energy / kcal", PACKAGED_FOOD, r"\benergy\b|\bkcal\b|\bcalories\b"),
    _signal("protein", PACKAGED_FOOD, r"\bprotein\b"),
    _signal("carbohydrate", PACKAGED_FOOD, r"\bcarbohydrates?\b"),
    _signal("fssai", PACKAGED_FOOD, r"\bfssai\b"),
    _signal("vegetarian mark", PACKAGED_FOOD, r"\b(?:non[\s-]?)?vegetarian\b|\bveg\b"),
    _signal("allergen advice", PACKAGED_FOOD, r"\ballergens?\b|\bcontains\s+(?:milk|nuts|soy|gluten|wheat)\b"),
    _signal("food additive code", PACKAGED_FOOD, r"\bins\s+\d{3}\b"),
    _signal("dairy", PACKAGED_FOOD, r"\bmilk\b|\bdairy\b|\bpasteuri[sz]ed\b|\bcurd\b|\bghee\b|\bpaneer\b"),
    _signal("staple / spice", PACKAGED_FOOD, r"\bflour\b|\batta\b|\brice\b|\bdal\b|\bmasala\b|\bspices?\b|\bsugar\b|\bsalt\b"),
    _signal("use by / best before", PACKAGED_FOOD, r"\buse\s+by\b|\bbest\s+before\b|\bexpiry\b|\bexp\.?\s*date\b"),
    # --- health supplement --------------------------------------------------
    _signal("supplement", "health-supplement", r"\b(?:dietary|health|nutritional|food|nutraceutical)\s+supplement\b|\bsupplements?\b"),
    _signal("consumption directions", "health-supplement", r"\bdirections?\s+(?:for|of)\s+use\b|\bdosage\b|\bhow\s+to\s+(?:use|consume)\b|\bconsume\b|\bdrop\s*,?\s*fizz\b"),
    _signal("effervescent / tablets / capsules", "health-supplement", r"\beffervescent\b|\btablets?\b|\bcapsules?\b|\bgummies\b"),
    _signal("not for medicinal use", "health-supplement", r"\bnot\s+(?:for|intended\s+for)\s+medicinal\s+use\b|\bnot\s+intended\s+to\s+(?:diagnose|treat|cure)\b"),
    _signal("vitamin / mineral", "health-supplement", r"\bvitamins?\b|\bzinc\b|\bcalcium\b|\biron\b|\bbiotin\b|\bcurcumin\b|\bcollagen\b"),
    # --- cosmetics and toiletries -------------------------------------------
    _signal("soap / bathing bar", "cosmetics-and-toiletries", r"\bsoap\b|\bbathing\s+bar\b|\bbeauty\s+bar\b|\bbody\s+wash\b"),
    _signal("shampoo / conditioner", "cosmetics-and-toiletries", r"\bshampoo\b|\bconditioner\b"),
    _signal("toothpaste", "cosmetics-and-toiletries", r"\btooth\s*paste\b|\bfluoride\b"),
    _signal("cream / lotion / serum", "cosmetics-and-toiletries", r"\bcream\b|\blotion\b|\bmoisturi[sz](?:er|ing)\b|\bserum\b"),
    _signal("skin / hair care", "cosmetics-and-toiletries", r"\bskin\b|\bhair\b|\bdermatologic(?:al|ally)\b"),
    _signal("for external use only", "cosmetics-and-toiletries", r"\bfor\s+external\s+use\s+only\b"),
    # --- cleaning and household chemicals -----------------------------------
    _signal("detergent / cleaner", "cleaning-product", r"\bdetergents?\b|\bcleaners?\b|\bcleaning\b|\bdisinfectant\b|\bstain\b|\bfloor\b|\bdish\s*wash\b"),
    _signal("spray / aerosol", "cleaning-product", r"\bspray\b|\baerosol\b|\bpressuri[sz]ed\b"),
    _signal("flammable / chemical warning", "cleaning-product", r"\bflammable\b|\bkeep\s+away\s+from\s+heat\b|\bdo\s+not\s+pierce\b|\bcorrosive\b|\birritation\b"),
    _signal("antimicrobial / antibacterial", "cleaning-product", r"\banti[\s-]?microbial\b|\banti[\s-]?bacterial\b|\bbacteria\b"),
    # --- medical device -----------------------------------------------------
    _signal("medical device", "medical-device", r"\bmedical\s+device\b|\bdevice\b"),
    _signal("sterile / single use", "medical-device", r"\bsterile\b|\bsingle\s+use\b|\bdo\s+not\s+reuse\b"),
    _signal("cdsco / medical licence", "medical-device", r"\bcdsco\b|\bmd\s*-?\s*\d+\b"),
    # --- tobacco ------------------------------------------------------------
    _signal("tobacco", "tobacco-product", r"\btobacco\b|\bcigarettes?\b|\bbidi\b|\bkhaini\b|\bgutka\b"),
    _signal("statutory tobacco warning", "tobacco-product", r"\bsmoking\s+kills\b|\bcauses\s+cancer\b|\binjurious\s+to\s+health\b"),
    # --- generic non-food ---------------------------------------------------
    _signal("keep out of reach of children", PACKAGED_NON_FOOD, r"\bkeep\s+(?:out\s+of\s+)?reach\s+of\s+children\b|\bout\s+of\s+reach\b"),
)


def matched_signals(cleaned: str) -> tuple[Signal, ...]:
    """Every signal whose pattern occurs in the cleaned text, in table order."""
    if not cleaned:
        return ()
    return tuple(signal for signal in SIGNALS if signal.matches(cleaned))


def describe(signal: Signal) -> str:
    """The evidence string a matched signal contributes to a classification."""
    return f"signal: {signal.label} (typical of {signal.indicative_of})"
