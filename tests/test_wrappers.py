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
    "vcs-compile": ("vcs", "CPU time: 12.3 seconds to compile\n", ["-full64", "top.sv"]),
    "xrun-compile": ("xrun", "xrun: compile complete\n", ["top.sv"]),
    "imc": ("imc", "Overall average grade: 78.50%\n", ["-execcmd", "report -summary"]),
    # Commercial and open PD/signoff wrappers. Their result markers are the documented
    # report formats, not yet parsed from a real log on the reference host.
    "dc": ("dc_shell", "Total cell area:            1234.500000\n", ["-f", "synth.tcl"]),
    "genus": ("genus", "Timing slack :     125ps\n", ["-batch", "-files", "synth.tcl"]),
    "innovus": ("innovus", "|     WNS (ns):| 0.042 |\n", ["-batch", "-files", "route.tcl"]),
    "icc2": ("icc2_shell", "  slack (MET)                                0.0420\n", ["-f", "route.tcl"]),
    "pt": ("pt_shell", "  slack (MET)                                0.0420\n", ["-f", "sta.tcl"]),
    "fm": ("fm_shell", "Verification SUCCEEDED\n", ["-f", "lec.tcl"]),
    "lec": ("lec", "Compared points      PO     DFF    Total\n"
                   "Equivalent           10     20     30\n", ["-nogui", "-dofile", "lec.do"]),
    "redhawk": ("redhawk", "WRAP_RESULT worst_ir_drop_pct=2.5\n", ["-f", "run.tcl"]),
    "magic": ("magic", "Total DRC errors found: 0\n", ["-dnull", "-noconsole", "drc.tcl"]),
    "netgen": ("netgen", "Circuits match uniquely.\n",
               ["-batch", "lvs", "a top", "b top", "setup.tcl", "comp.out"]),
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


@pytest.mark.parametrize("name", sorted(set(WRAPPERS) - {"verilator-sim", "vcs-compile", "xrun-compile", "imc"}))
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
    tested = {f"wrap-{name}.sh" for name in WRAPPERS} | {
        "wrap-verilator-lint.sh", "wrap-urg.sh", "wrap-cocotb-results.sh",
        "wrap-starrc.sh"}
    assert on_disk == tested


def test_klayout_reports_null_drc_total_when_nothing_was_found(tmp_path):
    _, out = run_wrapper(tmp_path, "klayout", NOISE)
    assert out["summary"]["drc_total"] is None


def test_klayout_counts_violations_from_the_log(tmp_path):
    _, out = run_wrapper(tmp_path, "klayout", "3 DRC violations\n")
    assert out["summary"]["drc_total"] == 3
    assert out["status"] == "WARN"
    assert out["verified"] is True


# imc is also searched for outside PATH; its missing-tool case is tested below
# with a controlled environment.
@pytest.mark.parametrize("name", sorted(set(WRAPPERS) - {"verilator-sim", "imc"}))
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


# --- wrap-imc.sh -------------------------------------------------------------
# imc is often installed off PATH (under $XCELIUM_HOME/tools/bin) or not at all.

