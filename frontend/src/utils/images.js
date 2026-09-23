/**
 * Naming the photograph a piece of evidence came from.
 *
 * One place, so the label on a violation, the one on a read declaration and the
 * one over an evidence figure all mean the same photograph. A number that moved
 * between sections would be worse than no number at all.
 *
 * The number is the backend's `position`, never an array index. They agree
 * today, and the moment they stop agreeing - a backend that omits a photograph,
 * a client that filters one - the index would quietly start pointing at the
 * wrong panel.
 */

/**
 * Position by stored image id.
 *
 * @param {{position: number, image: {id: string}}[]} images
 * @returns {Map<string, number>}
 */
export function imagePositions(images) {
  return new Map((images ?? []).map((entry) => [entry.image.id, entry.position]));
}

/**
 * "Image 2" for a stored image id, or null when it cannot be named.
 *
 * Null in four real cases, and all four mean the same thing to the interface:
 * **say nothing about which photograph**.
 *
 * - the backend recorded no source for this evidence (an older server, or an
 *   image row since deleted) — null there is "not stated", never "no
 *   photograph was involved";
 * - the id names no photograph in this result;
 * - there is only one photograph, where "Image 1" is noise rather than
 *   information;
 * - nothing was passed at all.
 *
 * Never a guess. Labelling evidence with a photograph the backend did not
 * attribute it to would be the interface inventing a claim about where a
 * declaration appears on a package.
 *
 * @param {string|null|undefined} imageId
 * @param {Map<string, number>} positions
 * @returns {string|null}
 */
export function imageLabel(imageId, positions) {
  if (!imageId || !positions || positions.size < 2) {
    return null;
  }
  const position = positions.get(imageId);
  return position === undefined ? null : `Image ${position}`;
}

/**
 * Which photograph a finding's evidence came from, as a stored image id.
 *
 * Findings carry no image of their own. The backend attributes evidence on the
 * **violation** a finding became, so that is the first and authoritative
 * source. Where a finding became no violation - a pass, an inconclusive
 * outcome, a downgraded failure - there is no evidence row, and the second
 * source is the reading itself: `fields_read` entries carry their own
 * `image_id`, and a finding's excerpt and bounding box were snapshotted from
 * one of them.
 *
 * That second step resolves **only when it is unambiguous**. A declaration
 * printed on two photographed panels produces two readings with the same
 * `fieldKey`, and the engine picked one by a rule this layer does not
 * reimplement - so where two could match, the answer is null and nothing is
 * named. Guessing would put a wrong panel next to a finding, which is worse
 * than putting none: it looks authoritative.
 *
 * @param {object} finding
 * @param {object[]} violations
 * @param {object[]} fieldsRead
 * @returns {string|null}
 */
export function findingImageId(finding, violations, fieldsRead) {
  if (!finding) {
    return null;
  }

  if (finding.violationId !== null && finding.violationId !== undefined) {
    const violation = (violations ?? []).find(
      (candidate) => candidate.id === finding.violationId,
    );
    const attributed = violation?.evidence?.find((item) => item.imageId);
    if (attributed) {
      return attributed.imageId;
    }
  }

  if (!finding.fieldKey) {
    return null;
  }
  const matching = (fieldsRead ?? []).filter(
    (field) => field.fieldKey === finding.fieldKey && field.imageId,
  );
  return matching.length === 1 ? matching[0].imageId : null;
}
