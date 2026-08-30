# LMPC 2011 — legal requirement inventory

What this file is: a record of **which requirements of the Legal Metrology
(Packaged Commodities) Rules, 2011 exist and are relevant to this project**, and
for each one, whether this software can evaluate it today.

What this file is **not**: a claim that any of them is implemented. Six rule
files exist in `definitions/`; two are evaluated. Everything else below is
inventoried, not built.

This separation is the point. It lets the project truthfully say *"we have
inventoried the applicable LMPC compliance requirements"* without implying
*"we have implemented every requirement"*.

**Source and provenance:** see [`SOURCES.md`](SOURCES.md). Every quotation below
is verbatim from the Department of Consumer Affairs consolidated publication
recorded there (SHA-256 `0ef948f9…f983a4b`), cross-checked against G.S.R. 128(E)
(13 Feb 2026) and G.S.R. 312(E) (27 Apr 2026). The amendment-chain gap and the
missing named human reviewer recorded in `SOURCES.md` apply to **every entry in
this file**.

## Status vocabulary

| Status | Meaning |
|---|---|
| `IMPLEMENTABLE_NOW` | Expressible with `field_presence` and the current taxonomy, with evidence the extractor actually produces. |
| `IMPLEMENTABLE_WITH_NEW_CHECK` | Legal text and evidence are available; needs a check type that does not exist. |
| `BLOCKED_BY_MISSING_APPLICABILITY_DATA` | The system does not collect the fact that decides whether the requirement applies. |
| `BLOCKED_BY_MISSING_EXTRACTION_FIELD` | The declaration is not in the extractor's supported set, so absence cannot be distinguished from "we never look for it". |
| `LEGAL_REVIEW_REQUIRED` | Wording or applicability needs a qualified human before any use. |
| `NOT_APPLICABLE_TO_PROJECT_SCOPE` | A real obligation, but not one a label-photograph checker can or should assess. |

## Extraction capability, as of this inventory

Taken from `labelextract.fields.SUPPORTED_KEYS` / `UNSUPPORTED_KEYS`, not from
documentation:

- **Supported:** `net_quantity`, `retail_sale_price`, `unit_sale_price`,
  `date_of_manufacture`, `date_of_packing`, `date_of_import`, `best_before`,
  `consumer_care_contact`, `country_of_origin`, `manufacturer_name`,
  `packer_name`, `importer_name`, `batch_number`, `other`
- **NOT supported:** `common_or_generic_name`, `manufacturer_address`

`unit_sale_price` entered the supported set on `feature/ml-label-extraction`
after this inventory was written. **That changed extraction capability and
nothing else.** Specifically:

- **Supported means attempted, not measured.** The key is newer than the frozen
  evaluation set, so all 28 of its cells score as `unknown` → excluded and
  there is **no precision, recall or value accuracy for it anywhere**. One
  correct reading on one panel is a demonstration, not a measurement. Read the
  supported list above as a statement about the extractor's code, never as a
  reliability claim.
- **No rule file names the key**, no status below was re-decided, and the rule
  6(11) entry is left for the rules owner to re-assess (see the note there).
- **No rule was activated on that branch.** `LM-PC-0002` and every other
  inactive rule remain `is_active: false`. Extraction capability and legal-rule
  activation are separate decisions, and this file's own contained-defect note
  above is the record of what happens when they are conflated.

`ProductCategory` holds three internal grouping codes only —
`packaged-commodity`, `packaged-food`, `packaged-non-food`. The system records
no net quantity, package capacity, commodity type, import status, buyer type or
principal-display-panel geometry as *applicability inputs*. That single fact
drives most of the `BLOCKED_BY_MISSING_APPLICABILITY_DATA` entries below.

Registered check types: `field_presence` only. Planned but **not registered**:
`value_check`, `format_check`, `numeric_check`, `conditional_check`,
`visual_check`.

---

## Defect found by this inventory — `LM-PC-0002` — CONTAINED, NOT FIXED

`LM-PC-0002` (rule 6(1)(b)) was shipped **active** and keyed on
`common_or_generic_name`, which is in `UNSUPPORTED_KEYS`. The extractor never
emits that field, and in production `ExtractedLabelField` rows come only from
extractor output, so for every readable label `check_field_presence` returned
`FAILED`. The rule reported a violation against every product, whatever the
package declared.

It was missed because the rule was checked against `LabelFieldKey` — the
*vocabulary* — rather than `SUPPORTED_KEYS` — the *capability*. The loader
validates the former and has no view of the latter.

**What is true of this branch:**

1. **The legal requirement exists.** Rule 6(1)(b) is real, verified, and
   quoted verbatim below. Nothing about the law is in doubt.
2. **The field is not currently safely extracted.** Identifying a common or
   generic name needs layout analysis the pattern-matching field layer does
   not do — it is the largest text on the front panel, which is a *layout*
   signal, not a keyword. See `ml/README.md`.
3. **Therefore the rule cannot safely be evaluated.** Its absence carries no
   information about the package.
4. **Activating it would create false `NON_COMPLIANT` results** — one against
   every product analysed.
5. **`LM-PC-0002` is `is_active: false`.** That is the *only* safeguard in
   place, and it is a containment measure, not a fix.

**What is NOT done here.** `field_presence` still cannot tell "the extractor
does not look for this declaration" apart from "the package does not declare
it". Any future rule keyed on an unextractable field would reproduce the same
false violation. Closing that properly means either

