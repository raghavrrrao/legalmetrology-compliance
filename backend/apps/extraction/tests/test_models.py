"""Database guarantees the extraction tables are relied on to keep.

The service layer is tested elsewhere (`test_extraction_service.py`). This file
tests the *schema*: what the database will and will not accept, what survives a
round trip, and what happens to children when a parent goes away.

Why these particular guarantees
-------------------------------
Two of them are load-bearing for the whole system and neither had a test:

1. **`field_key` is a plain `CharField` on purpose.** The vocabulary belongs to
   `labelextract.contracts.LabelFieldKey`, so the ML team can add a declaration
   without the backend shipping a migration. That is a deliberate architectural
   decision (see the field's `help_text` and `ARCHITECTURE.md`), and nothing
   asserted it - so a well-meaning `choices=` addition would have looked like a
   tidy-up and silently coupled the two layers.

2. **An uncertain reading must stay uncertain.** `normalized_value` is the only
   place the uncertainty flag, its reasons and the competing candidates are
   kept. If a round trip dropped or flattened any of them, the backend would be
   quietly converting "we could not tell which number is the net quantity" into
   "there is no net quantity" - which `field_presence` reads as a missing
   declaration, turning an ambiguous reading into a violation.

Nothing here asserts a legal requirement. Whether a declaration is *required*
is decided by verified `ComplianceRule` rows, not by this table.
"""

from __future__ import annotations

import pytest
from django.db import connection

from labelextract.contracts import LabelFieldKey

from apps.extraction.models import ExtractedLabelField, ExtractionRun


# --- the field-key vocabulary belongs to ml/ --------------------------------


def test_every_current_label_field_key_can_be_stored(
    completed_run, make_extracted_field
):
    """The backend must accept the whole ML vocabulary as it stands today."""
    for key in LabelFieldKey:
        make_extracted_field(completed_run, key.value)

    stored = set(
        ExtractedLabelField.objects.filter(run=completed_run).values_list(
            "field_key", flat=True
        )
    )
    assert stored == {key.value for key in LabelFieldKey}


def test_a_field_key_the_ml_layer_has_not_invented_yet_is_storable(
    completed_run, make_extracted_field
):
    """Adding a declaration in ml/ must not require a backend migration.

    The service layer still validates the key against `LabelFieldKey` before
    writing (`extraction_service._validated_key`), so this tolerance is at the
    schema level only - it is headroom for the ML vocabulary to grow, not a
    licence for arbitrary strings to arrive through the front door.
    """
    field = make_extracted_field(completed_run, "a_declaration_added_next_sprint")
    field.refresh_from_db()
    assert field.field_key == "a_declaration_added_next_sprint"


def test_field_key_declares_no_database_level_choices():
    """The vocabulary lives in ml/, and adding `choices=` would move it here.

    Asserted directly on the field rather than by trying to store a bad value,
    because Django's `choices` are **not** enforced by the database or by
    `Model.objects.create()` - only by `full_clean()`. A test that wrote an
    unknown key and expected an error would therefore pass whether or not the
    coupling had been introduced, which is worse than no test.

    What `choices=` would actually cost is a migration every time `ml/` names a
    new declaration, plus a second list of field keys to keep in step with
    `LabelFieldKey`. `engine_version` is checked for the same reason: the ML
    layer owns its version numbering, and a version the backend refuses to
    store is a run the backend cannot record.
    """
    assert not ExtractedLabelField._meta.get_field("field_key").choices
    assert not ExtractionRun._meta.get_field("engine_version").choices
    assert not ExtractionRun._meta.get_field("engine_name").choices


def test_field_key_column_is_wide_enough_for_the_ml_vocabulary(completed_run):
    """A silent truncation would produce a key the compliance engine never matches."""
    limit = ExtractedLabelField._meta.get_field("field_key").max_length
    longest = max(len(key.value) for key in LabelFieldKey)
    assert longest <= limit, (
        f"the longest LabelFieldKey is {longest} characters but field_key holds "
        f"{limit}"
    )


