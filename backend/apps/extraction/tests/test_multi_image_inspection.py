"""Several photographs of one package, read into one inspection.

The property under test throughout this file is the one the architecture rests
on: **N photographs produce one `ExtractionRun`, not N runs.** A packaged
commodity declares different things on different panels, so a verdict about the
package has to be reached from every panel at once. Anything that quietly
turned a set of photographs back into a set of independent readings would still
look plausible on screen, which is why it is pinned here rather than left to
the interface to get right.

Grouped as:

    A. the set becomes one run
    B. which photograph each declaration came from
    C. one bad photograph does not fail the inspection
    D. a single photograph still behaves exactly as it always did
    E. the request shape, over HTTP
    F. rejections

Recognition is stubbed and only recognition, the same way
`test_extraction_api.py` does it: fake pipelines are registered in the real
`labelextract` registry and resolved by name, so ingestion, the validators, the
contract check, the persistence and the serializers under test are all real.
The stub here is per-image - it reads a different declaration off each
photograph - because that is the only way to see whether the merge kept track
of which is which.
"""

from __future__ import annotations

import importlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from labelextract import registry
from labelextract.contracts import (
    BoundingBox,
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    ImageRef,
    LabelFieldKey,
    OcrResult,
    TextBlock,
)
from labelextract.exceptions import OcrFailureError
from labelextract.interfaces import OcrEngine
from labelextract.pipeline import ExtractionPipeline

from apps.extraction.models import ExtractedLabelField, ExtractionRun, ExtractionRunImage
from apps.extraction.services import extraction_service
from apps.images.constants import MAX_IMAGES_PER_INSPECTION
from apps.images.models import ProductImage
from apps.rules.checks.base import CheckContext

pytestmark = pytest.mark.django_db

_PANEL_PIPELINE = "multi-image-panels"
_ONE_BAD_PIPELINE = "multi-image-one-bad"
_TEST_VERSION = "0.0.0"


# --- a pipeline that reads a different panel every time it is called ---------


class _UnusedOcrEngine(OcrEngine):
    """Satisfies the pipeline's constructor and is never called.

    The stubs below override `run`, so the recognise/extract halves a real
    pipeline composes are not reached. `ExtractionPipeline` still requires an
    engine - correctly, since a pipeline without one could read nothing - so
    one is supplied. It raises rather than returning an empty result, because a
    stub that silently produced a reading nobody wrote would make a broken
    override look like a passing test.
    """

    name = "multi-image-unused-ocr"
    version = _TEST_VERSION

    def recognise(self, image: ImageRef) -> OcrResult:
        raise AssertionError("run() is overridden; this must not be reached")



class _PanelPipeline(ExtractionPipeline):
    """Reads a different declaration off each successive photograph.

    Real OCR reads whatever is in front of it; this reads position 1 as a panel
    carrying the net quantity, position 2 as one carrying the retail sale
    price, and position 3 as one carrying the date of manufacture, cycling
    after that. Which photograph produced which declaration is exactly what the
    merge has to keep straight, and a stub that returned the same reading every
    time could not tell a correct merge from one that lost the attribution.

    Counting calls is legitimate here for the same reason: the pipeline is
    resolved once per run and called once per photograph, and the count is how
    the stub knows which panel it is looking at.
    """

    #: Class-level so the count survives the registry handing out a fresh
    #: pipeline per `get_pipeline` call. Reset by the fixture below.
    calls = 0

    #: The declaration each successive photograph carries.
    _PANELS = [
        (LabelFieldKey.NET_QUANTITY, "Net Qty: 500 g", {"quantity": 500, "unit": "g"}),
        (
            LabelFieldKey.RETAIL_SALE_PRICE,
            "M.R.P. Rs. 250.00 (incl. of all taxes)",
            {"amount": 250.0, "currency": "INR"},
        ),
        (
            LabelFieldKey.DATE_OF_MANUFACTURE,
            "Mfd. 03/2026",
            {"month": 3, "year": 2026},
        ),
    ]

    def run(self, image: ImageRef) -> ExtractionResult:
        index = type(self).calls
        type(self).calls += 1
        key, raw_value, normalised = self._PANELS[index % len(self._PANELS)]
        return ExtractionResult(
            status=ExtractionStatus.COMPLETED,
            engine_name=self.name,
            engine_version=self.version,
            processing_ms=10 + index,
            ocr=OcrResult(
                blocks=(
                    TextBlock(
                        text=raw_value,
                        box=BoundingBox(x=4, y=4, width=300, height=18),
                        confidence=0.9,
                    ),
                ),
                # `full_text` is derived from the blocks, not passed in.
                raw={"panel": index},
            ),
            fields=(
                ExtractedField(
                    key=key,
                    raw_value=raw_value,
                    normalized_value=normalised,
                    confidence=0.9,
                    box=BoundingBox(x=4, y=4, width=300, height=18),
                ),
            ),
            metadata={"unread_declarations": []},
        )


