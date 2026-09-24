"""Who may evaluate a stored reading - `POST /api/v1/compliance/`.

The vulnerability this file pins shut
-------------------------------------
The endpoint takes an `extraction_run_id` and answers with a result carrying
that run's whole reading. It used to resolve the id with a bare
`ExtractionRun.objects.get(pk=...)`, so any caller the permission class let in
could name someone else's run and:

    read their label   - the recognised text and every declaration read,
                         returned inside the result body;
    keep reading it    - the new check was the caller's, so it sat in their
                         history and could be reopened at will;
    rewrite their facts - applicability declarations were upserted onto the
                          run's product, replacing what its owner had stated;
    attach to their product - the new check hung off the victim's product.

An anonymous demonstration caller could do all of it to a signed-in user's run.
It was confirmed against a throwaway database before this fix.

The rule now enforced (`apps/compliance/api/ownership.py`) is the one the result
endpoints already apply, carried back to the reading:

    signed-in caller -> only runs whose photographs they uploaded, all of them
    anonymous caller -> only runs whose photographs were uploaded anonymously

and a run the caller may not use is refused with exactly the 400 an unknown id
gets, before anything is written.

The attacks are reproduced over HTTP from the start - the victim's run comes out
of `POST /api/v1/extraction/` or `POST /api/v1/images/`, not a fixture - and
every refusal is checked against the database as well as the status code. A
refusal that returned 400 after writing a row would still be the bug.
"""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.catalog.models import Product, ProductApplicabilityDeclaration
from apps.compliance.models import (
    ComplianceCheck,
    ComplianceEvidence,
    ComplianceFinding,
    ComplianceViolation,
)
from apps.extraction.models import ExtractedLabelField, ExtractionRun, ExtractionRunImage
from apps.extraction.services import extraction_service
from apps.images.models import ProductImage
from apps.rules.models import ApplicabilityCondition

pytestmark = pytest.mark.django_db

#: Written into the victim's stored reading. It must never appear in a refusal.
OCR_MARKER = "SYNTHETIC-LABEL-TEXT-e41c"
FIELD_MARKER = "SYNTHETIC-DECLARATION-9b07"

#: Every table a refused request could plausibly write to.
TRACKED = (
    ComplianceCheck,
    ComplianceFinding,
    ComplianceViolation,
    ComplianceEvidence,
    Product,
    ProductApplicabilityDeclaration,
    ProductImage,
    ExtractionRun,
    ExtractionRunImage,
    ExtractedLabelField,
)


@pytest.fixture(autouse=True)
def _isolated_uploads(media_root):
    """Uploads land in a temporary directory, never in backend/media."""


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(
        username="other-tester", password="not-a-real-password-either"
    )


@pytest.fixture
def condition(db) -> ApplicabilityCondition:
    """A fact a submitter may state - the kind the declaration attack targets."""
    return ApplicabilityCondition.objects.create(
        code="probe-imported-product",
        name="Imported product (test condition)",
        determination=ApplicabilityCondition.Determination.USER_DECLARED,
    )


def _as(user=None) -> Client:
    client = Client()
    if user is not None:
        client.force_login(user)
    return client


def _uploads(png_bytes, count: int) -> list[SimpleUploadedFile]:
    return [
        SimpleUploadedFile(f"panel-{n}.png", png_bytes, content_type="image/png")
        for n in range(1, count + 1)
    ]


def _extract(client: Client, png_bytes, count: int = 1) -> ExtractionRun:
    """`POST /api/v1/extraction/`, as a client does it; returns the stored run.

    The configured engine is conftest's `null-engine`, which reads nothing, so
    the synthetic markers are then written into the stored reading - the run and
    its photographs are still exactly what the endpoint created.
    """
    response = client.post(
        reverse("v1:label-extract"),
        {"image": _uploads(png_bytes, count)},
        format="multipart",
    )
    assert response.status_code == 201, response.content
    run = ExtractionRun.objects.get(pk=response.json()["id"])
    ExtractionRun.objects.filter(pk=run.pk).update(recognised_text=OCR_MARKER)
    ExtractedLabelField.objects.create(
        run=run, image=run.image, field_key="net_quantity", raw_value=FIELD_MARKER
    )
    run.refresh_from_db()
    return run


def _evaluate(client: Client, run_id, **extra):
    return client.post(
        reverse("v1:compliance-evaluate"),
        {"extraction_run_id": str(run_id), **extra},
        content_type="application/json",
    )


def _counts() -> dict[str, int]:
    return {model.__name__: model.objects.count() for model in TRACKED}


def _assert_refused_like_an_unknown_id(response, run_id) -> None:
    """The refusal is the unknown-id 400, field for field, and leaks nothing."""
    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "validation_error",
            "message": response.json()["error"]["message"],
            "details": {"extraction_run_id": [f"No extraction run with id {run_id}."]},
        }
    }
    raw = response.content.decode()
    for secret in (OCR_MARKER, FIELD_MARKER):
        assert secret not in raw


# --- the owner is unaffected --------------------------------------------------


