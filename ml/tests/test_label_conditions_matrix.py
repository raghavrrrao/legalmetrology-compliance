"""The pipeline across the photograph conditions a label actually arrives in.

How this differs from `test_image_conditions.py`
------------------------------------------------
That file asserts the *contract* holds under a few conditions - status, error
codes, boxes inside the frame - and deliberately asserts nothing about what was
read. Every one of its tests would still pass if field extraction stopped
working entirely, because zero fields is a legal outcome everywhere in it.

This file adds the missing half: a **behavioural floor**. On a clean, synthetic,
high-contrast rendering of a declaration block, the declarations this extractor
claims to support must come out, with the right structured values. If they stop
coming out, something is broken, and that is worth failing over.

Read the floor test for what it is
----------------------------------
It is a rendering by Pillow of four lines of text, in Pillow's built-in bitmap
font, with no photograph anywhere near it. **It measures nothing about real
packaging and no number from it may be quoted as accuracy.** Accuracy is
measured against an annotated set per `docs/evaluation-strategy.md`, which has
not been done. What the floor proves is narrower and still worth having: the
preprocessing -> OCR -> extraction path is wired up and reads text that is
trivially readable.

The built-in font rather than a system one is deliberate: it ships with Pillow,
so this renders identically on every developer's machine and in CI, where a
`C:/Windows/Fonts` or `/usr/share/fonts` path would not exist.

Everything below the floor asserts contract only
------------------------------------------------
Blur, rotation, glare and the rest degrade recognition in ways that vary by
Tesseract build. Pinning what they read would be an accuracy claim that breaks
on an unrelated upgrade. What is pinned instead is the promise the system makes
whatever it manages to read:

- a degraded photograph is `COMPLETED` or `EMPTY`, **never** `FAILED`;
- no declaration is invented to fill a gap;
- every box lands inside the source photograph;
- a declaration whose keyword was read but whose value was not becomes an
  unread observation, never a value.
"""

from __future__ import annotations

import pytest

from labelextract import registry
from labelextract.contracts import ExtractionStatus, ImageRef, LabelFieldKey
from labelextract.exceptions import EngineNotAvailableError
from labelextract.fields import SUPPORTED_KEYS
from labelextract.fields.normalisation import is_uncertain
from labelextract.ocr import tesseract

PIL = pytest.importorskip("PIL", reason="Pillow is part of the optional [ocr] extra")

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter  # noqa: E402

#: The declaration block this file renders. Modelled on the panel of the first
#: product photographed for this project (a helmet-cleaning spray), so the
#: phrasings under test are ones that appear on a real Indian package rather
#: than ones invented to suit the patterns.
DECLARATION_LINES = (
    "NET QUANTITY : 120 GRAMS",
    "MRP : 349.00 INCL. OF ALL TAXES",
    "BATCH : 2546",
    "BEST BEFORE 2 YEARS FROM MFG. DT.",
)

_BACKGROUND = (250, 248, 240)
_INK = (10, 10, 10)
_SIZE = (760, 260)
_SPACING = 44
_ORIGIN = 24


def _panel(
    lines=DECLARATION_LINES,
    *,
    size=_SIZE,
    background=_BACKGROUND,
    ink=_INK,
    spacing=_SPACING,
    origin=_ORIGIN,
) -> Image.Image:
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((origin, origin + index * spacing), line, fill=ink)
    return image


def _as_ref(image: Image.Image, path) -> ImageRef:
    image.save(path, format="PNG")
    return ImageRef(
        path=path,
        image_format="png",
        size_bytes=path.stat().st_size,
        width=image.width,
        height=image.height,
    )


def _uneven(image: Image.Image) -> Image.Image:
    """One side of the panel lit, the other falling into shadow."""
    gradient = Image.linear_gradient("L").resize(image.size).rotate(90)
    return Image.composite(image, Image.new("RGB", image.size, (0, 0, 0)), gradient)


def _glare(image: Image.Image) -> Image.Image:
    """A specular highlight across the MRP line, as foil packaging gives."""
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((180, 60, 600, 130), fill=(255, 255, 255, 235))
    return image


def _obscured(image: Image.Image) -> Image.Image:
    """A torn or covered panel: the net-quantity line is gone, the rest remains."""
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 18, 760, 60), fill=(20, 20, 20))
    return image


