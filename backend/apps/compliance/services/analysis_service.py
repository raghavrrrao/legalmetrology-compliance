"""One call that runs the whole documented flow, upload to verdict.

    upload
      -> apps.images.services.ingestion        validate, store
      -> apps.extraction.services              OCR, extract, normalise, persist
      -> apps.compliance.services.engine       applicable rules, findings, verdict
      -> ComplianceCheck

Three entry points into that line, differing only in where they join it:

    analyse_upload(file)   the whole line, from an uploaded photograph
    analyse_image(image)   from a stored image: re-read it, then judge
    evaluate_run(run)      from a stored reading: judge it, re-reading nothing

`evaluate_run` is what `POST /api/v1/compliance/` calls, and it is the reason
`POST /api/v1/extraction/` is not a dead end: a caller can look at a reading
first and ask for a verdict on that same reading afterwards.

This module is **composition only**. It contains no validation, no persistence,
no rule evaluation and no verdict logic of its own - every one of those already
exists and is tested, and a second implementation here would be a second thing
to keep correct. Read it as a list of two calls with the awkward parts of
sequencing them handled in one place.

Why it exists rather than living in the view
--------------------------------------------
`docs/api.md` is explicit that business logic belongs in a service and that a
view must never write a `ProductImage` outside the ingestion path. It is also
the case that a management command, a test and a future queue worker all need
this same sequence. Writing it in the view would mean each of those either
duplicates it or skips a step.

Transactions: there are none here, deliberately
-----------------------------------------------
`extraction_service.run_extraction` manages its own transactions so that a
failed extraction still leaves a `failed` ExtractionRun behind explaining why.
Its docstring states that an enclosing `atomic()` discards that record along
with the exception, leaving the image stuck in `processing` with nothing to
show the user. So this module opens no transaction, and neither may its
callers. `engine.evaluate` is separately `@transaction.atomic` already, which
is the correct scope: the check, its violations and its evidence commit
together or not at all.

What a failure looks like
-------------------------
An unreadable photograph is not an error. It produces a `failed` or `empty`
ExtractionRun, and the compliance engine turns that into a REVIEW_REQUIRED
result whose summary says the image could not be read. The caller gets a
complete `AnalysisOutcome` in that case, not an exception - which is the whole
reason the engine has an INCONCLUSIVE state.

Only two things raise: a rejected upload (`ValidationError`, a 400) and an
engine that broke its own output contract (`MalformedExtractionResult`, a bug).
Both are re-raised unchanged so the API layer can tell them apart.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from apps.catalog.models import Product, ProductCategory
from apps.compliance.models import ComplianceCheck
from apps.compliance.services import engine
from apps.extraction.models import ExtractionRun
from apps.extraction.services import extraction_service
from apps.images.models import ProductImage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalysisOutcome:
    """What one upload-through-verdict call produced.

    Thin on purpose, for the same reason `ExtractionOutcome` is: everything
    worth knowing already hangs off these three rows, and copying any of it
    here would create a second copy that can drift from the database.
    """

    image: ProductImage
    run: ExtractionRun
    check: ComplianceCheck

    @property
    def product(self) -> Product | None:
        return self.check.product


def analyse_upload(
    upload,
    *,
    product: Product | None = None,
    category: ProductCategory | None = None,
    uploaded_by=None,
    view_type: str = ProductImage.ViewType.UNSPECIFIED,
    engine_name: str | None = None,
    engine_version: str | None = None,
) -> AnalysisOutcome:
    """Store `upload`, extract from it, and evaluate the result against the rules.

    Args:
        upload: The file as received. Validated by the ingestion service; this
            module never inspects it.
        product: An existing product this photograph shows, when known.
        category: Used only when `product` is None. A minimal `Product` is
            created to carry it, because rule applicability is answered from
            `Product.category` and there is nowhere else to hang it. Ignored
            when `product` is given - that product's own category wins, and
            silently reassigning it would rewrite a record the user did not ask
            to change.
        uploaded_by: The authenticated user, or None.
        view_type: Which panel of the package the photograph shows.
        engine_name: Override the configured pipeline. For comparing engines.
        engine_version: Override the configured pipeline version.

    Returns:
        An `AnalysisOutcome`. Always carries a saved `ComplianceCheck`, even
        when nothing could be read - "we could not read this" is a result the
        user needs, not an absence.

    Raises:
        django.core.exceptions.ValidationError: the upload was rejected.
            Nothing is stored.
        MalformedExtractionResult: the engine broke its output contract. The
            failed run is already recorded; this is re-raised because it is a
            bug rather than an unreadable photograph.
    """
    if product is None and category is not None:
        product = _product_for_category(category, created_by=uploaded_by)

    outcome = extraction_service.ingest_and_extract(
        upload,
        product=product,
        uploaded_by=uploaded_by,
        view_type=view_type,
        engine_name=engine_name,
        engine_version=engine_version,
    )

    check = engine.evaluate(
        outcome.run, product=product, requested_by=uploaded_by
    )

    logger.info(
        "Analysed image %s: extraction=%s, result=%s (%d rule(s) evaluated)",
        outcome.image.pk,
        outcome.run.status,
        check.result,
        check.rules_evaluated,
    )
    return AnalysisOutcome(image=outcome.image, run=outcome.run, check=check)


def evaluate_run(
    run: ExtractionRun,
    *,
    product: Product | None = None,
    category: ProductCategory | None = None,
    requested_by=None,
) -> ComplianceCheck:
    """Evaluate a reading that already exists against the applicable rules.

    The third entry point, and the one that closes the loop opened by
    `POST /api/v1/extraction/`: that endpoint produces an `ExtractionRun` and
    stops, deliberately, at the reading. This turns such a run into a verdict
    **without re-reading the photograph**.

    Re-running OCR to get a verdict would not merely be slow. It would evaluate
    a *different* reading from the one the caller was shown - OCR is not
    guaranteed identical across runs, and the engine may have been reconfigured
    in between - so a finding could cite a value the user never saw. Evaluating
    the stored run is what keeps the reading the user was shown and the verdict
    they were given the same evidence.

    Args:
        run: The reading to judge. Any stored run, however it was produced.
        product: The commodity this reading is of, when known.
        category: Used only when `product` is None, and only when the run's
            image is not already linked to a product. See below.
        requested_by: The authenticated user, or None.

    Returns:
        A saved `ComplianceCheck`, always - including when nothing could be
        read, which the engine reports as REVIEW_REQUIRED with an explanation.

    Nothing about which rules run is decided here, and nothing may be passed in
    to influence it. Applicability is answered by `engine.applicable_rules`
    from the loaded rule set and the commodity's category alone.
    """
    if product is None:
        # An image that already knows its product keeps it. Creating a second
        # product row for the same photograph would split its compliance
        # history in two, and silently reassigning the existing one would
        # rewrite a record the caller did not ask to change.
        product = run.image.product
    if product is None and category is not None:
        product = _product_for_category(category, created_by=requested_by)

    check = engine.evaluate(run, product=product, requested_by=requested_by)

    logger.info(
        "Evaluated extraction run %s: result=%s (%d rule(s) evaluated)",
        run.pk,
        check.result,
        check.rules_evaluated,
    )
    return check


def analyse_image(
    image: ProductImage,
    *,
    product: Product | None = None,
    requested_by=None,
    engine_name: str | None = None,
    engine_version: str | None = None,
) -> AnalysisOutcome:
    """Re-run extraction and evaluation over an image that is already stored.

    The counterpart to `analyse_upload` for an image that has been through
    ingestion before. Both halves stay separate underneath for the reason
    `ingest_and_extract` gives: re-checking an old photograph must not re-upload
    it, and each run is a new row so a better engine can be compared against an
    older one on the same evidence.
    """
    run = extraction_service.run_extraction(
        image, engine_name=engine_name, engine_version=engine_version
    )
    check = engine.evaluate(
        run, product=product or image.product, requested_by=requested_by
    )
    return AnalysisOutcome(image=image, run=run, check=check)


#: Name given to a product row created solely to carry a category for a
#: one-off submission. Written into `Product.name`, which is documented as "a
#: working name for this submission, not a label declaration" - so this is not
#: a claim about what the product is called.
_UNIDENTIFIED_PRODUCT_NAME = "Unidentified submission"


def _product_for_category(
    category: ProductCategory, *, created_by=None
) -> Product:
    """Create the minimal product row needed to make rules applicable.

    `applicable_rules()` answers "which declarations does this commodity need?"
    from `Product.category`, and returns an empty list when there is no
    category - which the engine correctly reports as REVIEW_REQUIRED rather
    than as compliance. So a submission that states its commodity needs
    somewhere to put that, and `Product` is the only place the schema provides.

    A new row per submission rather than a shared one per category: `Product`
    is the unit a compliance history hangs off, and merging unrelated
    submissions into one row would attach every check to the same product.
    Nothing is deduplicated, matching the model's own note that the same
    article may legitimately be submitted more than once.
    """
    return Product.objects.create(
        name=_UNIDENTIFIED_PRODUCT_NAME,
        category=category,
        created_by=created_by,
    )
