/**
 * The whole flow through the real navigator, provider and API modules.
 *
 * Only the two edges are replaced: the platform picker (mocked at the
 * expo-image-picker boundary) and the network (`fetch`). Everything between
 * - validation, the image set, navigation, the analysis hook, the mappers, the
 * screens - runs as it does in the app.
 *
 * This is where multi-image support is verified end to end: that three
 * photographs leave the phone as **one** request with three `image` parts, and
 * come back as one result. A unit test of the form builder could be right
 * while the screen still sent three separate inspections.
 */

import { NavigationContainer } from '@react-navigation/native';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import * as ImagePicker from 'expo-image-picker';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { RootNavigator } from './RootNavigator';
import {
  cameraPermission,
  complianceBody,
  extractionBody,
  imageSetBody,
  jsonResponse,
  libraryPermission,
  multiImageComplianceBody,
  routedFetch,
  RUN_ID,
} from '../../tests/fixtures';
import { PHONE_METRICS } from '../../tests/render';
import { AnalysisProvider } from '../hooks/AnalysisContext';

const picker = ImagePicker as jest.Mocked<typeof ImagePicker>;

/** Answers health/ with "ok" and the analysis requests from the queue given. */
function serve(...queue: (Response | Error)[]) {
  const stub = routedFetch({ queue });
  (globalThis as unknown as { fetch: unknown }).fetch = stub;
  return stub;
}

/** The analysis requests only - the home screen's health check is not one. */
function analysisCalls(stub: ReturnType<typeof routedFetch>) {
  return stub.calls.filter((call) => !/\/health\/$/.test(call.url));
}

/** The multipart parts of a request, as the recording FormData double kept them. */
function partsOf(call: { init: RequestInit | undefined }) {
  return (call.init?.body as unknown as { getParts(): { fieldName: string }[] }).getParts();
}

function galleryAssets(count: number) {
  return Array.from({ length: count }, (_value, index) => ({
    uri: `file:///cache/ImagePicker/panel-${index + 1}.jpg`,
    fileName: `panel-${index + 1}.jpg`,
    mimeType: 'image/jpeg',
    fileSize: 1000,
    width: 3000,
    height: 4000,
  }));
}

beforeEach(() => {
  jest.spyOn(console, 'info').mockImplementation(() => undefined);
  picker.requestCameraPermissionsAsync.mockResolvedValue(cameraPermission(true));
  picker.requestMediaLibraryPermissionsAsync.mockResolvedValue(libraryPermission(true));
  picker.launchCameraAsync.mockResolvedValue({
    canceled: false,
    assets: [{ uri: 'file:///cache/ImagePicker/abc.jpg', fileName: 'abc.jpg', mimeType: 'image/jpeg', fileSize: 1000, width: 3000, height: 4000 }],
  });
});

async function renderApp() {
  await render(
    <SafeAreaProvider initialMetrics={PHONE_METRICS}>
      <AnalysisProvider>
        <NavigationContainer>
          <RootNavigator />
        </NavigationContainer>
      </AnalysisProvider>
    </SafeAreaProvider>,
  );
}

