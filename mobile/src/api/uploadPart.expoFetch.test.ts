/**
 * Regression: the multipart part the app builds must be one Expo's fetch can
 * encode.
 *
 * Expo replaces the global `fetch` with `expo/fetch` on native, and its
 * encoder does not read React Native's legacy `{ uri }` file part - it throws
 * before any request is made, which the client can only report as a network
 * failure (HTTP 0). That is exactly what an Android phone showed against a
 * reachable server. This test runs the app's part through Expo's real
 * `FormData` patch and body normaliser (jest-expo stubs the patch, so the
 * actual module is required), with the global `FormData` set to React
 * Native's class as it is on a device.
 */

import RNFormDataModule from 'react-native/Libraries/Network/FormData';

import { buildUploadFormData, toUploadPart } from './extraction';
import { mockFileBytes } from '../../tests/setup';

const RNFormData = ((RNFormDataModule as any).default ?? RNFormDataModule) as new () => FormData;
const { installFormDataPatch } = jest.requireActual('expo/src/winter/FormData') as {
  installFormDataPatch: (formData: typeof FormData) => void;
};
const { normalizeBodyInitAsync } = jest.requireActual('expo/src/winter/fetch/RequestUtils') as {
  normalizeBodyInitAsync: (
    body: BodyInit,
  ) => Promise<{ body: Uint8Array | null; overriddenHeaders?: [string, string][] }>;
};

const originalFormData = globalThis.FormData;

beforeAll(() => {
  (globalThis as unknown as { FormData: unknown }).FormData = RNFormData;
  installFormDataPatch(RNFormData as unknown as typeof FormData);
});

afterAll(() => {
  (globalThis as unknown as { FormData: unknown }).FormData = originalFormData;
});

const upload = {
  uri: 'file:///data/user/0/host.exp.exponent/cache/ImagePicker/3f2a.jpeg',
  name: 'label.jpg',
  type: 'image/jpeg',
};

/** Byte-for-byte to characters, so binary content keeps its offsets. */
function decode(body: Uint8Array | null): string {
  return Array.from(body ?? new Uint8Array(), (byte) => String.fromCharCode(byte)).join('');
}

describe("the upload part under Expo's fetch", () => {
  it('is encoded into a multipart body with the validated filename, type and the file bytes', async () => {
    const { body, overriddenHeaders } = await normalizeBodyInitAsync(buildUploadFormData(upload, 'front'));

    const text = decode(body);
    expect(text).toContain('content-disposition: form-data; name="image"; filename="label.jpg"');
    expect(text).toContain('content-type: image/jpeg');
    expect(text).toContain('content-disposition: form-data; name="view_type"');
    expect(text).toContain('front');

    // The bytes came from the picked file, via expo-file-system.
    const bytesOffset = text.indexOf('content-type: image/jpeg') + 'content-type: image/jpeg\r\n\r\n'.length;
    expect(Array.from(body!.slice(bytesOffset, bytesOffset + mockFileBytes.length))).toEqual(
      Array.from(mockFileBytes),
    );

    // expo/fetch generates the boundary and sets the header itself; the app
    // must not, or the boundary in the header and the body could disagree.
    expect(overriddenHeaders).toEqual([['Content-Type', expect.stringMatching(/^multipart\/form-data; boundary=/)]]);
  });

  it("carries uri, name and type as well, for React Native's own fetch", () => {
    // EXPO_PUBLIC_USE_RN_FETCH=1 restores React Native's fetch, whose
    // FormData reads these three from the part and the file from the uri.
    const part = toUploadPart(upload);
    expect(part).toEqual({ uri: upload.uri, name: 'label.jpg', type: 'image/jpeg', bytes: expect.any(Function) });
  });

  it('documents why: the legacy {uri, name, type} part alone is rejected before any request', async () => {
    const legacy = new RNFormData();
    legacy.append('image', { uri: upload.uri, name: upload.name, type: upload.type } as unknown as Blob);

    await expect(normalizeBodyInitAsync(legacy)).rejects.toThrow('Unsupported FormDataPart implementation');
  });
});