def _minimal_env(tmp_path: Path, **extra):
    """An environment whose PATH holds only the system dirs bash/python3 need."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("XCELIUM_HOME", "IMC_HOME", "VMANAGER_HOME", "VCS_HOME")}
    py_dir = os.path.dirname(shutil.which("python3"))
    env["PATH"] = os.pathsep.join([str(tmp_path / "empty"), py_dir, "/usr/bin", "/bin"])
    (tmp_path / "empty").mkdir(exist_ok=True)
    env.update(extra)
    return env


def test_imc_missing_reports_tool_not_found_with_search_list(tmp_path):
    if any(shutil.which(t, path="/usr/bin:/bin") for t in ("imc", "xrun")):
        pytest.skip("imc or xrun in a system dir")
    xh = tmp_path / "xcelium"
    (xh / "tools" / "bin").mkdir(parents=True)
    # A launcher script that is not imc must not be mistaken for it.
    launcher = xh / "tools" / "bin" / "launch_rmi_imc.sh"
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    rc, out = run_script(tmp_path, "wrap-imc.sh", ["-execcmd", "report -summary"],
                         _minimal_env(tmp_path, XCELIUM_HOME=xh.as_posix()))
    assert rc == 1
    assert out["status"] == "FAIL"
    assert out["verified"] is False
    assert "tool not found: imc" in out["errors"][0]
    assert "can be collected but not merged or reported" in out["errors"][0]
    assert (xh / "tools" / "bin").as_posix() in out["summary"]["searched"]


def test_imc_is_found_under_xcelium_home_when_not_on_path(tmp_path):
    xh = tmp_path / "xcelium"
    bin_dir = xh / "tools" / "bin"
    bin_dir.mkdir(parents=True)
    fake = bin_dir / "imc"
    fake.write_bytes(FAKE_TOOL)
    fake.chmod(0o755)
    log = tmp_path / "fake.log"
    log.write_text("Overall average grade: 78.50%\nBlock average grade: 90%\n", encoding="utf-8")
    env = _minimal_env(tmp_path, XCELIUM_HOME=xh.as_posix(), FAKE_TOOL_LOG=log.as_posix(),
                       FAKE_TOOL_ARGV=(tmp_path / "fake.argv").as_posix())
    rc, out = run_script(tmp_path, "wrap-imc.sh", ["-execcmd", "report -summary"], env)
    assert rc == 0
    assert out["status"] == "PASS"
    assert out["summary"]["tool_path"] == fake.as_posix()
    assert out["summary"]["metrics"] == {"overall": 78.5, "block": 90.0}
    argv = (tmp_path / "fake.argv").read_text(encoding="utf-8").splitlines()
    assert argv == ["-batch", "-execcmd", "report -summary"]


def test_imc_parses_a_summary_table(tmp_path):
    table = ("Name   Overall   Block    Expression  Toggle   FSM\n"
             "-----------------------------------------------------\n"
             "top    81.20%    95.00%   70.10%      60.00%   88.88%\n")
    _, out = run_wrapper(tmp_path, "imc", table)
    assert out["status"] == "PASS"
    assert out["summary"]["column_mapping"] == "table"
    assert out["summary"]["metrics"] == {
        "overall": 81.2, "block": 95.0, "expression": 70.1, "toggle": 60.0, "fsm": 88.88}


def test_imc_cadence_error_code_fails(tmp_path):
    _, out = run_wrapper(tmp_path, "imc", "*E,NOFILE: cannot open merged\n")
    assert out["status"] == "FAIL"
    assert out["summary"]["first_error_code"] == "NOFILE"


# --- wrap-urg.sh -------------------------------------------------------------
# urg's summary is read from <report>/dashboard.txt, not stdout. This layout was
# measured on VCS Y-2026.03 (`urg -dir cov.vdb -report rpt -format text`).

DASHBOARD = (
    "Dashboard\n\nDate: Fri Oct 23 21:05:36 2026\n\nUser: u\n\nVersion: Y-2026.03\n"
    "Command line: urg -dir cov.vdb -dbname merged -report rpt -format text \n\n"
    "Number of tests: 3\n\n"
    "-------------------------------------------------------------------------------\n"
    "Total Coverage Summary \n"
    "SCORE  LINE   COND   TOGGLE FSM    BRANCH ASSERT \n"
    " 65.24  85.71 --      50.00 --      60.00 100.00 \n\n"
)

FAKE_URG = (
    b'#!/usr/bin/env bash\n'
    b'printf "%s\\n" "$@" > "$FAKE_TOOL_ARGV"\n'
    b'cat "$FAKE_TOOL_LOG" 2>/dev/null\n'
    b'if [[ -n "${FAKE_DASHBOARD:-}" ]]; then mkdir -p "$FAKE_REPORT";'
    b' cp "$FAKE_DASHBOARD" "$FAKE_REPORT/dashboard.txt"; fi\n'
    b'exit "${FAKE_TOOL_RC:-0}"\n'
)


def run_urg(tmp_path: Path, dashboard, stdout="Note-[URG-RDG] Report directory generated\n",
            rc=0, args=("-dir", "cov.vdb", "-report", "rpt", "-format", "text")):
    fake, env = fake_tool_env(tmp_path, "urg", stdout, rc)
    fake.write_bytes(FAKE_URG)
    report = "urgReport"
    if "-report" in args:
        report = args[list(args).index("-report") + 1]
    env["FAKE_REPORT"] = (tmp_path / report).as_posix()
    if dashboard is not None:
        dash = tmp_path / "dash.src"
        dash.write_text(dashboard, encoding="utf-8")
        env["FAKE_DASHBOARD"] = dash.as_posix()
    return run_script(tmp_path, "wrap-urg.sh", list(args), env)


def test_urg_parses_the_dashboard(tmp_path):
    rc, out = run_urg(tmp_path, DASHBOARD)
    assert rc == 0
    assert out["status"] == "PASS"
    assert out["verified"] is True
    assert out["summary"]["tests"] == 3
    assert out["summary"]["metrics"] == {
        "score": 65.24, "line": 85.71, "cond": None, "toggle": 50.0,
        "fsm": None, "branch": 60.0, "assert": 100.0}


def test_urg_default_report_dir_is_urgreport(tmp_path):
    _, out = run_urg(tmp_path, DASHBOARD, args=("-dir", "cov.vdb", "-format", "text"))
    assert out["status"] == "PASS"
    assert out["summary"]["report_dir"].endswith("urgReport")


def test_urg_without_text_dashboard_is_not_a_pass(tmp_path):
    rc, out = run_urg(tmp_path, None)
    assert rc == 0
    assert out["status"] == "WARN"
    assert out["verified"] is False
    assert UNVERIFIED in out["warnings"][0]


def test_urg_all_dash_summary_is_not_a_pass(tmp_path):
    """urg exits 0 with every metric '--' when the scope excluded the whole design."""
    dash = DASHBOARD.replace(" 65.24  85.71 --      50.00 --      60.00 100.00 ",
                             " --     --     --     --     --     --     --     ")
    rc, out = run_urg(tmp_path, dash)
    assert rc == 0
    assert out["status"] == "WARN"
    assert out["verified"] is False
    assert "nothing was instrumented" in out["warnings"][0]


def test_urg_stale_dashboard_is_not_a_result(tmp_path):
    report = tmp_path / "rpt"
    report.mkdir()
    old = report / "dashboard.txt"
    old.write_text(DASHBOARD, encoding="utf-8")
    os.utime(old, (1_000_000_000, 1_000_000_000))
    _, out = run_urg(tmp_path, None)
    assert out["status"] == "WARN"
    assert out["verified"] is False
    assert "stale" in out["warnings"][0]


def test_urg_error_marker_fails_and_exit_code_propagates(tmp_path):
    rc, out = run_urg(tmp_path, None, stdout="Error-[URG-ND] No source data\n", rc=1)
    assert rc == 1
    assert out["status"] == "FAIL"
    assert out["summary"]["first_error_code"] == "URG-ND"


def test_urg_warning_is_a_verified_warn(tmp_path):
    _, out = run_urg(tmp_path, DASHBOARD,
                     stdout="Warning-[UCAPI-SNF] Shape Not Found\n")
    assert out["status"] == "WARN"
    assert out["verified"] is True


def test_urg_missing_tool_fails(tmp_path):
    if shutil.which("urg", path="/usr/bin:/bin"):
        pytest.skip("urg in a system dir")
    rc, out = run_script(tmp_path, "wrap-urg.sh", ["-dir", "x.vdb"], _minimal_env(tmp_path))
    assert rc == 1
    assert out["status"] == "FAIL"
    assert out["verified"] is False
    assert "tool not found: urg" in out["errors"][0]


# --- wrap-cocotb-results.sh --------------------------------------------------
# Runs no tool: the cocotb makefile has exited 0 with failing tests (cocotb 1.9.2,
# observed on VCS and Xcelium), so results.xml is the verdict.

def junit(*cases):
    body = "".join(
        f'<testcase name="{name}" classname="tests.mod">{child}</testcase>'
        for name, child in cases
    )
    return f'<testsuites name="results"><testsuite name="all">{body}</testsuite></testsuites>'


def run_results(tmp_path: Path, *args):
    return run_script(tmp_path, "wrap-cocotb-results.sh", [str(a) for a in args])


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_results_all_pass(tmp_path):
    f = write(tmp_path / "results.xml", junit(("a", ""), ("b", ""), ("c", "<skipped/>")))
    rc, out = run_results(tmp_path, f)
    assert rc == 0
    assert out["status"] == "PASS"
    assert out["verified"] is True
    s = out["summary"]
    assert (s["tests"], s["passed"], s["failures"], s["errors"], s["skipped"]) == (3, 2, 0, 0, 1)
    assert s["skipped_tests"] == ["tests.mod.c"]


def test_results_failure_fails_even_though_make_would_exit_0(tmp_path):
    f = write(tmp_path / "results.xml", junit(("a", ""), ("b", '<failure message="x"/>')))
    rc, out = run_results(tmp_path, f)
    assert rc == 1
    assert out["exit_code"] == 1
    assert out["status"] == "FAIL"
    assert out["summary"]["failures"] == 1
    assert "FAILED: tests.mod.b" in out["errors"]


def test_results_error_element_fails(tmp_path):
    f = write(tmp_path / "results.xml", junit(("a", "<error/>")))
    rc, out = run_results(tmp_path, f)
    assert rc == 1
    assert out["summary"]["errors"] == 1


def test_results_missing_file_fails(tmp_path):
    rc, out = run_results(tmp_path, tmp_path / "results.xml")
    assert rc == 1
    assert out["status"] == "FAIL"
    assert "results file not found" in out["errors"][0]


def test_results_empty_file_fails(tmp_path):
    f = write(tmp_path / "results.xml", "")
    rc, out = run_results(tmp_path, f)
    assert rc == 1
    assert "empty" in out["errors"][0]


def test_results_unparsable_file_fails(tmp_path):
    f = write(tmp_path / "results.xml", "<testsuites><testsuite>")
    rc, out = run_results(tmp_path, f)
    assert rc == 1
    assert "unparsable" in out["errors"][0]


def test_results_no_testcase_fails(tmp_path):
    f = write(tmp_path / "results.xml", junit())
    rc, out = run_results(tmp_path, f)
    assert rc == 1
    assert out["status"] == "FAIL"
    assert "no testcase" in out["errors"][-1]


def test_results_all_skipped_is_not_a_pass(tmp_path):
    f = write(tmp_path / "results.xml", junit(("a", "<skipped/>")))
    rc, out = run_results(tmp_path, f)
    assert rc == 0
    assert out["status"] == "WARN"
    assert out["verified"] is False
    assert UNVERIFIED in out["warnings"][0]


def test_results_directories_are_searched_and_summed(tmp_path):
    write(tmp_path / "sim_build_vcs" / "suite_a" / "results.xml", junit(("a", ""), ("b", "")))
    write(tmp_path / "sim_build_vcs" / "suite_b" / "results.xml", junit(("c", "")))
    rc, out = run_results(tmp_path, tmp_path / "sim_build_vcs")
    assert rc == 0
    assert out["summary"]["files"] == 2
    assert out["summary"]["tests"] == 3


def test_results_directory_without_results_fails(tmp_path):
    (tmp_path / "empty_dir").mkdir()
    rc, out = run_results(tmp_path, tmp_path / "empty_dir")
    assert rc == 1
    assert "no results.xml under directory" in out["errors"][0]


def test_results_stale_file_fails_with_newer_than(tmp_path):
    f = write(tmp_path / "results.xml", junit(("a", "")))
    os.utime(f, (1_000_000_000, 1_000_000_000))
    stamp = write(tmp_path / "run.stamp", "")
    rc, out = run_results(tmp_path, "--newer-than", stamp, f)
    assert rc == 1
    assert "stale" in out["errors"][0]


def test_results_no_argument_fails(tmp_path):
    rc, out = run_results(tmp_path)
    assert rc == 1
    assert out["status"] == "FAIL"


@pytest.mark.parametrize("flag", ["--version", "--help"])
def test_results_version_run_is_not_a_pass(tmp_path, flag):
    rc, out = run_results(tmp_path, flag)
    assert rc == 0
    assert out["status"] == "WARN"
    assert out["verified"] is False


# --- commercial / open PD signoff wrappers: tool-specific verdicts -------------

def test_dc_captures_synopsys_error_code_and_fails(tmp_path):
    log = "Total cell area: 10.0\nError: Can't find design 'top'. (UID-341)\n"
    _, out = run_wrapper(tmp_path, "dc", log)
    assert out["status"] == "FAIL"
    assert out["summary"]["first_error_code"] == "UID-341"


def test_dc_counts_synopsys_warnings_by_code(tmp_path):
    log = ("Total cell area: 10.0\n"
           "Warning: Design 'top' has '2' unresolved references. (LINK-5)\n"
           "Warning: Design 'top' has '2' unresolved references. (LINK-5)\n")
    _, out = run_wrapper(tmp_path, "dc", log)
    assert out["status"] == "WARN"
    assert out["verified"] is True
    assert out["summary"]["warnings_by_code"] == {"LINK-5": 2}


def test_summary_lines_mentioning_errors_are_not_errors(tmp_path):
    """Innovus ends every log with a message summary; it must not read as an error."""
    log = ("|     WNS (ns):| 0.042 |\n"
           "*** Message Summary: 0 warning(s), 0 error(s)\n")
    _, out = run_wrapper(tmp_path, "innovus", log)
    assert out["status"] == "PASS"


def test_innovus_cadence_error_fails(tmp_path):
    _, out = run_wrapper(tmp_path, "innovus",
                         "|     WNS (ns):| 0.042 |\n**ERROR: (IMPSYT-6000): No design loaded\n")
    assert out["status"] == "FAIL"
    assert out["summary"]["first_error_code"] == "IMPSYT-6000"


def test_innovus_drc_violations_are_a_verified_warn(tmp_path):
    _, out = run_wrapper(tmp_path, "innovus", "Total Violations : 7 Viols.\n")
    assert out["status"] == "WARN"
    assert out["verified"] is True
    assert out["summary"]["drc_total"] == 7


def test_pt_reports_worst_slack_and_power(tmp_path):
    log = ("  slack (VIOLATED)        -0.1200\n  slack (MET)        0.3000\n"
           "  Total Power            =   1.23e-03   (100.00%)\n")
    _, out = run_wrapper(tmp_path, "pt", log)
    assert out["status"] == "PASS"
    assert out["summary"]["worst_slack"] == -0.12
    assert out["summary"]["total_power"] == 1.23e-03


def test_icc2_routing_drcs_are_a_verified_warn(tmp_path):
    _, out = run_wrapper(tmp_path, "icc2", "Total number of DRCs = 12\n")
    assert out["status"] == "WARN"
    assert out["verified"] is True
    assert out["summary"]["drc_total"] == 12


def test_icc2_wrapper_runs_fusion_compiler_when_asked(tmp_path):
    _, env = fake_tool_env(tmp_path, "fc_shell", WRAPPERS["icc2"][1])
    env["WRAP_ICC2_TOOL"] = "fc_shell"
    _, out = run_script(tmp_path, "wrap-icc2.sh", ["-f", "x.tcl"], env)
    assert out["status"] == "PASS"


@pytest.mark.parametrize("verdict", ["FAILED", "INCONCLUSIVE"])
def test_formality_failed_or_inconclusive_verdict_fails_at_exit_0(tmp_path, verdict):
    rc, out = run_wrapper(tmp_path, "fm", f"Verification {verdict}\n")
    assert rc == 0
    assert out["status"] == "FAIL"
    assert out["summary"]["verdict"] == verdict


def test_conformal_non_equivalent_points_fail_at_exit_0(tmp_path):
    log = ("Compared points      PO     DFF    Total\n"
           "Equivalent           10     19     29\n"
           "Non-equivalent       0      1      1\n")
    rc, out = run_wrapper(tmp_path, "lec", log)
    assert rc == 0
    assert out["status"] == "FAIL"
    assert out["summary"]["non_equivalent"] == 1


def test_conformal_aborted_points_are_not_a_pass(tmp_path):
    log = ("Compared points      PO     DFF    Total\n"
           "Equivalent           10     19     29\n"
           "Abort                0      1      1\n")
    _, out = run_wrapper(tmp_path, "lec", log)
    assert out["status"] == "FAIL"
    assert out["summary"]["aborted"] == 1


def test_conformal_comment_prefixed_error_fails(tmp_path):
    _, out = run_wrapper(tmp_path, "lec", WRAPPERS["lec"][1] + "// Error: Unknown command\n")
    assert out["status"] == "FAIL"


def test_magic_drc_count_is_a_verified_warn(tmp_path):
    _, out = run_wrapper(tmp_path, "magic", "Total DRC errors found: 42\n")
    assert out["status"] == "WARN"
    assert out["verified"] is True
    assert out["summary"]["drc_total"] == 42


def test_netgen_mismatch_fails_at_exit_0(tmp_path):
    rc, out = run_wrapper(tmp_path, "netgen", "Netlists do not match.\n")
    assert rc == 0
    assert out["status"] == "FAIL"
    assert out["summary"]["verdict"] == "mismatch"


def test_netgen_reads_the_lvs_report_file_this_run_wrote(tmp_path):
    fake, env = fake_tool_env(tmp_path, "netgen", "")
    fake.write_bytes(FAKE_TOOL.replace(
        b'exit', b'printf "Final result: Circuits match uniquely.\\n" > comp.out\nexit', 1))
    _, out = run_script(tmp_path, "wrap-netgen.sh", WRAPPERS["netgen"][2], env)
    assert out["status"] == "PASS"
    assert out["summary"]["report_file"].endswith("comp.out")


def test_netgen_stale_report_file_is_not_a_result(tmp_path):
    old = tmp_path / "comp.out"
    old.write_text("Circuits match uniquely.\n", encoding="utf-8")
    os.utime(old, (1_000_000_000, 1_000_000_000))
    _, out = run_wrapper(tmp_path, "netgen", NOISE)
    assert out["status"] == "WARN"
    assert out["verified"] is False


def test_netgen_property_errors_make_a_match_a_warn(tmp_path):
    _, out = run_wrapper(tmp_path, "netgen",
                         "Circuits match uniquely.\nProperty errors were found.\n")
    assert out["status"] == "WARN"
    assert out["verified"] is True


def test_redhawk_without_a_result_line_is_unverified(tmp_path):
    _, out = run_wrapper(tmp_path, "redhawk", "Static IR analysis done\n")
    assert out["status"] == "WARN"
    assert out["verified"] is False


# --- wrap-starrc.sh ----------------------------------------------------------
# The result is the parasitics file the command file names, not the log, so this
# wrapper is not in WRAPPERS: a fake tool that only prints a log cannot pass it.

FAKE_STARRC = (
    b'#!/usr/bin/env bash\n'
    b'cat "$FAKE_TOOL_LOG" 2>/dev/null\n'
    b'if [[ -n "${FAKE_SPEF:-}" ]]; then cp "$FAKE_SPEF" "$FAKE_OUT"; fi\n'
    b'exit "${FAKE_TOOL_RC:-0}"\n'
)
SPEF = '*SPEF "IEEE 1481-1998"\n*DESIGN "top"\n*D_NET n1 0.1\n*END\n*D_NET n2 0.2\n*END\n'


def run_starrc(tmp_path: Path, spef, log="", rc=0):
    fake, env = fake_tool_env(tmp_path, "StarXtract", log, rc)
    fake.write_bytes(FAKE_STARRC)
    out_file = tmp_path / "top.spef"
    env["FAKE_OUT"] = out_file.as_posix()
    if spef is not None:
        src = tmp_path / "src.spef"
        src.write_text(spef, encoding="utf-8")
        env["FAKE_SPEF"] = src.as_posix()
    cmd_file = tmp_path / "star_cmd"
    cmd_file.write_text(
        f"BLOCK: top\nNETLIST_FORMAT: SPEF\nNETLIST_FILE: {out_file.as_posix()}\n",
        encoding="utf-8")
    return run_script(tmp_path, "wrap-starrc.sh", [cmd_file.as_posix()], env)


def test_starrc_fresh_spef_passes_and_counts_nets(tmp_path):
    rc, out = run_starrc(tmp_path, SPEF)
    assert rc == 0
    assert out["status"] == "PASS"
    assert out["verified"] is True
    assert out["summary"]["d_nets"] == 2


def test_starrc_exit_0_without_spef_is_not_a_pass(tmp_path):
    rc, out = run_starrc(tmp_path, None)
    assert rc == 0
    assert out["status"] == "WARN"
    assert out["verified"] is False
    assert UNVERIFIED in out["warnings"][0]
    assert "was not written" in out["summary"]["no_result_reason"]


def test_starrc_stale_spef_is_not_a_result(tmp_path):
    old = tmp_path / "top.spef"
    old.write_text(SPEF, encoding="utf-8")
    os.utime(old, (1_000_000_000, 1_000_000_000))
    _, out = run_starrc(tmp_path, None)
    assert out["status"] == "WARN"
    assert out["verified"] is False
    assert "stale" in out["summary"]["no_result_reason"]


def test_starrc_spef_with_no_nets_is_not_a_result(tmp_path):
    _, out = run_starrc(tmp_path, '*SPEF "IEEE 1481-1998"\n*DESIGN "top"\n')
    assert out["status"] == "WARN"
    assert out["verified"] is False


def test_starrc_error_line_fails(tmp_path):
    _, out = run_starrc(tmp_path, SPEF, log="ERROR: layer map entry missing\n")
    assert out["status"] == "FAIL"


def test_starrc_warning_is_a_verified_warn(tmp_path):
    _, out = run_starrc(tmp_path, SPEF, log=WARNING_LINE)
    assert out["status"] == "WARN"
    assert out["verified"] is True


def test_starrc_nonzero_exit_propagates(tmp_path):
    rc, out = run_starrc(tmp_path, SPEF, rc=2)
    assert rc == 2
    assert out["status"] == "FAIL"


def test_starrc_missing_tool_fails(tmp_path):
    if shutil.which("StarXtract", path="/usr/bin:/bin"):
        pytest.skip("StarXtract in a system dir")
    rc, out = run_script(tmp_path, "wrap-starrc.sh", ["star_cmd"], _minimal_env(tmp_path))
    assert rc == 1
    assert out["status"] == "FAIL"
    assert out["verified"] is False
    assert "tool not found: StarXtract" in out["errors"][0]


PD_WRAPPERS = ("dc", "genus", "innovus", "icc2", "pt", "fm", "lec", "redhawk", "magic", "netgen")


@pytest.mark.parametrize("name", PD_WRAPPERS + ("starrc",))
@pytest.mark.parametrize("flag", ["--version", "--help"])
def test_pd_wrappers_answer_the_smoke_test_without_starting_the_tool(tmp_path, name, flag):
    """A vendor shell checks out a licence and took ~2 minutes to answer -version
    (innovus, pt_shell) on the second host, so the smoke test must not start it."""
    tool = WRAPPERS[name][0] if name != "starrc" else "StarXtract"
    _, env = fake_tool_env(tmp_path, tool, "should not run\n")
    rc, out = run_script(tmp_path, f"wrap-{name}.sh", [flag], env)
    assert rc == 0
    assert out["status"] == "WARN"
    assert out["verified"] is False
    assert "not started" in out["warnings"][0]
    assert not (tmp_path / "fake.argv").exists()
