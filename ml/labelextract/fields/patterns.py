"""Compiled patterns for locating declarations in recognised label text.

Kept in their own module so the *vocabulary of what a label looks like* can be
reviewed - and argued with - separately from the extraction logic that applies
it. Adding a phrasing here is a small, reviewable diff; it never changes what
the compliance engine requires.

Why patterns rather than a model
--------------------------------
A regex is deterministic, inspectable and testable, and when it is wrong it is
wrong in a way a person can read and fix. That is worth more here than recall.
A learned tagger would need annotated Indian label data we do not have, and its
mistakes would be unexplainable in a tool whose output is meant to be evidence.
This layer is a first pass, deliberately, and it says so.

Precision over recall, on purpose
---------------------------------
Most declarations are matched **only when an anchoring keyword is present**. A
bare `500 g` is not reported as a net quantity, because that string also
appears in the nutrition panel next to `per 100 g`. `docs/evaluation-strategy.md`
sets out why that trade is the right way round for this system: a declaration
we wrongly report as *present* hides a real violation, which is worse than one
we fail to find.

Scope: English only. Devanagari and other Indian scripts are recognised by the
OCR layer when the language data is installed, but nothing here matches them.
See the limitations section of `ml/README.md`.
"""

from __future__ import annotations

import re

_I = re.IGNORECASE

# --- shared fragments -------------------------------------------------------

#: A printed number: Indian (1,00,000) or international (1,000,000) grouping,
#: with up to three decimal places.
_NUMBER = r"\d{1,3}(?:,\d{2,3})*(?:\.\d{1,3})?|\d+(?:\.\d{1,3})?"

#: Units of net quantity as they are actually abbreviated on packaging. Ordered
#: longest-first inside each family so `kg` is not matched as `g`, and `ltr` is
#: not matched as `l`.
_UNITS = (
    r"kgs?|kilograms?|gms?|grams?|gr|mg|mcg|ug|g"
    r"|millilitres?|milliliters?|mls?|litres?|liters?|ltrs?|lt|cc|cl|dl|l"
    r"|pieces?|pcs?|units?|nos?|n|u"
)

#: How rupees are written. `Rs` with or without stops, the symbol, the ISO code.
_CURRENCY = r"₹|Rs\.?|INR|R\.?\s?s\.?"

_MONTHS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?"
    r"|aug(?:ust)?|sep(?:t)?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)


# --- net quantity -----------------------------------------------------------

#: The anchor that makes a number a *declared* net quantity rather than any
#: other number on the panel.
NET_QUANTITY_KEYWORD = re.compile(
    r"\bnet\s*(?:qty|quantity|wt|weight|content|contents|vol|volume)\b"
    r"|\bnet\s*(?:qty|wt|vol)\.?\s*[:\-]"
    r"|\bquantity\b",
    _I,
)

#: The part of `NET_QUANTITY_KEYWORD` that is strong enough to stand alone.
#:
#: `NET_QUANTITY_KEYWORD` ends in a bare `\bquantity\b`, and that is correct
#: where it is used: a *number and a unit* have to be on the same line before
#: anything is emitted, so `Quantity: 500 g` is read and prose is harmless.
#:
#: It is not correct as evidence *by itself*. "quantity" is an ordinary English
#: word - `the quantity supplied may vary`, `quantity surveyor` - so a line
#: carrying the word and nothing else is not a declaration, and reporting one
#: as a net quantity nobody could read would be a claim about a label that
#: never made it.
#:
#: Used only where a keyword with no value has to be reported as an
#: observation. Every string this matches is also matched by
#: `NET_QUANTITY_KEYWORD`; a test asserts that, so the two cannot drift into
#: disagreeing about what a net-quantity keyword is.
NET_QUANTITY_ANCHOR = re.compile(
    r"\bnet\s*(?:qty|quantity|wt|weight|content|contents|vol|volume)\b"
    r"|\bnet\s*(?:qty|wt|vol)\.?\s*[:\-]",
    _I,
)

