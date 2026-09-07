"""Measure what a second Tesseract language does to label recognition.

    cd ml
    python experiments/language_comparison.py data/hv-evaluation-set --report-dir /tmp/lang

Nothing here is production code and nothing here is imported by the package.
It exists so that "does Hindi help?" is a question somebody can *answer on their
own machine* rather than a question somebody has an opinion about, and so the
answer arrives with the dataset version, the sample count and the date attached.

What it holds constant
----------------------
**Language is the only variable.** Every configuration is built by taking the
options `labelextract.ocr.tesseract.build_pipeline()` ships - page-segmentation
mode 3, the empty-result retry on mode 11, engine mode 3, the 30 s cap - and
replacing `languages` alone, via `dataclasses.replace` on the production
default. Preprocessing is the production `PillowPreprocessor` and the field
extractor is the production `RuleBasedFieldExtractor`, both untouched.

That matters more than it sounds. The previous OCR branch moved two things at
once - a segmentation retry and four field-extraction rules - and the only
reason the write-up could say which one earned the score was that the two were
measured separately. A language experiment that also changed preprocessing or
PSM would measure nothing attributable.

Why it refuses to trust `eng+hin`
---------------------------------
**Tesseract 5.4.0 does not fail when a language in a `+` list is missing.**
Measured on this machine, with no `hin.traineddata` installed anywhere:

    -l hin       -> TesseractError, "Error opening data file .../hin.traineddata"
    -l eng+hin   -> exit 0, output byte-identical to -l eng
    -l hin+eng   -> exit 0, output byte-identical to -l eng

So a run configured as `eng+hin` on a machine without the language pack
produces the baseline's numbers exactly, and reports them as if Hindi had been
evaluated. That is a measurement trap, not a result: the honest reading is
"Hindi was never loaded", and the wrong reading - "Hindi makes no difference to
our labels" - is the one a table of identical numbers invites.

Every configuration is therefore checked against `pytesseract.get_languages()`
*before* it runs, and a configuration naming an absent language is **skipped and
reported as skipped**. It is never silently downgraded.

Installing the language data
----------------------------
Nothing here downloads anything. Language data is an operating-system package,
installed outside the repository, exactly as `eng` already is - no weights in
Git, nothing to checksum, nothing that can end up in a clone:

    Debian/Ubuntu   sudo apt install tesseract-ocr-hin
    macOS           brew install tesseract-lang
    Windows         re-run the UB-Mannheim installer and tick Hindi under
                    "Additional language data", or drop the official
                    hin.traineddata into the tessdata directory that
                    `tesseract --list-langs` prints

Confirm with `tesseract --list-langs` before re-running this script.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

#: Configurations to compare, in report order. The first is the production
#: baseline and always runs; the rest run only if their language data is
#: present. Deliberately short: three rows a person can read, not a sweep.
CONFIGURATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("eng", ("eng",)),
    ("eng+hin", ("eng", "hin")),
    ("hin", ("hin",)),
)

#: The character the whole question turns on. Indian packaging prints it, and
#: `labelextract.fields.patterns._CURRENCY` matches it - so whether a language
#: model can emit it decides whether a price with no keyword can ever be read.
RUPEE = "\u20b9"


def available_languages() -> set[str]:
    """What Tesseract can actually load, asked of Tesseract itself."""
    import pytesseract

    return set(pytesseract.get_languages(config=""))


def rupee_capability(languages: tuple[str, ...]) -> dict:
    """Can this language configuration output `₹` at all?

    Two independent checks, because they answer different questions and the
    second one alone would be an observation about three fonts rather than
    about the model:

    1. **Rendered recognition.** `₹ 0.08 per g` is drawn as clean synthetic type
       - no photograph, no glare, no curvature - and read back. If the glyph
       does not survive that, no amount of preprocessing will recover it from a
       hand-held photo of a crinkled bag.
    2. **Alphabet membership.** The LSTM unicharset extracted from each
       `.traineddata` is the model's entire output alphabet. A character absent
       from it cannot be emitted under any input whatsoever. This is the
       decisive check; the render is the demonstration.

    Post-processing a near-miss into `₹` is not attempted anywhere and must not
    be: turning a recognised `Z` into a currency symbol manufactures a reading
    the engine never made, which is the fabricated-value failure the extraction
    layer is built to avoid.
    """
    import pytesseract
    from PIL import Image, ImageDraw, ImageFont

    results: dict = {"languages": "+".join(languages), "rendered": [], "unicharset": {}}

    fonts = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in fonts:
        try:
            font = ImageFont.truetype(path, 64)
        except OSError:
            continue
        image = Image.new("L", (700, 130), 255)
        ImageDraw.Draw(image).text((20, 20), f"{RUPEE} 0.08 per g", font=font, fill=0)
        try:
            read = pytesseract.image_to_string(
                image, lang="+".join(languages), config="--psm 7 --oem 3"
            ).strip()
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            read = f"<{exc.__class__.__name__}>"
        results["rendered"].append(
            {"font": Path(path).name, "read": read, "emitted_rupee": RUPEE in read}
        )

    for language in languages:
        results["unicharset"][language] = _unicharset_has_rupee(language)
    return results


def _unicharset_has_rupee(language: str) -> dict:
    """Whether `language`'s LSTM alphabet contains `₹`.

    Reads the alphabet out of the installed `.traineddata` with
    `combine_tessdata -u`, which ships with Tesseract. Returns a `reason`
    instead of a verdict when the file or the tool cannot be found - "we could
    not check" and "the character is absent" are different answers and must not
    collapse into one.
    """
    import shutil
    import subprocess
    import tempfile

    tool = shutil.which("combine_tessdata")
    if tool is None:
        return {"checked": False, "reason": "combine_tessdata is not on PATH"}

    data_dir = _tessdata_dir()
    if data_dir is None:
        return {"checked": False, "reason": "could not locate the tessdata directory"}
    source = data_dir / f"{language}.traineddata"
    if not source.exists():
        return {"checked": False, "reason": f"{source.name} is not installed"}

    with tempfile.TemporaryDirectory(prefix="labelextract-unicharset-") as temp:
        prefix = Path(temp) / f"{language}."
        # No shell, and every argument is a path this function built.
        subprocess.run(
            [tool, "-u", str(source), str(prefix)],
            check=False, capture_output=True, timeout=60,
        )
        alphabet_file = prefix.with_name(f"{language}.lstm-unicharset")
        if not alphabet_file.exists():
            return {"checked": False, "reason": "no lstm-unicharset in the traineddata"}
        text = alphabet_file.read_bytes().decode("utf-8", errors="replace")

    entries = [line.split(" ")[0] for line in text.splitlines()[1:] if line.strip()]
    return {
        "checked": True,
        "alphabet_size": len(entries),
        "has_rupee": RUPEE in entries,
        "currency_glyphs_present": sorted(
            c for c in ("$", "\u00a2", "\u00a3", "\u00a5", "\u20ac", RUPEE) if c in entries
        ),
    }


def _tessdata_dir() -> Path | None:
    """Where Tesseract is reading language data from, asked of Tesseract."""
    import os
    import re
    import subprocess

    prefix = os.environ.get("TESSDATA_PREFIX")
    if prefix and Path(prefix).is_dir():
        return Path(prefix)
    try:
        listing = subprocess.run(
            ["tesseract", "--list-langs"], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'in "(.+?)"', listing.stdout + listing.stderr)
    if not match:
        return None
    candidate = Path(match.group(1))
    return candidate if candidate.is_dir() else None


def build_pipeline_for(languages: tuple[str, ...]):
    """The production pipeline with `languages` swapped and nothing else.

    Built from the production factory's own objects rather than from a fresh
    `TesseractOptions()`, so that if a production default moves this experiment
    moves with it instead of quietly measuring last month's configuration.
    """
    from labelextract.ocr.tesseract import TesseractOcrEngine, build_pipeline

    pipeline = build_pipeline()
    production_options = pipeline.ocr_engine.options
    pipeline.ocr_engine = TesseractOcrEngine(
        replace(production_options, languages=languages)
    )
    pipeline.version = f"{pipeline.version}+lang={'+'.join(languages)}"
    return pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="directory holding MANIFEST.json")
    parser.add_argument("--report-dir", required=True, help="where JSON reports go")
    parser.add_argument(
        "--skip-checksums", action="store_true",
        help="structural check only; a published measurement must not use this",
    )
    args = parser.parse_args(argv)

    from labelextract.evaluation.dataset import load_dataset
    from labelextract.evaluation.runner import evaluate

    reports = Path(args.report_dir)
    reports.mkdir(parents=True, exist_ok=True)

    installed = available_languages()
    print(f"tesseract languages installed: {sorted(installed)}")

    capability = {
        name: rupee_capability(langs)
        for name, langs in CONFIGURATIONS
        if set(langs) <= installed
    }
    (reports / "rupee-capability.json").write_text(
        json.dumps(capability, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for name, result in capability.items():
        emitted = any(r["emitted_rupee"] for r in result["rendered"])
        print(f"  {name:10} emits U+20B9 on rendered type: {emitted}")
        for language, alphabet in result["unicharset"].items():
            if alphabet.get("checked"):
                print(
                    f"    {language}.traineddata alphabet={alphabet['alphabet_size']} "
                    f"has_rupee={alphabet['has_rupee']} "
                    f"currency={alphabet['currency_glyphs_present']}"
                )
            else:
                print(f"    {language}.traineddata not checked: {alphabet['reason']}")

    dataset = load_dataset(Path(args.dataset), verify_checksums=not args.skip_checksums)
    skipped: list[str] = []
    for name, languages in CONFIGURATIONS:
        missing = sorted(set(languages) - installed)
        if missing:
            # Not silently downgraded to whatever *is* installed. See the module
            # docstring: `-l eng+hin` without `hin` returns the `eng` result and
            # exit code 0, and reporting that as an `eng+hin` measurement would
            # be reporting the baseline twice under two names.
            print(f"  SKIP {name}: language data not installed: {', '.join(missing)}")
            skipped.append(name)
            continue
        report = evaluate(dataset, build_pipeline_for(languages))
        destination = reports / f"lang-{name.replace('+', '_')}.json"
        destination.write_text(report.to_json(), encoding="utf-8")
        print(f"  RAN  {name}: wrote {destination.name}")

    if skipped:
        print(
            f"\n{len(skipped)} configuration(s) skipped for missing language data: "
            f"{', '.join(skipped)}.\nInstall it outside the repository - see this "
            f"module's docstring - then re-run.",
            file=sys.stderr,
        )
        return 4
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
