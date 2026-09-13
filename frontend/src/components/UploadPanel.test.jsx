/**
 * The upload panel: the one control the whole flow depends on.
 *
 * These assert behaviour, not appearance. What matters is that the file input
 * keeps exactly one accessible name, that choosing a file reports it upward,
 * that the chosen state shows the user what they actually picked, and that
 * Replace and Remove both remain reachable — a user who cannot undo a wrong
 * photograph has to reload the page to start again.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { UploadPanel } from './UploadPanel.jsx';

function healthy(overrides = {}) {
  return {
    extractionEngine: {
      name: 'tesseract',
      version: '0.3.0',
      isPlaceholder: false,
      ...overrides,
    },
    complianceRules: { verified: 11, unverified: 0 },
  };
}

function renderPanel(props = {}) {
  const onFileSelected = vi.fn();
  const onClear = vi.fn();
  const utils = render(
    <UploadPanel
      file={null}
      previewUrl={null}
      health={healthy()}
      disabled={false}
      onFileSelected={onFileSelected}
      onClear={onClear}
      {...props}
    />,
  );
  return { ...utils, onFileSelected, onClear };
}

const pngFile = () =>
  new File(['bytes'], 'label.png', { type: 'image/png' });

describe('before a photo is chosen', () => {
  it('says what to upload, and in what formats', () => {
    renderPanel();

    expect(
      screen.getByRole('heading', { name: /upload a product label image/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/drag and drop/i)).toBeInTheDocument();
    expect(screen.getByText(/JPG · PNG · WebP/)).toBeInTheDocument();
  });

  it('gives the file input exactly one accessible name', () => {
    renderPanel();

    // Two <label>s pointing at the same input make `getByLabelText` ambiguous
    // and give a screen reader two names for one control. There must be one.
    const inputs = screen.getAllByLabelText(/upload a product label image/i);
    expect(inputs).toHaveLength(1);
    expect(inputs[0]).toHaveAttribute('type', 'file');
  });

  it('reports the chosen file upward', () => {
    const { onFileSelected } = renderPanel();

    fireEvent.change(screen.getByLabelText(/upload a product label image/i), {
      target: { files: [pngFile()] },
    });

    expect(onFileSelected).toHaveBeenCalledTimes(1);
    expect(onFileSelected.mock.calls[0][0].name).toBe('label.png');
  });

  it('accepts a file dropped onto the panel', () => {
    const { onFileSelected } = renderPanel();
    const dropzone = screen
      .getByRole('heading', { name: /upload a product label image/i })
      .closest('label');

    fireEvent.drop(dropzone, { dataTransfer: { files: [pngFile()] } });

    expect(onFileSelected).toHaveBeenCalledTimes(1);
  });

  it('ignores a drop while the panel is disabled', () => {
    // Disabled means a request is in flight. Swapping the photograph under a
    // running analysis would leave the result describing a different image
    // than the one on screen.
    const { onFileSelected } = renderPanel({ disabled: true });
    const dropzone = screen
      .getByRole('heading', { name: /upload a product label image/i })
      .closest('label');

    fireEvent.drop(dropzone, { dataTransfer: { files: [pngFile()] } });

    expect(onFileSelected).not.toHaveBeenCalled();
  });
});

describe('once a photo is chosen', () => {
  it('shows the photograph, its name and its size', () => {
    renderPanel({ file: pngFile(), previewUrl: 'blob:preview' });

    const preview = screen.getByAltText(/label photo you selected/i);
    expect(preview).toHaveAttribute('src', 'blob:preview');
    expect(screen.getByText('label.png')).toBeInTheDocument();
    // The size in the user's units, from the real File, not a placeholder.
    expect(screen.getByText(/5 B/)).toBeInTheDocument();
    expect(screen.getByText(/PNG · supported/i)).toBeInTheDocument();
  });

  it('offers both Replace and Remove', () => {
    renderPanel({ file: pngFile(), previewUrl: 'blob:preview' });

    // Replace is a label over the same input, so it opens the picker without
    // any scripted click to go wrong.
    expect(screen.getByText('Replace')).toHaveAttribute('for', 'scan-image');
    expect(
      screen.getByRole('button', { name: /remove/i }),
    ).toBeInTheDocument();
  });

  it('clears the photograph when Remove is pressed', () => {
    const { onClear } = renderPanel({
      file: pngFile(),
      previewUrl: 'blob:preview',
    });

    fireEvent.click(screen.getByRole('button', { name: /remove/i }));

    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it('warns about a file type the API does not accept', () => {
    renderPanel({
      file: new File(['x'], 'scan.pdf', { type: 'application/pdf' }),
      previewUrl: null,
    });

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/cannot use that file/i);
    expect(alert).toHaveTextContent(/JPG, PNG or WebP/i);
  });
});

describe('what the panel will not claim', () => {
  it('says when no text reader is installed, rather than looking ready', () => {
    renderPanel({ health: healthy({ isPlaceholder: true }) });

    expect(
      screen.getByText(/no text reader is installed/i),
    ).toBeInTheDocument();
  });

  it('prints no maximum size, because the client does not know it', () => {
    renderPanel();

    // The limit is a backend environment variable that is not exposed here.
    // Printing a number the server does not enforce is worse than printing
    // none, so the copy defers to the server instead of naming a figure.
    expect(screen.getByText(/the server checks the size/i)).toBeInTheDocument();
    expect(screen.queryByText(/\d+\s?MB/i)).not.toBeInTheDocument();
  });
});
