"""Tests for how mcp-adapter.py interprets what a wrapper script returns.

The wrapper contract is to print JSON on every run. A wrapper that exits 0 and
prints nothing, or prints something that is not the wrapper JSON, has not
produced a result and must not be reported as PASS.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from conftest import _load


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
