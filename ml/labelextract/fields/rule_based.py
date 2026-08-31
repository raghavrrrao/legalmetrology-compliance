"""First-pass, deterministic interpretation of recognised label text.

What this is
------------
A keyword-anchored pattern matcher. It reads lines of OCR output and reports
which label declarations it can locate, with the evidence line attached. It is
the smallest thing that turns raw text into something the compliance engine can
be run against, and it is honest about being a first pass.

Three rules it will not break
-----------------------------
1. **It never emits a declaration it did not locate.** A missing field is
   meaningful input downstream; inventing one to complete a set would turn a
   non-compliant package into a compliant one silently.
2. **Ambiguity is reported, not resolved.** When a value has two valid
   readings, or two lines both look like the same declaration, the field is
   emitted with `normalized_value["uncertain"] = True` and the competing
   readings listed. Nothing picks a winner and presents it as measured.
3. **It makes no legal claim.** Locating a net quantity says nothing about
   whether one was required, or whether the declared value is correct. Both of
   those come from verified `ComplianceRule` rows.

Where it is weak, stated plainly
--------------------------------
- English only. Devanagari text is recognised by the OCR layer when the
  language data is installed, but no pattern here matches it.
- No layout understanding. Multi-line addresses, values in a column beside
  their label, and text wrapped mid-declaration are all missed.
- Several declarations are not attempted at all - product/brand name, generic
  name, manufacturer address. See `ml/README.md` for the full
  supported/unsupported list.

None of this has been measured. `docs/evaluation-strategy.md` describes how it
will be; no precision, recall or F1 figure for this extractor appears anywhere
in this repository.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable, Iterable

from labelextract.contracts import (
    BoundingBox,
    ExtractedField,
    ImageRef,
    LabelFieldKey,
    OcrResult,
    UnreadDeclaration,
)
from labelextract.fields import patterns as P
from labelextract.fields.normalisation import (
    REASONS_KEY,
    UNCERTAIN_KEY,
    certain,
    is_uncertain,
    normalise_date,
    normalise_duration,
    normalise_price,
    normalise_quantity,
    normalise_text,
    normalise_unit_price,
    uncertain,
)
from labelextract.interfaces import FieldExtractor

logger = logging.getLogger(__name__)

NAME = "rule-based-fields"
VERSION = "0.1.0"

#: How a candidate was located. Recorded on every field so a reviewer can tell
#: "the label said MRP" from "this line merely looked like a price".
MATCHED_BY_KEYWORD = "keyword"
MATCHED_BY_PATTERN = "pattern"

#: Declarations this extractor attempts. Anything in `LabelFieldKey` and not
#: here is deliberately unimplemented, not overlooked.
SUPPORTED_KEYS: frozenset[LabelFieldKey] = frozenset(
    {
        LabelFieldKey.NET_QUANTITY,
        LabelFieldKey.RETAIL_SALE_PRICE,
        LabelFieldKey.UNIT_SALE_PRICE,
        LabelFieldKey.BATCH_NUMBER,
        LabelFieldKey.DATE_OF_MANUFACTURE,
        LabelFieldKey.DATE_OF_PACKING,
        LabelFieldKey.DATE_OF_IMPORT,
        LabelFieldKey.BEST_BEFORE,
        LabelFieldKey.CONSUMER_CARE_CONTACT,
        LabelFieldKey.COUNTRY_OF_ORIGIN,
        LabelFieldKey.MANUFACTURER_NAME,
        LabelFieldKey.PACKER_NAME,
        LabelFieldKey.IMPORTER_NAME,
        LabelFieldKey.OTHER,
    }
)

#: In `LabelFieldKey` and NOT attempted here. Exported so the documentation and
#: a test can assert the two lists agree, rather than the docs drifting.
UNSUPPORTED_KEYS: frozenset[LabelFieldKey] = frozenset(LabelFieldKey) - SUPPORTED_KEYS

#: Declarations a *bare keyword* can be reported unread for, and the pattern
#: that names each. The same objects the detectors anchor on, so the two cannot
#: drift apart.
#:
#: The membership rule is narrow on purpose, and has two halves. A keyword
#: qualifies only if it **cannot also be the opening of a different declaration
#: in this pattern set**, and only if it is **a label marker rather than an
#: ordinary English word**. An unread observation is a positive claim about
#: what the label says. Getting it wrong sends a reviewer to look for something
#: that was never printed, and the point of the whole mechanism is to stop
#: guessing.
#:
#: The second half is why net quantity anchors on `NET_QUANTITY_ANCHOR` rather
#: than on `NET_QUANTITY_KEYWORD`: the latter ends in a bare `\bquantity\b`,
#: which is right when a number and a unit are on the same line and wrong as
#: evidence on its own. `the quantity supplied may vary` is prose.
#:
#: Deliberately excluded, each for a reason that would otherwise produce a
#: wrong claim:
#:
#: - `date_of_manufacture` and `date_of_packing`. Their keywords match the bare
#:   stems `manufactured` and `packed`, which is also how the *manufacturer*
#:   and *packer name* declarations begin. On `Packed by BAZINGA MEDIA` the
#:   date keyword matches and there is no packing date anywhere - reporting one
#:   as unread would invent a declaration. `extract()` is unaffected: it needs
#:   an actual date before it emits anything.
#: - `consumer_care_contact`. The detector already emits a keyword-only field
#:   marked uncertain when it finds the keyword and no contact details, so
#:   there is nothing left unresolved to report.
#: - `manufacturer_name`, `packer_name`, `importer_name`, `other`,
#:   `country_of_origin`. Their patterns capture keyword *and* value together,
#:   so a keyword with nothing after it never matches at all.
#:
#: `unit_sale_price` anchors on `UNIT_SALE_PRICE_ANCHOR` rather than on
#: `UNIT_SALE_PRICE_KEYWORD` for the same shape of reason net quantity does:
#: the keyword also matches the bare abbreviation `USP`, which on a supplement
#: or pharma label routinely means *United States Pharmacopeia*. The full
#: phrasings cannot mean anything else.
#:
#: `batch_number` used to sit in the excluded list for the same reason the
#: names do - its pattern captured keyword and value together, so a bare
#: `Batch No. :` produced no field and nothing to report. That was only true
#: because the pattern was silently capturing the keyword's own qualifier as
#: the value: `Batch No.` yielded the batch code `No`. Since
#: `patterns._NOT_A_BATCH_VALUE` stopped that, a named batch declaration whose
#: value could not be read produces nothing at all, which is exactly the state
#: this mechanism exists to name. It anchors on `BATCH_NUMBER_ANCHOR` - the
#: phrasings carrying an explicit qualifier - rather than on the bare `batch`
#: and `lot` stems, which are ordinary English words.
_KEYWORD_ANCHORS: tuple[tuple[LabelFieldKey, re.Pattern[str]], ...] = (
    (LabelFieldKey.NET_QUANTITY, P.NET_QUANTITY_ANCHOR),
    (LabelFieldKey.RETAIL_SALE_PRICE, P.MRP_KEYWORD),
    (LabelFieldKey.UNIT_SALE_PRICE, P.UNIT_SALE_PRICE_ANCHOR),
    (LabelFieldKey.BATCH_NUMBER, P.BATCH_NUMBER_ANCHOR),
    (LabelFieldKey.BEST_BEFORE, dict(P.DATE_KEYWORDS)["best_before"]),
    (LabelFieldKey.DATE_OF_IMPORT, dict(P.DATE_KEYWORDS)["date_of_import"]),
)


@dataclass(frozen=True)
class _Line:
    """One line of recognised text, with where it was read from."""

    index: int
    text: str
    box: BoundingBox | None
    confidence: float | None


@dataclass(frozen=True)
class _Candidate:
    """A possible reading of one declaration, before the best one is chosen."""

    key: LabelFieldKey
    raw_value: str
    normalized: dict
    confidence: float | None
    box: BoundingBox | None
    line_index: int
    matched_by: str
    #: What two candidates are compared on to decide whether they conflict.
    signature: Any = dataclass_field(default=None)


class RuleBasedFieldExtractor(FieldExtractor):
    """Locates declarations in recognised text using patterns and keywords.

    Stateless across calls: the registry caches one instance per process and it
    is reused for every image.
    """

    name = NAME
    version = VERSION

    def __init__(
        self,
        *,
        require_net_quantity_keyword: bool = True,
        read_name_from_next_line: bool = True,
    ) -> None:
        """
        Args:
            require_net_quantity_keyword: When True (the default), a quantity
                is reported as the net quantity only if the line also carries a
                net-quantity keyword. Turning this off raises recall on labels
                that print a bare `500 g`, at the cost of matching every number
                in the nutrition panel. Do not turn it off without measuring
                precision on an annotated set first - `docs/evaluation-strategy.md`
                explains why a false "present" is the more damaging error here.
            read_name_from_next_line: When True (the default), a name keyword
                that ends its line takes its value from the line below, marked
                uncertain for it. Off, only the keyword's own line is read.
                Measured on `our-eval-v0.3-usp-partial`; see `_names`.
        """
        self.require_net_quantity_keyword = require_net_quantity_keyword
        self.read_name_from_next_line = read_name_from_next_line

    def extract(self, ocr: OcrResult, image: ImageRef) -> tuple[ExtractedField, ...]:
        lines = _lines_from(ocr)
        if not lines:
            # No text recognised. Zero declarations is the correct and complete
            # answer; the pipeline reports EMPTY and the compliance engine
            # treats that as inconclusive rather than as a missing declaration.
            return ()

        candidates: list[_Candidate] = []
        for detector in self._detectors():
            try:
                candidates.extend(detector(lines))
            except Exception:
                # One misbehaving detector must not discard every declaration
                # read from the label. Logged with a traceback; the run
                # continues and simply reports fewer fields.
                logger.exception(
                    "Field detector %s failed; continuing without it",
                    getattr(detector, "__name__", detector),
                )
        return _resolve(candidates)

    def unread_declarations(
        self, ocr: OcrResult, fields: tuple[ExtractedField, ...]
    ) -> tuple[UnreadDeclaration, ...]:
        """Keywords that were recognised but produced no field.

        The case this was written for, from a real photograph of a curved can:
        OCR returned the single line `MRP` because the rest of that line was
        too foreshortened to read. `extract()` correctly emitted nothing - a
        keyword is not a price - but "no MRP field" then means two opposite
        things at once, and a compliance engine cannot tell which.

        The rule: a keyword in `_KEYWORD_ANCHORS` was recognised somewhere, and
        no field for that key came out anywhere. Per *line* would be more
        precise and would also flag a keyword whose value was correctly read
        from a different line, which is noise. This reports the one thing that
        is unambiguous - **we saw this declaration named and produced nothing
        for it.**

        `_KEYWORD_ANCHORS` is a deliberately short list, and the reasoning for
        every declaration left out of it is recorded there. The short version:
        an unread observation is a positive claim about what the label says,
        and several keywords in this pattern set are also the opening of a
        *different* declaration - `Packed by BAZINGA MEDIA` matches the
        packing-date keyword and carries no date. Reporting that would send a
        reviewer looking for something the package never printed.

        No value is inferred, no line is guessed at, and nothing here is a
        legal claim: that a keyword was printed says nothing about whether the
        declaration was required or whether its value would have been correct.
        """
        lines = _lines_from(ocr)
        if not lines:
            # Nothing was recognised at all. That is `EMPTY` - inconclusive
            # about every declaration - and reporting individual keywords as
            # unread would add nothing to it.
            return ()

        extracted_keys = {extracted.key for extracted in fields}
        unread: list[UnreadDeclaration] = []

        for key, keyword in _KEYWORD_ANCHORS:
            if key in extracted_keys:
                continue
            for line in lines:
                if not keyword.search(line.text):
                    continue
                unread.append(
                    UnreadDeclaration(
                        key=key,
                        evidence_text=line.text,
                        box=line.box,
                        confidence=line.confidence,
                    )
                )
                # One observation per declaration. A second line naming the
                # same unread declaration is the same finding, not a new one.
                break

        return tuple(unread)

    def _detectors(self) -> tuple[Callable[[list[_Line]], Iterable[_Candidate]], ...]:
        return (
            self._net_quantity,
            self._retail_sale_price,
            self._unit_sale_price,
            self._batch_number,
            self._dates,
            self._consumer_care_contact,
            self._country_of_origin,
            self._names,
        )

    # --- net quantity -------------------------------------------------------

    def _net_quantity(self, lines: list[_Line]) -> list[_Candidate]:
        found: list[_Candidate] = []
        for line in lines:
            if P.NON_DECLARATION_CONTEXT.search(line.text):
                # A nutrition-panel line. Its numbers are real quantities and
                # none of them is the declared net quantity.
                continue

            has_keyword = bool(P.NET_QUANTITY_KEYWORD.search(line.text))
            if self.require_net_quantity_keyword and not has_keyword:
                continue

            match = P.QUANTITY.search(line.text)
            if match is None:
                continue

            normalized = normalise_quantity(
                match.group("value"),
                match.group("unit"),
                pack_count_text=match.group("pack"),
            )
            if not has_keyword:
                normalized = _mark_uncertain(
                    normalized,
                    "no net-quantity keyword on this line; this may be any "
                    "quantity printed on the package",
                )
            found.append(
                _candidate(
                    LabelFieldKey.NET_QUANTITY,
                    line,
                    normalized,
                    MATCHED_BY_KEYWORD if has_keyword else MATCHED_BY_PATTERN,
                    signature=(
                        normalized.get("base_quantity"),
                        normalized.get("base_unit"),
                        normalized.get("quantity"),
                        normalized.get("unit"),
                    ),
                )
            )
        return found

    # --- retail sale price --------------------------------------------------

    def _retail_sale_price(self, lines: list[_Line]) -> list[_Candidate]:
        found: list[_Candidate] = []
        for line in lines:
            if P.NON_MRP_CONTEXT.search(line.text):
                # A unit price ("₹200 per kg") is a different declaration, and
                # `_unit_sale_price` is the detector that reads it.
                continue

            keyword = P.MRP_KEYWORD.search(line.text)
            has_keyword = keyword is not None

            if has_keyword:
                amount = _amount_near(line.text, keyword)
            elif P.UNIT_SALE_PRICE_KEYWORD.search(line.text):
                # `USP: Rs.0.93/g` names a *different* declaration and carries
                # exactly one amount. Without this, that one amount produced
                # two fields - the unit sale price it is, and a speculative
                # retail sale price - and `field_presence` passes on an
                # uncertain field just as it does on a committed one, so a
                # package declaring only a unit price would have been recorded
                # as declaring an MRP.
                #
                # Applied only on this branch. A line that carries an MRP
                # keyword *and* a unit-price keyword is still read for its MRP:
                # the keyword is doing the anchoring there, and dropping a
                # declared retail sale price is the more expensive mistake.
                continue
            else:
                # No keyword, so only a currency token can anchor this. A bare
                # number on an unlabelled line is not a price.
                price = P.PRICE.search(line.text)
                amount = _price_amount(price) if price is not None else None

            if amount is None:
                continue

            inclusive = None
            if P.TAX_INCLUSIVE.search(line.text):
                inclusive = True
            elif P.TAX_EXCLUSIVE.search(line.text):
                inclusive = False

            normalized = normalise_price(amount, inclusive_of_taxes=inclusive)
            if not has_keyword:
                normalized = _mark_uncertain(
                    normalized,
                    "a price was read but no MRP or retail-sale-price keyword "
                    "was found on this line",
                )
            found.append(
                _candidate(
                    LabelFieldKey.RETAIL_SALE_PRICE,
                    line,
                    normalized,
                    MATCHED_BY_KEYWORD if has_keyword else MATCHED_BY_PATTERN,
                    signature=normalized.get("amount"),
                )
            )
        return found

    # --- unit sale price ----------------------------------------------------

    def _unit_sale_price(self, lines: list[_Line]) -> list[_Candidate]:
        """Locate a unit sale price - rule 6(11)'s "Rs. _ per g" declaration.

        This reads evidence and stops there. Rule 6(11) prescribes which unit
        the declaration must use for which net-quantity band, and exempts a
        package whose retail sale price equals its unit sale price; both are
        comparisons for the rules layer to make against the extracted values,
        and neither is attempted here. `normalise_unit_price` says the same
        thing about the value itself.

        Two levels of confidence, on the same principle the MRP detector uses:

        - a unit-sale-price keyword introducing a per-unit amount is committed
          to, because nothing else on a package is phrased that way;
        - a bare `Rs.0.93/g` with no keyword is emitted **uncertain**, and only
          when a currency token was actually read. Without one, `0.08 per g`
          is indistinguishable from a nutrition figure or a comparison in
          marketing copy, so nothing is emitted at all.

        A line carrying an MRP keyword and no unit-sale-price keyword is left
        alone entirely. `MRP Rs.200/kg` is one declaration written with a rate,
        not two declarations, and reporting a second would record the package
        as declaring something it never separately declared - which
        `field_presence` would then pass on.
        """
        found: list[_Candidate] = []
        for line in lines:
            if P.NON_DECLARATION_CONTEXT.search(line.text):
                # A nutrition-panel line. `2.5 g per 100 g` is a real rate and
                # none of them is a price.
                continue

            keyword = P.UNIT_SALE_PRICE_KEYWORD.search(line.text)
            has_keyword = keyword is not None

            if has_keyword:
                match = _per_unit_price_near(line.text, keyword)
            else:
                if P.MRP_KEYWORD.search(line.text):
                    continue
                match = P.PER_UNIT_PRICE.search(line.text)
                if match is not None and not match.group("currency"):
                    # No keyword and no currency: not enough to call this a
                    # price at all.
                    match = None

            if match is None:
                continue

            normalized = normalise_unit_price(
                match.group("amount"), match.group("unit")
            )
            if not has_keyword:
                normalized = _mark_uncertain(
                    normalized,
                    "a per-unit price was read but no unit-sale-price keyword "
                    "was found on this line",
                )
            found.append(
                _candidate(
                    LabelFieldKey.UNIT_SALE_PRICE,
                    line,
                    normalized,
                    MATCHED_BY_KEYWORD if has_keyword else MATCHED_BY_PATTERN,
                    signature=(
                        normalized.get("amount"),
                        normalized.get("per_unit"),
                    ),
                )
            )
        return found

    # --- batch / lot --------------------------------------------------------

    def _batch_number(self, lines: list[_Line]) -> list[_Candidate]:
        found: list[_Candidate] = []
        for line in lines:
            match = P.BATCH_NUMBER.search(line.text)
            if match is None:
                continue

            value = normalise_text(match.group("value")).strip(P.TRAILING_PUNCTUATION)
            if not value:
                continue

            if _looks_like_a_date(value):
                # "Batch No: 03/2025" happens, and so does a batch label whose
                # value ran into the adjacent packing date. Either way we
                # cannot tell which we are looking at.
                normalized = uncertain(
                    "the value after the batch keyword reads as a date; it may "
                    "be a packing date rather than a batch code",
                    candidates=[value],
                )
            else:
                normalized = certain(batch_number=value)

            found.append(
                _candidate(
                    LabelFieldKey.BATCH_NUMBER,
                    line,
                    normalized,
                    MATCHED_BY_KEYWORD,
                    signature=value,
                )
            )
        return found

    # --- dates --------------------------------------------------------------

    def _dates(self, lines: list[_Line]) -> list[_Candidate]:
        found: list[_Candidate] = []
        for position, line in enumerate(lines):
            for key_value, keyword in P.DATE_KEYWORDS:
                if not keyword.search(line.text):
                    continue

                key = LabelFieldKey(key_value)
                # The value sometimes sits on the following line - a label
                # printing the keyword above the date, or OCR breaking the
                # line. Two lines is as far as this looks; anything more needs
                # real layout analysis.
                #
                # Every keyword is tried against every line, because one line
                # routinely carries two declarations: "MFG 12/2024 EXP 12/2026".
                for offset in (0, 1):
                    if position + offset >= len(lines):
                        break
                    source = lines[position + offset]
                    normalized = _date_value(
                        source.text, after=keyword if offset == 0 else None
                    )
                    if normalized is None:
                        continue

                    evidence = line.text
                    if offset:
                        evidence = f"{line.text} {source.text}"
                        # Nothing ties this date to this keyword except the two
                        # being adjacent, and "adjacent" is a guess about
                        # layout that a line-oriented reader cannot check. The
                        # next line may hold an address, a batch code, or the
                        # value belonging to a different keyword entirely.
                        normalized = _mark_uncertain(
                            normalized,
                            "the date was read from the line after the keyword; "
                            "it may belong to a different declaration",
                        )
                    found.append(
                        _candidate(
                            key,
                            line,
                            normalized,
                            MATCHED_BY_KEYWORD,
                            raw_value=evidence,
                            signature=(
                                normalized.get("date")
                                or normalized.get("year_month")
                                or (
                                    normalized.get("duration_value"),
                                    normalized.get("duration_unit"),
                                )
                            ),
                        )
                    )
                    break
        return found

    # --- consumer care contact ----------------------------------------------

    def _consumer_care_contact(self, lines: list[_Line]) -> list[_Candidate]:
        found: list[_Candidate] = []
        for line in lines:
            emails = P.EMAIL.findall(line.text)
            toll_free = P.TOLL_FREE_PHONE.findall(line.text)
            mobiles = [
                number
                for number in P.MOBILE_PHONE.findall(line.text)
                if not any(number in tf for tf in toll_free)
            ]
            has_keyword = bool(P.CONTACT_KEYWORD.search(line.text))

            if not (emails or toll_free or mobiles or has_keyword):
                continue
            if has_keyword and not (emails or toll_free or mobiles):
                # "Customer care:" with the number on another line. Recorded as
                # located-but-unread rather than dropped, because the absence
                # of a value here is a different fact from the absence of the
                # declaration.
                normalized = uncertain(
                    "a consumer-care keyword was found but no email or phone "
                    "number was read on this line"
                )
            else:
                values: dict[str, Any] = {}
                if emails:
                    values["emails"] = [normalise_text(e) for e in emails]
                phones = [normalise_text(p) for p in [*toll_free, *mobiles]]
                if phones:
                    values["phones"] = phones
                if has_keyword or toll_free or emails:
                    normalized = certain(**values)
                else:
                    # A bare ten-digit number with no keyword could belong to
                    # the manufacturer's address rather than to consumer care.
                    normalized = uncertain(
                        "a phone number was read with no consumer-care keyword "
                        "on the line",
                        **values,
                    )

            found.append(
                _candidate(
                    LabelFieldKey.CONSUMER_CARE_CONTACT,
                    line,
                    normalized,
                    MATCHED_BY_KEYWORD if has_keyword else MATCHED_BY_PATTERN,
                    signature=(
                        tuple(normalized.get("emails", ())),
                        tuple(normalized.get("phones", ())),
                    ),
                )
            )
        return found

    # --- country of origin --------------------------------------------------

    def _country_of_origin(self, lines: list[_Line]) -> list[_Candidate]:
        """Locate a country-of-origin declaration.

        Two anchors, two levels of confidence:

        - `Country of Origin: X` names the declaration. Nothing else on a
          package is phrased that way, so a match is committed to.
        - `Made in X` / `Product of X` is *usually* the country and sometimes
          the manufacturing town, so it is reported uncertain.

        Text that merely shares the phrasing - "Made in a facility that also
        processes nuts", "Product of the finest wheat grown in Punjab" - is not
        emitted at all rather than emitted as uncertain. An extracted field
        makes `field_presence` PASS regardless of its uncertainty flag, so
        emitting prose here would hide a package that never declared an origin,
        which is the failure this layer exists to avoid.
        """
        found: list[_Candidate] = []
        for line in lines:
            declared = P.COUNTRY_OF_ORIGIN_DECLARED.search(line.text)
            match = declared or P.COUNTRY_OF_ORIGIN_IMPLIED.search(line.text)
            if match is None:
                continue
            value = normalise_text(match.group("value")).strip(P.TRAILING_PUNCTUATION)
            if not value:
                continue

            # No country list is applied. Checking the value against a list of
            # recognised countries is a validation question, and validation of
            # a declared value belongs to the rules layer, not here.
            if declared is not None:
                normalized = certain(country_text=value)
            else:
                normalized = uncertain(
                    "read from a 'made in' / 'product of' phrase rather than an "
                    "explicit country-of-origin declaration; that wording is "
                    "also used for a manufacturing location",
                    country_text=value,
                )

            found.append(
                _candidate(
                    LabelFieldKey.COUNTRY_OF_ORIGIN,
                    line,
                    normalized,
                    MATCHED_BY_KEYWORD,
                    signature=value.casefold(),
                )
            )
        return found

    # --- names --------------------------------------------------------------

    def _names(self, lines: list[_Line]) -> list[_Candidate]:
        found: list[_Candidate] = []
        for position, line in enumerate(lines):
            for key_value, pattern in P.NAME_DECLARATIONS:
                match = pattern.search(line.text)
                if match is None:
                    continue
                value = normalise_text(match.group("value")).strip(
                    P.TRAILING_PUNCTUATION
                )
                evidence = line.text
                from_next_line = False
                if not _could_be_a_name(value) and self.read_name_from_next_line:
                    # The keyword ends its line and the name is printed below
                    # it. The same shape of layout `_dates` already looks one
                    # line ahead for, and looked at here for the same reason:
                    # `Manufactured by:` with nothing after it is a declaration
                    # whose value a person can read and this extractor cannot.
                    #
                    # One line, only when the keyword's own line carries no
                    # usable name at all, and always marked uncertain - because
                    # "the next line" is a guess about layout that a
                    # line-oriented reader cannot check. The line below a
                    # `Marketed by:` that ends a panel is as likely to be a
                    # customer-care number as a company name.
                    candidate_line = (
                        lines[position + 1] if position + 1 < len(lines) else None
                    )
                    if candidate_line is not None:
                        candidate_value = normalise_text(candidate_line.text).strip(
                            P.TRAILING_PUNCTUATION
                        )
                        if _could_be_a_name(candidate_value):
                            value = candidate_value
                            evidence = f"{line.text} {candidate_line.text}"
                            from_next_line = True

                if not _could_be_a_name(value):
                    # The keyword introduced something that is not a name. On
                    # `p007_01_back` OCR read `Manufactured by: #` - the
                    # company name is printed on the next line and the glyph
                    # between them was recognised as `#` - and this detector
                    # emitted `#` as the manufacturer's name. That is a
                    # committed reading of a declaration whose value was not
                    # read, and `field_presence` passes on it.
                    #
                    # Dropped rather than emitted uncertain: a name is a free
                    # text field, so there is no ambiguity to report - the
                    # captured characters simply are not a name. The keyword
                    # having been seen is a real observation, but not one this
                    # extractor can make safely; see `_KEYWORD_ANCHORS` for why
                    # the name keywords are not unread-declaration anchors.
                    continue

                values: dict[str, Any] = {"name": value}
                if key_value == "other":
                    values["declaration"] = "marketed_by"
                # Always uncertain: a company name on a label runs onto the
                # following lines together with its address, and this extractor
                # reads one line. What we captured is a prefix of the
                # declaration, not necessarily the whole of it.
                normalized = uncertain(
                    "the name may continue onto following lines; the "
                    "address is not extracted",
                    **values,
                )
                if from_next_line:
                    normalized = _mark_uncertain(
                        normalized,
                        "the name was read from the line after the keyword; it "
                        "may belong to a different declaration",
                    )
                found.append(
                    _candidate(
                        LabelFieldKey(key_value),
                        line,
                        normalized,
                        MATCHED_BY_KEYWORD,
                        raw_value=evidence,
                        signature=value.casefold(),
                    )
                )
                break
        return found


# --- helpers ----------------------------------------------------------------


def _lines_from(ocr: OcrResult) -> list[_Line]:
    """Flatten OCR blocks into non-empty lines of normalised text.

    A block that already contains newlines is split, so an engine that reports
    a whole paragraph per block is handled the same as one that reports lines.
    Each resulting line inherits its block's geometry and confidence, which is
    an approximation - and the reason the OCR layer emits one block per line.
    """
    lines: list[_Line] = []
    for block in ocr.blocks:
        for piece in block.text.splitlines():
            text = normalise_text(piece)
            if not text:
                continue
            lines.append(
                _Line(
                    index=len(lines),
                    text=text,
                    box=block.box,
                    confidence=block.confidence,
                )
            )
    return lines


def _candidate(
    key: LabelFieldKey,
    line: _Line,
    normalized: dict,
    matched_by: str,
    *,
    raw_value: str | None = None,
    signature: Any = None,
) -> _Candidate:
    return _Candidate(
        key=key,
        raw_value=raw_value if raw_value is not None else line.text,
        normalized={**normalized, "matched_by": matched_by},
        confidence=line.confidence,
        box=line.box,
        line_index=line.index,
        matched_by=matched_by,
        signature=signature,
    )


def _price_amount(match: re.Match[str] | None) -> str | None:
    """The amount from a `PRICE` or `BARE_AMOUNT` match, whichever side it fell."""
    if match is None:
        return None
    groups = match.groupdict()
    return groups.get("amount") or groups.get("amount_before")


def _amount_near(text: str, keyword: re.Match[str]) -> str | None:
    """Read the price belonging to an MRP keyword, or None if there is none.

    Proximity is the whole point, and it works the same way `_date_value` does:
    the text *after* the keyword is what the keyword introduces. Searching the
    whole line instead lets `MRP (incl. of all taxes) for 500 g pack: 250`
    report 500 - the net quantity - as the retail price, confidently.

    The one concession is a label that prints the price before the keyword
    ("Rs. 250 M.R.P."). That is read, but only when a currency token anchors
    it: a bare number sitting before the keyword is far more likely to be
    something else on the panel.
    """
    after = text[keyword.end():]
    match = P.PRICE.search(after) or P.BARE_AMOUNT.search(after)
    if match is None:
        match = P.PRICE.search(text[: keyword.start()])
    return _price_amount(match)


def _per_unit_price_near(text: str, keyword: re.Match[str]) -> re.Match[str] | None:
    """Read the per-unit price belonging to a unit-sale-price keyword.

    Proximity works the way it does in `_amount_near`: what the keyword
    introduces is the text *after* it. On
    `UNIT SALE PRICE : Rs.2.91 PER GRAM (NET 120 GRAMS)` searching the whole
    line first could attach the keyword to the net quantity instead.

    The one concession is a label that prints the rate before the name of the
    declaration, and it is allowed only when a currency token anchors it - a
    bare number ahead of the keyword is far more likely to be something else on
    the panel.
    """
    after = P.PER_UNIT_PRICE.search(text[keyword.end():])
    if after is not None:
        return after
    before = P.PER_UNIT_PRICE.search(text[: keyword.start()])
    if before is not None and before.group("currency"):
        return before
    return None


def _mark_uncertain(normalized: dict, reason: str) -> dict:
    """Add a reason to a mapping, promoting it to uncertain if it was not."""
    reasons = list(normalized.get(REASONS_KEY, []))
    if reason not in reasons:
        reasons.append(reason)
    return {**normalized, UNCERTAIN_KEY: True, REASONS_KEY: reasons}


def _date_value(text: str, *, after: re.Pattern[str] | None) -> dict | None:
    """Read a date or a shelf life from `text`, or None if there is neither.

    When `after` is given, only the portion of the line following that keyword
    is searched. That is what keeps "MFG 25/12/2024 EXP 24/12/2026" from
    attributing the manufacture date to the expiry keyword - and there is
    deliberately no fallback to the whole line, because a fallback would
    reintroduce exactly that mis-attribution whenever a keyword ends a line.
    The keyword-then-next-line case is handled by the caller instead.

    `after=None` is the next-line lookahead: the keyword was on the previous
    line, so the whole of this one is fair game.
    """
    source = text
    if after is not None:
        match = after.search(text)
        if match is None:
            return None
        source = text[match.end():]
    return _first_date_in(source)


def _first_date_in(text: str) -> dict | None:
    iso = P.ISO_DATE.search(text)
    if iso is not None:
        return normalise_date(
            first=iso.group("day"), second=iso.group("month"), year=iso.group("year")
        )

    named = P.NAMED_MONTH_DATE.search(text)
    if named is not None:
        return normalise_date(
            first=named.group("first"),
            month_name=named.group("month_name"),
            year=named.group("year"),
        )

    numeric = P.NUMERIC_DATE.search(text)
    if numeric is not None:
        return normalise_date(
            first=numeric.group("first"),
            second=numeric.group("second"),
            year=numeric.group("year"),
        )

    month_year = P.MONTH_YEAR_DATE.search(text)
    if month_year is not None:
        return normalise_date(
            first=month_year.group("first"), year=month_year.group("year")
        )

    duration = P.DURATION.search(text)
    if duration is not None:
        return normalise_duration(duration.group("count"), duration.group("unit"))
    return None


def _looks_like_a_date(value: str) -> bool:
    return _first_date_in(value) is not None


#: The weakest test that separates a name from OCR noise: a name contains at
#: least one letter.
#:
#: Deliberately not stronger - no word list, no length floor, no capitalisation
#: rule - because company names on Indian packaging are genuinely varied ("3M
#: India", "ITC Ltd", "S. K. Foods", a single-initial proprietor) and every
#: stricter rule would drop one of them. It is aimed at exactly one observed
#: failure: a keyword whose value line was not recognised, leaving a stray glyph
#: (`#`, `:`, `>`, `*`) behind for the pattern's `.+` to capture. Any letter at
#: all excludes those, and excluding no more than those is the point.
#:
#: `\w` minus digits and underscore rather than `[A-Za-z]`, so a Devanagari or
#: accented name is not rejected by a rule that was only ever meant to catch
#: punctuation.
_HAS_A_LETTER = re.compile(r"[^\W\d_]")


def _could_be_a_name(value: str) -> bool:
    return bool(value) and _HAS_A_LETTER.search(value) is not None


def _resolve(candidates: list[_Candidate]) -> tuple[ExtractedField, ...]:
    """Reduce many candidates to at most one field per declaration.

    Emitting several rows for the same key would leave the compliance engine
    picking one arbitrarily. Instead the best-supported reading is emitted, and
    when a genuinely different reading was also found, the field is marked
    uncertain and both are listed - the disagreement is information, not noise
    to discard.
    """
    grouped: dict[LabelFieldKey, list[_Candidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.key, []).append(candidate)

    fields: list[ExtractedField] = []
    for key in sorted(grouped, key=lambda k: k.value):
        ranked = sorted(grouped[key], key=_rank)
        best = ranked[0]
        normalized = dict(best.normalized)

        conflicting = _conflicting_signatures(ranked)
        if conflicting:
            normalized = _mark_uncertain(
                normalized,
                f"{len(conflicting)} different values were found for this "
                f"declaration on the label",
            )
            normalized["candidates"] = conflicting

        try:
            fields.append(
                ExtractedField(
                    key=key,
                    raw_value=best.raw_value,
                    normalized_value=normalized,
                    confidence=best.confidence,
                    box=best.box,
                )
            )
        except (ValueError, TypeError):
            # A malformed candidate - an empty raw value, an out-of-range
            # confidence - is dropped, not raised. One bad reading must not
            # discard every other declaration found on the label.
            logger.warning(
                "Discarded a malformed %s candidate from line %s",
                key.value,
                best.line_index,
            )
    return tuple(fields)


def _rank(candidate: _Candidate) -> tuple:
    """Sort key: best candidate first.

    Keyword-anchored beats pattern-only, committed beats uncertain, then higher
    OCR confidence, then earlier on the label. An unknown confidence sorts as
    if it were zero *for tie-breaking only* - that is an ordering convenience
    and is never written anywhere as a measured value.
    """
    return (
        0 if candidate.matched_by == MATCHED_BY_KEYWORD else 1,
        1 if is_uncertain(candidate.normalized) else 0,
        -(candidate.confidence if candidate.confidence is not None else 0.0),
        candidate.line_index,
    )


def _conflicting_signatures(ranked: list[_Candidate]) -> list[str]:
    """Distinct readings among candidates, or [] when they all agree.

    Candidates whose signature is None or empty carry no committed value, so
    they cannot disagree with anything and are ignored here.
    """
    seen: list[Any] = []
    for candidate in ranked:
        signature = candidate.signature
        if signature is None or signature == () or _is_all_none(signature):
            continue
        if signature not in seen:
            seen.append(signature)
    if len(seen) < 2:
        return []
    return [str(signature) for signature in seen]


def _is_all_none(signature: Any) -> bool:
    return isinstance(signature, tuple) and all(part is None for part in signature)
