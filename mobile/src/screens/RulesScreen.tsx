import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { ApiError } from '../api/client';
import { Button } from '../components/Button';
import { Callout } from '../components/Callout';
import { Card } from '../components/Card';
import { Screen } from '../components/Screen';
import { config, describeApiTarget } from '../config/env';
import { useRuleInventory } from '../hooks/useRuleInventory';
import { colors, radius, spacing, typography } from '../theme';
import type { RuleInventory, RuleInventoryEntry } from '../types/api';
import { describeError, type UserFacingError } from '../utils/errors';

/**
 * The rules the analysis server reports it has loaded, and the ones it does not
 * evaluate.
 *
 * **This screen displays; it decides nothing.** The list is
 * `GET /api/v1/rules/`, read through `useRuleInventory`, in the server's order.
 * No rule is evaluated here, no applicability is worked out here, and nothing
 * on it is about any particular package. Every field shown is one the server
 * sent, verbatim; the only figures computed are the active and inactive tallies
 * of the server's own `is_active` flags (see `src/api/rules.ts`).
 *
 * **The server's list or none.** While the request is in flight the screen says
 * so; when it fails the screen says the list could not be loaded and offers a
 * retry. It never shows another list in the meantime - the bundled
 * `src/data/lmpcRules.ts` is a repository mirror, not what this server has
 * loaded, and nothing here imports it.
 *
 * Two things it is careful not to claim:
 *
 * 1. **Loaded is not evaluated.** An inactive rule is listed *with* a
 *    "Not evaluated" marker rather than hidden. A requirement the server does
 *    not check is the more useful of the two facts to be able to find.
 * 2. **Evaluated is not evaluated in full.** The footnote says the presence of
 *    a rule here is not a claim that its clause is fully assessed.
 *
 * The markers deliberately take no tone colour. They are facts about the
 * server's configuration, not a state the server reported about a package, and
 * green or red on them would read as a verdict.
 */
export function RulesScreen() {
  const { reload, ...inventory } = useRuleInventory();
  const { host } = describeApiTarget(config.apiBaseUrl);

  return (
    <Screen testID="rules-screen">
      <Text accessibilityRole="header" style={styles.title}>
        Rules &amp; information
      </Text>
      <Text style={styles.lede}>
        The compliance rules loaded on the analysis server, as the server reports them.
      </Text>

      {inventory.phase === 'loading' ? (
        <View
          style={styles.loading}
          accessible
          accessibilityLabel={`Loading the rule list from ${host}`}
          accessibilityLiveRegion="polite"
          testID="rules-loading"
        >
          <ActivityIndicator size="small" color={colors.action} />
          <Text style={styles.loadingText}>Loading the rule list from {host}…</Text>
        </View>
      ) : null}

      {inventory.phase === 'error' ? (
        <RuleListError error={inventory.error} onRetry={reload} />
      ) : null}

      {inventory.phase === 'loaded' ? <RuleList inventory={inventory.inventory} host={host} /> : null}

      <Text style={styles.footnote} testID="rules-footnote">
        Nothing is decided on this phone. Every verdict and finding is computed by the analysis
        server, and a rule listed here is checked more narrowly than its clause requires — the
        repository’s rule inventory records how much more narrowly for each one.
      </Text>
    </Screen>
  );
}

function RuleList({ inventory, host }: { inventory: RuleInventory; host: string }) {
  return (
    <>
      <Text style={styles.source} testID="rules-source">
        Reported by the compliance server at {host}.
      </Text>

      <View style={styles.counts} testID="rule-counts-summary">
        <Count value={inventory.total} label="TOTAL" />
        <View style={styles.countDivider} />
        <Count value={inventory.active} label="ACTIVE" />
        <View style={styles.countDivider} />
        <Count value={inventory.inactive} label="INACTIVE" />
      </View>

      {inventory.rules.length === 0 ? (
        <Callout
          title="No rules reported"
          message="The server reports that it has no compliance rules loaded."
          testID="rules-empty"
        />
      ) : (
        <Card title="Rules on the server" testID="rules-list">
          {inventory.rules.map((rule, index) => (
            <RuleRow key={rule.code} rule={rule} last={index === inventory.rules.length - 1} />
          ))}
        </Card>
      )}
    </>
  );
}

