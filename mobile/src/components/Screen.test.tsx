/**
 * Who pays the bottom safe-area inset.
 *
 * `Screen` is used from both navigators, and the answer differs: under the tab
 * bar the bar has already cleared the home indicator, so adding the inset again
 * leaves a visible gap; on a pushed screen there is no bar and the inset is still
 * this component's to pay. Both directions are asserted here because each one is
 * a real bug in the other's shape - dead space under the last card, or a footer
 * button sitting under the home indicator.
 *
 * `BottomTabBarHeightContext` is provided directly rather than by rendering a
 * whole tab navigator: the question is what `Screen` does with a bar height, and
 * a navigator would answer it through two more layers of layout.
 */

import { BottomTabBarHeightContext } from '@react-navigation/bottom-tabs';
import { render, screen } from '@testing-library/react-native';
import { Text, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { Screen } from './Screen';
import { PHONE_METRICS } from '../../tests/render';
import { spacing } from '../theme';

const BOTTOM_INSET = PHONE_METRICS.insets.bottom;
/** Whatever the navigator reports; only its presence changes the behaviour. */
const TAB_BAR_HEIGHT = 56 + BOTTOM_INSET;

async function renderScreen({
  footer,
  underTabBar,
}: {
  footer?: boolean;
  underTabBar: boolean;
}) {
  const body = (
    <Screen testID="subject" footer={footer ? <Text>Pinned action</Text> : undefined}>
      <View testID="content" />
    </Screen>
  );
  await render(
    <SafeAreaProvider initialMetrics={PHONE_METRICS}>
      {underTabBar ? (
        <BottomTabBarHeightContext.Provider value={TAB_BAR_HEIGHT}>
          {body}
        </BottomTabBarHeightContext.Provider>
      ) : (
        body
      )}
    </SafeAreaProvider>,
  );
}

/** A style prop as one flat object, however many array layers it arrived in. */
function flatten(style: unknown): Record<string, number> {
  const layers = (Array.isArray(style) ? style.flat(Infinity) : [style]).filter(Boolean);
  return Object.assign({}, ...layers) as Record<string, number>;
}

/** The padding the scrolling body reserves. */
function scrollPadding() {
  return flatten(screen.getByTestId('screen-scroll').props.contentContainerStyle);
}

/** The padding the pinned footer reserves - what keeps its button off the edge. */
function footerPadding() {
  return flatten(screen.getByTestId('screen-footer').props.style);
}

describe('Screen, without a footer', () => {
  it('pays the bottom inset when there is no tab bar below it', async () => {
    await renderScreen({ underTabBar: false });

    expect(scrollPadding().paddingBottom).toBe(spacing.xl + BOTTOM_INSET);
  });

  it('leaves the bottom inset to the tab bar when there is one', async () => {
    await renderScreen({ underTabBar: true });

    // Not `spacing.xl + insets.bottom`: that would be the inset counted twice,
    // and on this phone it would show as 34 pt of dead space above the bar.
    expect(scrollPadding().paddingBottom).toBe(spacing.xl);
  });
});

describe('Screen, with a pinned footer', () => {
  it('keeps the footer clear of the home indicator when there is no tab bar', async () => {
    await renderScreen({ footer: true, underTabBar: false });

    expect(screen.getByText('Pinned action')).toBeOnTheScreen();
    // Analysis and Result are pushed over the bar, so nothing below this footer
    // clears the home indicator for it.
    expect(footerPadding().paddingBottom).toBe(spacing.lg + BOTTOM_INSET);
  });

  it('leaves the footer inset to the tab bar when there is one', async () => {
    await renderScreen({ footer: true, underTabBar: true });

    expect(screen.getByText('Pinned action')).toBeOnTheScreen();
    // Scan's "Check package" sits directly on top of the tab bar, which has
    // already cleared the indicator. Adding it again would float the button.
    expect(footerPadding().paddingBottom).toBe(spacing.lg);
  });

  it('applies the side insets either way, because nothing else pays those', async () => {
    await renderScreen({ underTabBar: true });

    const padding = scrollPadding();
    expect(padding.paddingLeft).toBe(spacing.lg + PHONE_METRICS.insets.left);
    expect(padding.paddingRight).toBe(spacing.lg + PHONE_METRICS.insets.right);
  });
});
