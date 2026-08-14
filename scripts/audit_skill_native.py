#!/usr/bin/env python
"""Audit task/skill pairing formats and distributions for diagnostic benches."""

from __future__ import annotations

import json
import os
import tomllib
from collections import Counter
from pathlib import Path

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _mapping(counter: Counter) -> dict[str, int]:
    return {str(key): value for key, value in counter.most_common()}


def _skillsbench_collection(root: Path, collection: str) -> dict:
    counters = {
        name: Counter()
        for name in (
            "difficulty",
            "category",
            "task_type",
            "modality",
            "interface",
            "skill_type",
        )
    }
    paths = sorted((root / collection).glob("*/task.md"))
    skill_counts: Counter = Counter()
    skill_names: Counter = Counter()
    for path in paths:
        parts = path.read_text(encoding="utf-8", errors="replace").split("---", 2)
        metadata = yaml.safe_load(parts[1]).get("metadata", {})
        for name, counter in counters.items():
            values = metadata.get(name, [])
            if not isinstance(values, list):
                values = [values]
            counter.update(str(value) for value in values if value not in (None, ""))
        skills_root = path.parent / "environment" / "skills"
        skills = (
            sorted(
                item
                for item in skills_root.iterdir()
                if item.is_dir() and (item / "SKILL.md").is_file()
            )
            if skills_root.exists()
            else []
        )
        skill_counts[len(skills)] += 1
        skill_names.update(item.name for item in skills)
    return {
        "tasks": len(paths),
        "skill_packages": sum(count * number for number, count in skill_counts.items()),
        "unique_skill_names": len(skill_names),
        "skill_packages_per_task": _mapping(skill_counts),
        "top_skill_names": _mapping(Counter(dict(skill_names.most_common(30)))),
        "distributions": {name: _mapping(counter) for name, counter in counters.items()},
    }


def audit_skillsbench(root: Path | str) -> dict:
    benchmark_root = Path(root)
    standard = _skillsbench_collection(benchmark_root, "tasks")
    extra = _skillsbench_collection(benchmark_root, "tasks-extra")
    return {
        "format": "BenchFlow task.md YAML front matter + instruction body",
        "standard_tasks": standard["tasks"],
        "extra_tasks": extra["tasks"],
        "skill_packages": standard["skill_packages"],
        "unique_skill_names": standard["unique_skill_names"],
        "skill_packages_per_task": standard["skill_packages_per_task"],
        "distributions": standard["distributions"],
        "tasks_extra": extra,
    }


def audit_skillflow(root: Path | str) -> dict:
    benchmark_root = Path(root)
    task_root = benchmark_root / "test_tasks"
    family_counts: Counter = Counter()
    difficulties: Counter = Counter()
    categories: Counter = Counter()
    tags: Counter = Counter()
    extensions: Counter = Counter()
    bundled_skills: Counter = Counter()
    test_files: Counter = Counter()
    task_paths = sorted(task_root.glob("*/*/task.toml"))
    for task_path in task_paths:
        family_counts[task_path.parents[1].name] += 1
        payload = tomllib.loads(task_path.read_text(encoding="utf-8"))
        metadata = payload.get("metadata", {})
        difficulties[str(metadata.get("difficulty", "missing"))] += 1
        categories[str(metadata.get("category", "missing"))] += 1
        tags.update(str(tag) for tag in metadata.get("tags", []))
        task_dir = task_path.parent
        environment = task_dir / "environment"
        for candidate in environment.rglob("*"):
            if candidate.is_file() and "skills" not in candidate.parts:
                extensions[candidate.suffix.casefold() or "<noext>"] += 1
        skills_root = environment / "skills"
        bundled_skills[
            sum(1 for item in skills_root.iterdir() if item.is_dir())
            if skills_root.exists()
            else 0
        ] += 1
        test_files[sum(1 for item in (task_dir / "tests").glob("*") if item.is_file())] += 1
    return {
        "format": "family/task directory with task.toml, instruction.md, environment, solution, tests",
        "families": len(family_counts),
        "tasks": len(task_paths),
        "family_task_counts": _mapping(family_counts),
        "difficulty": _mapping(difficulties),
        "category": _mapping(categories),
        "top_tags": _mapping(Counter(dict(tags.most_common(30)))),
        "environment_file_extensions": _mapping(extensions),
        "bundled_skill_dirs_per_task": _mapping(bundled_skills),
        "verifier_files_per_task": _mapping(test_files),
    }


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    methods_root = Path(
        os.environ.get("RSEBENCH_METHODS_ROOT", PROJECT_ROOT / "methods/external")
    )
    data_root = Path(os.environ.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data"))
    report = {
        "skillsbench": audit_skillsbench(methods_root / "skillsbench"),
        "skillflow": audit_skillflow(data_root / "raw/skillflow_tasks"),
    }
    output = PROJECT_ROOT / "outputs/audits/skill-native.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(output)
    print(
        f"SkillsBench standard={report['skillsbench']['standard_tasks']} "
        f"skills={report['skillsbench']['skill_packages']}"
    )
    print(
        f"SkillFlow families={report['skillflow']['families']} "
        f"tasks={report['skillflow']['tasks']}"
    )


if __name__ == "__main__":
    main()
