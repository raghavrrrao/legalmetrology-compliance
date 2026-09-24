/**
 * The photo-remove control's touch target.
 *
 * Measured on an Android emulator (API 35), the old control - a 28 pt Pressable
 * with `hitSlop={10}` - accepted taps across about 38 x 38 pt, not 48 x 48: the
 * part of a hit slop that falls outside the parent tile is dropped, while a
 * child's own frame outside the tile is not. The fix makes the 48 pt target out
 * of frame. Jest cannot measure a tap, so these tests pin the geometry that made
 * the measurement come out right, and fail on the old shape.
 */

import { fireEvent, render, screen } from '@testing-library/react-native';

import { ImageTray, REMOVE_TARGET } from './ImageTray';
import type { SelectedImage } from '../services/imageValidation';
import { MIN_TOUCH_TARGET, spacing } from '../theme';

function photo(n: number): SelectedImage {
  return {
    uri: `file:///cache/panel-${n}.jpg`,
    name: `panel-${n}.jpg`,
    type: 'image/jpeg',
    sizeBytes: 1000,
    width: 3000,
    height: 4000,
  };
}

function flat(style: unknown): Record<string, unknown> {
  const layers = (Array.isArray(style) ? style.flat(Infinity) : [style]).filter(Boolean);
  return Object.assign({}, ...layers) as Record<string, unknown>;
}

async function renderTray(onRemove = jest.fn()) {
  await render(
    <ImageTray images={[photo(1), photo(2)]} onRemove={onRemove} onAdd={jest.fn()} testID="tray" />,
  );
  return onRemove;
}

describe('ImageTray remove control', () => {
  it('has a 48 pt touch target made of its own frame, not of hit slop', async () => {
    await renderTray();

    const target = screen.getByTestId('remove-image-0');
    const style = flat(target.props.style);
    expect(style.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET);
    expect(style.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET);
    // Hit slop is what Android clipped at the tile's edge. The target must not
    // depend on it, or it silently shrinks back to ~38 pt on a device.
    expect(target.props.hitSlop).toBeUndefined();
  });

  it('keeps the visible circle the size and position it always had', async () => {
    await renderTray();

    const dot = flat(screen.getByTestId('remove-dot-0').props.style);
    expect(dot.width).toBe(28);
    expect(dot.height).toBe(28);

    // The circle's top-right corner in tile coordinates, derived from the
    // target's offset plus the dot's offset inside it. Before the fix it was
    // `top: -8, right: -8` directly on the tile; it must land there still.
    const target = flat(screen.getByTestId('remove-image-0').props.style);
    expect((target.top as number) + (dot.top as number)).toBe(-spacing.sm);
    expect((target.right as number) + (dot.right as number)).toBe(-spacing.sm);
  });

  it('stops at the gap before the next tile, so a neighbour never takes its taps', async () => {
    await renderTray();

    // `right: -12` puts the target's right edge exactly on the next tile's left
    // edge. Any further and the later-drawn neighbour would win those points,
    // and a tap on the neighbour's corner would remove this photo instead.
    const target = flat(screen.getByTestId('remove-image-0').props.style);
    expect(target.right).toBe(-spacing.md);
    expect(REMOVE_TARGET.right).toBe(-spacing.md);
    // And it rises no higher than the circle, which sits inside the row's
    // existing top padding - so the tray's layout is unchanged.
    expect(target.top).toBe(-spacing.sm);
  });

  it('still removes the photo it belongs to, and still says which one', async () => {
    const onRemove = await renderTray();

    const second = screen.getByLabelText('Remove photo 2');
    await fireEvent.press(second);

    expect(onRemove).toHaveBeenCalledWith(1);
    expect(onRemove).toHaveBeenCalledTimes(1);
  });
});
