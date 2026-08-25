import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vite.dev/config/
export default defineConfig({
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
});
