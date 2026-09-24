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
  imageBody,
  IMAGE_ID,
  IMAGE_ID_2,
  IMAGE_ID_3,
  imageSetBody,
  jsonResponse,
  libraryPermission,
  multiImageComplianceBody,
  routedFetch,
  runImageBody,
  RUN_ID,
} from '../../tests/fixtures';
import { PHONE_METRICS } from '../../tests/render';
import { AnalysisProvider } from '../hooks/AnalysisContext';

const picker = ImagePicker as jest.Mocked<typeof ImagePicker>;

/** Answers health/ with "ok", rules/ with a list, and the analysis requests from the queue given. */
function serve(...queue: (Response | Error)[]) {
  const stub = routedFetch({ queue });
  (globalThis as unknown as { fetch: unknown }).fetch = stub;
  return stub;
}

/** The rule-list requests the Rules tab makes. */
function ruleListCalls(stub: ReturnType<typeof routedFetch>) {
  return stub.calls.filter((call) => /\/rules\/(\?.*)?$/.test(call.url));
}

/**
 * The analysis requests only - neither the home screen's health check nor the
 * Rules tab's rule list is one.
 */
function analysisCalls(stub: ReturnType<typeof routedFetch>) {
  return stub.calls.filter(
    (call) => !/\/health\/$/.test(call.url) && !/\/rules\/(\?.*)?$/.test(call.url),
  );
}

/**
 * The titles of every native stack header in the tree.
 *
 * react-native-screens renders a header as an `RNSScreenStackHeaderConfig` host
 * element carrying `title` as a prop - it is drawn natively, so it is not a Text
 * node a `getByText` could find. Walking the rendered JSON is the only way to
 * read it in Jest.
 */
function headerTitles(): string[] {
  const titles: string[] = [];
  const walk = (node: unknown) => {
    if (!node || typeof node !== 'object') {
      return;
    }
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    const element = node as { type?: string; props?: { title?: unknown }; children?: unknown };
    if (element.type === 'RNSScreenStackHeaderConfig' && typeof element.props?.title === 'string') {
      titles.push(element.props.title);
    }
    walk(element.children);
  };
  walk(screen.toJSON());
  return titles;
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

  it('does not keep saying "Analysing" in the header once the analysis has stopped', async () => {
    serve(new TypeError('Network request failed'));
    await renderApp();

    await fireEvent.press(screen.getByTestId('take-photo'));
    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('check-package'));
    await screen.findByTestId('analysis-error');

    // The body says "Analysis stopped". The header used to say "Analysing"
    // above it regardless - on a device, the two contradicted each other.
    expect(screen.getByText('Analysis stopped')).toBeOnTheScreen();
    const titles = headerTitles();
    expect(titles).toContain('Analysis');
    expect(titles).not.toContain('Analysing');
  });

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

/**
 * The same flow, now that the five destinations are bottom tabs and Analysis and
 * Result are pushed over them.
 *
 * The restructure moved Home and Scan from a stack into a tab navigator, which
 * changes three things the flow depends on: a tab screen's `navigate('Analysis')`
 * has to bubble to the stack above it, "back to the start" can no longer be
 * `popToTop()`, and a tab the user has left stays mounted rather than being
 * unwound. The tests below are about those three, and about the one new way a
 * user can now interrupt an inspection: switching tabs in the middle of it.
 */
