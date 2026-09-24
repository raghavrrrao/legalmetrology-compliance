import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { MainTabParamList } from './types';
import { AppHeader } from '../components/AppHeader';
import { TabBarIcon, type TabIconName } from '../components/TabBarIcon';
import { HomeScreen } from '../screens/HomeScreen';
import { InspectionsScreen } from '../screens/InspectionsScreen';
import { RulesScreen } from '../screens/RulesScreen';
import { ScanScreen } from '../screens/ScanScreen';
import { SettingsScreen } from '../screens/SettingsScreen';
import { colors, shell, tabLabelType } from '../theme';

const Tab = createBottomTabNavigator<MainTabParamList>();

/**
 * The options every tab shares, given its icon and label.
 *
 * A helper rather than a loop over a table: mapping `name -> component` through
 * a record means widening each screen's props to satisfy the record's value
 * type, which is a cast in all but name. Five explicit `Tab.Screen` elements
 * cost four extra lines and let every screen keep its real prop type, so a
 * screen typed for the wrong navigator is a compile error.
 */
function tabOptions(icon: TabIconName, label: string, spoken: string) {
  return {
    title: label,
    tabBarAccessibilityLabel: spoken,
    tabBarButtonTestID: `tab-${label.toLowerCase()}`,
    tabBarIcon: ({ focused }: { focused: boolean }) => <TabPill icon={icon} focused={focused} />,
    tabBarLabel: ({ focused }: { focused: boolean }) => <TabLabel label={label} focused={focused} />,
  };
}

/**
 * The icon on its pill - the whole of the selected-state indicator.
 *
 * It goes in the navigator's icon slot, and `tabBarIconStyle` below sizes that
 * slot to the pill. Left at the library default the slot is 31 x 28 - sized for a
 * bare glyph - and anything wider is laid out inside those 31 points.
 */
function TabPill({ icon, focused }: { icon: TabIconName; focused: boolean }) {
  return (
    <View style={[styles.pill, focused && styles.pillOn]}>
      <TabBarIcon name={icon} color={focused ? colors.action : colors.textMuted} />
    </View>
  );
}

/**
 * The label, in the navigator's *label* slot rather than under the pill.
 *
 * It used to be drawn inside the icon slot together with the pill, so one
 * component decided both. On a device that put the label inside the icon slot's
 * 31 pt width, and "History" and "Settings" rendered as "Hist…" and "Sett…" at
 * 390 pt - the item was 76 pt wide and the label was offered 31 of it. The label
 * slot is the full width of the item, which is what the arithmetic in
 * `theme.shell` assumed all along.
 */
function TabLabel({ label, focused }: { label: string; focused: boolean }) {
  return (
    <Text
      numberOfLines={1}
      // The label must never shrink to fit: at 11 pt it is already at the floor,
      // and a bar whose labels are different sizes reads as broken.
      allowFontScaling={false}
      style={[
        styles.label,
        { color: focused ? colors.action : colors.textMuted },
        focused && styles.labelOn,
      ]}
    >
      {label}
    </Text>
  );
}

/**
 * The five application destinations.
 *
 * **The header lives here, not on the stack above.** Every tab shows the same
 * branded header, so it is rendered once by this navigator; the root stack sets
 * `headerShown: false` for this whole subtree. Analysis and Result keep the
 * native stack's header, which is what gives them a real platform back gesture.
 *
 * All five tabs are peers, and none of them is a raised centre button. Home
 * already leads with a full-width "Take photo", so promoting Scan inside the bar
 * would be the same action twice with the bar's one job - saying where you are -
 * made harder to read.
 */
export function MainTabs() {
  const insets = useSafeAreaInsets();
  return (
    <Tab.Navigator
      initialRouteName="Home"
      screenOptions={{
        header: () => <AppHeader testID="app-header" />,
        /*
         * No transition between destinations.
         *
         * Switching tab is the one navigation where the user already knows what
         * they asked for, and a cross-fade between two screens of dense text is
         * the kind of motion this design brief rules out - it delays reading and
         * clarifies nothing. Turning it off also stops `BottomTabView` driving an
         * animation clock, which was the source of an act() warning in every test
         * that touched the bar.
         */
        animation: 'none',
        /*
         * `height` must include the bottom inset. The library returns a numeric
         * `height` from this style verbatim - it adds `insets.bottom` only to its
         * own default (`getTabBarHeight` in bottom-tabs) - while still applying
         * `paddingBottom: insets.bottom` itself. A bare 56 therefore made the whole
         * bar 56 with the inset padded *inside* it, leaving about 27 pt for icon and
         * label and drawing the Android gesture handle across the labels. Found on
         * an emulator; Jest has no layout, so no unit test saw it.
         */
        tabBarStyle: [styles.bar, { height: shell.tabBarHeight + insets.bottom }],
        tabBarItemStyle: styles.barItem,
        tabBarIconStyle: styles.iconSlot,
        tabBarShowLabel: true,
        /*
         * Pinned, because the default is not "below" everywhere: at 768 pt and up
         * the library puts labels *beside* icons, which is a different bar from
         * the one specified and would break the equal-width items on a tablet.
         */
        tabBarLabelPosition: 'below-icon',
        tabBarActiveTintColor: colors.action,
        tabBarInactiveTintColor: colors.textMuted,
      }}
    >
      <Tab.Screen name="Home" component={HomeScreen} options={tabOptions('home', 'Home', 'Home')} />
      <Tab.Screen
        name="Scan"
        component={ScanScreen}
        options={tabOptions('scan', 'Scan', 'Scan a package')}
      />
      {/*
        The route is `Inspections` and the label is "History". The route name is
        what the rest of the app navigates by and it names the thing; the label is
        the shorter of the two words and the one that fits 64 pt at 360 pt wide.
        "Rules" is shortened the same way - "Rules & information" does not fit,
        and truncating a tab label is not an option, so the full name is what a
        screen reader says instead.
      */}
      <Tab.Screen
        name="Inspections"
        component={InspectionsScreen}
        options={tabOptions('history', 'History', 'Previous inspections')}
      />
      <Tab.Screen
        name="Rules"
        component={RulesScreen}
        options={tabOptions('rules', 'Rules', 'Rules and information')}
      />
      <Tab.Screen
        name="Settings"
        component={SettingsScreen}
        options={tabOptions('settings', 'Settings', 'Settings')}
      />
    </Tab.Navigator>
  );
}

const styles = StyleSheet.create({
  /*
   * Opaque, a hairline on top, no shadow - the same treatment as the header, and
   * for the same reason. Its height is set inline above, because it depends on
   * the inset; `components/Screen.tsx` is written to make sure nothing else adds
   * the inset a second time.
   */
  bar: {
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    elevation: 0,
    shadowOpacity: 0,
    paddingTop: 5,
  },
  barItem: {
    flexBasis: 0,
    flexGrow: 1,
    minWidth: 0,
  },
  /* The icon slot, sized to the pill so the pill is laid out rather than overflowing. */
  iconSlot: {
    width: shell.tabPill.width,
    height: shell.tabPill.height,
  },
  pill: {
    width: shell.tabPill.width,
    height: shell.tabPill.height,
    borderRadius: 999,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pillOn: {
    backgroundColor: colors.actionSoft,
  },
  label: {
    ...tabLabelType,
    fontWeight: '500',
    marginTop: 3,
  },
  labelOn: {
    fontWeight: '600',
  },
});
