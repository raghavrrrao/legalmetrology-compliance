/**
 * The scanning frame on the analysis screen.
 *
 * Two properties are worth a test here and neither is about how it looks: the
 * sweep must stop when the device has asked for reduced motion, and it must
 * never imply progress that the pipeline does not report.
 */

import { AccessibilityInfo } from 'react-native';
import { act, render, screen, waitFor } from '@testing-library/react-native';

import { ScanPreview } from './ScanPreview';

function mockReduceMotion(enabled: boolean) {
  jest
    .spyOn(AccessibilityInfo, 'isReduceMotionEnabled')
    .mockResolvedValue(enabled);
  jest
    .spyOn(AccessibilityInfo, 'addEventListener')
    // The component only needs `remove` to exist; nothing here fires the event.
    .mockReturnValue({ remove: jest.fn() } as never);
}

/**
 * Render, then let the `AccessibilityInfo.isReduceMotionEnabled` promise
 * settle.
 *
 * The component asks the OS whether motion is wanted and sets state when the
 * answer arrives. That resolution happens on a microtask outside React's
 * `act` scope, which React escalates to an error - so the flush belongs here,
 * once, rather than being worked around differently in every test.
 */
async function renderPreview(props: { scanning?: boolean } = {}) {
  // `render` inside the act scope rather than beside it. `render` opens its own
  // scope and the mocked promise resolves as that scope closes, so a second
  // `act` afterwards overlaps the first - which React reports as an error
  // rather than a warning, and which fails the test for a reason that has
  // nothing to do with the component.
  await act(async () => {
    render(
      <ScanPreview uri="file:///label.jpg" scanning testID="frame" {...props} />,
    );
  });
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe('ScanPreview', () => {
  it('sweeps while a request is in flight', async () => {
    mockReduceMotion(false);

    await renderPreview();

    expect(screen.getByTestId('scan-sweep')).toBeOnTheScreen();
  });

  it('shows no sweep once nothing is in flight', async () => {
    mockReduceMotion(false);

    await renderPreview({ scanning: false });

    expect(screen.getByTestId('frame')).toBeOnTheScreen();
    expect(screen.queryByTestId('scan-sweep')).not.toBeOnTheScreen();
  });

  it('does not sweep when the device asks for reduced motion', async () => {
    mockReduceMotion(true);

    await renderPreview();

    // The frame and the photograph stay; only the movement goes.
    await waitFor(() =>
      expect(screen.queryByTestId('scan-sweep')).not.toBeOnTheScreen(),
    );
    expect(screen.getByTestId('frame')).toBeOnTheScreen();
  });

  it('claims no progress: no percentage, no estimate, no progressbar', async () => {
    mockReduceMotion(false);

    await renderPreview();
    expect(screen.getByTestId('scan-sweep')).toBeOnTheScreen();

    // The frame is a sign of life over a state stated in words elsewhere. It
    // must not carry a number of its own.
    expect(screen.queryByText(/%/)).not.toBeOnTheScreen();
    expect(screen.queryByText(/remaining|estimated|second/i)).not.toBeOnTheScreen();
    expect(screen.queryByRole('progressbar')).not.toBeOnTheScreen();
  });
});
