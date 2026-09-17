import { StyleSheet, Text, View } from 'react-native';

import { StatusBadge } from './StatusBadge';
import { colors, radius, spacing, typography } from '../theme';
import type { Finding } from '../types/api';
import { formatConfidence, humaniseCode } from '../utils/format';
import { findingStatusLabel, toneForFindingStatus } from '../utils/status';

/**
 * One rule's outcome, as the backend recorded it.
 *
 * Shows what was required, what was read, and what was concluded - every
 * word from the response. The status is the backend's four-valued one,
 * passed through: "Needs review" (inconclusive) is not a soft fail and "Not
 * applicable" is not a pass, and this card never rounds either to another.
 */
export function FindingCard({ finding }: { finding: Finding }) {
  const tone = toneForFindingStatus(finding.status);
  const heading = finding.title || humaniseCode(finding.ruleCode);
  const reference = [finding.clause ? `Rule ${finding.clause}` : '', finding.legalReference]
    .filter(Boolean)
    .join(' · ');

  return (
    <View style={styles.card} testID={`finding-${finding.id}`}>
      <View style={styles.header}>
        <Text style={styles.title} accessibilityRole="header">
          {heading}
        </Text>
        <StatusBadge label={findingStatusLabel(finding.status)} tone={tone} />
      </View>

      {reference ? <Text style={styles.reference}>{reference}</Text> : null}

      {finding.message ? <Text style={styles.message}>{finding.message}</Text> : null}

      {finding.requirement ? (
        <View style={styles.block}>
          <Text style={styles.blockLabel}>Requirement</Text>
          <Text style={styles.blockText}>{finding.requirement}</Text>
        </View>
      ) : null}

      {finding.evidenceExcerpt ? (
        <View style={styles.block}>
          <Text style={styles.blockLabel}>What was read</Text>
          <Text style={[styles.blockText, styles.evidence]} selectable>
            “{finding.evidenceExcerpt}”
          </Text>
          {finding.extractedConfidence !== null ? (
            <Text style={styles.meta}>
              Reading confidence {formatConfidence(finding.extractedConfidence)} — the OCR engine’s confidence
              in its own characters, not a measure of compliance.
            </Text>
          ) : null}
        </View>
      ) : null}

      {finding.downgradedFromFailed ? (
        <Text style={styles.meta}>
          Recorded as needing review rather than as a violation because the rule is not yet verified
          against the authoritative legal text.
        </Text>
      ) : null}

      {finding.applicabilityNote ? <Text style={styles.meta}>{finding.applicabilityNote}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
    backgroundColor: colors.surface,
  },
  header: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  title: {
    ...typography.body,
    fontWeight: '600',
    color: colors.text,
    flexShrink: 1,
    flexGrow: 1,
    minWidth: 120,
  },
  reference: {
    ...typography.caption,
    color: colors.textMuted,
    marginBottom: spacing.sm,
  },
  message: {
    ...typography.small,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  block: {
    marginTop: spacing.xs,
    marginBottom: spacing.sm,
  },
  blockLabel: {
    ...typography.caption,
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    marginBottom: 2,
  },
  blockText: {
    ...typography.small,
    color: colors.text,
  },
  evidence: {
    fontStyle: 'italic',
  },
  meta: {
    ...typography.caption,
    color: colors.textSecondary,
    marginTop: spacing.xs,
  },
});
