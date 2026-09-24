/**
 * Regenerate `src/data/lmpcRules.ts` from the repository's rule definitions.
 *
 *     node scripts/generate-rules.mjs
 *
 * The Rules screen used to list the requirements from this bundled copy. It now
 * lists what the server reports at `GET /api/v1/rules/`, and nothing in the app
 * imports the copy - see the generated file's header for what it is kept as.
 * This script is how the copy is made, and `src/data/lmpcRules.test.ts` is what
 * fails if somebody edits the copy by hand or changes a definition without
 * rerunning it.
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
 * The repository's rule definitions, as a display list.
 *
 * GENERATED, AND A MIRROR - NOT A SOURCE OF TRUTH
 * ----------------------------------------------
 * Regenerate rather than edit: \`node scripts/generate-rules.mjs\` reads
 * \`rules/definitions/*.json\` at the repository root and rewrites this file.
 * \`lmpcRules.test.ts\` reads those same files and fails if the two have drifted,
 * so a rule added, renamed, deactivated or re-referenced upstream breaks the
 * mobile test run instead of quietly leaving a stale copy in the repository.
 *
 * **Not what the app shows.** The Rules screen lists what the analysis server
 * reports at \`GET /api/v1/rules/\` (see \`docs/api.md\`), and nothing in the app
 * imports this file. It was the screen's data source before that endpoint
 * existed. It is kept, generated and drift-tested, as a mirror of the
 * repository's definition files only - it says what the repository ships, not
 * what any server has loaded - and it is not an offline fallback: shown in
 * place of the server's list it would be mistaken for it.
 *
 * **What this list is not.** It is not what was evaluated for any particular
 * package - that is the result screen's findings, which come from the server. It
 * is not a legal text: \`title\` and \`provision\` are the repository's own words
 * for each rule, and each requirement's full wording stays in the JSON where it
 * can be reviewed. \`isActive\` is the flag on the definition, which is why one
 * rule here says it is not evaluated; the server remains the authority on
 * whether it ran.
 */

/** One rule definition, as mirrored from \`rules/definitions/\`. */
export interface LmpcRule {
  /** The stable identifier a finding cites, e.g. \`LM-PC-0003\`. */
  code: string;
  /** The repository's own name for the requirement. */
  title: string;
  /** Where it comes from, short form - e.g. \`Rule 6(1)(c)\`. */
  provision: string;
  severity: string;
  /**
   * Whether the definition is switched on in the repository. A definition that
   * exists but is inactive is recorded and not evaluated once loaded; whether a
   * given server has it switched on is that server's \`is_active\`.
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