- teaching the extractor to read the declaration, so the key enters
  `SUPPORTED_KEYS`; or
- giving the check a per-run signal for what the engine actually attempted, so
  an unattempted key yields `INCONCLUSIVE` rather than `FAILED`.

Both are **separate tasks outside this inventory branch** — the first is ML
work, the second changes check behaviour. Neither is a legal decision:
reactivating `LM-PC-0002` needs extraction support, not legal review.

## Chapter I — Preliminary

### Rule 2(m) — definition of "retail sale price"

| | |
|---|---|
| **Requirement** | Definitional, not a declaration obligation. |
| **Quotation** | "'retail sale price' means the maximum price at which the commodity in packaged form may be sold to the consumer inclusive of all taxes;" |
| **Effective** | As substituted by G.S.R. 629(E), w.e.f. 1 Jan 2018 |
| **Evidence** | n/a — supports `LM-PC-0005` |
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | A definition. It constrains how rule 6(1)(e) is read; it is not separately enforceable. Recorded because `LM-PC-0005`'s wording depends on it. |

---

## Chapter II — Packages intended for retail sale

### Rule 3 — application of the Chapter

| | |
|---|---|
| **Requirement** | Chapter II does not apply to certain packages at all. |
| **Quotation** | "The provisions of this chapter shall not apply to- (a) packages of commodities containing quantity of more than 25 kilogram or 25 litre; (b) cement, fertilizer and agricultural farm produce sold in bags above 50 kilogram; and (c) packaged commodities meant for industrial consumers or institutional consumers." |
| **Applicability** | Gates **every** rule 4–23 requirement below. |
| **Effective** | As substituted by G.S.R. 629(E), w.e.f. 1 Jan 2018 |
| **Evidence** | Net quantity of the package; commodity type; buyer type |
| **Extraction** | Net quantity is extracted as a *label reading*, not as trusted applicability data. Buyer type is never known. |
| **Engine** | No — applicability is decided by `ProductCategory` alone |
| **check_type** | n/a (a scope gate, not a check) |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` |
| **Why** | The system cannot know whether a submission is a 30 kg sack or an institutional consignment. **Every active rule is therefore applied to some packages that are outside the Rules.** This is the single widest correctness caveat in the project and cannot be closed by any rule file. |

### Rule 4(1) — no pre-packing without the required declarations

| | |
|---|---|
| **Quotation** | "no person shall pre-pack or cause or permit to be pre-packed any commodity for sale, distribution or delivery unless the package in which the commodity is pre-packed bears thereon or on a label is securely affixed thereto, such declarations as are required to be made under these rules." |
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | A duty on the packer, discharged by complying with rules 6 onward. It adds no declaration this system could check independently; checking it *is* checking rule 6. |

### Rule 4(2) — promotional grouped packages

| | |
|---|---|
| **Quotation** | "When one or more packages intended for retail sale are grouped together for being sold as a retail package on promotional offer, every package of the group shall comply with provisions of rule 6." |
| **Effective** | Substituted by G.S.R. 779(E) / G.S.R. 226(E), w.e.f. 1 Oct 2022 |
| **Evidence** | Whether the submission is a promotional group, and a photograph of each constituent package |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` |
| **Why** | One `ProductImage` is one photograph. Nothing records that a submission is a promotional multipack or links the constituent packages. |

### Rule 5 — standard packages — **OMITTED**

| | |
|---|---|
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | "Rule 5 omitted vide GSR 779(E) dated 2nd November, 2021 w.e.f. 1.4.2022 (now w.e.f 01.10.2022 vide GSR 226(E) dated 28.3.2022)." No longer in force. Recorded so nobody re-derives it from an older copy of the Rules. |

### Rule 6(1) opening words — declaration must be definite, plain and conspicuous

| | |
|---|---|
| **Quotation** | "Every package shall bear thereon or on label securely affixed thereto, a definite, plain and conspicuous declaration made in accordance with the provisions of this chapter as, to-" |
| **Evidence** | Rendered appearance of the declaration |
| **check_type** | `visual_check` (planned, unregistered) |
| **Status** | `IMPLEMENTABLE_WITH_NEW_CHECK` |
| **Why** | "Definite, plain and conspicuous" is a presentation standard. `CheckContext.image` and `ExtractedLabelField.bounding_box` exist, so the inputs are there; the check type is not. Also `LEGAL_REVIEW_REQUIRED` — what counts as "conspicuous" is a judgement no threshold should be invented for. |

### Rule 6(1)(a) — manufacturer / packer / importer → `LM-PC-0001` (inactive)

| | |
|---|---|
| **Quotation** | "the name and address of the manufacturer, or where the manufacturer is not the packer, the name and address of the manufacturer and packer and for any imported package the name and address of the importer shall be mentioned." |
| **Exemption** | Explanation III: "In respect of packages containing food articles, the provisions of this clause shall not apply, but the provisions of, and the requirements specified in the Food Safety and Standards Act, 2006 (34 of 2006) and the rules made thereunder shall apply;" |
| **Effective** | 1 Jan 2018 (Explanation III as substituted by G.S.R. 629(E)) |
| **Evidence** | `manufacturer_name` **or** `packer_name` **or** `importer_name`; plus address |
| **Extraction** | Names supported. `manufacturer_address` **not** supported. |
| **Engine** | No — `field_presence` tests one key |
| **check_type** | A disjunction check (does not exist) |
| **Status** | `IMPLEMENTABLE_WITH_NEW_CHECK` |
| **Why** | The clause is disjunctive; a single-key check would fail a lawfully labelled imported package. The address half is additionally `BLOCKED_BY_MISSING_EXTRACTION_FIELD`. Food carve-out is expressible and already encoded. |

