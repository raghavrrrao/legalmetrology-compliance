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
#:
#: The first branch requires **at least one** comma group, and that `+` is
#: load bearing. It was `*`, which made the branch match any 1-3 digit run -
#: and Python alternation is leftmost-first, not longest-match, so a number
#: with no commas never reached the second branch. `Rs. 1500` matched the first
#: branch as `150` and the trailing `0` was simply left behind:
#:
#:     MRP Rs. 1500      ->  amount 150       (10x understated, and certain)
#:     MRP Rs. 99999999  ->  amount 999
#:
#: `BARE_AMOUNT` never showed this because its `(?!\d)` lookahead forces the
#: engine to backtrack into the second branch; `PRICE` has no such guard, so
#: any four-or-more-digit price written without a comma - which is how most
#: Indian packs print one - was silently truncated. Requiring the comma sends
#: every ungrouped number to the second branch, which takes all of its digits.
_NUMBER = r"\d{1,3}(?:,\d{2,3})+(?:\.\d{1,3})?|\d+(?:\.\d{1,3})?"

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

#: The join between the two words of a two-word keyword, tolerant of the stray
#: glyphs OCR inserts between them.
#:
#: Measured, not guessed: a real DMart pack printed `Use By: 26/01/26` and
#: Tesseract returned `Use @ By: 26/01/26`. The date itself was perfect; a
#: single spurious `@` cost the whole declaration, because `use\s*by` cannot
#: span it.
#:
#: Deliberately narrow. It allows at most two non-word characters between two
#: words that must *both* still be present and correctly spelled. It does not
#: make the keyword fuzzy, does not tolerate a missing word, and does not
#: tolerate a misspelling - `ie By` (OCR losing the first two letters of "Use")
#: still does not match, because matching a bare `by` would collide with
#: "Marketed by" and "Packed by" and invent declarations that were never made.
_GLYPH_GAP = r"\s*[^\w\s]{0,2}\s*"

#: Small worded counts, for shelf lives printed as words rather than digits.
#: Bounded at twelve: a shelf life is months or years, and beyond twelve the
#: risk of matching an unrelated number word outweighs the recall.
_WORD_COUNTS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_WORD_COUNT_ALTERNATION = "|".join(_WORD_COUNTS)

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

#: `4 UNITS X 125 g` - a multipack written with the count unit spelled out
#: between the count and the per-unit quantity.
#:
#: `QUANTITY`'s own `pack` group only handles the bare `4 x 125 g` form. On a
#: real Dove carton reading `NET CONTENTS WHEN PACKED 4 UNITS X 125 g + 125 g
#: FREE`, the bare form does not apply and `QUANTITY.search` returns the *first*
#: match, `4 UNITS` - reporting a 625 g pack as a count of four, with no mass
#: at all and no uncertainty flag. This names the form so it can be recognised
#: rather than silently truncated.
MULTIPACK_QUANTITY = re.compile(
    rf"(?P<pack>\d{{1,3}})\s*"
    rf"(?:pieces?|pcs?|units?|nos?|n|u)\b\.?\s*"
    rf"[x×*]\s*"
    rf"(?P<value>{_NUMBER})\s*"
    rf"(?P<unit>{_UNITS})\b\.?",
    _I,
)

