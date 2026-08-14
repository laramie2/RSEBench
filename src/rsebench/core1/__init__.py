"""Core-1 construction API with domain-isolated optional dependencies."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "Core1OperatorProfile": "rsebench.core1.contracts",
    "Core1Profile": "rsebench.core1.contracts",
    "load_core1_profiles": "rsebench.core1.contracts",
    "Core1NoiseProfile": "rsebench.core1.materialize",
    "Core1Sizes": "rsebench.core1.materialize",
    "StaticPairManifest": "rsebench.core1.materialize",
    "freeze_static_pair": "rsebench.core1.materialize",
    "load_core1_noise_profile": "rsebench.core1.materialize",
    "materialize_core1_profile": "rsebench.core1.materialize",
    "SpreadsheetPromptPair": "rsebench.core1.spreadsheet",
    "build_spreadsheet_n1_pair": "rsebench.core1.spreadsheet",
    "build_spreadsheet_n2_pair": "rsebench.core1.spreadsheet",
    "OfficeQAPromptPair": "rsebench.core1.officeqa",
    "build_conflicting_period_fixture": "rsebench.core1.officeqa",
    "build_officeqa_n1_pair": "rsebench.core1.officeqa",
    "SkillLearnArtifactPair": "rsebench.core1.skilllearn",
    "SkillLearnFamily": "rsebench.core1.skilllearn",
    "SkillLearnPromptPair": "rsebench.core1.skilllearn",
    "SkillLearnSplit": "rsebench.core1.skilllearn",
    "build_skilllearn_n1_pair": "rsebench.core1.skilllearn",
    "build_skilllearn_n2_pair": "rsebench.core1.skilllearn",
    "build_skilllearn_split": "rsebench.core1.skilllearn",
    "discover_skilllearn_families": "rsebench.core1.skilllearn",
    "WebShopGoalConstraints": "rsebench.core1.webshop",
    "WebShopN1Context": "rsebench.core1.webshop",
    "WebShopNearMatch": "rsebench.core1.webshop",
    "WebShopRankingOverlay": "rsebench.core1.webshop",
    "build_webshop_n1_context": "rsebench.core1.webshop",
    "build_webshop_n2_overlay": "rsebench.core1.webshop",
    "parse_goal_constraints": "rsebench.core1.webshop",
    "select_near_match": "rsebench.core1.webshop",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
