import { StyleSheet, Text, View } from 'react-native';

import { Button } from './Button';
import { Card } from './Card';
import { colors, spacing, typography } from '../theme';
import type { ProductClassification } from '../types/api';
import { formatConfidence, humaniseCode } from '../utils/format';

interface ClassificationCardProps {
  classification: ProductClassification;
  /**
   * Offered when the result was produced without a product type and the
   * classifier named one. Confirming sends the category to the backend for
   * a re-check of the same reading - a person's decision, recorded as such.
   * Absent, no button is shown.
   */
  onUseAsProductType?: (categoryCode: string) => void;
  busy?: boolean;
}

/**
 * What kind of product the label text looks like, according to the backend's
 * classifier.
 *
 * Presented as an observation with its own confidence, and labelled as such:
 * the number is the classifier's confidence in the *category*. It is not a
 * compliance figure, nothing in the rule engine reads it, and this card never
 * combines it with the verdict. `category: "unknown"` means the classifier
 * ran and declined to choose, which is shown in those words.
 */
export function ClassificationCard({ classification, onUseAsProductType, busy = false }: ClassificationCardProps) {
  const isUnknown = classification.category === 'unknown';
  const categoryLabel = isUnknown ? 'Could not tell' : humaniseCode(classification.category);

  return (
    <Card
      title="Product classification"
      description="A suggestion from the label text. It is not part of the compliance result."
      testID="classification-card"
    >
      <View style={styles.row}>
        <Text style={styles.label}>Product classification</Text>
        <Text style={styles.value} testID="classification-category">
          {categoryLabel}
        </Text>
      </View>
      {classification.subcategory && !isUnknown ? (
        <View style={styles.row}>
          <Text style={styles.label}>Subcategory</Text>
          <Text style={styles.value}>{humaniseCode(classification.subcategory)}</Text>
        </View>
      ) : null}
      <View style={styles.row}>
        <Text style={styles.label}>Confidence</Text>
        <Text style={styles.value} testID="classification-confidence">
          {formatConfidence(classification.confidence)}
        </Text>
      </View>
      <Text style={styles.note}>
        This confidence is the classifier’s confidence in the product type. It says nothing about
        whether the label complies with the Rules.
      </Text>
      {onUseAsProductType && !isUnknown ? (
        <Button
          variant="secondary"
          label={`Re-check as ${categoryLabel}`}
          accessibilityHint="Runs the compliance check again on the same reading, using this product type"
          onPress={() => onUseAsProductType(classification.category)}
          loading={busy}
          style={styles.button}
          testID="use-classification"
        />
      ) : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  row: {
    marginBottom: spacing.sm,
  },
  label: {
    ...typography.caption,
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  value: {
    ...typography.body,
    fontWeight: '600',
    color: colors.text,
  },
  note: {
    ...typography.caption,
    color: colors.textSecondary,
    marginTop: spacing.xs,
  },
  button: {
    marginTop: spacing.md,
  },
});