### Rule 6(1)(aa) — country of origin for imported products

| | |
|---|---|
| **Quotation** | "The name of the country of origin or manufacture or assembly in case of imported products shall be mentioned on the package;" |
| **Applicability** | Imported products only |
| **Effective** | Inserted by G.S.R. 629(E), w.e.f. 1 Jan 2018 |
| **Evidence** | `country_of_origin` — **supported** by the extractor |
| **Engine** | No — cannot express "this package is imported" |
| **check_type** | `conditional_check` |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` |
| **Why** | The evidence is available; the *trigger* is not. Import status is not a `ProductCategory` and is not recorded anywhere. Inferring it from the presence of `importer_name` would make the rule self-fulfilling: a package that omits both would look exempt. **This is the closest requirement to implementable — it needs one applicability input, not a new check.** |

### Rule 6(1)(b) — common or generic name → `LM-PC-0002` (active — **defective**)

| | |
|---|---|
| **Quotation** | "The common or generic names of the commodity contained in the package and in case of packages with more than one product, the name and number or quantity of each product shall be mentioned on the package." |
| **Exemptions** | None attached to this clause |
| **Effective** | 1 Apr 2011 |
| **Evidence** | `common_or_generic_name` |
| **Extraction** | **NOT supported** — in `UNSUPPORTED_KEYS` |
| **Engine** | Yes, mechanically — but on evidence that never arrives |
| **check_type** | `field_presence` |
| **Status** | `BLOCKED_BY_MISSING_EXTRACTION_FIELD` |
| **Why** | See the contained-defect note above. The rule is `is_active: false`, which is what currently prevents the false violation — the check itself still cannot distinguish an unextractable field from an absent declaration, so **reactivating it would restore the bug**. Unblocked by extraction work, not by a legal decision. |

### Rule 6(1)(c) — net quantity → `LM-PC-0003` (active)

| | |
|---|---|
| **Quotation** | "The net quantity, in terms of the standard unit of weight or measure, of the commodity contained in the package or where the commodity is packed or sold by number, the number of the commodity contained in the package shall be mentioned." |
| **Exemptions** | None attached to this clause (rule 3 / rule 26 gates apply) |
| **Effective** | 1 Apr 2011 |
| **Evidence** | `net_quantity` — **supported** |
| **check_type** | `field_presence` |
| **Status** | `IMPLEMENTABLE_NOW` — **implemented** |
| **Why** | Presence only. Whether the quantity is *correctly expressed* is rules 11–13, below. |

### Rule 6(1)(d) — month and year of manufacture → `LM-PC-0004` (inactive)

| | |
|---|---|
| **Quotation** | "The month and year in which the commodity is manufactured ~~or pre-packed or imported~~ shall be mentioned in the package:" — the struck words "shall be omitted vide GSR 779(E) dated 2nd November, 2021 w.e.f. 1.4.2022 (now w.e.f 01.10.2022 vide GSR 226(E) dated 28.3.2022)". |
| **Exemptions** | Food articles → FSS Act 2006; seeds certified under the Seeds Act 1966; cosmetics → Drugs and Cosmetics Rules 1945. Proviso (A): "no declaration as to the month and year … shall be required to be made on-- (i) any package containing bidi or incense sticks; (ii) any domestic liquefied petroleum gas cylinder of 14.2kg or 5kg, bottled and marketed by a public sector undertaking" |
| **Effective** | Current wording w.e.f. 1 Oct 2022 |
| **Evidence** | `date_of_manufacture` — **supported** |
| **check_type** | `conditional_check` |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` |
| **Why** | Food carve-out is expressible; cosmetics, seeds, bidi, incense sticks and LPG cylinders all sit inside `packaged-non-food` with no narrower category. |

### Rule 6(1)(da) — best before / use by

| | |
|---|---|
| **Quotation** | "If a package contains a commodity which may become unfit for human consumption after a period of time, the 'best before or use by the date, month and year' shall also be mentioned on the label: Provided that nothing in this clause shall apply if a provision in this regard is made in any other law." |
| **Effective** | Substituted by G.S.R. 629(E), w.e.f. 1 Jan 2018 |
| **Evidence** | `best_before` — **supported** |
| **check_type** | `conditional_check` |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` |
| **Why** | Triggered by a property of the commodity — "may become unfit for human consumption after a period of time" — that the system does not record. `packaged-food` is **not** a safe proxy: salt and sugar are food; many non-foods perish. The second proviso (displaced by any other law) is a further `LEGAL_REVIEW_REQUIRED` question. |

### Rule 6(1)(e) — retail sale price → `LM-PC-0005` (inactive)

| | |
|---|---|
| **Quotation** | "the retail sale price of the package;" + "shall clearly indicate that it is the maximum retail price inclusive of all taxes in Indian currency:" |
| **Exemptions** | Proviso (C): "no declaration as to the retail sale price shall be required to be made on (i) any package containing bidi; (ii) any domestic liquefied petroleum gas cylinder of which the price is covered under the Administrative Price Mechanism of the Government." Alcoholic beverages / spirituous liquor → State Excise Laws. Essential commodities with a notified price → G.S.R. 858(E). |
| **Effective** | Current wording w.e.f. 1 Oct 2022 |
| **Evidence** | `retail_sale_price` — **supported** |
| **check_type** | `conditional_check` for applicability; `format_check` for the manner of declaration |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` |
| **Why** | Bidi, LPG and alcohol are not separable in the current taxonomy. Separately, "clearly indicate … inclusive of all taxes in Indian currency" is a *format* requirement `field_presence` cannot express. |