function RuleRow({ rule, last }: { rule: RuleInventoryEntry; last: boolean }) {
  // "Rule 6(1)(c)" from the linked clause - the label `FindingCard` uses for the
  // same field. Nothing is shown when the server links no clause; one is never
  // read out of the reference text.
  const clauseLabel = rule.clause ? `Rule ${rule.clause}` : null;
  const unverified = rule.sourceStatus === 'unverified';

  return (
    <View
      style={[styles.rule, last && styles.ruleLast]}
      accessible
      // One spoken element per rule, in the order a sighted reader takes it:
      // what it is, where it comes from, whether it runs. Separate elements
      // would make a screen reader walk the code, the clause and the markers as
      // unrelated fragments.
      accessibilityLabel={[
        rule.title,
        rule.legalReference || clauseLabel,
        rule.isActive ? 'Active' : 'Inactive, not evaluated',
        unverified ? 'Not yet verified' : null,
        `Reference ${rule.code}`,
      ]
        .filter(Boolean)
        .join('. ')}
      testID={`rule-${rule.code}`}
    >
      <View style={styles.ruleMeta}>
        <Text style={styles.code}>{rule.code}</Text>
        {clauseLabel ? <Text style={styles.provision}>{clauseLabel}</Text> : null}
        <View style={styles.spacer} />
        {unverified ? (
          <Text style={styles.marker} testID={`rule-unverified-${rule.code}`}>
            Not yet verified
          </Text>
        ) : null}
        {rule.isActive ? null : (
          <Text style={styles.marker} testID={`rule-inactive-${rule.code}`}>
            Not evaluated
          </Text>
        )}
      </View>
      <Text style={styles.ruleTitle}>{rule.title}</Text>
      {rule.legalReference ? (
        <Text style={styles.reference} testID={`rule-reference-${rule.code}`}>
          {rule.legalReference}
        </Text>
      ) : null}
    </View>
  );
}

/**
 * Why the list is not there, in the words every other screen uses - except
 * where the shared wording is about analysing a photograph, which would be
 * wrong here: a timeout (seen on a device, where the shared message blamed "a
 * very large photo"), 401/403 and 404.
 */
function describeRuleListError(error: unknown): UserFacingError {
  if (error instanceof ApiError && error.code === 'timeout') {
    return {
      title: 'The server took too long',
      message: 'It did not arrive in time, which can happen on a slow connection. Please try again.',
      retryable: true,
    };
  }
  if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
    return {
      title: 'Rule list not available',
      message:
        'This server shows its rule list only to signed-in users, and the mobile app does not '
        + 'support sign-in yet.',
      retryable: false,
    };
  }
  if (error instanceof ApiError && error.status === 404) {
    return {
      title: 'Rule list not available',
      message:
        'This server does not provide a rule list. It may be running a version from before the '
        + 'list was added.',
      retryable: false,
    };
  }
  return describeError(error);
}

function RuleListError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const described = describeRuleListError(error);
  return (
    <Callout
      title={described.title}
      message={`The server’s current rule list could not be loaded. ${described.message}`}
      tone="error"
      testID="rules-error"
    >
      {described.retryable ? <Button label="Try again" onPress={onRetry} testID="rules-retry" /> : null}
    </Callout>
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
  loading: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  loadingText: {
    ...typography.small,
    color: colors.textSecondary,
    flexShrink: 1,
  },
  source: {
    ...typography.caption,
    color: colors.textMuted,
    marginBottom: spacing.sm,
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
  marker: {
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
  reference: {
    ...typography.caption,
    color: colors.textMuted,
    marginTop: 2,
  },
  footnote: {
    ...typography.caption,
    color: colors.textMuted,
  },
});
