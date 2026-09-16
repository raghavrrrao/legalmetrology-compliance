"""The categories a product classifier may answer with, and why these ones.

This is NOT an arbitrary label set chosen because it was convenient to train
on. Every code here is tied to something the rest of the system already
recognises, so a classification can be consumed downstream without a
translation table that would drift:

**Categories are `ProductCategory` codes.** `packaged-food` and
`packaged-non-food` are the two sub-groupings `seed_categories` creates under
`packaged-commodity`, and they are already part of a reviewed data contract:
every shipped rule file names one of them, and the applicability framework's
one category-determined condition (`food-article`) is answered from
`packaged-food`. A classifier that speaks those codes can, in a later step
and once a person has confirmed the suggestion, be recorded as
`Product.category` without translation. `unknown` is the third value and is
not a category at all - it is the classifier declining to choose.

**Subcategories reuse applicability-condition codes wherever one exists.**
`rules/framework/applicability_conditions.json` defines `user_declared`
conditions - `cosmetics-and-toiletries`, `tobacco-product`, `medical-device`,
`alcoholic-beverage`, `electronic-product` - that the framework notes have "no
commodity taxonomy entry". A subcategory carrying the same code is that
taxonomy entry, and a future step can turn a confident subcategory into a
suggested declaration for exactly that condition, with a person confirming it.
The remaining subcategories (`general-food`, `health-supplement`,
`cleaning-product`, `other-non-food`) are internal groupings with no condition
behind them; they exist because the labels the project has actually
photographed fall into them, and because a food classifier that cannot tell a
supplement from a biscuit is not answering the question a reviewer asks.

**What this vocabulary is not.** It is not a legal taxonomy. Nothing here
asserts that "health supplement" is a category under the Legal Metrology
(Packaged Commodities) Rules, 2011, that a `medical-device` classification
makes rule 26(c) apply, or that any declaration is required for anything in
it. A subcategory sharing a condition's code does not answer the condition -
it is a *suggestion* to be confirmed, and until that confirmation the
condition stays UNKNOWN exactly as it does today. See
`docs/ml/product-classification.md`.

**Defined is not trained.** The shipped model knows only the subcategories the
seed dataset contains. A code being listed here means the classifier is
*allowed* to answer with it, not that it can. The set of classes a model can
produce is read from its artifact (`TfidfLinearModel.classes`), never from
this file.
"""

from __future__ import annotations

from dataclasses import dataclass

from labelextract.contracts import UNKNOWN_CATEGORY

#: Bump when a code is added, removed or re-parented. Recorded in every
#: dataset and artifact so a model trained against one vocabulary is never
#: silently read against another.
TAXONOMY_VERSION = "1"

#: The two `ProductCategory` codes below `packaged-commodity`, verbatim.
PACKAGED_FOOD = "packaged-food"
PACKAGED_NON_FOOD = "packaged-non-food"

#: Re-exported so callers reach every vocabulary word through one module.
UNKNOWN = UNKNOWN_CATEGORY

CATEGORIES: tuple[str, ...] = (PACKAGED_FOOD, PACKAGED_NON_FOOD)


@dataclass(frozen=True)
class Subcategory:
    """One narrower grouping within a category."""

    code: str
    category: str
    name: str
    #: The `ApplicabilityCondition.code` this subcategory corresponds to, when
    #: it is one. None for an internal grouping. A non-None value means a
    #: confident prediction *could* be offered to a person as a suggested
    #: answer to that condition - never recorded as one automatically.
    applicability_condition: str | None
    description: str