#: Lines that contain a quantity which is definitely *not* the net quantity.
#: The nutrition panel is the dominant source of false positives on a real
#: label - it is full of `per 100 g` and `2.5 g` - and this is what keeps them
#: out.
NON_DECLARATION_CONTEXT = re.compile(
    r"\bper\s*(?:\d|serve|serving|portion|pack\b)"
    r"|\bnutrition|\bnutritional\b|\bingredient|\bserving"
    r"|\benergy\b|\bprotein\b|\bcarbohydrate|\bsugars?\b|\bsodium\b"
    r"|\bcholesterol\b|\bkcal\b|\bkj\b|\bfat\b|\bfibre\b|\bfiber\b|\brda\b",
    _I,
)

QUANTITY = re.compile(
    rf"(?:(?P<pack>\d{{1,3}})\s*[x×]\s*)?"
    rf"(?P<value>{_NUMBER})\s*"
    rf"(?P<unit>{_UNITS})\b\.?",
    _I,
)


# --- retail sale price ------------------------------------------------------

MRP_KEYWORD = re.compile(
    r"\bm\.?\s?r\.?\s?p\.?(?![a-z])"
    r"|\bmaximum\s+retail\s+price\b"
    r"|\bretail\s+sale\s+price\b"
    r"|\bmax\.?\s*retail\s*price\b",
    _I,
)

#: A number introduced or followed by a currency token. Two alternatives rather
#: than one optional side, so the amount group is unambiguous either way.
PRICE = re.compile(
    rf"(?:{_CURRENCY})\s*(?P<amount>{_NUMBER})"
    rf"|(?P<amount_before>{_NUMBER})\s*(?:{_CURRENCY})(?![a-z])",
    _I,
)

#: A bare number, used only after an MRP keyword when no currency token was
#: read - OCR loses the ₹ glyph often enough that requiring it would cost real
#: recall, and the keyword is already doing the anchoring work.
#:
#: A number carrying a unit is skipped. `MRP for 500 g pack: 250` prints the
#: net quantity before the price, and taking the first number there would
#: record 500 as the retail price. The digit guards on either side stop the
#: unit lookahead from being dodged by matching only part of the number: `500 g`
#: must not degrade into `50` followed by `0 g`.
BARE_AMOUNT = re.compile(
    rf"(?<![\d.,])(?P<amount>{_NUMBER})(?!\d)(?!\s*(?:{_UNITS})\b)",
    _I,
)

TAX_INCLUSIVE = re.compile(
    r"incl(?:usive|\.)?\s*(?:of)?\s*all\s*tax", _I
)
TAX_EXCLUSIVE = re.compile(r"excl(?:usive|\.)?\s*(?:of)?\s*all\s*tax", _I)

#: Phrases that make a price line something other than the retail sale price.
#:
#: Deliberately still matching only the full phrasings, not the `USP`
#: abbreviation. Widening it to the abbreviation - or to the `/kg` rate form -
#: was tried and reverted: it suppressed `MRP Rs.200/kg` entirely, which is a
#: retail sale price written as a rate and is the one declaration this project
#: can least afford to drop. The narrower case it was meant to fix is handled
#: in `rule_based._retail_sale_price`, where it can be applied only to the
#: speculative no-keyword branch.
NON_MRP_CONTEXT = re.compile(
    r"\bunit\s*(?:sale\s*)?price\b|\bper\s*(?:kg|g|ml|l|litre|liter|piece|pc)\b",
    _I,
)


# --- unit sale price --------------------------------------------------------

#: The phrasings that *name* the declaration and cannot mean anything else on a
#: package. Used as the unread-declaration anchor, where a match is a positive
#: claim that the label carries this declaration.
UNIT_SALE_PRICE_ANCHOR = re.compile(r"\bunit\s*sale\s*price\b|\bunit\s*price\b", _I)

#: `UNIT_SALE_PRICE_ANCHOR` plus the abbreviation labels actually print.
#:
#: `usp` is deliberately in the keyword and deliberately **not** in the anchor.
#: On an Indian supplement or pharma label `USP` is at least as likely to mean
#: *United States Pharmacopeia* as *unit sale price*, and the frozen evaluation
#: set contains an effervescent-tablet tube where that reading is live. The
#: split contains the damage: a keyword only ever contributes to a field when a
#: per-unit price is read on the same line, whereas the anchor alone would let
#: a pharmacopoeia marker be reported as an unread price declaration - a claim
#: about the label that nothing on it supports.
#:
#: Every string the anchor matches is also matched here; a test asserts it, so
#: the two cannot drift into disagreeing about what the keyword is.
UNIT_SALE_PRICE_KEYWORD = re.compile(
    r"\bunit\s*sale\s*price\b|\bunit\s*price\b|\busp\b", _I
)

