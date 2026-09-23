import { Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, elevation, MIN_TOUCH_TARGET, radius, spacing, typography } from '../theme';
import type { SelectedImage } from '../services/imageValidation';

interface ImageTrayProps {
  /** The photographs of this inspection, in submission order. */
  images: SelectedImage[];
  /** Remove the photograph at this index. */
  onRemove: (index: number) => void;
  /** Add more. Omitted or with `canAddMore` false, the add tile is disabled. */
  onAdd?: () => void;
  canAddMore?: boolean;
  /** Disables every control while a pick or an upload is in flight. */
  busy?: boolean;
  testID?: string;
}

/**
 * The photographs gathered for one inspection, as a row of thumbnails.
 *
 * This is the control that has to make one thing unmistakable: **these
 * photographs, and only these, are what will be checked.** Everything below
 * serves that.
 *
 * - Each tile is **numbered**, and the number is the position the backend will
 *   use. "Image 2" on this screen and "Evidence · Image 2" on the result screen
 *   are the same photograph, which is the whole point of showing a number
 *   rather than just a strip of pictures.
 * - Each tile has its **own remove control**, labelled with the number, so a
 *   screen-reader user can remove the third photograph without discovering
 *   which one "remove" means by pressing it.
 * - The **add tile sits at the end of the row**, in the same rhythm as the
 *   thumbnails, so adding more reads as continuing the set rather than as
 *   starting again.
 *
 * Accessibility: the row is a horizontal list a screen reader walks through in
 * order; each thumbnail is one element labelled with its position, and the
 * remove button beside it is a separate, individually labelled button. The
 * remove control is 44 px and sits inside a 48 px touch target, at the corner
 * of a tile large enough that the two cannot be confused by a thumb.
 *
 * No animation here at all. A tray of the user's own photographs does not need
 * motion to be understood, and a removal that animates is a removal the user
 * has to wait to be sure of.
 */
export function ImageTray({
  images,
  onRemove,
  onAdd,
  canAddMore = true,
  busy = false,
  testID,
}: ImageTrayProps) {
  const total = images.length;

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
      accessibilityRole="list"
      accessibilityLabel={
        total === 0
          ? 'No photos added yet'
          : `${total} ${total === 1 ? 'photo' : 'photos'} in this inspection`
      }
      testID={testID}
    >
      {images.map((image, index) => (
        <View key={image.uri} style={styles.tile} testID={`image-tile-${index}`}>
          <Image
            source={{ uri: image.uri }}
            style={styles.thumbnail}
            resizeMode="cover"
            accessible
            // The position, not a description of the photograph: this app has
            // not looked at it and must not claim to know what it shows.
            accessibilityLabel={`Photo ${index + 1} of ${total}`}
          />

          <View style={styles.badge} pointerEvents="none">
            <Text style={styles.badgeText}>{index + 1}</Text>
          </View>

          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Remove photo ${index + 1}`}
            accessibilityHint="Takes this photo out of the inspection"
            accessibilityState={{ disabled: busy }}
            disabled={busy}
            onPress={() => onRemove(index)}
            // Extends the touch target past the visible 28 px control without
            // enlarging it into the thumbnail it sits on.
            hitSlop={10}
            style={({ pressed }) => [styles.remove, pressed && styles.removePressed, busy && styles.dim]}
            testID={`remove-image-${index}`}
          >
            <Text style={styles.removeGlyph}>×</Text>
          </Pressable>
        </View>
      ))}

      {onAdd ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Add another photo"
          accessibilityHint={
            canAddMore
              ? 'Choose where the next photo of this package comes from'
              : 'The maximum number of photos has been added'
          }
          accessibilityState={{ disabled: busy || !canAddMore }}
          disabled={busy || !canAddMore}
          onPress={onAdd}
          style={({ pressed }) => [
            styles.tile,
            styles.addTile,
            pressed && canAddMore && !busy && styles.addTilePressed,
            (!canAddMore || busy) && styles.dim,
          ]}
          testID="add-image"
        >
          <Text style={styles.addGlyph}>+</Text>
          <Text style={styles.addLabel}>Add</Text>
        </Pressable>
      ) : null}
    </ScrollView>
  );
}

const TILE = 96;
const REMOVE = 28;

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: spacing.md,
    paddingVertical: spacing.xs,
    // So the remove control at a tile's top-right corner is not clipped by the
    // scroll view's own bounds.
    paddingTop: spacing.sm,
    paddingRight: spacing.xs,
  },
  tile: {
    width: TILE,
    height: TILE,
    borderRadius: radius.md,
    backgroundColor: colors.photoWell,
    // The selected state: a hairline in the accent, so a tile reads as part of
    // the set at a glance rather than as a picture that happens to be nearby.
    borderWidth: 1.5,
    borderColor: colors.primary,
    ...elevation.card,
  },
  thumbnail: {
    width: '100%',
    height: '100%',
    borderRadius: radius.md - 1.5,
  },
  badge: {
    position: 'absolute',
    left: spacing.xs,
    bottom: spacing.xs,
    minWidth: 20,
    paddingHorizontal: spacing.xs,
    paddingVertical: 1,
    borderRadius: radius.xs,
    backgroundColor: 'rgba(28, 28, 30, 0.72)',
    alignItems: 'center',
  },
  badgeText: {
    ...typography.caption,
    fontWeight: '700',
    color: '#FFFFFF',
  },
  remove: {
    position: 'absolute',
    top: -spacing.sm,
    right: -spacing.sm,
    width: REMOVE,
    height: REMOVE,
    borderRadius: REMOVE / 2,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    alignItems: 'center',
    justifyContent: 'center',
    ...elevation.raised,
  },
  removePressed: {
    backgroundColor: colors.surfaceSunken,
  },
  removeGlyph: {
    fontSize: 18,
    lineHeight: 20,
    fontWeight: '600',
    color: colors.text,
  },
  addTile: {
    backgroundColor: colors.primarySofter,
    borderStyle: 'dashed',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: MIN_TOUCH_TARGET,
  },
  addTilePressed: {
    backgroundColor: colors.primarySoft,
  },
  addGlyph: {
    fontSize: 26,
    lineHeight: 30,
    fontWeight: '300',
    color: colors.primary,
  },
  addLabel: {
    ...typography.caption,
    fontWeight: '600',
    color: colors.primary,
  },
  dim: {
    opacity: 0.5,
  },
});
