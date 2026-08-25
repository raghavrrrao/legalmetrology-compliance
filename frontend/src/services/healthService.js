/**
 * Health endpoint client.
 *
 * The only API service in the base structure. Each feature branch adds its own
 * module here (productService.js, analysisService.js, ...) following this shape:
 * a thin function per endpoint that returns plain data and lets `ApiError`
 * propagate. Components must never call `fetch` or `apiClient` directly.
 */

import { apiClient } from './apiClient.js';

/**
 * @typedef {object} HealthStatus
 * @property {'ok'|'degraded'} status
 * @property {string} apiVersion
 * @property {{database: string, extractionEngine: string}} dependencies
 * @property {{name: string, version: string, isPlaceholder: boolean|null}} extractionEngine
 * @property {{activeTotal: number|null, verified: number|null, unverified: number|null}|null} complianceRules
 */

/**
 * Fetch backend health.
 *
 * Maps the API's snake_case onto camelCase at the boundary, so the rest of the
 * frontend uses one naming convention and a change to the API shape is
 * contained in this file.
 *
 * @returns {Promise<HealthStatus>}
 * @throws {import('./apiClient.js').ApiError}
 */
export async function fetchHealth(options = {}) {
  const data = await apiClient.get('health/', options);

  return {
    status: data.status,
    apiVersion: data.api_version,
    dependencies: {
      database: data.dependencies?.database ?? 'unknown',
      extractionEngine: data.dependencies?.extraction_engine ?? 'unknown',
    },
    extractionEngine: {
      name: data.extraction_engine?.name ?? null,
      version: data.extraction_engine?.version ?? null,
      isPlaceholder: data.extraction_engine?.is_placeholder ?? null,
    },
    complianceRules: data.compliance_rules
      ? {
          activeTotal: data.compliance_rules.active_total,
          verified: data.compliance_rules.verified,
          unverified: data.compliance_rules.unverified,
        }
      : null,
  };
}
