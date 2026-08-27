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

One rule for cross-references
-----------------------------
Labels routinely say *where* a declaration is printed - `See Above Panel for
Date of Packaging, MRP Rs. (incl. of all taxes), Batch No. & Use By Date`. Two
detectors used to treat any such phrase as a veto over the whole line, and the
other six ignored it, so the same sentence fragment suppressed a net quantity
while leaving an MRP and a best-before date untouched:

    MRP Rs. 40.00 (see below for offers)        ->  40.00 extracted
    Net Quantity: 500 g (see below for offers)  ->  nothing at all
    Best Before 12/2026. See above panel.       ->  2026-12 extracted

The rule is now the same everywhere, and it is about the *value*, not the
phrase:

- a usable value on the line is extracted, whatever else the line says;
- a declaration named with no usable value produces no field, and
  `unread_declarations` records that it was named;
- nothing is ever read out of the reference text itself.

The third point is what the veto was really protecting, and it is enforced
where it belongs - `_batch_value`, `DECLARATION_STOPWORDS` and the `validation`
stage refuse `No`, `panel`, `above` and the rest as values. That guard does not
need to know a cross-reference phrase was present, which is why there is no
longer a pattern for one.

Where it is weak, stated plainly
--------------------------------
- English only. Devanagari text is recognised by the OCR layer when the
  language data is installed, but no pattern here matches it.
- No layout understanding. Multi-line addresses, values in a column beside
  their label, and text wrapped mid-declaration are all missed.
- Several declarations are not attempted at all - product/brand name, generic
  name, manufacturer address, unit sale price. See `ml/README.md` for the full
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
    normalise_fssai_licence,
    normalise_price,
    normalise_quantity,
    normalise_text,
    uncertain,
)
from labelextract.fields.validation import validate
from labelextract.interfaces import FieldExtractor

logger = logging.getLogger(__name__)