def test_a_user_can_evaluate_the_run_they_extracted(client, user, png_bytes):
    owner = _as(user)
    run = _extract(owner, png_bytes)

    response = _evaluate(owner, run.pk)

    assert response.status_code == 201
    body = response.json()
    assert body["extraction"]["id"] == str(run.pk)
    assert body["extraction"]["recognised_text"] == OCR_MARKER
    check = ComplianceCheck.objects.get(pk=body["id"])
    assert check.requested_by == user
    assert check.extraction_run == run


def test_the_owner_can_re_evaluate_their_run(client, user, png_bytes):
    """Re-checking with a stated fact is the intended use - it still works."""
    owner = _as(user)
    run = _extract(owner, png_bytes)

    assert _evaluate(owner, run.pk).status_code == 201
    assert _evaluate(owner, run.pk).status_code == 201
    assert ComplianceCheck.objects.filter(extraction_run=run, requested_by=user).count() == 2


# --- another signed-in user ---------------------------------------------------


def test_another_user_cannot_evaluate_the_run_and_nothing_is_written(
    user, other_user, png_bytes
):
    """The confirmed attack: B names A's run id, taken from A's extraction."""
    run = _extract(_as(user), png_bytes)
    before = _counts()

    response = _evaluate(_as(other_user), run.pk)

    _assert_refused_like_an_unknown_id(response, run.pk)
    assert _counts() == before
    assert not ComplianceCheck.objects.filter(requested_by=other_user).exists()


def test_the_refusal_is_indistinguishable_from_an_id_that_names_nothing(
    user, other_user, png_bytes
):
    """No oracle: B cannot tell "exists but not yours" from "does not exist"."""
    run = _extract(_as(user), png_bytes)
    unknown = uuid.uuid4()
    intruder = _as(other_user)

    refused = _evaluate(intruder, run.pk)
    missing = _evaluate(intruder, unknown)

    assert refused.status_code == missing.status_code == 400
    assert refused.json() == {
        "error": {
            **missing.json()["error"],
            "details": {"extraction_run_id": [f"No extraction run with id {run.pk}."]},
        }
    }
    assert missing.json()["error"]["details"] == {
        "extraction_run_id": [f"No extraction run with id {unknown}."]
    }


def test_a_refused_request_that_names_a_category_creates_no_product(
    user, other_user, png_bytes, category
):
    """`category_code` would make a product - but only after authorisation."""
    run = _extract(_as(user), png_bytes)
    before = _counts()

    response = _evaluate(_as(other_user), run.pk, category_code=category.code)

    _assert_refused_like_an_unknown_id(response, run.pk)
    assert _counts() == before
    assert category.code not in response.content.decode()


def test_another_user_cannot_rewrite_the_facts_declared_about_their_product(
    user, other_user, png_bytes, category, condition
):
    """The write half of the attack, through the one flow that links a product.

    `POST /api/v1/images/` with a category links the photographs to a product,
    so a later evaluation of that run records declarations on it. The owner
    states "no"; the intruder must not be able to turn it into "yes", nor hang
    a check of their own off the owner's product.
    """
    owner = _as(user)
    uploaded = owner.post(
        reverse("v1:image-analyse"),
        {
            "image": SimpleUploadedFile("label.png", png_bytes, content_type="image/png"),
            "category_code": category.code,
        },
        format="multipart",
    )
    assert uploaded.status_code == 201, uploaded.content
    run = ExtractionRun.objects.get(pk=uploaded.json()["extraction"]["id"])
    product = run.image.product
    assert product is not None and product.created_by == user
    stated = _evaluate(owner, run.pk, applicability_declarations={condition.code: "no"})
    assert stated.status_code == 201

    before = _counts()
    product_before = Product.objects.filter(pk=product.pk).values().get()
    checks_on_product = product.compliance_checks.count()

    response = _evaluate(
        _as(other_user), run.pk, applicability_declarations={condition.code: "yes"}
    )

    _assert_refused_like_an_unknown_id(response, run.pk)
    assert _counts() == before
    declaration = ProductApplicabilityDeclaration.objects.get(
        product=product, condition=condition
    )
    assert declaration.answer == ProductApplicabilityDeclaration.Answer.NO
    assert Product.objects.filter(pk=product.pk).values().get() == product_before
    assert product.compliance_checks.count() == checks_on_product
    assert not product.compliance_checks.filter(requested_by=other_user).exists()
    body = response.content.decode()
    assert str(product.pk) not in body
    assert category.code not in body


# --- anonymous demonstration callers ------------------------------------------


def test_an_anonymous_demo_caller_cannot_evaluate_a_signed_in_users_run(
    user, png_bytes, settings
):
    run = _extract(_as(user), png_bytes)
    settings.DEMO_PUBLIC_ANALYSIS_API = True
    before = _counts()

    response = _evaluate(_as(), run.pk)

    _assert_refused_like_an_unknown_id(response, run.pk)
    assert _counts() == before


