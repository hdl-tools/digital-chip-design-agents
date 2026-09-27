"""Tests for the EDA wrapper scripts in plugins/infrastructure/tools/.

A wrapper must not report PASS unless it found a result in the tool's output.
Each test puts a fake tool on PATH that prints a chosen log and exits with a
chosen code, then runs the real wrapper through bash.

The wrappers are bash scripts. On Windows ``bash`` may resolve to WSL or Git
Bash with different path handling, so the module is skipped there unless
``RUN_WRAPPER_TESTS=1`` is set.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO_ROOT

TOOLS_DIR = REPO_ROOT / "plugins" / "infrastructure" / "tools"
BASH = shutil.which("bash")

pytestmark = [
    pytest.mark.skipif(BASH is None or shutil.which("python3") is None,
                       reason="bash and python3 are required"),
    pytest.mark.skipif(sys.platform == "win32" and not os.environ.get("RUN_WRAPPER_TESTS"),
                       reason="set RUN_WRAPPER_TESTS=1 to run the bash wrappers on Windows"),
]

UNVERIFIED = "no recognisable result in tool output"
WARNING_LINE = "[WARN] WARNING: check this\n"
NOISE = "Reading design...\nDone.\n"

# wrapper name -> executable the wrapper looks for, a log that contains a
# result the wrapper parses, and the arguments to call the wrapper with.
WRAPPERS = {
    "yosys": ("yosys", "Number of cells:      42\n", ["-p", "stat"]),
    "openroad": ("openroad", "wns 0.10\ntns 0.00\n", ["flow.tcl"]),
    "opensta": ("sta", "wns 0.10\ntns 0.00\n", ["sta.tcl"]),
    "klayout": ("klayout", "0 DRC violations\n", ["-b", "-r", "drc.lydrc"]),
    "symbiflow": ("sby", "PROVED prop_a\n", ["proof.sby"]),
    "gem5": ("gem5", "simInsts 1000\nhostSeconds 1.5\n", ["config.py"]),
    "bambu": ("bambu-hls", "Total latency: 12 cycles\n", ["top.c"]),
    "verilator-sim": (None, "TEST PASSED\n", []),
}


def run_wrapper(tmp_path: Path, name: str, log: str, rc: int = 0):
    tool, _, args = WRAPPERS[name]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log_file = tmp_path / "fake.log"
    log_file.write_bytes(log.encode("utf-8"))

    fake = bin_dir / (tool or "sim_binary")
    fake.write_bytes(
        b'#!/usr/bin/env bash\ncat "$FAKE_TOOL_LOG" 2>/dev/null\nexit "${FAKE_TOOL_RC:-0}"\n'
    )
    fake.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["FAKE_TOOL_LOG"] = log_file.as_posix()
    env["FAKE_TOOL_RC"] = str(rc)

    wrapper = (TOOLS_DIR / f"wrap-{name}.sh").as_posix()
    # verilator-sim takes the simulation binary as its first argument.
    call_args = [fake.as_posix()] if tool is None else args
    proc = subprocess.run(
        [BASH, wrapper, *call_args],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert proc.stdout.strip(), f"wrapper printed nothing; stderr: {proc.stderr}"
    return proc.returncode, json.loads(proc.stdout)


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_empty_output_with_exit_0_is_not_a_pass(tmp_path, name):
    rc, out = run_wrapper(tmp_path, name, "")
    assert rc == 0
    assert out["status"] == "WARN"
    assert out["verified"] is False
    assert UNVERIFIED in out["warnings"][0]


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_unrecognised_output_with_exit_0_is_not_a_pass(tmp_path, name):
    _, out = run_wrapper(tmp_path, name, NOISE)
    assert out["status"] == "WARN"
    assert out["verified"] is False


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_recognised_clean_output_passes(tmp_path, name):
    rc, out = run_wrapper(tmp_path, name, WRAPPERS[name][1])
    assert rc == 0
    assert out["status"] == "PASS"
    assert out["verified"] is True
    assert out["warnings"] == []


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_recognised_output_with_warning_is_a_verified_warn(tmp_path, name):
    _, out = run_wrapper(tmp_path, name, WRAPPERS[name][1] + WARNING_LINE)
    assert out["status"] == "WARN"
    assert out["verified"] is True
    assert not any(UNVERIFIED in w for w in out["warnings"])


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_nonzero_exit_fails_and_is_propagated(tmp_path, name):
    rc, out = run_wrapper(tmp_path, name, WRAPPERS[name][1], rc=3)
    assert rc == 3
    assert out["exit_code"] == 3
    assert out["status"] == "FAIL"


@pytest.mark.parametrize("name", sorted(set(WRAPPERS) - {"verilator-sim"}))
def test_error_line_with_exit_0_fails(tmp_path, name):
    _, out = run_wrapper(tmp_path, name, WRAPPERS[name][1] + "ERROR: bad thing\n")
    assert out["status"] == "FAIL"


def test_verilator_error_line_with_pass_marker_is_a_warn(tmp_path):
    """Simulation logs print lines such as 'Error count: 0'; an ERROR line alone
    must not fail a run that printed TEST PASSED, but it must not pass silently."""
    _, out = run_wrapper(tmp_path, "verilator-sim", "TEST PASSED\nERROR count: 0\n")
    assert out["status"] == "WARN"
    assert out["verified"] is True


def test_verilator_fail_marker_fails(tmp_path):
    _, out = run_wrapper(tmp_path, "verilator-sim", "TEST FAILED\n")
    assert out["status"] == "FAIL"


def test_klayout_reports_null_drc_total_when_nothing_was_found(tmp_path):
    _, out = run_wrapper(tmp_path, "klayout", NOISE)
    assert out["summary"]["drc_total"] is None


def test_klayout_counts_violations_from_the_log(tmp_path):
    _, out = run_wrapper(tmp_path, "klayout", "3 DRC violations\n")
    assert out["summary"]["drc_total"] == 3
    assert out["status"] == "WARN"
    assert out["verified"] is True


@pytest.mark.parametrize("name", sorted(set(WRAPPERS) - {"verilator-sim"}))
def test_missing_tool_fails(tmp_path, name):
    tool = WRAPPERS[name][0]
    if shutil.which(tool):
        pytest.skip(f"{tool} is installed")
    proc = subprocess.run(
        [BASH, (TOOLS_DIR / f"wrap-{name}.sh").as_posix()],
        cwd=tmp_path, capture_output=True, text=True, timeout=60,
        stdin=subprocess.DEVNULL,
    )
    out = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert out["status"] == "FAIL"
    assert out["verified"] is False