#: The condition matrix. Each entry is a transform of the clean panel.
#:
#: These are *approximations* of photographic conditions made with Pillow
#: filters. A gaussian blur is not camera shake and a brightness scale is not
#: a dim shop aisle. They are close enough to drive the pipeline down the same
#: branches, and they are not evaluation data.
CONDITIONS = {
    "clean": lambda: _panel(),
    "rotated_slightly": lambda: _panel().rotate(5, expand=True, fillcolor=_BACKGROUND),
    "rotated_moderately": lambda: _panel().rotate(
        12, expand=True, fillcolor=_BACKGROUND
    ),
    "rotated_quarter_turn": lambda: _panel().rotate(
        90, expand=True, fillcolor=_BACKGROUND
    ),
    "upside_down": lambda: _panel().rotate(180, expand=True, fillcolor=_BACKGROUND),
    "blur_mild": lambda: _panel().filter(ImageFilter.GaussianBlur(1.0)),
    "blur_moderate": lambda: _panel().filter(ImageFilter.GaussianBlur(2.5)),
    "blur_heavy": lambda: _panel().filter(ImageFilter.GaussianBlur(6.0)),
    "dark": lambda: ImageEnhance.Brightness(_panel()).enhance(0.18),
    "very_dark": lambda: ImageEnhance.Brightness(_panel()).enhance(0.06),
    "uneven_illumination": lambda: _uneven(_panel()),
    "glare_over_a_declaration": lambda: _glare(_panel()),
    "low_contrast": lambda: _panel(background=(138, 136, 130), ink=(116, 114, 108)),
    "small_text": lambda: _panel(size=(300, 110), spacing=16, origin=8),
    "cropped_label": lambda: _panel().crop((0, 0, 760, 120)),
    "value_out_of_frame": lambda: _panel().crop((0, 0, 110, 260)),
    "obscured_declaration": lambda: _obscured(_panel()),
    "blank_frame": lambda: Image.new("RGB", (400, 300), (140, 140, 140)),
    "second_script": lambda: _panel(
        lines=(
            "NET QUANTITY : 120 GRAMS",
            "\u0936\u0941\u0926\u094d\u0927 \u0935\u091c\u0928 : 120 \u0917\u094d\u0930\u093e\u092e",
            "MRP : 349.00",
            "\u0928\u093f\u0930\u094d\u092e\u093e\u0924\u093e : \u092c\u093e\u091c\u093c\u093f\u0902\u0917\u093e",
        )
    ),
}


@pytest.fixture(scope="module")
def pipeline():
    """The registered Tesseract pipeline, skipped when the binary is absent.

    Module-scoped because it is stateless across images and the registry caches
    it anyway; building it per test would only repeat the warmup.
    """
    pytest.importorskip("pytesseract")
    built = registry.get_pipeline(tesseract.NAME, tesseract.VERSION)
    try:
        built.ocr_engine.warmup()
    except EngineNotAvailableError:
        pytest.skip("the tesseract binary is not installed on this machine")
    return built


@pytest.fixture(scope="module")
def render(tmp_path_factory, pipeline):
    """Render a named condition, run it, and hand back the image and result.

    Each condition is rendered and recognised **once** for the whole module and
    the result reused. Four of the tests below are parametrized over the entire
    matrix, so running the pipeline per test would shell out to Tesseract
    around eighty times for nineteen distinct images - a minute of test time
    buying nothing, on a suite people are expected to run before every commit.

    Reuse is safe because every contract type here is a frozen dataclass: no
    test can mutate a result and affect another. The one place ordering could
    matter is `test_the_floor_is_reproducible`, which asks two runs to agree
    and therefore calls the pipeline directly rather than through the cache.
    """
    directory = tmp_path_factory.mktemp("conditions")
    cache: dict[str, tuple] = {}

    def _run(condition: str):
        if condition not in cache:
            image = _as_ref(CONDITIONS[condition](), directory / f"{condition}.png")
            cache[condition] = (image, pipeline.run(image))
        return cache[condition]

    return _run


def _field(result, key: LabelFieldKey):
    return result.field_for(key)


def _unread_keys(result) -> set[str]:
    return {item["key"] for item in result.metadata["unread_declarations"]}


# --- the behavioural floor --------------------------------------------------


