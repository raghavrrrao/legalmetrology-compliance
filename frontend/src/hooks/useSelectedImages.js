/**
 * The photographs chosen for one inspection, before it is submitted.
 *
 * One package, several panels: the user adds the front, then the back, then a
 * close-up of a small declaration, removes the one that came out blurred, and
 * submits the set. This hook owns that list, the preview URLs behind it, and
 * the reasons a file was refused. It does not upload and it decides nothing
 * about compliance.
 *
 * The web counterpart of the mobile client's `useInspectionImages`, with one
 * addition the browser makes necessary: **object URLs**. Each file gets one for
 * its thumbnail, and every one is revoked when the file leaves the set or the
 * component unmounts. An object URL that is never revoked keeps the whole image
 * alive in memory for the life of the tab, and with six photographs that is no
 * longer a rounding error.
 *
 * Three rules it enforces, all about not submitting something unintended:
 *
 * 1. **A file cannot be added twice.** The picker will happily return the same
 *    file again on a second visit, and a duplicate would have its declarations
 *    read and counted twice. Identity is name + size + last-modified, which is
 *    as close as a browser gets to "the same file"; `File` objects from two
 *    separate picks are never `===` even when they are the same bytes.
 * 2. **The set is bounded** at the number the backend accepts. Nothing is
 *    silently discarded: what did not fit is reported, and the user can remove
 *    one and add another.
 * 3. **An unsupported type never enters the set.** The check is the one this
 *    client has always applied - the three formats the API accepts - so a
 *    single-file selection behaves exactly as it did.
 *
 * What it deliberately does **not** check is size. The limit is a backend
 * environment variable that is not exposed to the client, and refusing a file
 * against a number invented here would reject uploads the server would have
 * accepted. An oversized file is rejected by the API, whose message names the
 * actual limit, and the selection survives so the user can remove that one
 * photograph and submit the rest. A zero-byte file *is* refused, because "this
 * file is empty" is something the browser genuinely knows.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { MAX_INSPECTION_IMAGES } from '../config/env.js';

/** The formats the API accepts. Mirrors `backend/apps/images/constants.py`. */
export const ACCEPTED_TYPES = Object.freeze([
  'image/jpeg',
  'image/png',
  'image/webp',
]);

/** The `accept` attribute for the file input. */
export const ACCEPT_ATTRIBUTE = ACCEPTED_TYPES.join(',');

/**
 * As close to "the same file" as a browser will say.
 *
 * Two `File` objects from separate picks are never `===`, so identity has to be
 * built from what the browser reports about them. Name, size and modification
 * time together are wrong only for two genuinely different files that share all
 * three, which is not a case worth breaking de-duplication for.
 */
function identify(file) {
  return `${file.name}\u0000${file.size}\u0000${file.lastModified ?? 0}`;
}

/**
 * Sort out which of the incoming files may join `current`.
 *
 * Pure, and exported for its own tests: the order of these checks is the order
 * the messages appear in, and getting it wrong means telling somebody their
 * file was a duplicate when it was actually the seventh.
 *
 * @returns {{accepted: File[], rejections: {kind: string, files: string[]}[]}}
 */
export function triageFiles(current, incoming, max = MAX_INSPECTION_IMAGES) {
  const seen = new Set(current.map((entry) => identify(entry.file)));
  const accepted = [];
  const unsupported = [];
  const empty = [];
  const duplicate = [];
  const overflow = [];

  let room = Math.max(0, max - current.length);

  for (const file of incoming) {
    if (!ACCEPTED_TYPES.includes(file.type)) {
      // Checked before anything else: an HEIC is not "a duplicate" and not
      // "the seventh photo", whatever else is true of the selection.
      unsupported.push(file.name);
      continue;
    }
    if (file.size === 0) {
      empty.push(file.name);
      continue;
    }
    const key = identify(file);
    if (seen.has(key)) {
      duplicate.push(file.name);
      continue;
    }
    if (room === 0) {
      overflow.push(file.name);
      continue;
    }
    seen.add(key);
    room -= 1;
    accepted.push(file);
  }

  const rejections = [];
  if (unsupported.length > 0) {
    rejections.push({ kind: 'unsupported', files: unsupported });
  }
  if (empty.length > 0) {
    rejections.push({ kind: 'empty', files: empty });
  }
  if (duplicate.length > 0) {
    rejections.push({ kind: 'duplicate', files: duplicate });
  }
  if (overflow.length > 0) {
    rejections.push({ kind: 'overflow', files: overflow });
  }
  return { accepted, rejections };
}

