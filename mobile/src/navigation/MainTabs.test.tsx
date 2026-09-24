/**
 * The tab shell: the five destinations, the header over them, and the geometry
 * that has to hold at every supported width.
 *
 * WHAT "RESPONSIVE" MEANS IN THIS FILE, EXACTLY
 * --------------------------------------------
 * Jest does not run Yoga, so nothing here measures a rendered pixel or a glyph.
 * What the width-parameterised tests below check is the *contract* that makes the
 * bar fit: every item divides the bar evenly rather than sizing to its own label,
 * every label is one line with font scaling off, and all five labels are present
 * and spelled in full. A truncated label would still read as its full string in
 * this tree, so these tests cannot catch truncation directly - they catch the
 * things that would *cause* it, and `tabGeometry` below checks the arithmetic
 * that says it cannot happen.
 *
 * Real-device confirmation is not something a Jest run can stand in for, and this
 * file does not claim to be it.
 */

import { NavigationContainer } from '@react-navigation/native';
import { fireEvent, render, screen, within } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { MainTabs } from './MainTabs';
import { routedFetch } from '../../tests/fixtures';
import { metricsFor, PHONE_METRICS, SHELL_WIDTHS } from '../../tests/render';
import { AnalysisProvider } from '../hooks/AnalysisContext';
import { MIN_TOUCH_TARGET, shell } from '../theme';

/** Tab button testID, visible label, spoken name, and the screen it reveals. */
const DESTINATIONS = [
  { testID: 'tab-home', label: 'Home', spoken: 'Home', screen: 'home-screen' },
  { testID: 'tab-scan', label: 'Scan', spoken: 'Scan a package', screen: 'scan-screen' },
  {
    testID: 'tab-history',
    label: 'History',
    spoken: 'Previous inspections',
    screen: 'inspections-screen',
  },
  { testID: 'tab-rules', label: 'Rules', spoken: 'Rules and information', screen: 'rules-screen' },
  { testID: 'tab-settings', label: 'Settings', spoken: 'Settings', screen: 'settings-screen' },
] as const;

beforeEach(() => {
  (globalThis as unknown as { fetch: unknown }).fetch = routedFetch();
  jest.spyOn(console, 'info').mockImplementation(() => undefined);
});

async function renderTabs(width: (typeof SHELL_WIDTHS)[number] = 390) {
  await render(
    <SafeAreaProvider initialMetrics={width === 390 ? PHONE_METRICS : metricsFor(width)}>
      <AnalysisProvider>
        <NavigationContainer>
          <MainTabs />
        </NavigationContainer>
      </AnalysisProvider>
    </SafeAreaProvider>,
  );
}

describe('the tab bar', () => {
  it('offers exactly the five destinations, in bar order', async () => {
    await renderTabs();

    for (const destination of DESTINATIONS) {
      expect(screen.getByTestId(destination.testID)).toBeOnTheScreen();
    }
    // A sixth tab is not a styling change - it breaks the width arithmetic in
    // `theme.shell`, so it has to fail here.
    expect(screen.queryByTestId('tab-analysis')).toBeNull();
    expect(screen.queryByTestId('tab-result')).toBeNull();
  });

  it('starts on Home', async () => {
    await renderTabs();

    expect(screen.getByTestId('home-screen')).toBeOnTheScreen();
  });

  it('shows the branded header over every destination', async () => {
    await renderTabs();

    for (const destination of DESTINATIONS) {
      await fireEvent.press(screen.getByTestId(destination.testID));
      expect(screen.getByTestId('app-header')).toHaveTextContent('NIRIKSHAN', { exact: false });
    }
  });

  it('carries no account or profile action in the header', async () => {
    await renderTabs();

    // There is no account system, so the header's right-hand action was dropped
    // rather than pointed at something. See `AppHeader`.
    const header = screen.getByTestId('app-header');
    expect(within(header).queryByLabelText(/account/i)).toBeNull();
    expect(within(header).queryByRole('button')).toBeNull();
  });

  it.each(DESTINATIONS.map((d) => [d.label, d.testID, d.screen] as const))(
    'opens %s when its tab is pressed',
    async (_label, testID, screenTestID) => {
      await renderTabs();

      await fireEvent.press(screen.getByTestId(testID));

      expect(screen.getByTestId(screenTestID)).toBeOnTheScreen();
    },
  );

  it('gives the two shortened labels their full names for a screen reader', async () => {
    await renderTabs();

    // "History" is the label for the Inspections route and "Rules" for Rules &
    // information, because the full names do not fit 11 pt at 360 pt wide. The
    // spoken name is the full one, so nothing is lost to a screen reader.
    expect(screen.getByLabelText('Previous inspections')).toBeOnTheScreen();
    expect(screen.getByLabelText('Rules and information')).toBeOnTheScreen();
  });

  it.each(DESTINATIONS.map((d) => [d.label, d.testID, d.spoken] as const))(
    'names the %s tab the same way to a screen reader as on screen',
    async (label, testID, spoken) => {
      await renderTabs();

      expect(labelsIn(testID, label).length).toBeGreaterThan(0);
      expect(screen.getByLabelText(spoken)).toBeOnTheScreen();
    },
  );
});

