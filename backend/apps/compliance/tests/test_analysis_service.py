"""The orchestration service: upload -> extraction -> verdict, in one call.

These tests are about *composition*, not about the components. Validation,
extraction and the verdict logic each have their own suites; what is asserted
here is that the three are joined in the right order, that a failure in the
middle still produces a result the user can be shown, and that the guarantees
the engine makes survive the trip through this layer.

A fake pipeline is registered in the `labelextract` registry and resolved by
name exactly as a real one is, so everything under test is the real service,
the real persistence and the real engine - only recognition is stubbed. That is
the same approach `apps/extraction/tests/test_extraction_service_ocr.py` takes,
and for the same reason: a test that needed Tesseract installed would fail on
half the team's machines and would be measuring recognition rather than wiring.
"""

import pytest

from labelextract import registry
from labelextract.contracts import (
    ExtractedField,
    ImageRef,
    LabelFieldKey,
    OcrResult,
    TextBlock,
)
from labelextract.exceptions import OcrFailureError
from labelextract.interfaces import FieldExtractor, OcrEngine
from labelextract.pipeline import ExtractionPipeline

from apps.catalog.models import Product, ProductCategory
from apps.compliance.models import ComplianceCheck
from apps.compliance.services import analysis_service
from apps.extraction.models import ExtractionRun
from apps.images.models import ProductImage

pytestmark = pytest.mark.django_db

_READING_PIPELINE = "analysis-test-reading"
_FAILING_PIPELINE = "analysis-test-failing"
_TEST_VERSION = "0.0.0"


class _ReadingOcrEngine(OcrEngine):
    """Returns a fixed, plausible reading of a back panel."""

    name = "analysis-test-ocr"
    version = _TEST_VERSION

    def recognise(self, image: ImageRef) -> OcrResult:
        lines = [
            "Net Qty: 500 g",
            "M.R.P. Rs. 250.00 (incl. of all taxes)",
        ]
        # `full_text` is derived from the blocks by the contract, not passed in.
        return OcrResult(
            blocks=tuple(
                TextBlock(text=line, confidence=0.9) for line in lines
            ),
            raw={"source": "analysis-test"},
        )


class _FailingOcrEngine(OcrEngine):
    """An engine that cannot read the image - an ordinary outcome, not a bug."""

    name = "analysis-test-failing-ocr"
    version = _TEST_VERSION

    def recognise(self, image: ImageRef) -> OcrResult:
        raise OcrFailureError("The photograph could not be read")


class _FixedFieldExtractor(FieldExtractor):
    """Reports exactly one declaration, so presence checks have something real."""

    name = "analysis-test-fields"
    version = _TEST_VERSION

    def extract(self, ocr: OcrResult, image: ImageRef):
        return (
            ExtractedField(
                key=LabelFieldKey.NET_QUANTITY,
                raw_value="Net Qty: 500 g",
                normalized_value={"value": 500, "unit": "g"},
                confidence=0.9,
            ),
        )


@pytest.fixture(autouse=True)
def _register_test_pipelines():
    """Register the fakes for the duration of the module.

    The registry refuses to replace an existing key, so registration is guarded
    - the suite may run this module more than once in a session. The instance
    cache is cleared afterwards rather than the registrations removed, because
    `register_pipeline` has no inverse and inventing one here would be a change
    to the ml/ package for a test's convenience.
    """
    registered = {key for key in registry.available_pipelines()}

    if (_READING_PIPELINE, _TEST_VERSION) not in registered:
        registry.register_pipeline(
            _READING_PIPELINE,
            _TEST_VERSION,
            lambda: ExtractionPipeline(
                name=_READING_PIPELINE,
                version=_TEST_VERSION,
                ocr_engine=_ReadingOcrEngine(),
                field_extractor=_FixedFieldExtractor(),
            ),
        )
    if (_FAILING_PIPELINE, _TEST_VERSION) not in registered:
        registry.register_pipeline(
            _FAILING_PIPELINE,
            _TEST_VERSION,
            lambda: ExtractionPipeline(
                name=_FAILING_PIPELINE,
                version=_TEST_VERSION,
                ocr_engine=_FailingOcrEngine(),
            ),
        )
    yield
    registry.clear_cache()