#: An amount attached to *one* unit of measure: rule 6(11)'s own prescribed form
#: ("Rs. _ per g") and the abbreviations that stand in for it on real packaging.
#:
#:     UNIT SALE PRICE : Rs.2.91 PER GRAM
#:     Rs.0.93/g
#:     Rs. 200 per kg
#:     2.91 Rs. per gram
#:
#: The currency token is optional and captured, because whether one was read is
#: what decides how far this pattern may be trusted on its own - see
#: `rule_based._unit_sale_price`.
#:
#: A unit must follow the separator immediately, so the nutrition-panel form
#: `per 100 g` cannot match. The written-out `per 1 kg` does not match either,
#: and deliberately is not made to: `NON_DECLARATION_CONTEXT` claims any line
#: containing `per <digit>` before this pattern is ever consulted, and loosening
#: that guard to reach one unattested phrasing would let the whole nutrition
#: panel back in.
#:
#: The leading guard refuses an amount that starts part-way through a printed
#: number. `Rs.12,5 per g` is a decimal comma this project does not resolve by
#: guessing; without the guard the engine would skip the unmatchable `12,` and
#: commit to `5 per g` - a confident reading of a price the label never
#: printed, which is exactly the failure this layer exists to avoid. With it,
#: the line yields nothing.
PER_UNIT_PRICE = re.compile(
    rf"(?<![\d,.])"
    rf"(?:(?P<currency>{_CURRENCY})\s*)?"
    rf"(?P<amount>{_NUMBER})\s*"
    rf"(?:{_CURRENCY})?\s*"
    rf"(?:per\b|/)\s*"
    rf"(?P<unit>{_UNITS})\b\.?",
    _I,
)


# --- dates ------------------------------------------------------------------

#: Keyword -> which date this is. Order matters: `date of packing` must be
#: tried before the looser `pkd`, and `best before` before a bare `before`.
DATE_KEYWORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "date_of_manufacture",
        re.compile(
            r"\bdate\s+of\s+(?:manufacture|mfg|mfr)\b"
            r"|\bmanufactur(?:ed|ing)\s*(?:on|date)?\b"
            r"|\bmfg\.?\s*(?:date|dt|on)?\b"
            r"|\bmfd\.?\s*(?:date|dt|on)?\b",
            _I,
        ),
    ),
    (
        "date_of_packing",
        re.compile(
            r"\bdate\s+of\s+pack(?:ing|ed)?\b"
            r"|\bpacked\s*(?:on|date)?\b"
            r"|\bpkd\.?\s*(?:on|date|dt)?\b"
            r"|\bpacking\s*date\b",
            _I,
        ),
    ),
    (
        "date_of_import",
        re.compile(r"\bdate\s+of\s+import\b|\bimported\s+on\b", _I),
    ),
    (
        "best_before",
        re.compile(
            r"\bbest\s*(?:before|by)\b"
            r"|\buse\s*(?:by|before)\b"
            r"|\bexp(?:iry|ires?|\.)?\s*(?:date|on|dt)?\b"
            r"|\bexpiration\b"
            r"|\bconsume\s*(?:by|before)\b",
            _I,
        ),
    ),
)

#: DD/MM/YYYY and friends. Which component is the day is decided in
#: `normalisation`, not here - both readings are valid patterns.
NUMERIC_DATE = re.compile(
    r"(?<!\d)(?P<first>\d{1,2})\s*[/\-.]\s*(?P<second>\d{1,2})"
    r"\s*[/\-.]\s*(?P<year>\d{4}|\d{2})(?!\d)"
)

#: MM/YYYY - a real and common form for `best before`, and a partial date, not
#: a full one.
MONTH_YEAR_DATE = re.compile(
    r"(?<!\d)(?P<first>\d{1,2})\s*[/\-.]\s*(?P<year>\d{4})(?!\d)"
)

