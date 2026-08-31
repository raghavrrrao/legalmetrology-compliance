import {
  boundingBoxToPercentages,
  sortFindingsForDisplay,
  toneForFindingStatus,
} from '../utils/compliance.js';

/**
 * The photograph, with each finding's evidence marked on it.
 *
 * The Figma "Evidence Source" panel: the uploaded image with numbered markers
 * and outlines over the regions the findings were read from. The numbers match
 * the ones on the finding cards, because both derive from
 * `sortFindingsForDisplay` over the same array.
 *
 * Two facts shape this component:
 *
 * **The image comes from the browser, not the API.** `ProductImageSerializer`
 * exposes the measured facts about a stored photograph - format, dimensions,
 * size, status - and no URL; there is no endpoint that serves the bytes back.
 * So the caller passes an object URL for the `File` the user selected, and this
 * draws boxes over it using `image.width`/`image.height` as the coordinate
 * space, which is exactly the space `bounding_box` is expressed in. On a screen
 * with no local file - a result opened from a link - there is nothing to show
 * and the empty state says so rather than implying the photograph was lost.
 *
 * **Coordinates are never invented.** A finding with no `bounding_box` gets no
 * marker; a box that is not four finite positive numbers gets no marker. The
 * finding still appears in the list with its excerpt. A drawn rectangle is a
 * claim about where on the package something was read, and a guessed one would
 * be a false claim.
 */
export function EvidencePanel({ imageUrl, image, findings }) {
  const ordered = sortFindingsForDisplay(findings ?? []);

  const boxes = ordered
    .map((finding, index) => ({
      finding,
      index,
      position: boundingBoxToPercentages(
        finding.boundingBox,
        image?.width,
        image?.height,
      ),
    }))
    .filter((entry) => entry.position !== null);

  if (!imageUrl) {
    return (
      <div className="empty-state">
        <p>
          The photograph is not available on this device. The API stores what
          was measured from the image — its format, dimensions and size — but
          does not serve the picture back, so it can only be shown on the
          screen it was uploaded from.
        </p>
      </div>
    );
  }

  return (
    <figure className="evidence-figure">
      <div className="evidence-stage">
        {/*
          The alt text describes the photograph's role, not its contents: what
          it shows is precisely what the system has not established.
        */}
        <img
          src={imageUrl}
          alt="The uploaded package label, with evidence regions outlined"
        />

        {boxes.map(({ finding, index, position }) => {
          const tone = toneForFindingStatus(finding.status);
          return (
            <span
              key={finding.id}
              className={`evidence-box evidence-box--${tone}`}
              style={position}
            >
              <span className="evidence-box__marker">
                {String(index + 1).padStart(2, '0')}
              </span>
            </span>
          );
        })}
      </div>

      <figcaption className="hint">
        {boxes.length === 0
          ? 'No finding recorded a location on the image, so nothing is outlined. The excerpts behind each finding are shown with it below.'
          : `${boxes.length} of ${ordered.length} findings recorded a location on the image. Numbers match the findings below.`}
      </figcaption>
    </figure>
  );
}