### Rule 6(1)(f) — dimensions where sizes are relevant

| | |
|---|---|
| **Quotation** | "Where the sizes of the commodity contained in the package are relevant, the dimensions of the commodity contained in the package and if the dimensions of the different pieces are different, the dimensions of each such different piece shall be mentioned." |
| **Evidence** | No `LabelFieldKey` for dimensions |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` + `BLOCKED_BY_MISSING_EXTRACTION_FIELD` |
| **Why** | Both the trigger ("sizes are relevant") and the evidence are absent. Also `LEGAL_REVIEW_REQUIRED`: "relevant" is undefined in the Rules and rules 14–17 specify where it bites. |

### Rule 6(1)(g) — such other matter as specified in these rules

| | |
|---|---|
| **Quotation** | "such other matter as are specified in these rules:" |
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | A pointer, not a declaration. Its content is the other rules in this inventory. |

### Rule 6(1) proviso (B) — carry-over of pre-printed packaging material

| | |
|---|---|
| **Quotation** | "where any packaging material bearing thereon the month in which any commodity was expected to have been pre-packed is not exhausted during that month, such packaging material may be used for pre-packing the concerned commodity produced or manufactured during the next succeeding month and not there after…" with a proviso excluding food products whose 'Best before or Use before' period is ninety days or less. |
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | A permission about manufacturing practice over time, not a declaration on a package. Unverifiable from one photograph. |

### Rule 6(2) — consumer care details → `LM-PC-0006` (active)

| | |
|---|---|
| **Quotation** | "Every package shall bear the name, address, telephone number, e-mail address of the person who can be or the office which can be contacted, in case of consumer complaints." |
| **Effective** | Substituted by G.S.R. 385(E), effective 1 Jan 2016 (source records "dispensed upto 30.6.2016") |
| **Evidence** | `consumer_care_contact` — **supported** |
| **check_type** | `field_presence` for presence; a composite check for all four elements |
| **Status** | `IMPLEMENTABLE_NOW` (presence) — **implemented, partially** |
| **Why** | Presence is checked. Whether all four elements — name, address, telephone, e-mail — are present is not. Under-claims, which is the safe direction. |

### Rule 6(3) — stickers may not alter required declarations

| | |
|---|---|
| **Quotation** | "It shall not be permissible to affix individual stickers on the package for altering or making declaration required under these rules: Provided that for reducing the Maximum Retail Price (MRP), a sticker with the revised lower MRP (inclusive of all taxes) may be affixed and the same shall not cover the MRP declaration made by the manufacturer or the packer…" |
| **Evidence** | Whether a declaration is on a sticker, and whether it covers the original |
| **check_type** | `visual_check` |
| **Status** | `IMPLEMENTABLE_WITH_NEW_CHECK` + `LEGAL_REVIEW_REQUIRED` |
| **Why** | Detecting an overlaid sticker from a photograph is a research problem, not a check-type gap. Listed because it is a real and commonly contravened obligation. |

### Rule 6(4) and 6(4A) — permitted additional declarations

| | |
|---|---|
| **Quotation** | 6(4A): "Nothing in this rule shall preclude a manufacturer or packer or importer to declare the following on the package, in addition to the mandatory declarations- (a) Barcode or GTIN or QR Code; (b) 'e-code' … (c) logos of Government schemes…" |
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | Permissive. Nothing to fail. |

### Rule 6(5) — multi-component packages

| | |
|---|---|
| **Quotation** | "Where a commodity consists of a number of components and these components are packed in two or more units, for sale as a single commodity, the declaration required to be made under sub-rule (1) shall appear on the main package and such package shall also carry information about the other accompanying packages…" |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` |
| **Why** | Requires knowing that a submission is a multi-unit commodity and which photograph is the main package. Not modelled. |

### Rule 6(6) — exhaustion of old wrappers — spent

| | |
|---|---|
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | A transitional permission expiring "upto 31st March 2012". Long spent. |

### Rule 6(7) — "GM" on genetically modified food

| | |
|---|---|
| **Quotation** | "Every package containing the genetically modified food shall bear at the top of its principle display panel the words 'GM'." |
| **Effective** | Inserted by G.S.R. 427(E), w.e.f. 1 Jan 2013 |
| **Evidence** | No `LabelFieldKey`; also requires PDP position |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` + `BLOCKED_BY_MISSING_EXTRACTION_FIELD` |
| **Why** | Whether a food is genetically modified is not knowable from a photograph, and "at the top of the principal display panel" is a `visual_check`. |

### Rule 6(8) — veg / non-veg dot on cosmetics and toiletries

| | |
|---|---|
| **Quotation** | "Every package containing soaps, shampoos, tooth pastes and other cosmetics and toiletries shall bear at the top of its principal display panel a red or, as the case may be, brown dot for products of non-vegetarian origin and a green dot for products of vegetarian origin." |
| **Effective** | Inserted by G.S.R. 137 dated 15 Jun 2014, w.e.f. 1 Jul 2014 |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` |
| **Why** | Needs a cosmetics/toiletries category, colour detection and PDP geometry. Notable as a requirement a `visual_check` could genuinely reach once a category exists. |

