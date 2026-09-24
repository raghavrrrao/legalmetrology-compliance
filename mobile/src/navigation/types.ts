/**
 * The routes of the app and what each one is opened with.
 *
 *     MainTabs ─ Home · Scan · Inspections · Rules · Settings
 *        │
 *        └─ Scan ──▶ Analysis ──▶ Result        (pushed over the tabs)
 *
 * **Two navigators, and which screen belongs to which is a decision about the
 * task rather than about the shell.** The five tabs are places in the
 * application; a person switches between them whenever they like and loses
 * nothing by doing so. Analysis and Result are steps *inside one inspection* -
 * they exist only because a particular package was submitted, they are meant to
 * be finished or abandoned rather than parked, and `Analysis` deliberately
 * refuses a back gesture while a request is in flight. A tab that sometimes
 * cannot be left is not a tab, so they stay on the root stack and cover the bar.
 *
 * **No route takes a parameter.** An inspection is a set of photographs that the
 * user adds to and removes from, and it has to survive navigating to the
 * progress screen and back after a failed upload - so it lives in
 * `AnalysisProvider` alongside the reading and the result, not in route state.
 *
 * `Scan` used to be `Preview` and used to carry `{ image }`. It was renamed when
 * it stopped being a look at one photograph before sending it and became the
 * place the set is composed.
 */

import type { BottomTabScreenProps } from '@react-navigation/bottom-tabs';
import type { CompositeScreenProps, NavigatorScreenParams } from '@react-navigation/native';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';

/** The five application destinations, in bar order. */
export type MainTabParamList = {
  Home: undefined;
  Scan: undefined;
  Inspections: undefined;
  Rules: undefined;
  Settings: undefined;
};

export type RootStackParamList = {
  /**
   * `NavigatorScreenParams` is what lets a screen on the stack name a tab:
   * `navigate('MainTabs', { screen: 'Home' })` is checked against
   * `MainTabParamList`, so a typo in a tab name is a compile error rather than a
   * silent no-op at runtime.
   */
  MainTabs: NavigatorScreenParams<MainTabParamList>;
  Analysis: undefined;
  Result: undefined;
};

/** A screen on the root stack: Analysis and Result. */
export type RootScreenProps<Route extends keyof RootStackParamList> = NativeStackScreenProps<
  RootStackParamList,
  Route
>;

/**
 * A screen inside the tab bar.
 *
 * Composite because a tab screen navigates in both directions: sideways to
 * another tab (`navigate('Home')`, handled by the tab navigator) and outwards to
 * a pushed screen (`navigate('Analysis')`, which the tab navigator does not know
 * and React Navigation therefore bubbles to the stack above it). Typing these as
 * plain `BottomTabScreenProps` would reject the second, which is exactly the
 * call the scan flow depends on.
 */
export type TabScreenProps<Route extends keyof MainTabParamList> = CompositeScreenProps<
  BottomTabScreenProps<MainTabParamList, Route>,
  NativeStackScreenProps<RootStackParamList>
>;

/**
 * Where "leave this inspection and start again" goes.
 *
 * Analysis and Result are pushed over the bar, so getting back to the beginning
 * is two facts at once: pop the stack, and show the Home tab rather than
 * whichever tab happened to be selected when the inspection started. `popToTop`
 * alone did the first and, once the tabs existed, stopped doing the second -
 * someone who began from the Scan tab would have landed back on Scan. Naming the
 * destination here keeps the three callers saying the same thing.
 */
export const HOME_TAB = { screen: 'Home' } as const;
