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


def test_materializes_dapo_exact_answer_fields(tmp_path: Path):
    math = _task(
        "hash-1",
        "dapo_fixed_1000",
        "math",
        "Solve clean problem",
        gold_answers=["89"],
        metadata={"ability": "MATH", "reward_style": "rule-lighteval/MATH_v2"},
    )
    noisy = math.model_copy(
        update={"prompt": "Incorrect attempt.\n\nSolve clean problem", "source_hash": "7" * 64}
    )
    split = build_evolution_split(
        benchmark=math.benchmark,
        domain=math.domain,
        seed=7,
        source_hash="8" * 64,
        train=[_pair(math, noisy)],
        validation=[],
        clean_test=[math.model_copy(update={"task_id": "hash-2"})],
    )

    native_dir = materialize_skillopt_split(
        split, arm="noisy", output_dir=tmp_path / "dapo"
    )
    item = _items(native_dir, "train")[0]

    assert item["id"] == "hash-1"
    assert item["question"].startswith("Incorrect attempt")
    assert item["ground_truth"] == "89"
    assert item["task_type"] == "MATH"


def test_officeqa_noisy_arm_uses_ranked_retrieval_fixture(tmp_path: Path):
    fixture = tmp_path / "retrieval.json"
    fixture.write_text(
        json.dumps(
            {
                "results": [
                    {"document_id": "docs/decoy-a.txt", "is_gold": False},
                    {"document_id": "docs/decoy-b.txt", "is_gold": False},
                    {"document_id": "docs/gold.txt", "is_gold": True},
                ],
                "expected_gold_rank": 3,
            }
        ),
        encoding="utf-8",
    )
    clean = _task(
        "o1",
        "officeqa_full",
        "document",
        "office question",
        gold_answers=["answer"],
        metadata={"gold_document_ids": ["docs/gold.txt"]},
    )
    noisy = clean.model_copy(
        update={
            "source_hash": "9" * 64,
            "artifact_path": str(fixture),
            "metadata": {
                **clean.metadata,
                "retrieval_fixture": str(fixture),
            },
        }
    )
    split = build_evolution_split(
        benchmark=clean.benchmark,
        domain=clean.domain,
        seed=7,
        source_hash="a" * 64,
        train=[_pair(clean, noisy)],
        validation=[],
        clean_test=[clean.model_copy(update={"task_id": "o2"})],
    )

    clean_dir = materialize_skillopt_split(
        split, arm="clean", output_dir=tmp_path / "clean-ranked"
    )
    noisy_dir = materialize_skillopt_split(
        split, arm="noisy", output_dir=tmp_path / "noisy-ranked"
    )

    assert _items(clean_dir, "train")[0]["source_files"] == ["gold.txt"]
    assert _items(noisy_dir, "train")[0]["source_files"] == [
        "decoy-a.txt",
        "decoy-b.txt",
        "gold.txt",
    ]
    assert _items(noisy_dir, "train")[0]["rsebench_expected_gold_rank"] == 3


def test_materializes_docvqa_image_and_answers(tmp_path: Path):
    image = tmp_path / "doc.png"
    image.write_bytes(b"png")
    clean = _task(
        "d1",
        "docvqa_10pct",
        "document",
        "What is the total?",
        gold_answers=["42", "forty two"],
        artifact_path=str(image),
        metadata={"question_types": ["figure"], "doc_id": "doc-1"},
    )
    noisy = clean.model_copy(
        update={"prompt": "A prior attempt says 41.\n\nWhat is the total?", "source_hash": "b" * 64}
    )
    split = build_evolution_split(
        benchmark=clean.benchmark,
        domain=clean.domain,
        seed=7,
        source_hash="c" * 64,
        train=[_pair(clean, noisy)],
        validation=[],
        clean_test=[clean.model_copy(update={"task_id": "d2"})],
    )

    native = materialize_skillopt_split(
        split, arm="noisy", output_dir=tmp_path / "docvqa"
    )
    item = _items(native, "train")[0]

    assert item["question"].startswith("A prior attempt")
    assert item["answers"] == ["42", "forty two"]
    assert item["image_path"] == str(image.resolve())
    assert item["task_type"] == "figure"


def test_materializes_searchqa_grounded_context(tmp_path: Path):
    clean = _task(
        "q1",
        "searchqa_skillopt",
        "document",
        "Who wrote it?",
        gold_answers=["Ada"],
        metadata={"context": "[DOC] Ada wrote the report."},
    )
    noisy = clean.model_copy(
        update={"prompt": "A prior attempt says Bob.\n\nWho wrote it?", "source_hash": "d" * 64}
    )
    split = build_evolution_split(
        benchmark=clean.benchmark,
        domain=clean.domain,
        seed=7,
        source_hash="e" * 64,
        train=[_pair(clean, noisy)],
        validation=[],
        clean_test=[clean.model_copy(update={"task_id": "q2"})],
    )

    native = materialize_skillopt_split(
        split, arm="noisy", output_dir=tmp_path / "searchqa"
    )
    item = _items(native, "train")[0]

    assert item["question"].startswith("A prior attempt says Bob")
    assert item["context"] == "[DOC] Ada wrote the report."
    assert item["answers"] == ["Ada"]
