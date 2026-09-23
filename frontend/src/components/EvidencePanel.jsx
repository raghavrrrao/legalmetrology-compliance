import {
  boundingBoxToPercentages,
  sortFindingsForDisplay,
  toneForFindingStatus,
} from '../utils/compliance.js';
import { findingImageId } from '../utils/images.js';

/**
 * The photographs, with each finding's evidence marked on the one it came from.
 *
 * The Figma "Evidence Source" panel: the uploaded images with numbered markers
 * and outlines over the regions the findings were read from. The numbers match
 * the ones on the finding cards, because both derive from
 * `sortFindingsForDisplay` over the same array.
 *
 * Three facts shape this component:
 *
 * **The images come from the browser, not the API.** `ProductImageSerializer`
 * exposes the measured facts about a stored photograph - format, dimensions,
 * size, status - and no URL; there is no endpoint that serves the bytes back.
 * So the caller passes object URLs for the `File`s the user selected, in
 * submission order, and this draws boxes over them using each stored image's
 * `width`/`height` as the coordinate space, which is exactly the space
 * `bounding_box` is expressed in. On a screen with no local files - a result
 * opened from a link - there is nothing to show and the empty state says so
 * rather than implying the photographs were lost.
 *
 * **Coordinates are never invented.** A finding with no `bounding_box` gets no
 * marker; a box that is not four finite positive numbers gets no marker. The
 * finding still appears in the list with its excerpt. A drawn rectangle is a
 * claim about where on the package something was read, and a guessed one would
 * be a false claim.
 *
 * **Nor is the photograph a box belongs to.** An inspection may carry several,
 * and a region measured on the back panel drawn over the front one would point
 * a reviewer at the wrong part of the package - which is worse than pointing at
 * nothing, because it looks authoritative. So each box is placed on the
 * photograph `findingImageId` resolves, and a finding whose photograph cannot
 * be resolved is drawn on none of them. With a single photograph there is
 * nothing to resolve and every box lands on it, exactly as before.
 */
export function EvidencePanel({
  imageUrl,
  imageUrls,
  image,
  images,
  findings,
  // Where the attribution actually lives: the backend records which photograph
  // a piece of evidence came from on the violation, and which photograph a
  // declaration was read from on the reading. `findingImageId` consults both.
  violations = [],
  fieldsRead = [],
}) {
  const ordered = sortFindingsForDisplay(findings ?? []);

  // The photographs to draw on, paired with their local preview. Falls back to
  // the single `image`/`imageUrl` pair, which is what a result page opened from
  // a link and a backend without image sets both provide.
  const urls = Array.isArray(imageUrls) && imageUrls.length > 0
    ? imageUrls
    : [imageUrl];
  const panels = (
    Array.isArray(images) && images.length > 0
      ? images
      : image
        ? [{ position: 1, image }]
        : []
  ).map((entry, index) => ({
    position: entry.position ?? index + 1,
    image: entry.image,
    url: urls[index] ?? null,
  }));

  const single = panels.length <= 1;

  const boxes = ordered
    .map((finding, index) => ({
      finding,
      index,
      // Only asked when there is more than one photograph to choose between.
      // With one, every box belongs to it - there is no other candidate, and
      // an id comparison there would be a way to lose a marker over a
      // photograph whose id the response happened not to carry.
      imageId: single ? null : findingImageId(finding, violations, fieldsRead),
      boundingBox: finding.boundingBox,
    }))
    .filter((entry) => entry.boundingBox);

  const withUrl = panels.filter((panel) => panel.url);
  if (withUrl.length === 0) {
    return (
      <div className="empty-state">
        <p>
          The {panels.length > 1 ? 'photographs are' : 'photograph is'} not
          available on this device. The API stores what was measured from{' '}
          {panels.length > 1 ? 'each image' : 'the image'} — its format,
          dimensions and size — but does not serve the picture back, so it can
          only be shown on the screen it was uploaded from.
        </p>
      </div>
    );
  }

  /** Boxes that will actually be drawn: attributed to a photograph we can show. */
  const placed = single
    ? boxes.length
    : boxes.filter((box) =>
        panels.some(
          (panel) => box.imageId && panel.image?.id === box.imageId && panel.url,
        ),
      ).length;

  return (
    <div className="evidence-figures">
      {panels
        .filter((panel) => panel.url)
        .map((panel) => {
          const mine = boxes
            .filter(
              (box) =>
                single || (box.imageId && box.imageId === panel.image?.id),
            )
            .map((box) => ({
              ...box,
              position: boundingBoxToPercentages(
                box.boundingBox,
                panel.image?.width,
                panel.image?.height,
              ),
            }))
            .filter((box) => box.position !== null);

          return (
            <figure className="evidence-figure" key={panel.image?.id ?? panel.position}>
              {!single && (
                <figcaption className="evidence-figure__label">
                  {`Image ${panel.position}`}
                </figcaption>
              )}
              <div className="evidence-stage">
                {/*
                  The alt text describes the photograph's role, not its
                  contents: what it shows is precisely what the system has not
                  established.
                */}
                <img
                  src={panel.url}
                  alt={
                    single
                      ? 'The uploaded package label, with evidence regions outlined'
                      : `Package photo ${panel.position}, with evidence regions outlined`
                  }
                />

                {mine.map((box) => {
                  const tone = toneForFindingStatus(box.finding.status);
                  return (
                    <span
                      key={box.finding.id}
                      className={`evidence-box evidence-box--${tone}`}
                      style={box.position}
                    >
                      <span className="evidence-box__marker">
                        {String(box.index + 1).padStart(2, '0')}
                      </span>
                    </span>
                  );
                })}
              </div>
            </figure>
          );
        })}

      <p className="hint">
        {boxes.length === 0
          ? 'No finding recorded a location on the image, so nothing is outlined. The excerpts behind each finding are shown with it below.'
          : single
            ? `${placed} of ${ordered.length} findings recorded a location on the image. Numbers match the findings below.`
            : // With several photographs a box is drawn only where the server
              // said which one it came from, so the sentence says so rather
              // than implying the rest recorded nothing.
              `${placed} of ${ordered.length} findings recorded a location the server attributed to one of these photos. Numbers match the findings below.`}
      </p>
    </div>
  );
}
