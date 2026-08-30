# Legal sources for the rules in `definitions/`

`rules/README.md` says every rule must carry where it came from and whether
that source has been verified. This file is the long form of that record: what
was consulted, how it was retrieved, what it says, and — just as importantly —
what could **not** be established.

Nothing in this file is a paraphrase of a legal requirement. Requirement text
that appears in a rule file is either quoted verbatim from the source named
below, or is a plain-language restatement placed in `requirement` with the
verbatim wording preserved alongside it in `source_note`.

## Primary source

| | |
|---|---|
| Document | *Book on Legal Metrology Packaged Commodities Rules, 2011 with all amendments* |
| Publisher | Department of Consumer Affairs, Ministry of Consumer Affairs, Food and Public Distribution, Government of India |
| URL | `https://consumeraffairs.gov.in/public/upload/admin/cmsfiles/whatsnews/Book_on_Legal_Metrology_Packaged_Commodities_Rules,2011_with_all_amendments_whatsnews.pdf` |
| SHA-256 | `0ef948f9c6b89f5dfb20d384861901714fd0dc54fc67b5b86c772d2c3f983a4b` |
| Size | 978,073 bytes |
| Server `Last-Modified` | 2025-04-14 12:18:18 GMT |
| Retrieved | 2026-08-30 |
| Retrieved by | Claude Code (automated legal-source check) for raghavrrrao |

The principal rules are G.S.R. 202(E) dated 7 March 2011, in force from
1 April 2011. This publication reproduces the principal rules with each
amendment shown against the clause it changes.

### Corroborating primary sources

Two Gazette notifications were retrieved directly and read in full, to confirm
that the most recent amendments do not touch the clauses used here:

- **G.S.R. 128(E)**, 13 February 2026 — Legal Metrology (Packaged Commodities)
  Amendment Rules, 2026, in force 1 July 2026. Inserts rule 6(**10A**) only
  (country-of-origin filter on e-commerce listings).
  `https://consumeraffairs.gov.in/public/upload/files/2026.02.13%20PCR%201st%20COO%20Filter%20on%20e-commerce%20websites_1771231030.pdf`
- **G.S.R. 312(E)**, 27 April 2026 — Second Amendment Rules, 2026, in force
  1 July 2027. Substitutes rule 6(**10A**) only.
  `https://consumeraffairs.gov.in/public/upload/files/2026.4.27%20PCR%202nd%20COO%20from%201.7.2027_1777348487.pdf`

Neither amends rule 6(1)(a)–(g) or rule 6(2).

The Legal Metrology (Packaged Commodities) Amendment Rules, 2025 were checked
via the Press Information Bureau release of 29 October 2025 (PRID 2183777).
That amendment harmonises the rules with the Medical Devices Rules, 2017 for
the height and width of numerals and letters, for rule 33 relaxations and for
principal-display-panel placement. The release states expressly that "the
requirement to make mandatory declarations remains". It does not change which
declarations rule 6(1) or rule 6(2) require.

## Retrieval note (read this before re-verifying)

Several official hosts were unreachable from the machine this check ran on:

- `consumeraffairs.nic.in` — connection refused (`164.100.117.174:443`)
- `doca.gov.in`, `iilm.gov.in`, `megweights.gov.in` — TLS certificate expired
  or handshake failure
- `cwnm.nic.in` — connection timeout

`consumeraffairs.gov.in` served the primary source over TLS validated against
the Windows trust store. It failed validation in one HTTP client whose trust
store lacked the intermediate certificate; the same bytes were retrieved
successfully with `curl`, and the SHA-256 above pins exactly what was read.

## Amendment-chain gap — OPEN, needs a human

The primary source's own footnotes stop at **G.S.R. 226(E), 28 March 2022**.
The February 2026 Gazette notification states that the principal rules were
"last amended vide number G.S.R. 881(E), dated 2nd December, 2025".

So there is a window — amendments notified between 28 March 2022 and
2 December 2025, which includes an amendment dated 6 October 2023 — that the
primary source's annotations do not cover, and whose Gazette texts could not
be retrieved because the hosts carrying them were unreachable.

Two things reduce, but do not close, the risk:

1. The primary source was published on the Department's own server on
   **2025-04-14**, i.e. after the October 2023 amendment, and it presents
   rule 6(1)(a)–(g) and rule 6(2) as reproduced below.
