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
