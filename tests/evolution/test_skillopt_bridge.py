import json
from pathlib import Path

from rsebench.contracts import NoiseManifest, Severity, TaskManifest
from rsebench.evolution.contracts import EvolutionTaskPair
from rsebench.evolution.skillopt_bridge import materialize_skillopt_split
from rsebench.evolution.splits import build_evolution_split


def _task(task_id: str, benchmark: str, domain: str, prompt: str, **kwargs):
    return TaskManifest(
        task_id=task_id,
        benchmark=benchmark,
        domain=domain,
        prompt=prompt,
        gold_answers=kwargs.pop("gold_answers", ["gold"]),
        source_hash=(task_id.encode().hex() + "0" * 64)[:64],
        **kwargs,
    )


def _pair(clean: TaskManifest, noisy: TaskManifest) -> EvolutionTaskPair:
    return EvolutionTaskPair(
        pair_id=f"{clean.task_id}-pair",
        task_id=clean.task_id,
        clean=clean,
        noisy=noisy,
        noise=NoiseManifest(
            noise_id=f"{clean.task_id}-noise",
            task_id=clean.task_id,
            channel="C1",
            mechanism="M2",
            operator="failed_attempt",
            domain=clean.domain,
            benchmark=clean.benchmark,
            severity=Severity(level="L2", budget=2),
            seed=7,
            clean_hash=clean.source_hash,
            noisy_hash=noisy.source_hash,
            timing="evolution",
        ),
    )


def _items(path: Path, split: str) -> list[dict]:
    return json.loads((path / split / "items.json").read_text(encoding="utf-8"))


def test_materializes_spreadsheet_prompt_and_keeps_test_clean(tmp_path: Path):
    workbook_dir = tmp_path / "spreadsheet" / "s1"
    workbook_dir.mkdir(parents=True)
    initial = workbook_dir / "1_s1_init.xlsx"
    initial.write_bytes(b"fixture")
    clean = _task(
        "s1", "spreadsheetbench_verified", "spreadsheet", "clean sheet",
        artifact_path=str(initial),
        metadata={"answer_range": "A1", "answer_sheet": "Sheet1"},
    )
    noisy = clean.model_copy(update={"prompt": "noisy sheet", "source_hash": "1" * 64})
    test = _task(
        "s2", "spreadsheetbench_verified", "spreadsheet", "clean test",
        artifact_path=str(initial),
        metadata={"answer_range": "B2", "answer_sheet": "Sheet1"},
    )
    manifest = build_evolution_split(
        benchmark=clean.benchmark,
        domain=clean.domain,
        seed=7,
        source_hash="2" * 64,
        train=[_pair(clean, noisy)],
        validation=[],
        clean_test=[test],
    )

    clean_dir = materialize_skillopt_split(manifest, arm="clean", output_dir=tmp_path / "clean")
    noisy_dir = materialize_skillopt_split(manifest, arm="noisy", output_dir=tmp_path / "noisy")

    assert _items(clean_dir, "train")[0]["instruction"] == "clean sheet"
    assert _items(noisy_dir, "train")[0]["instruction"] == "noisy sheet"
    assert _items(clean_dir, "test") == _items(noisy_dir, "test")
    assert _items(clean_dir, "train")[0]["spreadsheet_path"] == str(workbook_dir)


def test_materializes_officeqa_and_livemath_native_fields(tmp_path: Path):
    office = _task(
        "o1", "officeqa_full", "document", "clean office",
        gold_answers=["42"],
        metadata={"gold_document_ids": ["docs/report.txt"], "category": "hard"},
    )
    office_noisy = office.model_copy(update={"prompt": "noisy office", "source_hash": "3" * 64})
    office_split = build_evolution_split(
        benchmark=office.benchmark,
        domain=office.domain,
        seed=7,
        source_hash="4" * 64,
        train=[_pair(office, office_noisy)],
        validation=[],
        clean_test=[office.model_copy(update={"task_id": "o2"})],
    )
    office_dir = materialize_skillopt_split(
        office_split, arm="noisy", output_dir=tmp_path / "office"
    )
    office_item = _items(office_dir, "train")[0]
    assert office_item["question"] == "noisy office"
    assert office_item["ground_truth"] == "42"
    assert office_item["source_files"] == ["report.txt"]

    math = _task(
        "202601:1", "livemathematicianbench", "math", "clean math",
        gold_answers=["B"],
        metadata={
            "month": "202601",
            "no": 1,
            "choices": [{"label": "A", "text": "x"}, {"label": "B", "text": "y"}],
            "correct_choice": {"label": "B", "text": "y"},
            "theorem_type": ["Inequality"],
        },
    )
    math_noisy = math.model_copy(update={"prompt": "noisy math", "source_hash": "5" * 64})
    math_split = build_evolution_split(
        benchmark=math.benchmark,
        domain=math.domain,
        seed=7,
        source_hash="6" * 64,
        train=[_pair(math, math_noisy)],
        validation=[],
        clean_test=[math.model_copy(update={"task_id": "202601:2"})],
    )
    math_dir = materialize_skillopt_split(
        math_split, arm="noisy", output_dir=tmp_path / "math"
    )
    math_item = _items(math_dir, "train")[0]
    assert math_item["question"] == "noisy math"
    assert math_item["correct_choice"]["label"] == "B"
    assert math_item["choices"][1]["text"] == "y"
