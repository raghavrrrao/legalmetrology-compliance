/**
 * Rule inventory client - `GET /api/v1/rules/`.
 *
 * The rules the analysis server has loaded, active and inactive, in the
 * server's order. This is what the Rules screen lists, and the server is the
 * authority on it: the app keeps no copy that could stand in for it.
 *
 * Nothing here evaluates anything. The endpoint sends no validator, parameter,
 * category or applicability, and this module would have nowhere to put one; a
 * compliance rule must never be implemented in JavaScript. What it does:
 *
 * - **Reads every page.** The endpoint is paginated. One request at the largest
 *   page size the backend serves covers any inventory up to that size, and the
 *   `next` link is followed after that - so the screen never presents a first
 *   page as though it were the whole inventory.
 * - **Refuses a response it cannot vouch for.** A malformed page, a malformed
 *   rule, or pages that do not add up to the `count` they report reject the
 *   whole inventory with `unexpected_response`. Dropping the one bad row and
 *   showing the rest would present an incomplete list as the server's.
 * - **Tallies the `is_active` flags** of that complete list, so the screen can
 *   show how many rules are active without computing anything itself.
 */

import { ApiError, apiClient, buildUrl, type RequestOptions } from './client';
import { config } from '../config/env';
import type { PageWire, RuleInventory, RuleInventoryEntry, RuleWire } from '../types/api';

/**
 * The largest page the backend serves (`DefaultPageNumberPagination.max_page_size`,
 * docs/api.md). Asking for it keeps an inventory of that size or less to one
 * request; it is not an assumption about how many rules there are.
 */
export const RULES_PAGE_SIZE = 100;

/**
 * How many pages are followed before giving up - ten thousand rules at the page
 * size above. A server that kept answering with a `next` link would otherwise
 * leave the screen loading for ever.
 */
export const MAX_RULE_PAGES = 100;

const SOURCE_STATUSES: readonly RuleWire['source_status'][] = ['verified', 'unverified'];
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Every rejection is the same error to the user; `reason` is for a developer's log. */
function malformed(reason: string): ApiError {
  return new ApiError('The server returned an unexpected response.', {
    status: 200,
    code: 'unexpected_response',
    details: { reason },
  });
}

function isStringOrNull(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isDateOrNull(value: unknown): value is string | null {
  return value === null || (typeof value === 'string' && ISO_DATE.test(value));
}

/**
 * Map one rule, or throw.
 *
 * Every field is required and checked against the contract; there is no default
 * for any of them, because a default here would be the app inventing a rule's
 * reference, clause or status. Fields the contract does not name are not
 * copied, so nothing else the server might send reaches the screen.
 */
export function mapRule(value: unknown): RuleInventoryEntry {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw malformed('rule is not an object');
  }
  const rule = value as Partial<Record<keyof RuleWire, unknown>>;

  if (typeof rule.code !== 'string' || !rule.code.trim()) {
    throw malformed('rule has no code');
  }
  if (typeof rule.title !== 'string') {
    throw malformed(`${rule.code}: title is not a string`);
  }
  if (typeof rule.legal_reference !== 'string') {
    throw malformed(`${rule.code}: legal_reference is not a string`);
  }
  if (!isStringOrNull(rule.clause)) {
    throw malformed(`${rule.code}: clause is not a string or null`);
  }
  if (!SOURCE_STATUSES.includes(rule.source_status as RuleWire['source_status'])) {
    throw malformed(`${rule.code}: source_status is not one the contract defines`);
  }
  if (typeof rule.is_active !== 'boolean') {
    throw malformed(`${rule.code}: is_active is not a boolean`);
  }
  if (!isDateOrNull(rule.effective_from) || !isDateOrNull(rule.effective_to)) {
    throw malformed(`${rule.code}: an effective date is not an ISO date or null`);
  }

  return {
    code: rule.code,
    title: rule.title,
    legalReference: rule.legal_reference,
    clause: rule.clause,
    sourceStatus: rule.source_status as RuleWire['source_status'],
    isActive: rule.is_active,
    effectiveFrom: rule.effective_from,
    effectiveTo: rule.effective_to,
  };
}

export interface RulePage {
  count: number;
  next: string | null;
  rules: RuleInventoryEntry[];
}

/** Map one page of the paginated envelope, or throw. */
export function mapRulePage(data: unknown): RulePage {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw malformed('page is not an object');
  }
  const page = data as Partial<Record<keyof PageWire<unknown>, unknown>>;

  if (typeof page.count !== 'number' || !Number.isInteger(page.count) || page.count < 0) {
    throw malformed('count is not a non-negative integer');
  }
  if (!isStringOrNull(page.next) || !isStringOrNull(page.previous)) {
    throw malformed('next or previous is not a string or null');
  }
  if (!Array.isArray(page.results)) {
    throw malformed('results is not a list');
  }
  if (page.results.length > page.count) {
    throw malformed('a page holds more rules than the count');
  }

  return { count: page.count, next: page.next, rules: page.results.map(mapRule) };
}

/**
 * The `next` link, if it points back at the server this app is configured for.
 *
 * The backend builds it from the request, so it always does; a link to another
 * origin would mean following a server's instruction to fetch from somewhere
 * the app was never pointed at, and is refused rather than obeyed.
 */
function sameServer(next: string): string {
  let target: URL;
  try {
    target = new URL(next);
  } catch {
    throw malformed('next is not a URL');
  }
  if (target.origin !== new URL(config.apiBaseUrl).origin) {
    throw malformed('next points at a different server');
  }
  return target.toString();
}

/**
 * The server's complete rule inventory.
 *
 * @throws {ApiError} for every failure - network, HTTP status, or a response
 *   that is not a complete, well-formed inventory (`unexpected_response`).
 */
export async function fetchRuleInventory(
  options: Pick<RequestOptions, 'signal'> = {},
): Promise<RuleInventory> {
  const rules: RuleInventoryEntry[] = [];
  const requested = new Set<string>();
  let path: string | null = `rules/?page_size=${RULES_PAGE_SIZE}`;
  let count: number | null = null;

  while (path !== null) {
    if (requested.size >= MAX_RULE_PAGES) {
      throw malformed(`more than ${MAX_RULE_PAGES} pages`);
    }
    const url = buildUrl(path);
    if (requested.has(url)) {
      throw malformed('next repeats a page already read');
    }
    requested.add(url);

    const page = mapRulePage(await apiClient.get<unknown>(path, options));
    if (count === null) {
      count = page.count;
    } else if (page.count !== count) {
      // The inventory changed while it was being read. Neither count is the
      // one the rows add up to, so neither is shown.
      throw malformed('count changed between pages');
    }
    rules.push(...page.rules);
    path = page.next === null ? null : sameServer(page.next);
  }

  if (rules.length !== count) {
    throw malformed(`pages hold ${rules.length} rules, count says ${count}`);
  }
  if (new Set(rules.map((rule) => rule.code)).size !== rules.length) {
    throw malformed('a rule code appears more than once');
  }

  const active = rules.filter((rule) => rule.isActive).length;
  return { rules, total: count ?? 0, active, inactive: rules.length - active };
}
