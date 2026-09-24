import { StyleSheet, View } from 'react-native';

import { shell } from '../theme';

/** The five destinations, in bar order. */
export type TabIconName = 'home' | 'scan' | 'history' | 'rules' | 'settings';

interface TabBarIconProps {
  name: TabIconName;
  /** Stroke colour. The caller passes the selected or unselected ink. */
  color: string;
  size?: number;
  testID?: string;
}

/**
 * The five tab icons, drawn from Views.
 *
 * **Why not an icon library.** These are the only five icons in the app, and
 * every way of getting them as paths costs a native dependency: `react-native-svg`
 * is not installed and is not a transitive dependency of anything here, and the
 * icon-font packages bring their own asset pipeline. Five shapes that are all
 * rectangles, one circle and one rotated square do not justify either. A glyph
 * font was the other option and is worse: the system emoji fall back differently
 * per platform and per OS version, which is how an icon silently becomes a box.
 *
 * Everything is laid out on a **24-unit grid** and scaled to `size`, so the
 * geometry can be read against the handoff's 24-grid drawings without arithmetic.
 * `u()` converts a grid unit to a device-independent pixel.
 *
 * The stroke has a floor of 1.5: below that, a hairline on a 2x screen lands on
 * a half pixel and renders unevenly across the icons, which reads as some of
 * them being lighter than others rather than as a rounding artefact.
 *
 * Accessibility: an icon is decorative here. Every tab carries a visible text
 * label and an `accessibilityLabel`, so the icon is hidden from assistive
 * technology rather than described twice.
 */
export function TabBarIcon({ name, color, size = shell.tabIcon, testID }: TabBarIconProps) {
  const u = (n: number) => (n / 24) * size;
  const stroke = Math.max(1.5, u(1.75));

  return (
    <View
      style={[styles.box, { width: size, height: size }]}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      testID={testID}
    >
      {name === 'home' ? <HomeIcon u={u} stroke={stroke} color={color} /> : null}
      {name === 'scan' ? <ScanIcon u={u} stroke={stroke} color={color} /> : null}
      {name === 'history' ? <HistoryIcon u={u} stroke={stroke} color={color} /> : null}
      {name === 'rules' ? <RulesIcon u={u} stroke={stroke} color={color} /> : null}
      {name === 'settings' ? <SettingsIcon u={u} stroke={stroke} color={color} /> : null}
    </View>
  );
}

interface ShapeProps {
  u: (n: number) => number;
  stroke: number;
  color: string;
}

/**
 * A house: a chevron roof over an open-topped body, with a door.
 *
 * The roof is a square carrying only its top and left borders, rotated 45deg -
 * which puts those two borders on top as a peak. A square of side s spans
 * s * sqrt(2) once rotated, so side 12 gives the 17-unit roof width the grid
 * drawing has.
 */
function HomeIcon({ u, stroke, color }: ShapeProps) {
  return (
    <>
      <View
        style={{
          position: 'absolute',
          left: u(6),
          top: u(6),
          width: u(12),
          height: u(12),
          borderTopWidth: stroke,
          borderLeftWidth: stroke,
          borderColor: color,
          transform: [{ rotate: '45deg' }],
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: u(5.5),
          top: u(11),
          width: u(13),
          height: u(9.5),
          borderLeftWidth: stroke,
          borderRightWidth: stroke,
          borderBottomWidth: stroke,
          borderColor: color,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: u(10),
          top: u(15.5),
          width: u(4),
          height: u(5),
          borderTopWidth: stroke,
          borderLeftWidth: stroke,
          borderRightWidth: stroke,
          borderColor: color,
        }}
      />
    </>
  );
}

