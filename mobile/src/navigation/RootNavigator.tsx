import { createNativeStackNavigator } from '@react-navigation/native-stack';

import { MainTabs } from './MainTabs';
import type { RootStackParamList } from './types';
import { AnalysisScreen } from '../screens/AnalysisScreen';
import { ResultScreen } from '../screens/ResultScreen';
import { colors } from '../theme';

const Stack = createNativeStackNavigator<RootStackParamList>();

/**
 * The tabs, with one inspection pushed over them.
 *
 *     MainTabs ──▶ Analysis ──▶ Result
 *
 * A native stack rather than a JS one so back gestures, the Android back button
 * and the header follow each platform's own conventions.
 *
 * **`MainTabs` hides this navigator's header** because the tab navigator renders
 * its own branded one - see `MainTabs.tsx`. Analysis and Result keep this
 * header, which is what gives them a platform back chevron and title; they also
 * hide the back button and offer explicit actions instead, so "back" from a
 * finished result cannot land on a stale spinner.
 *
 * Why Analysis and Result are here and not tabs: `types.ts` has the reasoning,
 * and the short of it is that `Analysis` refuses to be left while a request is
 * in flight, which is not something a tab may do.
 */
export function RootNavigator() {
  return (
    <Stack.Navigator
      initialRouteName="MainTabs"
      screenOptions={{
        headerStyle: { backgroundColor: colors.surface },
        // The back chevron and any header action take the accent; the title
        // stays text-coloured, so the accent means "you can press this".
        headerTintColor: colors.action,
        headerTitleStyle: { fontWeight: '600', color: colors.text },
        headerShadowVisible: false,
        contentStyle: { backgroundColor: colors.background },
      }}
    >
      <Stack.Screen name="MainTabs" component={MainTabs} options={{ headerShown: false }} />
      {/*
        "Analysis", not "Analysing". The header names the screen; the screen's
        own heading says what is happening ("Analysing label…", then "Analysis
        stopped"), and that heading is the live region a screen reader announces.
        A progressive-tense header stayed on after an analysis had stopped,
        saying the opposite of the heading under it. A noun cannot go stale, so
        this does not need to track state - and a state-driven title would only
        have repeated the heading word for word.
      */}
      <Stack.Screen
        name="Analysis"
        component={AnalysisScreen}
        options={{ title: 'Analysis', headerBackVisible: false, gestureEnabled: false }}
      />
      <Stack.Screen
        name="Result"
        component={ResultScreen}
        options={{ title: 'Result', headerBackVisible: false, gestureEnabled: false }}
      />
    </Stack.Navigator>
  );
}
