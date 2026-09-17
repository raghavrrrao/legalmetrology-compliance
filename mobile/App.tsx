/**
 * Root of the mobile client.
 *
 * Three providers, each with one job: safe-area insets so nothing hides under
 * a notch or the home indicator, navigation, and the analysis state the
 * screens share. Everything else lives under src/.
 */

import { NavigationContainer } from '@react-navigation/native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AnalysisProvider } from './src/hooks/AnalysisContext';
import { RootNavigator } from './src/navigation/RootNavigator';

export default function App() {
  return (
    <SafeAreaProvider>
      <AnalysisProvider>
        <NavigationContainer>
          <RootNavigator />
        </NavigationContainer>
      </AnalysisProvider>
      <StatusBar style="dark" />
    </SafeAreaProvider>
  );
}