describe('the scan flow through the tab shell', () => {
  it('reaches Analysis from the Scan tab, which the tab navigator itself cannot do', async () => {
    const stub = serve(
      jsonResponse(extractionBody(), { status: 201 }),
      jsonResponse(complianceBody(), { status: 201 }),
    );
    await renderApp();

    // Straight to the Scan tab, rather than through Home's "Take photo" - so the
    // push out of a tab is exercised on its own.
    await fireEvent.press(screen.getByTestId('tab-scan'));
    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('take-photo'));
    await waitFor(() => expect(screen.getByTestId('image-tray')).toBeOnTheScreen());

    await fireEvent.press(screen.getByTestId('check-package'));

    // `Analysis` is on the root stack, so the tab navigator has no such route and
    // React Navigation has to hand the action to its parent. If that stopped
    // working the button would silently do nothing.
    //
    // Arriving at Result is the assertion, rather than catching Analysis on the
    // way: with the responses already queued, Analysis reaches `complete` and
    // replaces itself in the same batch of work, so looking for it is a race. It
    // is not skipped - Result is only reachable through it.
    await screen.findByTestId('result-screen');
    expect(analysisCalls(stub)).toHaveLength(2);
  });

  it('covers the tab bar while an inspection is being analysed', async () => {
    serve(jsonResponse(extractionBody(), { status: 201 }), jsonResponse(complianceBody(), { status: 201 }));
    await renderApp();

    await fireEvent.press(screen.getByTestId('take-photo'));
    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('check-package'));
    await screen.findByTestId('result-screen');

    // Analysis and Result are pushed over the bar, not tabs themselves. A tab
    // that cannot be left - Analysis holds the screen while a request is in
    // flight - would be a broken tab, so it must not be reachable as one.
    expect(screen.queryByTestId('tab-home')).toBeNull();
  });

  it('keeps the photographs when the user visits another tab mid-inspection', async () => {
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: galleryAssets(3) });
    const stub = serve(
      jsonResponse({ ...extractionBody(), images: imageSetBody() }, { status: 201 }),
      jsonResponse(multiImageComplianceBody(), { status: 201 }),
    );
    await renderApp();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));
    await screen.findByTestId('scan-screen');
    expect(screen.getByTestId('check-package')).toHaveTextContent('3 photos', { exact: false });

    // Newly possible now that there is a bar: read the rules, then come back.
    // The set lives in `AnalysisProvider` above the navigator precisely so that
    // this cannot lose it.
    await fireEvent.press(screen.getByTestId('tab-rules'));
    await screen.findByTestId('rules-screen');
    // The Rules tab lists what the server reports, with one request of its own
    // that touches neither the photographs nor the analysis queue.
    await screen.findByTestId('rules-list');
    expect(ruleListCalls(stub)).toHaveLength(1);
    expect(analysisCalls(stub)).toHaveLength(0);
    await fireEvent.press(screen.getByTestId('tab-scan'));
    await screen.findByTestId('scan-screen');

    expect(screen.getByTestId('check-package')).toHaveTextContent('3 photos', { exact: false });

    await fireEvent.press(screen.getByTestId('check-package'));
    await screen.findByTestId('result-screen');

    // And still one inspection of three photographs, not a new one.
    const calls = analysisCalls(stub);
    expect(calls).toHaveLength(2);
    expect(partsOf(calls[0]).filter((part) => part.fieldName === 'image')).toHaveLength(3);
  });

  it('returns to the Home tab from a finished result, not to the tab it started on', async () => {
    serve(jsonResponse(extractionBody(), { status: 201 }), jsonResponse(complianceBody(), { status: 201 }));
    await renderApp();

    // Begin from the Scan tab, so "the tab it started on" is not Home.
    await fireEvent.press(screen.getByTestId('tab-scan'));
    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('take-photo'));
    await waitFor(() => expect(screen.getByTestId('image-tray')).toBeOnTheScreen());
    await fireEvent.press(screen.getByTestId('check-package'));
    await screen.findByTestId('result-screen');

    await fireEvent.press(screen.getByTestId('scan-another'));

    // `popToTop()` would have landed back on Scan, with the bar showing Scan
    // selected and an empty tray - which reads as the inspection having failed.
    await waitFor(() => expect(screen.getByTestId('home-screen')).toBeOnTheScreen());
    expect(screen.queryByTestId('result-screen')).toBeNull();
  });

  it('returns to the Home tab when an inspection is abandoned after a failure', async () => {
    serve(new TypeError('Network request failed'));
    await renderApp();

    await fireEvent.press(screen.getByTestId('tab-scan'));
    await screen.findByTestId('scan-screen');
    await fireEvent.press(screen.getByTestId('take-photo'));
    await waitFor(() => expect(screen.getByTestId('image-tray')).toBeOnTheScreen());
    await fireEvent.press(screen.getByTestId('check-package'));
    await screen.findByTestId('analysis-error');

    await fireEvent.press(screen.getByTestId('start-over'));

    await waitFor(() => expect(screen.getByTestId('home-screen')).toBeOnTheScreen());
  });

  it('sends the user from Home to the Scan tab when an inspection is started there', async () => {
    serve();
    await renderApp();

    await fireEvent.press(screen.getByTestId('take-photo'));

    // Home's "Take photo" seeds the set and then moves to the Scan tab. It is a
    // sibling now rather than a push, so nothing is stacked on top of the bar.
    await screen.findByTestId('scan-screen');
    expect(screen.getByTestId('tab-scan')).toBeOnTheScreen();
  });

  // --- the production regression, as four photographs ----------------------

  it('checks four photographs as one package and says so on the result', async () => {
    // Distinct ids, not just distinct filenames: the result screen keys its image
    // list by id, and four panels sharing `imageBody()`'s default id collapse into
    // one row - which would make this test pass while showing "4 images checked"
    // above a single panel.
    const fourPanels = [
      runImageBody({ position: 1, image: imageBody({ id: IMAGE_ID, original_filename: 'front.jpg' }) }),
      runImageBody({ position: 2, image: imageBody({ id: IMAGE_ID_2, original_filename: 'back.jpg' }) }),
      runImageBody({ position: 3, image: imageBody({ id: IMAGE_ID_3, original_filename: 'side.jpg' }) }),
      runImageBody({
        position: 4,
        image: imageBody({ id: '66666666-5555-4444-3333-222222222222', original_filename: 'base.jpg' }),
      }),
    ];
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: galleryAssets(4) });
    const stub = serve(
      jsonResponse({ ...extractionBody(), images: fourPanels }, { status: 201 }),
      jsonResponse(multiImageComplianceBody({ images: fourPanels }), { status: 201 }),
    );
    await renderApp();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));
    await screen.findByTestId('scan-screen');
    expect(screen.getByTestId('check-package')).toHaveTextContent('4 photos', { exact: false });

    await fireEvent.press(screen.getByTestId('check-package'));
    await screen.findByTestId('result-screen');

    // The shape verified against the deployed backend with four real photographs:
    // one upload carrying four `image` parts, then one evaluation of the run it
    // returned, and one verdict about the package.
    const calls = analysisCalls(stub);
    expect(calls).toHaveLength(2);
    expect(calls[0].url).toMatch(/\/extraction\/$/);
    expect(partsOf(calls[0]).map((part) => part.fieldName)).toEqual([
      'image',
      'image',
      'image',
      'image',
    ]);
    expect(calls[1].url).toMatch(/\/compliance\/$/);
    expect(JSON.parse(calls[1].init?.body as string)).toEqual({ extraction_run_id: RUN_ID });

    expect(screen.getByTestId('images-checked')).toHaveTextContent('4 images checked', {
      exact: false,
    });
    expect(screen.getByTestId('images-checked')).toHaveTextContent('one package, one result', {
      exact: false,
    });
    expect(screen.getAllByTestId('verdict-badge')).toHaveLength(1);
  });
});
