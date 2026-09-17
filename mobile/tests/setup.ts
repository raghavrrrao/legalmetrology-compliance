/**
 * Runs before every test file.
 *
 * Three things are replaced here, each with the smallest surface the code
 * under test calls; individual tests override return values as they need.
 *
 * - `expo-image-picker` and `expo-constants` reach native modules that do not
 *   exist under Jest.
 * - `FormData`: React Native's implementation accepts `{ uri, name, type }`
 *   parts and exposes them through `getParts()`; Node's accepts only strings
 *   and Blobs and would stringify a file part to "[object Object]". The double
 *   below records what was appended, in the shape React Native's does, so a
 *   test can assert on the multipart body the app actually builds.
 *
 * Jest matchers (`toBeOnTheScreen`, `toHaveTextContent`, ...) are registered
 * automatically by @testing-library/react-native; nothing to import.
 */

jest.mock('expo-image-picker', () => ({
  PermissionStatus: { GRANTED: 'granted', DENIED: 'denied', UNDETERMINED: 'undetermined' },
  requestCameraPermissionsAsync: jest.fn(),
  requestMediaLibraryPermissionsAsync: jest.fn(),
  launchCameraAsync: jest.fn(),
  launchImageLibraryAsync: jest.fn(),
}));

jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { hostUri: undefined } },
}));

export interface RecordedPart {
  fieldName: string;
  value: unknown;
}

class RecordingFormData {
  private readonly parts: RecordedPart[] = [];

  append(fieldName: string, value: unknown): void {
    this.parts.push({ fieldName, value });
  }

  /** Mirrors React Native's `FormData.getParts()`. */
  getParts(): RecordedPart[] {
    return [...this.parts];
  }
}

(globalThis as unknown as { FormData: unknown }).FormData = RecordingFormData;

beforeEach(() => {
  // `logError` writes to console.warn in development builds, which Jest is.
  // The messages are asserted nowhere and would only bury real warnings.
  jest.spyOn(console, 'warn').mockImplementation(() => undefined);
});

afterEach(() => {
  jest.restoreAllMocks();
  jest.clearAllMocks();
});
