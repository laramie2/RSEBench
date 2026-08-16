from __future__ import annotations

import pytest

from scripts.run_skillflow_clean import build_parser


def test_cli_has_all_control_plane_commands() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    for command in ("preflight", "screen", "confirm", "aggregate", "freeze"):
        assert command in help_text


def test_paid_commands_require_explicit_cost_confirmation() -> None:
    parser = build_parser()
    screen = parser.parse_args(["screen"])
    confirm = parser.parse_args(["confirm"])

    assert screen.confirm_provider_cost is False
    assert confirm.confirm_provider_cost is False
    assert screen.dry_run is False
    assert confirm.dry_run is False
    assert screen.batch == "a"


@pytest.mark.parametrize("command", ["preflight", "aggregate", "freeze"])
def test_offline_commands_have_no_cost_flag(command: str) -> None:
    parser = build_parser()
    args = parser.parse_args([command])
    assert not hasattr(args, "confirm_provider_cost")
