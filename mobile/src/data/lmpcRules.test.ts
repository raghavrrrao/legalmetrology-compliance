/// <reference types="node" />
/**
 * The rules the phone ships must be the rules the repository ships.
 *
 * NOTE ON `node:fs`: this is the only file in `src/` that touches Node's
 * standard library, and the reference above is why `tsconfig.json` does not need
 * to add `node` to `types` for the whole project - which would hand every screen
 * `Buffer` and `process.exit`, neither of which exists in React Native. Nothing
 * that ships in the bundle may import from `node:*`; this file never runs on a
 * phone.
 *
 * `src/data/lmpcRules.ts` is a generated mirror of `rules/definitions/*.json`.
 * The Rules screen no longer reads it - it lists `GET /api/v1/rules/` - and
 * nothing in the app imports it (that file's header says what it is kept as).
 * While it is kept, it must not drift: a mirror with nothing watching it is a
 * stale list waiting to happen, with a rule deactivated upstream still marked
 * active and a rule added upstream missing.
 *
 * So this test reads the definitions off disk - the real files, not a fixture -
 * and compares them field by field. It fails if anyone edits the mirror by hand,
 * changes a definition without rerunning `node scripts/generate-rules.mjs`, or
 * adds a rule from a different instrument.
 *
 * Reading up out of `mobile/` is deliberate. The alternative is a fixture copy of
 * the definitions, which is a second mirror with the same problem.
 */

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { LMPC_RULES, RULE_COUNTS } from './lmpcRules';

const DEFINITIONS = join(__dirname, '..', '..', '..', 'rules', 'definitions');
const SUFFIX = ' of the Legal Metrology (Packaged Commodities) Rules, 2011';

interface Definition {
  code: string;
  title: string;
  legal_reference: string;
  severity: string;
  is_active: boolean;
}

function definitions(): Definition[] {
  return readdirSync(DEFINITIONS)
    .filter((name) => /^LM-PC-\d+\.json$/.test(name))
    .sort()
    .map((name) => JSON.parse(readFileSync(join(DEFINITIONS, name), 'utf8')) as Definition);
}

describe('the bundled rule list', () => {
  it('finds the repository rule definitions where it expects them', () => {
    // Guards the test itself: a wrong path would make every assertion below
    // vacuous by comparing two empty lists.
    expect(definitions().length).toBeGreaterThan(0);
  });

  it('carries every rule definition, in the same order, with no extras', () => {
    expect(LMPC_RULES.map((rule) => rule.code)).toEqual(definitions().map((d) => d.code));
  });

  it('matches each definition field for field', () => {
    for (const definition of definitions()) {
      const rule = LMPC_RULES.find((candidate) => candidate.code === definition.code);
      expect(rule).toBeDefined();
      expect(rule).toEqual({
        code: definition.code,
        title: definition.title,
        provision: definition.legal_reference.replace(SUFFIX, ''),
        severity: definition.severity,
        isActive: definition.is_active,
      });
    }
  });

  it('shortens the provision without losing which instrument it came from', () => {
    // The screen shows "Rule 6(1)(c)". That is only safe to shorten because every
    // definition cites the same instrument; one that did not would be silently
    // relabelled as an LMPC rule, so the generator refuses it and so does this.
    for (const definition of definitions()) {
      expect(definition.legal_reference.endsWith(SUFFIX)).toBe(true);
    }
    expect(LMPC_RULES.every((rule) => /^Rule \d/.test(rule.provision))).toBe(true);
  });

  it('counts recorded, evaluated and inactive from the definitions themselves', () => {
    const all = definitions();
    expect(RULE_COUNTS.recorded).toBe(all.length);
    expect(RULE_COUNTS.evaluated).toBe(all.filter((d) => d.is_active).length);
    expect(RULE_COUNTS.inactive).toBe(all.filter((d) => !d.is_active).length);
    expect(RULE_COUNTS.evaluated + RULE_COUNTS.inactive).toBe(RULE_COUNTS.recorded);
  });

  it('keeps at least one recorded-but-not-evaluated rule visible', () => {
    // Not a requirement about the law - a requirement about honesty. The inactive
    // rule is what shows that recorded and evaluated are different things. The
    // Rules screen now takes that from the server's `is_active`, so if upstream
    // ever activates the last one this fails, and the fix is to confirm the
    // screen still marks an inactive server rule (RulesScreen.test.tsx) before
    // deleting this assertion.
    expect(RULE_COUNTS.inactive).toBeGreaterThan(0);
  });
});
