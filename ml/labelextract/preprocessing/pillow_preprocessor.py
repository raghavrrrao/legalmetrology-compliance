"""Pillow-based preparation of a photograph for OCR.

Why Pillow and not OpenCV
-------------------------
Pillow is already a backend dependency (upload validation decodes every file
with it), so this stage adds no new install for anyone on the team. OpenCV
would add ~60 MB and a wheel that behaves differently across the operating
systems six people are using, in exchange for transforms - true deskew,
adaptive thresholding - that we cannot yet show are an improvement, because we
have no annotated evaluation set to measure them against. When that set exists
and the numbers justify it, this class is one of three components behind an
interface: replacing it changes nothing else.

What is applied, and why each earns its place
---------------------------------------------
1. **EXIF orientation** (`exif_transpose`). Phone cameras record a landscape
   sensor reading plus a rotation tag. Tesseract reads pixels and ignores the
   tag, so a portrait photo of a label arrives sideways and recognition
   collapses. This is the single highest-value transform here and it is the
   reason this stage exists at all.
2. **Grayscale.** Colour carries no information for character recognition, and
   Tesseract converts internally anyway. Doing it once here makes the
   intermediate a third of the size.
3. **Contrast normalisation** (`autocontrast`, with a 1% cut-off at each end).
   Rescales the histogram so a flat, dim, or hazy photograph uses the full
   range. The cut-off stops one specular highlight from defining "white" and
   flattening the rest of the panel.

Deliberately NOT applied by default
-----------------------------------
- **Denoising.** A median filter removes sensor noise and also removes the
  strokes of 6-point print - the size at which net quantity and batch number
  are usually printed. Available as `denoise=True`, off until measured.
- **Resizing.** Available via `max_dimension` / `min_dimension`, both off.
  Enabling either makes bounding boxes land in preprocessed-image space, and
  nothing yet maps them back onto the original for the UI's evidence overlay.
  `ExtractionPipeline` records both sets of dimensions in run metadata so this
  is detectable rather than silent.
- **Deskew and perspective correction.** Genuinely useful for photographs of
  curved and hand-held packaging, and genuinely not implementable well without
  numpy/OpenCV. Stated as a limitation rather than approximated badly.

Safety
------
Byte size and pixel count are checked against a budget *before* the image is
loaded. Django applies its own limits at upload, but this package is callable
from a CLI or a script with no Django in front of it, and a decompression bomb
is cheap to send and expensive to decode.
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from labelextract.contracts import ImageRef
from labelextract.exceptions import (
    EngineNotAvailableError,
    ImageTooLargeError,
    InvalidImageError,
    PreprocessingError,
    UnsupportedImageFormatError,
)
from labelextract.imageio import readable_path
from labelextract.interfaces import ImagePreprocessor

logger = logging.getLogger(__name__)

NAME = "pillow-preprocessor"
VERSION = "0.1.0"

#: What a caller may declare, mapped to the canonical name it means. `jpg` and
#: `jpeg` are the same format spelled two ways, and a declaration of either
#: must match a decoded JPEG.
_DECLARED_TO_CANONICAL: dict[str, str] = {
    "jpeg": "jpeg",
    "jpg": "jpeg",
    "png": "png",
    "webp": "webp",
}

#: Pillow's own format identifiers, mapped to the same canonical names. Pillow
#: reports what it actually decoded, which is the authoritative answer about
#: what the file is.
_PILLOW_TO_CANONICAL: dict[str, str] = {
    "JPEG": "jpeg",
    "PNG": "png",
    "WEBP": "webp",
}

#: Formats this stage will open. Mirrors `apps.images.constants.ALLOWED_FORMATS`
#: rather than importing it - `ml/` must not depend on Django. The two lists
#: are checked against each other by a backend test.
SUPPORTED_FORMATS: frozenset[str] = frozenset(_DECLARED_TO_CANONICAL)


@dataclass(frozen=True)
class PreprocessingConfig:
    """What the preprocessor is allowed to do, and how far.

    Every default is the conservative choice. Turning something on is a
    decision someone should be able to justify with a measurement.
    """

    #: Apply the EXIF rotation tag. Almost always correct for phone photos.
    apply_exif_orientation: bool = True
    #: Convert to 8-bit grayscale.
    grayscale: bool = True
    #: Rescale the histogram to the full range.
    autocontrast: bool = True
    #: Fraction of the histogram ignored at each end by autocontrast, so a
    #: single blown-out highlight does not define white for the whole panel.
    autocontrast_cutoff_percent: int = 1
    #: 3x3 median filter. Off: it erases small print. See module docstring.
    denoise: bool = False
    #: Downscale so the longest side is at most this many pixels. None = never.
    #: Enabling this moves bounding boxes into preprocessed-image space.
    max_dimension: int | None = None
    #: Upscale so the longest side is at least this many pixels. None = never.
    #: Same bounding-box caveat.
    min_dimension: int | None = None

    # --- budget, enforced before the image is decoded ---
    #: 10 MB, matching `MAX_IMAGE_UPLOAD_SIZE_MB`'s default in the backend.
    max_bytes: int = 10 * 1024 * 1024
    #: 50 MP, matching `MAX_IMAGE_PIXELS`' default in the backend.
    max_pixels: int = 50_000_000

    def __post_init__(self) -> None:
        if not 0 <= self.autocontrast_cutoff_percent < 50:
            raise ValueError("autocontrast_cutoff_percent must be in [0, 50)")
        for name in ("max_dimension", "min_dimension"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive or None")
        if (
            self.max_dimension is not None
            and self.min_dimension is not None
            and self.min_dimension > self.max_dimension
        ):
            raise ValueError("min_dimension must not exceed max_dimension")
        if self.max_bytes <= 0 or self.max_pixels <= 0:
            raise ValueError("max_bytes and max_pixels must be positive")


class PillowPreprocessor(ImagePreprocessor):
    """Prepares an image for OCR and writes the result to a temporary file.

    The original is never modified - it is the evidence a user disputing a
    finding needs to see. Intermediates are written into a directory this
    instance owns and are deleted by `release()` as soon as the pipeline is
    finished with them.

    Instances are reused across requests (the registry caches pipelines), so
    nothing about a single image is stored on `self`.
    """

    name = NAME
    version = VERSION

    def __init__(
        self,
        config: PreprocessingConfig | None = None,
        *,
        output_dir: Path | None = None,
    ) -> None:
        """
        Args:
            config: Which transforms to apply. Defaults are conservative.
            output_dir: Where intermediates are written. Defaults to a private
                temporary directory created on first use and removed when the
                process exits, so nothing is left behind by a crash that
                bypasses `release()`.
        """
        self.config = config or PreprocessingConfig()
        self._explicit_output_dir = output_dir
        self._temp_dir = None

    # --- lifecycle ----------------------------------------------------------

    def warmup(self) -> None:
        """Confirm Pillow is importable before the first upload arrives."""
        self._pillow()

    def process(self, image: ImageRef) -> ImageRef:
        Image, ImageOps, ImageFilter = self._pillow()

        self._check_budget(image)
        source_path = readable_path(image)

        # Two stages, two `try` blocks, because they fail for opposite reasons
        # and must not share an error code. Reading is about the *input*: a
        # truncated file, a renamed script, a decoder that refuses. Writing is
        # about *our own* storage: a full disk, a read-only temp directory, a
        # permission problem. Telling a user to retake a photograph because our
        # disk filled up would send them to fix something that is not broken.
        prepared = self._read_and_transform(image, source_path, Image, ImageOps,
                                            ImageFilter)
        return self._write(prepared)

    def _read_and_transform(self, image, source_path, Image, ImageOps, ImageFilter):
        """Decode the source and apply the configured transforms.

        Every failure here is a fact about the *input file*.

        Raises:
            InvalidImageError: the bytes could not be decoded.
            ImageTooLargeError / UnsupportedImageFormatError: budget or format.
            PreprocessingError: a transform failed on a decodable image.
        """
        try:
            with Image.open(source_path) as opened:
                # Header only at this point - no pixel data has been decoded,
                # so the bomb guard runs before the expensive part.
                self._check_declared_pixels(opened.size)
                self._check_format(opened.format, image.image_format)
                # `_apply` always returns a new image, never `opened` itself,
                # so the result stays valid after this `with` closes the file.
                return self._apply(opened, Image, ImageOps, ImageFilter)
        except (ImageTooLargeError, UnsupportedImageFormatError, InvalidImageError):
            raise
        except FileNotFoundError as exc:
            raise InvalidImageError(f"Image file does not exist: {source_path}") from exc
        except OSError as exc:
            # Pillow reports both "these bytes are not an image" and "this
            # image is truncated" as OSError subclasses. Either way the file is
            # unusable as input, which is InvalidImageError, not a transform
            # failure.
            raise InvalidImageError(
                f"Image could not be decoded: {exc.__class__.__name__}"
            ) from exc
        except Exception as exc:
            raise PreprocessingError(
                f"Preprocessing failed: {exc.__class__.__name__}"
            ) from exc

    def _write(self, prepared) -> ImageRef:
        """Persist the prepared image and describe it.

        Every failure here is a fact about *our* storage, never about the
        user's file, so all of them are `PreprocessingError`. That includes
        creating the output directory and stat-ing the result: a write that
        appears to succeed but leaves nothing on disk is a storage failure too,
        and returning an `ImageRef` to a file that is not there would surface
        later as a far more confusing "image does not exist" from the OCR
        stage.

        Raises:
            PreprocessingError: the intermediate could not be written or read
                back.
        """
        destination: Path | None = None
        try:
            destination = self._destination()
            # PNG for the intermediate: lossless, so preprocessing never
            # introduces the JPEG ringing that would then be handed to OCR as
            # if it were on the package.
            prepared.save(destination, format="PNG")
            size_bytes = destination.stat().st_size
        except Exception as exc:
            # `save()` can fail *after* creating the file - a partial write on
            # a full disk - and `stat()` can fail on a file that was written
            # successfully. Either way nobody downstream receives this path, so
            # nothing will ever call `release()` for it and it would sit in the
            # output directory until the process exits. Discard it here.
            #
            # `_discard` never raises, so it cannot displace the failure being
            # reported, and the original exception is still chained.
            if destination is not None:
                self._discard(destination)
            # One clause, because every outcome here is the same finding: the
            # image is fine and our storage is not. `OSError` covers the disk
            # and permission cases; Pillow can also raise its own encoder
            # errors, and those are equally not the user's problem.
            raise PreprocessingError(
                f"Could not write the preprocessed image: "
                f"{exc.__class__.__name__}"
            ) from exc

        width, height = prepared.size
        return ImageRef(
            path=destination,
            image_format="png",
            size_bytes=size_bytes,
            width=width,
            height=height,
        )

    def release(self, processed: ImageRef) -> None:
        """Delete an intermediate this preprocessor wrote.

        Never raises, idempotent, and never deletes anything outside the
        directory it owns - a preprocessor handed someone else's path must not
        remove it, and the original image is the evidence a disputed finding is
        checked against.
        """
        self._discard(processed.path)

    def _discard(self, path: Path) -> None:
        """Best-effort removal of one file this preprocessor created.

        The single place intermediates are deleted, used both by `release()`
        and by the write-failure path in `_write`, so "only inside the
        directory we own" is enforced once rather than twice.

        Idempotent - deleting an already-deleted file is not an error - and it
        never raises. Losing an extraction result, or displacing the exception
        that explains a failure, because a temporary file could not be deleted
        would be a strictly worse outcome than the leftover file.
        """
        try:
            owned = self._output_dir().resolve()
            target = path.resolve()
            if target.parent != owned:
                logger.warning(
                    "Refusing to release a path outside the preprocessing "
                    "directory: %s",
                    target,
                )
                return
            target.unlink(missing_ok=True)
        except Exception:
            logger.warning("Could not release preprocessed image", exc_info=True)

    # --- transforms ---------------------------------------------------------

    def _apply(self, opened, Image, ImageOps, ImageFilter):
        """Run the configured transforms, in the only order that makes sense.

        The order is: **orientation, colour, resize, denoise, contrast.**

        1. Orientation first, because it decides which side is up and every
           later step is cheaper to reason about once it is settled.
        2. Colour conversion next, so the resample and the filters that follow
           move one channel instead of three.
        3. Resize (when configured), before the tonal work.
        4. Denoise (when configured), on the pixels that will be recognised.
        5. Contrast last, so it measures the histogram of the image OCR will
           actually see rather than one of an intermediate that no longer
           exists.

        Always returns a new image - `convert()` runs unconditionally - so the
        caller may close the source file immediately afterwards.
        """
        image = opened
        if self.config.apply_exif_orientation:
            # Returns a new image and strips the tag, so the rotation cannot be
            # applied twice by anything downstream.
            image = ImageOps.exif_transpose(image)

        if self.config.grayscale:
            image = image.convert("L")
        else:
            image = image.convert("RGB")

        image = self._resize(image, Image)

        if self.config.denoise:
            image = image.filter(ImageFilter.MedianFilter(size=3))

        if self.config.autocontrast:
            image = ImageOps.autocontrast(
                image, cutoff=self.config.autocontrast_cutoff_percent
            )
        return image

    def _resize(self, image, Image):
        """Scale uniformly, or not at all. Aspect ratio is never altered."""
        width, height = image.size
        longest = max(width, height)
        if longest == 0:
            raise PreprocessingError("Image has a zero dimension")

        scale = 1.0
        if self.config.max_dimension is not None and longest > self.config.max_dimension:
            scale = self.config.max_dimension / longest
        elif (
            self.config.min_dimension is not None and longest < self.config.min_dimension
        ):
            scale = self.config.min_dimension / longest

        if scale == 1.0:
            return image

        target = (max(1, round(width * scale)), max(1, round(height * scale)))
        self._check_declared_pixels(target)
        # LANCZOS in both directions: it preserves the edges of small glyphs
        # better than bilinear, which is the whole point of resizing for OCR.
        return image.resize(target, Image.Resampling.LANCZOS)

    # --- guards -------------------------------------------------------------

    def _check_budget(self, image: ImageRef) -> None:
        if image.size_bytes > self.config.max_bytes:
            raise ImageTooLargeError(
                f"Image is {image.size_bytes} bytes; the limit is "
                f"{self.config.max_bytes}."
            )
        if image.width is not None and image.height is not None:
            self._check_declared_pixels((image.width, image.height))

    def _check_declared_pixels(self, size: tuple[int, int]) -> None:
        width, height = size
        if width <= 0 or height <= 0:
            raise InvalidImageError("Image reports a non-positive dimension")
        if width * height > self.config.max_pixels:
            raise ImageTooLargeError(
                f"Image is {width}x{height} pixels; the limit is "
                f"{self.config.max_pixels} total."
            )

    def _check_format(self, pillow_format: str | None, declared: str) -> None:
        """Reject on what the bytes decode as, not on what the caller claimed.

        Three checks, and the third is the one that matters most:

        1. The declared format must be one we accept.
        2. The decoded format must be one we accept - **the decoder's answer is
           authoritative**, because it is derived from the bytes rather than
           from anything a caller or a filename asserted.
        3. The two must agree.

        (3) is not redundant. Checking each side against the allowlist
        independently passes a file declared `webp` that decodes as PNG, since
        both are individually supported. That disagreement means the caller's
        record of the file is wrong, and every consumer of that record - the
        stored `ProductImage.image_format`, the API response, whatever a
        reviewer is shown - is wrong with it. The image may well be readable;
        the bookkeeping around it is not, so it is refused rather than silently
        corrected.

        `jpg` and `jpeg` are the same declaration, so they are compared after
        canonicalisation rather than as strings.

        Raises:
            UnsupportedImageFormatError: either side is unsupported, they
                disagree, or the decoder could not name the format at all.
        """
        canonical_declared = _DECLARED_TO_CANONICAL.get(declared.strip().lower())
        if canonical_declared is None:
            raise UnsupportedImageFormatError(
                f"Unsupported image format {declared!r}. Supported: "
                f"{', '.join(sorted(SUPPORTED_FORMATS))}."
            )

        if pillow_format is None:
            # Pillow names the format of anything it opens from a file, so this
            # means we have no authoritative answer to check against. Refused
            # rather than assumed: an unidentifiable format is exactly what the
            # decoded-format check exists to catch.
            raise UnsupportedImageFormatError(
                "The image format could not be determined from the file's "
                "contents."
            )

        canonical_decoded = _PILLOW_TO_CANONICAL.get(pillow_format.strip().upper())
        if canonical_decoded is None:
            raise UnsupportedImageFormatError(
                f"File decoded as {pillow_format}, which is not a supported "
                f"image format."
            )

        if canonical_decoded != canonical_declared:
            raise UnsupportedImageFormatError(
                f"Image format mismatch: declared {declared!r} but the file "
                f"decodes as {canonical_decoded}. The decoded format is "
                f"authoritative; the declared format is wrong."
            )

    # --- plumbing -----------------------------------------------------------

    @staticmethod
    def _pillow():
        """Import Pillow on first use.

        Kept out of module import so `labelextract`'s contracts remain
        installable with no dependencies, and so a missing Pillow surfaces as
        `EngineNotAvailableError` - a recorded, actionable failed run - rather
        than an ImportError at Django startup.
        """
        try:
            from PIL import Image, ImageFilter, ImageOps
        except ImportError as exc:
            raise EngineNotAvailableError(
                "Pillow is not installed. Install the OCR extra: "
                "pip install -e ./ml[ocr]"
            ) from exc
        return Image, ImageOps, ImageFilter

    def _output_dir(self) -> Path:
        if self._explicit_output_dir is not None:
            self._explicit_output_dir.mkdir(parents=True, exist_ok=True)
            return self._explicit_output_dir
        if self._temp_dir is None:
            # TemporaryDirectory registers its own finalizer, so the directory
            # and anything still in it are removed when this preprocessor is
            # collected or the process exits. A crash between process() and
            # release() therefore cannot leave intermediates behind for ever.
            # It also means intermediates live exactly as long as the
            # preprocessor that made them - which is the whole process, since
            # the registry caches one pipeline instance.
            self._temp_dir = tempfile.TemporaryDirectory(prefix="labelextract-pre-")
        return Path(self._temp_dir.name)

    def _destination(self) -> Path:
        """A fresh, unguessable name per call, so concurrent runs cannot collide."""
        return self._output_dir() / f"{uuid.uuid4().hex}.png"
