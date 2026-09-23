/**
 * The upload panel: the one control the whole flow depends on.
 *
 * These assert behaviour, not appearance. What matters is that the file input
 * keeps exactly one accessible name, that choosing files reports them upward,
 * that every photograph in the set can be seen and individually removed, and
 * that nothing a user chose is silently discarded.
 *
 * The panel is presentational: `useSelectedImages` owns the set and decides
 * what may join it, and has its own tests. What is checked here is that the
 * panel renders the state it is given and reports every intention back.
 */

import { fireEvent, render, screen, within } from '@testing-library/react';
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

const pngFile = (name = 'label.png') =>
  new File(['bytes'], name, { type: 'image/png' });

/** One entry as `useSelectedImages` shapes it. */
function entry(index, overrides = {}) {
  return {
    id: `image-${index}`,
    file: pngFile(`panel-${index}.png`),
    previewUrl: `blob:preview-${index}`,
    viewType: 'unspecified',
    decodeFailed: false,
    ...overrides,
  };
}

function entries(count) {
  return Array.from({ length: count }, (_value, index) => entry(index + 1));
}

function renderPanel(props = {}) {
  const handlers = {
    onFilesSelected: vi.fn(),
    onRemove: vi.fn(),
    onViewTypeChange: vi.fn(),
    onDecodeFailed: vi.fn(),
    onDismissRejections: vi.fn(),
  };
  const utils = render(
    <UploadPanel
      entries={[]}
      rejections={[]}
      canAddMore
      remaining={6}
      health={healthy()}
      disabled={false}
      {...handlers}
      {...props}
    />,
  );
  return { ...utils, ...handlers };
}