class _OneBadPanelPipeline(_PanelPipeline):
    """The same, except the second photograph cannot be read at all.

    The realistic multi-image failure: two good panels and one out-of-focus
    close-up. `OcrFailureError` is an ordinary outcome, not a bug, so the set
    must survive it.
    """

    def run(self, image: ImageRef) -> ExtractionResult:
        if type(self).calls == 1:
            type(self).calls += 1
            raise OcrFailureError("That photograph could not be read")
        return super().run(image)


@pytest.fixture(autouse=True)
def _register_test_pipelines():
    """Register the fakes, and reset their call counters per test.

    The registry refuses to replace an existing key and has no inverse, so
    registration is guarded rather than undone - the same arrangement
    `test_extraction_api.py` uses, and for the same reason.
    """
    registered = set(registry.available_pipelines())

    def _ensure(name, cls):
        if (name, _TEST_VERSION) not in registered:
            registry.register_pipeline(
                name,
                _TEST_VERSION,
                lambda cls=cls, name=name: cls(
                    name=name,
                    version=_TEST_VERSION,
                    ocr_engine=_UnusedOcrEngine(),
                ),
            )

    _ensure(_PANEL_PIPELINE, _PanelPipeline)
    _ensure(_ONE_BAD_PIPELINE, _OneBadPanelPipeline)
    _PanelPipeline.calls = 0
    _OneBadPanelPipeline.calls = 0
    yield
    _PanelPipeline.calls = 0
    _OneBadPanelPipeline.calls = 0


@pytest.fixture
def panels(settings):
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = _PANEL_PIPELINE
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _TEST_VERSION


@pytest.fixture
def one_bad_panel(settings):
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = _ONE_BAD_PIPELINE
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _TEST_VERSION


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    """The HTTP tests in section E reach the endpoints anonymously.

    Permissions are asserted in the endpoints' own test modules; defaulting the
    switch on here keeps this file about image sets.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = True


def _uploads(png_bytes, count):
    """`count` distinct uploads of the same real PNG bytes.

    Distinct filenames, because the point is several photographs of one
    package, and identical bytes are fine - nothing deduplicates on checksum,
    and the validators care about the bytes rather than the name.
    """
    return [
        SimpleUploadedFile(f"panel-{index}.png", png_bytes, content_type="image/png")
        for index in range(1, count + 1)
    ]


def _post(client, png_bytes, count=3, view_types=None, route="v1:label-extract"):
    payload: dict = {"image": _uploads(png_bytes, count)}
    if view_types is not None:
        payload["view_type"] = view_types
    return client.post(reverse(route), payload, format="multipart")


# --- A. the set becomes one run ---------------------------------------------


def test_three_photographs_produce_one_run_not_three(
    png_bytes, media_root, panels
):
    """The whole design, asserted directly.

    Three runs would mean three compliance checks and three verdicts about one
    package - and a net quantity printed only on the back would make the front
    photograph's verdict read as a missing declaration.
    """
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 3))

    assert ExtractionRun.objects.count() == 1
    assert ProductImage.objects.count() == 3
    assert len(outcome.images) == 3
    assert outcome.run.run_images.count() == 3


def test_every_declaration_of_every_panel_is_on_the_one_run(
    png_bytes, media_root, panels
):
    """Three panels, three different declarations, one reading of the package."""
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 3))

    assert {field.field_key for field in outcome.run.fields.all()} == {
        LabelFieldKey.NET_QUANTITY.value,
        LabelFieldKey.RETAIL_SALE_PRICE.value,
        LabelFieldKey.DATE_OF_MANUFACTURE.value,
    }


def test_the_positions_are_the_order_the_photographs_were_submitted(
    png_bytes, media_root, panels
):
    """`position` is the number a person is shown, so it must be the order sent."""
    uploads = _uploads(png_bytes, 3)
    outcome = extraction_service.ingest_and_extract_all(uploads)

    links = list(outcome.run.run_images.all())
    assert [link.position for link in links] == [1, 2, 3]
    assert [link.image.original_filename for link in links] == [
        "panel-1.png",
        "panel-2.png",
        "panel-3.png",
    ]


def test_the_primary_photograph_is_the_first_one_submitted(
    png_bytes, media_root, panels
):
    """`ExtractionRun.image` stays meaningful: it is position 1."""
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 3))

    assert outcome.run.image_id == outcome.images[0].pk
    assert outcome.image is outcome.images[0]
    assert outcome.run.run_images.get(position=1).image_id == outcome.run.image_id


def test_the_recognised_text_of_the_set_is_every_panel_joined(
    png_bytes, media_root, panels
):
    """One label's worth of text, read off several panels."""
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 3))

    assert outcome.run.recognised_text == (
        "Net Qty: 500 g\n"
        "M.R.P. Rs. 250.00 (incl. of all taxes)\n"
        "Mfd. 03/2026"
    )


