"""Image preparation, kept strictly separate from recognition.

One implementation so far: `PillowPreprocessor`. It is deliberately small.
Every transform it applies has a stated reason and can be switched off, because
preprocessing that is not measured against a real evaluation set is as likely
to hurt recognition as help it - aggressive denoising in particular erases the
thin strokes of small print, which is exactly the text on a label we most need.

Importing this module does not require Pillow. `PillowPreprocessor` imports it
on first use and raises `EngineNotAvailableError` if it is missing, so
`labelextract`'s contracts stay dependency-free.
"""

from labelextract.preprocessing.pillow_preprocessor import (
    PillowPreprocessor,
    PreprocessingConfig,
)

__all__ = ["PillowPreprocessor", "PreprocessingConfig"]