let nextId = 0;

export function useSelectedImages() {
  const [entries, setEntries] = useState([]);
  const [rejections, setRejections] = useState([]);

  // Every URL this hook has created, so unmount can revoke them all. A ref
  // rather than state: revoking is a side effect and must not re-render.
  const urlsRef = useRef(new Set());

  useEffect(
    () => () => {
      for (const url of urlsRef.current) {
        URL.revokeObjectURL(url);
      }
      urlsRef.current.clear();
    },
    [],
  );

  const add = useCallback((incoming) => {
    const files = Array.from(incoming ?? []).filter(Boolean);
    if (files.length === 0) {
      // A cancelled picker reports no files at all. Not an error, and not a
      // reason to clear the refusals the user is currently reading.
      return { added: 0 };
    }

    let added = 0;
    setEntries((current) => {
      const { accepted, rejections: refused } = triageFiles(current, files);
      setRejections(refused);
      added = accepted.length;
      if (accepted.length === 0) {
        return current;
      }
      const created = accepted.map((file) => {
        const previewUrl = URL.createObjectURL(file);
        urlsRef.current.add(previewUrl);
        nextId += 1;
        return {
          id: `image-${nextId}`,
          file,
          previewUrl,
          // The panel this photograph shows, stated per photograph because the
          // backend reads `view_type` positionally. Unstated by default: the
          // order somebody photographs a package in is not evidence that the
          // second shot is the back.
          viewType: 'unspecified',
          // Set when the browser cannot decode the file for its thumbnail,
          // which is the one honest signal available for a corrupt image.
          decodeFailed: false,
        };
      });
      return [...current, ...created];
    });
    return { added };
  }, []);

  const remove = useCallback((id) => {
    setRejections([]);
    setEntries((current) => {
      const target = current.find((entry) => entry.id === id);
      if (!target) {
        return current;
      }
      URL.revokeObjectURL(target.previewUrl);
      urlsRef.current.delete(target.previewUrl);
      return current.filter((entry) => entry.id !== id);
    });
  }, []);

  const setViewType = useCallback((id, viewType) => {
    setEntries((current) =>
      current.map((entry) => (entry.id === id ? { ...entry, viewType } : entry)),
    );
  }, []);

  /** Record that the browser could not decode this file into a preview. */
  const markUndecodable = useCallback((id) => {
    setEntries((current) =>
      current.map((entry) =>
        entry.id === id ? { ...entry, decodeFailed: true } : entry,
      ),
    );
  }, []);

  const clear = useCallback(() => {
    setRejections([]);
    setEntries((current) => {
      for (const entry of current) {
        URL.revokeObjectURL(entry.previewUrl);
        urlsRef.current.delete(entry.previewUrl);
      }
      return [];
    });
  }, []);

  const dismissRejections = useCallback(() => setRejections([]), []);

  return useMemo(
    () => ({
      /** The set, in the order it will be submitted. Index 0 is position 1. */
      entries,
      files: entries.map((entry) => entry.file),
      viewTypes: entries.map((entry) => entry.viewType),
      count: entries.length,
      canAddMore: entries.length < MAX_INSPECTION_IMAGES,
      remaining: Math.max(0, MAX_INSPECTION_IMAGES - entries.length),
      /** Why the most recent add was refused, in part or whole. */
      rejections,
      add,
      remove,
      setViewType,
      markUndecodable,
      clear,
      dismissRejections,
    }),
    [
      entries,
      rejections,
      add,
      remove,
      setViewType,
      markUndecodable,
      clear,
      dismissRejections,
    ],
  );
}
