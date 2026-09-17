/**
 * Health endpoint client - `GET /api/v1/health/`.
 *
 * The one public, unthrottled endpoint. The home screen calls it through the
 * same client every other request uses, so "the server is reachable" means
 * reachable by this app at the address this build was given - not by a
 * browser at some other address.
 */

import { apiClient, type RequestOptions } from './client';

export interface HealthStatus {
  status: string;
  apiVersion: string;
  extractionEngine: { name: string | null; version: string | null; isPlaceholder: boolean | null };
}

interface HealthWire {
  status?: string;
  api_version?: string;
  extraction_engine?: { name?: string; version?: string; is_placeholder?: boolean };
}

export async function fetchHealth(options: Pick<RequestOptions, 'signal'> = {}): Promise<HealthStatus> {
  const data = await apiClient.get<HealthWire>('health/', options);
  return {
    status: typeof data?.status === 'string' ? data.status : 'unknown',
    apiVersion: typeof data?.api_version === 'string' ? data.api_version : '',
    extractionEngine: {
      name: data?.extraction_engine?.name ?? null,
      version: data?.extraction_engine?.version ?? null,
      isPlaceholder: typeof data?.extraction_engine?.is_placeholder === 'boolean' ? data.extraction_engine.is_placeholder : null,
    },
  };
}
