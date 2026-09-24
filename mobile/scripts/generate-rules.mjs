/**
 * Regenerate `src/data/lmpcRules.ts` from the repository's rule definitions.
 *
 *     node scripts/generate-rules.mjs
 *
 * The Rules screen names the twelve requirements from a bundled copy - see the
 * generated file's header for why, and for the backend endpoint that now lists
 * the loaded rules. This script is how the copy is made, and
 * `src/data/lmpcRules.test.ts` is what fails if somebody edits the copy by hand
 * or changes a definition without rerunning it.
 *
 * Only display fields are copied. The requirement's full legal wording stays in
 * the JSON, where it is reviewed; putting it in the bundle would invite treating
 * the bundle as the text of the Rules.
 */

import { readdirSync, readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFINITIONS = join(HERE, '..', '..', 'rules', 'definitions');
const OUT = join(HERE, '..', 'src', 'data', 'lmpcRules.ts');

/**
 * Every `legal_reference` ends with this, and the screen shows the part before
 * it. Asserted rather than stripped optionally: a definition that referenced a
 * different instrument would otherwise be silently relabelled as an LMPC rule.
 */
const SUFFIX = ' of the Legal Metrology (Packaged Commodities) Rules, 2011';

const rules = readdirSync(DEFINITIONS)
  .filter((name) => /^LM-PC-\d+\.json$/.test(name))
  .sort()
  .map((name) => {
    const definition = JSON.parse(readFileSync(join(DEFINITIONS, name), 'utf8'));
    const reference = definition.legal_reference;
    if (typeof reference !== 'string' || !reference.endsWith(SUFFIX)) {
      throw new Error(`${name}: legal_reference is not an LMPC 2011 reference: ${reference}`);
    }
    return {
      code: definition.code,
      title: definition.title,
      provision: reference.slice(0, -SUFFIX.length),
      severity: definition.severity,
      isActive: Boolean(definition.is_active),
    };
  });

if (rules.length === 0) {
  throw new Error(`No rule definitions found in ${DEFINITIONS}`);
}

/** A TypeScript single-quoted string literal. */
const str = (value) => `'${String(value).replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`;

const header = `/**
 * The rule definitions this app is built with, as a display list.
 *
 * GENERATED, AND A MIRROR - NOT A SOURCE OF TRUTH
 * ----------------------------------------------
 * Regenerate rather than edit: \`node scripts/generate-rules.mjs\` reads
 * \`rules/definitions/*.json\` at the repository root and rewrites this file.
 * \`lmpcRules.test.ts\` reads those same files and fails if the two have drifted,
 * so a rule added, renamed, deactivated or re-referenced upstream breaks the
 * mobile test run instead of quietly leaving a stale list on the Rules screen.
 *
 * **Why a mirror exists at all.** When the Rules screen was built, no endpoint
 * listed rules, so the only way for the phone to name the requirements was to
 * carry a copy - and the only safe way to carry a copy is to have a test that
 * notices when it goes stale. The backend now serves the rules it has loaded at
 * \`GET /api/v1/rules/\` (see \`docs/api.md\`). Moving the Rules screen onto that
 * endpoint is a separate follow-up task; until it lands, this file is still what
 * the screen displays, and it mirrors the repository's definition files - not
 * what any particular server has loaded.
 *
 * **What this list is not.** It is not what was evaluated for any particular
 * package - that is the result screen's findings, which come from the server. It
 * is not a legal text: \`title\` and \`provision\` are the repository's own words
 * for each rule, and each requirement's full wording stays in the JSON where it
 * can be reviewed. \`isActive\` is the flag on the definition, which is why one
 * rule here says it is not evaluated; the server remains the authority on
 * whether it ran.
 */

/** One rule, as the Rules screen lists it. */
export interface LmpcRule {
  /** The stable identifier a finding cites, e.g. \`LM-PC-0003\`. */
  code: string;
  /** The repository's own name for the requirement. */
  title: string;
  /** Where it comes from, short form - e.g. \`Rule 6(1)(c)\`. */
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
`;

const body = rules
  .map(
    (rule) =>
      `  { code: ${str(rule.code)}, title: ${str(rule.title)}, provision: ${str(rule.provision)}, severity: ${str(rule.severity)}, isActive: ${rule.isActive} },`,
  )
  .join('\n');

const footer = `
/** How many definitions are recorded, and how many are active - as bundled, not as any server has loaded them. */
export const RULE_COUNTS = Object.freeze({
  recorded: LMPC_RULES.length,
  evaluated: LMPC_RULES.filter((rule) => rule.isActive).length,
  inactive: LMPC_RULES.filter((rule) => !rule.isActive).length,
});
`;

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(
  OUT,
  `${header}\nexport const LMPC_RULES: readonly LmpcRule[] = Object.freeze([\n${body}\n]);\n${footer}`,
  'utf8',
);

const evaluated = rules.filter((rule) => rule.isActive).length;
console.log(
  `Wrote ${rules.length} rules (${evaluated} evaluated, ${rules.length - evaluated} inactive) to ${OUT}`,
);
