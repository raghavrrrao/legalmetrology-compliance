/**
 * The whole flow through the real navigator, provider and API modules.
 *
 * Only the two edges are replaced: the platform picker (mocked at the
 * expo-image-picker boundary) and the network (`fetch`). Everything between
 * - validation, navigation, the analysis hook, the mappers, the screens -
 * runs as it does in the app.
 */

import { NavigationContainer } from '@react-navigation/native';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import * as ImagePicker from 'expo-image-picker';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { RootNavigator } from './RootNavigator';
import { cameraPermission, complianceBody, extractionBody, jsonResponse, RUN_ID } from '../../tests/fixtures';
import { PHONE_METRICS } from '../../tests/render';
import { AnalysisProvider } from '../hooks/AnalysisContext';

const picker = ImagePicker as jest.Mocked<typeof ImagePicker>;
const fetchMock = jest.fn();

beforeEach(() => {
  (globalThis as unknown as { fetch: unknown }).fetch = fetchMock;
  picker.requestCameraPermissionsAsync.mockResolvedValue(cameraPermission(true));
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
  it('goes Home -> Preview -> Analysis -> Result and shows the backend verdict', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(extractionBody(), { status: 201 }))
      .mockResolvedValueOnce(jsonResponse(complianceBody(), { status: 201 }));
    await renderApp();

    expect(screen.getByTestId('home-screen')).toBeOnTheScreen();
    await fireEvent.press(screen.getByTestId('take-photo'));

    await screen.findByTestId('preview-screen');
    await fireEvent.press(screen.getByTestId('use-photo'));

    await screen.findByTestId('result-screen');
    expect(screen.getByTestId('verdict-badge')).toHaveTextContent('Partially compliant', { exact: false });
    expect(screen.getByTestId('classification-category')).toHaveTextContent('Packaged food', { exact: false });

    // One upload, then one evaluation of the run it returned.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/extraction\/$/);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ extraction_run_id: RUN_ID });
  });

  it('stops on the progress screen with the offline message, and can start over', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Network request failed'));
    await renderApp();

    await fireEvent.press(screen.getByTestId('take-photo'));
    await screen.findByTestId('preview-screen');
    await fireEvent.press(screen.getByTestId('use-photo'));

    const error = await screen.findByTestId('analysis-error');
    expect(error).toHaveTextContent('Unable to connect to the analysis server.', { exact: false });
    expect(screen.queryByTestId('result-screen')).toBeNull();

    await fireEvent.press(screen.getByTestId('start-over'));
    await waitFor(() => expect(screen.getByTestId('home-screen')).toBeOnTheScreen());
  });

  it('retries a failed verdict without uploading the photo again', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(extractionBody(), { status: 201 }))
      .mockResolvedValueOnce(jsonResponse({ detail: 'Server Error (500)' }, { status: 500 }))
      .mockResolvedValueOnce(jsonResponse(complianceBody(), { status: 201 }));
    await renderApp();

    await fireEvent.press(screen.getByTestId('take-photo'));
    await screen.findByTestId('preview-screen');
    await fireEvent.press(screen.getByTestId('use-photo'));

    await screen.findByTestId('analysis-error');
    expect(screen.getByTestId('step-reading-done')).toBeOnTheScreen();
    await fireEvent.press(screen.getByTestId('retry'));

    await screen.findByTestId('result-screen');
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[2][0]).toMatch(/\/compliance\/$/);
  });

  it('starts a fresh analysis from the result screen', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(extractionBody(), { status: 201 }))
      .mockResolvedValueOnce(jsonResponse(complianceBody(), { status: 201 }));
    await renderApp();

    await fireEvent.press(screen.getByTestId('take-photo'));
    await screen.findByTestId('preview-screen');
    await fireEvent.press(screen.getByTestId('use-photo'));
    await screen.findByTestId('result-screen');

    await fireEvent.press(screen.getByTestId('scan-another'));

    await waitFor(() => expect(screen.getByTestId('home-screen')).toBeOnTheScreen());
    expect(screen.queryByTestId('result-screen')).toBeNull();
  });
});