### Rule 6(9) — labels on imported packages

| | |
|---|---|
| **Quotation** | "it shall be permissible to affix a label on imported packages for making the declarations required under these rules." |
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | Permissive. |

### Rule 6(10) and 6(10A) — e-commerce display and country-of-origin filter

| | |
|---|---|
| **Quotation** | 6(10): "An E-Commerce entity shall ensure that the mandatory declarations … except the month and year in which the commodity is manufactured or packed, shall be displayed on the digital and electronic network used for e-commerce transactions". 6(10A), as substituted by G.S.R. 312(E): "Every e-commerce entity offering for sale any imported product shall, with effect from the 1st day of July, 2027, ensure that the product listing of such imported product contains a searchable and sortable filter specifying the country of origin." |
| **Effective** | 6(10A) inserted by G.S.R. 128(E) w.e.f. 1 Jul 2026; substituted by G.S.R. 312(E) w.e.f. 1 Jul 2027 |
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | Obligations on an e-commerce listing, not on a physical package. This system analyses photographs of packages. Recorded because it is the most recently amended part of rule 6 and a reader will look for it. |

### Rule 6(11) — unit sale price

| | |
|---|---|
| **Quotation** | "The unit sale price shall be declared as- (i) 'Rs. _ per g' for pre-packaged commodities with net quantity of commodity …" with "Provided further that declaration of unit sale price is not required for the pre-packaged commodities in which retail sale price is equal to the unit sale price." |
| **Evidence** | `unit_sale_price` — the extractor now **attempts** this declaration (keyword-anchored; the printed unit is reported, never converted). Attempted is not the same as reliable: the key is newer than the frozen evaluation set, so **no precision or recall figure exists for it** |
| **check_type** | `format_check` + `numeric_check` (the format depends on the net-quantity band, and the exemption is an arithmetic comparison) — **neither is registered** |
| **Status** | `BLOCKED_BY_MISSING_EXTRACTION_FIELD` — **unchanged, and still correct as a bottom line.** The extraction half has moved and needs a rules-owner re-assessment; the requirement remains unevaluable either way |
| **Why** | **This requirement still cannot be evaluated, and extraction work did not change that.** What changed on `feature/ml-label-extraction` is only that the extractor now attempts the declaration — one panel of the frozen set reads as `Rs.2.91 per gram`, which demonstrates the detector runs and measures nothing, because that set does not annotate this key. Everything that makes the requirement unevaluable stands untouched: deciding the required *form* needs the net-quantity band, the "not required where retail sale price equals unit sale price" proviso is an arithmetic comparison, and `format_check` and `numeric_check` remain unregistered. Applicability and format are the rules layer's to decide; the extractor supplies evidence and makes no claim about whether a declaration was required or correctly expressed. The status line was **not** re-decided here — that is a legal-inventory judgement for the rules owner, not an ML change — and no rule file was created or activated. **Note it is rule 6(11), not a clause of rule 6(1)** — a common mis-citation. |

### Rule 7 — principal display panel: area, size of numerals and letters

| | |
|---|---|
| **Quotation** | 7(3): "The width of the letter or numeral shall not be less than one third of its height, except in the case of numeral '1' and letters (i), ( I) and ( );" — with Table-I fixing minimum heights against PDP area bands. |
| **Effective** | As substituted by G.S.R. 629(E) w.e.f. 1 Jan 2018; Table-I corrected by G.S.R. 1373(E) dated 7 Nov 2017 |
| **Evidence** | PDP area, and rendered glyph height and width |
| **check_type** | `visual_check` |
| **Status** | `IMPLEMENTABLE_WITH_NEW_CHECK` |
| **Why** | **The most tractable of the visual requirements**: Table-I is objective and numeric, `ExtractedLabelField.bounding_box` gives glyph geometry and `CheckContext.image` gives the source. It still needs PDP area (rule 7(4) gives the formula per package shape, which needs the package shape) and a real millimetre scale, which a photograph does not carry. The 2025 amendment additionally makes the Medical Devices Rules, 2017 prevail for medical devices — a further applicability input. |

### Rule 8(1) — declarations appear on the principal display panel

| | |
|---|---|
| **Quotation** | "Every declaration required to be made under these rules shall appear on the principal display panel. Provided that the area surrounding the quantity declaration shall be free from printed information. (a) above and below by a space equal to at least the height of the numeral in the declaration, and (b) to the left and right by a space at least twice the height of numeral in the declaration." |
| **check_type** | `visual_check` |
| **Status** | `IMPLEMENTABLE_WITH_NEW_CHECK` |
| **Why** | The clear-space proviso is expressed purely in multiples of the numeral height, so it is computable from bounding boxes without a millimetre scale — arguably the single most implementable visual requirement in the Rules. Identifying *which* face is the principal display panel remains open. |

### Rule 9(1)(a) — legible and prominent

| | |
|---|---|
| **Quotation** | "Every declaration which is required to be made on a package under these rules shall be -- (a) legible and prominent;" |
| **check_type** | `visual_check` (planned, unregistered) |
| **Status** | `IMPLEMENTABLE_WITH_NEW_CHECK` + `LEGAL_REVIEW_REQUIRED` |
| **Why** | The Rules set no numeric threshold for "legible and prominent"; rules 7 and 8 supply the measurable proxies. Implementing this directly would mean inventing a threshold — which is exactly what this project forbids. Should be approached through rules 7 and 8, not on its own. |

