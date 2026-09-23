import { createNativeStackNavigator } from '@react-navigation/native-stack';

import type { RootStackParamList } from './types';
import { AnalysisScreen } from '../screens/AnalysisScreen';
import { HomeScreen } from '../screens/HomeScreen';
import { ResultScreen } from '../screens/ResultScreen';
import { ScanScreen } from '../screens/ScanScreen';
import { colors } from '../theme';

const Stack = createNativeStackNavigator<RootStackParamList>();

/**
 * One linear stack: Home -> Scan -> Analysis -> Result.
 *
 * A native stack rather than a JS one so back gestures, the Android back
 * button and the header follow each platform's own conventions. The analysis
 * and result screens hide the back button and offer explicit actions instead,
 * so "back" from a finished result cannot land on a stale spinner.
 */
export function RootNavigator() {
  return (
    <Stack.Navigator
      initialRouteName="Home"
      screenOptions={{
        headerStyle: { backgroundColor: colors.surface },
        // The back chevron and any header action take the accent; the title
        // stays text-coloured, so the accent means "you can press this".
        headerTintColor: colors.primary,
        headerTitleStyle: { fontWeight: '600', color: colors.text },
        headerShadowVisible: false,
        contentStyle: { backgroundColor: colors.background },
      }}
    >
      <Stack.Screen name="Home" component={HomeScreen} options={{ title: 'NIRIKSHAN' }} />
      <Stack.Screen name="Scan" component={ScanScreen} options={{ title: 'Scan a package' }} />
      <Stack.Screen
        name="Analysis"
        component={AnalysisScreen}
        options={{ title: 'Analysing', headerBackVisible: false, gestureEnabled: false }}
      />
      <Stack.Screen
        name="Result"
        component={ResultScreen}
        options={{ title: 'Result', headerBackVisible: false, gestureEnabled: false }}
      />
    </Stack.Navigator>
  );
}
