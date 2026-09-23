import { useEffect, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, Image, StyleSheet, View } from 'react-native';

import { colors, radius } from '../theme';

interface ScanPreviewProps {
  /** The local URI of the photograph being checked. */
  uri: string;
  /** False once nothing is in flight, which stops the sweep. */
  scanning?: boolean;
  testID?: string;
}

/**
 * The photograph being checked, under a scanning sweep.
 *
 * The mobile counterpart of the web's analysis frame, built the way a native
 * screen should be rather than by porting the CSS: `Animated` with
 * `useNativeDriver`, so the sweep runs on the UI thread and does not compete
 * with the upload for the JavaScript one.
 *
 * **It shows progress through the image, and reports none.** There is no bar,
 * no percentage and no estimate here, because the pipeline reports none - the
 * sweep is a sign of life over a state that `ProgressSteps` states in words
 * beside it. When the sweep stops, nothing about the outcome has been said.
 *
 * Reduced motion is honoured directly: `AccessibilityInfo.isReduceMotionEnabled`
 * plus its change event, so the sweep is never started on a device that has
 * asked for stillness, and stops on one that asks mid-analysis. The frame, the
 * brackets and the photograph all remain - only the movement goes.
 */
export function ScanPreview({ uri, scanning = true, testID }: ScanPreviewProps) {
  // `useState` with a lazy initialiser rather than `useRef(...).current`: both
  // give one `Animated.Value` for the component's lifetime, but only this one
  // avoids reading a ref during render, which React's own lint rule rejects
  // because it is the shape that silently fails to update.
  const [travel] = useState(() => new Animated.Value(0));
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    let active = true;
    AccessibilityInfo.isReduceMotionEnabled()
      .then((enabled) => {
        if (active) {
          setReduceMotion(enabled);
        }
      })
      // A device that cannot answer is not a device that wants animation
      // forced on it, but it is also not a reason to fail: default to moving,
      // which is the same thing every other surface in the app does.
      .catch(() => undefined);

    const subscription = AccessibilityInfo.addEventListener(
      'reduceMotionChanged',
      setReduceMotion,
    );
    return () => {
      active = false;
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    if (!scanning || reduceMotion) {
      travel.stopAnimation();
      travel.setValue(0);
      return undefined;
    }

    const loop = Animated.loop(
      Animated.timing(travel, {
        toValue: 1,
        duration: 2400,
        easing: Easing.inOut(Easing.ease),
        useNativeDriver: true,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [scanning, reduceMotion, travel]);

  const translateY = travel.interpolate({
    inputRange: [0, 1],
    outputRange: [-SWEEP_HEIGHT, FRAME_HEIGHT],
  });

  return (
    <View style={styles.frame} testID={testID}>
      <Image
        source={{ uri }}
        style={styles.image}
        resizeMode="contain"
        // Decorative here: the screen's heading and the step list already say
        // what is happening, and describing the user's own photograph back to
        // them adds nothing.
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
      />

      {scanning && !reduceMotion ? (
        <Animated.View
          pointerEvents="none"
          style={[styles.sweep, { transform: [{ translateY }] }]}
          testID="scan-sweep"
        />
      ) : null}

      <View pointerEvents="none" style={[styles.bracket, styles.topLeft]} />
      <View pointerEvents="none" style={[styles.bracket, styles.topRight]} />
      <View pointerEvents="none" style={[styles.bracket, styles.bottomLeft]} />
      <View pointerEvents="none" style={[styles.bracket, styles.bottomRight]} />
    </View>
  );
}

/** Fixed so the sweep's travel can be expressed without measuring on layout. */
const FRAME_HEIGHT = 240;
const SWEEP_HEIGHT = 34;
const BRACKET = 20;
const BRACKET_WIDTH = 2;
const EDGE = 10;

const styles = StyleSheet.create({
  frame: {
    height: FRAME_HEIGHT,
    borderRadius: radius.lg,
    overflow: 'hidden',
    backgroundColor: colors.photoWell,
    marginBottom: 16,
  },
  image: {
    width: '100%',
    height: '100%',
  },
  sweep: {
    position: 'absolute',
    left: 0,
    right: 0,
    height: SWEEP_HEIGHT,
    backgroundColor: 'rgba(52, 199, 123, 0.18)',
    borderBottomWidth: 1.5,
    borderBottomColor: 'rgba(180, 255, 214, 0.9)',
  },
  bracket: {
    position: 'absolute',
    width: BRACKET,
    height: BRACKET,
    borderColor: 'rgba(255, 255, 255, 0.7)',
  },
  topLeft: {
    top: EDGE,
    left: EDGE,
    borderTopWidth: BRACKET_WIDTH,
    borderLeftWidth: BRACKET_WIDTH,
  },
  topRight: {
    top: EDGE,
    right: EDGE,
    borderTopWidth: BRACKET_WIDTH,
    borderRightWidth: BRACKET_WIDTH,
  },
  bottomLeft: {
    bottom: EDGE,
    left: EDGE,
    borderBottomWidth: BRACKET_WIDTH,
    borderLeftWidth: BRACKET_WIDTH,
  },
  bottomRight: {
    bottom: EDGE,
    right: EDGE,
    borderBottomWidth: BRACKET_WIDTH,
    borderRightWidth: BRACKET_WIDTH,
  },
});
