/**
 * The Inspections screen must not imply a history it does not have.
 *
 * The handoff drew a populated list; this build has nowhere to read one from and
 * no identity to scope one to (the screen's own doc comment has the detail). The
 * assertions below are therefore mostly negative - they pin the *absence* of
 * placeholder rows and of a promise that rows will appear - because those are the
 * two ways this screen could start lying without anybody noticing.
 */

import { fireEvent, render, screen } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { InspectionsScreen } from './InspectionsScreen';
import { PHONE_METRICS, stubNavigation } from '../../tests/render';

async function renderInspections() {
  const navigation = stubNavigation();
  await render(
    <SafeAreaProvider initialMetrics={PHONE_METRICS}>
      <InspectionsScreen
        navigation={navigation as never}
        route={{ key: 'Inspections', name: 'Inspections' } as never}
      />
    </SafeAreaProvider>,
  );
  return { navigation };
}

describe('InspectionsScreen', () => {
  it('shows the empty state', async () => {
    await renderInspections();

    expect(screen.getByTestId('inspections-screen')).toBeOnTheScreen();
    expect(screen.getByTestId('inspections-empty')).toBeOnTheScreen();
    expect(screen.getByText('Nothing to show here yet')).toBeOnTheScreen();
  });

  it('carries none of the handoff specimen placeholders', async () => {
    await renderInspections();

    // `[PACKAGE NAME]` and `[DATE]` are layout placeholders from the design
    // board. If either ever reaches a real screen it is a bug, and a loud one -
    // it would look like data.
    expect(screen.queryByText(/\[PACKAGE NAME\]/)).toBeNull();
    expect(screen.queryByText(/\[DATE\]/)).toBeNull();
    expect(screen.queryByText(/\[/)).toBeNull();
  });

  it('does not promise that finished inspections will be listed here', async () => {
    await renderInspections();

    // The handoff's copy was "Every inspection you complete is listed here,
    // newest first." This build keeps no such record, so that sentence - and any
    // rephrasing of it - must not be on the screen.
    expect(screen.queryByText(/listed here/i)).toBeNull();
    expect(screen.queryByText(/newest first/i)).toBeNull();
    expect(screen.getByText(/not kept on this phone/i)).toBeOnTheScreen();
  });

  it('explains that listing per person needs an identity the app does not have', async () => {
    await renderInspections();

    const footnote = screen.getByTestId('inspections-footnote');
    // The server does store checks - saying otherwise would be the opposite
    // error, understating what exists.
    expect(footnote).toHaveTextContent('does store every check', { exact: false });
    expect(footnote).toHaveTextContent('signs in to nothing', { exact: false });
  });

  it('offers the scan tab as the way out of the empty state', async () => {
    const { navigation } = await renderInspections();

    await fireEvent.press(screen.getByTestId('scan-from-inspections'));

    expect(navigation.navigate).toHaveBeenCalledWith('Scan');
  });
});
