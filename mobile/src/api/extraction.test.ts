/**
 * The extraction client: what is uploaded, and how the reading is mapped.
 */

import { ApiError } from './client';
import {
  buildUploadFormData,
  EXTRACTION_TIMEOUT_MS,
  extractLabel,
  mapExtractionRun,
  mapProductClassification,
} from './extraction';
import { classificationBody, errorEnvelope, extractionBody, jsonResponse, RUN_ID } from '../../tests/fixtures';
import { mockFileBytes, type RecordedPart } from '../../tests/setup';

const fetchMock = jest.fn();

beforeEach(() => {
  (globalThis as unknown as { fetch: unknown }).fetch = fetchMock;
});

function parts(formData: FormData): RecordedPart[] {
  return (formData as unknown as { getParts(): RecordedPart[] }).getParts();
}

describe('buildUploadFormData', () => {
  it('sends the file under the field name the backend reads, with name, type and a byte source', () => {
    const formData = buildUploadFormData({ uri: 'file:///tmp/a.jpg', name: 'label.jpg', type: 'image/jpeg' });

    // `bytes()` is what expo/fetch reads; `uri` is what React Native's own
    // fetch reads. See uploadPart.expoFetch.test.ts for the encoding itself.
    expect(parts(formData)).toEqual([
      {
        fieldName: 'image',
        value: { uri: 'file:///tmp/a.jpg', name: 'label.jpg', type: 'image/jpeg', bytes: expect.any(Function) },
      },
    ]);
  });

  it('reads the bytes from the picked file, lazily', async () => {
    const formData = buildUploadFormData({ uri: 'file:///cache/ImagePicker/x.jpeg', name: 'label.jpg', type: 'image/jpeg' });
    const part = parts(formData)[0].value as { bytes: () => Promise<Uint8Array> };

    await expect(part.bytes()).resolves.toEqual(mockFileBytes);
  });

  it('adds view_type only when given', () => {
    const withView = buildUploadFormData({ uri: 'file:///a.png', name: 'a.png', type: 'image/png' }, 'back');
    expect(parts(withView)).toContainEqual({ fieldName: 'view_type', value: 'back' });

    const without = buildUploadFormData({ uri: 'file:///a.png', name: 'a.png', type: 'image/png' });
    expect(parts(without).map((part) => part.fieldName)).toEqual(['image']);
  });
});

describe('extractLabel', () => {
  it('posts multipart to extraction/ with the upload timeout and maps the response', async () => {
    fetchMock.mockResolvedValue(jsonResponse(extractionBody(), { status: 201 }));

    const run = await extractLabel({ uri: 'file:///a.jpg', name: 'a.jpg', type: 'image/jpeg' }, { viewType: 'front' });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/extraction\/$/);
    expect(init.method).toBe('POST');
    expect(parts(init.body).map((part) => part.fieldName)).toEqual(['image', 'view_type']);

    expect(run.id).toBe(RUN_ID);
    expect(run.engineName).toBe('tesseract');
    expect(run.producedUsableOutput).toBe(true);
    expect(run.fieldsRead).toHaveLength(2);
    expect(run.fieldsRead[0]).toEqual({
      fieldKey: 'net_quantity',
      rawValue: 'Net Qty: 500 g',
      normalizedValue: { quantity: 500, unit: 'g', uncertain: false },
      confidence: 0.87,
      boundingBox: { x: 4, y: 4, width: 300, height: 18 },
    });
    expect(run.image).toEqual(expect.objectContaining({ id: expect.any(String), width: 1600, height: 1200 }));
    expect(run.productClassification).toEqual(
      expect.objectContaining({ category: 'packaged-food', confidence: 0.7232, classifierName: 'tfidf-logreg' }),
    );
  });

  it('uses a longer timeout than the default for the upload', () => {
    expect(EXTRACTION_TIMEOUT_MS).toBeGreaterThan(15000);
  });

  it('lets a validation error propagate with its details', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(errorEnvelope('validation_error', 'The submitted data was not valid.', {
        image: ['Unsupported file extension. Allowed extensions: .jpeg, .jpg, .png, .webp.'],
      }), { status: 400 }),
    );

    await expect(extractLabel({ uri: 'file:///a.heic', name: 'a.heic', type: 'image/heic' })).rejects.toMatchObject({
      status: 400,
      code: 'validation_error',
    });
  });

  it('rejects a 2xx body that is not a run', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ unexpected: true }, { status: 201 }));

    const error = await extractLabel({ uri: 'file:///a.jpg', name: 'a.jpg', type: 'image/jpeg' }).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe('unexpected_response');
  });
});

describe('mapExtractionRun', () => {
  it('keeps "not found" and "could not be read" distinguishable', () => {
    const run = mapExtractionRun({
      ...extractionBody(),
      status: 'empty',
      produced_usable_output: false,
      error_code: 'no_text',
      error_message: 'The engine produced no text.',
      fields_read: [],
    });

    expect(run?.producedUsableOutput).toBe(false);
    expect(run?.errorCode).toBe('no_text');
    expect(run?.fieldsRead).toEqual([]);
  });

  it('keeps a null confidence null, never zero', () => {
    const run = mapExtractionRun(
      extractionBody({ fields_read: [{ field_key: 'mrp', raw_value: 'MRP 10', confidence: null }] }),
    );

    expect(run?.fieldsRead[0].confidence).toBeNull();
  });

  it('tolerates missing optional lists', () => {
    const run = mapExtractionRun({
      id: RUN_ID,
      engine_name: 'null-engine',
      engine_version: '0.0.0',
      is_placeholder: true,
      status: 'empty',
      produced_usable_output: false,
    });

    expect(run).toEqual(
      expect.objectContaining({ isPlaceholder: true, fieldsRead: [], unreadDeclarations: [], productClassification: null }),
    );
  });
});

describe('mapProductClassification', () => {
  it('maps a classification as the backend sends it', () => {
    expect(mapProductClassification(classificationBody())).toEqual({
      category: 'packaged-food',
      subcategory: 'health-supplement',
      confidence: 0.7232,
      subcategoryConfidence: 0.5517,
      evidence: ['signal: ingredients (typical of packaged-food)'],
      categoryScores: { 'packaged-food': 0.7232, 'packaged-non-food': 0.2768 },
      classifierName: 'tfidf-logreg',
      classifierVersion: '0.1.0',
    });
  });

  it('returns null when no classification was made', () => {
    // A backend without the classifier (tesseract <= 0.3.0), a null-engine
    // run, or a classifier that failed. Never a category.
    expect(mapProductClassification(null)).toBeNull();
    expect(mapProductClassification(undefined)).toBeNull();
  });

  it('returns null for a malformed value rather than showing it as a category', () => {
    expect(mapProductClassification({} as never)).toBeNull();
    expect(mapProductClassification({ category: 42 } as never)).toBeNull();
    expect(mapProductClassification('packaged-food' as never)).toBeNull();
  });

  it('keeps "unknown" as a category the classifier chose, and a null confidence null', () => {
    const mapped = mapProductClassification(classificationBody({ category: 'unknown', subcategory: null, confidence: null }));

    expect(mapped?.category).toBe('unknown');
    expect(mapped?.subcategory).toBeNull();
    expect(mapped?.confidence).toBeNull();
  });
});
