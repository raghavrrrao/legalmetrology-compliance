/**
 * The preview: look at the photo, optionally name the product type, go.
 */

import { fireEvent, render, screen } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { PreviewScreen } from './PreviewScreen';
import { selectedImage } from '../../tests/fixtures';
import { fakeAnalysis, PHONE_METRICS, stubNavigation } from '../../tests/render';

const mockUseAnalysis = jest.fn();
jest.mock('../hooks/AnalysisContext', () => ({
  useAnalysis: () => mockUseAnalysis(),
}));

async function renderPreview() {
  const analysis = fakeAnalysis();
  mockUseAnalysis.mockReturnValue(analysis);
  const navigation = stubNavigation();
  const image = selectedImage();
  await render(
    <SafeAreaProvider initialMetrics={PHONE_METRICS}>
      <PreviewScreen
        navigation={navigation as never}
        route={{ key: 'Preview', name: 'Preview', params: { image } } as never}
      />
    </SafeAreaProvider>,
  );
  return { analysis, navigation, image };
}

describe('PreviewScreen', () => {
  it('shows the selected photo', async () => {
    const { image } = await renderPreview();

    const preview = screen.getByTestId('preview-image');
    expect(preview.props.source).toEqual({ uri: image.uri });
    expect(screen.getByText('229 KB')).toBeOnTheScreen();
  });

  it('starts the analysis with the photo and goes to the progress screen', async () => {
    const { analysis, navigation, image } = await renderPreview();

    await fireEvent.press(screen.getByTestId('use-photo'));

    expect(analysis.analyse).toHaveBeenCalledWith(image, { categoryCode: '' });
    expect(navigation.navigate).toHaveBeenCalledWith('Analysis');
  });

  it('passes a product type the user typed, trimmed', async () => {
    const { analysis, image } = await renderPreview();

    await fireEvent.changeText(screen.getByTestId('category-code'), '  packaged-food ');
    await fireEvent.press(screen.getByTestId('use-photo'));

    expect(analysis.analyse).toHaveBeenCalledWith(image, { categoryCode: 'packaged-food' });
  });

  it('goes back on retake without starting anything', async () => {
    const { analysis, navigation } = await renderPreview();

    await fireEvent.press(screen.getByTestId('retake'));

    expect(navigation.goBack).toHaveBeenCalled();
    expect(analysis.analyse).not.toHaveBeenCalled();
  });
});
