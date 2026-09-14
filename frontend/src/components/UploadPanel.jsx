import { useRef, useState } from 'react';

import { formatFileSize } from '../utils/format.js';

/**
 * Step one: the photograph, and whether we can work with it.
 *
 * The hero of the scan screen. A visitor who reads nothing else must still see
 * one large target that says what to put in it, so this is the only element on
 * the page drawn at that weight — everything below it is a card.
 *
 * Drag-and-drop with a real `<input type="file">` behind a `<label>` rather
 * than a div pretending to be one: the input stays focusable and
 * keyboard-operable, the label is its accessible name and its click target,
 * and on a phone the same control opens the camera roll. There is no
 * JavaScript click-forwarding to go wrong.
 *
 * **The readiness checks are only what the browser can actually know.** Earlier
 * designs asked for "Image Quality & Resolution" and "OCR Readiness &
 * Lighting"; neither is something the frontend measures, and no endpoint
 * reports them, so inventing a verdict for either would put a check on screen
 * that checks nothing. What is shown instead is real: whether the chosen file's
 * type is one the API accepts, and whether a text reader is installed at all —
 * the second read from `/health/`, which is where that fact lives.
 *
 * Those checks used to be a dense technical list — engine names, versions, MIME
 * types — in front of a user who wanted to know one thing: can I press the
 * button yet. They are now one confirmation line, and the version strings live
 * under "Technical details" where somebody debugging a deployment can still
 * find them and nobody else has to read them.
 *
 * The maximum file size is deliberately not printed as a number. It is a
 * backend environment variable that is not exposed to the client, and printing
 * a number the server does not enforce would be worse than printing none; an
 * oversized upload is rejected by the API and its message is rendered.
 */
const ACCEPTED_TYPES = 'image/jpeg,image/png,image/webp';

export function UploadPanel({
  file,
  previewUrl,
  onFileSelected,
  onClear,
  health,
  disabled,
}) {
  const inputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);

  function selectFirst(fileList) {
    const chosen = fileList?.[0];
    if (chosen) {
      onFileSelected(chosen);
    }
  }

  function handleDrop(event) {
    event.preventDefault();
    setIsDragging(false);
    if (!disabled) {
      selectFirst(event.dataTransfer?.files);
    }
  }

  function handleClear() {
    if (inputRef.current) {
      inputRef.current.value = '';
    }
    onClear();
  }

  const typeAccepted = file ? ACCEPTED_TYPES.split(',').includes(file.type) : null;
  const engineInstalled = health
    ? health.extractionEngine.isPlaceholder === false
    : null;

  return (
    <section className="upload">
      {/*
        The input lives outside both branches so that replacing a photo never
        unmounts the control the user is operating.

        It carries no <label> of its own: exactly one label points at it at any
        moment - the dropzone before a photo is chosen, "Replace photo" after -
        so the control has one accessible name rather than two competing ones.
      */}
      <input
        id="scan-image"
        ref={inputRef}
        type="file"
        accept={ACCEPTED_TYPES}
        className="visually-hidden"
        disabled={disabled}
        onChange={(event) => selectFirst(event.target.files)}
      />

      {file ? (
        <div className="upload__chosen">
          <div className="upload__preview">
            {previewUrl && (
              <img
                className="upload__image"
                src={previewUrl}
                alt="The label photo you selected"
              />
            )}
          </div>

          <div className="upload__meta">
            <p className="upload__confirm">
              <CheckIcon />
              Photo ready to check
            </p>
            <p className="upload__filename">{file.name}</p>
            <dl className="upload__facts">
              <dt>Size</dt>
              <dd>{formatFileSize(file.size)}</dd>
              <dt>Format</dt>
              <dd>
                {typeAccepted
                  ? `${formatName(file.type)} · supported`
                  : formatName(file.type)}
              </dd>
            </dl>

            <div className="upload__actions">
              <label htmlFor="scan-image" className="button">
                Replace
              </label>
              <button
                type="button"
                className="button button--quiet"
                onClick={handleClear}
                disabled={disabled}
              >
                Remove
              </button>
            </div>
          </div>
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

            <h2 className="upload__title">Upload a product label image</h2>
            <p className="upload__text">
              Drag and drop, or choose an image
            </p>
            <span className="upload__button button button--primary">
              Choose an image
            </span>
            <p className="upload__formats">
              JPG · PNG · WebP — the server checks the size and rejects an
              oversized file
            </p>
          </span>
        </label>
      )}

      {typeAccepted === false && (
        <p className="callout callout--warning" role="alert">
          <strong>We cannot use that file.</strong> Please choose a JPG, PNG or
          WebP image.
        </p>
      )}

      {engineInstalled === false && (
        <p className="callout callout--warning">
          <strong>No text reader is installed on this server.</strong> No text
          will be read from the photo, so nothing here would be a real reading.
        </p>
      )}

      <details className="technical-details">
        <summary>Technical details</summary>
        <dl className="detail-list">
          <dt>Accepted formats</dt>
          <dd>JPEG, PNG, WebP</dd>
          <dt>Maximum size</dt>
          <dd>Enforced by the server, which rejects an oversized upload.</dd>
          {file && (
            <>
              <dt>Reported type</dt>
              <dd>
                <code>{file.type || 'not reported by the browser'}</code>
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

/**
 * A MIME type as the word a person uses for it.
 *
 * Falls back to the raw type, and then to a plain statement that the browser
 * reported none - which is a real state for a file dragged out of some tools,
 * and is not the same thing as an unsupported one.
 */
function formatName(mimeType) {
  const names = {
    'image/jpeg': 'JPG',
    'image/png': 'PNG',
    'image/webp': 'WebP',
  };
  return names[mimeType] ?? mimeType ?? 'type not reported';
}
