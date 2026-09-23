"""Give every run that already exists the image set it always had: one image.

Before `ExtractionRunImage`, a run read exactly one photograph and nothing
recorded which photograph each declaration came from - because there was only
ever one answer. This writes that answer down, so the new columns describe old
rows as truthfully as they describe new ones:

- one membership row per existing run, at position 1, pointing at
  `ExtractionRun.image`;
- `ExtractedLabelField.image` set to that same photograph for every reading of
  that run.

Neither is an invention. A run's declarations were read from its image; there
was no other image they could have come from. Leaving the columns null instead
would make every historical reading indistinguishable from one whose source is
genuinely unknown, and the API documents null as exactly that - so a result
page would stop citing an image for findings that have always had one.

`status` is derived from the run's own status, which for a single-image run is
the same statement about the same photograph. PENDING and RUNNING have no
per-image equivalent (a membership row is written only after the pipeline has
finished with the image); a run stuck in either is an interrupted process
rather than a reading, so those are recorded as FAILED, which is what their
image's own `ProductImage.status` would already say.

Reversible: the reverse drops the membership rows and clears the column,
returning to exactly the state before this ran.
"""

from django.db import migrations

#: Batch size for the field backfill. Large enough that a normal installation
#: is one round trip, small enough that a long-running one does not build a
#: single statement out of every reading ever made.
_BATCH = 1000


def backfill(apps, schema_editor):
    ExtractionRun = apps.get_model("extraction", "ExtractionRun")
    ExtractionRunImage = apps.get_model("extraction", "ExtractionRunImage")
    ExtractedLabelField = apps.get_model("extraction", "ExtractedLabelField")

    # The historical model's TextChoices are not available through `apps`, so
    # the values are written out. They are database values and stable by
    # definition - that is why `ExtractionRun.Status` stores strings.
    completed_or_empty = {"completed", "empty"}

    memberships = []
    for run in ExtractionRun.objects.all().iterator(chunk_size=_BATCH):
        if run.image_id is None:  # pragma: no cover - the column is NOT NULL
            continue
        status = run.status if run.status in completed_or_empty else "failed"
        memberships.append(
            ExtractionRunImage(
                run_id=run.pk,
                image_id=run.image_id,
                position=1,
                status=status,
                error_code=run.error_code or "",
                error_message=run.error_message or "",
                processing_ms=run.processing_ms,
            )
        )
        if len(memberships) >= _BATCH:
            ExtractionRunImage.objects.bulk_create(memberships)
            memberships = []
    if memberships:
        ExtractionRunImage.objects.bulk_create(memberships)

    # One UPDATE per run rather than per reading: a run's readings all came
    # from its one image.
    for run_id, image_id in ExtractionRun.objects.values_list("pk", "image_id").iterator(
        chunk_size=_BATCH
    ):
        ExtractedLabelField.objects.filter(run_id=run_id, image__isnull=True).update(
            image_id=image_id
        )


def unbackfill(apps, schema_editor):
    ExtractionRunImage = apps.get_model("extraction", "ExtractionRunImage")
    ExtractedLabelField = apps.get_model("extraction", "ExtractedLabelField")

    ExtractionRunImage.objects.all().delete()
    ExtractedLabelField.objects.update(image=None)


class Migration(migrations.Migration):

    dependencies = [
        ("extraction", "0002_multi_image_inspection"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
