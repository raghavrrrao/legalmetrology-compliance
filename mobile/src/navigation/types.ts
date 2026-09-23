/**
 * The routes of the app and what each one is opened with.
 *
 *     Home -> Scan -> Analysis -> Result
 *
 * **No route takes a parameter.** An inspection is a set of photographs that
 * the user adds to and removes from, and it has to survive navigating to the
 * progress screen and back after a failed upload - so it lives in
 * `AnalysisProvider` alongside the reading and the result, not in route state.
 *
 * `Scan` used to be `Preview` and used to carry `{ image }`. It was renamed
 * when it stopped being a look at one photograph before sending it and became
 * the place the set is composed.
 */

import type { NativeStackScreenProps } from '@react-navigation/native-stack';

export type RootStackParamList = {
  Home: undefined;
  Scan: undefined;
  Analysis: undefined;
  Result: undefined;
};

export type RootScreenProps<Route extends keyof RootStackParamList> = NativeStackScreenProps<
  RootStackParamList,
  Route
>;