def test_the_processing_time_is_the_total_spent_in_the_pipeline(
    png_bytes, media_root, panels
):
    """A sum, because the photographs are read one after another."""
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 3))

    # The stub reports 10, 11, 12 ms for successive photographs.
    assert outcome.run.processing_ms == 33
    assert [link.processing_ms for link in outcome.run.run_images.all()] == [10, 11, 12]


def test_the_view_types_are_applied_positionally_and_never_copied(
    png_bytes, media_root, panels
):
    """Saying the first photograph is the front says nothing about the second."""
    outcome = extraction_service.ingest_and_extract_all(
        _uploads(png_bytes, 3),
        view_types=[ProductImage.ViewType.FRONT, ProductImage.ViewType.BACK],
    )

    assert [image.view_type for image in outcome.images] == [
        ProductImage.ViewType.FRONT,
        ProductImage.ViewType.BACK,
        # Not repeated from the last stated value: nobody said what this is.
        ProductImage.ViewType.UNSPECIFIED,
    ]


# --- B. which photograph each declaration came from --------------------------


def test_each_declaration_records_the_photograph_it_was_read_from(
    png_bytes, media_root, panels
):
    """The link that lets a finding cite "image 2" rather than "the package"."""
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 3))
    by_key = {field.field_key: field for field in outcome.run.fields.all()}

    assert by_key[LabelFieldKey.NET_QUANTITY.value].image_id == outcome.images[0].pk
    assert (
        by_key[LabelFieldKey.RETAIL_SALE_PRICE.value].image_id == outcome.images[1].pk
    )
    assert (
        by_key[LabelFieldKey.DATE_OF_MANUFACTURE.value].image_id == outcome.images[2].pk
    )


def test_a_declaration_read_off_two_panels_keeps_both_readings(
    png_bytes, media_root, panels
):
    """Nothing is discarded, because both readings are real observations.

    Four photographs cycle the stub's three panels, so the fourth repeats the
    first: the same declaration, read twice, off two different photographs.
    """
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 4))

    net_quantity = list(
        outcome.run.fields.filter(field_key=LabelFieldKey.NET_QUANTITY.value)
    )
    assert len(net_quantity) == 2
    assert {reading.image_id for reading in net_quantity} == {
        outcome.images[0].pk,
        outcome.images[3].pk,
    }


def test_the_earliest_photograph_supplies_the_reading_the_rules_judge(
    png_bytes, media_root, panels
):
    """The one place a duplicate reading is resolved, and it resolves by position.

    Not by confidence: OCR confidence is an opinion about characters, not about
    which panel carries the authoritative declaration.
    """
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 4))

    context = CheckContext.from_run(outcome.run)
    selected = context.field(LabelFieldKey.NET_QUANTITY.value)

    assert selected is not None
    assert selected.image_id == outcome.images[0].pk