def test_a_clean_panel_yields_the_declarations_printed_on_it(render):
    """The one test in this suite that fails when extraction stops working.

    Not an accuracy measurement - see the module docstring. It renders four
    lines in a bitmap font at high contrast and asserts the pipeline still
    turns them into structured declarations. If this fails, either recognition
    or interpretation changed; the recognised text in the failure message says
    which.
    """
    _, result = render("clean")

    assert result.status is ExtractionStatus.COMPLETED
    found = {extracted.key for extracted in result.fields}
    expected = {
        LabelFieldKey.NET_QUANTITY,
        LabelFieldKey.RETAIL_SALE_PRICE,
        LabelFieldKey.BATCH_NUMBER,
        LabelFieldKey.BEST_BEFORE,
    }
    assert expected <= found, (
        f"a clean rendering of {DECLARATION_LINES} should yield every "
        f"declaration in it. Recognised: {result.ocr.full_text!r}"
    )


def test_the_clean_panel_values_are_structured_correctly(render):
    """The values, not just the keys - a key with a wrong value is worse.

    The batch code is deliberately not asserted. A four-digit code has no
    redundancy, `2546` reads as `2548` on some builds, and pinning it would
    make this an accuracy test of one glyph.
    """
    _, result = render("clean")

    quantity = _field(result, LabelFieldKey.NET_QUANTITY).normalized_value
    assert quantity["base_quantity"] == 120
    assert quantity["base_unit"] == "g"
    assert quantity["measure"] == "mass"
    assert is_uncertain(quantity) is False

    price = _field(result, LabelFieldKey.RETAIL_SALE_PRICE).normalized_value
    assert price["amount"] == "349.00"
    assert price["currency"] == "INR"
    assert price["inclusive_of_all_taxes"] is True
    assert is_uncertain(price) is False

    shelf_life = _field(result, LabelFieldKey.BEST_BEFORE).normalized_value
    assert shelf_life["duration_value"] == 2
    assert shelf_life["duration_unit"] == "years"


def test_the_clean_panel_declares_no_manufacture_date(render):
    """End-to-end guard for the shelf-life/manufacture-date defect.

    `BEST BEFORE 2 YEARS FROM MFG. DT.` carries the manufacture keyword and no
    manufacture date. The panel declares none, so the result must contain none
    - a duration reported here would record an undeclared date as declared.
    See `test_field_extraction.py`'s regression section for the unit-level
    case this came from.
    """
    _, result = render("clean")

    assert _field(result, LabelFieldKey.DATE_OF_MANUFACTURE) is None
    assert _field(result, LabelFieldKey.DATE_OF_PACKING) is None


def test_the_floor_is_reproducible(tmp_path, pipeline):
    """Two runs over the same bytes agree.

    Tesseract is deterministic for a fixed build and configuration. If this
    ever fails, every other assertion in this file is unreliable and that is
    the first thing to know.

    Deliberately bypasses the `render` cache and runs the pipeline twice: a
    cached result compared against itself would assert nothing at all.
    """
    image = _as_ref(CONDITIONS["clean"](), tmp_path / "clean.png")

    first = pipeline.run(image)
    second = pipeline.run(image)

    assert first.ocr.full_text == second.ocr.full_text
    assert [f.key for f in first.fields] == [f.key for f in second.fields]
    assert [f.normalized_value for f in first.fields] == [
        f.normalized_value for f in second.fields
    ]


# --- the condition matrix: contract only ------------------------------------


@pytest.mark.parametrize("condition", sorted(CONDITIONS))
def test_no_condition_produces_a_failed_run(render, condition):
    """A hard-to-read photograph is not a system error.

    `FAILED` means we could not run. A dark, blurred or sideways photograph
    ran fine and read little, which is `COMPLETED` or `EMPTY`. Collapsing the
    two would send a user to report a bug instead of retaking a picture.
    """
    _, result = render(condition)

    assert result.status in (ExtractionStatus.COMPLETED, ExtractionStatus.EMPTY)
    assert result.error_code is None
    assert result.error_message is None
    assert result.is_placeholder is False


