/**
 * The rule definitions this app is built with, as a display list.
 *
 * GENERATED, AND A MIRROR - NOT A SOURCE OF TRUTH
 * ----------------------------------------------
 * Regenerate rather than edit: `node scripts/generate-rules.mjs` reads
 * `rules/definitions/*.json` at the repository root and rewrites this file.
 * `lmpcRules.test.ts` reads those same files and fails if the two have drifted,
 * so a rule added, renamed, deactivated or re-referenced upstream breaks the
 * mobile test run instead of quietly leaving a stale list on the Rules screen.
 *
 * **Why a mirror exists at all.** When the Rules screen was built, no endpoint
 * listed rules, so the only way for the phone to name the requirements was to
 * carry a copy - and the only safe way to carry a copy is to have a test that
 * notices when it goes stale. The backend now serves the rules it has loaded at
 * `GET /api/v1/rules/` (see `docs/api.md`). Moving the Rules screen onto that
 * endpoint is a separate follow-up task; until it lands, this file is still what
 * the screen displays, and it mirrors the repository's definition files - not
 * what any particular server has loaded.
 *
 * **What this list is not.** It is not what was evaluated for any particular
 * package - that is the result screen's findings, which come from the server. It
 * is not a legal text: `title` and `provision` are the repository's own words
 * for each rule, and each requirement's full wording stays in the JSON where it
 * can be reviewed. `isActive` is the flag on the definition, which is why one
 * rule here says it is not evaluated; the server remains the authority on
 * whether it ran.
 */

/** One rule, as the Rules screen lists it. */
export interface LmpcRule {
  /** The stable identifier a finding cites, e.g. `LM-PC-0003`. */
  code: string;
  /** The repository's own name for the requirement. */
  title: string;
  /** Where it comes from, short form - e.g. `Rule 6(1)(c)`. */
  provision: string;
  severity: string;
  /**
   * Whether the definition is switched on. A definition that exists but is
   * inactive is recorded and not evaluated, and the screen lists it saying so
   * rather than leaving it out - a requirement the tool does not check is the
   * more important of the two things to be able to see.
   */
  isActive: boolean;
}

export const LMPC_RULES: readonly LmpcRule[] = Object.freeze([
  { code: 'LM-PC-0001', title: 'Name and address of the manufacturer, packer or importer', provision: 'Rule 6(1)(a)', severity: 'major', isActive: true },
  { code: 'LM-PC-0002', title: 'Common or generic name of the commodity', provision: 'Rule 6(1)(b)', severity: 'major', isActive: false },
  { code: 'LM-PC-0003', title: 'Net quantity of the commodity', provision: 'Rule 6(1)(c)', severity: 'major', isActive: true },
  { code: 'LM-PC-0004', title: 'Month and year of manufacture', provision: 'Rule 6(1)(d)', severity: 'major', isActive: true },
  { code: 'LM-PC-0005', title: 'Retail sale price (maximum retail price)', provision: 'Rule 6(1)(e)', severity: 'major', isActive: true },
  { code: 'LM-PC-0006', title: 'Consumer care details', provision: 'Rule 6(2)', severity: 'major', isActive: true },
  { code: 'LM-PC-0007', title: 'Country of origin for imported products', provision: 'Rule 6(1)(aa)', severity: 'major', isActive: true },
  { code: 'LM-PC-0008', title: 'Net quantity in units of the International System of Units', provision: 'Rule 13(5)', severity: 'major', isActive: true },
  { code: 'LM-PC-0009', title: 'No dozen, score, gross or great gross on the package', provision: 'Rule 13(4)', severity: 'minor', isActive: true },
  { code: 'LM-PC-0010', title: 'Consumer care telephone number and e-mail address', provision: 'Rule 6(2)', severity: 'major', isActive: true },
  { code: 'LM-PC-0011', title: 'Month and year of manufacture must be determinable', provision: 'Rule 6(1)(d)', severity: 'major', isActive: true },
  { code: 'LM-PC-0012', title: 'Retail sale price must not be declared exclusive of taxes', provision: 'Rule 6(1)(e)', severity: 'major', isActive: true },
]);

/** How many definitions are recorded, and how many are active - as bundled, not as any server has loaded them. */
export const RULE_COUNTS = Object.freeze({
  recorded: LMPC_RULES.length,
  evaluated: LMPC_RULES.filter((rule) => rule.isActive).length,
  inactive: LMPC_RULES.filter((rule) => !rule.isActive).length,
});
