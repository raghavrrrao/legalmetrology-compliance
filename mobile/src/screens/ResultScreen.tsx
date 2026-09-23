import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button } from '../components/Button';
import { Callout } from '../components/Callout';
import { Card } from '../components/Card';
import { ClassificationCard } from '../components/ClassificationCard';
import { ExtractedFieldsList } from '../components/ExtractedFieldsList';
import { FindingCard } from '../components/FindingCard';
import { KeyValue } from '../components/KeyValue';
import { Screen } from '../components/Screen';
import { StatusBadge } from '../components/StatusBadge';
import { VerdictPanel } from '../components/VerdictPanel';
import { useAnalysis } from '../hooks/AnalysisContext';
import type { RootScreenProps } from '../navigation/types';
import { colors, MIN_TOUCH_TARGET, spacing, typography } from '../theme';
import type { ComplianceResult } from '../types/api';
import { describeError } from '../utils/errors';
import { formatDuration, humaniseCode } from '../utils/format';
import { findingStatusLabel, groupFindingsByStatus, toneForResult } from '../utils/status';

/**
 * The verdict and everything behind it, exactly as the backend returned it.
 *
 * Things on this screen that are deliberate and must survive a redesign:
 *
 * 1. **The summary is shown next to the verdict, always.** It is what
 *    distinguishes "we checked and it passed" from "the product type was not
 *    known, so nothing could be checked".
 * 2. **REVIEW REQUIRED is a real outcome, not a soft pass**, and NOT
 *    APPLICABLE findings are not passes. Both keep their own tone and label.
 * 3. **The three kinds of evidence stay apart**: what was read (extracted
 *    fields), what the rules concluded (findings), and what a person stated
 *    (declarations). The classifier's suggestion is a fourth thing and is
 *    labelled as a suggestion.
 * 4. **No score.** Nothing here counts, averages or grades. The counts shown
 *    are the backend's own `rules_*` numbers.
 */
export function ResultScreen({ navigation }: RootScreenProps<'Result'>) {
  const analysis = useAnalysis();
  const { result, extraction, complianceError, isEvaluating, evaluate, retry, reset } = analysis;
  const [showTechnical, setShowTechnical] = useState(false);

  const scanAnother = () => {
    reset();
    navigation.popToTop();
  };

  if (!result) {
    return (
      <Screen testID="result-screen">
        <Callout title="No result to show" message="Scan a label to see its result here." tone="neutral">
          <Button label="Scan a label" onPress={scanAnother} />
        </Callout>
      </Screen>
    );
  }

  const reading = result.extraction ?? extraction;
  const classification = reading?.productClassification ?? null;
  const recheckError = complianceError ? describeError(complianceError) : null;
  const verdictLabel = result.resultDisplay || humaniseCode(result.result) || 'Unknown';
  const groups = groupFindingsByStatus(result.findings);

  return (
    <Screen
      testID="result-screen"
      footer={<Button label="Scan another label" onPress={scanAnother} testID="scan-another" />}
    >
      <Text accessibilityRole="header" style={styles.title}>
        Result
      </Text>

      <VerdictPanel tone={toneForResult(result.result)} testID="verdict-card">
        <StatusBadge label={verdictLabel} tone={toneForResult(result.result)} size="large" testID="verdict-badge" />
        {result.summary ? (
          <Text style={styles.summary} testID="verdict-summary">
            {result.summary}
          </Text>
        ) : null}
        <RuleCounts result={result} />
        <KeyValue
          label="Product type used"
          value={
            result.productCategoryCode
              ? `${humaniseCode(result.productCategoryCode)}${
                  // A model chose the rule set. Said here, beside the verdict, so
                  // nobody reads the findings as if a person had stated the type.
                  result.productCategorySource === 'classifier'
                    ? ' — established automatically from the label by the classifier, under this server’s policy'
                    : ''
                }`
              : 'Not specified — the rules for a specific product type were not applied'
          }
          testID="product-type-used"
        />
      </VerdictPanel>

      {recheckError ? (
        <Callout title={recheckError.title} message={recheckError.message} tone="error" testID="recheck-error">
          {recheckError.retryable ? (
            <Button label="Try again" onPress={() => void retry()} loading={isEvaluating} />
          ) : null}
        </Callout>
      ) : null}

      {reading?.isPlaceholder ? (
        <Callout
          title="No text reader on this server"
          message="The server read no text from this photo. Nothing below is a real reading."
          tone="warning"
        />
      ) : reading && !reading.producedUsableOutput ? (
        <Callout
          title="The label could not be read clearly"
          message="A declaration missing from this reading says nothing about the package. Try a sharper, flatter, better-lit photo."
          tone="warning"
          testID="unusable-reading"
        />
      ) : null}

      {classification ? (
        <ClassificationCard
          classification={classification}
          assessment={result.applicabilityAssessment}
          onUseAsProductType={
            result.productCategoryCode ? undefined : (code) => void evaluate({ categoryCode: code })
          }
          busy={isEvaluating}
        />
      ) : null}

      <Card
        title={`Requirements checked${result.findingsReported ? ` (${result.findings.length})` : ''}`}
        description="Every requirement that was examined and what each one concluded. Failures first, then the ones needing review."
        testID="findings-card"
      >
        {!result.findingsReported ? (
          <Text style={styles.muted} testID="findings-not-reported">
            This server does not report per-requirement outcomes.
          </Text>
        ) : result.findings.length === 0 ? (
          <Text style={styles.muted} testID="findings-empty">
            No requirements were examined. The summary above says why.
          </Text>
        ) : (
          groups.map((group) => (
            <View key={group.status} style={styles.group} testID={`findings-group-${group.status}`}>
              <Text accessibilityRole="header" style={styles.groupTitle}>
                {findingStatusLabel(group.status)} ({group.items.length})
              </Text>
              {group.items.map((finding) => (
                <FindingCard key={finding.id} finding={finding} />
              ))}
            </View>
          ))
        )}

        {!result.findingsReported && result.violations.length > 0 ? (
          <View style={styles.group}>
            <Text accessibilityRole="header" style={styles.groupTitle}>
              Violations ({result.violations.length})
            </Text>
            {result.violations.map((violation) => (
              <View key={violation.id} style={styles.violation}>
                <Text style={styles.violationTitle}>{humaniseCode(violation.ruleCode)}</Text>
                <Text style={styles.small}>{violation.message}</Text>
              </View>
            ))}
          </View>
        ) : null}
      </Card>

      {result.applicabilityDeclarations.length > 0 ? (
        <Card
          title="Facts stated about the package"
          description="Stated by a person, not read from the label. They decide whether some requirements apply."
        >
          {result.applicabilityDeclarations.map((declaration) => (
            <KeyValue
              key={declaration.code}
              label={declaration.name}
              value={`${declaration.answerDisplay || declaration.answer}${
                declaration.sourceDisplay ? ` (${declaration.sourceDisplay})` : ''
              }`}
            />
          ))}
        </Card>
      ) : null}

      <Card
        title="What was read from the label"
        description="The declarations recognised in the photo. Observations, not conclusions."
        testID="extracted-card"
      >
        <ExtractedFieldsList fields={reading?.fieldsRead ?? []} />
        {reading && reading.unreadDeclarations.length > 0 ? (
          <Text style={styles.muted}>
            {reading.unreadDeclarations.length} declaration(s) were named on the label but their values could
            not be read. A clearer photo may help.
          </Text>
        ) : null}
      </Card>

      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded: showTechnical }}
        onPress={() => setShowTechnical((value) => !value)}
        style={styles.disclosure}
        testID="toggle-technical"
      >
        <Text style={styles.disclosureText}>
          {showTechnical ? 'Hide technical details' : 'Show technical details'}
        </Text>
      </Pressable>

      {showTechnical ? (
        <Card testID="technical-card">
          <KeyValue label="Result id" value={result.id} mono />
          <KeyValue label="Evaluation status" value={humaniseCode(result.status) || 'Unknown'} />
          <KeyValue label="Rule engine version" value={result.engineVersion || 'Not reported'} />
          {result.processingMs !== null ? (
            <KeyValue label="Rule engine time" value={formatDuration(result.processingMs)} />
          ) : null}
          {reading ? (
            <>
              <KeyValue label="Reading id" value={reading.id} mono />
              <KeyValue label="Text reader" value={`${reading.engineName} ${reading.engineVersion}`.trim()} />
              <KeyValue label="Reading status" value={humaniseCode(reading.status) || 'Unknown'} />
              {reading.processingMs !== null ? (
                <KeyValue label="Reading time" value={formatDuration(reading.processingMs)} />
              ) : null}
              {reading.errorCode ? (
                <KeyValue label="Reading problem" value={humaniseCode(reading.errorCode)} />
              ) : null}
              <KeyValue
                label="Product classification"
                value={
                  classification
                    ? `${classification.category}${classification.classifierName ? ` (${classification.classifierName} ${classification.classifierVersion})`.trimEnd() : ''}`
                    : 'None was made for this reading'
                }
                testID="technical-classification"
              />
              <KeyValue label="Recognised text" value={reading.recognisedText || '(none)'} mono />
            </>
          ) : null}
        </Card>
      ) : null}
    </Screen>
  );
}