def test_the_selection_is_stable_across_repeated_builds(
    png_bytes, media_root, panels
):
    """Two evaluations of one reading must not judge different evidence."""
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 4))

    first = CheckContext.from_run(ExtractionRun.objects.get(pk=outcome.run.pk))
    second = CheckContext.from_run(ExtractionRun.objects.get(pk=outcome.run.pk))

    assert (
        first.field(LabelFieldKey.NET_QUANTITY.value).pk
        == second.field(LabelFieldKey.NET_QUANTITY.value).pk
    )


def test_a_reading_survives_the_deletion_of_the_photograph_it_came_from(
    png_bytes, media_root, panels
):
    """SET_NULL, not CASCADE: a finding must not lose its evidence with an image.

    The reading stays and its `image` becomes null, which the API documents as
    "the source was not recorded" rather than "no image was involved".
    """
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 3))
    reading = outcome.run.fields.get(field_key=LabelFieldKey.RETAIL_SALE_PRICE.value)

    outcome.images[1].delete()
    reading.refresh_from_db()

    assert ExtractedLabelField.objects.filter(pk=reading.pk).exists()
    assert reading.image_id is None
    assert reading.raw_value == "M.R.P. Rs. 250.00 (incl. of all taxes)"


# --- C. one bad photograph does not fail the inspection ----------------------


def test_one_unreadable_photograph_does_not_fail_the_whole_inspection(
    png_bytes, media_root, one_bad_panel
):
    """Two good panels and a blurred close-up is a worse photograph set, not an
    unreadable package."""
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 3))

    assert outcome.run.status == ExtractionRun.Status.COMPLETED
    assert outcome.run.produced_usable_output is True
    assert outcome.run.error_code == ""


def test_the_unreadable_photograph_is_still_reported_as_unreadable(
    png_bytes, media_root, one_bad_panel
):
    """It must not disappear: a submitter needs to know image 2 contributed
    nothing."""
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 3))
    links = {link.position: link for link in outcome.run.run_images.all()}

    assert links[1].status == ExtractionRunImage.Status.COMPLETED
    assert links[2].status == ExtractionRunImage.Status.FAILED
    assert links[2].error_code == "ocr_failed"
    assert links[3].status == ExtractionRunImage.Status.COMPLETED


def test_the_unreadable_photographs_own_row_is_marked_failed(
    png_bytes, media_root, one_bad_panel
):
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 3))

    outcome.images[1].refresh_from_db()
    outcome.images[0].refresh_from_db()
    assert outcome.images[1].status == ProductImage.Status.FAILED
    assert outcome.images[0].status == ProductImage.Status.PROCESSED


def test_the_declarations_of_the_readable_panels_are_all_kept(
    png_bytes, media_root, one_bad_panel
):
    """Photographs 1 and 3 were read; the declaration only photograph 2 carried
    is simply absent, which is the honest outcome of not being able to read
    it."""
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 3))

    assert {field.field_key for field in outcome.run.fields.all()} == {
        LabelFieldKey.NET_QUANTITY.value,
        LabelFieldKey.DATE_OF_MANUFACTURE.value,
    }


def test_a_set_whose_every_photograph_failed_is_a_failed_run(
    png_bytes, media_root, settings
):
    """The same outcome a single unreadable photograph has always produced."""
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = _ONE_BAD_PIPELINE
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _TEST_VERSION
    # Start the counter where every call raises.
    _OneBadPanelPipeline.calls = 1

    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 1))

    assert outcome.run.status == ExtractionRun.Status.FAILED
    assert outcome.run.produced_usable_output is False
    assert outcome.run.error_code == "ocr_failed"


# --- D. a single photograph behaves exactly as it always did -----------------


def test_a_single_photograph_still_makes_a_run_of_one(
    png_bytes, media_root, panels
):
    outcome = extraction_service.ingest_and_extract(
        SimpleUploadedFile("label.png", png_bytes, content_type="image/png")
    )

    assert outcome.run.image_id == outcome.image.pk
    assert outcome.images == (outcome.image,)
    assert list(outcome.run.run_images.values_list("position", flat=True)) == [1]