/** A viewfinder: four corner brackets and the scan line across the middle. */
function ScanIcon({ u, stroke, color }: ShapeProps) {
  const arm = u(7);
  const inset = u(3.5);
  const radius = u(3);
  const corner = { position: 'absolute' as const, width: arm, height: arm, borderColor: color };
  return (
    <>
      <View
        style={[
          corner,
          {
            left: inset,
            top: inset,
            borderTopWidth: stroke,
            borderLeftWidth: stroke,
            borderTopLeftRadius: radius,
          },
        ]}
      />
      <View
        style={[
          corner,
          {
            right: inset,
            top: inset,
            borderTopWidth: stroke,
            borderRightWidth: stroke,
            borderTopRightRadius: radius,
          },
        ]}
      />
      <View
        style={[
          corner,
          {
            right: inset,
            bottom: inset,
            borderBottomWidth: stroke,
            borderRightWidth: stroke,
            borderBottomRightRadius: radius,
          },
        ]}
      />
      <View
        style={[
          corner,
          {
            left: inset,
            bottom: inset,
            borderBottomWidth: stroke,
            borderLeftWidth: stroke,
            borderBottomLeftRadius: radius,
          },
        ]}
      />
      <View
        style={{
          position: 'absolute',
          left: inset,
          right: inset,
          top: u(12) - stroke / 2,
          height: stroke,
          backgroundColor: color,
        }}
      />
    </>
  );
}

/**
 * A clock.
 *
 * The handoff draws the conventional "clock with a reset arrow" for history.
 * The arrow's tail is an arc and an arrowhead, which is two more rotated
 * squares and a visibly worse shape at 22 pt than no arrow at all - so the dial
 * stands alone. The tab's visible "History" label is what disambiguates it from
 * a timer, and that label is always present.
 */
function HistoryIcon({ u, stroke, color }: ShapeProps) {
  return (
    <>
      <View
        style={{
          position: 'absolute',
          left: u(3.5),
          top: u(3.5),
          width: u(17),
          height: u(17),
          borderWidth: stroke,
          borderColor: color,
          borderRadius: u(17) / 2,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: u(12) - stroke / 2,
          top: u(7.4),
          width: stroke,
          height: u(4.6),
          backgroundColor: color,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: u(12),
          top: u(12) - stroke / 2,
          width: u(3.8),
          height: stroke,
          backgroundColor: color,
        }}
      />
    </>
  );
}

/**
 * A document with three lines of text.
 *
 * The handoff draws an open book. A book is two mirrored covers with a curved
 * spine; without paths that is four rotated Views and it reads as a smudge at
 * 22 pt. A sheet with three rules on it says "the written requirements" just as
 * plainly and holds its shape at every size, so it is the substitution made
 * here rather than a worse drawing of the original.
 */
function RulesIcon({ u, stroke, color }: ShapeProps) {
  const line = {
    position: 'absolute' as const,
    left: u(8.25),
    width: u(7.5),
    height: stroke,
    backgroundColor: color,
  };
  return (
    <>
      <View
        style={{
          position: 'absolute',
          left: u(5),
          top: u(3),
          width: u(14),
          height: u(18),
          borderWidth: stroke,
          borderColor: color,
          borderRadius: u(2.5),
        }}
      />
      <View style={[line, { top: u(8.5) }]} />
      <View style={[line, { top: u(12) }]} />
      <View style={[line, { top: u(15.5) }]} />
    </>
  );
}

/**
 * Three sliders, each a rail broken by a knob.
 *
 * A gear was the other candidate and needs eight teeth around a hub; at 22 pt
 * those teeth merge and it reads as a sun. Sliders stay legible, and the knobs
 * sit at different offsets so the icon is not mistaken for a list.
 */
function SettingsIcon({ u, stroke, color }: ShapeProps) {
  const rails: { y: number; left: number; rightStart: number; knob: number }[] = [
    { y: 6, left: 6.2, rightStart: 14.7, knob: 12.2 },
    { y: 12, left: 3.8, rightStart: 12.3, knob: 9.8 },
    { y: 18, left: 8.3, rightStart: 16.8, knob: 14.3 },
  ];
  return (
    <>
      {rails.map((rail) => (
        <View key={rail.y}>
          <View
            style={{
              position: 'absolute',
              left: u(3.5),
              top: u(rail.y) - stroke / 2,
              width: u(rail.left),
              height: stroke,
              backgroundColor: color,
            }}
          />
          <View
            style={{
              position: 'absolute',
              left: u(rail.rightStart),
              top: u(rail.y) - stroke / 2,
              width: u(20.5 - rail.rightStart),
              height: stroke,
              backgroundColor: color,
            }}
          />
          <View
            style={{
              position: 'absolute',
              left: u(rail.knob) - stroke / 2,
              top: u(rail.y - 2),
              width: stroke,
              height: u(4),
              backgroundColor: color,
            }}
          />
        </View>
      ))}
    </>
  );
}

const styles = StyleSheet.create({
  box: {
    position: 'relative',
  },
});
