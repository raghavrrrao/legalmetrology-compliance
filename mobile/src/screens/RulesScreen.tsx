import { StyleSheet, Text, View } from 'react-native';

import { Card } from '../components/Card';
import { Screen } from '../components/Screen';
import { LMPC_RULES, RULE_COUNTS } from '../data/lmpcRules';
import { colors, radius, spacing, typography } from '../theme';

/**
 * The requirements this build checks, and the one it does not.
 *
 * **This screen displays; it decides nothing.** No rule is evaluated here, no
 * status is derived here, and nothing on it is about any particular package. The
 * list is a mirror of `rules/definitions/*.json` generated into
 * `src/data/lmpcRules.ts` - see that file for why a copy exists and what keeps it
 * honest.
 *
 * Two things it is careful not to claim:
 *
 * 1. **Recorded is not evaluated.** Twelve definitions ship and eleven are
 *    switched on, so the inactive one is listed *with* a "Not evaluated" marker
 *    rather than hidden. A requirement the tool does not check is the more
 *    useful of the two facts to be able to find.
 * 2. **Evaluated is not evaluated in full.** Every one of these is checked more
 *    narrowly than its clause requires - `rules/INVENTORY.md` records how much
 *    more narrowly - so the footnote says the presence of a rule here is not a
 *    claim that the clause is fully assessed.
 *
 * The Active/Not-evaluated marker deliberately takes no tone colour. It is a
 * fact about this build's configuration, not a state the server reported about a
 * package, and green or red on it would read as a verdict.
 */
export function RulesScreen() {
  return (
    <Screen testID="rules-screen">
      <Text accessibilityRole="header" style={styles.title}>
        Rules &amp; information
      </Text>
      <Text style={styles.lede}>
        The rule definitions this version of the app was built with, from rules 6 and 13 of the
        Legal Metrology (Packaged Commodities) Rules, 2011. The analysis server applies its own copy.
      </Text>

      <View style={styles.counts} testID="rule-counts-summary">
        <Count value={RULE_COUNTS.recorded} label="RECORDED" />
        <View style={styles.countDivider} />
        <Count value={RULE_COUNTS.evaluated} label="EVALUATED" />
        <View style={styles.countDivider} />
        <Count value={RULE_COUNTS.inactive} label="INACTIVE" />
      </View>

      <Card title="What gets checked" testID="rules-list">
        {LMPC_RULES.map((rule, index) => (
          <View
            key={rule.code}
            style={[styles.rule, index === LMPC_RULES.length - 1 && styles.ruleLast]}
            accessible
            // One spoken element per rule, in the order a sighted reader takes
            // it: what it is, where it comes from, whether it runs. Four separate
            // elements would make a screen reader walk the code, the provision
            // and the marker as three unrelated fragments.
            accessibilityLabel={`${rule.title}. ${rule.provision}. ${
              rule.isActive ? 'Evaluated' : 'Recorded but not evaluated'
            }. Reference ${rule.code}.`}
            testID={`rule-${rule.code}`}
          >
            <View style={styles.ruleMeta}>
              <Text style={styles.code}>{rule.code}</Text>
              <Text style={styles.provision}>{rule.provision}</Text>
              <View style={styles.spacer} />
              {rule.isActive ? null : (
                <Text style={styles.inactive} testID={`rule-inactive-${rule.code}`}>
                  Not evaluated
                </Text>
              )}
            </View>
            <Text style={styles.ruleTitle}>{rule.title}</Text>
          </View>
        ))}
      </Card>

      <Text style={styles.footnote} testID="rules-footnote">
        Nothing is decided on this phone. Every verdict and finding is computed by the analysis
        server, and a rule listed here is checked more narrowly than its clause requires — the
        repository’s rule inventory records how much more narrowly for each one.
      </Text>
    </Screen>
  );
}

function Count({ value, label }: { value: number; label: string }) {
  return (
    <View style={styles.count}>
      <Text style={styles.countValue}>{value}</Text>
      <Text style={styles.countLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  title: {
    ...typography.title,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  lede: {
    ...typography.body,
    color: colors.textSecondary,
    marginBottom: spacing.lg,
  },
  counts: {
    flexDirection: 'row',
    alignItems: 'stretch',
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    paddingVertical: spacing.md,
    marginBottom: spacing.lg,
  },
  count: {
    flexGrow: 1,
    flexBasis: 0,
    alignItems: 'center',
  },
  countDivider: {
    width: 1,
    backgroundColor: colors.border,
  },
  countValue: {
    ...typography.title,
    color: colors.text,
  },
  countLabel: {
    ...typography.overline,
    color: colors.textMuted,
  },
  rule: {
    marginBottom: spacing.lg,
  },
  ruleLast: {
    marginBottom: 0,
  },
  ruleMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  code: {
    ...typography.overline,
    color: colors.textSecondary,
    backgroundColor: colors.surfaceSunken,
    borderRadius: radius.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    overflow: 'hidden',
  },
  provision: {
    ...typography.caption,
    color: colors.textMuted,
  },
  spacer: {
    flexGrow: 1,
  },
  inactive: {
    ...typography.caption,
    fontWeight: '600',
    color: colors.textSecondary,
    backgroundColor: colors.surfaceSunken,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
    overflow: 'hidden',
  },
  ruleTitle: {
    ...typography.small,
    fontWeight: '500',
    color: colors.text,
  },
  footnote: {
    ...typography.caption,
    color: colors.textMuted,
  },
});
