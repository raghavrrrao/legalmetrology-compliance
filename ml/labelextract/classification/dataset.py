"""Loading and validating a product-classification dataset.

The format
----------
One JSON file. A header describes the set; `examples` lists one entry per
piece of text. Everything an example needs to be traced back to where it
came from is on the example, not implied by its position in a folder:

    {
      "dataset_version": "product-classification-seed-v0.1",
      "created_on": "2026-09-16",
      "description": "...",
      "taxonomy_version": "1",
      "examples": [
        {
          "example_id": "p001_05_declaration_closeup/ocr",
          "product_id": "product_001",
          "category": "packaged-non-food",
          "subcategory": "cleaning-product",
          "text": "...",
          "text_source": "ocr",
          "labelled_by": "claude-opus-5-draft",
          "label_verified_by": null,
          "ocr_engine": "tesseract",
          "ocr_engine_version": "0.2.0",
          "source_dataset": "our-eval-v0.1-draft",
          "source_sample_id": "p001_05_declaration_closeup",
          "image_sha256": "...",
          "note": "..."
        }
      ]
    }

Field by field:

- `product_id` groups every example that came from the same physical
  package - its several panels, and the OCR and transcribed variants of one
  panel. **Evaluation must split by product, never by example.** Two
  photographs of one pack share brand names, an address block and a licence
  number; a model that has seen one has largely seen the other, and a split
  that puts them on opposite sides reports a number that predicts nothing.
- `text_source` is `ocr` for text exactly as an engine recognised it, or
  `manual_transcription` for text a person or a model typed from the
  photograph. The two are different data: one carries the noise the
  classifier meets in production, the other carries the words a label
  actually prints. Both are useful; neither may be mistaken for the other.
- `labelled_by` names who assigned the category, and `label_verified_by`
  names the person who checked it - or is null. The seed set's labels are
  **model-drafted and unverified**, and every example says so, for the same
  reason the evaluation set's annotations do: a label nobody remembers
  guessing becomes ground truth by default.
- `ocr_engine` / `ocr_engine_version` record which pipeline produced OCR
  text, so a sample can be regenerated from its photograph. Null for
  transcriptions.
- `source_dataset` / `source_sample_id` / `image_sha256` tie the example to
  a photograph in a frozen evaluation set, whose manifest carries the same
  SHA-256. The photographs themselves are not in the repository - see
  `docs/data-strategy.md` - but the digest lets anyone holding them confirm
  they have the same file.

Validation refuses; it never repairs
------------------------------------
Every problem raises `ClassificationDataError`. A dataset that loads with
some examples silently dropped still reports a sample count, and that count
is what ends up in a metrics table.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

from labelextract.classification import taxonomy

#: The dataset the shipped artifact was trained on, inside the package.
SEED_DATASET_FILENAME = "seed_v0.1.json"

TEXT_SOURCES = ("ocr", "manual_transcription")


class ClassificationDataError(ValueError):
    """A dataset file is malformed. Raised rather than repaired, always."""


@dataclass(frozen=True)
class ClassificationExample:
    example_id: str
    product_id: str
    category: str
    subcategory: str
    text: str
    text_source: str
    labelled_by: str
    label_verified_by: str | None
    ocr_engine: str | None
    ocr_engine_version: str | None
    source_dataset: str | None
    source_sample_id: str | None
    image_sha256: str | None
    note: str

    @property
    def is_verified(self) -> bool:
        return bool(self.label_verified_by)


@dataclass(frozen=True)
class ClassificationDataset:
    dataset_version: str
    created_on: str
    description: str
    taxonomy_version: str
    examples: tuple[ClassificationExample, ...]
    #: SHA-256 of the file's bytes. Recorded in the artifact trained from it,
    #: so "which data produced this model" has a checkable answer.
    sha256: str
    path: Path

    @property
    def product_ids(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for example in self.examples:
            seen.setdefault(example.product_id, None)
        return tuple(seen)

    def by_product(self) -> dict[str, tuple[ClassificationExample, ...]]:
        groups: dict[str, list[ClassificationExample]] = {}
        for example in self.examples:
            groups.setdefault(example.product_id, []).append(example)
        return {product: tuple(items) for product, items in groups.items()}

    def label_counts(self) -> dict[str, dict[str, int]]:
        """Examples and distinct products per subcategory."""
        counts: dict[str, dict[str, Any]] = {}
        for example in self.examples:
            entry = counts.setdefault(
                example.subcategory, {"examples": 0, "products": set()}
            )
            entry["examples"] += 1
            entry["products"].add(example.product_id)
        return {
            name: {"examples": entry["examples"], "products": len(entry["products"])}
            for name, entry in sorted(counts.items())
        }


def seed_dataset_path() -> Path:
    package = resources.files("labelextract.classification")
    return Path(str(package / "datasets" / SEED_DATASET_FILENAME))


def load_dataset(path: Path | None = None) -> ClassificationDataset:
    """Read and validate a dataset file. Defaults to the shipped seed set.

    Raises:
        ClassificationDataError: the file is absent, not JSON, or invalid.
    """
    resolved = Path(path) if path is not None else seed_dataset_path()
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise ClassificationDataError(f"dataset could not be read: {resolved}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ClassificationDataError(f"dataset is not valid UTF-8 JSON: {resolved}") from exc
    return parse_dataset(data, sha256=hashlib.sha256(raw).hexdigest(), path=resolved)


def parse_dataset(
    data: Mapping[str, Any], *, sha256: str = "", path: Path | None = None
) -> ClassificationDataset:
    if not isinstance(data, Mapping):
        raise ClassificationDataError("dataset must be a JSON object")
    for key in ("dataset_version", "created_on", "description", "taxonomy_version"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ClassificationDataError(f"dataset {key} must be a non-empty string")
    if data["taxonomy_version"] != taxonomy.TAXONOMY_VERSION:
        raise ClassificationDataError(
            f"dataset labels use taxonomy {data['taxonomy_version']!r}; this "
            f"code speaks {taxonomy.TAXONOMY_VERSION!r}"
        )
    examples = data.get("examples")
    if not isinstance(examples, list) or not examples:
        raise ClassificationDataError("dataset examples must be a non-empty list")

    parsed: list[ClassificationExample] = []
    seen_ids: set[str] = set()
    for position, entry in enumerate(examples):
        example = _parse_example(entry, position)
        if example.example_id in seen_ids:
            raise ClassificationDataError(f"duplicate example_id {example.example_id!r}")
        seen_ids.add(example.example_id)
        parsed.append(example)

    return ClassificationDataset(
        dataset_version=data["dataset_version"],
        created_on=data["created_on"],
        description=data["description"],
        taxonomy_version=data["taxonomy_version"],
        examples=tuple(parsed),
        sha256=sha256,
        path=path if path is not None else Path(""),
    )


def _parse_example(entry: Any, position: int) -> ClassificationExample:
    where = f"examples[{position}]"
    if not isinstance(entry, Mapping):
        raise ClassificationDataError(f"{where} must be an object")

    def required_str(key: str) -> str:
        value = entry.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ClassificationDataError(f"{where}.{key} must be a non-empty string")
        return value

    def optional_str(key: str) -> str | None:
        value = entry.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ClassificationDataError(f"{where}.{key} must be a string or null")
        return value

    example_id = required_str("example_id")
    product_id = required_str("product_id")
    category = required_str("category")
    subcategory = required_str("subcategory")
    if not taxonomy.is_category(category):
        raise ClassificationDataError(
            f"{where}.category {category!r} is not a taxonomy category"
        )
    if not taxonomy.is_subcategory(subcategory):
        raise ClassificationDataError(
            f"{where}.subcategory {subcategory!r} is not a taxonomy subcategory"
        )
    if taxonomy.category_for(subcategory) != category:
        raise ClassificationDataError(
            f"{where}: subcategory {subcategory!r} does not belong to {category!r}"
        )

    text = entry.get("text")
    if not isinstance(text, str):
        # Empty text is allowed - a front panel that yielded nothing is a
        # real outcome worth keeping - but it must be a string.
        raise ClassificationDataError(f"{where}.text must be a string")

    text_source = required_str("text_source")
    if text_source not in TEXT_SOURCES:
        raise ClassificationDataError(
            f"{where}.text_source must be one of {TEXT_SOURCES}, got {text_source!r}"
        )
    if "label_verified_by" not in entry:
        raise ClassificationDataError(
            f"{where}.label_verified_by must be present (a name, or null)"
        )
    ocr_engine = optional_str("ocr_engine")
    ocr_engine_version = optional_str("ocr_engine_version")
    if text_source == "ocr" and not (ocr_engine and ocr_engine_version):
        raise ClassificationDataError(
            f"{where}: OCR text must record ocr_engine and ocr_engine_version"
        )
    image_sha256 = optional_str("image_sha256")
    if image_sha256 is not None and (
        len(image_sha256) != 64 or any(c not in "0123456789abcdef" for c in image_sha256)
    ):
        raise ClassificationDataError(f"{where}.image_sha256 must be 64 hex characters")

    note = entry.get("note", "")
    if not isinstance(note, str):
        raise ClassificationDataError(f"{where}.note must be a string")

    return ClassificationExample(
        example_id=example_id,
        product_id=product_id,
        category=category,
        subcategory=subcategory,
        text=text,
        text_source=text_source,
        labelled_by=required_str("labelled_by"),
        label_verified_by=optional_str("label_verified_by"),
        ocr_engine=ocr_engine,
        ocr_engine_version=ocr_engine_version,
        source_dataset=optional_str("source_dataset"),
        source_sample_id=optional_str("source_sample_id"),
        image_sha256=image_sha256,
        note=note,
    )
