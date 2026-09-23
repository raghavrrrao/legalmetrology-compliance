import { StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '../theme';
import type { ExtractedField } from '../types/api';
import { formatConfidence, formatNormalizedValue, humaniseCode } from '../utils/format';
import { imageLabel, type ImagePositions } from '../utils/images';

interface ExtractedFieldsListProps {
  fields: ExtractedField[];
  /**
   * Position by stored image id, from `utils/images.imagePositions`. Supplied
   * when the inspection has more than one photograph; each declaration is then
   * labelled with the panel it was read from.
   */
  positions?: ImagePositions;
}

/**
 * The declarations read off the package: each one's raw text, the
 * interpretation the backend made of it (when it made one), and the OCR
 * confidence (when the engine reported one). Observations, not conclusions.
 *
 * A declaration may appear **twice** when it is printed on two photographed
 * panels. Both are shown, each against its own photograph, because both are
 * real readings and hiding one would be this app deciding which panel of a
 * package to believe.
 */
export function ExtractedFieldsList({ fields, positions }: ExtractedFieldsListProps) {
  if (fields.length === 0) {
    return (
      <Text style={styles.empty} testID="extracted-fields-empty">
        No declarations were recognised in these photos.
      </Text>
    );
  }
  return (
    <View accessibilityRole="list">
      {fields.map((field, index) => {
        const interpreted = formatNormalizedValue(field.normalizedValue);
        const source = positions ? imageLabel(field.imageId, positions) : null;
        return (
          <View
            key={`${field.fieldKey}-${index}`}
            style={[styles.item, index === fields.length - 1 && styles.itemLast]}
            testID={`extracted-${field.fieldKey}`}
          >
            <Text style={styles.key}>
              {source ? `${humaniseCode(field.fieldKey)} · ${source}` : humaniseCode(field.fieldKey)}
            </Text>
            <Text style={styles.raw} selectable>
              {field.rawValue}
            </Text>
            {interpreted ? <Text style={styles.meta}>Read as: {interpreted}</Text> : null}
            <Text style={styles.meta}>Reading confidence: {formatConfidence(field.confidence)}</Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  item: {
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  itemLast: {
    borderBottomWidth: 0,
  },
  key: {
    ...typography.caption,
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  raw: {
    ...typography.body,
    color: colors.text,
  },
  meta: {
    ...typography.caption,
    color: colors.textSecondary,
    marginTop: 2,
  },
  empty: {
    ...typography.small,
    color: colors.textSecondary,
  },
});