### Rule 9(1)(b) — contrasting colour for price and quantity numerals

| | |
|---|---|
| **Quotation** | "numerals of the retail sale price and net quantity declaration shall be printed, painted or inscribed on the package in a colour that contrasts conspicuously with the background of the label" — with provisos for blown/formed/moulded information and for hand-written declarations. |
| **check_type** | `visual_check` |
| **Status** | `IMPLEMENTABLE_WITH_NEW_CHECK` |
| **Why** | Contrast is measurable from pixels within a bounding box. "Contrasts conspicuously" has no numeric threshold in the Rules → `LEGAL_REVIEW_REQUIRED` before any figure is adopted. |

### Rule 9(2) — declaration not to be read through a liquid

| | |
|---|---|
| **Quotation** | "No declaration shall be made so as to require it to be read through any liquid commodity contained in the package." |
| **Status** | `IMPLEMENTABLE_WITH_NEW_CHECK` + `LEGAL_REVIEW_REQUIRED` |
| **Why** | Would require inferring package construction from an image. Recorded for completeness. |

### Rule 9(3) — outer container or wrapper

| | |
|---|---|
| **Quotation** | "Where a package is provided with an outside container or wrapper such container or wrapper shall also contain all the declarations which are required to appear on the package except where such container or wrapper itself is transparent and the declarations on the package itself are easily readable through such outside wrapper." + "Provided that no such declarations on the inner package is required, if the outer package contains all declarations required under these rules." |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` |
| **Why** | Needs to know whether the photographed item is an inner or outer package. Not modelled. |

### Rule 9(4) — language

| | |
|---|---|
| **Quotation** | "The particulars of the declarations required to be specified under this rule on a package shall either be in Hindi in Devnagri script or in English: Provided that nothing contained in this sub-rule shall prevent the use of any other language in addition to Hindi or English language." |
| **Evidence** | Script/language of the recognised text |
| **check_type** | `format_check` |
| **Status** | `IMPLEMENTABLE_WITH_NEW_CHECK` |
| **Why** | Detecting Devanagari or Latin script is tractable. But the OCR is **English-only**, so a wholly Hindi label would read as unreadable rather than as compliant — reporting that as a violation would be exactly backwards. Must not be attempted before the extractor handles Devanagari. |

### Rule 10(1) — name and complete address, conspicuously

| | |
|---|---|
| **Quotation** | "Subject to the provisions of rule 6, every package … shall bear conspicuously on it, the name and complete address of the manufacturer, or where the manufacturer is not the packer, the name and address of the manufacturer and the packer and in case of imported packages, the name and address of the importer" — with a proviso for packages of 10 cubic cm or less, and Explanation 1 defining 'complete address'. |
| **Effective** | As substituted by G.S.R. 629(E) w.e.f. 1 Jan 2018 |
| **Evidence** | `manufacturer_address` — **NOT supported** |
| **Status** | `BLOCKED_BY_MISSING_EXTRACTION_FIELD` |
| **Why** | This is the *address* obligation that rule 6(1)(a) references. It is the operative provision for completeness of the address, and the extractor explicitly does not read addresses. The 10 cubic cm proviso is additionally missing applicability data (package capacity). |

### Rule 10(2) — corporate name

| | |
|---|---|
| **Quotation** | "The name of the manufacturer or packer or importer shall be the actual corporate name, or if not incorporated, the name under which the business is conducted by such manufacturer or packer or importer in India." |
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | Verifying a name is the actual corporate name requires a companies register, not a photograph. |

### Rule 11 — general provisions on declaring quantity

| | |
|---|---|
| **Quotation** | 11(1): "In declaring the net quantity of the commodity contained in a package, the weight of wrappers and materials other than the commodity shall be excluded." 11(2)/(3): the declaration "shall not be qualified by the words 'when packed' or the like". 11(4): commodities in the Third Schedule may be so qualified. |
| **Evidence** | The declared quantity string; physical weighing for 11(1) |
| **check_type** | `format_check` for the "when packed" prohibition |
| **Status** | 11(1) `NOT_APPLICABLE_TO_PROJECT_SCOPE` (requires weighing the goods); 11(2)–(4) `IMPLEMENTABLE_WITH_NEW_CHECK` |
| **Why** | Detecting the qualifier "when packed" in the net-quantity string is a straightforward text check, but knowing whether the commodity is in the Third Schedule is missing applicability data. |

### Rule 12 — manner of declaring quantity

| | |
|---|---|
| **Quotation** | 12(2): "the declaration of quantity shall be in terms of the unit of - (a) mass, if the commodity is solid, semi-solid, viscous …; (b) length …; (c) area …; (d) volume …; or (e) number …". 12(6): the declaration "shall not contain any word or expression … which tends to create or is likely to create an exaggerated, misleading or inadequate expression as to the quantity". 12(7): packages of ten cubic cm or less may declare on a tag or card. |
| **Evidence** | The declared quantity string; the physical state of the commodity |
| **check_type** | `format_check` |
| **Status** | `IMPLEMENTABLE_WITH_NEW_CHECK` for 12(6) (a prohibited-word list is objective and appears verbatim in the pre-2011 text: 'minimum', 'not less than', 'average', 'about', 'approximately'); `BLOCKED_BY_MISSING_APPLICABILITY_DATA` for 12(2) (requires knowing whether the commodity is solid, liquid or sold by number) |
| **Why** | 12(6) is the most implementable non-presence requirement in the Rules that needs no new applicability input. |

### Rule 13 — units of weight, measure or number

| | |
|---|---|
| **Quotation** | 13(4): "No number called the dozen, score, gross, great gross or the like shall be specified or indicated on any package." 13(5)(i): "No system of units other than the International System of Units shall be used in furnishing the net quantity of the packages". 13(5)(ii), as substituted w.e.f. 1 Oct 2022: "for items sold by number, the number or unit or piece or pair or set or such other word which represents the quantity in the package shall be mentioned." 13(2)/(3): which unit to use below and above one kilogram, metre, litre etc. 13(6): supplementary declaration for multiple like packages. |
| **Evidence** | The declared quantity string |
| **check_type** | `format_check` |
| **Status** | `IMPLEMENTABLE_WITH_NEW_CHECK` |
| **Why** | **The strongest candidate for the next real rule after a `format_check` exists.** 13(2)–(5) are objective, purely textual, need no applicability input beyond the declared value itself, and the evidence (`net_quantity`) is already extracted. Detecting "dozen" or a non-SI unit such as "oz" in the net-quantity string requires no judgement. |

### Rules 14–17 — dimension declarations for specific commodity classes

| | |
|---|---|
| **Quotation** | Rule 14: "Where a package contains commodities like bed-sheets, hemmed fabric materials, dhoties, sarees, napkins, pillow-covers, towels, table cloths or similar other commodities, the number and the dimensions of finished size of such commodities shall also be declared…". Rule 15: dimensions where they have "a relationship to the price". Rule 16: "the number of usable sheets … and the dimensions of each such sheet" for aluminium foil, facial tissues, waxed paper, toilet paper. Rule 17: declaration form for bag-, box-, cup- and pan-type container commodities. |
| **Evidence** | No `LabelFieldKey` for dimensions or sheet count |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` + `BLOCKED_BY_MISSING_EXTRACTION_FIELD` |
| **Why** | Each is triggered by a named commodity class the taxonomy does not have, and none of the evidence is extracted. These are the operative provisions behind rule 6(1)(f). Rule 14's "or similar other commodities" is additionally `LEGAL_REVIEW_REQUIRED`. |

