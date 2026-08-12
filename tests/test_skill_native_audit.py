from pathlib import Path

from scripts.audit_skill_native import audit_skillsbench, audit_skillflow


def test_skillsbench_audit_reads_taxonomy_and_skill_packages(tmp_path: Path):
    task = tmp_path / "tasks" / "one"
    (task / "environment/skills/xlsx").mkdir(parents=True)
    (task / "environment/skills/xlsx/SKILL.md").write_text("# xlsx")
    (task / "task.md").write_text(
        "---\nmetadata:\n  difficulty: medium\n  category: office-white-collar\n"
        "  modality: [spreadsheet]\n  task_type: [transformation]\n---\nDo it.\n"
    )
    report = audit_skillsbench(tmp_path)
    assert report["standard_tasks"] == 1
    assert report["skill_packages"] == 1
    assert report["distributions"]["category"]["office-white-collar"] == 1


def test_skillflow_audit_reads_family_and_task_toml(tmp_path: Path):
    task = tmp_path / "test_tasks" / "Family" / "task-1"
    (task / "environment").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "task.toml").write_text(
        'version="1.0"\n[metadata]\ndifficulty="hard"\ncategory="spreadsheet"\n'
    )
    (task / "instruction.md").write_text("Do it.")
    (task / "tests/test.sh").write_text("true")
    report = audit_skillflow(tmp_path)
    assert report["families"] == 1
    assert report["tasks"] == 1
    assert report["family_task_counts"]["Family"] == 1
