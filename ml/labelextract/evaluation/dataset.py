"""Loading and validating a frozen evaluation dataset from disk.

Where the dataset lives, and why not in Git
-------------------------------------------
`docs/data-strategy.md` puts the evaluation set outside the repository:

    ml/data/our-evaluation-set/
    ├── images/
    ├── annotations/        one JSON per image
    └── MANIFEST.json

`.gitignore` blocks every file under `ml/data/` except the README and the
`.gitkeep` placeholders, and `tests/test_data_layout.py` asserts that nothing
else is ever tracked there. So the *dataset* is deliberately absent from a
clone, and what this repository holds is the *code that reads one* - this
module, its schema, and the tests that pin both.

That split is what makes the arrangement reproducible rather than merely
convenient: the manifest names a version and carries a SHA-256 per image, so a
result published against `v1` can be checked by anyone holding the same files,
and an edited photograph fails validation instead of quietly changing what a
published number meant.

Nothing here downloads anything. `docs/data-strategy.md` is explicit that an
automatic download is how an unlicensed corpus ends up on six machines without
anybody reading the terms.

Validation refuses; it never repairs
------------------------------------
Every problem below raises. There is no "best effort" mode and no flag to skip
a bad sample, because a dataset that loads with three samples silently dropped
still reports a sample count, and that count is what ends up in the report.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from labelextract.evaluation.schema import (
    DatasetManifest,
    EvaluationDataError,
    SampleAnnotation,
    SampleEntry,
)

#: The manifest filename `docs/data-strategy.md` names.
MANIFEST_FILENAME = "MANIFEST.json"

#: Read images in chunks when digesting: an evaluation set is photographs, and
#: holding one in memory to checksum it is avoidable.
_DIGEST_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class Sample:
    """A manifest entry joined to its annotation and its resolved image path."""

    entry: SampleEntry
    annotation: SampleAnnotation
    image_path: Path

    @property
    def sample_id(self) -> str:
        return self.entry.sample_id


@dataclass(frozen=True)
class EvaluationDataset:
    """A validated, frozen evaluation set.

    Constructing one is the only way to get samples, and construction runs
    every check. There is no path that yields a half-validated dataset.
    """

    root: Path
    manifest: DatasetManifest
    samples: tuple[Sample, ...]

    @property
    def dataset_version(self) -> str:
        return self.manifest.dataset_version

    def __len__(self) -> int:
        return len(self.samples)

    def __iter__(self) -> Iterator[Sample]:
        return iter(self.samples)

    def sample(self, sample_id: str) -> Sample:
        for sample in self.samples:
            if sample.sample_id == sample_id:
                return sample
        raise KeyError(sample_id)


def file_sha256(path: Path) -> str:
    """Lowercase hex SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_DIGEST_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_inside(candidate: Path, resolved_root: Path) -> bool:
    """Whether `candidate` resolves to a location inside `resolved_root`.

    Both sides are resolved, so a dataset directory that is itself a symlink
    still validates - it is only paths escaping *out* of the tree that are
    refused.
    """
    try:
        candidate.resolve().relative_to(resolved_root)
    except (ValueError, OSError):
        return False
    return True


