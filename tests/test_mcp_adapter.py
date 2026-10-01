"""Tests for how mcp-adapter.py interprets what a wrapper script returns.

The wrapper contract is to print JSON on every run. A wrapper that exits 0 and
prints nothing, or prints something that is not the wrapper JSON, has not
produced a result and must not be reported as PASS.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import REPO_ROOT, _load


@pytest.fixture(scope="module")
def adapter():
    return _load("mcp_adapter", "plugins/infrastructure/tools/mcp-adapter.py")


def run(adapter, monkeypatch, stdout="", stderr="", returncode=0):
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    return adapter._run_wrapper("/path/to/wrap-yosys.sh", "yosys", {}, 5)


def test_empty_stdout_with_exit_0_is_fail(adapter, monkeypatch):
    out = run(adapter, monkeypatch, stdout="", stderr="something on stderr")
    assert out["status"] == "FAIL"
    assert out["verified"] is False
    assert out["exit_code"] == 0
    assert any("no output" in e for e in out["errors"])
    assert out["stderr_excerpt"] == "something on stderr"


def test_non_json_stdout_with_exit_0_is_fail(adapter, monkeypatch):
    out = run(adapter, monkeypatch, stdout="yosys 0.40 (git sha1 ...)")
    assert out["status"] == "FAIL"
    assert out["verified"] is False
    assert out["raw_output_excerpt"].startswith("yosys 0.40")


@pytest.mark.parametrize(
    "payload",
    [{"tool": "yosys", "exit_code": 0}, {"status": "OK"}, ["PASS"], "PASS", 0],
    ids=["no-status", "unknown-status", "list", "string", "number"],
)
def test_json_without_a_valid_status_is_fail(adapter, monkeypatch, payload):
    out = run(adapter, monkeypatch, stdout=json.dumps(payload))
    assert out["status"] == "FAIL"
    assert out["verified"] is False


@pytest.mark.parametrize("status", ["PASS", "WARN", "FAIL"])
def test_valid_wrapper_json_is_passed_through_unchanged(adapter, monkeypatch, status):
    payload = {
        "tool": "yosys", "exit_code": 0, "status": status, "verified": True,
        "summary": {"cells": 42}, "errors": [], "warnings": [], "raw_log": "/tmp/x.log",
    }
    assert run(adapter, monkeypatch, stdout=json.dumps(payload)) == payload


def test_wrapper_json_without_verified_field_is_passed_through(adapter, monkeypatch):
    """A custom wrapper written before the field existed keeps working."""
    payload = {"tool": "custom", "exit_code": 0, "status": "PASS", "summary": {},
               "errors": [], "warnings": [], "raw_log": ""}
    assert run(adapter, monkeypatch, stdout=json.dumps(payload)) == payload


def test_nonzero_exit_with_empty_stdout_is_fail(adapter, monkeypatch):
    out = run(adapter, monkeypatch, stdout="", stderr="boom", returncode=2)
    assert out["status"] == "FAIL"
    assert out["exit_code"] == 2


def test_timeout_is_fail(adapter, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    out = adapter._run_wrapper("/path/to/wrap-yosys.sh", "yosys", {}, 5)
    assert out["status"] == "FAIL"
    assert out["verified"] is False


def test_non_executable_wrapper_is_fail(adapter, monkeypatch):
    """A wrapper added after `chmod +x` was last run must not take the server down."""
    def fake_run(cmd, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    out = adapter._run_wrapper("/path/to/wrap-yosys.sh", "yosys", {}, 5)
    assert out["status"] == "FAIL"
    assert out["verified"] is False
    assert "chmod +x" in out["errors"][0]


# --- Verilator lint mode (issue #112) ----------------------------------------
# The server is configured with the sim wrapper, whose first argument is a
# compiled simulation binary. Lint mode used to hand it `--lint-only`, so
# Verilator was never run.

SIM_WRAPPER = "/opt/tools/wrap-verilator-sim.sh"


def test_verilator_lint_mode_runs_the_lint_wrapper(adapter, monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    adapter._run_wrapper(SIM_WRAPPER, "verilator", {"mode": "lint", "args": ["-Wall", "top.sv"]}, 5)
    wrapper, *args = seen["cmd"]
    assert Path(wrapper) == Path("/opt/tools/wrap-verilator-lint.sh")
    assert args == ["-Wall", "top.sv"]


@pytest.mark.parametrize("inputs", [
    {"mode": "sim", "sim_binary": "./obj_dir/Vtop", "args": ["+seed=1"]},
    {"sim_binary": "./obj_dir/Vtop", "args": ["+seed=1"]},
], ids=["explicit-sim", "default-mode"])
def test_verilator_sim_mode_keeps_the_configured_wrapper(adapter, inputs):
    assert adapter._select_wrapper(SIM_WRAPPER, "verilator", inputs) == SIM_WRAPPER
    assert adapter._build_cli_args("verilator", inputs) == ["./obj_dir/Vtop", "+seed=1"]


def test_only_verilator_switches_wrapper_on_mode(adapter):
    assert adapter._select_wrapper("/t/wrap-yosys.sh", "yosys", {"mode": "lint"}) == "/t/wrap-yosys.sh"


needs_posix_bash = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None or shutil.which("python3") is None,
    reason="the adapter executes the wrapper directly: needs a POSIX host with bash and python3",
)


def lint_end_to_end(adapter, tmp_path, monkeypatch, log, rc):
    """Drive mode "lint" through the real wrappers with a fake verilator on PATH."""
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("wrap-verilator-sim.sh", "wrap-verilator-lint.sh"):
        shutil.copy(REPO_ROOT / "plugins" / "infrastructure" / "tools" / name, tools / name)
        (tools / name).chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "verilator"
    fake.write_text(f'#!/usr/bin/env bash\ncat "{tmp_path}/fake.log"\nexit {rc}\n', encoding="utf-8")
    fake.chmod(0o755)
    (tmp_path / "fake.log").write_text(log, encoding="utf-8")
    (tmp_path / "top.sv").write_text("module top; endmodule\n", encoding="utf-8")

    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.chdir(tmp_path)
    return adapter._run_wrapper(
        str(tools / "wrap-verilator-sim.sh"), "verilator",
        {"mode": "lint", "args": ["-Wall", "top.sv"]}, 30,
    )


@needs_posix_bash
def test_lint_mode_end_to_end_clean_run_passes(adapter, tmp_path, monkeypatch):
    out = lint_end_to_end(adapter, tmp_path, monkeypatch, "", 0)
    assert out["tool"] == "verilator-lint"
    assert out["status"] == "PASS"
    assert out["verified"] is True
    assert out["summary"]["error_count"] == 0


@needs_posix_bash
def test_lint_mode_end_to_end_reports_errors_and_warnings(adapter, tmp_path, monkeypatch):
    log = ("%Warning-WIDTH: top.sv:3:12: Operator ASSIGNW expects 8 bits\n"
           "%Error: top.sv:5:1: syntax error, unexpected endmodule\n"
           "%Error: Exiting due to 1 error(s)\n")
    out = lint_end_to_end(adapter, tmp_path, monkeypatch, log, 1)
    assert out["status"] == "FAIL"
    assert out["exit_code"] == 1
    assert out["summary"]["error_count"] == 1
    assert out["summary"]["warnings_by_code"] == {"WIDTH": 1}
