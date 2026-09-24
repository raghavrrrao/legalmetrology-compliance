/**
 * Settings shows real configuration and no invented controls.
 *
 * Half of these assertions are negative, and that is the point of the screen: a
 * settings page is the easiest place in an application to add a switch for
 * something that does not exist. Each absence below names the thing that would
 * have to be built before the control could honestly appear.
 */

import { fireEvent, render, screen } from '@testing-library/react-native';
import { Linking } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { SettingsScreen } from './SettingsScreen';
import { routedFetch } from '../../tests/fixtures';
import { PHONE_METRICS, stubNavigation } from '../../tests/render';
import { MAX_INSPECTION_IMAGES, MAX_UPLOAD_SIZE_MB } from '../config/env';
import { RULE_COUNTS } from '../data/lmpcRules';

beforeEach(() => {
  // The screen embeds `ServerStatus`, which checks `health/` on mount;
  // `routedFetch` answers that by default.
  (globalThis as unknown as { fetch: unknown }).fetch = routedFetch();
  jest.spyOn(console, 'info').mockImplementation(() => undefined);
});

async function renderSettings() {
  const navigation = stubNavigation();
  await render(
    <SafeAreaProvider initialMetrics={PHONE_METRICS}>
      <SettingsScreen
        navigation={navigation as never}
        route={{ key: 'Settings', name: 'Settings' } as never}
      />
    </SafeAreaProvider>,
  );
  return { navigation };
}

describe('SettingsScreen', () => {
  it('shows the configured inspection limits, from config rather than literals', async () => {
    await renderSettings();

    expect(screen.getByText('Photographs per inspection')).toBeOnTheScreen();
    expect(screen.getByText(String(MAX_INSPECTION_IMAGES))).toBeOnTheScreen();
    expect(screen.getByText(`${MAX_UPLOAD_SIZE_MB} MB`)).toBeOnTheScreen();
  });

  it('says the server is the authority on those limits', async () => {
    await renderSettings();

    expect(screen.getByText(/The server decides either way/)).toBeOnTheScreen();
  });

  it('reports how many of the recorded rules are evaluated, and opens the rules screen', async () => {
    const { navigation } = await renderSettings();

    const row = screen.getByTestId('open-rules');
    expect(row).toHaveTextContent(`${RULE_COUNTS.evaluated} of ${RULE_COUNTS.recorded}`, {
      exact: false,
    });

    await fireEvent.press(row);
    expect(navigation.navigate).toHaveBeenCalledWith('Rules');
  });

  it('hands permissions to the operating system instead of faking a toggle', async () => {
    const openSettings = jest.spyOn(Linking, 'openSettings').mockResolvedValue(undefined);
    await renderSettings();

    await fireEvent.press(screen.getByTestId('open-system-settings'));

    expect(openSettings).toHaveBeenCalled();
    // No switch, because the app cannot grant or revoke anything.
    expect(screen.queryByRole('switch')).toBeNull();
  });

  it('offers no account, sync, notification or theme controls', async () => {
    await renderSettings();

    for (const absent of [
      /sign in/i,
      /log ?in/i,
      /account/i,
      /profile/i,
      /notification/i,
      /sync/i,
      /dark mode/i,
      /theme/i,
    ]) {
      expect(screen.queryByText(absent)).toBeNull();
    }
  });

  it('has no editable field, because the server address is fixed at build time', async () => {
    await renderSettings();

    // A text input here would accept typing and change nothing:
    // `EXPO_PUBLIC_API_BASE_URL` is inlined into the bundle when it is built.
    expect(screen.queryByTestId('api-base-url-input')).toBeNull();
    expect(screen.queryByPlaceholderText(/http/i)).toBeNull();
  });

  it('repeats that nothing is analysed on the phone', async () => {
    await renderSettings();

    expect(screen.getByTestId('settings-footnote')).toHaveTextContent(
      'Nothing is analysed on this phone',
      { exact: false },
    );
  });
});