@pytest.mark.parametrize("condition", sorted(CONDITIONS))
def test_every_box_lands_inside_the_photograph(render, condition):
    """The regression the box mapping exists to prevent, across every condition.

    The pipeline upscales small images, so the engine reports geometry in a
    larger coordinate system than the file the user uploaded. A box that
    escaped the mapping would still be a valid box - just drawn over the wrong
    part of the package, with nothing failing anywhere.
    """
    image, result = render(condition)

    assert result.metadata["bounding_box_space"] in ("source", "preprocessed")
    boxes = [block.box for block in result.ocr.blocks if block.box is not None]
    boxes += [f.box for f in result.fields if f.box is not None]
    for box in boxes:
        assert box.x >= 0 and box.y >= 0
        assert box.x + box.width <= image.width
        assert box.y + box.height <= image.height


@pytest.mark.parametrize("condition", sorted(CONDITIONS))
def test_nothing_is_invented_under_any_condition(render, condition):
    """Every field is a well-formed observation from the supported vocabulary.

    The failure this guards against is a degraded image producing a *plausible*
    field rather than none: a key outside the vocabulary, an empty reading, a
    confidence outside the unit interval, or a normalised mapping with no
    uncertainty verdict on it.
    """
    _, result = render(condition)

    for extracted in result.fields:
        assert extracted.key in SUPPORTED_KEYS
        assert isinstance(extracted.raw_value, str) and extracted.raw_value.strip()
        if extracted.confidence is not None:
            assert 0.0 <= extracted.confidence <= 1.0
        if extracted.normalized_value is not None:
            assert "uncertain" in extracted.normalized_value


@pytest.mark.parametrize("condition", sorted(CONDITIONS))
def test_an_unread_declaration_never_carries_a_value(render, condition):
    """The `UnreadDeclaration` invariant, checked on real recognition output.

    An unread observation says "this declaration is named here and we could not
    read it". It must never duplicate a declaration that *was* read, and it
    must never acquire a value - a presence check would then pass on it.
    """
    _, result = render(condition)

    extracted_keys = {f.key.value for f in result.fields}
    for observation in result.metadata["unread_declarations"]:
        assert observation["key"] not in extracted_keys
        assert observation["evidence_text"].strip()
        assert set(observation) == {"key", "evidence_text", "box", "confidence"}


def test_a_frame_with_no_text_recognises_nothing_rather_than_something(render):
    """`EMPTY`, and not a single fabricated declaration."""
    _, result = render("blank_frame")

    assert result.status is ExtractionStatus.EMPTY
    assert result.fields == ()
    assert result.metadata["unread_declarations"] == []
    assert result.error_code is None


# --- partial visibility: the case the unread mechanism exists for -----------


def test_a_declaration_cut_off_by_the_frame_is_unread_not_absent(render):
    """The frame ends mid-value: the keyword is visible, the number is not.

    This is the finding the whole `UnreadDeclaration` mechanism was built for,
    and this is the only test that drives it through real recognition rather
    than through hand-written text. "Net quantity not declared" and "net
    quantity declared, photograph cut it off" are opposite conclusions, and an
    empty `fields` tuple says both.
    """
    _, result = render("value_out_of_frame")

    assert _field(result, LabelFieldKey.NET_QUANTITY) is None, (
        "the value is outside the frame; reporting one would be an invention"
    )
    assert LabelFieldKey.NET_QUANTITY.value in _unread_keys(result), (
        f"the net-quantity keyword is legible and its value is not, so this "
        f"must be reported as unread. Recognised: {result.ocr.full_text!r}"
    )


def test_an_obscured_declaration_is_absent_rather_than_guessed(render):
    """A torn or covered line: neither a value nor a keyword survives.

    Nothing is reported for it, which is correct - there is no evidence to
    report. The declarations that are still legible must survive, so one
    damaged line does not cost the whole panel.
    """
    _, result = render("obscured_declaration")

    assert _field(result, LabelFieldKey.NET_QUANTITY) is None
    assert _field(result, LabelFieldKey.RETAIL_SALE_PRICE) is not None, (
        f"the MRP line is untouched and must still be read. "
        f"Recognised: {result.ocr.full_text!r}"
    )


def test_a_second_script_degrades_without_breaking_the_run(render):
    """Devanagari with only `eng` language data installed.

    The English declarations must still be read, and the unrecognised script
    must not become a declaration. This is not a test of Hindi support - there
    is none in the extractor's patterns, which is stated in ml/README.md.
    """
    _, result = render("second_script")

    assert result.status is ExtractionStatus.COMPLETED
    assert _field(result, LabelFieldKey.NET_QUANTITY) is not None
    for extracted in result.fields:
        assert extracted.key in SUPPORTED_KEYS
