/**
 * The routes of the app and what each one is opened with.
 *
 *     Home -> Preview -> Analysis -> Result
 *
 * Only the preview takes a parameter, and only the small, serialisable
 * description of the picked photograph. Readings and results are never route
 * params: they live in `AnalysisProvider`, so the progress and result screens
 * read the same analysis rather than a copy.
 */

import type { NativeStackScreenProps } from '@react-navigation/native-stack';

import type { SelectedImage } from '../services/imageValidation';

export type RootStackParamList = {
  Home: undefined;
  Preview: { image: SelectedImage };
  Analysis: undefined;
  Result: undefined;
};

export type RootScreenProps<Route extends keyof RootStackParamList> = NativeStackScreenProps<
  RootStackParamList,
  Route
>;