2. The two 2026 Gazette notifications and the 2025 amendment, all read
   directly, touch rule 6(10A), rule 7, rule 33 and PDP placement — not the
   substance of rule 6(1) or rule 6(2).

**A named human reviewer must still confirm the 2022–2025 amendment chain
against the Gazette before these rules are relied on.** Until then, treat the
`verified` status on these rules as "verified against the Department's own
consolidated publication", not "verified against every notification in force".

## Clause-by-clause record

Quoted verbatim from the primary source.

### Rule 6(1) — opening words

> Every package shall bear thereon or on label securely affixed thereto, a
> definite, plain and conspicuous declaration made in accordance with the
> provisions of this chapter as, to-

### Rule 6(1)(a) — manufacturer, packer, importer → `LM-PC-0001`

> the name and address of the manufacturer, or where the manufacturer is not
> the packer, the name and address of the manufacturer and packer and for any
> imported package the name and address of the importer shall be mentioned.

Explanation III, as substituted vide G.S.R. 629(E) dated 23 June 2017 w.e.f.
1 January 2018:

> In respect of packages containing food articles, the provisions of this
> clause shall not apply, but the provisions of, and the requirements specified
> in the Food Safety and Standards Act, 2006 (34 of 2006) and the rules made
> thereunder shall apply;

### Rule 6(1)(aa) — country of origin (not implemented)

Inserted vide G.S.R. 629(E) dated 23 June 2017 w.e.f. 1 January 2018:

> The name of the country of origin or manufacture or assembly in case of
> imported products shall be mentioned on the package;

Applies to imported products only. No category or check in this repository can
express "this package is imported", so no rule file was created.

### Rule 6(1)(b) — common or generic name → `LM-PC-0002`

> The common or generic names of the commodity contained in the package and in
> case of packages with more than one product, the name and number or quantity
> of each product shall be mentioned on the package.

No proviso, explanation or exemption attaches to this clause.

### Rule 6(1)(c) — net quantity → `LM-PC-0003`

> The net quantity, in terms of the standard unit of weight or measure, of the
> commodity contained in the package or where the commodity is packed or sold
> by number, the number of the commodity contained in the package shall be
> mentioned.

No proviso, explanation or exemption attaches to this clause.

### Rule 6(1)(d) — month and year → `LM-PC-0004`

As printed, with the source's amendment annotation:

> The month and year in which the commodity is manufactured or pre-packed or
> imported shall be mentioned in the package:

> the words, - "or pre-packed or imported" shall be omitted vide GSR 779(E)
> dated 2nd November, 2021 w.e.f. 1.4.2022 (now w.e.f 01.10.2022 vide GSR
> 226(E) dated 28.3.2022).

**The clause in force therefore covers month and year of manufacture only.**

Provisos: food articles are governed by the Food Safety and Standards Act,
2006; seeds labelled and certified under the Seeds Act, 1966 are excluded;
cosmetics products are governed by the Drugs and Cosmetics Rules, 1945.

Proviso (A) to rule 6(1):

> no declaration as to the month and year in which the commodity is
> manufactured or pre-packed shall be required to be made on--
> (i) any package containing bidi or incense sticks;
> (ii) any domestic liquefied petroleum gas cylinder of 14.2kg or 5kg, bottled
> and marketed by a public sector undertaking;

### Rule 6(1)(da) — best before / use by (not implemented)

Substituted vide G.S.R. 629(E) dated 23 June 2017 w.e.f. 1 January 2018:

> If a package contains a commodity which may become unfit for human
> consumption after a period of time, the 'best before or use by the date,
> month and year' shall also be mentioned on the label:
>
> Provided that nothing in this clause shall apply if a provision in this
> regard is made in any other law.

Conditional on the commodity being one that "may become unfit for human
consumption after a period of time" — a property of the commodity, not of the
category. No rule file was created.

### Rule 6(1)(e) — retail sale price → `LM-PC-0005`

> the retail sale price of the package;

Substituted words, vide G.S.R. 629(E) dated 23 June 2017 w.e.f. 1 January 2018
and further amended vide G.S.R. 779(E) / G.S.R. 226(E):

