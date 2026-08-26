"""Regression tests against the real product photographs, when they are present.

Why these tests skip almost everywhere
--------------------------------------
`ml/data/` is ignored by Git in its entirety and deliberately so - see
`ml/data/README.md`. No photograph of a product ships with this repository, and
none ever should: an image committed once is in every clone permanently, the
packaging carries third-party trade dress, and photographs taken in shops catch
things nobody intended to photograph.

So these tests **skip on a fresh clone and skip in CI**, and run only on the
machine of the developer who took the pictures. That is a smaller guarantee
than a normal test gives, and it is still the only automated check that the
pipeline behaves on an actual photograph rather than on a Pillow rendering.
Everything that can be asserted without a real photograph is asserted in
`test_label_conditions_matrix.py`, which runs everywhere.

What is asserted, and what is deliberately not
----------------------------------------------
Two tiers.

**Tier 1, every image: contract only.** No `FAILED` status, no invented field,
every box inside the frame, metadata that survives a JSONField. These hold for
a photograph of a desk and are the ones worth running over the whole set.

**Tier 2, the declaration close-up only: the values it actually declares.**
`05_declaration_closeup` is a square-on photograph of the mandatory-declaration
panel, and the pipeline reads it. Pinning the net quantity and the MRP is what
makes a preprocessing or pattern change visible: a tuning that improves one
synthetic case and quietly loses a real one fails here.

**No accuracy figure may be quoted from this file.** Six photographs of one
product is not an evaluation set, four of them are not of the declaration panel
at all, and nothing here is annotated ground truth. `docs/evaluation-strategy.md`
describes what measuring would require. See `ml/data/README.md` before adding
an image.

Adding another product
----------------------
Add a directory beside `product_001` and an entry in `EXPECTED`. Record what
the panel actually says, from the physical package, not from what the pipeline
happened to return - an expectation copied from output measures nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from labelextract import registry
from labelextract.contracts import ExtractionStatus, ImageRef, LabelFieldKey
from labelextract.exceptions import EngineNotAvailableError
from labelextract.fields import SUPPORTED_KEYS
from labelextract.ocr import tesseract

PIL = pytest.importorskip("PIL", reason="Pillow is part of the optional [ocr] extra")

from PIL import Image  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_DIR = REPO_ROOT / "ml" / "data" / "raw" / "products" / "product_001"

#: The panel this product carries, transcribed from the physical package.
#:
#: Product 001 is a helmet-cleaning aerosol. Its declaration panel prints, in
#: this order: commodity, net quantity, MRP, unit sale price, manufacturer and
#: address, consumer-care contact, batch, manufacturing date and a shelf life.
#:
#: Two of those are printed with **no value after the keyword** on the physical
#: package: `BATCH:` and `MFG. DT. :`. That is not a photography problem and it
#: is why this product is a useful regression: a system that reports a batch
#: number or a manufacture date for it has invented one.
DECLARED = {
    "net_quantity_base_grams": 120,
    "mrp_amount": "349.00",
    "mrp_inclusive_of_taxes": True,
    "best_before_years": 2,
}

#: Filename -> what the photograph shows. Used only to make a failure readable;
#: nothing parses these names, per `ml/data/README.md`.
IMAGES = {
    "01_front_clean.jpeg": "front panel, marketing copy, no declarations",
    "02_back_clean.jpeg": "back panel, dense small print at an angle",
    "03_left_clean.jpeg": "left panel, curved surface",
    "04_right_clean.jpeg": "right panel, declaration keywords with unreadable values",
    "05_declaration_closeup.jpeg": "declaration panel, square on - the readable one",
    "06_declaration_closeup_angled.jpeg": "declaration panel at an angle",
}

pytestmark = pytest.mark.skipif(
    not PRODUCT_DIR.is_dir() or not any(PRODUCT_DIR.glob("*.jpeg")),
    reason=(
        f"no local product photographs in {PRODUCT_DIR} - they are gitignored "
        f"by design; see ml/data/README.md"
    ),
)


@pytest.fixture(scope="module")
def pipeline():
    pytest.importorskip("pytesseract")
    built = registry.get_pipeline(tesseract.NAME, tesseract.VERSION)
    try:
        built.ocr_engine.warmup()
    except EngineNotAvailableError:
        pytest.skip("the tesseract binary is not installed on this machine")
    return built


def _ref(path: Path) -> ImageRef:
    with Image.open(path) as probe:
        width, height = probe.size
        image_format = (probe.format or "jpeg").lower()
    return ImageRef(
        path=path,
        image_format=image_format,
        size_bytes=path.stat().st_size,
        width=width,
        height=height,
    )


@pytest.fixture(scope="module")
def runs(pipeline):
    """Every available photograph, recognised once and reused.

    Real photographs are several megapixels and get upscaled before
    recognition, so a run costs the better part of a second. Running each image
    once per test would make this file slower than the rest of the suite
    combined.
    """
    results = {}
    for path in sorted(PRODUCT_DIR.glob("*.jpeg")):
        image = _ref(path)
        results[path.name] = (image, pipeline.run(image))
    return results


def _present(runs, name):
    if name not in runs:
        pytest.skip(f"{name} is not in {PRODUCT_DIR}")
    return runs[name]


# --- tier 1: the contract, over every photograph ----------------------------


def test_at_least_one_photograph_was_found(runs):
    """Guards the guard: a typo'd glob would make every test below vacuous."""
    assert runs, f"the skip condition passed but no image was loaded from {PRODUCT_DIR}"


