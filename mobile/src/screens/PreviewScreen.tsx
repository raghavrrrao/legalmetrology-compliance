import { useState } from 'react';
import { Image, StyleSheet, Text, TextInput, View } from 'react-native';

import { Button } from '../components/Button';
import { Card } from '../components/Card';
import { Screen } from '../components/Screen';
import { useAnalysis } from '../hooks/AnalysisContext';
import type { RootScreenProps } from '../navigation/types';
import { colors, radius, spacing, typography } from '../theme';
import { formatBytes } from '../utils/format';

/** Tallest the preview grows; wider phones get the full width regardless. */
const MAX_PREVIEW_HEIGHT = 420;

/**
 * Look at the photograph before it is sent.
 *
 * The product type is a text field rather than a list, for the reason the web
 * client's is (`frontend/src/components/ConfigurationPanel.jsx`): no endpoint
 * lists product categories, and a list typed into the app would be a copy of
 * backend rows that goes stale silently. The backend validates the code and
 * rejects an unknown one with a message this app shows. Leaving it blank is
 * supported and honest - the result then says the product type was not known.
 */
export function PreviewScreen({ navigation, route }: RootScreenProps<'Preview'>) {
  const { image } = route.params;
  const analysis = useAnalysis();
  const [categoryCode, setCategoryCode] = useState('');

  const aspectRatio = image.width && image.height ? image.width / image.height : 4 / 3;

  const usePhoto = () => {
    // Not awaited: the progress screen watches the analysis as it runs.
    void analysis.analyse(image, { categoryCode: categoryCode.trim() });
    navigation.navigate('Analysis');
  };

  return (
    <Screen
      testID="preview-screen"
      footer={
        <>
          <Button label="Use this photo" onPress={usePhoto} testID="use-photo" />
          <Button
            variant="secondary"
            label="Retake"
            accessibilityHint="Goes back so you can take or choose a different photo"
            onPress={() => navigation.goBack()}
            testID="retake"
          />
        </>
      }
    >
      <Text accessibilityRole="header" style={styles.title}>
        Check the photo
      </Text>
      <Text style={styles.lede}>Make sure the whole label is in frame and the text is readable.</Text>

      <View style={styles.frame}>
        <Image
          source={{ uri: image.uri }}
          accessible
          accessibilityLabel="The photo you selected, showing the product label"
          style={[styles.image, { aspectRatio }]}
          resizeMode="contain"
          testID="preview-image"
        />
      </View>
      {image.sizeBytes !== null ? <Text style={styles.meta}>{formatBytes(image.sizeBytes)}</Text> : null}

      <Card
        title="Product type (optional)"
        description="If you know the product category code, enter it so the right rules are applied. Leave it blank if you are not sure."
      >
        <TextInput
          value={categoryCode}
          onChangeText={setCategoryCode}
          placeholder="e.g. packaged-food"
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none"
          autoCorrect={false}
          accessibilityLabel="Product category code, optional"
          style={styles.input}
          testID="category-code"
        />
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: {
    ...typography.title,
    color: colors.text,
    marginBottom: spacing.xs,
  },
  lede: {
    ...typography.small,
    color: colors.textSecondary,
    marginBottom: spacing.lg,
  },
  frame: {
    width: '100%',
    backgroundColor: colors.photoWell,
    borderRadius: radius.lg,
    overflow: 'hidden',
    alignItems: 'center',
  },
  image: {
    width: '100%',
    maxHeight: MAX_PREVIEW_HEIGHT,
  },
  meta: {
    ...typography.caption,
    color: colors.textMuted,
    marginTop: spacing.xs,
    marginBottom: spacing.lg,
  },
  input: {
    ...typography.body,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    minHeight: 48,
    backgroundColor: colors.surface,
  },
});
