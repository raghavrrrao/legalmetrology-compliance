"""The human-verification ledger for classifier training labels.

What problem this solves
------------------------
Every label in `seed_v0.1.json` was assigned by a model reading a photograph.
`label_verified_by` is null on all 33, and that is honest - but "honest about
being unverified" is a description of the problem, not a way out of it. This
module is the way out: the record a person writes when they actually check a
product, and the machinery that turns that record into `label_verified_by`
without anyone hand-editing a dataset file.

The ledger is the authority; the dataset is a projection of it
--------------------------------------------------------------
A verified row in a dataset is a *claim*. The ledger is what the claim rests
on, and the two are checked against each other (`reconcile`) rather than
trusted separately:

- a dataset row that claims verification with no ledger entry behind it is an
  error - somebody typed a name into a field;
- a ledger entry that disagrees with the label the dataset carries is an error
  - one of them is stale, and which one is not for code to decide;
- a ledger entry for an example that does not exist is an error.

This mirrors what the project already does for image annotations in
`ml/data/human-verification/VERIFICATION-LOG.md`, with one difference: that log
is deliberately *not* applied to its datasets, and lives outside Git with the
photographs. This ledger is committed, because the dataset it describes is
committed too - text only, no image bytes - and provenance that a clone cannot
read is not provenance for anyone but the person who wrote it.

What a person must establish
----------------------------
Four things, per product, all of them recorded on the entry:

1. **Product identity** - what the package actually is, named in words.
2. **Category** - the `ProductCategory` code.
3. **Subcategory** - the taxonomy code, where one applies.
4. **The source** - which photographs and which example rows were looked at.

An entry that omits any of them is refused. A verifier who confirms a category
without saying which photographs they opened has recorded an opinion, not a
verification.

What may never verify a label
-----------------------------
A machine. `dataset.MACHINE_LABELLER_MARKERS` is checked against every
`verifier` here and every `label_verified_by` in the dataset. The classifier
being trained on these labels is the most important single case: a model that
confirms its own training data produces agreement with itself, and a metric
computed against it measures nothing at all. There is no flag to override
this.

Outcomes
--------
``confirmed``   the drafted label is right; the row becomes verified.
``changed``     the drafted label is wrong. The entry carries the new label,
                and `apply` writes it - the change and the verification
                land together, never separately.
``unresolved``  a person looked and deliberately did not decide. Recorded so
                the next reviewer starts from it; **never** applied, and the
                row stays unverified.

Applying
--------
`apply(dataset_document, ledger)` returns a new dataset document. It is a pure
function over parsed JSON - it writes no file - so the caller decides whether
the result becomes a new `dataset_version`. It must: the digest changes, and
`docs/ml/product-classification.md` requires a new version rather than an edit
to one a model has been trained against.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Sequence

from labelextract.classification import taxonomy
from labelextract.classification.dataset import (
    ClassificationDataError,
    ClassificationDataset,
    _is_iso_date,
    machine_marker_in,
)
from labelextract.classification.validation import ERROR, WARNING, Finding

#: The committed ledger, beside the dataset it describes.
LEDGER_FILENAME = "label_verification_ledger.json"

#: Bump when an entry gains or loses a required field.
LEDGER_VERSION = "classifier-label-verification-v1"

CONFIRMED = "confirmed"
CHANGED = "changed"
UNRESOLVED = "unresolved"
OUTCOMES = (CONFIRMED, CHANGED, UNRESOLVED)

#: Outcomes that make a row verified. `unresolved` deliberately does not.
APPLICABLE_OUTCOMES = (CONFIRMED, CHANGED)


@dataclass(frozen=True)
class VerificationEntry:
    """One product, checked by one person, on one date."""

    ref: str
    product_id: str
    verifier: str
    verified_on: str
    #: What the package is, in a person's words. Not parsed; it exists so a
    #: later reader can tell whether the verifier and they are looking at the
    #: same product.
    product_identity: str
    category: str
    subcategory: str
    outcome: str
    #: The example rows the verifier read. Every one is checked to exist.
    example_ids: tuple[str, ...]
    #: The photographs the verifier opened, by digest.
    image_sha256: tuple[str, ...]
    note: str

    @property
    def is_applicable(self) -> bool:
        return self.outcome in APPLICABLE_OUTCOMES


@dataclass(frozen=True)
class VerificationLedger:
    ledger_version: str
    dataset_version: str
    description: str
    entries: tuple[VerificationEntry, ...]
    path: Path

    def by_ref(self) -> dict[str, VerificationEntry]:
        return {entry.ref: entry for entry in self.entries}

    def applicable(self) -> tuple[VerificationEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_applicable)

    def covered_example_ids(self) -> frozenset[str]:
        """Example ids an applicable entry would mark verified."""
        return frozenset(
            example_id
            for entry in self.applicable()
            for example_id in entry.example_ids
        )


def ledger_path() -> Path:
    package = resources.files("labelextract.classification")
    return Path(str(package / "datasets" / LEDGER_FILENAME))


def load_ledger(path: Path | None = None) -> VerificationLedger:
    """Read and validate a ledger file. Defaults to the shipped one.

    Raises:
        ClassificationDataError: absent, not JSON, or invalid.
    """
    resolved = Path(path) if path is not None else ledger_path()
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise ClassificationDataError(f"ledger could not be read: {resolved}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ClassificationDataError(
            f"ledger is not valid UTF-8 JSON: {resolved}"
        ) from exc
    return parse_ledger(data, path=resolved)


def parse_ledger(
    data: Mapping[str, Any], *, path: Path | None = None
) -> VerificationLedger:
    if not isinstance(data, Mapping):
        raise ClassificationDataError("ledger must be a JSON object")
    for key in ("ledger_version", "dataset_version", "description"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ClassificationDataError(f"ledger {key} must be a non-empty string")
    if data["ledger_version"] != LEDGER_VERSION:
        raise ClassificationDataError(
            f"ledger speaks {data['ledger_version']!r}; this code speaks "
            f"{LEDGER_VERSION!r}"
        )
    entries = data.get("entries")
    # An empty ledger is valid and is the honest state of a dataset nobody has
    # verified yet. Refusing it would force a fabricated first entry.
    if not isinstance(entries, list):
        raise ClassificationDataError("ledger entries must be a list")

    parsed: list[VerificationEntry] = []
    seen_refs: set[str] = set()
    for position, entry in enumerate(entries):
        item = _parse_entry(entry, position)
        if item.ref in seen_refs:
            raise ClassificationDataError(f"duplicate ledger ref {item.ref!r}")
        seen_refs.add(item.ref)
        parsed.append(item)

    return VerificationLedger(
        ledger_version=data["ledger_version"],
        dataset_version=data["dataset_version"],
        description=data["description"],
        entries=tuple(parsed),
        path=path if path is not None else Path(""),
    )


def _parse_entry(entry: Any, position: int) -> VerificationEntry:
    where = f"entries[{position}]"
    if not isinstance(entry, Mapping):
        raise ClassificationDataError(f"{where} must be an object")

    def required_str(key: str) -> str:
        value = entry.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ClassificationDataError(f"{where}.{key} must be a non-empty string")
        return value

    def string_list(key: str) -> tuple[str, ...]:
        value = entry.get(key)
        if not isinstance(value, list) or not value:
            raise ClassificationDataError(f"{where}.{key} must be a non-empty list")
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ClassificationDataError(
                    f"{where}.{key} must contain non-empty strings"
                )
        return tuple(value)

    ref = required_str("ref")
    verifier = required_str("verifier")
    marker = machine_marker_in(verifier)
    if marker is not None:
        raise ClassificationDataError(
            f"{where}.verifier {verifier!r} looks like a machine (contains "
            f"{marker!r}); a label may only be verified by a person, and the "
            f"classifier may never verify its own training data"
        )
    verified_on = required_str("verified_on")
    if not _is_iso_date(verified_on):
        raise ClassificationDataError(
            f"{where}.verified_on must be an ISO YYYY-MM-DD date, got "
            f"{verified_on!r}"
        )

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

    outcome = required_str("outcome")
    if outcome not in OUTCOMES:
        raise ClassificationDataError(
            f"{where}.outcome must be one of {OUTCOMES}, got {outcome!r}"
        )

    note = entry.get("note", "")
    if not isinstance(note, str):
        raise ClassificationDataError(f"{where}.note must be a string")

    return VerificationEntry(
        ref=ref,
        product_id=required_str("product_id"),
        verifier=verifier,
        verified_on=verified_on,
        product_identity=required_str("product_identity"),
        category=category,
        subcategory=subcategory,
        outcome=outcome,
        example_ids=string_list("example_ids"),
        image_sha256=string_list("image_sha256"),
        note=note,
    )


# --- checking a ledger against a dataset -------------------------------------


def reconcile(
    dataset: ClassificationDataset, ledger: VerificationLedger
) -> list[Finding]:
    """Findings where the ledger and the dataset do not agree.

    Run as part of `validation.main`, so the two files cannot drift apart
    unnoticed. Reports; changes nothing.
    """
    findings: list[Finding] = []
    by_example = dataset.by_example_id()
    by_product = dataset.by_product()

    if ledger.entries and ledger.dataset_version != dataset.dataset_version:
        findings.append(
            Finding(
                "ledger-dataset-mismatch",
                ERROR,
                f"ledger was written against {ledger.dataset_version!r} but "
                f"this dataset is {dataset.dataset_version!r}; a decision made "
                f"about one version is not automatically true of another",
            )
        )

    for entry in ledger.entries:
        if entry.product_id not in by_product:
            findings.append(
                Finding(
                    "ledger-unknown-product",
                    ERROR,
                    f"ledger entry {entry.ref!r} verifies product "
                    f"{entry.product_id!r}, which is not in the dataset",
                    (entry.ref,),
                )
            )
            continue
        for example_id in entry.example_ids:
            example = by_example.get(example_id)
            if example is None:
                findings.append(
                    Finding(
                        "ledger-unknown-example",
                        ERROR,
                        f"ledger entry {entry.ref!r} names example "
                        f"{example_id!r}, which is not in the dataset",
                        (entry.ref,),
                    )
                )
                continue
            if example.product_id != entry.product_id:
                findings.append(
                    Finding(
                        "ledger-example-product-mismatch",
                        ERROR,
                        f"ledger entry {entry.ref!r} verifies product "
                        f"{entry.product_id!r} but names example "
                        f"{example_id!r}, which belongs to "
                        f"{example.product_id!r}",
                        (entry.ref,),
                    )
                )
            if entry.is_applicable and (
                example.subcategory != entry.subcategory
                or example.category != entry.category
            ):
                findings.append(
                    Finding(
                        "ledger-label-disagreement",
                        ERROR,
                        f"ledger entry {entry.ref!r} decided "
                        f"{entry.category}/{entry.subcategory} but example "
                        f"{example_id!r} carries "
                        f"{example.category}/{example.subcategory}; the "
                        f"decision has not been applied, or the dataset was "
                        f"changed after it",
                        (entry.ref, example_id),
                    )
                )
        known_digests = {
            example.image_sha256
            for example in by_product[entry.product_id]
            if example.image_sha256
        }
        unknown = sorted(set(entry.image_sha256) - known_digests)
        if unknown:
            findings.append(
                Finding(
                    "ledger-unknown-image",
                    WARNING,
                    f"ledger entry {entry.ref!r} cites "
                    f"{len(unknown)} photograph(s) that no example of "
                    f"{entry.product_id!r} references",
                    (entry.ref,),
                )
            )

    covered = ledger.covered_example_ids()
    refs = set(ledger.by_ref())
    for example in dataset.verified_examples:
        if example.example_id not in covered:
            findings.append(
                Finding(
                    "verified-without-ledger-entry",
                    ERROR,
                    f"example is marked verified by "
                    f"{example.label_verified_by!r} but no ledger entry covers "
                    f"it; a name in a field is not a verification",
                    (example.example_id,),
                )
            )
        elif example.label_verification_ref not in refs:
            findings.append(
                Finding(
                    "unknown-verification-ref",
                    ERROR,
                    f"example cites verification ref "
                    f"{example.label_verification_ref!r}, which is not in the "
                    f"ledger",
                    (example.example_id,),
                )
            )

    for entry in ledger.applicable():
        pending = sorted(
            example_id
            for example_id in entry.example_ids
            if example_id in by_example and not by_example[example_id].is_verified
        )
        if pending:
            findings.append(
                Finding(
                    "ledger-entry-not-applied",
                    WARNING,
                    f"ledger entry {entry.ref!r} is {entry.outcome} but "
                    f"{len(pending)} of its examples are still unverified in "
                    f"the dataset; run `apply` and publish a new "
                    f"dataset_version",
                    (entry.ref,),
                )
            )
    return findings


# --- applying a ledger to a dataset document ---------------------------------


def apply(
    document: Mapping[str, Any],
    ledger: VerificationLedger,
    *,
    dataset_version: str | None = None,
    created_on: str | None = None,
) -> dict[str, Any]:
    """A new dataset document with the ledger's decisions written into it.

    Pure: `document` is not modified and no file is written. For every
    applicable entry, each example it names gains `label_verified_by`,
    `label_verified_on` and `label_verification_ref`, and - for a `changed`
    outcome - the corrected `category` and `subcategory`.

    `unresolved` entries are skipped entirely, by design.

    Args:
        document: a parsed dataset file.
        ledger: the decisions to apply.
        dataset_version: the new version. Required when anything is applied:
            the digest changes, and a version that has been trained against
            may not be edited in place.
        created_on: ISO date for the new version. Defaults to the latest
            `verified_on` among the applied entries, so the result is
            deterministic and does not depend on when the command ran.

    Raises:
        ClassificationDataError: the document does not match the ledger, or a
            new `dataset_version` was needed and not given.
    """
    if not isinstance(document, Mapping) or not isinstance(
        document.get("examples"), list
    ):
        raise ClassificationDataError("document must be a parsed dataset object")

    applicable = ledger.applicable()
    result = copy.deepcopy(dict(document))
    examples: list[dict[str, Any]] = result["examples"]
    by_id = {
        example.get("example_id"): example
        for example in examples
        if isinstance(example, Mapping)
    }

    applied = 0
    for entry in applicable:
        for example_id in entry.example_ids:
            example = by_id.get(example_id)
            if example is None:
                raise ClassificationDataError(
                    f"ledger entry {entry.ref!r} names example {example_id!r}, "
                    f"which is not in the document"
                )
            if example.get("product_id") != entry.product_id:
                raise ClassificationDataError(
                    f"ledger entry {entry.ref!r} verifies product "
                    f"{entry.product_id!r} but example {example_id!r} belongs "
                    f"to {example.get('product_id')!r}"
                )
            example["category"] = entry.category
            example["subcategory"] = entry.subcategory
            example["label_verified_by"] = entry.verifier
            example["label_verified_on"] = entry.verified_on
            example["label_verification_ref"] = entry.ref
            applied += 1

    if applied:
        if not dataset_version:
            raise ClassificationDataError(
                "applying a verification changes the dataset digest, so it "
                "must be published under a new dataset_version - pass one. "
                "Editing a version a model has been trained against would "
                "silently change what every published number refers to"
            )
        if dataset_version == document.get("dataset_version"):
            raise ClassificationDataError(
                f"dataset_version {dataset_version!r} is the version being "
                f"applied to; publish a new one"
            )
        result["dataset_version"] = dataset_version
        result["created_on"] = created_on or max(
            entry.verified_on for entry in applicable
        )
    return result


def verification_summary(
    dataset: ClassificationDataset, ledger: VerificationLedger
) -> dict[str, Any]:
    """Counts a report can quote without recomputing them three ways."""
    verified = dataset.verified_examples
    verified_products = {example.product_id for example in verified}
    outcomes: dict[str, int] = {outcome: 0 for outcome in OUTCOMES}
    for entry in ledger.entries:
        outcomes[entry.outcome] += 1
    return {
        "dataset_version": dataset.dataset_version,
        "ledger_version": ledger.ledger_version,
        "examples": len(dataset.examples),
        "verified_examples": len(verified),
        "unverified_examples": len(dataset.examples) - len(verified),
        "products": len(dataset.product_ids),
        "verified_products": len(verified_products),
        "unverified_products": len(dataset.product_ids) - len(verified_products),
        "ledger_entries": len(ledger.entries),
        "ledger_outcomes": outcomes,
        "verifiers": sorted({entry.verifier for entry in ledger.entries}),
    }


def new_ledger_document(dataset_version: str, description: str) -> dict[str, Any]:
    """An empty ledger for a dataset version. The honest starting point."""
    return {
        "ledger_version": LEDGER_VERSION,
        "dataset_version": dataset_version,
        "description": description,
        "entries": [],
    }


def entry_template(
    dataset: ClassificationDataset, product_id: str, *, ref: str
) -> dict[str, Any]:
    """A pre-filled entry for a reviewer to complete, or an empty dict.

    Fills only what the dataset already knows - which examples and which
    photographs belong to the product. `verifier`, `verified_on`,
    `product_identity` and `outcome` are left blank **on purpose**: they are
    the four things a person must supply, and pre-filling any of them from
    the drafted label is how a draft becomes a verification without anybody
    deciding anything.
    """
    examples = dataset.by_product().get(product_id, ())
    if not examples:
        raise ClassificationDataError(f"no such product: {product_id!r}")
    digests = sorted({e.image_sha256 for e in examples if e.image_sha256})
    return {
        "ref": ref,
        "product_id": product_id,
        "verifier": "",
        "verified_on": "",
        "product_identity": "",
        "category": "",
        "subcategory": "",
        "outcome": "",
        "example_ids": sorted(e.example_id for e in examples),
        "image_sha256": digests,
        "note": (
            "Drafted label for reference only, NOT a suggestion to confirm: "
            + "/".join(
                sorted({f"{e.category}/{e.subcategory}" for e in examples})
            )
        ),
    }


def entry_templates(
    dataset: ClassificationDataset, product_ids: Sequence[str] | None = None
) -> list[dict[str, Any]]:
    """`entry_template` for every unverified product, in dataset order."""
    wanted = list(product_ids) if product_ids is not None else list(dataset.product_ids)
    return [
        entry_template(dataset, product_id, ref=f"{product_id}-review")
        for product_id in wanted
    ]