/**
 * Every rendering of one tab's label.
 *
 * There are **two**, not one: `BottomTabItem` calls `tabBarIcon` for both the
 * focused and the unfocused state and keeps both in the tree, cross-fading their
 * opacity when the selection moves. So a `getByText` here would throw "found
 * multiple elements" on a perfectly healthy bar, and asserting on only the first
 * would leave the state the user is about to see unchecked. Both copies have to
 * satisfy the contract, so both are returned and both are asserted.
 */
function labelsIn(tabTestID: string, label: string) {
  return within(screen.getByTestId(tabTestID)).getAllByText(label);
}

describe.each(SHELL_WIDTHS)('the tab bar at %i pt wide', (width) => {
  it('shows all five labels, spelled in full', async () => {
    await renderTabs(width);

    for (const destination of DESTINATIONS) {
      expect(labelsIn(destination.testID, destination.label).length).toBeGreaterThan(0);
      // An ellipsis in a tab label means the bar has failed. React Native would
      // render one as part of the text node, so this is checkable even though the
      // width is not.
      const tab = screen.getByTestId(destination.testID);
      expect(tab).not.toHaveTextContent('…', { exact: false });
      expect(tab).not.toHaveTextContent('...', { exact: false });
    }
  });

  it('keeps every label on one line and out of the font-scale ramp', async () => {
    await renderTabs(width);

    for (const destination of DESTINATIONS) {
      for (const label of labelsIn(destination.testID, destination.label)) {
        // Two lines would make the bar taller than 56 and misalign the icons; font
        // scaling would do the same at the largest accessibility sizes. The label is
        // already at the 11 pt floor, so it does not shrink either.
        expect(label.props.numberOfLines).toBe(1);
        expect(label.props.allowFontScaling).toBe(false);
      }
    }
  });

  it('shows the header and the destination together', async () => {
    await renderTabs(width);

    expect(screen.getByTestId('app-header')).toBeOnTheScreen();
    expect(screen.getByTestId('home-screen')).toBeOnTheScreen();
  });
});

/**
 * The arithmetic the bar depends on, checked without rendering anything.
 *
 * This is the part that genuinely proves five tabs fit: the bar is divided into
 * five equal items, so the only question is whether one fifth of the narrowest
 * supported width is enough for a 48 pt target and an 11 pt word.
 */
describe('tab geometry', () => {
  /** What one item gets: the bar's width, less its 4 pt padding either side, / 5. */
  const itemWidth = (barWidth: number) => (barWidth - 8) / 5;
  /** What the label gets inside it: the item, less the item's 3 pt padding either side. */
  const labelWidth = (barWidth: number) => itemWidth(barWidth) - 6;

  it.each(SHELL_WIDTHS)('gives each of the five items a real touch target at %i pt', (width) => {
    expect(itemWidth(width)).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET);
  });

  it('leaves room for the longest label at the narrowest supported width', () => {
    // "Settings" is the longest of the five. At 11 pt in the system font it
    // measures roughly 47 pt - an estimate, not a measurement, which is why the
    // assertion is a floor with headroom rather than a comparison to that figure.
    expect(labelWidth(360)).toBeGreaterThan(60);
  });

  it('is 70.4 pt per item at 360 pt, the width the handoff was checked against', () => {
    expect(Number(itemWidth(360).toFixed(1))).toBe(70.4);
    expect(Number(labelWidth(360).toFixed(1))).toBe(64.4);
  });

  it('keeps the icon and its selected pill inside the bar height', () => {
    // 5 top padding + the pill + 3 gap + a 14 pt label line has to fit 56.
    expect(5 + shell.tabPill.height + 3 + 14).toBeLessThanOrEqual(shell.tabBarHeight);
    expect(shell.tabIcon).toBeLessThanOrEqual(shell.tabPill.height);
  });
});