def _analyse(upload, **kwargs):
    return analysis_service.analyse_upload(
        upload,
        engine_name=_READING_PIPELINE,
        engine_version=_TEST_VERSION,
        **kwargs,
    )


# --- the composition itself --------------------------------------------------


def test_one_call_produces_an_image_a_run_and_a_check(png_upload, media_root):
    """The whole documented flow, end to end, in one call."""
    outcome = _analyse(png_upload)

    assert isinstance(outcome.image, ProductImage)
    assert isinstance(outcome.run, ExtractionRun)
    assert isinstance(outcome.check, ComplianceCheck)

    # Every row was actually written, not just constructed.
    assert ProductImage.objects.filter(pk=outcome.image.pk).exists()
    assert ExtractionRun.objects.filter(pk=outcome.run.pk).exists()
    assert ComplianceCheck.objects.filter(pk=outcome.check.pk).exists()

    # And they are joined to each other, not three unrelated rows.
    assert outcome.run.image_id == outcome.image.pk
    assert outcome.check.extraction_run_id == outcome.run.pk


def test_the_reading_reaches_the_database(png_upload, media_root):
    """Extraction ran for real: the declaration the engine reported is stored."""
    outcome = _analyse(png_upload)

    assert outcome.run.status == ExtractionRun.Status.COMPLETED
    stored = {field.field_key for field in outcome.run.fields.all()}
    assert stored == {LabelFieldKey.NET_QUANTITY.value}


def test_the_check_is_completed_not_left_running(png_upload, media_root):
    """A caller must never receive a check still in RUNNING."""
    outcome = _analyse(png_upload)

    assert outcome.check.status == ComplianceCheck.Status.COMPLETED
    assert outcome.check.completed_at is not None
    assert outcome.check.summary != ""


# --- the guarantees survive this layer ---------------------------------------


def test_with_no_rules_loaded_the_result_is_review_required(
    png_upload, media_root, category
):
    """Engine guarantee 1, reached through the service.

    Rules do ship now, but this test loads none, so a perfectly readable
    label still yields REVIEW_REQUIRED. Not COMPLIANT - nothing was checked,
    which is not the same as nothing being wrong. The same guarantee against
    the real shipped rules is in apps/rules/tests/test_shipped_definitions.py.
    """
    outcome = _analyse(png_upload, category=category)

    assert outcome.check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    assert outcome.check.rules_evaluated == 0


def test_a_verified_rule_that_passes_yields_compliant(
    png_upload, media_root, category, make_rule
):
    """The COMPLIANT path exists and is reachable - with a rule that passes.

    Uses a fixture rule rather than a shipped one, so this stays a test of
    the wiring rather than of any legal conclusion.
    """
    make_rule(code="ANALYSIS-PASS", field_key="net_quantity", verified=True)

    outcome = _analyse(png_upload, category=category)

    assert outcome.check.result == ComplianceCheck.Result.COMPLIANT
    assert outcome.check.rules_passed == 1
    assert outcome.check.violations.count() == 0


def test_a_verified_rule_that_fails_yields_non_compliant_with_evidence(
    png_upload, media_root, category, make_rule
):
    """A finding carries its rule code and the text that justifies it."""
    make_rule(
        code="ANALYSIS-FAIL", field_key="consumer_care_contact", verified=True
    )

    outcome = _analyse(png_upload, category=category)

    assert outcome.check.result == ComplianceCheck.Result.NON_COMPLIANT
    violation = outcome.check.violations.get()
    assert violation.rule_code == "ANALYSIS-FAIL"
    assert violation.field_key == "consumer_care_contact"
    # The evidence is what we DID read - the justification for the absence.
    assert violation.evidence.exists()


def test_an_unverified_rule_can_never_make_a_product_non_compliant(
    png_upload, media_root, category, make_rule
):
    """Engine guarantee 2, reached through the service."""
    make_rule(
        code="ANALYSIS-UNVERIFIED",
        field_key="consumer_care_contact",
        verified=False,
    )

    outcome = _analyse(png_upload, category=category)

    assert outcome.check.result != ComplianceCheck.Result.NON_COMPLIANT
    assert outcome.check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    assert outcome.check.violations.count() == 0


