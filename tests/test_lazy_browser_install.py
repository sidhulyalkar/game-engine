import subprocess
import sys

import pytest

from game_engine.autonomous import TournamentFailure, _browser_install_command, _install_browser_engines
from game_engine.cli import build_parser


def test_browser_install_command_is_explicit_and_browser_scoped():
    command = _browser_install_command(("chromium", "firefox", "webkit"))
    assert command == [
        sys.executable,
        "-m",
        "playwright",
        "install",
        "--with-deps",
        "chromium",
        "firefox",
        "webkit",
    ]


def test_browser_install_command_requires_at_least_one_engine():
    with pytest.raises(ValueError, match="at least one browser"):
        _browser_install_command(())


def test_browser_install_failure_is_classified_as_its_own_tournament_stage(monkeypatch):
    calls = []

    def fail(command, check):
        calls.append((command, check))
        raise subprocess.CalledProcessError(7, command)

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(TournamentFailure) as exc_info:
        _install_browser_engines(("chromium",))

    assert exc_info.value.stage == "browser-engine-install"
    assert "exit code 7" in exc_info.value.message
    assert calls == [([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"], True)]


def test_autonomous_cli_exposes_on_demand_browser_install_without_changing_default():
    parser = build_parser()
    default_args = parser.parse_args(["autonomous-tournament", "brief.json"])
    assert default_args.install_browsers_on_demand is False

    enabled_args = parser.parse_args([
        "autonomous-tournament",
        "brief.json",
        "--install-browsers-on-demand",
    ])
    assert enabled_args.install_browsers_on_demand is True