#: 12 Mar 2025, MAR 2025, 12-MAR-25.
NAMED_MONTH_DATE = re.compile(
    rf"(?:(?P<first>\d{{1,2}})\s*[-/ .]\s*)?"
    rf"(?P<month_name>{_MONTHS})\.?\s*[-/ .,]?\s*(?P<year>\d{{4}}|\d{{2}})(?!\d)",
    _I,
)

ISO_DATE = re.compile(
    r"(?<!\d)(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?!\d)"
)

#: "Best before 9 months from the date of packaging" - a shelf life, not a date.
DURATION = re.compile(
    r"(?P<count>\d{1,3})\s*(?P<unit>days?|weeks?|months?|years?)\b", _I
)


# --- batch / lot ------------------------------------------------------------

#: The qualifier a batch keyword may carry - `No.`, `Number`, `Code` - is part
#: of the *keyword*, never part of the value. Saying so explicitly is not
#: redundant with the optional group below it, because that group is optional:
#: on `Batch No. & Use By Date` the engine matched `No.` as the qualifier,
#: found no value after it, backtracked, matched the qualifier as *empty*, and
#: committed to `No` as the batch code.
#:
#: Measured on `our-eval-v0.3-usp-partial`, that one backtrack produced the
#: whole dataset's only fabricated value - `p007_01_back`, a pack printing
#: `Batch No. :` with nothing stamped against it - and one confident wrong
#: reading on `p010_01_back`, whose legend line reads `Batch No. & Use By Date`.
#: Both were emitted `uncertain: False`, which is the worst failure this layer
#: has: `field_presence` passes on them and a reviewer is shown `No` as if it
#: were a production code.
#:
#: The `\b` after each word is what keeps a genuine code that merely *begins*
#: with those letters matching. There is no word boundary between `NO` and `1`,
#: so `Batch: NO123` and `Batch Code: CODE45` are unaffected.
_NOT_A_BATCH_VALUE = r"(?!(?:nos?|number|code)\b)"

BATCH_NUMBER = re.compile(
    r"\b(?:batch|lot|b\.?\s*no|l\.?\s*no|bn)\b\.?\s*"
    r"(?:no\.?|number|code|#)?\s*[:.\-]?\s*"
    rf"{_NOT_A_BATCH_VALUE}"
    r"(?P<value>[A-Za-z0-9][A-Za-z0-9\-/]{1,19})",
    _I,
)

#: The phrasings that *name* a batch declaration and cannot mean anything else
#: on a package, used where a keyword with no readable value has to be reported
#: as an observation (`rule_based._KEYWORD_ANCHORS`).
#:
#: Narrower than `BATCH_NUMBER`'s own keyword alternation, and deliberately:
#: `lot` and `batch` are ordinary English words - "a lot of", "batch cooked" -
#: and an unread observation is a positive claim about what the label says.
#: Requiring the qualifier is what makes the phrase unambiguous. Every string
#: this matches is also matched by `BATCH_NUMBER`'s keyword prefix; a test
#: asserts it, so the two cannot drift into disagreeing.
BATCH_NUMBER_ANCHOR = re.compile(
    r"\b(?:batch|lot)\b\.?\s*(?:nos?\.?|number|code)\b"
    r"|\b(?:b|l)\.?\s*no\b\.?"
    r"|\bbn\b\.?\s*(?:nos?\.?|number|code)\b",
    _I,
)


# --- consumer care contact --------------------------------------------------

CONTACT_KEYWORD = re.compile(
    r"\b(?:consumer|customer)\s*(?:care|complaints?|service|helpline)\b"
    r"|\bhelpline\b|\btoll[\s\-]?free\b"
    r"|\bfor\s+(?:any\s+)?(?:queries|complaints?|feedback|grievances?)\b"
    r"|\bcontact\s*(?:us|no|number)?\b"
    r"|\be-?mail\b",
    _I,
)

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

#: Indian toll-free numbers, the strongest single signal that a line is a
#: consumer-care declaration.
#:
#: Two or three groups after the `1800`, not exactly two. Indian toll-free
#: numbers are printed in several groupings and the label chooses one:
#: `1800 123 4567`, `1800 22 1234`, `1800-10-22-221`, `18001234567`. The
#: two-group form missed the four-group printing entirely - measured on
#: `p003_03_right`, whose panel reads `TOLL FREE: 1800-10-22-221` and which the
#: extractor located as a consumer-care declaration and then reported with no
#: phone number read.
#:
#: The `\b` at the front is what keeps this out of the FSSAI licence numbers
#: that crowd the same panel: `10018022005492` contains `1800` but no word
#: boundary before it, so it cannot match.
TOLL_FREE_PHONE = re.compile(r"\b1[\s\-]?800(?:[\s\-]?\d{2,4}){2,3}\b")