def _read_json(path: Path, what: str) -> object:
    if not path.is_file():
        raise EvaluationDataError(f"{what} does not exist: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvaluationDataError(f"{what} is not valid JSON ({path}): {exc}") from exc
    except UnicodeDecodeError as exc:
        raise EvaluationDataError(f"{what} is not UTF-8 ({path}): {exc}") from exc


def load_manifest(root: Path) -> DatasetManifest:
    """Parse `MANIFEST.json` from a dataset root. Does not touch the samples."""
    root = Path(root)
    return DatasetManifest.from_dict(
        _read_json(root / MANIFEST_FILENAME, "the dataset manifest")
    )


def load_dataset(root: Path, *, verify_checksums: bool = True) -> EvaluationDataset:
    """Load and fully validate the frozen dataset rooted at `root`.

    Args:
        root: the directory holding `MANIFEST.json`.
        verify_checksums: re-digest every image and compare against the
            manifest. On by default, because the digest is the entire mechanism
            by which "frozen" is a fact rather than an intention. Turning it off
            is for a caller that has already verified the set in the same
            process - never for making a failing dataset load.

    Raises:
        EvaluationDataError: anything about the dataset is wrong - a missing
            file, a malformed annotation, a sample id that disagrees with its
            manifest entry, or an image whose bytes have changed.
    """
    root = Path(root)
    if not root.is_dir():
        raise EvaluationDataError(f"the dataset root does not exist: {root}")

    manifest = load_manifest(root)

    samples: list[Sample] = []
    problems: list[str] = []

    resolved_root = root.resolve()

    for entry in manifest.samples:
        image_path = root / entry.image
        annotation_path = root / entry.annotation

        # Belt and braces behind `SampleEntry`'s string checks. Those reject
        # the paths that *look* like an escape; this rejects the ones that
        # turn out to be one - a symlink out of the tree, or a separator
        # convention nobody anticipated. Cheap, and it is the check that stays
        # correct when the string rules are wrong.
        escaped = [
            str(candidate)
            for candidate in (image_path, annotation_path)
            if not _is_inside(candidate, resolved_root)
        ]
        if escaped:
            problems.append(
                f"{entry.sample_id}: {escaped[0]} resolves outside the dataset "
                f"root {resolved_root}. A manifest may only reference files "
                f"inside its own dataset."
            )
            continue

        if not image_path.is_file():
            problems.append(
                f"{entry.sample_id}: image is missing at {entry.image}. The manifest "
                f"lists it, so either the file was not copied or the manifest is "
                f"describing a different dataset."
            )
            continue

        try:
            annotation = SampleAnnotation.from_dict(
                _read_json(annotation_path, f"annotation for {entry.sample_id}")
            )
        except EvaluationDataError as exc:
            problems.append(str(exc))
            continue

        if annotation.sample_id != entry.sample_id:
            problems.append(
                f"{entry.sample_id}: its annotation file declares sample_id "
                f"{annotation.sample_id!r}. A mismatch means the annotation and the "
                f"photograph are not the same sample, and scoring them together "
                f"would attribute one label's truth to another's image."
            )
            continue

        if verify_checksums:
            actual = file_sha256(image_path)
            if actual != entry.image_sha256:
                problems.append(
                    f"{entry.sample_id}: {entry.image} does not match the manifest "
                    f"digest.\n  manifest: {entry.image_sha256}\n  on disk:  {actual}\n"
                    f"  The frozen set has changed. Publish a new dataset_version "
                    f"rather than editing this one - every number already reported "
                    f"against {manifest.dataset_version} was measured on the old bytes."
                )
                continue

        samples.append(
            Sample(entry=entry, annotation=annotation, image_path=image_path)
        )

    if problems:
        listed = "\n".join(f"  - {problem}" for problem in problems)
        raise EvaluationDataError(
            f"dataset {manifest.dataset_version} at {root} is not usable "
            f"({len(problems)} problem(s)):\n{listed}"
        )

    return EvaluationDataset(root=root, manifest=manifest, samples=tuple(samples))


def describe_dataset(dataset: EvaluationDataset) -> dict:
    """A short, JSON-safe description of what was loaded.

    Every evaluation report embeds this. `docs/evaluation-strategy.md` requires
    a number to be reported with its dataset, size and date - "'94% on 50
    images' is a useful claim; '94%' is not" - so the identity travels with the
    result rather than being remembered separately.
    """
    annotated_fields = sum(len(sample.annotation.fields) for sample in dataset)
    with_reference_text = sum(
        1 for sample in dataset if sample.annotation.reference_text is not None
    )
    conditions: dict[str, int] = {}
    for sample in dataset:
        for condition in sample.annotation.conditions:
            conditions[condition] = conditions.get(condition, 0) + 1

    return {
        "dataset_version": dataset.dataset_version,
        "created_on": dataset.manifest.created_on,
        "description": dataset.manifest.description,
        "sample_count": len(dataset),
        "annotated_field_count": annotated_fields,
        "samples_with_reference_text": with_reference_text,
        "conditions": dict(sorted(conditions.items())),
    }