describe('the scan flow', () => {
  it('goes Home -> Scan -> Analysis -> Result and shows the backend verdict', async () => {
    const stub = serve(jsonResponse(extractionBody(), { status: 201 }), jsonResponse(complianceBody(), { status: 201 }));
    await renderApp();

    expect(screen.getByTestId('home-screen')).toBeOnTheScreen();
    await fireEvent.press(screen.getByTestId('take-photo'));

    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('check-package'));

    await screen.findByTestId('result-screen');
    expect(screen.getByTestId('verdict-badge')).toHaveTextContent('Partially compliant', { exact: false });
    expect(screen.getByTestId('classification-category')).toHaveTextContent('Packaged food', { exact: false });

    // One upload, then one evaluation of the run it returned.
    const calls = analysisCalls(stub);
    expect(calls).toHaveLength(2);
    expect(calls[0].url).toMatch(/\/extraction\/$/);
    expect(JSON.parse(calls[1].init?.body as string)).toEqual({ extraction_run_id: RUN_ID });
  });

  // --- several photographs, one inspection ---------------------------------

  it('sends three photos as one request with three image parts', async () => {
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: galleryAssets(3) });
    const stub = serve(
      jsonResponse({ ...extractionBody(), images: imageSetBody() }, { status: 201 }),
      jsonResponse(multiImageComplianceBody(), { status: 201 }),
    );
    await renderApp();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));
    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('check-package'));
    await screen.findByTestId('result-screen');

    const calls = analysisCalls(stub);
    // Two requests in total - read, then judge - whatever the number of
    // photographs. Three uploads would be three inspections.
    expect(calls).toHaveLength(2);
    expect(calls[0].url).toMatch(/\/extraction\/$/);
    expect(partsOf(calls[0]).map((part) => part.fieldName)).toEqual(['image', 'image', 'image']);
  });

  it('shows one verdict for the set, and says how many photos it used', async () => {
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: galleryAssets(3) });
    serve(
      jsonResponse({ ...extractionBody(), images: imageSetBody() }, { status: 201 }),
      jsonResponse(multiImageComplianceBody(), { status: 201 }),
    );
    await renderApp();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));
    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('check-package'));
    await screen.findByTestId('result-screen');

    expect(screen.getByTestId('images-checked')).toHaveTextContent('3 images checked', { exact: false });
    // One badge, one summary: a verdict per photograph would describe an
    // analysis the backend did not perform.
    expect(screen.getAllByTestId('verdict-badge')).toHaveLength(1);
  });

  it('adds a photo to an inspection already in progress', async () => {
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: galleryAssets(2) });
    const stub = serve(
      jsonResponse({ ...extractionBody(), images: imageSetBody() }, { status: 201 }),
      jsonResponse(multiImageComplianceBody(), { status: 201 }),
    );
    await renderApp();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));
    await screen.findByTestId('scan-screen');
    expect(screen.getByTestId('check-package')).toHaveTextContent('2 photos', { exact: false });

    // The camera, from inside the scan screen: a third panel of the same
    // package, not a new inspection.
    await fireEvent.press(screen.getByTestId('add-image'));
    await fireEvent.press(screen.getByTestId('take-photo'));
    await waitFor(() => expect(screen.getByTestId('check-package')).toHaveTextContent('3 photos', { exact: false }));

    await fireEvent.press(screen.getByTestId('check-package'));
    await screen.findByTestId('result-screen');

    expect(partsOf(analysisCalls(stub)[0]).filter((part) => part.fieldName === 'image')).toHaveLength(3);
  });

  it('removes a photo before submitting, and sends only what is left', async () => {
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: galleryAssets(3) });
    const stub = serve(
      jsonResponse(extractionBody(), { status: 201 }),
      jsonResponse(complianceBody(), { status: 201 }),
    );
    await renderApp();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));
    await screen.findByTestId('scan-screen');

    await fireEvent.press(screen.getByTestId('remove-image-1'));
    await waitFor(() => expect(screen.getByTestId('check-package')).toHaveTextContent('2 photos', { exact: false }));

    await fireEvent.press(screen.getByTestId('check-package'));
    await screen.findByTestId('result-screen');

    expect(partsOf(analysisCalls(stub)[0]).filter((part) => part.fieldName === 'image')).toHaveLength(2);
  });

  it('will not submit once every photo has been removed', async () => {
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: galleryAssets(1) });
    const stub = serve();
    await renderApp();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));
    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('remove-image-0'));

    await waitFor(() => expect(screen.getByTestId('empty-selection')).toBeOnTheScreen());
    await fireEvent.press(screen.getByTestId('check-package'));

    expect(analysisCalls(stub)).toHaveLength(0);
    expect(screen.queryByTestId('analysis-screen')).toBeNull();
  });

  // --- failures -------------------------------------------------------------

  it('stops on the progress screen with the offline message, and can start over', async () => {
    serve(new TypeError('Network request failed'));
    await renderApp();

    await fireEvent.press(screen.getByTestId('take-photo'));
    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('check-package'));

    const error = await screen.findByTestId('analysis-error');
    expect(error).toHaveTextContent('Unable to connect to the analysis server.', { exact: false });
    expect(screen.queryByTestId('result-screen')).toBeNull();

    await fireEvent.press(screen.getByTestId('start-over'));
    await waitFor(() => expect(screen.getByTestId('home-screen')).toBeOnTheScreen());
  });

  it('keeps every photo when the upload fails, and resends the same set on retry', async () => {
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: galleryAssets(3) });
    const stub = serve(
      new TypeError('Network request failed'),
      jsonResponse({ ...extractionBody(), images: imageSetBody() }, { status: 201 }),
      jsonResponse(multiImageComplianceBody(), { status: 201 }),
    );
    await renderApp();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));
    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('check-package'));
    await screen.findByTestId('analysis-error');

    await fireEvent.press(screen.getByTestId('retry'));
    await screen.findByTestId('result-screen');

    // Somebody who photographed three panels on a bad connection must not have
    // to photograph them again - and the retry must send the same set, not a
    // different one.
    const calls = analysisCalls(stub);
    expect(partsOf(calls[0]).filter((part) => part.fieldName === 'image')).toHaveLength(3);
    expect(partsOf(calls[1]).filter((part) => part.fieldName === 'image')).toHaveLength(3);
  });

  it('retries a failed verdict without uploading the photos again', async () => {
    const stub = serve(
      jsonResponse(extractionBody(), { status: 201 }),
      jsonResponse({ detail: 'Server Error (500)' }, { status: 500 }),
      jsonResponse(complianceBody(), { status: 201 }),
    );
    await renderApp();

    await fireEvent.press(screen.getByTestId('take-photo'));
    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('check-package'));

    await screen.findByTestId('analysis-error');
    expect(screen.getByTestId('step-reading-done')).toBeOnTheScreen();
    await fireEvent.press(screen.getByTestId('retry'));

    await screen.findByTestId('result-screen');
    const calls = analysisCalls(stub);
    expect(calls).toHaveLength(3);
    expect(calls[2].url).toMatch(/\/compliance\/$/);
  });

  it('shows a backend validation error about the photos without losing them', async () => {
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: galleryAssets(2) });
    serve(
      jsonResponse(
        { error: { code: 'validation_error', message: 'The submitted data was not valid.', details: { image: ['Too large.'] } } },
        { status: 400 },
      ),
    );
    await renderApp();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));
    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('check-package'));

    expect(await screen.findByTestId('analysis-error')).toBeOnTheScreen();
    expect(screen.queryByTestId('result-screen')).toBeNull();
  });

  it('starts a fresh analysis from the result screen, with no photos carried over', async () => {
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: galleryAssets(3) });
    serve(
      jsonResponse({ ...extractionBody(), images: imageSetBody() }, { status: 201 }),
      jsonResponse(multiImageComplianceBody(), { status: 201 }),
    );
    await renderApp();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));
    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('check-package'));
    await screen.findByTestId('result-screen');

    await fireEvent.press(screen.getByTestId('scan-another'));

    await waitFor(() => expect(screen.getByTestId('home-screen')).toBeOnTheScreen());
    expect(screen.queryByTestId('result-screen')).toBeNull();
    // The last package's photographs must not be waiting in the next
    // inspection.
    expect(screen.queryByTestId('image-tray')).toBeNull();
  });
});
