import pytest

from labelextract import registry
from labelextract.baseline import null_engine
from labelextract.exceptions import PipelineNotFoundError


def test_null_engine_is_registered():
    assert (null_engine.NAME, null_engine.VERSION) in list(
        registry.available_pipelines()
    )


def test_unknown_pipeline_raises():
    with pytest.raises(PipelineNotFoundError):
        registry.get_pipeline("does-not-exist", "9.9.9")


def test_pipeline_instances_are_cached():
    """Loading an OCR model must happen once per process, not per request."""
    first = registry.get_pipeline(null_engine.NAME, null_engine.VERSION)
    second = registry.get_pipeline(null_engine.NAME, null_engine.VERSION)
    assert first is second

    registry.clear_cache()
    assert registry.get_pipeline(null_engine.NAME, null_engine.VERSION) is not first


def test_duplicate_registration_is_rejected():
    """Otherwise which engine ran would depend on import order."""
    with pytest.raises(ValueError):
        registry.register_pipeline(
            null_engine.NAME, null_engine.VERSION, null_engine.build_pipeline
        )
