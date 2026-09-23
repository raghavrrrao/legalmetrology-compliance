import { useRef, useState } from 'react';

import { ACCEPT_ATTRIBUTE } from '../hooks/useSelectedImages.js';
import { MAX_INSPECTION_IMAGES } from '../config/env.js';
import { formatFileSize } from '../utils/format.js';

/**
 * Step one: the photographs, and whether we can work with them.
 *
 * The hero of the scan screen. A visitor who reads nothing else must still see
 * one large target that says what to put in it, so this is the only element on
 * the page drawn at that weight — everything below it is a card.
 *
 * **One inspection, several photographs.** A packaged commodity declares
 * different things on different panels — the net quantity on the back, the
 * price on a side, a batch number in small print — so this panel gathers a
 * *set*. Adding the back of a package continues the same inspection; it never
 * starts a second one. The backend reads the whole set into one reading and
 * returns one verdict, which is the only way a claim about a *package* can be
 * reached when its declarations are spread across panels.
 *
 * Drag-and-drop with a real `<input type="file">` behind a `<label>` rather
 * than a div pretending to be one: the input stays focusable and
 * keyboard-operable, the label is its accessible name and its click target,
 * and on a phone the same control opens the camera roll. There is no
 * JavaScript click-forwarding to go wrong, and **drag-and-drop is never the
 * only way in** — the same label is a button for anyone using a keyboard.
 *
 * **The readiness checks are only what the browser can actually know.** Earlier
 * designs asked for "Image Quality & Resolution" and "OCR Readiness &
 * Lighting"; neither is something the frontend measures, and no endpoint
 * reports them, so inventing a verdict for either would put a check on screen
 * that checks nothing. What is shown instead is real: whether each chosen
 * file's type is one the API accepts, whether the browser could decode it at
 * all, and whether a text reader is installed — the last read from `/health/`,
 * which is where that fact lives.
 *
 * The maximum file size is deliberately not printed as a number. It is a
 * backend environment variable that is not exposed to the client, and printing
 * a number the server does not enforce would be worse than printing none; an
 * oversized upload is rejected by the API and its message is rendered, with the
 * rest of the set still selected.
 *
 * **Which panel each photograph shows is stated per photograph**, on the
 * thumbnail, because the API reads `view_type` positionally — one value for a
 * set of six would record a claim about five photographs that nobody made.
 * That control used to live in "Package details" as a single select, which was
 * unambiguous only while an inspection could hold one photograph.
 */
const VIEW_TYPES = [
  ['unspecified', 'Not specified'],
  ['front', 'Front panel'],
  ['back', 'Back panel'],
  ['principal_display', 'Principal display panel'],
  ['label', 'Label close-up'],
  ['other', 'Other'],
];