SUBCATEGORIES: tuple[Subcategory, ...] = (
    Subcategory(
        code="general-food",
        category=PACKAGED_FOOD,
        name="General food",
        applicability_condition=None,
        description=(
            "Ordinary packaged food: staples, snacks, dairy, spices, "
            "confectionery. The catch-all within packaged-food."
        ),
    ),
    Subcategory(
        code="health-supplement",
        category=PACKAGED_FOOD,
        name="Health supplement / nutraceutical",
        applicability_condition=None,
        description=(
            "Dietary and health supplements sold as food under an FSSAI "
            "licence: tablets, capsules, powders and effervescents carrying "
            "nutritional information, a serving size and consumption "
            "directions. A food for the purposes of this taxonomy; not a "
            "drug, which this system cannot identify and does not attempt to."
        ),
    ),
    Subcategory(
        code="alcoholic-beverage",
        category=PACKAGED_FOOD,
        name="Alcoholic beverage",
        applicability_condition="alcoholic-beverage",
        description=(
            "Corresponds to the applicability condition of the same code. "
            "Placed under packaged-food for the classifier's grouping only, "
            "because such labels read like food labels (ingredients, FSSAI "
            "licence). Whether an alcoholic beverage is a 'food article' "
            "within the meaning of the Rules is a legal question this "
            "taxonomy does not answer, and the placement decides nothing "
            "about applicability. The shipped model has no training example."
        ),
    ),
    Subcategory(
        code="cosmetics-and-toiletries",
        category=PACKAGED_NON_FOOD,
        name="Cosmetics and toiletries",
        applicability_condition="cosmetics-and-toiletries",
        description=(
            "Soaps, shampoos, toothpastes, creams and other cosmetics and "
            "toiletries. Corresponds to the applicability condition of the "
            "same code, which the framework records as sitting inside "
            "packaged-non-food with no narrower category - this is that "
            "narrower category."
        ),
    ),
    Subcategory(
        code="cleaning-product",
        category=PACKAGED_NON_FOOD,
        name="Cleaning and household chemical product",
        applicability_condition=None,
        description=(
            "Detergents, cleaners, disinfectants, sprays and aerosols for "
            "household or equipment use. An internal grouping."
        ),
    ),
    Subcategory(
        code="medical-device",
        category=PACKAGED_NON_FOOD,
        name="Medical device",
        applicability_condition="medical-device",
        description=(
            "Corresponds to the applicability condition of the same code. "
            "Listed so the vocabulary can express it; the shipped model has "
            "no training example of one."
        ),
    ),
    Subcategory(
        code="tobacco-product",
        category=PACKAGED_NON_FOOD,
        name="Tobacco or tobacco product",
        applicability_condition="tobacco-product",
        description=(
            "Corresponds to the applicability condition of the same code. "
            "Listed so the vocabulary can express it; the shipped model has "
            "no training example of one."
        ),
    ),
    Subcategory(
        code="electronic-product",
        category=PACKAGED_NON_FOOD,
        name="Electronic product",
        applicability_condition="electronic-product",
        description=(
            "Corresponds to the applicability condition of the same code, "
            "which the framework records as vocabulary only. The shipped "
            "model has no training example of one."
        ),
    ),
    Subcategory(
        code="other-non-food",
        category=PACKAGED_NON_FOOD,
        name="Other non-food",
        applicability_condition=None,
        description="The catch-all within packaged-non-food.",
    ),
)

SUBCATEGORY_BY_CODE: dict[str, Subcategory] = {
    item.code: item for item in SUBCATEGORIES
}


def category_for(subcategory_code: str) -> str:
    """The category a subcategory belongs to.

    Raises:
        KeyError: the code is not in the vocabulary. A model artifact naming a
            class this file does not know is a version mismatch, and reading
            it anyway would attach a prediction to nothing.
    """
    return SUBCATEGORY_BY_CODE[subcategory_code].category


def subcategories_of(category: str) -> tuple[str, ...]:
    """Every subcategory code under `category`, in declaration order."""
    return tuple(
        item.code for item in SUBCATEGORIES if item.category == category
    )


def is_category(code: str) -> bool:
    return code in CATEGORIES


def is_subcategory(code: str) -> bool:
    return code in SUBCATEGORY_BY_CODE