describe('before any photo is chosen', () => {
  it('asks for the photos of a package, and says they are checked together', () => {
    renderPanel();

    expect(
      screen.getByRole('heading', { name: /upload package photos/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/add the front, the back, and any panels/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/checked together, as one package/i)).toBeInTheDocument();
    expect(screen.getByText(/JPG · PNG · WebP/)).toBeInTheDocument();
  });

  it('does not claim every panel is required', () => {
    renderPanel();

    // "Add the front, the back, and any panels containing declarations" is an
    // invitation. A user with one photograph must not read it as a refusal.
    expect(screen.queryByText(/must (upload|add|provide)/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/required/i)).not.toBeInTheDocument();
  });

  it('gives the file input exactly one accessible name', () => {
    renderPanel();

    // Two <label>s pointing at the same input make `getByLabelText` ambiguous
    // and give a screen reader two names for one control. There must be one.
    const inputs = screen.getAllByLabelText(/upload package photos/i);
    expect(inputs).toHaveLength(1);
    expect(inputs[0]).toHaveAttribute('type', 'file');
  });

  it('lets the picker return more than one file', () => {
    renderPanel();

    expect(screen.getByLabelText(/upload package photos/i)).toHaveAttribute(
      'multiple',
    );
  });

  it('reports one chosen file upward', () => {
    const { onFilesSelected } = renderPanel();

    fireEvent.change(screen.getByLabelText(/upload package photos/i), {
      target: { files: [pngFile()] },
    });

    expect(onFilesSelected).toHaveBeenCalledTimes(1);
    expect(onFilesSelected.mock.calls[0][0]).toHaveLength(1);
    expect(onFilesSelected.mock.calls[0][0][0].name).toBe('label.png');
  });

  it('reports every file of a multiple selection, in order', () => {
    const { onFilesSelected } = renderPanel();

    fireEvent.change(screen.getByLabelText(/upload package photos/i), {
      target: { files: [pngFile('front.png'), pngFile('back.png')] },
    });

    // One call carrying both - the order becomes the position each photograph
    // is submitted at.
    expect(onFilesSelected).toHaveBeenCalledTimes(1);
    expect(onFilesSelected.mock.calls[0][0].map((file) => file.name)).toEqual([
      'front.png',
      'back.png',
    ]);
  });

  it('accepts several files dropped onto the panel', () => {
    const { onFilesSelected } = renderPanel();
    const dropzone = screen
      .getByRole('heading', { name: /upload package photos/i })
      .closest('label');

    fireEvent.drop(dropzone, {
      dataTransfer: { files: [pngFile('a.png'), pngFile('b.png')] },
    });

    expect(onFilesSelected).toHaveBeenCalledTimes(1);
    expect(onFilesSelected.mock.calls[0][0]).toHaveLength(2);
  });

  it('ignores a drop while the panel is disabled', () => {
    // Disabled means a request is in flight. Changing the set under a running
    // analysis would leave the result describing different photographs than
    // the ones on screen.
    const { onFilesSelected } = renderPanel({ disabled: true });
    const dropzone = screen
      .getByRole('heading', { name: /upload package photos/i })
      .closest('label');

    fireEvent.drop(dropzone, { dataTransfer: { files: [pngFile()] } });

    expect(onFilesSelected).not.toHaveBeenCalled();
  });

  it('reports nothing when the picker is cancelled', () => {
    const { onFilesSelected } = renderPanel();

    // A cancelled picker fires change with an empty list. Not an error, and
    // not something to report upward as a selection.
    fireEvent.change(screen.getByLabelText(/upload package photos/i), {
      target: { files: [] },
    });

    expect(onFilesSelected).not.toHaveBeenCalled();
  });
});

describe('once photos are chosen', () => {
  it('shows a thumbnail for every photo, with its name and size', () => {
    renderPanel({ entries: entries(3) });

    expect(screen.getByAltText('Photo 1 of 3')).toHaveAttribute(
      'src',
      'blob:preview-1',
    );
    expect(screen.getByAltText('Photo 2 of 3')).toBeInTheDocument();
    expect(screen.getByAltText('Photo 3 of 3')).toBeInTheDocument();
    expect(screen.getByText('panel-1.png')).toBeInTheDocument();
    // The size in the user's units, from the real File, not a placeholder.
    expect(screen.getAllByText(/5 B/)).toHaveLength(3);
  });

  it('says how many photos are selected', () => {
    renderPanel({ entries: entries(3) });

    expect(screen.getByText('3 photos selected')).toBeInTheDocument();
  });

  it('says one photo in the singular', () => {
    renderPanel({ entries: entries(1) });

    expect(screen.getByText('1 photo selected')).toBeInTheDocument();
  });

  it('gives every remove control a name that identifies its photo', () => {
    renderPanel({ entries: entries(3) });

    // So a screen-reader user can remove the third photo without discovering
    // which one "remove" means by pressing it.
    expect(screen.getByRole('button', { name: 'Remove image 1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove image 2' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove image 3' })).toBeInTheDocument();
  });

  it('removes the photo whose control was pressed', () => {
    const set = entries(3);
    const { onRemove } = renderPanel({ entries: set });

    fireEvent.click(screen.getByRole('button', { name: 'Remove image 2' }));

    expect(onRemove).toHaveBeenCalledWith(set[1].id);
  });

  it('offers an add control that opens the same input', () => {
    renderPanel({ entries: entries(2) });

    // A <label> for the input rather than a scripted click, so it is reachable
    // by keyboard and cannot break.
    expect(screen.getByText('Add photos').closest('label')).toHaveAttribute(
      'for',
      'scan-image',
    );
  });

  it('says the set is full and stops accepting more', () => {
    renderPanel({ entries: entries(6), canAddMore: false, remaining: 0 });

    expect(screen.queryByText('Add photos')).not.toBeInTheDocument();
    expect(screen.getByText('All 6 added')).toBeInTheDocument();
    expect(screen.getByText(/maximum of 6/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/all 6 added/i)).toBeDisabled();
  });

  it('keeps the file input named, and named once, whatever the state', () => {
    // Exactly one <label> points at the input at any moment, and which one it
    // is changes with the state - the dropzone while empty, the add tile
    // after. Dropping the tile when the set was full would have left a
    // nameless file input on the page for anyone tabbing to it.
    const { rerender } = renderPanel({ entries: entries(2) });
    expect(screen.getAllByLabelText(/add photos/i)).toHaveLength(1);

    rerender(
      <UploadPanel
        entries={entries(6)}
        rejections={[]}
        canAddMore={false}
        remaining={0}
        health={healthy()}
        disabled={false}
        onFilesSelected={() => {}}
        onRemove={() => {}}
        onViewTypeChange={() => {}}
        onDecodeFailed={() => {}}
        onDismissRejections={() => {}}
      />,
    );
    expect(screen.getAllByLabelText(/all 6 added/i)).toHaveLength(1);
  });

  it('asks which panel each photo shows, naming the photo', () => {
    renderPanel({ entries: entries(2) });

    // Positional on the API, so it is stated per photograph - one global value
    // would record a claim about the other photographs that nobody made.
    expect(
      screen.getByLabelText('Which part of the package is image 1?'),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText('Which part of the package is image 2?'),
    ).toBeInTheDocument();
  });

  it('reports a panel choice against the photo it was made on', () => {
    const set = entries(2);
    const { onViewTypeChange } = renderPanel({ entries: set });

    fireEvent.change(
      screen.getByLabelText('Which part of the package is image 2?'),
      { target: { value: 'back' } },
    );

    expect(onViewTypeChange).toHaveBeenCalledWith(set[1].id, 'back');
  });

  it('says so when the browser could not decode a file', () => {
    renderPanel({ entries: [entry(1, { decodeFailed: true })] });

    expect(screen.getByRole('alert')).toHaveTextContent(
      /could not be opened as an image/i,
    );
  });

  it('reports a thumbnail that fails to load, rather than showing a broken frame', () => {
    const set = entries(1);
    const { onDecodeFailed } = renderPanel({ entries: set });

    fireEvent.error(screen.getByAltText('Photo 1 of 1'));

    expect(onDecodeFailed).toHaveBeenCalledWith(set[0].id);
  });
});

describe('when files are refused', () => {
  it('names the unsupported file rather than discarding it silently', () => {
    renderPanel({
      entries: entries(1),
      rejections: [{ kind: 'unsupported', files: ['scan.pdf'] }],
    });

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('scan.pdf');
    expect(alert).toHaveTextContent(/JPG, PNG or WebP/i);
  });

  it('explains the limit and what to do about it', () => {
    renderPanel({
      entries: entries(6),
      canAddMore: false,
      remaining: 0,
      rejections: [{ kind: 'overflow', files: ['seventh.png'] }],
    });

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('seventh.png');
    expect(alert).toHaveTextContent(/up to 6 images can be checked together/i);
    expect(alert).toHaveTextContent(/remove one to make room/i);
  });

  it('names a duplicate', () => {
    renderPanel({
      entries: entries(1),
      rejections: [{ kind: 'duplicate', files: ['panel-1.png'] }],
    });

    expect(screen.getByRole('alert')).toHaveTextContent(
      /already in this inspection/i,
    );
  });

  it('names an empty file', () => {
    renderPanel({
      entries: [],
      rejections: [{ kind: 'empty', files: ['nothing.png'] }],
    });

    expect(screen.getByRole('alert')).toHaveTextContent(/the file is empty/i);
  });

  it('lists every kind of refusal at once', () => {
    renderPanel({
      entries: entries(1),
      rejections: [
        { kind: 'unsupported', files: ['a.pdf'] },
        { kind: 'duplicate', files: ['panel-1.png'] },
      ],
    });

    const alert = screen.getByRole('alert');
    expect(within(alert).getAllByRole('listitem')).toHaveLength(2);
  });

  it('lets the refusals be dismissed', () => {
    const { onDismissRejections } = renderPanel({
      rejections: [{ kind: 'duplicate', files: ['panel-1.png'] }],
    });

    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }));

    expect(onDismissRejections).toHaveBeenCalledTimes(1);
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