# --- uncertainty must survive persistence -----------------------------------


def test_a_withheld_uncertain_reading_round_trips_intact(
    completed_run, make_extracted_field
):
    """The exact payload the extractor emits when it refuses to pick a number.

    `Net Qty: 500 g + 50 g free` may declare 500 g or 550 g. The extractor
    commits to neither, flags the reading uncertain and lists what was printed.
    All three parts have to reach the database: the flag, the reason a reviewer
    reads, and the candidates that let them decide.
    """
    payload = {
        "uncertain": True,
        "uncertainty_reasons": [
            "a bonus or free quantity is printed alongside the declared one"
        ],
        "candidates": ["500 g", "50 g"],
        "matched_by": "keyword",
    }
    field = make_extracted_field(
        completed_run,
        LabelFieldKey.NET_QUANTITY.value,
        raw_value="Net Qty: 500 g + 50 g free",
        normalized_value=payload,
    )

    reloaded = ExtractedLabelField.objects.get(pk=field.pk)
    assert reloaded.normalized_value == payload
    assert reloaded.normalized_value["uncertain"] is True
    assert reloaded.normalized_value["candidates"] == ["500 g", "50 g"]


def test_a_certain_reading_is_not_marked_uncertain_by_storage(
    completed_run, make_extracted_field
):
    """The other direction: persistence must not add doubt either."""
    payload = {"quantity": 500, "unit": "g", "base_quantity": 500, "uncertain": False}
    field = make_extracted_field(
        completed_run, LabelFieldKey.NET_QUANTITY.value, normalized_value=payload
    )

    field.refresh_from_db()
    assert field.normalized_value == payload


def test_no_normalised_value_and_an_empty_one_stay_distinguishable(
    completed_run, make_extracted_field
):
    """`NULL` and `{}` mean different things and must not collapse into each other.

    `NULL` is "no normaliser exists for this key yet"; `{}` is "a normaliser
    ran and produced nothing". A consumer reading absence as "not determined"
    gets the wrong answer if the database rounds one into the other.
    """
    absent = make_extracted_field(completed_run, "other", normalized_value=None)
    empty = make_extracted_field(completed_run, "other", normalized_value={})

    assert ExtractedLabelField.objects.get(pk=absent.pk).normalized_value is None
    assert ExtractedLabelField.objects.get(pk=empty.pk).normalized_value == {}


def test_a_missing_confidence_is_null_rather_than_zero(
    completed_run, make_extracted_field
):
    """NULL means "the engine did not report one", never "no confidence at all".

    Defaulting this to 0.0 would make every unreported reading look like the
    engine's worst one.
    """
    field = make_extracted_field(completed_run, "other")
    field.refresh_from_db()
    assert field.confidence is None


# --- deletion behaviour ------------------------------------------------------


def test_deleting_an_image_removes_its_runs_and_their_fields(
    product_image, make_extracted_field
):
    """Extraction results are readings *of* an image and do not outlive it.

    Left behind, they would be readings with no photograph to check them
    against - unfalsifiable evidence in a system whose output is meant to be
    evidence.
    """
    run = ExtractionRun.objects.create(
        image=product_image,
        engine_name="stub",
        engine_version="0.0.0",
        status=ExtractionRun.Status.COMPLETED,
    )
    make_extracted_field(run, LabelFieldKey.NET_QUANTITY.value)
    run_pk = run.pk

    product_image.delete()

    assert not ExtractionRun.objects.filter(pk=run_pk).exists()
    assert not ExtractedLabelField.objects.filter(run_id=run_pk).exists()


def test_deleting_a_run_removes_its_fields_but_not_its_image(
    completed_run, product_image, make_extracted_field
):
    """A re-run must be able to replace readings without discarding the photo."""
    make_extracted_field(completed_run, LabelFieldKey.BATCH_NUMBER.value)
    run_pk = completed_run.pk

    completed_run.delete()

    assert not ExtractedLabelField.objects.filter(run_id=run_pk).exists()
    assert product_image.__class__.objects.filter(pk=product_image.pk).exists()


