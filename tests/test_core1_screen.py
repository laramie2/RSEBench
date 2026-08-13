from __future__ import annotations

import json

from scripts.run_core1_screen import (
    Core1Screen,
    SubprocessDispatcher,
    build_core1_cells,
    classify_result,
)


def test_core1_matrix_has_exactly_four_domains_times_four_ordered_stages() -> None:
    cells = build_core1_cells()

    assert len(cells) == 16
    assert len({cell.cell_id for cell in cells}) == 16
    assert [cell.stage for cell in cells[:4]] == ["N3", "N4", "N2", "N1"]
    assert {(cell.benchmark, cell.method) for cell in cells} == {
        ("spreadsheetbench_verified", "skillopt"),
        ("officeqa_full", "skillopt"),
        ("skilllearnbench", "skilllearn_self_feedback"),
        ("skilllearnbench", "skilllearn_teacher_feedback"),
        ("webshop", "skilladaptor"),
    }
    assert all(cell.form == ("static" if cell.stage in {"N1", "N2"} else "runtime") for cell in cells)


def test_classification_distinguishes_harm_null_and_opposite() -> None:
    assert classify_result(clean_score=0.7, noisy_score=0.4) == "passed"
    assert classify_result(clean_score=0.7, noisy_score=0.7) == "null"
    assert classify_result(clean_score=0.4, noisy_score=0.7) == "opposite"


def test_screen_resume_does_not_repeat_completed_cells(tmp_path) -> None:
    calls: list[str] = []

    def dispatch(cell, smoke_only):
        calls.append(cell.cell_id)
        return {
            "clean_score": 0.75,
            "noisy_score": 0.5,
            "run_dir": f"runs/{cell.cell_id}",
            "token_usage": {"billed_tokens": {"total_tokens": 50}},
        }

    cells = build_core1_cells()[:2]
    screen = Core1Screen(output_dir=tmp_path, dispatcher=dispatch)
    first = screen.run(cells, smoke_only=False, resume=True)
    second = screen.run(cells, smoke_only=False, resume=True)

    assert calls == [cell.cell_id for cell in cells]
    assert first == second
    assert {row["status"] for row in second["cells"]} == {"passed"}
    persisted = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert persisted == second


def test_screen_persists_blocked_exception_without_fake_scores(tmp_path) -> None:
    def dispatch(cell, smoke_only):
        raise RuntimeError("provider unavailable")

    screen = Core1Screen(output_dir=tmp_path, dispatcher=dispatch)
    result = screen.run(build_core1_cells()[:1], smoke_only=True, resume=False)

    row = result["cells"][0]
    assert row["status"] == "blocked"
    assert row["clean_score"] is None
    assert row["noisy_score"] is None
    assert "provider unavailable" in row["detail"]


def test_screen_rejects_dispatch_when_estimate_exceeds_profile_cap(tmp_path) -> None:
    called = False

    def dispatch(cell, smoke_only):
        nonlocal called
        called = True
        return {}

    cell = build_core1_cells()[0].model_copy(
        update={"token_cap": 10, "estimated_tokens": 11}
    )
    result = Core1Screen(output_dir=tmp_path, dispatcher=dispatch).run(
        [cell], smoke_only=False, resume=False
    )

    assert called is False
    assert result["cells"][0]["status"] == "blocked"
    assert "token cap" in result["cells"][0]["detail"]


def test_webshop_static_cell_passes_frozen_overlay_to_paired_runner(tmp_path) -> None:
    cell = next(
        cell
        for cell in build_core1_cells()
        if cell.benchmark == "webshop" and cell.stage == "N1"
    )
    split = tmp_path / "benchmark/core1/splits/webshop/N1.json"
    split.parent.mkdir(parents=True)
    split.write_text("{}", encoding="utf-8")
    dispatcher = SubprocessDispatcher(output_dir=tmp_path, root=tmp_path)

    command = dispatcher._command(cell, smoke_only=True)  # noqa: SLF001

    assert "--static-noise-path" in command
    path = command[command.index("--static-noise-path") + 1]
    assert path.endswith("benchmark/core1/static_data/webshop/N1.json")


def test_webshop_smoke_keeps_enough_steps_to_avoid_artificial_floor(tmp_path) -> None:
    cell = next(
        cell
        for cell in build_core1_cells()
        if cell.benchmark == "webshop" and cell.stage == "N3"
    )
    split = tmp_path / "benchmark/core1/splits/webshop/N3.json"
    split.parent.mkdir(parents=True)
    split.write_text("{}", encoding="utf-8")
    dispatcher = SubprocessDispatcher(output_dir=tmp_path, root=tmp_path)

    command = dispatcher._command(cell, smoke_only=True)  # noqa: SLF001

    assert command[command.index("--max-episode-steps") + 1] == "8"


def test_officeqa_gets_multidocument_turn_budget(tmp_path) -> None:
    cell = next(
        cell
        for cell in build_core1_cells()
        if cell.benchmark == "officeqa_full" and cell.stage == "N3"
    )
    split = tmp_path / "benchmark/core1/splits/officeqa_full/N3.json"
    split.parent.mkdir(parents=True)
    split.write_text("{}", encoding="utf-8")
    dispatcher = SubprocessDispatcher(output_dir=tmp_path, root=tmp_path)

    command = dispatcher._command(cell, smoke_only=True)  # noqa: SLF001

    assert command[command.index("--max-turns") + 1] == "6"


def test_skilllearn_screen_rejects_floor_and_ceiling_before_evolution(tmp_path) -> None:
    cell = next(
        cell
        for cell in build_core1_cells()
        if cell.benchmark == "skilllearnbench" and cell.stage == "N3"
    )
    split = tmp_path / "benchmark/core1/splits/skilllearnbench/N3.json"
    split.parent.mkdir(parents=True)
    split.write_text("{}", encoding="utf-8")
    dispatcher = SubprocessDispatcher(output_dir=tmp_path, root=tmp_path)

    command = dispatcher._command(cell, smoke_only=True)  # noqa: SLF001

    assert command[command.index("--seed-score-min") + 1] == "0.0"
    assert command[command.index("--seed-score-max") + 1] == "1.0"
