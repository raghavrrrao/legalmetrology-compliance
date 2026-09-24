/**
 * The Rules screen shows the repository's rules and claims nothing about them.
 *
 * The assertions are deliberately about *honesty* rather than about layout: that
 * every rule is listed, that the inactive one is listed and marked rather than
 * hidden, and that the screen says the checking happens elsewhere. Those are the
 * properties that would make the screen a compliance claim if they broke.
 */

import { render, screen } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { RulesScreen } from './RulesScreen';
import { PHONE_METRICS } from '../../tests/render';
import { LMPC_RULES, RULE_COUNTS } from '../data/lmpcRules';

async function renderRules() {
  await render(
    <SafeAreaProvider initialMetrics={PHONE_METRICS}>
      <RulesScreen />
    </SafeAreaProvider>,
  );
}

describe('RulesScreen', () => {
  it('lists every bundled rule with its code, provision and title', async () => {
    await renderRules();

    for (const rule of LMPC_RULES) {
      const row = screen.getByTestId(`rule-${rule.code}`);
      expect(row).toHaveTextContent(rule.code, { exact: false });
      expect(row).toHaveTextContent(rule.provision, { exact: false });
      expect(row).toHaveTextContent(rule.title, { exact: false });
    }
  });

  it('marks a recorded rule that is not evaluated, rather than hiding it', async () => {
    await renderRules();

    const inactive = LMPC_RULES.filter((rule) => !rule.isActive);
    expect(inactive.length).toBeGreaterThan(0);

    for (const rule of inactive) {
      expect(screen.getByTestId(`rule-inactive-${rule.code}`)).toBeOnTheScreen();
    }
    // And the active ones carry no marker, or the marker would mean nothing.
    for (const rule of LMPC_RULES.filter((candidate) => candidate.isActive)) {
      expect(screen.queryByTestId(`rule-inactive-${rule.code}`)).toBeNull();
    }
  });

  it('separates how many rules are recorded from how many are evaluated', async () => {
    await renderRules();

    const summary = screen.getByTestId('rule-counts-summary');
    expect(summary).toHaveTextContent(String(RULE_COUNTS.recorded), { exact: false });
    expect(summary).toHaveTextContent('RECORDED', { exact: false });
    expect(summary).toHaveTextContent(String(RULE_COUNTS.evaluated), { exact: false });
    expect(summary).toHaveTextContent('EVALUATED', { exact: false });
  });

  it('says nothing is decided on the phone, and that a check is narrower than its clause', async () => {
    await renderRules();

    const footnote = screen.getByTestId('rules-footnote');
    expect(footnote).toHaveTextContent('Nothing is decided on this phone', { exact: false });
    expect(footnote).toHaveTextContent('more narrowly than its clause requires', { exact: false });
  });

  it('presents the list as the app’s bundled copy, not as what the server checks', async () => {
    await renderRules();

    // The list is generated from `rules/definitions` at build time. Nothing asks
    // the server which rules it has loaded, so the screen must not say it did -
    // the first version read "The requirements this server checks", which a
    // device review caught.
    expect(screen.queryByText(/this server checks/i)).toBeNull();
    expect(screen.getByText(/this version of the app was built with/i)).toBeOnTheScreen();
    expect(screen.getByText(/The analysis server applies its own copy/i)).toBeOnTheScreen();
  });

  it('names the instrument the rules come from', async () => {
    await renderRules();

    expect(
      screen.getByText(/Legal Metrology \(Packaged Commodities\) Rules, 2011/),
    ).toBeOnTheScreen();
  });
});