export function UploadPanel({
  entries,
  rejections,
  canAddMore,
  remaining,
  onFilesSelected,
  onRemove,
  onViewTypeChange,
  onDecodeFailed,
  onDismissRejections,
  health,
  disabled,
}) {
  const inputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);

  const count = entries.length;

  function take(fileList) {
    const files = Array.from(fileList ?? []);
    if (files.length > 0) {
      onFilesSelected(files);
    }
    // Cleared so choosing the same file again still fires a change event.
    // Without this, removing a photo and re-picking it does nothing at all.
    if (inputRef.current) {
      inputRef.current.value = '';
    }
  }

  function handleDrop(event) {
    event.preventDefault();
    setIsDragging(false);
    if (!disabled) {
      take(event.dataTransfer?.files);
    }
  }

  const engineInstalled = health
    ? health.extractionEngine.isPlaceholder === false
    : null;

  return (
    <section className="upload">
      {/*
        The input lives outside both branches so that adding a photo never
        unmounts the control the user is operating.

        It carries no <label> of its own: exactly one label points at it at any
        moment - the dropzone while the set is empty, "Add photos" after - so
        the control has one accessible name rather than two competing ones.
      */}
      <input
        id="scan-image"
        ref={inputRef}
        type="file"
        accept={ACCEPT_ATTRIBUTE}
        multiple
        className="visually-hidden"
        disabled={disabled || !canAddMore}
        onChange={(event) => take(event.target.files)}
      />

      {count > 0 ? (
        <div className="upload__set">
          <div className="upload__set-head">
            <p className="upload__confirm">
              <CheckIcon />
              {count === 1 ? '1 photo selected' : `${count} photos selected`}
            </p>
            <p className="upload__set-note">
              {canAddMore
                ? 'All of these are checked together, as one package.'
                : `That is the maximum of ${MAX_INSPECTION_IMAGES}. Remove one to add another.`}
            </p>
          </div>

          <ul className="upload__thumbs">
            {entries.map((entry, index) => (
              <li className="upload__thumb" key={entry.id}>
                <div className="upload__thumb-frame">
                  <img
                    className="upload__thumb-image"
                    src={entry.previewUrl}
                    // The position, not a description: this client has not
                    // looked at the photograph and must not claim to know what
                    // it shows.
                    alt={`Photo ${index + 1} of ${count}`}
                    onError={() => onDecodeFailed(entry.id)}
                  />
                  <span className="upload__thumb-index" aria-hidden="true">
                    {index + 1}
                  </span>
                  <button
                    type="button"
                    className="upload__thumb-remove"
                    aria-label={`Remove image ${index + 1}`}
                    disabled={disabled}
                    onClick={() => onRemove(entry.id)}
                  >
                    <span aria-hidden="true">×</span>
                  </button>
                </div>

                <p className="upload__thumb-name" title={entry.file.name}>
                  {entry.file.name}
                </p>
                <p className="upload__thumb-size">
                  {formatFileSize(entry.file.size)}
                </p>

                {entry.decodeFailed && (
                  <p className="upload__thumb-warning" role="alert">
                    This file could not be opened as an image. The server will
                    reject it.
                  </p>
                )}

                {/*
                  Per photograph, because `view_type` is positional on the API.
                  The label names the image so a screen reader reaching the
                  fourth select knows which photograph it is about.
                */}
                <label
                  className="visually-hidden"
                  htmlFor={`view-type-${entry.id}`}
                >
                  {`Which part of the package is image ${index + 1}?`}
                </label>
                <select
                  id={`view-type-${entry.id}`}
                  className="upload__thumb-view"
                  value={entry.viewType}
                  disabled={disabled}
                  onChange={(event) =>
                    onViewTypeChange(entry.id, event.target.value)
                  }
                >
                  {VIEW_TYPES.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </li>
            ))}

            {/*
              The add tile sits at the end of the row, in the same rhythm as the
              thumbnails, so adding more reads as continuing the set rather than
              as starting again. It is a <label> for the same input, so it is
              reachable by keyboard and needs no click forwarding.

              It stays rendered when the set is full, dimmed and saying so,
              rather than disappearing. Two reasons: a control that vanishes is
              harder to understand than one that explains itself, and this
              label is the input's accessible name - removing it would leave a
              nameless file input on the page for anyone tabbing to it.
              Activating it does nothing, because the input itself is disabled.
            */}
            <li
              className={`upload__thumb upload__thumb--add${
                canAddMore ? '' : ' upload__thumb--full'
              }`}
            >
              <label
                htmlFor="scan-image"
                className="upload__add"
                aria-disabled={!canAddMore}
              >
                <span className="upload__add-glyph" aria-hidden="true">
                  {canAddMore ? '+' : '✓'}
                </span>
                <span className="upload__add-label">
                  {canAddMore ? 'Add photos' : 'All 6 added'}
                </span>
                <span className="visually-hidden">
                  {canAddMore
                    ? `${remaining} more can be added`
                    : 'Remove one to add another'}
                </span>
              </label>
            </li>
          </ul>

          <p className="upload__set-panels">
            Not sure which panel a photo shows? Leave it as{' '}
            <strong>Not specified</strong>. A declaration that is not in any
            photograph has not been shown to be missing from the package.
          </p>
        </div>
      ) : (
        <label
          htmlFor="scan-image"
          className={`upload__dropzone${isDragging ? ' upload__dropzone--active' : ''}`}
          onDragOver={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
        >
          {/*
            A faint technical grid behind the panel, masked to fade out at the
            edges. Drawn with two repeating-linear-gradients rather than 451
            elements or an image: it costs one painted layer, it scales to any
            panel size, and it needs no library. Purely decorative, so it is
            aria-hidden and sits behind the content.
          */}
          <span className="upload__grid" aria-hidden="true" />

          <span className="upload__inner">
            {/*
              Inline SVG rather than a glyph: the icon characters in the design
              are not in every system font, and a missing one renders as a tofu
              box on the most prominent element of the screen.
            */}
            <span className="upload__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="26" height="26" fill="none">
                <rect
                  x="3"
                  y="5"
                  width="18"
                  height="14"
                  rx="2.5"
                  stroke="currentColor"
                  strokeWidth="1.6"
                />
                <path
                  d="M3 16.2l4.6-4.1 3.8 3.3 3.1-2.6L21 16.6"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <circle cx="8.8" cy="9.6" r="1.4" fill="currentColor" />
              </svg>
            </span>

            <h2 className="upload__title">Upload package photos</h2>
            <p className="upload__text">
              Add the front, the back, and any panels containing declarations.
              They are checked together, as one package.
            </p>
            <span className="upload__button button button--primary">
              Add photos
            </span>
            <p className="upload__formats">
              Drag and drop, or choose up to {MAX_INSPECTION_IMAGES} images ·
              JPG · PNG · WebP — the server checks the size and rejects an
              oversized file
            </p>
          </span>
        </label>
      )}

      {rejections.length > 0 && (
        <div className="callout callout--warning" role="alert">
          <p>
            <strong>
              {rejections.length === 1
                ? 'One thing was not added.'
                : 'Some files were not added.'}
            </strong>
          </p>
          <ul className="upload__rejections">
            {rejections.map((rejection) => (
              <li key={rejection.kind}>{describeRejection(rejection)}</li>
            ))}
          </ul>
          <button
            type="button"
            className="button button--quiet"
            onClick={onDismissRejections}
          >
            Dismiss
          </button>
        </div>
      )}

      {engineInstalled === false && (
        <p className="callout callout--warning">
          <strong>No text reader is installed on this server.</strong> No text
          will be read from the photos, so nothing here would be a real reading.
        </p>
      )}

      <details className="technical-details">
        <summary>Technical details</summary>
        <dl className="detail-list">
          <dt>Accepted formats</dt>
          <dd>JPEG, PNG, WebP</dd>
          <dt>Photos per inspection</dt>
          <dd>
            Up to {MAX_INSPECTION_IMAGES}, sent as one request and read into one
            inspection.
          </dd>
          <dt>Maximum size</dt>
          <dd>Enforced by the server, which rejects an oversized upload.</dd>
          {count > 0 && (
            <>
              <dt>Reported types</dt>
              <dd>
                {entries
                  .map((entry) => entry.file.type || 'not reported')
                  .join(', ')}
              </dd>
            </>
          )}
          <dt>Text reader</dt>
          <dd>
            {health?.extractionEngine?.name
              ? `${health.extractionEngine.name} ${health.extractionEngine.version ?? ''}`.trim()
              : 'Backend health has not been read yet.'}
          </dd>
          {health?.complianceRules && (
            <>
              <dt>Loaded rules</dt>
              <dd>
                {health.complianceRules.verified} verified,{' '}
                {health.complianceRules.unverified} unverified. Only a verified
                rule can report a package as non-compliant.
              </dd>
            </>
          )}
        </dl>
      </details>
    </section>
  );
}

/**
 * Why some files were refused, in the user's words.
 *
 * Each kind names the files it concerns, because "a file was not added" in
 * front of a selection of six is not something anybody can act on. Nothing is
 * discarded silently: every refusal reaches this list.
 */
export function describeRejection({ kind, files }) {
  const named = files.join(', ');
  switch (kind) {
    case 'unsupported':
      return `${named} — not a JPG, PNG or WebP image, which are the formats the server reads.`;
    case 'empty':
      return `${named} — the file is empty.`;
    case 'duplicate':
      return `${named} — ${files.length === 1 ? 'is' : 'are'} already in this inspection.`;
    case 'overflow':
      return `${named} — up to ${MAX_INSPECTION_IMAGES} images can be checked together. Remove one to make room.`;
    default:
      return named;
  }
}

/** A tick, drawn rather than typed, so it cannot render as a tofu box. */
function CheckIcon() {
  return (
    <span className="upload__confirm-mark" aria-hidden="true">
      <svg viewBox="0 0 16 16" width="11" height="11" fill="none">
        <path
          d="m3.5 8.5 3 3 6-7"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}