/** The backend's own counts, shown only when it reported them. */
function RuleCounts({ result }: { result: ComplianceResult }) {
  const parts: string[] = [];
  if (result.rulesEvaluated !== null) {
    parts.push(`${result.rulesEvaluated} examined`);
  }
  if (result.rulesPassed !== null) {
    parts.push(`${result.rulesPassed} passed`);
  }
  if (result.rulesFailed !== null) {
    parts.push(`${result.rulesFailed} failed`);
  }
  if (result.rulesInconclusive !== null) {
    parts.push(`${result.rulesInconclusive} need review`);
  }
  if (result.rulesNotApplicable !== null) {
    parts.push(`${result.rulesNotApplicable} not applicable`);
  }
  if (parts.length === 0) {
    return null;
  }
  return (
    <Text style={styles.counts} testID="rule-counts">
      {parts.join(' · ')}
    </Text>
  );
}

const styles = StyleSheet.create({
  title: {
    ...typography.title,
    color: colors.text,
    marginBottom: spacing.md,
  },
  summary: {
    ...typography.body,
    color: colors.text,
    marginTop: spacing.md,
  },
  counts: {
    ...typography.small,
    color: colors.textSecondary,
    marginTop: spacing.md,
    marginBottom: spacing.md,
  },
  group: {
    marginBottom: spacing.md,
  },
  groupTitle: {
    ...typography.body,
    fontWeight: '700',
    color: colors.text,
    marginBottom: spacing.sm,
  },
  muted: {
    ...typography.small,
    color: colors.textSecondary,
  },
  small: {
    ...typography.small,
    color: colors.text,
  },
  violation: {
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  violationTitle: {
    ...typography.body,
    fontWeight: '600',
    color: colors.text,
  },
  disclosure: {
    minHeight: MIN_TOUCH_TARGET,
    justifyContent: 'center',
    marginBottom: spacing.md,
  },
  disclosureText: {
    ...typography.body,
    color: colors.primary,
    fontWeight: '600',
  },
});
