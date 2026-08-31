import { useRef, useState } from 'react';

import { StatusBadge } from './StatusBadge.jsx';
import { formatFileSize } from '../utils/format.js';

/**
 * The Figma "Inspection Workspace" dropzone and its pre-flight checks.
 *
 * Drag-and-drop with a real `<input type="file">` behind it rather than a
 * div pretending to be one: the input stays focusable and keyboard-operable,
 * and the label remains its accessible name.
 *
 * **The pre-flight checks are only what the browser can actually know.** The
 * Figma shows "Image Quality & Resolution" and "OCR Readiness & Lighting";
 * neither is something the frontend measures, and no endpoint reports them, so
 * inventing a verdict for either would put a check on screen that checks
 * nothing. What is shown instead is real: whether a file has been chosen,
 * whether its type is one the API accepts, and whether an OCR engine is
 * installed at all - the last read from `/health/`, which is where that fact
 * lives.
 *
 * The Figma's "Max 25MB/file" caption is likewise absent. The limit is a
 * backend environment variable that is not exposed to the client, and printing
 * a number the server does not enforce would be worse than printing none; an
 * oversized upload is rejected by the API and its message is rendered.
 */
const ACCEPTED_TYPES = 'image/jpeg,image/png,image/webp';

export function UploadPanel({ file, onFileSelected, onClear, health, disabled }) {
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
  const engineInstalled = health ? health.extractionEngine.isPlaceholder === false : null;

  return (
    <>
      <div className="card">
        <div className="card__header">
          <h2 className="card__title">Inspection workspace</h2>
          {health?.complianceRules && (
            <StatusBadge
              value="ruleset"
              tone={health.complianceRules.verified > 0 ? 'success' : 'warning'}
              label={
                health.complianceRules.verified > 0
                  ? 'Ruleset loaded'
                  : 'No verified rules'
              }
            />
          )}
        </div>

        <div className="card__body">
          <div
            className={`dropzone${isDragging ? ' dropzone--active' : ''}`}
            onDragOver={(event) => {
              event.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
          >
            {/*
              Inline SVG rather than a glyph: the icon characters in the design
              are not in every system font, and a missing one renders as a
              tofu box on the most prominent element of the screen.
            */}
            <svg
              className="dropzone__icon"
              viewBox="0 0 24 24"
              width="32"
              height="32"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              aria-hidden="true"
            >
              <rect x="3" y="4" width="18" height="14" rx="2" />
              <circle cx="9" cy="9.5" r="1.5" />
              <path d="m4 15 4.5-4 4 3.5L16 11l4 4" />
            </svg>
            <h3 className="dropzone__title">Check a packaged product</h3>
            <p className="dropzone__text">
              Drag and drop a high-resolution photograph of the front, back or
              side panel here. Make sure the mandatory declarations are visible
              and in focus.
            </p>

            <div className="dropzone__actions field">
              <label htmlFor="scan-image" className="visually-hidden">
                Label photograph
              </label>
              <input
                id="scan-image"
                ref={inputRef}
                type="file"
                accept={ACCEPTED_TYPES}
                disabled={disabled}
                onChange={(event) => selectFirst(event.target.files)}
              />
            </div>
          </div>

          {file && (
            <div className="file-summary">
              <span className="file-summary__name">{file.name}</span>
              <span className="file-summary__size">
                {formatFileSize(file.size)}
              </span>
              <button
                type="button"
                className="button--link"
                onClick={handleClear}
                disabled={disabled}
              >
                Remove
              </button>
            </div>
          )}
        </div>

        <div className="card__footer">
          <span>Accepted: JPEG, PNG, WebP</span>
          <span>The server enforces the maximum file size.</span>
        </div>
      </div>

      <div className="card">
        <div className="card__header">
          <h3 className="card__title">Pre-flight checks</h3>
        </div>
        <div className="card__body">
          <PreflightRow
            label="Product imagery"
            detail={
              file
                ? `${file.name} selected`
                : 'Choose a photograph to begin.'
            }
            state={file ? 'ready' : 'awaiting'}
          />
          <PreflightRow
            label="File type"
            detail={
              typeAccepted === null
                ? 'Checked once a file is chosen.'
                : typeAccepted
                  ? `${file.type} is accepted by the API.`
                  : `${file.type || 'This file type'} is outside the accepted list; the server will reject it.`
            }
            state={
              typeAccepted === null
                ? 'awaiting'
                : typeAccepted
                  ? 'ready'
                  : 'blocked'
            }
          />
          <PreflightRow
            label="Extraction engine"
            detail={
              engineInstalled === null
                ? 'Backend health has not been read.'
                : engineInstalled
                  ? `${health.extractionEngine.name} ${health.extractionEngine.version} is installed.`
                  : 'No OCR engine is installed — the pipeline will read no text from this image.'
            }
            state={
              engineInstalled === null
                ? 'awaiting'
                : engineInstalled
                  ? 'ready'
                  : 'blocked'
            }
          />
        </div>
      </div>
    </>
  );
}

const PREFLIGHT_TONE = { ready: 'success', awaiting: 'neutral', blocked: 'warning' };
const PREFLIGHT_LABEL = { ready: 'Ready', awaiting: 'Awaiting', blocked: 'Attention' };

function PreflightRow({ label, detail, state }) {
  return (
    <div className="check-row">
      <span className="check-row__label">
        {label}
        <span className="check-row__detail">{detail}</span>
      </span>
      <StatusBadge
        value={state}
        tone={PREFLIGHT_TONE[state]}
        label={PREFLIGHT_LABEL[state]}
      />
    </div>
  );
}