def test_an_unreadable_image_is_a_result_not_an_exception(
    png_upload, media_root, category, make_rule
):
    """Engine guarantee 3: a failed read is REVIEW_REQUIRED, never a violation.

    The caller still gets a complete outcome. A photograph nobody could read is
    something the user needs to be told about, not an error to swallow.
    """
    make_rule(code="ANALYSIS-UNREADABLE", field_key="net_quantity")

    outcome = analysis_service.analyse_upload(
        png_upload,
        category=category,
        engine_name=_FAILING_PIPELINE,
        engine_version=_TEST_VERSION,
    )

    assert outcome.run.status == ExtractionRun.Status.FAILED
    assert outcome.check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    assert outcome.check.violations.count() == 0


def test_a_failed_extraction_still_leaves_its_failure_record(
    png_upload, media_root
):
    """The reason this service opens no transaction of its own.

    `run_extraction` documents that an enclosing `atomic()` discards the
    failure record along with the exception, leaving the image stuck in
    PROCESSING with nothing explaining why. This asserts the record survives
    the trip through the orchestration layer.
    """
    outcome = analysis_service.analyse_upload(
        png_upload,
        engine_name=_FAILING_PIPELINE,
        engine_version=_TEST_VERSION,
    )

    run = ExtractionRun.objects.get(pk=outcome.run.pk)
    assert run.status == ExtractionRun.Status.FAILED
    assert run.error_code != ""
    assert run.error_message != ""

    image = ProductImage.objects.get(pk=outcome.image.pk)
    assert image.status == ProductImage.Status.FAILED


# --- category handling -------------------------------------------------------


def test_without_a_category_the_result_says_the_commodity_is_unknown(
    png_upload, media_root
):
    """Not knowing the commodity is reported, never guessed at."""
    outcome = _analyse(png_upload)

    assert outcome.check.product is None
    assert outcome.check.result == ComplianceCheck.Result.REVIEW_REQUIRED
    assert "category" in outcome.check.summary.lower()


def test_a_category_creates_the_product_row_that_carries_it(
    png_upload, media_root, category
):
    """Rule applicability is answered from Product.category, so one is needed."""
    outcome = _analyse(png_upload, category=category)

    assert outcome.check.product is not None
    assert outcome.check.product.category_id == category.pk
    assert outcome.image.product_id == outcome.check.product.pk


def test_an_explicit_product_is_used_and_its_category_is_not_reassigned(
    png_upload, media_root, product, category
):
    """A caller's product wins over a category argument.

    Silently reassigning an existing product's category would rewrite a record
    the caller did not ask to change.
    """
    other = ProductCategory.objects.create(code="other-cat", name="Other")

    outcome = _analyse(png_upload, product=product, category=other)

    assert outcome.check.product_id == product.pk
    product.refresh_from_db()
    assert product.category_id == category.pk


def test_no_product_row_is_created_when_no_category_is_given(
    png_upload, media_root
):
    """The upload-then-identify workflow: an unidentified photo stays that way."""
    before = Product.objects.count()

    _analyse(png_upload)

    assert Product.objects.count() == before


# --- re-analysing an image already stored ------------------------------------


def test_analyse_image_reruns_without_re_uploading(
    png_upload, media_root, category
):
    """Re-checking an old photograph adds a run; it does not add an image."""
    first = _analyse(png_upload, category=category)
    image_count = ProductImage.objects.count()

    second = analysis_service.analyse_image(
        first.image,
        engine_name=_READING_PIPELINE,
        engine_version=_TEST_VERSION,
    )

    assert ProductImage.objects.count() == image_count
    assert second.image.pk == first.image.pk
    # A new run and a new check, so nothing the first result cited is destroyed.
    assert second.run.pk != first.run.pk
    assert second.check.pk != first.check.pk
    assert ExtractionRun.objects.filter(image=first.image).count() == 2