#: `+ 125 g FREE`, `& 50 g extra` - a bonus quantity added to the declared one.
#:
#: Whether the net quantity of such a pack is the base amount or the total is a
#: question about the declaration, not about the characters. This exists so the
#: extractor can say it does not know, rather than commit to whichever number
#: the scanner happened to reach first.
#: **An offer word on its own is not evidence of a bonus**, and that is the
#: whole shape of this pattern. It used to end in a bare `(?:free|extra)\b`,
#: which made every composition claim printed beside a quantity look like one:
#:
#:     Net Qty: 500 g   Gluten Free         ->  no net quantity reported
#:     Net Weight: 250 g Preservative Free  ->  no net quantity reported
#:     Net Contents: 500 g Alcohol Free     ->  no net quantity reported
#:
#: Those three packages declare 500 g, 250 g and 500 g plainly, with nothing
#: ambiguous about any of them, and the extractor withheld all three.
#:
#: The replacement is structural rather than a list of marketing phrases: a
#: bonus quantity is *a printed quantity* immediately followed by the offer
#: word, optionally introduced by `+` or `&`. In `Gluten Free` the token before
#: `Free` is not a quantity, so nothing matches - and no vocabulary of health
#: claims has to be kept up to date for whichever phrase appears next.
#:
#: `free from` / `free of` is excluded for the same structural reason: it
#: introduces what the package does *not* contain, so the `free` is not an
#: offer even when a quantity runs straight into it - `Net Wt 200 g Free From
#: Preservatives`.
#:
#: The limit of the rule, stated rather than papered over: a trailing
#: adjectival use - `Net Qty 1 L Extra Strong` - still reads as a bonus,
#: because a quantity really does immediately precede the offer word. That
#: failure withholds a value instead of committing to a wrong one, which is the
#: safe direction to be wrong in here.
BONUS_QUANTITY = re.compile(
    rf"(?:[+&]\s*)?(?:{_NUMBER})\s*(?:{_UNITS})\b\.?\s*"
    rf"(?:free\b(?!\s*(?:from|of)\b)|extra\b)",
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
NON_MRP_CONTEXT = re.compile(
    r"\bunit\s*(?:sale\s*)?price\b|\bper\s*(?:kg|g|ml|l|litre|liter|piece|pc)\b",
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
            rf"\bbest{_GLYPH_GAP}(?:before|by)\b"
            rf"|\buse{_GLYPH_GAP}(?:by|before)\b"
            r"|\bexp(?:iry|ires?|\.)?\s*(?:date|on|dt)?\b"
            r"|\bexpiration\b"
            rf"|\bconsume{_GLYPH_GAP}(?:by|before)\b",
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
#:
#: The count may be worded: a real namkeen pack prints `BEST BEFORE TWO MONTHS
#: AFTER PACKING`, which OCR read perfectly and the digits-only pattern then
#: discarded. `normalise_duration` resolves the word via `WORD_COUNTS`.
DURATION = re.compile(
    rf"(?P<count>\d{{1,3}}|{_WORD_COUNT_ALTERNATION})\s*"
    rf"(?P<unit>days?|weeks?|months?|years?)\b",
    _I,
)

#: Worded counts `DURATION` may capture, exposed for `normalise_duration`.
WORD_COUNTS: dict[str, int] = dict(_WORD_COUNTS)


# --- batch / lot ------------------------------------------------------------

BATCH_NUMBER = re.compile(
    r"\b(?:batch|lot|b\.?\s*no|l\.?\s*no|bn)\b\.?\s*"
    r"(?:no\.?|number|code|#)?\s*[:.\-]?\s*"
    r"(?P<value>[A-Za-z0-9][A-Za-z0-9\-/]{0,19}"
    r"(?:\s+[A-Za-z0-9][A-Za-z0-9\-/]{0,19})?)",
    _I,
)

#: The part of the batch keyword strong enough to stand on its own as evidence
#: that the declaration was *named*, for `unread_declarations`.
#:
#: Stricter than `BATCH_NUMBER`'s opening: a bare `b no` or `bn` is too easy to
#: produce from misread text, so a marker word or punctuation must follow.
BATCH_ANCHOR = re.compile(
    r"\b(?:batch|lot)\b\.?\s*(?:no\b\.?|number|code|#|:)",
    _I,
)

#: Words that are part of *naming* a declaration and can never be its value.
#:
#: This exists because of a real and dangerous failure. `BATCH_NUMBER`'s
#: `(?:no\.?|number|code|#)?` group is optional, so on a package printing
#:
#:     Batch No. :
#:
#: with the value left blank, the group backtracks, the value group takes `No`
#: itself, and the extractor emitted `batch_number = "No"` as a *certain*
#: reading. `field_presence` passes on any extracted field regardless of its
#: uncertainty flag, so a package that failed to declare a batch number was
#: recorded as having declared one - a real violation turned into a pass.
#:
#: Matched against a whole token, never a substring: a genuine batch code
#: beginning with the letters "no" must not be rejected.
DECLARATION_STOPWORDS: frozenset[str] = frozenset(
    {
        "no", "nos", "number", "numbers", "num", "code", "codes",
        "batch", "batches", "lot", "lots", "bn",
        "mfg", "mfd", "exp", "expiry", "pkd", "packed", "packing",
        "date", "dates", "dt", "use", "used", "by", "before", "best",
        "mrp", "price", "rs", "inr", "net", "qty", "quantity", "wt",
        "weight", "vol", "volume", "and", "the", "of", "for", "see",
        "panel", "above", "below", "refer", "details", "n", "a",
        # Consumer-care block vocabulary. A real marketer line reading
        # `Marketed By Address` - OCR's rendering of "...Care Executive At
        # 'Marketed By' Address" - produced a company called "Address".
        "address", "care", "customer", "consumer", "executive", "contact",
        "feedback", "suggestions", "please", "queries", "complaints",
    }
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
#: The group structure after the `1800` prefix is not fixed in practice, and
#: the previous two-group form could not match the very common four-group
#: printing. Measured: a Dove carton prints `TOLL FREE: 1800-10-22-221`, which
#: OCR read exactly and this pattern then failed to match, so the extracted
#: consumer-care field carried no number at all. Total digits after the prefix
#: are bounded at 6-8, which is what a real toll-free number has.
TOLL_FREE_PHONE = re.compile(
    r"\b1[\s\-]?800(?:[\s\-]?\d){6,8}\b"
)

#: A ten-digit Indian mobile number, optionally with the country code.
MOBILE_PHONE = re.compile(r"(?:\+?91[\s\-]?)?\b[6-9]\d{4}[\s\-]?\d{5}\b")

#: A landline with an STD code: `022-71230555`, `(020) 2612 3456`.
#:
#: Consumer-care blocks on retail packs routinely print a landline rather than
#: a mobile. A DMart pack prints `Phone No.: 022-71230555`, recognised exactly
#: and matched by nothing. The leading `0` is what distinguishes an STD code
#: from a stray run of digits.
#:
#: **The separator between the STD code and the subscriber number is required,
#: not optional**, and that is what keeps this pattern from eating things that
#: are not phone numbers. Without it, the same 14-digit FSSAI licence numbers
#: this module now extracts also matched here: an OCR line reading
#: `m Lic No (0721999000621` was reported as a consumer-care phone number.
#: Printed landlines carry a space, a hyphen or brackets; an unbroken digit run
#: is a licence, a barcode or a batch code. The trailing `(?!\d)` stops a match
#: from ending in the middle of a longer run.
LANDLINE_PHONE = re.compile(
    r"(?:\(0\d{2,4}\)|\b0\d{2,4})[\s\-]\s*\d{6,8}(?!\d)"
)

#: A line carrying a licence number rather than contact details.
#:
#: Used to keep the phone patterns off it. A licence number and a phone number
#: are both long digit runs printed next to a `No.`, and the only thing that
#: reliably tells them apart on one line of text is which keyword introduced
#: them.
LICENCE_NUMBER_CONTEXT = re.compile(
    r"\bfssai\b|\blic(?:ence|ense)?\b\.?\s*no\b", _I
)


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


# --- FSSAI licence ----------------------------------------------------------

#: An FSSAI licence number: the word, or a `Lic. No.` marker, then 14 digits.
#:
#: This is the one declaration in this pattern set with a format rigid enough
#: to validate outright - an FSSAI licence is exactly 14 digits - which is why
#: it can be added with far less false-positive risk than a free-text field.
#: The digit count is checked in `normalise_fssai_licence`, not here, so that a
#: near-miss becomes an uncertain reading rather than silently no reading at
#: all: OCR truncating a digit is a fact a reviewer needs to see.
#:
#: The separators allow the spaces and hyphens OCR inserts into a long digit
#: run. `\D{0,3}` between marker and digits absorbs `.: ` and the stray glyphs
#: that land on the `fssai` logo lockup.
FSSAI_LICENCE = re.compile(
    r"(?:\bfssai\b|\blic(?:ence|ense)?\b\.?\s*\bno\b|\blicence\s*number\b)"
    r"\D{0,6}"
    # Twelve digits minimum rather than fourteen: a licence OCR truncated by a
    # digit or two must still be *caught*, so that `normalise_fssai_licence`
    # can report it as an incomplete reading. Requiring the full fourteen here
    # would make a truncation indistinguishable from a pack with no licence.
    r"(?P<value>\d[\d\s\-]{10,20}\d)",
    _I,
)

#: The keyword alone, for `unread_declarations`: the licence was named but no
#: digits followed it.
FSSAI_ANCHOR = re.compile(r"\bfssai\b", _I)