#: A ten-digit Indian mobile number, optionally with the country code.
MOBILE_PHONE = re.compile(r"(?:\+?91[\s\-]?)?\b[6-9]\d{4}[\s\-]?\d{5}\b")


# --- country of origin ------------------------------------------------------

# A country name as it is printed: one to four capitalised words, optionally
# joined by a lowercase connector ("United States of America", "Trinidad and
# Tobago", "Republic of Korea"). ALL CAPS matches too, since labels often use
# it.
#
# The capitalisation requirement is the whole precision mechanism here, and it
# is why these two patterns are NOT compiled with `re.IGNORECASE` - the anchor
# is case-insensitive via an inline group, the value is not. It is what
# separates a declaration from the prose that shares its phrasing:
#
#     "Made in India"                                    -> India
#     "Made in a facility that also processes nuts"      -> no match
#     "Product of India"                                 -> India
#     "Product of the finest wheat grown in Punjab"      -> no match
#     "Origin of ingredients: multiple countries"        -> no match
#
# The cost is a label whose country is printed in lower case, or mangled into
# lower case by OCR, which is not matched at all. That is the safe direction:
# an extracted field makes `field_presence` PASS whether or not it is flagged
# uncertain, so a wrong value here would hide a genuinely missing declaration.
_COUNTRY_WORD = r"[A-Z][A-Za-z'\-]*"
_COUNTRY_CONNECTOR = r"(?:of|and|the|del|de|du|des)"
_COUNTRY_VALUE = (
    rf"{_COUNTRY_WORD}(?:\s+(?:{_COUNTRY_CONNECTOR}\s+)?{_COUNTRY_WORD}){{0,3}}"
)

#: "Country of Origin: India" - the label names the declaration itself. There
#: is nothing else this phrasing means.
COUNTRY_OF_ORIGIN_DECLARED = re.compile(
    r"(?i:\bcountry\s+of\s+origin\b\s*[:\-]?\s*)"
    rf"(?P<value>{_COUNTRY_VALUE})"
)

#: "Made in India", "Product of India" - almost always the country, but the
#: same words also introduce a manufacturing site ("Manufactured in Pune"), a
#: shared-facility allergen warning, and marketing copy. Matches are reported
#: as uncertain for that reason; see `rule_based._country_of_origin`.
COUNTRY_OF_ORIGIN_IMPLIED = re.compile(
    r"(?i:\b(?:made\s+in|product\s+of|produce\s+of|manufactured\s+in"
    r"|origin)\b\s*[:\-]?\s*)"
    rf"(?P<value>{_COUNTRY_VALUE})"
)


# --- names ------------------------------------------------------------------

#: Keyword -> `LabelFieldKey` value. Only the *name* is captured. The address
#: that follows on the next lines is not extracted; see `ml/README.md`.
NAME_DECLARATIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "manufacturer_name",
        re.compile(
            r"\b(?:manufactured|mfd|mfg|mfr)\.?\s*(?:&|and)?\s*"
            r"(?:packed\s*)?by\b\s*[:\-]?\s*(?P<value>.+)",
            _I,
        ),
    ),
    (
        "packer_name",
        re.compile(r"\b(?:packed|pkd|packer)\.?\s*by\b\s*[:\-]?\s*(?P<value>.+)", _I),
    ),
    (
        "importer_name",
        re.compile(r"\bimport(?:ed|er)\.?\s*by\b\s*[:\-]?\s*(?P<value>.+)", _I),
    ),
    (
        "other",
        re.compile(r"\bmarketed\s*by\b\s*[:\-]?\s*(?P<value>.+)", _I),
    ),
)

#: Trailing punctuation to strip from a captured free-text value. Never applied
#: to `raw_value`, which stays exactly as recognised.
TRAILING_PUNCTUATION = " \t.,:;-–—|/\\"
