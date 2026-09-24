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
 * remove control is drawn at 28 pt and its touch target is a 48 x 48 frame
 * around it - see `REMOVE_TARGET` for where that frame sits and why.
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
            /*
             * The touch target is this Pressable's own 48 x 48 frame; the
             * visible 28 pt circle is drawn inside it. It used to be a 28 pt
             * Pressable with `hitSlop={10}`, which measured about 38 x 38 on an
             * Android emulator: React Native drops the part of a hit slop that
             * falls outside the parent (here, the tile), though it does accept
             * a child's real frame there. So the target is made of frame.
             */
            style={[styles.removeTarget, busy && styles.dim]}
            testID={`remove-image-${index}`}
          >
            {({ pressed }) => (
              <View style={[styles.remove, pressed && styles.removePressed]} testID={`remove-dot-${index}`}>
                <Text style={styles.removeGlyph}>×</Text>
              </View>
            )}
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
/** Space between tiles. The remove target may reach into it, and no further. */
const GAP = spacing.md;
/** How far the visible circle overhangs the tile's top and right edges. */
const OVERHANG = spacing.sm;

/**
 * Where the remove control's 48 pt target sits, in tile coordinates.
 *
 * Three constraints decide it, and the numbers fall out of them:
 *
 * - **It contains the circle**, which stays exactly where it always was: 28 pt,
 *   overhanging the tile by 8 at the top-right.
 * - **Its right edge is the start of the next tile**, `GAP` past this one. A
 *   later sibling is drawn on top, so a target reaching into the next tile would
 *   lose those points to it anyway - and would make the neighbour's corner
 *   remove this photo.
 * - **Its top edge is the circle's top**, inside the row's existing top padding,
 *   so the tray's layout does not move.
 *
 * The remaining height goes down into this tile's own thumbnail, which is not
 * interactive - the same region `hitSlop` used to cover, a little larger.
 */
export const REMOVE_TARGET = Object.freeze({
  size: MIN_TOUCH_TARGET,
  top: -OVERHANG,
  right: -GAP,
  /** The circle's offset inside the target, so it lands where it always did. */
  dotRight: GAP - OVERHANG,
  dotSize: REMOVE,
});

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: GAP,
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
    borderColor: colors.action,
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
  /* The 48 pt touch target. Transparent; see `REMOVE_TARGET`. */
  removeTarget: {
    position: 'absolute',
    top: REMOVE_TARGET.top,
    right: REMOVE_TARGET.right,
    width: REMOVE_TARGET.size,
    height: REMOVE_TARGET.size,
  },
  /* The visible circle, unchanged in size and position from before. */
  remove: {
    position: 'absolute',
    top: 0,
    right: REMOVE_TARGET.dotRight,
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
    backgroundColor: colors.actionSofter,
    borderStyle: 'dashed',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: MIN_TOUCH_TARGET,
  },
  addTilePressed: {
    backgroundColor: colors.actionSoft,
  },
  addGlyph: {
    fontSize: 26,
    lineHeight: 30,
    fontWeight: '300',
    color: colors.action,
  },
  addLabel: {
    ...typography.caption,
    fontWeight: '600',
    color: colors.action,
  },
  dim: {
    opacity: 0.5,
  },
});
