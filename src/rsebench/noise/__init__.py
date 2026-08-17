"""Noise-generation primitives, stage plugins, and compatibility bridges."""

from rsebench.noise.adapters import LegacyGeneratedNoiseAdapter, RuntimeMutationOperator
from rsebench.noise.base import GeneratedNoise, NoiseOperator
from rsebench.noise.contracts import (
    MethodEvidenceAdapter,
    NoisePlugin,
    RuntimeNoiseOperator,
    StaticNoiseOperator,
    StaticNoiseResult,
    StaticNoiseSpec,
)
from rsebench.noise.registry import discover_noise_plugins

__all__ = [
    "GeneratedNoise",
    "LegacyGeneratedNoiseAdapter",
    "MethodEvidenceAdapter",
    "NoiseOperator",
    "NoisePlugin",
    "RuntimeMutationOperator",
    "RuntimeNoiseOperator",
    "StaticNoiseOperator",
    "StaticNoiseResult",
    "StaticNoiseSpec",
    "discover_noise_plugins",
]
