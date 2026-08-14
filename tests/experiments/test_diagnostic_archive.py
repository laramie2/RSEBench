from pathlib import Path

from rsebench.experiments.archive import build_diagnostic_manifest
from rsebench.hashing import sha256_tree


def test_build_diagnostic_manifest_is_portable_and_nonformal(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "outputs"
    run_root = output_root / "runs/clean-qualification-20260813"
    run_root.mkdir(parents=True)
    (run_root / "matrix_status.json").write_text("{}\n", encoding="utf-8")

    payload = build_diagnostic_manifest(
        run_root,
        output_root=output_root,
        git_head="6fb608c14fb601cdf1c8a34421b6f114110740f6",
    )

    assert payload["track"] == "diagnostic"
    assert payload["qualification_version"] == "clean-qualification-v1"
    assert payload["git_head"] == "6fb608c14fb601cdf1c8a34421b6f114110740f6"
    assert payload["run_root_hash"] == sha256_tree(run_root)
    assert payload["run_locator"] == (
        "rsebench-output://runs/clean-qualification-20260813"
    )
    assert payload["formal_qualification"] is False
    assert str(tmp_path) not in str(payload)