NAME = "rule-based-fields"
#: 0.2.0 added the refusal guards (a keyword-shaped value is not a value, an
#: ambiguous quantity is withheld), the `validation` stage, and the FSSAI
#: licence field. What this extractor emits for the same text changed, so the
#: version moves with it.
VERSION = "0.2.0"

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
        LabelFieldKey.BATCH_NUMBER,
        LabelFieldKey.FSSAI_LICENCE,
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
#: `batch_number` was on that list and has moved off it. The reasoning that put
#: it there - "the pattern captures keyword and value together, so a bare
#: keyword never matches" - stopped being true once `_batch_value` began
#: *rejecting* a captured value that is only the keyword's own suffix. A pack
#: printing `Batch No. :` with nothing after it now correctly produces no
#: field, and without an anchor here that would be silent - indistinguishable
#: from a pack carrying no batch declaration at all. `BATCH_ANCHOR` is stricter
#: than the extraction pattern's opening for the usual reason: evidence has to
#: be unambiguous, so a bare `bn` or `b no` does not qualify.
_KEYWORD_ANCHORS: tuple[tuple[LabelFieldKey, re.Pattern[str]], ...] = (
    (LabelFieldKey.NET_QUANTITY, P.NET_QUANTITY_ANCHOR),
    (LabelFieldKey.RETAIL_SALE_PRICE, P.MRP_KEYWORD),
    (LabelFieldKey.BATCH_NUMBER, P.BATCH_ANCHOR),
    (LabelFieldKey.FSSAI_LICENCE, P.FSSAI_ANCHOR),
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

    def __init__(self, *, require_net_quantity_keyword: bool = True) -> None:
        """
        Args:
            require_net_quantity_keyword: When True (the default), a quantity
                is reported as the net quantity only if the line also carries a
                net-quantity keyword. Turning this off raises recall on labels
                that print a bare `500 g`, at the cost of matching every number
                in the nutrition panel. Do not turn it off without measuring
                precision on an annotated set first - `docs/evaluation-strategy.md`
                explains why a false "present" is the more damaging error here.
        """
        self.require_net_quantity_keyword = require_net_quantity_keyword

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
            self._batch_number,
            self._fssai_licence,
            self._dates,
            self._consumer_care_contact,
            self._country_of_origin,
            self._names,
        )

    # --- net quantity -------------------------------------------------------

    def _net_quantity(self, lines: list[_Line]) -> list[_Candidate]:
        found: list[_Candidate] = []
        for line in lines:
            has_keyword = bool(P.NET_QUANTITY_KEYWORD.search(line.text))

            if P.NON_DECLARATION_CONTEXT.search(line.text) and not (
                P.NET_QUANTITY_ANCHOR.search(line.text)
            ):
                # A nutrition-panel line. Its numbers are real quantities and
                # none of them is the declared net quantity.
                #
                # It is a whole-line veto, so an explicit net-quantity anchor
                # overrides it. `Net Quantity: 500 g. See above for nutrition`
                # is a declaration that happens to mention the panel, and the
                # bare word "nutrition" was enough to discard it entirely.
                #
                # `NET_QUANTITY_ANCHOR` rather than `NET_QUANTITY_KEYWORD`, and
                # the difference is the whole safety of the override: the
                # keyword ends in a bare `\bquantity\b`, so a genuine panel
                # heading reading `Quantity per 100 g` would cancel its own
                # guard and be read as a 100 g declaration. The anchor requires
                # `Net Qty` / `Net Weight` / `Net Contents` - which is what a
                # declaration prints and a nutrition panel does not.
                continue
            if self.require_net_quantity_keyword and not has_keyword:
                continue

            normalized = _quantity_on(line.text)
            if normalized is None:
                continue

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
                # `LabelFieldKey.UNIT_SALE_PRICE` is not attempted yet.
                continue

            keyword = P.MRP_KEYWORD.search(line.text)
            has_keyword = keyword is not None

            if has_keyword:
                amount = _amount_near(line.text, keyword)
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

    # --- batch / lot --------------------------------------------------------

    def _batch_number(self, lines: list[_Line]) -> list[_Candidate]:
        """Locate a batch or lot code.

        No cross-reference guard, deliberately. `See Above Panel for ... Batch
        No. & Use By Date` used to be skipped as a whole line; it does not need
        to be, because the only thing such a line can offer is `No` - and
        `_batch_value` refuses that, as does the `validation` stage behind it.
        Vetoing the line as well cost `Batch No.: A123. Refer above panel for
        storage` its perfectly readable code. See the module docstring.
        """
        found: list[_Candidate] = []
        for line in lines:
            match = P.BATCH_NUMBER.search(line.text)
            if match is None:
                continue

            value = _batch_value(match.group("value"))
            if value is None:
                # The keyword was printed with no usable value after it. No
                # field: a keyword is not a batch code, and emitting one would
                # record a declaration the package may never have made.
                # `unread_declarations` reports the keyword instead.
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

    # --- FSSAI licence ------------------------------------------------------

    def _fssai_licence(self, lines: list[_Line]) -> list[_Candidate]:
        """Locate an FSSAI licence number.

        Added because this declaration is mandatory on every packaged food and
        was being discarded despite being among the *best*-recognised text on
        the labels measured - three packs returned their licence numbers
        digit-perfect while their MRP was unreadable.

        It is the safest field in this set to add, for one reason: an FSSAI
        licence is exactly 14 digits, so a match can be checked against its own
        format without knowing anything about the product. A wrong digit count
        is reported uncertain rather than dropped, because a truncated licence
        number is something a reviewer needs to see, and rather than silently
        corrected, because inventing a digit would produce a licence number
        indistinguishable from a correctly read one.

        A pack often prints several licence numbers - one per manufacturing
        site, keyed A) to O). `_resolve` reports the disagreement and lists
        them all rather than picking one, which is the honest answer: this
        layer cannot know which site made the unit in front of the camera.
        """
        found: list[_Candidate] = []
        for line in lines:
            for match in P.FSSAI_LICENCE.finditer(line.text):
                normalized = normalise_fssai_licence(match.group("value"))
                found.append(
                    _candidate(
                        LabelFieldKey.FSSAI_LICENCE,
                        line,
                        normalized,
                        MATCHED_BY_KEYWORD,
                        signature=normalized.get("licence_number"),
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
            # A licence line is long digit runs introduced by a `No.`, which
            # is exactly what the phone patterns look for. Measured: an FSSAI
            # licence number was reported as a consumer-care phone number.
            # Email is still read, because an address on such a line is
            # unambiguous.
            is_licence_line = bool(P.LICENCE_NUMBER_CONTEXT.search(line.text))

            emails = P.EMAIL.findall(line.text)
            toll_free = (
                [] if is_licence_line else P.TOLL_FREE_PHONE.findall(line.text)
            )
            mobiles = [] if is_licence_line else [
                number
                for number in P.MOBILE_PHONE.findall(line.text)
                if not any(number in tf for tf in toll_free)
            ]
            # Landlines are matched after the other two and de-duplicated
            # against them, because an STD-code pattern is the loosest of the
            # three and must not claim digits another pattern already read.
            landlines = [] if is_licence_line else [
                number
                for number in P.LANDLINE_PHONE.findall(line.text)
                if not any(number in other for other in [*toll_free, *mobiles])
            ]
            has_keyword = bool(P.CONTACT_KEYWORD.search(line.text))

            if not (emails or toll_free or mobiles or landlines or has_keyword):
                continue
            if has_keyword and not (emails or toll_free or mobiles or landlines):
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
                phones = [
                    normalise_text(p) for p in [*toll_free, *mobiles, *landlines]
                ]
                if phones:
                    values["phones"] = phones
                if has_keyword or toll_free or emails:
                    normalized = certain(**values)
                else:
                    # A bare ten-digit number with no keyword could belong to
                    # the manufacturer's address rather than to consumer care.
                    # A bare landline even more so - an STD code with no
                    # keyword is most often part of the printed address.
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
        for line in lines:
            for key_value, pattern in P.NAME_DECLARATIONS:
                match = pattern.search(line.text)
                if match is None:
                    continue
                value = normalise_text(match.group("value")).strip(
                    P.TRAILING_PUNCTUATION
                )
                if not value:
                    continue

                values: dict[str, Any] = {"name": value}
                if key_value == "other":
                    values["declaration"] = "marketed_by"
                # Always uncertain: a company name on a label runs onto the
                # following lines together with its address, and this extractor
                # reads one line. What we captured is a prefix of the
                # declaration, not necessarily the whole of it.
                found.append(
                    _candidate(
                        LabelFieldKey(key_value),
                        line,
                        uncertain(
                            "the name may continue onto following lines; the "
                            "address is not extracted",
                            **values,
                        ),
                        MATCHED_BY_KEYWORD,
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


def _quantity_on(text: str) -> dict | None:
    """The net quantity declared on one line, or None if there is none.

    This reads the **whole line** rather than the first thing on it that looks
    like a quantity, because a declaration line routinely carries more than one
    number and the first is often the wrong one.

    The case that forced this, from a real Dove carton:

        NET CONTENTS WHEN PACKED 4 UNITS X 125 g + 125 g FREE

    `QUANTITY.search` returns `4 UNITS` - the first match - and the old code
    committed to it, emitting `quantity: 4, unit: units, measure: count` with
    `uncertain: false`. A 625 g pack was recorded as a count of four, with no
    mass anywhere in the output and nothing to signal doubt.

    Three rules, in order:

    1. **A multipack form wins.** `4 UNITS X 125 g` is one declaration, not two
       numbers, and `MULTIPACK_QUANTITY` reads it as a count times a per-unit
       amount so the base quantity comes out right.
    2. **A measurable amount beats a bare count.** Where a line declares both,
       the mass or volume is the substantive net quantity; the count says how
       it is divided up. This alone is what stops `4 units` being the answer.
    3. **Disagreement is reported, not resolved.** If distinct measurable
       readings remain, or a bonus quantity is printed alongside the declared
       one, the reading is emitted uncertain with every candidate listed. Which
       number a `+ 125 g FREE` pack declares as its net quantity is a question
       about the declaration; picking one would be a guess wearing the
       appearance of a reading.
    """
    multipack = P.MULTIPACK_QUANTITY.search(text)
    if multipack is not None:
        normalized = normalise_quantity(
            multipack.group("value"),
            multipack.group("unit"),
            pack_count_text=multipack.group("pack"),
        )
        return _flag_bonus(normalized, text)

    readings = [
        (match, normalise_quantity(match.group("value"), match.group("unit"),
                                   pack_count_text=match.group("pack")))
        for match in P.QUANTITY.finditer(text)
    ]
    if not readings:
        return None

    measurable = [
        (match, normalized) for match, normalized in readings
        if normalized.get("measure") in ("mass", "volume")
    ]
    chosen = measurable or readings
    normalized = chosen[0][1]

    distinct = _distinct_quantities(chosen)
    if len(distinct) > 1:
        normalized = _mark_uncertain(
            normalized,
            f"{len(distinct)} different quantities are printed on this line "
            f"({', '.join(distinct)}); which one is the declared net quantity "
            f"cannot be determined from the text alone",
        )
        normalized = {**normalized, "candidates": distinct}

    return _flag_bonus(normalized, text)


#: Quantity keys withheld when the reading cannot be committed to.
#:
#: The same set `validation._VALUE_KEYS[NET_QUANTITY]` strips, and it has to
#: be: both exist to leave a net-quantity mapping with no committed value, and
#: a key present in one and missing from the other would leave a number behind
#: on one path and not the other - exactly the "withheld" reading that still
#: puts a quantity into the compliance record.
#:
#: `test_extraction_robustness.test_withheld_quantity_keys_match_validation`
#: asserts the two are equal, so adding a key to `normalise_quantity` without
#: adding it to both places fails rather than half-working.
_QUANTITY_VALUE_KEYS = (
    "quantity", "unit", "base_quantity", "base_unit", "measure", "pack_count",
)


def _flag_bonus(normalized: dict, text: str) -> dict:
    """Withhold the value when a bonus quantity shares the line.

    `500 g + 50 g free` may declare 500 g or 550 g, and `4 units x 125 g +
    125 g free` may declare 500 g or 625 g. The package knows which; the
    characters do not, and no ordering of the numbers on the line settles it.

    The value is **withheld rather than flagged**, which is stronger than what
    the rest of this module does for an uncertain reading, and deliberately so.
    A flagged-but-present net quantity still puts a specific number into the
    compliance record, and on the carton this was measured against every
    available number - 4, 125, 500, 625 - is wrong except one. Emitting the
    declaration with no committed quantity keeps `field_presence` correct (the
    package *does* declare a net quantity) while putting nothing in the record
    that a reviewer would have to catch.

    The candidates are listed, so the reviewer sees exactly what was printed.
    """
    if not P.BONUS_QUANTITY.search(text):
        return normalized

    candidates = _distinct_quantities(
        [(match, normalise_quantity(match.group("value"), match.group("unit"),
                                    pack_count_text=match.group("pack")))
         for match in P.QUANTITY.finditer(text)]
    )
    withheld = {
        name: value
        for name, value in normalized.items()
        if name not in _QUANTITY_VALUE_KEYS
    }
    withheld = _mark_uncertain(
        withheld,
        "a bonus or free quantity is printed alongside the declared one, so "
        "the net quantity may be the base amount or the total; no value is "
        "reported rather than guessing which",
    )
    if candidates:
        withheld["candidates"] = candidates
    return withheld


def _distinct_quantities(
    readings: list[tuple[re.Match[str], dict]]
) -> list[str]:
    """Human-readable distinct readings among `readings`, or [] if they agree."""
    seen: list[str] = []
    for _, normalized in readings:
        base = normalized.get("base_quantity")
        unit = normalized.get("base_unit") or normalized.get("unit")
        if base is None:
            base = normalized.get("quantity")
        if base is None:
            continue
        label = f"{base} {unit}".strip()
        if label not in seen:
            seen.append(label)
    return seen if len(seen) > 1 else []


def _batch_value(captured: str) -> str | None:
    """The batch code from a `BATCH_NUMBER` capture, or None if there is none.

    Two things go wrong with the raw capture, both measured on real packs:

    **The keyword's own suffix becomes the value.** `BATCH_NUMBER`'s
    `(?:no\\.?|number|code|#)?` group is optional, so on a pack printing
    `Batch No. :` with the value left blank, the group backtracks and the value
    group takes `No`. That produced `batch_number = "No"`, *certain*, for a
    package that declared no batch number at all.

    **The capture runs into adjacent text.** Allowing a second token is what
    lets `Batch No.: K BL28I50075` be read whole, and it is also what lets
    `Batch No: A123 Use` pick up a word that is not part of the code.

    Both are handled by walking the captured tokens and stopping at the first
    one that is label vocabulary rather than code. What survives must contain a
    digit: every batch and lot code on every pack this was measured against
    does, and requiring one is what rejects the OCR-damaged `Ni` that no
    stopword list would catch. A purely alphabetic code would be refused, and
    that is the intended direction of the trade - a missing batch number is a
    review flag, an invented one is a compliance pass.
    """
    tokens: list[str] = []
    for token in normalise_text(captured).split():
        cleaned = token.strip(P.TRAILING_PUNCTUATION)
        if not cleaned:
            break
        if cleaned.casefold() in P.DECLARATION_STOPWORDS:
            break
        tokens.append(cleaned)

    value = " ".join(tokens)
    if not value:
        return None
    if not any(character.isdigit() for character in value):
        return None
    return value


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
        # The single choke point every emitted field passes through. The
        # detectors guard their own patterns and those guards are the primary
        # defence; this is the one place a future detector cannot route around
        # by accident. See `validation`'s module docstring for why the
        # duplication is deliberate.
        normalized = validate(key, dict(best.normalized))

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

    A candidate carrying a value beats one carrying none, then keyword-anchored
    beats pattern-only, then committed beats uncertain, then higher OCR
    confidence, then earlier on the label. An unknown confidence sorts as if it
    were zero *for tie-breaking only* - that is an ordering convenience and is
    never written anywhere as a measured value.

    Value-presence leads, and it was not always first. A label printing

        For Feedback/Suggestions, Please Contact
        Phone No.: 022-71230555

    produces a keyword-anchored candidate carrying nothing from the first line
    and a pattern-only candidate carrying the number from the second. Ranking
    the keyword first meant the emitted field was the empty one, with the
    number visible only in `candidates`. "We saw the word 'contact'" is not a
    better-supported reading of a consumer-care declaration than the phone
    number itself.
    """
    return (
        1 if _carries_no_value(candidate) else 0,
        0 if candidate.matched_by == MATCHED_BY_KEYWORD else 1,
        1 if is_uncertain(candidate.normalized) else 0,
        -(candidate.confidence if candidate.confidence is not None else 0.0),
        candidate.line_index,
    )


def _carries_no_value(candidate: _Candidate) -> bool:
    """True when this reading located a declaration but committed to nothing.

    The same emptiness test `_conflicting_signatures` uses, so "cannot disagree
    with anything" and "loses to anything that has a value" stay one idea.
    """
    signature = candidate.signature
    return signature is None or signature == () or _is_all_none(signature)


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
