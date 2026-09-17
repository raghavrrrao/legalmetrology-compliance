/**
 * Jest configuration for the mobile client.
 *
 * `jest-expo` is the preset the Expo SDK ships and tests against: it wires up
 * the React Native transformer, the module mocks for the native layer, and the
 * `transformIgnorePatterns` that let Expo's untranspiled packages be required
 * from a test. The web frontend uses Vitest; it is not used here because Vitest
 * has no equivalent of that preset and React Native's Flow-typed sources do
 * not go through it without one.
 */
module.exports = {
  preset: 'jest-expo',
  setupFilesAfterEnv: ['<rootDir>/tests/setup.ts'],
  testMatch: ['<rootDir>/src/**/*.test.ts', '<rootDir>/src/**/*.test.tsx'],
  // Coverage is collected from the code under src/ only - the template's
  // App.tsx and index.ts are wiring, not behaviour.
  collectCoverageFrom: ['src/**/*.{ts,tsx}', '!src/**/*.test.{ts,tsx}'],
};