> shall clearly indicate that it is the maximum retail price inclusive of all
> taxes in Indian currency:

Rule 2(m), as substituted vide G.S.R. 629(E):

> "retail sale price" means the maximum price at which the commodity in
> packaged form may be sold to the consumer inclusive of all taxes;

Proviso to clause (e):

> Provided that for packages containing alcoholic beverages or spirituous
> liquor, the State Excise Laws and the rules made there under shall be
> applicable within the State in which it is manufactured and where the state
> excise laws and rules made there under do not provide for declaration of
> retail sale price, the provisions of these rules shall apply.

Proviso inserted vide G.S.R. 858(E) dated 7 September 2016:

> Provided further that if the retail sale price of any essential commodity is
> fixed and notified by the Competent Authority under the Essential Commodities
> Act, 1955 the same shall apply.

Proviso (C) to rule 6(1):

> no declaration as to the retail sale price shall be required to be made on
> (i) any package containing bidi;
> (ii) any domestic liquefied petroleum gas cylinder of which the price is
> covered under the Administrative Price Mechanism of the Government.

### Rule 6(1)(f) — dimensions (not implemented)

> Where the sizes of the commodity contained in the package are relevant, the
> dimensions of the commodity contained in the package and if the dimensions of
> the different pieces are different, the dimensions of each such different
> piece shall be mentioned.

Conditional on the sizes being "relevant". No rule file was created.

### Rule 6(1)(g)

> such other matter as are specified in these rules:

Not a declaration in itself. No rule file was created.

### Rule 6(2) — consumer care details → `LM-PC-0006`

As substituted vide G.S.R. 385(E) dated 14 May 2015, effective 1 January 2016
(the source records "dispensed upto 30.6.2016"):

> Every package shall bear the name, address, telephone number, e-mail address
> of the person who can be or the office which can be contacted, in case of
> consumer complaints.

**This is rule 6(2), not rule 6(1)(f).** The branch brief cited 6(1)(f) for
consumer care details; 6(1)(f) is the dimensions clause quoted above.

### Rule 6(11) — unit sale price (not implemented)

Unit sale price is rule 6(**11**), not a clause of rule 6(1). Its declaration
format is prescribed per net-quantity band, and it is not required where the
retail sale price equals the unit sale price. That is a format and comparison
requirement, not a presence requirement.

### Rule 9(1)(a) — legible and prominent (not implemented)

> Every declaration which is required to be made on a package under these rules
> shall be --
> (a) legible and prominent;

This is a property of how a declaration is rendered, not whether it exists.
`rules/SCHEMA.md` already anticipates it as `visual_check`, which is listed in
`apps.rules.checks.PLANNED_CHECK_TYPES` and is **not registered**. The loader
rejects any rule naming it. No rule file was created; doing so with
`field_presence` would silently answer a different question.

## Scope limits that apply to every rule here and are NOT encoded

These gate whether Chapter II — and in rule 26's case, the rules as a whole —
apply at all. They depend on net quantity and on who the buyer is, neither of
which is a `ProductCategory`, so **no rule file can express them**.

Rule 3, as substituted vide G.S.R. 629(E) dated 23 June 2017:

> The provisions of this chapter shall not apply to-
> (a) packages of commodities containing quantity of more than 25 kilogram or
> 25 litre;
> (b) cement, fertilizer and agricultural farm produce sold in bags above 50
> kilogram; and
> (c) packaged commodities meant for industrial consumers or institutional
> consumers.

Rule 26:

> Nothing contained in these rules shall apply to any package containing a
> commodity if--
> (a) the net weight or measure of the commodity is ten gram or ten millilitre
> or less, if sold by weight or measure;

with a proviso inserted vide G.S.R. 385(E) dated 14 May 2015 w.e.f. 1 July
2016 that clause (a) does not apply to tobacco and tobacco products; and
further clauses covering fast food items packed by a restaurant or hotel and
the like, scheduled and non-scheduled formulations under the Drugs (Price
Control) Order, 2013 (excluding medical devices declared as drugs), and thread
sold in coil to handloom weavers.

**Consequence:** an active rule in this set will be applied to a package that
is in fact outside the rules — a 30 kg sack, a 5 g sachet, a restaurant
takeaway box. Closing this needs applicability inputs the system does not
collect, not a different rule file.
