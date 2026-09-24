import { StyleSheet, View } from 'react-native';

import { colors, radius } from '../theme';

interface BrandMarkProps {
  /** Side of the tile. The scale inside is drawn at 62% of it. */
  size?: number;
  testID?: string;
}

/**
 * The application mark: a balance scale on a dark tile.
 *
 * A balance rather than a tick, a shield or a magnifier. Legal metrology *is*
 * weights and measures, so the scale is the one figure that says what this
 * application is about without making a claim about what it finds. A tick would
 * be a verdict on the tile, which is the one thing a mark must never be.
 *
 * Drawn from Views on the same 24-unit grid as `TabBarIcon`, and for the same
 * reason - see that file's note on why there is no icon dependency here. The
 * tile takes `colors.brandInk`, which exists for this and the wordmark beside it
 * and is not a control colour.
 */
export function BrandMark({ size = 32, testID }: BrandMarkProps) {
  const glyph = size * 0.62;
  const u = (n: number) => (n / 24) * glyph;
  const stroke = Math.max(1.5, u(1.8));
  const ink = colors.onAction;

  const pan = {
    position: 'absolute' as const,
    top: u(8.4),
    width: u(4.6),
    height: u(2.8),
    borderBottomWidth: stroke,
    borderLeftWidth: stroke,
    borderRightWidth: stroke,
    borderColor: ink,
    borderBottomLeftRadius: u(2.3),
    borderBottomRightRadius: u(2.3),
  };

  return (
    <View
      style={[styles.tile, { width: size, height: size, borderRadius: radius.sm }]}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      testID={testID}
    >
      <View style={{ width: glyph, height: glyph }}>
        {/* The upright, from the beam down to the foot. */}
        <View
          style={{
            position: 'absolute',
            left: u(12) - stroke / 2,
            top: u(4.6),
            width: stroke,
            height: u(14.6),
            backgroundColor: ink,
          }}
        />
        {/* The foot. */}
        <View
          style={{
            position: 'absolute',
            left: u(8.2),
            top: u(19.2) - stroke / 2,
            width: u(7.6),
            height: stroke,
            backgroundColor: ink,
          }}
        />
        {/* The beam. Its ends are the centres of the two pans below. */}
        <View
          style={{
            position: 'absolute',
            left: u(4.6),
            top: u(8.4) - stroke / 2,
            width: u(14.8),
            height: stroke,
            backgroundColor: ink,
          }}
        />
        <View style={[pan, { left: u(2.3) }]} />
        <View style={[pan, { left: u(17.1) }]} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  tile: {
    backgroundColor: colors.brandInk,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