def test_a_single_photographs_raw_output_keeps_exactly_the_keys_it_had(
    png_bytes, media_root, panels
):
    """No new key on the single-image shape: anything reading one goes on working.

    The per-photograph breakdown is added only for a genuine set.
    """
    outcome = extraction_service.ingest_and_extract(
        SimpleUploadedFile("label.png", png_bytes, content_type="image/png")
    )

    assert set(outcome.run.raw_output) == {"engine_raw", "metadata", "block_count"}
    assert outcome.run.raw_output["metadata"] == {"unread_declarations": []}


def test_a_set_records_its_per_photograph_breakdown_in_raw_output(
    png_bytes, media_root, one_bad_panel
):
    outcome = extraction_service.ingest_and_extract_all(_uploads(png_bytes, 3))

    breakdown = outcome.run.raw_output["images"]
    assert [entry["position"] for entry in breakdown] == [1, 2, 3]
    assert [entry["status"] for entry in breakdown] == ["completed", "failed", "completed"]
    assert breakdown[1]["error_code"] == "ocr_failed"


def test_run_extraction_over_a_single_stored_image_matches_run_extraction(
    product_image, panels
):
    """The two doors onto one photograph must produce the same reading."""
    one = extraction_service.run_extraction(product_image)
    _PanelPipeline.calls = 0
    other = extraction_service.run_extraction_over([product_image])

    assert one.status == other.status
    assert one.recognised_text == other.recognised_text
    assert (
        list(one.fields.values_list("field_key", "raw_value"))
        == list(other.fields.values_list("field_key", "raw_value"))
    )


# --- E. the request shape, over HTTP -----------------------------------------


def test_repeating_the_image_part_uploads_a_set(client, png_bytes, media_root, panels):
    """The multipart form of a set: the same key, sent more than once."""
    response = _post(client, png_bytes, count=3)

    assert response.status_code == 201
    body = response.json()
    assert [entry["position"] for entry in body["images"]] == [1, 2, 3]
    assert body["image"]["id"] == body["images"][0]["image"]["id"]


def test_each_declaration_in_the_response_names_its_photograph(
    client, png_bytes, media_root, panels
):
    """Image-level evidence, as the client receives it."""
    body = _post(client, png_bytes, count=3).json()

    ids = [entry["image"]["id"] for entry in body["images"]]
    by_key = {field["field_key"]: field for field in body["fields_read"]}

    assert by_key["net_quantity"]["image_id"] == ids[0]
    assert by_key["retail_sale_price"]["image_id"] == ids[1]
    assert by_key["date_of_manufacture"]["image_id"] == ids[2]


def test_view_types_are_sent_positionally_over_the_wire(
    client, png_bytes, media_root, panels
):
    body = _post(
        client,
        png_bytes,
        count=3,
        view_types=[ProductImage.ViewType.FRONT, ProductImage.ViewType.BACK],
    ).json()

    assert [entry["image"]["view_type"] for entry in body["images"]] == [
        "front",
        "back",
        "unspecified",
    ]


