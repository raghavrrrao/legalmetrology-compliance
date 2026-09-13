import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * Refuse to build a production bundle with no API URL in it.
 *
 * `VITE_API_BASE_URL` is baked into the JavaScript at build time, so a missing
 * value is not a runtime misconfiguration somebody can fix on the host - it is
 * a broken artefact that has already been uploaded. Failing here, loudly, is
 * the last moment the mistake is cheap. `src/config/env.js` carries the same
 * refusal for a bundle built some other way.
 */
function assertApiBaseUrlConfigured(mode) {
  const { VITE_API_BASE_URL } = loadEnv(mode, process.cwd(), 'VITE_');

  if (!VITE_API_BASE_URL?.trim()) {
    throw new Error(
      'VITE_API_BASE_URL is not set, so this build would have no API to call. '
        + 'Set it in frontend/.env.production (the deployed Railway API) or '
        + 'pass it on the command line. See docs/deployment.md.',
    );
  }
}

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  if (command === 'build' && mode === 'production') {
    assertApiBaseUrlConfigured(mode);
  }

  return {
    plugins: [react()],
    server: {
      // Fixed port: it is listed in the backend's CORS_ALLOWED_ORIGINS, so a
      // silent fallback to 5174 would look like a CORS bug rather than a port
      // clash. strictPort makes the real cause obvious.
      port: 5173,
      strictPort: true,
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.js'],
      css: false,
    },
  };
});