### Rule 18 — duties of wholesale and retail dealers

| | |
|---|---|
| **Quotation** | 18(2): "No retail dealer or other person including manufacturer, packer, importer and wholesale dealer shall make any sale of any commodity in packed form at a price exceeding the retail sale price thereof." 18(2A): no different MRPs on an identical pre-packaged commodity by restrictive or unfair trade practices. |
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | Conduct obligations about the price actually charged and about pricing across identical goods. Neither is visible on a single package photograph. 18(2A) would need cross-product comparison the system does not do. |

### Rules 19–23 — inspection, sampling and permissible error

| | |
|---|---|
| **Scope** | Procedures for inspection at manufacturer, packer, wholesale and retail premises; maximum permissible error; deceptive packages. |
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | Enforcement procedure for Legal Metrology officers, requiring physical sampling and weighing per the First, Fifth and Sixth Schedules. Nothing here is assessable from a photograph, and this software is not an enforcement instrument. |

---

## Chapter III — Wholesale packages

### Rule 24 — declarations on every wholesale package

| | |
|---|---|
| **Quotation** | "Every wholesale package shall bear thereon a legible, definite, plain and conspicuous declaration as to - (a) The name and address of the manufacturer or importer or where the manufacturer or importer is not the packer, of the packer; (b) the identity of the commodity contained in the package; and (c) the total number of retail package contained in such wholesale package or the net quantity in terms of standard units of weights, measures or number…" with a proviso where another law requires a similar declaration. |
| **Evidence** | Names supported; identity of commodity ≈ `common_or_generic_name` (**not** supported) |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` |
| **Why** | A *smaller and more tractable* declaration set than rule 6 — but the system cannot tell a wholesale package from a retail one, and the two rule sets are mutually exclusive. Applying rule 6 to a wholesale package, which this system currently would, is a false-positive source. Needs a retail/wholesale applicability input. |

---

## Chapter IV — Export packages

### Rule 25 — restriction on sale of export packages in India

| | |
|---|---|
| **Quotation** | "An export package shall not be sold in India unless the manufacturer or packer has re-packed or relabeled the commodity in accordance with the provisions contained in Chapter II…" |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` |
| **Why** | Requires knowing the package is an export package offered for sale in India. |

---

## Chapter V — Exemptions

### Rule 26 — exemption in respect of certain packages

| | |
|---|---|
| **Quotation** | "Nothing contained in these rules shall apply to any package containing a commodity if-- (a) the net weight or measure of the commodity is ten gram or ten millilitre or less, if sold by weight or measure;" — with a proviso, inserted by G.S.R. 385(E) w.e.f. 1 Jul 2016, that clause (a) does not apply to tobacco and tobacco products; "(b) any package containing fast food items packed by restaurant or hotel and the like; (c) it contains scheduled formulations and non-scheduled formulations covered under the Drugs (Price Control) Order, 2013 … Provided that no exemption shall be applicable to medical devices declared as drugs;" and thread sold in coil to handloom weavers. |
| **Effective** | Clause (c) as substituted and clause (d) omitted by G.S.R. 629(E) w.e.f. 1 Jan 2018 |
| **Applicability** | Gates **every** rule in this inventory |
| **Status** | `BLOCKED_BY_MISSING_APPLICABILITY_DATA` |
| **Why** | Like rule 3, this is a scope gate no rule file can encode. A 10 g sachet, a restaurant takeaway box and a DPCO-covered medicine are all outside the Rules entirely, and all three would currently be evaluated against the active rules. |