def test_a_single_image_request_is_unchanged(client, png_bytes, media_root, panels):
    """The request this API has always accepted, answered as it always was."""
    response = client.post(
        reverse("v1:label-extract"),
        {"image": SimpleUploadedFile("label.png", png_bytes, content_type="image/png")},
        format="multipart",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["image"]["original_filename"] == "label.png"
    # The set is still described - as a set of one, which is what it is.
    assert len(body["images"]) == 1
    assert body["images"][0]["position"] == 1


def test_a_run_made_before_image_sets_existed_still_describes_its_photograph(
    client, completed_run
):
    """No membership rows, because the fixture writes the run directly.

    The response must describe the photograph the run read rather than claim it
    read none - which is what an empty `images` list would say.
    """
    from apps.extraction.api.serializers import ExtractionResponseSerializer

    body = ExtractionResponseSerializer(completed_run).data

    assert len(body["images"]) == 1
    assert body["images"][0]["position"] == 1
    assert body["images"][0]["image"]["id"] == str(completed_run.image_id)
    assert body["images"][0]["status"] == "completed"


# --- F. rejections ------------------------------------------------------------


def test_too_many_photographs_are_rejected_as_a_bad_request(
    client, png_bytes, media_root, panels
):
    response = _post(client, png_bytes, count=MAX_IMAGES_PER_INSPECTION + 1)

    assert response.status_code == 400
    assert "image" in response.json()["error"]["details"]
    assert ExtractionRun.objects.count() == 0


def test_no_photograph_at_all_is_rejected_naming_the_field(
    client, png_bytes, media_root, panels
):
    """Unchanged from the single-image contract: `details.image` says what is
    missing."""
    response = client.post(reverse("v1:label-extract"), {}, format="multipart")

    assert response.status_code == 400
    assert "image" in response.json()["error"]["details"]


def test_one_rejected_photograph_rejects_the_whole_request(
    client, png_bytes, media_root, panels
):
    """A set is one inspection, so a file the validators refuse fails all of it.

    Half an inspection is not a thing the submitter asked for, and reporting a
    partial success would leave them believing a panel was checked when it was
    not.
    """
    response = client.post(
        reverse("v1:label-extract"),
        {
            "image": [
                SimpleUploadedFile("panel-1.png", png_bytes, content_type="image/png"),
                SimpleUploadedFile("panel-2.txt", b"not an image", content_type="text/plain"),
            ]
        },
        format="multipart",
    )

    assert response.status_code == 400
    assert "image" in response.json()["error"]["details"]
    assert ExtractionRun.objects.count() == 0


def test_the_same_stored_photograph_twice_is_refused(product_image, panels):
    """It would double-count the declarations, and breach the row's uniqueness."""
    with pytest.raises(ValueError, match="more than once"):
        extraction_service.run_extraction_over([product_image, product_image])


def test_an_empty_set_is_refused(panels):
    with pytest.raises(ValueError, match="at least one"):
        extraction_service.run_extraction_over([])


# --- G. the backfill that gave old runs their set ----------------------------

#: The migration's module name starts with a digit, so it cannot be reached
#: with an import statement.
_BACKFILL = "apps.extraction.migrations.0003_backfill_run_image_set"


def test_the_backfill_gives_an_existing_run_the_set_it_always_had(
    completed_run, make_extracted_field
):
    """`0003_backfill_run_image_set`, exercised against real rows.

    The migration runs on an empty database when the test database is built, so
    nothing else in the suite sees it do any work. What it does is the whole
    point: a run written before image sets existed read exactly one photograph,
    and leaving its columns null would make every historical reading
    indistinguishable from one whose source is genuinely unknown - so a result
    page would stop citing an image for findings that have always had one.

    Driven through the migration's own functions with the live app registry.
    They take `apps` precisely so they do not depend on the current model
    classes, and calling them with the real ones runs the same statements
    against the same schema. The fixture writes its run directly, which is
    exactly the shape a pre-migration row has: no membership rows, and readings
    with no image.
    """
    from django.apps import apps as live_apps

    migration = importlib.import_module(_BACKFILL)

    reading = make_extracted_field(completed_run, "net_quantity")
    assert reading.image_id is None
    assert completed_run.run_images.count() == 0

    migration.backfill(live_apps, None)

    reading.refresh_from_db()
    link = completed_run.run_images.get()
    assert link.position == 1
    assert link.image_id == completed_run.image_id
    assert link.status == ExtractionRunImage.Status.COMPLETED
    assert reading.image_id == completed_run.image_id


def test_the_backfill_records_an_old_failed_run_as_a_failed_photograph(
    product_image, png_bytes
):
    """A run stuck in `running` has no per-photograph equivalent of that state.

    Recorded as failed, which is what its image's own status already says: a
    membership row is only ever written once the pipeline has finished with an
    image, so there is no honest way to describe an interrupted one as
    anything else.
    """
    from django.apps import apps as live_apps

    migration = importlib.import_module(_BACKFILL)

    interrupted = ExtractionRun.objects.create(
        image=product_image,
        engine_name="stub",
        engine_version="0.0.0",
        status=ExtractionRun.Status.RUNNING,
    )

    migration.backfill(live_apps, None)

    assert interrupted.run_images.get().status == ExtractionRunImage.Status.FAILED


def test_the_backfill_can_be_undone(completed_run, make_extracted_field):
    """Reverting returns the rows to exactly the state before it ran."""
    from django.apps import apps as live_apps

    migration = importlib.import_module(_BACKFILL)

    reading = make_extracted_field(completed_run, "net_quantity")
    migration.backfill(live_apps, None)
    migration.unbackfill(live_apps, None)

    reading.refresh_from_db()
    assert completed_run.run_images.count() == 0
    assert reading.image_id is None
