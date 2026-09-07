/**
 * The facts a submitter may state about a package.
 *
 *     GET /api/v1/compliance/applicability-conditions/
 *
 * Several clauses of the Legal Metrology (Packaged Commodities) Rules, 2011
 * apply — or do not apply — on facts **no photograph can establish**: whether
 * the package contains bidi, whether it is imported, whether the buyer is an
 * institutional consumer. Without them the engine cannot decide those clauses
 * and correctly reports REVIEW REQUIRED. This endpoint is how the browser
 * learns which questions are worth asking.
 *
 * **The catalogue is served, never written here.** Every code, name,
 * description, clause reference and note comes from the legal framework loaded
 * in the backend. Hardcoding a list of conditions in JavaScript would be a copy
 * of the legal catalogue that goes stale the moment a clause is transcribed or
 * a rule is deactivated, with nothing failing — which is exactly the failure
 * mode this project exists to avoid. If this file ever grows a literal list of
 * condition codes, that is a bug.
 *
 * Nothing here decides anything. What an answer *does* to a clause is decided
 * by the deterministic resolver in the backend; this module renames keys.
 */

import { apiClient } from './apiClient.js';

/**
 * @typedef {object} ClauseEffect
 * @property {string} clause        e.g. '6(1)(e)'
 * @property {string} mode          requires | exempts | scope_gate | withholds_exemption
 * @property {string} modeDisplay   the backend's label for that mode
 * @property {string} note          the framework's own note on this link
 * @property {string[]} ruleCodes   executable rules affected; empty for a gate
 */

/**
 * @typedef {object} ApplicabilityCondition
 * @property {string} code             the key to send in the declarations map
 * @property {string} name
 * @property {string} description
 * @property {string} determination
 * @property {string} determinationNote
 * @property {'rules_scope'|'clause'} scope
 * @property {string[]} answers        the permitted answers, from the API
 * @property {ClauseEffect[]} affects
 */

/**
 * @typedef {object} ApplicabilityCatalogue
 * @property {ApplicabilityCondition[]} conditions
 * @property {Record<string, string>} answerSemantics  what each answer means
 * @property {boolean} frameworkLoaded
 */

/** Answers the API accepts. Only ever used as a fallback — see `mapCondition`. */
const FALLBACK_ANSWERS = Object.freeze(['yes', 'no', 'unknown']);

function mapEffect(effect) {
  return {
    clause: effect.clause || '',
    mode: effect.mode || '',
    modeDisplay: effect.mode_display || '',
    note: effect.note || '',
    ruleCodes: Array.isArray(effect.rule_codes) ? effect.rule_codes : [],
  };
}

function mapCondition(condition) {
  return {
    code: condition.code,
    name: condition.name || condition.code,
    description: condition.description || '',
    determination: condition.determination || '',
    determinationNote: condition.determination_note || '',
    // Anything this build has not heard of is treated as a clause-level
    // condition rather than as a scope gate: the wrong guess in that direction
    // understates what an answer does, which is the safe way to be wrong.
    scope: condition.scope === 'rules_scope' ? 'rules_scope' : 'clause',
    // Served rather than assumed, so the radio group is built from the API's
    // vocabulary. The fallback exists only for a malformed response and is not
    // a place to add a fourth answer.
    answers: Array.isArray(condition.answers) && condition.answers.length
      ? condition.answers
      : [...FALLBACK_ANSWERS],
    affects: Array.isArray(condition.affects) ? condition.affects.map(mapEffect) : [],
  };
}

/**
 * Fetch the declarable facts for this installation.
 *
 * `frameworkLoaded: false` with an empty list is a real answer and a different
 * one from an empty list on a loaded framework: the first is a deployment that
 * has not run `load_legal_framework`, the second means nothing declarable bears
 * on any loaded rule. The UI says something different for each.
 *
 * @param {{signal?: AbortSignal}} [options]
 * @returns {Promise<ApplicabilityCatalogue>}
 * @throws {import('./apiClient.js').ApiError}
 */
export async function fetchApplicabilityConditions(options = {}) {
  const data = await apiClient.get(
    'compliance/applicability-conditions/',
    options,
  );

  // Defensive rather than trusting: `conditions` drives a `.map` and a
  // malformed response must not take the scan screen down with it.
  const conditions = Array.isArray(data?.conditions) ? data.conditions : [];

  return {
    conditions: conditions.map(mapCondition),
    answerSemantics:
      data?.answer_semantics && typeof data.answer_semantics === 'object'
        ? data.answer_semantics
        : {},
    frameworkLoaded: Boolean(data?.framework_loaded),
  };
}
