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


# The fake tool records the arguments it was called with (one per line), prints
# the chosen log, and exits with the chosen code.
FAKE_TOOL = (
    b'#!/usr/bin/env bash\n'
    b'printf "%s\\n" "$@" > "$FAKE_TOOL_ARGV"\n'
    b'cat "$FAKE_TOOL_LOG" 2>/dev/null\n'
    b'exit "${FAKE_TOOL_RC:-0}"\n'
)


def fake_tool_env(tmp_path: Path, tool: str, log: str, rc: int = 0):
    """Put a fake ``tool`` on PATH; return its path and the environment to run in."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log_file = tmp_path / "fake.log"
    log_file.write_bytes(log.encode("utf-8"))

    fake = bin_dir / tool
    fake.write_bytes(FAKE_TOOL)
    fake.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["FAKE_TOOL_LOG"] = log_file.as_posix()
    env["FAKE_TOOL_RC"] = str(rc)
    env["FAKE_TOOL_ARGV"] = (tmp_path / "fake.argv").as_posix()
    return fake, env


def run_script(tmp_path: Path, script: str, call_args, env=None):
    proc = subprocess.run(
        [BASH, (TOOLS_DIR / script).as_posix(), *call_args],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert proc.stdout.strip(), f"wrapper printed nothing; stderr: {proc.stderr}"
    return proc.returncode, json.loads(proc.stdout)


def run_wrapper(tmp_path: Path, name: str, log: str, rc: int = 0):
    tool, _, args = WRAPPERS[name]
    fake, env = fake_tool_env(tmp_path, tool or "sim_binary", log, rc)
    # verilator-sim takes the simulation binary as its first argument.
    call_args = [fake.as_posix()] if tool is None else args
    return run_script(tmp_path, f"wrap-{name}.sh", call_args, env)


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


@pytest.mark.parametrize("flag", ["--version", "--help", "-h"])
def test_verilator_sim_answers_version_and_help_itself(tmp_path, flag):
    """Issue #95: the first argument is the simulation binary, so the deploy-time
    smoke test's --version was reported as a missing binary - the same FAIL a
    broken wrapper gives. It now gets the WARN the other wrappers return."""
    rc, out = run_script(tmp_path, "wrap-verilator-sim.sh", [flag])
    assert rc == 0
    assert out["status"] == "WARN"
    assert out["verified"] is False
    assert "usage: wrap-verilator-sim.sh" in out["warnings"][0]


def test_verilator_sim_still_fails_on_a_missing_binary(tmp_path):
    rc, out = run_script(tmp_path, "wrap-verilator-sim.sh", ["./no_such_sim"])
    assert rc == 1
    assert out["status"] == "FAIL"
    assert out["verified"] is False


# --- wrap-verilator-lint.sh (issue #112) ------------------------------------
# A clean `verilator --lint-only` run exits 0 and prints nothing, so this wrapper
# cannot share the tests above that treat empty output as "no result".

LINT_ERROR_LOG = (
    "%Warning-WIDTH: top.sv:3:12: Operator ASSIGNW expects 8 bits on the Assign RHS\n"
    "                            : ... note: In instance 'top'\n"
    "%Error: top.sv:5:1: syntax error, unexpected endmodule\n"
    "%Error: Exiting due to 1 error(s)\n"
)


def run_lint(tmp_path: Path, log: str, rc: int = 0, args=("-Wall", "top.sv"), design=True):
    if design:
        (tmp_path / "top.sv").write_text("module top; endmodule\n", encoding="utf-8")
    _, env = fake_tool_env(tmp_path, "verilator", log, rc)
    rc_out, out = run_script(tmp_path, "wrap-verilator-lint.sh", list(args), env)
    argv = (tmp_path / "fake.argv").read_text(encoding="utf-8").split()
    return rc_out, out, argv


def test_lint_clean_run_passes_on_empty_output(tmp_path):
    rc, out, argv = run_lint(tmp_path, "")
    assert rc == 0
    assert out["tool"] == "verilator-lint"
    assert out["status"] == "PASS"
    assert out["verified"] is True
    assert out["summary"]["error_count"] == 0
    assert out["summary"]["input_files"] == 1
    assert argv == ["--lint-only", "-Wall", "top.sv"]


def test_lint_only_flag_is_not_duplicated(tmp_path):
    _, _, argv = run_lint(tmp_path, "", args=("--lint-only", "-Wall", "top.sv"))
    assert argv.count("--lint-only") == 1


def test_lint_warning_is_a_verified_warn_counted_by_code(tmp_path):
    log = ("%Warning-WIDTH: top.sv:3:12: Operator ASSIGNW expects 8 bits\n"
           "%Warning-WIDTH: top.sv:4:12: Operator ASSIGNW expects 4 bits\n"
           "%Warning-UNUSEDSIGNAL: top.sv:2:9: Signal is not used: 'x'\n")
    rc, out, _ = run_lint(tmp_path, log, args=("-Wall", "-Wno-fatal", "top.sv"))
    assert rc == 0
    assert out["status"] == "WARN"
    assert out["verified"] is True
    assert out["summary"]["warning_count"] == 3
    assert out["summary"]["warnings_by_code"] == {"WIDTH": 2, "UNUSEDSIGNAL": 1}
    assert not any(UNVERIFIED in w for w in out["warnings"])


def test_lint_error_fails_and_the_closing_line_is_not_counted(tmp_path):
    rc, out, _ = run_lint(tmp_path, LINT_ERROR_LOG, rc=1)
    assert rc == 1
    assert out["exit_code"] == 1
    assert out["status"] == "FAIL"
    assert out["verified"] is True
    assert out["summary"]["error_count"] == 1
    assert out["summary"]["warning_count"] == 1
    assert out["summary"]["exited_on"] == "errors"
    assert out["errors"] == ["%Error: top.sv:5:1: syntax error, unexpected endmodule"]


def test_lint_exit_on_warnings_fails_with_zero_errors(tmp_path):
    """Verilator exits non-zero on warnings unless -Wno-fatal is given. The exit
    code is passed through, but the counts must not call a warning an error."""
    log = ("%Warning-WIDTH: top.sv:3:12: Operator ASSIGNW expects 8 bits\n"
           "%Error: Exiting due to 1 warning(s)\n")
    rc, out, _ = run_lint(tmp_path, log, rc=1)
    assert rc == 1
    assert out["status"] == "FAIL"
    assert out["summary"]["error_count"] == 0
    assert out["summary"]["exited_on"] == "warnings"
    assert out["errors"] == ["%Error: Exiting due to 1 warning(s)"]


def test_lint_version_run_is_not_a_pass(tmp_path):
    """The deploy-time smoke test: the tool ran, but nothing was linted."""
    rc, out, _ = run_lint(tmp_path, "Verilator 5.028 2024-08-21 rev v5.028\n",
                          args=("--version",), design=False)
    assert rc == 0
    assert out["status"] == "WARN"
    assert out["verified"] is False
    assert UNVERIFIED in out["warnings"][0]


def test_lint_without_an_existing_design_file_is_not_a_pass(tmp_path):
    """Exit 0 with empty output is the clean result only if a design was read."""
    rc, out, _ = run_lint(tmp_path, "", args=("-Wall", "missing.sv"), design=False)
    assert rc == 0
    assert out["status"] == "WARN"
    assert out["verified"] is False
    assert out["summary"]["input_files"] == 0


def test_lint_missing_tool_fails(tmp_path):
    if shutil.which("verilator"):
        pytest.skip("verilator is installed")
    rc, out = run_script(tmp_path, "wrap-verilator-lint.sh", ["top.sv"])
    assert rc == 1
    assert out["status"] == "FAIL"
    assert out["verified"] is False
    assert out["errors"] == ["tool not found: verilator"]


def test_every_wrapper_script_is_exercised_here():
    """A wrapper added to the tools directory without tests would ship unchecked."""
    on_disk = {p.name for p in TOOLS_DIR.glob("wrap-*.sh")}
    tested = {f"wrap-{name}.sh" for name in WRAPPERS} | {"wrap-verilator-lint.sh"}
    assert on_disk == tested


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
