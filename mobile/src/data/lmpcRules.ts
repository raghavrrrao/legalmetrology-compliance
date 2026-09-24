/**
 * The repository's rule definitions, as a display list.
 *
 * GENERATED, AND A MIRROR - NOT A SOURCE OF TRUTH
 * ----------------------------------------------
 * Regenerate rather than edit: `node scripts/generate-rules.mjs` reads
 * `rules/definitions/*.json` at the repository root and rewrites this file.
 * `lmpcRules.test.ts` reads those same files and fails if the two have drifted,
 * so a rule added, renamed, deactivated or re-referenced upstream breaks the
 * mobile test run instead of quietly leaving a stale copy in the repository.
 *
 * **Not what the app shows.** The Rules screen lists what the analysis server
 * reports at `GET /api/v1/rules/` (see `docs/api.md`), and nothing in the app
 * imports this file. It was the screen's data source before that endpoint
 * existed. It is kept, generated and drift-tested, as a mirror of the
 * repository's definition files only - it says what the repository ships, not
 * what any server has loaded - and it is not an offline fallback: shown in
 * place of the server's list it would be mistaken for it.
 *
 * **What this list is not.** It is not what was evaluated for any particular
 * package - that is the result screen's findings, which come from the server. It
 * is not a legal text: `title` and `provision` are the repository's own words
 * for each rule, and each requirement's full wording stays in the JSON where it
 * can be reviewed. `isActive` is the flag on the definition, which is why one
 * rule here says it is not evaluated; the server remains the authority on
 * whether it ran.
 */

/** One rule definition, as mirrored from `rules/definitions/`. */
export interface LmpcRule {
  /** The stable identifier a finding cites, e.g. `LM-PC-0003`. */
  code: string;
  /** The repository's own name for the requirement. */
  title: string;
  /** Where it comes from, short form - e.g. `Rule 6(1)(c)`. */
  provision: string;
  severity: string;
  /**
   * Whether the definition is switched on in the repository. A definition that
   * exists but is inactive is recorded and not evaluated once loaded; whether a
   * given server has it switched on is that server's `is_active`.
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
