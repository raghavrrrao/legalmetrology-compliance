"""Exception hierarchy for the extraction layer.

The backend catches `LabelExtractError` to mark an extraction run as failed
without needing to know anything about a specific engine implementation. Each
class carries a stable `code` that is persisted and surfaced through the API,
so the frontend can branch on it without parsing English messages.
"""


class LabelExtractError(Exception):
    """Base class for every error raised by this package."""

    code = "extraction_error"


class InvalidImageError(LabelExtractError):
    """The image is unusable: unreadable, empty, or not a decodable image."""

    code = "invalid_image"


class EngineNotAvailableError(LabelExtractError):
    """An engine was requested but its binary, model or runtime is not installed."""

    code = "engine_not_available"


class PipelineNotFoundError(LabelExtractError):
    """No pipeline is registered under the requested name/version."""

    code = "pipeline_not_found"


class UnsupportedImageFormatError(InvalidImageError):
    """The file decodes, but not as a format this pipeline accepts.

    A subclass of `InvalidImageError` so existing handlers that catch the
    broader case keep working; the distinct `code` lets the UI say "convert
    this to JPEG/PNG" instead of "this file is broken", which are different
    instructions for the user.

    The code matches `apps.images.validators`' own
    `unsupported_image_format`, so the same string reaches the frontend whether
    the format was rejected at upload or inside the pipeline.
    """

    code = "unsupported_image_format"


class ImageTooLargeError(InvalidImageError):
    """The image exceeds the byte or pixel budget this pipeline will process.

    Django rejects oversized uploads before they are stored. This is the same
    guard applied again inside `ml/`, which is callable from a CLI or a script
    with no Django in front of it. Decompression bombs are cheap to send and
    expensive to decode, so the limit is enforced wherever decoding happens.
    """

    code = "image_too_large"


class PreprocessingError(LabelExtractError):
    """Image preparation failed before recognition was attempted.

    Distinct from `InvalidImageError`: the file was decodable, but a transform
    (rotation, conversion, resize) could not be completed. Kept separate so a
    preprocessing regression is not misread as "users are uploading bad files".
    """

    code = "preprocessing_failed"


class OcrFailureError(LabelExtractError):
    """The OCR engine was available but failed while recognising this image.

    An operational failure - a crashed subprocess, a timeout, unparseable
    engine output - not a bug in our code and not an unreadable image. It is a
    `LabelExtractError` so the pipeline records a failed run rather than
    letting one bad image take down a request.

    Recognising *nothing* is NOT this error: an empty `OcrResult` is a valid
    outcome that becomes `ExtractionStatus.EMPTY`.
    """

    code = "ocr_failed"


class FieldExtractionError(LabelExtractError):
    """The field extractor could not run over the recognised text.

    Reserved for the extractor being unable to operate at all. An individual
    malformed candidate must NOT raise this - it is skipped and recorded, so
    one unparseable line cannot discard every declaration read from the label.
    """

    code = "field_extraction_failed"
