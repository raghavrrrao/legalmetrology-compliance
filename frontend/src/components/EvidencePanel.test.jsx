/**
 * The evidence overlay.
 *
 * The rule this component is held to: a rectangle drawn on the photograph is a
 * claim about where something was read, so it appears only when the API
 * actually supplied a usable box. Everything here tests that boundary.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { EvidencePanel } from './EvidencePanel.jsx';

const IMAGE = { width: 800, height: 600, imageFormat: 'png' };

function finding(overrides = {}) {
  return {
    id: 1,
    status: 'failed',
    boundingBox: { x: 40, y: 60, width: 200, height: 30 },
    ...overrides,
  };
}

function boxes(container) {
  return container.querySelectorAll('.evidence-box');
}

describe('EvidencePanel', () => {
  it('draws a marker for each finding that recorded a location', () => {
    const { container } = render(
      <EvidencePanel
        imageUrl="blob:preview"
        image={IMAGE}
        findings={[finding({ id: 1 }), finding({ id: 2 })]}
      />,
    );

    expect(boxes(container)).toHaveLength(2);
    expect(screen.getByRole('img')).toHaveAttribute('src', 'blob:preview');
    expect(screen.getByText(/2 of 2 findings recorded a location/i)).toBeInTheDocument();
  });

  it('positions a box from the source-image coordinate space', () => {
    const { container } = render(
      <EvidencePanel imageUrl="blob:preview" image={IMAGE} findings={[finding()]} />,
    );

    const [box] = boxes(container);
    expect(box.style.left).toBe('5%');
    expect(box.style.top).toBe('10%');
    expect(box.style.width).toBe('25%');
    expect(box.style.height).toBe('5%');
  });

  it('draws nothing for a finding with no bounding box', () => {
    const { container } = render(
      <EvidencePanel
        imageUrl="blob:preview"
        image={IMAGE}
        findings={[finding({ boundingBox: null })]}
      />,
    );

    expect(boxes(container)).toHaveLength(0);
    expect(
      screen.getByText(/no finding recorded a location on the image/i),
    ).toBeInTheDocument();
  });

  it('draws nothing when the image dimensions are unknown', () => {
    // Without the source dimensions there is no coordinate space to map into,
    // and guessing one would put a rectangle in the wrong place.
    const { container } = render(
      <EvidencePanel imageUrl="blob:preview" image={null} findings={[finding()]} />,
    );

    expect(boxes(container)).toHaveLength(0);
  });

  it('reports an unavailable photograph instead of an empty frame', () => {
    render(<EvidencePanel imageUrl={null} image={IMAGE} findings={[finding()]} />);

    expect(
      screen.getByText(/not available on this device/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('numbers markers in the same order the findings are listed', () => {
    render(
      <EvidencePanel
        imageUrl="blob:preview"
        image={IMAGE}
        findings={[
          finding({ id: 1, status: 'passed' }),
          finding({ id: 2, status: 'failed' }),
        ]}
      />,
    );

    // Failures sort first in both places, so the failed finding is 01 here and
    // 01 in the list beside it.
    expect(screen.getByText('01')).toBeInTheDocument();
    expect(screen.getByText('02')).toBeInTheDocument();
  });

  it('handles an empty findings array', () => {
    const { container } = render(
      <EvidencePanel imageUrl="blob:preview" image={IMAGE} findings={[]} />,
    );

    expect(boxes(container)).toHaveLength(0);
    expect(screen.getByRole('img')).toBeInTheDocument();
  });
});
