"""Data-integrity checks over a classification dataset, and the coverage report.

`dataset.py` refuses a file that is *malformed*. This module answers a
different question: the file parsed, but is the data in it fit to train or
measure a classifier on?

The two are separate on purpose. A duplicated product, a label that
contradicts itself across two panels, or a product sitting in both sides of an
evaluation split are all perfectly well-formed JSON. None of them is caught by
a schema, and each one quietly changes what a measured number means - usually
upwards, which is why nobody notices.

    from labelextract.classification import dataset, validation

    findings = validation.validate(dataset.load_dataset())
    validation.raise_for_errors(findings)      # refuses; never repairs

Or from a shell, which also prints the coverage table:

    python -m labelextract.classification.validation
    python -m labelextract.classification.validation --dataset my_set.json \\
        --ledger ledger.json --require-verified

Severity
--------
``error``    the data is wrong, or a claim in it is not supported. Fails the
             command (exit 1) and `raise_for_errors`.
``warning``  the data is honest but thin - a class with one product, a label
             nobody has verified. Reported, never fatal, because the shipped
             seed set is *entirely* warnings and refusing to load it would be
             refusing to describe the problem this module exists to describe.
``info``     a count worth stating next to the rest.

`--require-verified` promotes the unverified-label warning to an error. That
is the switch a future held-out set would be validated under; the seed set
does not pass it and is not meant to.

Nothing here repairs anything. Where a finding is ambiguous - two products
whose text is identical might be a duplicate import or might be two genuinely
identical private-label packs - it is reported with both identifiers and left
for a person. Guessing which one it is, in code, is how a dataset acquires a
correction nobody remembers making.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from labelextract.classification import taxonomy
from labelextract.classification.dataset import (
    ClassificationDataError,
    ClassificationDataset,
    ClassificationExample,
    load_dataset,
    machine_marker_in,
)

ERROR = "error"
WARNING = "warning"
INFO = "info"

#: Products per subcategory below which a class cannot be measured at all by
#: leave-one-product-out: with one product, holding it out leaves nothing to
#: learn the class from and its recall is 0 by construction. Not a target -
#: `docs/ml/product-classification.md` puts the useful figure at 5-10 - just
#: the point below which a reported number is an artefact of the split.
MIN_PRODUCTS_PER_CLASS = 2


@dataclass(frozen=True)
class Finding:
    """One thing that is wrong, or thin, about a dataset."""

    code: str
    severity: str
    message: str
    #: Example ids, product ids or class codes the finding is about. Always
    #: carried so a report names what to go and look at.
    subjects: tuple[str, ...] = ()

    def __str__(self) -> str:
        where = f" [{', '.join(self.subjects)}]" if self.subjects else ""
        return f"{self.severity.upper():7s} {self.code}: {self.message}{where}"


class DatasetIntegrityError(ClassificationDataError):
    """One or more error-severity findings. Carries them all, not just the first."""

    def __init__(self, findings: Sequence[Finding]) -> None:
        self.findings = tuple(findings)
        detail = "\n".join(f"  - {finding}" for finding in self.findings)
        super().__init__(
            f"{len(self.findings)} dataset integrity error(s):\n{detail}"
        )


def _normalised_text(text: str) -> str:
    """Text compared for duplication: whitespace collapsed, case folded.

    Two OCR runs of one photograph differ in trailing spaces and line breaks
    long before they differ in words, and a duplicate that survives only
    because of a newline is still a duplicate.
    """
    return " ".join(text.split()).casefold()


# --- the individual checks ---------------------------------------------------
#
# Each returns findings and takes the whole dataset, so a check can see
# relationships between examples. Numbered to match the check list in
# `docs/ml/product-classification.md`.


def check_product_ids(dataset: ClassificationDataset) -> list[Finding]:
    """1. Every example names a product, and the name is not a placeholder."""
    findings: list[Finding] = []
    placeholders = {"", "unknown", "none", "null", "tbd", "todo", "n/a", "x"}
    for example in dataset.examples:
        if example.product_id.strip().casefold() in placeholders:
            findings.append(
                Finding(
                    "missing-product-id",
                    ERROR,
                    f"product_id {example.product_id!r} is a placeholder, not "
                    f"an identity; every example must name the physical pack "
                    f"it came from",
                    (example.example_id,),
                )
            )
    return findings


def check_duplicate_products(dataset: ClassificationDataset) -> list[Finding]:
    """2. Two product ids that are in fact the same physical pack.

    Detected from the photographs: one image digest can only have been taken
    of one package, so the same digest under two product ids means one pack
    was imported twice and is being counted as two independent products. That
    inflates every per-class product count and puts the *same* pack on both
    sides of a leave-one-product-out split.
    """
    findings: list[Finding] = []
    owners: dict[str, set[str]] = {}
    for example in dataset.examples:
        if example.image_sha256:
            owners.setdefault(example.image_sha256, set()).add(example.product_id)
    for digest, products in sorted(owners.items()):
        if len(products) > 1:
            findings.append(
                Finding(
                    "duplicate-product",
                    ERROR,
                    f"image {digest[:12]}... is shared by {len(products)} "
                    f"product ids; one photograph is of one package, so these "
                    f"are not independent products",
                    tuple(sorted(products)),
                )
            )
    return findings


def check_duplicate_images(dataset: ClassificationDataset) -> list[Finding]:
    """3. The same photograph used twice for the same kind of text.

    One image legitimately appears more than once - the seed set carries both
    the OCR of a panel and a transcription of it. What may not happen is the
    same (image, text_source) pair twice: that is one reading counted twice,
    and it weights that panel double in training and in every metric.
    """
    findings: list[Finding] = []
    seen: dict[tuple[str, str], list[str]] = {}
    for example in dataset.examples:
        if example.image_sha256:
            key = (example.image_sha256, example.text_source)
            seen.setdefault(key, []).append(example.example_id)
    for (digest, source), ids in sorted(seen.items()):
        if len(ids) > 1:
            findings.append(
                Finding(
                    "duplicate-image",
                    ERROR,
                    f"image {digest[:12]}... appears {len(ids)} times with "
                    f"text_source {source!r}; one reading is being counted "
                    f"more than once",
                    tuple(sorted(ids)),
                )
            )
    return findings


def check_labels_present(dataset: ClassificationDataset) -> list[Finding]:
    """4. Every example carries a category and a subcategory."""
    findings: list[Finding] = []
    for example in dataset.examples:
        if not example.category.strip() or not example.subcategory.strip():
            findings.append(
                Finding(
                    "missing-label",
                    ERROR,
                    "category and subcategory must both be set",
                    (example.example_id,),
                )
            )
    return findings


def check_taxonomy_values(dataset: ClassificationDataset) -> list[Finding]:
    """5 and 12. Codes are in the vocabulary, and the pair is consistent.

    The loader already refuses these, so a finding here means something built
    a `ClassificationDataset` without going through it. Checked anyway: this
    module is also the thing a future dataset builder validates its output
    with, before that output is ever written to a file.
    """
    findings: list[Finding] = []
    for example in dataset.examples:
        if not taxonomy.is_category(example.category):
            findings.append(
                Finding(
                    "invalid-category",
                    ERROR,
                    f"category {example.category!r} is not in taxonomy "
                    f"{taxonomy.TAXONOMY_VERSION}",
                    (example.example_id,),
                )
            )
            continue
        if not taxonomy.is_subcategory(example.subcategory):
            findings.append(
                Finding(
                    "unsupported-taxonomy-value",
                    ERROR,
                    f"subcategory {example.subcategory!r} is not in taxonomy "
                    f"{taxonomy.TAXONOMY_VERSION}",
                    (example.example_id,),
                )
            )
            continue
        if taxonomy.category_for(example.subcategory) != example.category:
            findings.append(
                Finding(
                    "inconsistent-taxonomy-pair",
                    ERROR,
                    f"subcategory {example.subcategory!r} does not sit under "
                    f"category {example.category!r}",
                    (example.example_id,),
                )
            )
    if dataset.taxonomy_version != taxonomy.TAXONOMY_VERSION:
        findings.append(
            Finding(
                "taxonomy-version-mismatch",
                ERROR,
                f"dataset speaks taxonomy {dataset.taxonomy_version!r}, this "
                f"code speaks {taxonomy.TAXONOMY_VERSION!r}",
            )
        )
    return findings


def check_provenance(dataset: ClassificationDataset) -> list[Finding]:
    """6. Every example can be traced back to the thing it came from."""
    findings: list[Finding] = []
    for example in dataset.examples:
        missing = [
            name
            for name, value in (
                ("source_dataset", example.source_dataset),
                ("source_sample_id", example.source_sample_id),
                ("image_sha256", example.image_sha256),
            )
            if not value
        ]
        if missing:
            findings.append(
                Finding(
                    "missing-provenance",
                    ERROR,
                    f"cannot be traced to a photograph: {', '.join(missing)} "
                    f"not set",
                    (example.example_id,),
                )
            )
        if example.text_source == "ocr" and not (
            example.ocr_engine and example.ocr_engine_version
        ):
            findings.append(
                Finding(
                    "missing-ocr-provenance",
                    ERROR,
                    "OCR text must name the engine and version that produced "
                    "it, or it cannot be regenerated",
                    (example.example_id,),
                )
            )
        if not example.labelled_by.strip():
            findings.append(
                Finding(
                    "missing-labeller",
                    ERROR,
                    "labelled_by must name whoever assigned the category",
                    (example.example_id,),
                )
            )
    return findings


def check_verification(
    dataset: ClassificationDataset, *, require_verified: bool = False
) -> list[Finding]:
    """7. Unverified labels, and verifications that do not hold up.

    A missing verification is a warning - the shipped seed set has 33 of them
    and saying so is the point. A verification that names a machine, or that
    is missing its date or its ledger reference, is an error: it is a claim
    the data does not support.
    """
    findings: list[Finding] = []
    unverified = dataset.unverified_examples
    for example in dataset.verified_examples:
        assert example.label_verified_by is not None
        marker = machine_marker_in(example.label_verified_by)
        if marker is not None:
            findings.append(
                Finding(
                    "machine-verifier",
                    ERROR,
                    f"label_verified_by {example.label_verified_by!r} contains "
                    f"{marker!r}; the classifier and the drafting model may "
                    f"never verify their own labels",
                    (example.example_id,),
                )
            )
        if not example.label_verified_on or not example.label_verification_ref:
            findings.append(
                Finding(
                    "incomplete-verification",
                    ERROR,
                    "a verified label must carry label_verified_on and "
                    "label_verification_ref",
                    (example.example_id,),
                )
            )
    if unverified:
        findings.append(
            Finding(
                "unverified-labels",
                ERROR if require_verified else WARNING,
                f"{len(unverified)} of {len(dataset.examples)} labels have "
                f"never been checked by a person; any metric computed against "
                f"them measures agreement with whoever drafted them",
                tuple(example.example_id for example in unverified[:5])
                + (("...",) if len(unverified) > 5 else ()),
            )
        )
    return findings


def check_conflicting_labels(dataset: ClassificationDataset) -> list[Finding]:
    """8. One product labelled two different ways.

    A pack is one kind of product. Two panels of it carrying different
    subcategories means at least one is wrong, and training on both teaches
    the model that the same brand and address block are evidence for both.
    """
    findings: list[Finding] = []
    for product, examples in sorted(dataset.by_product().items()):
        for field in ("category", "subcategory"):
            values = sorted({getattr(example, field) for example in examples})
            if len(values) > 1:
                findings.append(
                    Finding(
                        "conflicting-label",
                        ERROR,
                        f"product {product!r} carries {len(values)} different "
                        f"{field} values ({', '.join(values)}); one package is "
                        f"one kind of product",
                        tuple(example.example_id for example in examples),
                    )
                )
    return findings


def check_duplicate_text(dataset: ClassificationDataset) -> list[Finding]:
    """11. The same text twice.

    Across two product ids it is evidence the same pack was imported twice
    under two names - an error, and one `check_duplicate_products` misses when
    the digests differ (two photographs of one pack, or a digest left null).
    Within one product it is a warning: two panels that genuinely read the
    same happens, but it weights that text double.

    Empty text is skipped. A front panel that OCR read as nothing is a real
    outcome the seed set deliberately keeps, and several of them agreeing is
    not a duplicate.
    """
    findings: list[Finding] = []
    groups: dict[str, list[ClassificationExample]] = {}
    for example in dataset.examples:
        normalised = _normalised_text(example.text)
        if normalised:
            groups.setdefault(normalised, []).append(example)
    for examples in groups.values():
        if len(examples) < 2:
            continue
        products = sorted({example.product_id for example in examples})
        ids = tuple(sorted(example.example_id for example in examples))
        if len(products) > 1:
            findings.append(
                Finding(
                    "duplicate-text-across-products",
                    ERROR,
                    f"identical text is labelled under {len(products)} "
                    f"product ids ({', '.join(products)}); either one pack was "
                    f"imported twice or one of these labels is wrong",
                    ids,
                )
            )
        else:
            findings.append(
                Finding(
                    "duplicate-text-within-product",
                    WARNING,
                    f"identical text appears {len(examples)} times under "
                    f"{products[0]!r}; it carries double weight in training "
                    f"and in every metric",
                    ids,
                )
            )
    return findings


def check_class_coverage(dataset: ClassificationDataset) -> list[Finding]:
    """10. Classes with no examples, and classes with too few products."""
    findings: list[Finding] = []
    counts = dataset.label_counts()
    for subcategory in taxonomy.SUBCATEGORIES:
        entry = counts.get(subcategory.code)
        if entry is None:
            findings.append(
                Finding(
                    "empty-class",
                    WARNING,
                    f"subcategory {subcategory.code!r} is defined in the "
                    f"taxonomy and has no example; the vocabulary can express "
                    f"it, no model trained here can produce it",
                    (subcategory.code,),
                )
            )
        elif entry["products"] < MIN_PRODUCTS_PER_CLASS:
            findings.append(
                Finding(
                    "single-product-class",
                    WARNING,
                    f"subcategory {subcategory.code!r} has {entry['examples']} "
                    f"examples from {entry['products']} product; "
                    f"leave-one-product-out cannot measure it - hold that "
                    f"product out and nothing remains to learn the class from",
                    (subcategory.code,),
                )
            )
    return findings


def check_fold_integrity(
    folds: Mapping[str, Iterable[str]],
) -> list[Finding]:
    """9. No product appears in more than one evaluation fold.

    Takes fold name -> product ids, so it can be run over any split: the
    leave-one-product-out folds `train.py` builds, or a future fixed
    train/validation/test partition. A product on both sides of a split means
    the model is measured on a package it was fitted on, and the number that
    comes out predicts nothing.
    """
    findings: list[Finding] = []
    placement: dict[str, list[str]] = {}
    for fold_name, products in folds.items():
        for product in products:
            placement.setdefault(product, []).append(fold_name)
    for product, fold_names in sorted(placement.items()):
        if len(fold_names) > 1:
            findings.append(
                Finding(
                    "product-leakage",
                    ERROR,
                    f"product {product!r} appears in {len(fold_names)} folds "
                    f"({', '.join(sorted(fold_names))}); every text from one "
                    f"package must stay on one side of a split",
                    (product,),
                )
            )
    return findings


def leave_one_product_out_folds(
    dataset: ClassificationDataset,
) -> dict[str, tuple[str, ...]]:
    """The held-out product of each fold `train.py` evaluates, as a mapping.

    One product per fold, which is what makes the split sound. Passing this
    to `check_fold_integrity` is the regression test that it stays that way.
    """
    return {f"holdout:{product}": (product,) for product in dataset.product_ids}


# --- running them all --------------------------------------------------------

#: Every check that needs only the dataset, in report order.
CHECKS = (
    check_product_ids,
    check_duplicate_products,
    check_duplicate_images,
    check_labels_present,
    check_taxonomy_values,
    check_provenance,
    check_conflicting_labels,
    check_duplicate_text,
    check_class_coverage,
)


def validate(
    dataset: ClassificationDataset, *, require_verified: bool = False
) -> tuple[Finding, ...]:
    """Every check, over one dataset. Errors first, then warnings, then info.

    Includes the leave-one-product-out fold-integrity check, because a dataset
    whose own evaluation split leaks is not a valid dataset to quote a number
    from - and the split is derived from the data, so it can be checked here.
    """
    findings: list[Finding] = []
    for check in CHECKS:
        findings.extend(check(dataset))
    findings.extend(check_verification(dataset, require_verified=require_verified))
    findings.extend(check_fold_integrity(leave_one_product_out_folds(dataset)))
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    return tuple(sorted(findings, key=lambda f: (order.get(f.severity, 3), f.code)))


def errors(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    return tuple(finding for finding in findings if finding.severity == ERROR)


def raise_for_errors(findings: Iterable[Finding]) -> None:
    """Refuse loudly. Never repairs, never drops, never continues."""
    found = errors(findings)
    if found:
        raise DatasetIntegrityError(found)


# --- the coverage report -----------------------------------------------------


@dataclass(frozen=True)
class CoverageRow:
    subcategory: str
    category: str
    products: int
    examples: int
    verified: int
    unverified: int


def coverage(dataset: ClassificationDataset) -> tuple[CoverageRow, ...]:
    """One row per taxonomy subcategory, including the ones with nothing in them.

    Empty classes are rows, not omissions. A table that lists only what is
    present reads as though the taxonomy were fully covered.
    """
    by_subcategory: dict[str, list[ClassificationExample]] = {}
    for example in dataset.examples:
        by_subcategory.setdefault(example.subcategory, []).append(example)
    rows = []
    for subcategory in taxonomy.SUBCATEGORIES:
        examples = by_subcategory.get(subcategory.code, [])
        verified = sum(1 for example in examples if example.is_verified)
        rows.append(
            CoverageRow(
                subcategory=subcategory.code,
                category=subcategory.category,
                products=len({example.product_id for example in examples}),
                examples=len(examples),
                verified=verified,
                unverified=len(examples) - verified,
            )
        )
    return tuple(rows)


def format_coverage(dataset: ClassificationDataset) -> str:
    """The coverage table and the dataset totals, as text."""
    rows = coverage(dataset)
    width = max(len(row.subcategory) for row in rows)
    lines = [
        f"{'CATEGORY':{width}s} | PRODUCTS | EXAMPLES | VERIFIED | UNVERIFIED",
        f"{'-' * width}-+----------+----------+----------+-----------",
    ]
    for row in rows:
        lines.append(
            f"{row.subcategory:{width}s} | {row.products:8d} | "
            f"{row.examples:8d} | {row.verified:8d} | {row.unverified:10d}"
        )
    verified = len(dataset.verified_examples)
    lines += [
        "",
        "DATASET TOTALS",
        f"  Products:   {len(dataset.product_ids)}",
        f"  Examples:   {len(dataset.examples)}",
        f"  Images:     {len(dataset.image_sha256s)}",
        f"  Verified:   {verified}",
        f"  Unverified: {len(dataset.examples) - verified}",
    ]
    return "\n".join(lines)


# --- the command -------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m labelextract.classification.validation",
        description=(
            "Validate a product-classification dataset and print its coverage. "
            "Exit 0 when no error-severity finding was raised, 1 otherwise."
        ),
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Dataset JSON. Defaults to the shipped seed set.",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help=(
            "Verification ledger to reconcile the dataset against. Defaults to "
            "the shipped ledger."
        ),
    )
    parser.add_argument(
        "--no-ledger",
        action="store_true",
        help="Skip ledger reconciliation entirely.",
    )
    parser.add_argument(
        "--require-verified",
        action="store_true",
        help="Treat an unverified label as an error rather than a warning.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Findings only; do not print the coverage table.",
    )
    args = parser.parse_args(argv)

    try:
        dataset = load_dataset(args.dataset)
    except ClassificationDataError as exc:
        print(f"dataset could not be loaded: {exc}", file=sys.stderr)
        return 1

    findings = list(validate(dataset, require_verified=args.require_verified))

    if not args.no_ledger:
        # Imported here so `validation` does not import `verification` at
        # module scope - either module must be usable on its own.
        from labelextract.classification import verification

        try:
            ledger = verification.load_ledger(args.ledger)
        except ClassificationDataError as exc:
            print(f"ledger could not be loaded: {exc}", file=sys.stderr)
            return 1
        findings.extend(verification.reconcile(dataset, ledger))

    print(f"dataset:  {dataset.dataset_version}")
    print(f"file:     {dataset.path}")
    print(f"digest:   {dataset.sha256}")
    print(f"taxonomy: {dataset.taxonomy_version}")
    print()
    if not args.quiet:
        print(format_coverage(dataset))
        print()

    if findings:
        print(f"FINDINGS ({len(findings)})")
        for finding in findings:
            print(f"  {finding}")
    else:
        print("No findings.")

    failed = errors(findings)
    print()
    print(
        f"{len(failed)} error(s), "
        f"{sum(1 for f in findings if f.severity == WARNING)} warning(s)."
    )
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