# --- reproducibility ---------------------------------------------------------


def test_a_run_records_which_engine_produced_it(product_image):
    """A stored run names its pipeline, which is what makes it reproducible.

    `labelextract.registry` is keyed by name and version, so these two strings
    are what lets a result recorded months ago be re-executed - or, when the
    version is deliberately not registered, at least be interpreted.
    """
    run = ExtractionRun.objects.create(
        image=product_image,
        engine_name="tesseract",
        engine_version="0.2.1",
        status=ExtractionRun.Status.COMPLETED,
    )
    run.refresh_from_db()
    assert (run.engine_name, run.engine_version) == ("tesseract", "0.2.1")


def test_engine_version_is_free_text_not_a_database_enum(product_image):
    """The ML layer owns its version numbering; the backend records what it is told.

    A version the backend refuses to store is a run the backend cannot record.
    """
    run = ExtractionRun.objects.create(
        image=product_image,
        engine_name="a-second-engine",
        engine_version="1.4.2-rc1",
        status=ExtractionRun.Status.COMPLETED,
    )
    run.refresh_from_db()
    assert run.engine_version == "1.4.2-rc1"


def test_run_metadata_survives_verbatim(product_image):
    """`raw_output` is persisted as given, and other layers depend on that.

    The extraction pipeline documents that it puts observations *about* a run
    into its metadata - `bounding_box_space`, the preprocessing scale, and the
    declarations it saw named but could not read - specifically because the
    backend stores this mapping without touching it. Reshaping it here would
    break a contract written on the other side of the boundary.
    """
    metadata = {
        "bounding_box_space": "source",
        "preprocessing_scale": [1.0, 1.0],
        "unread_declarations": [
            {
                "key": "batch_number",
                "evidence_text": "Batch No. :",
                "box": None,
                "confidence": 0.91,
            }
        ],
    }
    run = ExtractionRun.objects.create(
        image=product_image,
        engine_name="stub",
        engine_version="0.0.0",
        status=ExtractionRun.Status.COMPLETED,
        raw_output={"metadata": metadata, "block_count": 3},
    )

    reloaded = ExtractionRun.objects.get(pk=run.pk)
    assert reloaded.raw_output["metadata"] == metadata


# --- the index the compliance engine reads through --------------------------


def test_the_run_and_field_key_index_exists(db):
    """`context.field(key)` looks a declaration up by run and key on every rule.

    Named rather than merely declared, so a rename shows up here instead of as
    a slow query on a full table.
    """
    index_names = {
        index.name
        for index in ExtractedLabelField._meta.indexes
    }
    assert "field_run_key_idx" in index_names

    with connection.cursor() as cursor:
        existing = connection.introspection.get_constraints(
            cursor, ExtractedLabelField._meta.db_table
        )
    assert "field_run_key_idx" in existing


@pytest.mark.parametrize(
    "status",
    [
        ExtractionRun.Status.PENDING,
        ExtractionRun.Status.RUNNING,
        ExtractionRun.Status.COMPLETED,
        ExtractionRun.Status.EMPTY,
        ExtractionRun.Status.FAILED,
    ],
)
def test_every_declared_run_status_is_storable(product_image, status):
    """`EMPTY` is the one that matters: it is not `FAILED` and not `COMPLETED`.

    "The photograph was unreadable" has to stay distinguishable from "the run
    broke" and from "we read it and found nothing", because the compliance
    engine turns the first into INCONCLUSIVE and the third into a finding.
    """
    run = ExtractionRun.objects.create(
        image=product_image,
        engine_name="stub",
        engine_version="0.0.0",
        status=status,
    )
    run.refresh_from_db()
    assert run.status == status
