/**
 * The analysis state.
 *
 * Most of these assert what the panel must NOT do. A progress display is the
 * easiest place in an interface to start lying - a bar that fills on a timer,
 * a percentage nobody computed, a stage that ticks because it looks better
 * ticking - and none of those failures would be caught by the screens on
 * either side of it.
 */

import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AnalysisPanel } from './AnalysisPanel.jsx';
import { PHASES } from '../hooks/useLabelAnalysis.js';

function renderPanel(props = {}) {
  return render(
    <AnalysisPanel
      previewUrl="blob:preview"
      fileName="label.jpg"
      phase={PHASES.EXTRACTING}
      {...props}
    />,
  );
}

/**
 * One stage row, found inside the list.
 *
 * Scoped to the list on purpose: the running stage's name is also the panel's
 * heading, so a bare text query matches twice. That duplication is intended -
 * the heading is what a reader sees first and the row is where its state
 * lives - so the query is what has to be specific.
 */
function stage(name) {
  return within(screen.getByRole('list')).getByText(name).closest('li');
}

describe('what the panel shows', () => {
  it('shows the photograph being checked, with a description of it', () => {
    renderPanel();

    expect(
      screen.getByRole('img', { name: /the label being checked: label\.jpg/i }),
    ).toHaveAttribute('src', 'blob:preview');
  });

  it('names the stage that is actually running as the heading', () => {
    renderPanel({ phase: PHASES.EXTRACTING });

    expect(
      screen.getByRole('heading', { name: /reading the label/i }),
    ).toBeInTheDocument();
  });

  it('says the work happens on the server, not in the browser', () => {
    renderPanel();

    expect(screen.getByText(/nothing is decided in this browser/i)).toBeInTheDocument();
  });
});

describe('stages follow the real phase', () => {
  it('marks reading as in progress while the extraction request is in flight', () => {
    renderPanel({ phase: PHASES.EXTRACTING });

    expect(stage('Reading the label')).toHaveClass('analysis__stage--active');
    expect(stage('Checking requirements')).toHaveClass('analysis__stage--pending');
  });

  it('moves to checking once the reading has come back', () => {
    renderPanel({ phase: PHASES.EVALUATING });

    expect(stage('Reading the label')).toHaveClass('analysis__stage--done');
    expect(stage('Checking requirements')).toHaveClass('analysis__stage--active');
  });

  it('reports the declaration count from the response, once there is one', () => {
    renderPanel({ phase: PHASES.EVALUATING, declarationsRead: 4 });

    expect(within(stage('Reading the label')).getByText(/4 declarations read/i))
      .toBeInTheDocument();
  });

  it('shows no count at all when the response did not carry one', () => {
    // Undefined is not zero. A reading whose field count is unknown must not
    // be reported as having found nothing.
    renderPanel({ phase: PHASES.EVALUATING, declarationsRead: undefined });

    expect(screen.queryByText(/declarations read/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/0 declarations/i)).not.toBeInTheDocument();
  });

  it('states each stage in words as well as by its marker', () => {
    renderPanel({ phase: PHASES.EXTRACTING });

    expect(within(stage('Photograph uploaded')).getByText('complete')).toBeInTheDocument();
    expect(within(stage('Reading the label')).getByText('in progress')).toBeInTheDocument();
    expect(within(stage('Preparing findings')).getByText('not started')).toBeInTheDocument();
  });
});

describe('what it must never claim', () => {
  it('shows no percentage, no fraction and no countdown', () => {
    const { container } = renderPanel({
      phase: PHASES.EVALUATING,
      declarationsRead: 4,
    });

    // "4 declarations read" is a real count from the response and is allowed.
    // A percentage, an "n of m" or a seconds estimate is not: nothing in the
    // pipeline reports progress, so nothing here may imply it does.
    expect(container.textContent).not.toMatch(/%/);
    expect(container.textContent).not.toMatch(/\b\d+\s*(of|\/)\s*\d+\b/);
    expect(container.textContent).not.toMatch(/\bsecond|\bminute|remaining|estimated/i);
  });

  it('exposes no progressbar role, because there is no measurable progress', () => {
    renderPanel();

    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('does not split one server call into two ticking stages', () => {
    // The extraction request recognises text AND extracts declarations; the
    // compliance request evaluates rules AND assembles findings. The browser
    // cannot see inside either, so there are four stages and not five.
    renderPanel();

    expect(screen.getAllByRole('listitem')).toHaveLength(4);
  });

  it('renders without a preview without inventing an image', () => {
    renderPanel({ previewUrl: null });

    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: /reading the label/i }),
    ).toBeInTheDocument();
  });
});