def test_no_photograph_produces_a_failed_run(runs):
    """A real photograph is readable, unreadable, or somewhere between.

    None of those is `FAILED`. `FAILED` means the pipeline could not run, and
    a JPEG off a phone is not that.
    """
    for name, (_, result) in runs.items():
        assert result.status in (
            ExtractionStatus.COMPLETED,
            ExtractionStatus.EMPTY,
        ), f"{name} ({IMAGES.get(name, '?')}): {result.error_code} {result.error_message}"
        assert result.error_code is None
        assert result.is_placeholder is False


def test_every_box_lands_inside_the_photograph(runs):
    """These images are upscaled before recognition, so the mapping is live.

    A box that escaped it would put a reviewer's evidence overlay over the
    wrong part of the can, with nothing anywhere reporting a problem.
    """
    for name, (image, result) in runs.items():
        assert result.metadata["bounding_box_space"] == "source", name
        boxes = [b.box for b in result.ocr.blocks if b.box is not None]
        boxes += [f.box for f in result.fields if f.box is not None]
        for box in boxes:
            assert box.x >= 0 and box.y >= 0, name
            assert box.x + box.width <= image.width, name
            assert box.y + box.height <= image.height, name


def test_nothing_outside_the_supported_vocabulary_is_reported(runs):
    for name, (_, result) in runs.items():
        for extracted in result.fields:
            assert extracted.key in SUPPORTED_KEYS, name
            assert extracted.raw_value.strip(), name
            if extracted.confidence is not None:
                assert 0.0 <= extracted.confidence <= 1.0, name


def test_every_run_survives_the_journey_into_a_jsonfield(runs):
    """The backend persists `metadata` and `ocr.raw` verbatim into a JSONField.

    Real engine output is where a non-serialisable value would actually appear
    - the word list, the Tesseract version, the geometry - and none of the
    stub-driven tests exercise it.
    """
    for name, (_, result) in runs.items():
        json.dumps(
            {
                "engine_raw": dict(result.ocr.raw),
                "metadata": dict(result.metadata),
                "block_count": len(result.ocr.blocks),
            }
        ), name


def test_no_photograph_reports_a_manufacture_or_packing_date(runs):
    """The package prints `MFG. DT. :` with nothing after it.

    Any date reported for this product was invented. This is the real-image
    half of the shelf-life regression: before it was fixed, the close-up
    produced `date_of_manufacture` with the value "2 years", read out of
    `BEST BEFORE 2 YEARS FROM MFG. DT.` on the following line.
    """
    for name, (_, result) in runs.items():
        for key in (
            LabelFieldKey.DATE_OF_MANUFACTURE,
            LabelFieldKey.DATE_OF_PACKING,
            LabelFieldKey.DATE_OF_IMPORT,
        ):
            found = result.field_for(key)
            assert found is None, (
                f"{name} reported {key.value} as "
                f"{found.normalized_value!r}, but the package declares no "
                f"such date - the keyword is printed with a blank after it"
            )


# --- tier 2: the declaration close-up, which the pipeline does read ---------


def test_the_declaration_panel_yields_the_net_quantity(runs):
    _, result = _present(runs, "05_declaration_closeup.jpeg")
    found = result.field_for(LabelFieldKey.NET_QUANTITY)

    assert found is not None, (
        f"the panel declares 120 GRAMS and it was not read. "
        f"Recognised: {result.ocr.full_text[-400:]!r}"
    )
    assert found.normalized_value["base_quantity"] == DECLARED["net_quantity_base_grams"]
    assert found.normalized_value["base_unit"] == "g"
    assert found.normalized_value["measure"] == "mass"