def test_an_anonymous_demo_caller_can_still_evaluate_an_anonymous_run(
    png_bytes, settings
):
    """The demonstration keeps working: anonymous upload, anonymous verdict."""
    settings.DEMO_PUBLIC_ANALYSIS_API = True
    demo = _as()
    run = _extract(demo, png_bytes)
    assert run.image.uploaded_by is None

    response = _evaluate(demo, run.pk)

    assert response.status_code == 201
    assert ComplianceCheck.objects.get(pk=response.json()["id"]).requested_by is None


def test_the_anonymous_pool_is_still_shared_between_anonymous_callers(
    png_bytes, settings
):
    """Stated rather than hidden: this fix does not make anonymous runs private.

    Two anonymous callers are indistinguishable to this API, so one can still
    evaluate the other's run - exactly as they can read each other's results.
    Separating them needs an identity the project does not have yet.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = True
    run = _extract(_as(), png_bytes)

    assert _evaluate(_as(), run.pk).status_code == 201


def test_a_signed_in_user_cannot_use_an_anonymous_run(user, png_bytes, settings):
    """A signed-in caller does not inherit the anonymous demonstration pool."""
    settings.DEMO_PUBLIC_ANALYSIS_API = True
    run = _extract(_as(), png_bytes)
    before = _counts()

    response = _evaluate(_as(user), run.pk)

    _assert_refused_like_an_unknown_id(response, run.pk)
    assert _counts() == before


def test_with_the_switch_off_anonymous_callers_are_refused_before_any_lookup(
    user, png_bytes, settings
):
    run = _extract(_as(user), png_bytes)
    settings.DEMO_PUBLIC_ANALYSIS_API = False
    before = _counts()

    response = _evaluate(_as(), run.pk)

    assert response.status_code in (401, 403)
    assert _counts() == before


# --- several photographs ------------------------------------------------------


def test_a_multi_image_run_of_the_owners_works_for_the_owner(user, png_bytes):
    owner = _as(user)
    run = _extract(owner, png_bytes, count=3)
    assert run.run_images.count() == 3
    assert set(run.run_images.values_list("image__uploaded_by", flat=True)) == {user.pk}

    response = _evaluate(owner, run.pk)

    assert response.status_code == 201
    assert len(response.json()["images"]) == 3


def test_a_multi_image_run_of_the_owners_is_refused_to_another_user(
    user, other_user, png_bytes
):
    run = _extract(_as(user), png_bytes, count=3)
    before = _counts()

    _assert_refused_like_an_unknown_id(_evaluate(_as(other_user), run.pk), run.pk)
    assert _counts() == before


def _mixed_run(first: ProductImage, second: ProductImage) -> ExtractionRun:
    """One run over photographs with different uploaders.

    The API never builds one - it ingests a set in one request - but the service
    it calls accepts any saved images and does not refuse a mix, so the rule
    cannot assume the photographs share an owner. Built through that real service.
    """
    run = extraction_service.run_extraction_over([first, second])
    ExtractionRun.objects.filter(pk=run.pk).update(recognised_text=OCR_MARKER)
    return run


def test_a_run_holding_someone_elses_photograph_is_refused_to_its_primary_owner(
    user, other_user, png_bytes
):
    """Authorising on the primary image alone would let this through.

    A's photograph is position 1 - `ExtractionRun.image` - so a check of
    `run.image.uploaded_by` passes for A. B's photograph is position 2, and its
    reading would come back in A's result. Every photograph has to be A's.
    """
    mine = _extract(_as(user), png_bytes).image
    theirs = _extract(_as(other_user), png_bytes).image
    run = _mixed_run(mine, theirs)
    assert run.image == mine
    before = _counts()

    for caller in (_as(user), _as(other_user)):
        _assert_refused_like_an_unknown_id(_evaluate(caller, run.pk), run.pk)
    assert _counts() == before


def test_a_run_mixing_owned_and_anonymous_photographs_is_refused_to_both(
    user, png_bytes, settings
):
    """An anonymous photograph is not the signed-in owner's, and vice versa."""
    settings.DEMO_PUBLIC_ANALYSIS_API = True
    owned = _extract(_as(user), png_bytes).image
    anonymous = _extract(_as(), png_bytes).image
    owned_first = _mixed_run(owned, anonymous)
    anonymous_first = _mixed_run(anonymous, owned)
    before = _counts()

    for run in (owned_first, anonymous_first):
        for caller in (_as(user), _as()):
            _assert_refused_like_an_unknown_id(_evaluate(caller, run.pk), run.pk)
    assert _counts() == before


def test_a_run_read_before_image_sets_existed_is_judged_by_its_one_photograph(
    user, other_user, completed_run
):
    """A run with no membership rows has exactly one photograph: `run.image`.

    Migration 0003 gave every earlier run its position-1 row, so this shape
    exists only when a run is created directly - as the shared fixture does.
    The rule still decides it from the photograph it has.
    """
    ExtractionRunImage.objects.filter(run=completed_run).delete()
    completed_run.image.uploaded_by = user
    completed_run.image.save(update_fields=["uploaded_by"])

    assert _evaluate(_as(other_user), completed_run.pk).status_code == 400
    assert _evaluate(_as(user), completed_run.pk).status_code == 201
