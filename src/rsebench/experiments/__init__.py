"""Unified experiment control interfaces and legacy pilot compatibility."""

from rsebench.experiments import legacy as _legacy


PROJECT_ROOT = _legacy.PROJECT_ROOT
DeepSeekClient = _legacy.DeepSeekClient
_answer_text = _legacy._answer_text
_cache_key = _legacy._cache_key
_correct = _legacy._correct


def run_math_execution_pilot(*, limit: int = 5):
    """Run the legacy pilot while honoring the package-level project root."""

    _legacy.PROJECT_ROOT = PROJECT_ROOT
    return _legacy.run_math_execution_pilot(limit=limit)


__all__ = ["run_math_execution_pilot"]
