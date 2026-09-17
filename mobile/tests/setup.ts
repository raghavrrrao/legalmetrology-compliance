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

/**
 * `expo-file-system`'s `File` reads the picked photograph off disk through a
 * native module. The double records the uri it was given and hands back a
 * fixed byte sequence, so an upload test can see that the body was built
 * from the file the user picked.
 */
/** The bytes the fake File hands back: the start of a JPEG header. */
export const mockFileBytes = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46]);

jest.mock('expo-file-system', () => ({
  File: class FakeFile {
    readonly uri: string;
    readonly exists = true;
    readonly size = 8;
    readonly type = 'image/jpeg';

    constructor(...uris: string[]) {
      this.uri = uris.join('/');
    }

    get name(): string {
      return this.uri.split('/').pop() ?? '';
    }

    bytes(): Promise<Uint8Array> {
      return Promise.resolve(mockFileBytes);
    }
  },
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
