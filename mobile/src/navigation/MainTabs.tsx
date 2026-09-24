import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { StyleSheet, Text, View } from 'react-native';

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
    tabBarIcon: ({ focused }: { focused: boolean }) => (
      <TabItem icon={icon} label={label} focused={focused} />
    ),
  };
}

/**
 * One tab item: the icon on its pill, and the label under it.
 *
 * Both are drawn here rather than through `tabBarIcon` plus `tabBarLabel`,
 * because the selected state is a pill *behind the icon only* and the label sits
 * outside it. Splitting that across the two options would mean the pill's width
 * was decided in one place and the thing it has to centre on in another.
 *
 * `flex: 1` with `flexBasis: 0` on every item is what divides the bar evenly at
 * any width instead of sizing each item to its own label - which is what would
 * make "Settings" wider than "Scan" and the icons stop lining up.
 */
function TabItem({ icon, label, focused }: { icon: TabIconName; label: string; focused: boolean }) {
  const ink = focused ? colors.action : colors.textMuted;
  return (
    <View style={styles.item}>
      <View style={[styles.pill, focused && styles.pillOn]}>
        <TabBarIcon name={icon} color={ink} />
      </View>
      <Text
        numberOfLines={1}
        // The label must never shrink to fit: at 11 pt it is already at the
        // floor, and a bar whose labels are different sizes reads as broken.
        // The arithmetic in `theme.shell` is what guarantees it does not have to.
        allowFontScaling={false}
        style={[styles.label, { color: ink }, focused && styles.labelOn]}
      >
        {label}
      </Text>
    </View>
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
        tabBarStyle: styles.bar,
        tabBarItemStyle: styles.barItem,
        // The pill and the label are drawn by `TabItem`; the defaults would
        // otherwise render a second label under it.
        tabBarShowLabel: false,
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
   * for the same reason. `height` is the content box; the navigator adds the
   * bottom safe-area inset to it itself, and `components/Screen.tsx` is written
   * to make sure nothing else adds it a second time.
   */
  bar: {
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    height: shell.tabBarHeight,
    elevation: 0,
    shadowOpacity: 0,
    paddingTop: 5,
  },
  barItem: {
    flexBasis: 0,
    flexGrow: 1,
    minWidth: 0,
  },
  item: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: 3,
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
  },
  labelOn: {
    fontWeight: '600',
  },
});
