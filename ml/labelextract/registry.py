"""Name/version lookup for extraction pipelines.

The backend asks for a pipeline by name and version. It never imports an engine
implementation directly, so adding, versioning or removing an OCR engine is a
change inside `ml/` only - `feature/ocr-processing` touches no Django code.

    from labelextract import registry
    pipeline = registry.get_pipeline("null-engine", "0.1.0")
    result = pipeline.run(image_ref)
"""

from __future__ import annotations

from typing import Callable, Iterator

from labelextract.exceptions import PipelineNotFoundError
from labelextract.pipeline import ExtractionPipeline

#: A zero-argument callable that builds a ready-to-use pipeline.
PipelineFactory = Callable[[], ExtractionPipeline]

_REGISTRY: dict[tuple[str, str], PipelineFactory] = {}
_CACHE: dict[tuple[str, str], ExtractionPipeline] = {}


def register_pipeline(name: str, version: str, factory: PipelineFactory) -> None:
    """Register `factory` under `name`/`version`.

    Raises:
        ValueError: a pipeline is already registered under this key. Silently
            replacing one would make which engine ran depend on import order.
    """
    key = (name, version)
    if key in _REGISTRY:
        raise ValueError(f"Pipeline already registered: {name} {version}")
    _REGISTRY[key] = factory


def get_pipeline(name: str, version: str) -> ExtractionPipeline:
    """Return the pipeline for `name`/`version`, building it on first use.

    Instances are cached, so loading an OCR model happens once per process.
    Implementations must therefore be safe to reuse across requests.

    Raises:
        PipelineNotFoundError: nothing is registered under this key.
    """
    key = (name, version)
    if key in _CACHE:
        return _CACHE[key]
    try:
        factory = _REGISTRY[key]
    except KeyError:
        raise PipelineNotFoundError(
            f"No extraction pipeline registered for name={name!r} "
            f"version={version!r}. Available: {sorted(_REGISTRY)}"
        ) from None
    pipeline = factory()
    _CACHE[key] = pipeline
    return pipeline


def available_pipelines() -> Iterator[tuple[str, str]]:
    """Yield every registered (name, version) pair, sorted."""
    yield from sorted(_REGISTRY)


def clear_cache() -> None:
    """Drop cached instances. Intended for tests and for reloading models."""
    _CACHE.clear()


def _register_builtin_pipelines() -> None:
    """Register the pipelines shipped with this package.

    Only names and factories are imported here - never Pillow, pytesseract or
    any engine's runtime. A factory resolves its own dependencies when it is
    first called, so importing `labelextract` on a machine with no OCR stack
    installed still works, still lists both pipelines, and still runs the whole
    test suite. Asking for a pipeline whose dependencies are missing raises
    `EngineNotAvailableError`, which the backend records as a failed run with
    an actionable error code.
    """
    from labelextract.baseline import null_engine
    from labelextract.ocr import tesseract

    register_pipeline(
        null_engine.NAME, null_engine.VERSION, null_engine.build_pipeline
    )
    register_pipeline(tesseract.NAME, tesseract.VERSION, tesseract.build_pipeline)


_register_builtin_pipelines()
