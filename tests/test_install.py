"""Tests for the `chatagents install` / `uninstall` commands (JSON-fallback path)."""
import json
import shutil

import pytest
from typer.testing import CliRunner

from chatagents import cli

runner = CliRunner()


@pytest.fixture
def fake_no_claude(monkeypatch):
    """Force the JSON-fallback path by hiding any real `claude` binary."""
    real_which = shutil.which
    monkeypatch.setattr(
        cli.shutil,
        "which",
        lambda name: None if name == "claude" else real_which(name),
    )


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_install_user_writes_claude_json(fake_no_claude, isolated_home):
    r = runner.invoke(cli.app, ["install", "--scope", "user"])
    assert r.exit_code == 0, r.output
    cfg = json.loads((isolated_home / ".claude.json").read_text())
    assert "chatagents" in cfg["mcpServers"]
    entry = cfg["mcpServers"]["chatagents"]
    assert entry["command"] in ("uv", "chatagents") or entry["command"].endswith("python")
    assert "serve" in entry["args"]


def test_install_refuses_overwrite_without_force(fake_no_claude, isolated_home):
    r1 = runner.invoke(cli.app, ["install", "--scope", "user"])
    assert r1.exit_code == 0
    r2 = runner.invoke(cli.app, ["install", "--scope", "user"])
    assert r2.exit_code == 1
    assert "already registered" in r2.output


def test_install_force_overwrites(fake_no_claude, isolated_home):
    runner.invoke(cli.app, ["install", "--scope", "user"])
    # Mutate the entry, then re-install with --force
    cfg_path = isolated_home / ".claude.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["mcpServers"]["chatagents"] = {"command": "stale", "args": []}
    cfg_path.write_text(json.dumps(cfg))
    r = runner.invoke(cli.app, ["install", "--scope", "user", "--force"])
    assert r.exit_code == 0
    cfg = json.loads(cfg_path.read_text())
    assert cfg["mcpServers"]["chatagents"]["command"] != "stale"


def test_uninstall_removes_entry(fake_no_claude, isolated_home):
    runner.invoke(cli.app, ["install", "--scope", "user"])
    r = runner.invoke(cli.app, ["uninstall", "--scope", "user"])
    assert r.exit_code == 0
    cfg = json.loads((isolated_home / ".claude.json").read_text())
    assert "chatagents" not in cfg.get("mcpServers", {})


def test_install_preserves_other_mcp_servers(fake_no_claude, isolated_home):
    cfg_path = isolated_home / ".claude.json"
    cfg_path.write_text(json.dumps({
        "mcpServers": {"other-server": {"command": "x", "args": []}},
        "someOtherKey": 42,
    }))
    r = runner.invoke(cli.app, ["install", "--scope", "user"])
    assert r.exit_code == 0
    cfg = json.loads(cfg_path.read_text())
    assert cfg["someOtherKey"] == 42
    assert "other-server" in cfg["mcpServers"]
    assert "chatagents" in cfg["mcpServers"]


def test_install_project_scope(fake_no_claude, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(cli.app, ["install", "--scope", "project"])
    assert r.exit_code == 0, r.output
    cfg_path = tmp_path / ".claude" / "settings.json"
    assert cfg_path.exists()
    cfg = json.loads(cfg_path.read_text())
    assert "chatagents" in cfg["mcpServers"]
