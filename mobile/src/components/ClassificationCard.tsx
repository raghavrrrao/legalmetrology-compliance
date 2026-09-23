import { StyleSheet, Text, View } from 'react-native';

import { Button } from './Button';
import { Card } from './Card';
import { colors, spacing, typography } from '../theme';
import type { ApplicabilityAssessment, ProductClassification } from '../types/api';
import { formatConfidence, humaniseCode } from '../utils/format';

interface ClassificationCardProps {
  classification: ProductClassification;
  /**
   * The backend's assessment of the same classification: why it was not acted
   * on, what the label says, and what confirming would do. Absent against a
   * backend that predates it, and the card then renders exactly as it did.
   */
  assessment?: ApplicabilityAssessment | null;
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
export function ClassificationCard({
  classification,
  assessment = null,
  onUseAsProductType,
  busy = false,
}: ClassificationCardProps) {
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
        {/*
          "Model confidence", not "Confidence". The sentence below already says
          what the number is, but a reader scanning the card sees the label
          first, and a bare "Confidence" beside a compliance verdict is exactly
          the reading this screen exists to prevent.
        */}
        <Text style={styles.label}>Model confidence</Text>
        <Text style={styles.value} testID="classification-confidence">
          {formatConfidence(classification.confidence)}
        </Text>
      </View>
      <Text style={styles.note}>
        This confidence is the classifier’s confidence in the product type. It says nothing about
        whether the label complies with the Rules.
      </Text>

      {/*
        Why the suggestion was not acted on. The backend's sentence, not one
        written here: the policy is the server's and the two clients must not
        describe it differently.
      */}
      {assessment?.reason ? (
        <Text style={styles.note} testID="classification-reason">
          {assessment.reason}
        </Text>
      ) : null}

      {/*
        What the photograph actually says. Phrases the reading contains, each
        with the words around it, so the person confirming can check the label
        rather than trust the number above. Capped for a small screen.
      */}
      {assessment ? (
        <View style={styles.evidence} testID="classification-evidence">
          <Text style={styles.label}>What the label says</Text>
          {assessment.hasSupportingEvidence && assessment.labelSignals.length > 0 ? (
            <>
              {assessment.labelSignals.slice(0, MAX_SIGNALS).map((signal) => (
                <View key={signal.phrase} style={styles.signal} testID={`signal-${signal.phrase}`}>
                  <Text style={styles.signalPhrase}>{signal.phrase}</Text>
                  {signal.snippet ? (
                    <Text style={styles.signalSnippet} selectable>
                      “{signal.snippet}”
                    </Text>
                  ) : null}
                </View>
              ))}
              <Text style={styles.note}>
                These phrases are typically found on this kind of product. They do not establish
                what this product is.
              </Text>
            </>
          ) : (
            <Text style={styles.note} testID="classification-no-evidence">
              {assessment.evidenceNote ||
                'No supporting evidence from the label was reported for this suggestion.'}
            </Text>
          )}
        </View>
      ) : null}
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
      {onUseAsProductType && !isUnknown && assessment?.categoryQuestionOutcome ? (
        <Text style={styles.note} testID="classification-outcome">
          {assessment.categoryQuestionOutcome}
        </Text>
      ) : null}
    </Card>
  );
}

/** Enough for a person to recognise the label; short enough for a phone. */
const MAX_SIGNALS = 3;

const styles = StyleSheet.create({
  row: {
    marginBottom: spacing.sm,
  },
  evidence: {
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  signal: {
    marginTop: spacing.sm,
  },
  signalPhrase: {
    ...typography.small,
    fontWeight: '600',
    color: colors.text,
  },
  signalSnippet: {
    ...typography.caption,
    color: colors.textSecondary,
    fontStyle: 'italic',
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
