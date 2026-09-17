import { StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '../theme';

/**
 * How to take a photograph the OCR can read. Plain advice to the person
 * holding the phone; no image processing happens on the device.
 */
export const PHOTO_TIPS = [
  'Lay the label flat and fill the frame with it.',
  'Make sure the text is sharp and readable.',
  'Avoid glare and shadows across the label.',
  'Include the whole declaration panel, not just part of it.',
  'Hold the phone steady while the photo is taken.',
];

export function PhotoTips() {
  return (
    <View accessibilityRole="list" style={styles.list}>
      {PHOTO_TIPS.map((tip) => (
        <View key={tip} style={styles.item} accessible accessibilityLabel={tip}>
          <Text style={styles.bullet}>•</Text>
          <Text style={styles.text}>{tip}</Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  list: {
    marginTop: spacing.xs,
  },
  item: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: spacing.sm,
  },
  bullet: {
    ...typography.small,
    color: colors.textSecondary,
    width: 16,
  },
  text: {
    ...typography.small,
    color: colors.textSecondary,
    flex: 1,
  },
});
