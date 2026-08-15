from __future__ import annotations


def test_resource_lock_script_exposes_formal_root_inputs() -> None:
    from scripts.build_noise_screen_resource_lock import build_parser

    help_text = build_parser().format_help()
    for option in (
        "--selection-root",
        "--data-root",
        "--methods-root",
        "--methods-registry",
        "--image-manifest",
        "--output",
    ):
        assert option in help_text
    assert "--input" not in help_text