---

## Chapter VI — Registration

### Rules 27–30 — registration of manufacturers, packers and importers

| | |
|---|---|
| **Scope** | Application for registration with the Director or Controller, fees, shorter address, compilation and circulation of lists. |
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | Administrative registration with a regulator. Nothing on the package evidences it, and rule 32(1) prices contravention separately. |

---

## Chapter VII — General

### Rule 31 — advertisements mentioning retail sale price

| | |
|---|---|
| **Quotation** | "(1) Any advertisement mentioning the retail sale price of the pre-packaged commodity shall contain a declaration as to the net quantity or number of the commodity contained in the package. (2) The font size of the net quantity in the advertisement shall be same as that of retail sale price." |
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | Governs advertisements, not packages. This system analyses package photographs. |

### Rule 32 — penalties and compounding

| | |
|---|---|
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | Sanctions. This system does not and must not compute penalties: the project's stated position is that it assists a human reviewer and makes no legal determination. Attaching a rupee figure to a finding would contradict that directly. |

### Rule 33 — power to relax

| | |
|---|---|
| **Quotation** | "The Central Government may … permit a manufacturer or packer to pack for sale the packages for a reasonable period by relaxing one or more provision of these Rules with such corrective measures as may be specified." |
| **Status** | `LEGAL_REVIEW_REQUIRED` |
| **Why** | **A relaxation granted under rule 33 makes an otherwise-correct finding wrong.** The system has no way to know one exists. Every finding it produces is therefore conditional on no relaxation applying — a caveat that belongs in the user-facing output, not only here. The 2025 amendment further provides that rule 33 relaxations do not apply where the Medical Devices Rules, 2017 apply. |

### Rule 34 — repeal and savings

| | |
|---|---|
| **Status** | `NOT_APPLICABLE_TO_PROJECT_SCOPE` |
| **Why** | Repeals the Standards of Weights and Measures (Packaged Commodities) Rules, 1977. |

---

## Roll-up

| Status | Count | Entries |
|---|---:|---|
| `IMPLEMENTABLE_NOW` | 2 | 6(1)(c) net quantity; 6(2) consumer care (presence only) — the only two evaluated |
| `IMPLEMENTABLE_WITH_NEW_CHECK` | 11 | 6(1) opening words; 6(1)(a); 6(3); 7; 8(1); 9(1)(a); 9(1)(b); 9(2); 9(4); 11(2)–(4); 12(6); 13 |
| `BLOCKED_BY_MISSING_APPLICABILITY_DATA` | 14 | 3; 4(2); 6(1)(aa); 6(1)(d); 6(1)(da); 6(1)(e); 6(1)(f); 6(5); 6(7); 6(8); 9(3); 12(2); 14–17; 24; 25; 26 |
| `BLOCKED_BY_MISSING_EXTRACTION_FIELD` | 4 | 6(1)(b) **(active — defective)**; 6(11); 10(1); 14–17 |
| `LEGAL_REVIEW_REQUIRED` | 5 | 6(1) opening words; 9(1)(a); 9(1)(b); 14; 33 |
| `NOT_APPLICABLE_TO_PROJECT_SCOPE` | 15 | 2(m); 4(1); 5; 6(1)(g); 6(1) proviso (B); 6(4)/(4A); 6(6); 6(9); 6(10)/(10A); 10(2); 11(1); 18; 19–23; 27–30; 31; 32; 34 |

Entries appear under more than one status where more than one thing blocks them.

## What would unblock the most, in order

1. **Applicability inputs on `Product`** — declared net quantity, commodity
   type, import status, retail/wholesale, buyer type. This alone unblocks
   6(1)(aa), 6(1)(d), 6(1)(e), 6(1)(da), 24, and narrows the rule 3 / rule 26
   over-application. It is the single highest-value change and needs a schema
   decision, which is why it is not made here.
2. **`format_check`** — unblocks rule 13 and rule 12(6) immediately, on
   evidence already extracted.
3. **A disjunction check** — unblocks 6(1)(a).
4. **Extracting `common_or_generic_name`** — a prerequisite for reactivating
   `LM-PC-0002`, and unblocks part of rule 24. **Entry into `SUPPORTED_KEYS` is
   necessary and not sufficient, and this entry originally implied otherwise.**
   `feature/ml-label-extraction` measured the only anchor a pattern layer could
   use — `COMMODITY :`, `Name of Commodity`, `Generic Name` — across the 674
   lines the current pipeline reads from the 28 frozen photographs: it appears
   on **1 panel of 28**. A detector at that recall would satisfy the letter of
   the condition above while leaving absence of the field just as uninformative
   as it is today, and reactivating on the strength of it would restore the
   false violation on 27 of 28 panels. Whatever closes this must come with a
   measured recall figure, not merely a key in a set.
5. **`visual_check` plus PDP geometry** — unblocks rules 7 and 8, and only then
   should rule 9(1)(a) be approached through them.