def test_the_declaration_panel_yields_the_retail_sale_price(runs):
    _, result = _present(runs, "05_declaration_closeup.jpeg")
    found = result.field_for(LabelFieldKey.RETAIL_SALE_PRICE)

    assert found is not None, (
        f"the panel declares MRP 349.00 and it was not read. "
        f"Recognised: {result.ocr.full_text[-400:]!r}"
    )
    assert found.normalized_value["amount"] == DECLARED["mrp_amount"]
    assert (
        found.normalized_value["inclusive_of_all_taxes"]
        is DECLARED["mrp_inclusive_of_taxes"]
    )


def test_the_declaration_panel_yields_the_shelf_life(runs):
    _, result = _present(runs, "05_declaration_closeup.jpeg")
    found = result.field_for(LabelFieldKey.BEST_BEFORE)

    assert found is not None
    assert found.normalized_value["duration_value"] == DECLARED["best_before_years"]
    assert found.normalized_value["duration_unit"] == "years"


def test_the_unit_sale_price_is_not_mistaken_for_the_retail_price(runs):
    """The panel prints both, one line apart.

    `UNIT SALE PRICE : 2.91 PER GRAM` sits directly under the MRP. Reporting
    2.91 as the retail sale price would be a wrong declared value rather than a
    missing one, which is the harder error to notice downstream.
    """
    _, result = _present(runs, "05_declaration_closeup.jpeg")
    found = result.field_for(LabelFieldKey.RETAIL_SALE_PRICE)

    if found is not None:
        assert found.normalized_value.get("amount") != "2.91"
    assert result.field_for(LabelFieldKey.UNIT_SALE_PRICE) is None, (
        "unit_sale_price is not implemented; a value here means something "
        "started guessing"
    )


# --- the case the unread mechanism was built from ---------------------------


def test_the_side_panel_reports_its_unreadable_mrp_as_unread(runs):
    """The photograph this whole mechanism came from.

    `04_right_clean` catches the declaration panel edge-on. OCR returns the
    line `MRP` and nothing else, because the rest of it is too foreshortened to
    recognise. The package plainly declares an MRP - the keyword is legible -
    but its value is unknown.

    Without the unread observation this is an empty `fields` tuple, identical
    to a package that declares no MRP at all. One of those is "photograph the
    panel again"; the other is a potential violation.
    """
    _, result = _present(runs, "04_right_clean.jpeg")

    assert result.field_for(LabelFieldKey.RETAIL_SALE_PRICE) is None
    unread = {item["key"] for item in result.metadata["unread_declarations"]}
    assert LabelFieldKey.RETAIL_SALE_PRICE.value in unread, (
        f"the MRP keyword is legible on this panel and its value is not, so "
        f"the absence must be reported as unread rather than as nothing. "
        f"Recognised: {result.ocr.full_text!r}"
    )


def test_every_unread_observation_carries_its_evidence(runs):
    """An unfalsifiable claim is worse than no claim.

    "An MRP keyword was seen" without the line it was seen on cannot be checked
    by the reviewer it is addressed to.
    """
    for name, (image, result) in runs.items():
        for observation in result.metadata["unread_declarations"]:
            assert observation["evidence_text"].strip(), name
            assert observation["key"] in {key.value for key in SUPPORTED_KEYS}, name
            box = observation["box"]
            if box is not None:
                assert box["x"] + box["width"] <= image.width, name
                assert box["y"] + box["height"] <= image.height, name


def test_no_unread_observation_duplicates_a_field_that_was_read(runs):
    for name, (_, result) in runs.items():
        unread = {item["key"] for item in result.metadata["unread_declarations"]}
        extracted = {field.key.value for field in result.fields}
        assert unread.isdisjoint(extracted), name


# --- the panels that carry no declarations ----------------------------------


def test_a_marketing_panel_declares_nothing_rather_than_something(runs):
    """The front of the can carries advertising copy and no declaration.

    Reading a declaration off it would be a false positive of the worst kind: a
    presence check would pass, and a package missing that declaration would be
    recorded as carrying it.
    """
    _, result = _present(runs, "01_front_clean.jpeg")

    assert result.fields == (), (
        f"the front panel declares nothing; got "
        f"{[f.key.value for f in result.fields]} from "
        f"{result.ocr.full_text!r}"
    )
