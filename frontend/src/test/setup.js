// Adds jest-dom matchers (toBeInTheDocument, toHaveTextContent, ...) to
// Vitest's expect. Loaded via `setupFiles` in vite.config.js.
import '@testing-library/jest-dom/vitest';

// jsdom implements neither of these, and any screen that shows a file the user
// picked needs them. Defined here rather than per-suite because they belong to
// the environment: React runs the revoke in a cleanup effect, which fires
// during Testing Library's own afterEach and so outlives a suite's teardown.
if (typeof URL.createObjectURL !== 'function') {
  URL.createObjectURL = () => 'blob:object-url-stub';
}
if (typeof URL.revokeObjectURL !== 'function') {
  URL.revokeObjectURL = () => {};
}
