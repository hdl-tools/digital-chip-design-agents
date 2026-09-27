#!/usr/bin/env python3
"""
mcp-session-adapter.py — Persistent MCP stdio server for interactive EDA tool sessions.

Implements MCP protocol version 2024-11-05 over stdio (JSON-RPC 2.0, newline-delimited).
Keeps a long-lived Tcl subprocess (openroad or sta) open between tool calls, so the
agent can query timing, DRC, area, etc. on an already-loaded design without re-loading
on every call.

Usage:
    python3 mcp-session-adapter.py --tool openroad [--version 1.0.0]
    python3 mcp-session-adapter.py --tool opensta  [--version 1.0.0]

Environment (openroad):
    OPENROAD_EXE        openroad executable name or path (default: openroad)
    PDK_ROOT            path to PDK root (used in load_design defaults)
    PLATFORM            PDK platform name e.g. sky130hd

Environment (opensta):
    OPENSTA_EXE         sta executable name or path (default: sta)
    LIBERTY_PATH        default directory for .lib files
    SPEF_PATH           full path to the .spef parasitics file (not a directory); passed directly to read_parasitics

Environment (both):
    SESSION_TIMEOUT_S   per-command timeout in seconds (default: 120)
    SESSION_STARTUP_S   startup drain timeout in seconds (default: 10)
"""

import sys
import json
import subprocess
import argparse
import os
import re
import select
import time
import threading
from typing import Optional


def _readline_timed(stream, deadline: float) -> str:
    """
    Read one line from stream, returning '' if the deadline passes before
    a line arrives.  Uses select(2) so the calling thread is not blocked
    beyond the remaining time budget.

    Note: select on file objects is POSIX-only (Linux/macOS).  These wrapper
    scripts target Linux EDA environments; Windows is not supported.
    """
    remaining = deadline - time.time()
    if remaining <= 0:
        return ''
    ready, _, _ = select.select([stream], [], [], remaining)
    if not ready:
        return ''
    return stream.readline()

# ---------------------------------------------------------------------------
# Protocol helpers
# ---------------------------------------------------------------------------

def _send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, separators=(',', ':')) + '\n')
    sys.stdout.flush()


def _ok(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _log(msg: str) -> None:
    print(f"[mcp-session] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Tcl session
# ---------------------------------------------------------------------------

_SENTINEL = "<<MCP_SESSION_DONE>>"


class TclSession:
    """
    Wraps a long-lived Tcl-based EDA process (openroad / sta).

    Commands are sent via stdin; output is collected until the sentinel line
    appears.  stderr is merged into stdout so error messages are captured.
    """

    def __init__(self, exe: str, startup_timeout: int = 10):
        self._proc = subprocess.Popen(
            [exe],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,          # line-buffered
        )
        self._lock = threading.Lock()
        self._alive = True
        # Drain any startup banner
        self._drain_startup(startup_timeout)
        _log(f"session started (pid={self._proc.pid})")

    def _drain_startup(self, timeout: int) -> None:
        """
        Discard any startup banner by sending the sentinel immediately
        and collecting until it echoes back.  Respects timeout via select.
        """
        self._proc.stdin.write(f'puts "{_SENTINEL}"\n')
        self._proc.stdin.flush()
        deadline = time.time() + timeout
        while True:
            line = _readline_timed(self._proc.stdout, deadline)
            if not line or line.rstrip('\n') == _SENTINEL:
                break

    def run(self, tcl: str, timeout: int = 120) -> tuple[list[str], bool]:
        """
        Send Tcl commands and collect output until the sentinel.

        Returns (lines, had_error).  Thread-safe.
        """
        if not self._alive:
            return ["session is closed"], True

        with self._lock:
            script = tcl.strip() + f'\nputs "{_SENTINEL}"\n'
            try:
                self._proc.stdin.write(script)
                self._proc.stdin.flush()
            except BrokenPipeError:
                self._alive = False
                return ["session process died (broken pipe)"], True

            lines: list[str] = []
            had_error = False
            deadline = time.time() + timeout

            while True:
                line = _readline_timed(self._proc.stdout, deadline)
                if line == '':
                    # '' means either deadline passed (select timeout) or EOF
                    if self._proc.poll() is not None:
                        self._alive = False
                        had_error = True
                        lines.append("session process exited unexpectedly")
                    else:
                        had_error = True
                        lines.append(f"command timed out after {timeout}s")
                        try:
                            self._proc.kill()
                        except OSError:
                            pass
                        self._alive = False
                    break
                stripped = line.rstrip('\n')
                if stripped == _SENTINEL:
                    break
                lines.append(stripped)
                if re.search(r'\[ERROR\]|^Error\b|^error\b', stripped):
                    had_error = True

            return lines, had_error

    def is_alive(self) -> bool:
        if not self._alive:
            return False
        if self._proc.poll() is not None:
            self._alive = False
        return self._alive

    def close(self) -> None:
        if not self._alive:
            return
        try:
            self._proc.stdin.write("exit\n")
            self._proc.stdin.flush()
        except Exception:
            pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._alive = False
        _log("session closed")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_timing(lines: list[str]) -> dict:
    """Extract WNS, TNS, and worst slack paths from report_timing output."""
    text = '\n'.join(lines)
    result: dict = {}

    wns_m = re.search(r'wns\s+([-\d.]+)', text)
    tns_m = re.search(r'tns\s+([-\d.]+)', text)
    if wns_m:
        result["setup_wns_ns"] = float(wns_m.group(1))
    if tns_m:
        result["setup_tns_ns"] = float(tns_m.group(1))

    # Hold metrics
    hold_wns_m = re.search(r'hold\s+wns\s+([-\d.]+)', text, re.I)
    hold_tns_m = re.search(r'hold\s+tns\s+([-\d.]+)', text, re.I)
    if hold_wns_m:
        result["hold_wns_ns"] = float(hold_wns_m.group(1))
    if hold_tns_m:
        result["hold_tns_ns"] = float(hold_tns_m.group(1))

    # Worst path endpoint names
    endpoints = re.findall(r'Endpoint\s*:\s*(\S+)', text)
    if endpoints:
        result["worst_endpoints"] = endpoints[:5]

    slack_m = re.findall(r'slack\s+\((?:MET|VIOLATED)\)\s+([-\d.]+)', text)
    if slack_m:
        result["worst_slack_ns"] = float(slack_m[0])

    result["raw_lines"] = len(lines)
    return result


def _parse_drc(lines: list[str]) -> dict:
    """Extract DRC violation counts from check_drc / report_drc output."""
    text = '\n'.join(lines)
    result: dict = {}
    total_m = re.search(r'(\d+)\s+(?:DRC\s+)?(?:violations?|errors?)', text, re.I)
    if total_m:
        result["drc_total"] = int(total_m.group(1))
    else:
        # No count in the output: the result is unknown, not zero violations.
        result["drc_total"] = None

    cats: dict = {}
    for m in re.finditer(r'(\w[\w\s]*?)\s*:\s*(\d+)\s*violations?', text, re.I):
        cats[m.group(1).strip()] = int(m.group(2))
    if cats:
        result["drc_categories"] = cats

    result["raw_lines"] = len(lines)
    return result


def _parse_area(lines: list[str]) -> dict:
    """Extract area and utilisation from report_design_area output."""
    text = '\n'.join(lines)
    result: dict = {}
    area_m = re.search(r'Design area\s+([\d.]+)\s+u\^2\s+([\d.]+)%', text)
    if area_m:
        result["area_um2"] = float(area_m.group(1))
        result["utilisation_pct"] = float(area_m.group(2))
    result["raw_lines"] = len(lines)
    return result


def _parse_power(lines: list[str]) -> dict:
    """Extract power summary from report_power output."""
    text = '\n'.join(lines)
    result: dict = {}
    total_m = re.search(r'Total\s+([\d.e+\-]+)\s+([\d.e+\-]+)\s+([\d.e+\-]+)\s+([\d.e+\-]+)', text)
    if total_m:
        result["internal_power_W"] = float(total_m.group(1))
        result["switching_power_W"] = float(total_m.group(2))
        result["leakage_power_W"]   = float(total_m.group(3))
        result["total_power_W"]     = float(total_m.group(4))
    result["raw_lines"] = len(lines)
    return result


# ---------------------------------------------------------------------------
# Tool definitions per session type
# ---------------------------------------------------------------------------

_TOOLS_OPENROAD = [
    {
        "name": "load_design",
        "description": "Load an OpenROAD design database (.odb/.db) into the session",
        "inputSchema": {
            "type": "object",
            "properties": {
                "db_path": {
                    "type": "string",
                    "description": "Absolute path to the .odb or .db file"
                }
            },
            "required": ["db_path"],
        },
    },
    {
        "name": "query_timing",
        "description": "Report setup/hold timing summary: WNS, TNS, worst endpoints",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path_count": {
                    "type": "integer",
                    "default": 5,
                    "description": "Number of worst paths to report (default: 5)"
                },
                "path_type": {
                    "type": "string",
                    "enum": ["setup", "hold", "both"],
                    "default": "setup",
                    "description": "Timing check type to report"
                },
            },
        },
    },
    {
        "name": "query_drc",
        "description": "Run DRC check and return total violation count and per-category breakdown",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_design_area",
        "description": "Return core area (um²) and utilisation percentage",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_power",
        "description": "Return power breakdown: internal, switching, leakage, total (Watts)",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_tcl",
        "description": "Execute arbitrary Tcl in the OpenROAD session and return raw output lines",
        "inputSchema": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "Tcl script to execute"
                },
                "timeout_s": {
                    "type": "integer",
                    "description": "Per-command timeout override in seconds"
                },
            },
            "required": ["script"],
        },
    },
    {
        "name": "close_design",
        "description": "Reset the OpenROAD session (clears loaded design; session stays alive)",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_TOOLS_OPENSTA = [
    {
        "name": "load_design",
        "description": "Load a gate-level netlist, liberty, SDC, and optionally parasitics into OpenSTA",
        "inputSchema": {
            "type": "object",
            "properties": {
                "netlist": {
                    "type": "string",
                    "description": "Path to gate-level Verilog netlist"
                },
                "sdc": {
                    "type": "string",
                    "description": "Path to SDC constraints file"
                },
                "liberty_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Paths to .lib liberty files (supplements LIBERTY_PATH env)"
                },
                "spef": {
                    "type": "string",
                    "description": "Path to .spef parasitics file (optional)"
                },
                "top_module": {
                    "type": "string",
                    "description": "Name of the top-level module to link"
                },
            },
            "required": ["netlist", "sdc"],
        },
    },
    {
        "name": "report_timing",
        "description": "Report setup/hold timing: WNS, TNS, worst slack paths per corner",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path_count": {
                    "type": "integer",
                    "default": 5,
                    "description": "Number of worst paths (default: 5)"
                },
                "path_type": {
                    "type": "string",
                    "enum": ["max", "min", "both"],
                    "default": "max",
                    "description": "max=setup, min=hold"
                },
                "corner": {
                    "type": "string",
                    "description": "Specific corner name; omit for all corners"
                },
            },
        },
    },
    {
        "name": "report_slack_histogram",
        "description": "Return a slack distribution histogram across all endpoints",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bins": {
                    "type": "integer",
                    "default": 10,
                    "description": "Number of histogram bins"
                }
            },
        },
    },
    {
        "name": "check_timing",
        "description": "Report unconstrained paths, multi-driven nets, and missing constraints",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_tcl",
        "description": "Execute arbitrary Tcl in the OpenSTA session and return raw output lines",
        "inputSchema": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "Tcl script to execute"
                },
                "timeout_s": {
                    "type": "integer",
                    "description": "Per-command timeout override in seconds"
                },
            },
            "required": ["script"],
        },
    },
    {
        "name": "close_design",
        "description": "Reset the OpenSTA session (clears loaded design; session stays alive)",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def _dispatch_openroad(
    session: TclSession, tool_name: str, inputs: dict, timeout: int
) -> dict:
    if tool_name == "load_design":
        db = inputs["db_path"]
        lines, err = session.run(f'read_db {{{db}}}', timeout)
        return {"loaded": not err, "db_path": db, "messages": lines[:20], "had_error": err}

    elif tool_name == "query_timing":
        n = inputs.get("path_count", 5)
        pt = inputs.get("path_type", "setup")
        if pt == "both":
            tcl = (
                f'report_timing -path_type summary -nworst {n}\n'
                f'report_timing -path_type summary -nworst {n} -hold'
            )
        elif pt == "hold":
            tcl = f'report_timing -path_type summary -nworst {n} -hold'
        else:
            tcl = f'report_timing -path_type summary -nworst {n}'
        lines, err = session.run(tcl, timeout)
        parsed = _parse_timing(lines)
        parsed["had_error"] = err
        return parsed

    elif tool_name == "query_drc":
        lines, err = session.run('check_drc', timeout)
        parsed = _parse_drc(lines)
        parsed["had_error"] = err
        return parsed

    elif tool_name == "get_design_area":
        lines, err = session.run('report_design_area', timeout)
        parsed = _parse_area(lines)
        parsed["had_error"] = err
        return parsed

    elif tool_name == "get_power":
        lines, err = session.run('report_power', timeout)
        parsed = _parse_power(lines)
        parsed["had_error"] = err
        return parsed

    elif tool_name == "run_tcl":
        script = inputs["script"]
        t = inputs.get("timeout_s", timeout)
        lines, err = session.run(script, t)
        return {"output_lines": lines, "had_error": err, "line_count": len(lines)}

    elif tool_name == "close_design":
        lines, err = session.run('delete_db', timeout)
        return {"reset": True, "messages": lines[:10], "had_error": err}

    return {"error": f"unknown tool: {tool_name}"}


def _dispatch_opensta(
    session: TclSession, tool_name: str, inputs: dict, timeout: int
) -> dict:
    if tool_name == "load_design":
        tcl_parts: list[str] = []

        # Liberty files from env + input
        liberty_dir = os.environ.get("LIBERTY_PATH", "")
        for lib in inputs.get("liberty_files", []):
            tcl_parts.append(f'read_liberty {{{lib}}}')
        if liberty_dir and not inputs.get("liberty_files"):
            tcl_parts.append(f'foreach f [glob -nocomplain {{{liberty_dir}}}/*.lib] {{ read_liberty $f }}')

        tcl_parts.append(f'read_verilog {{{inputs["netlist"]}}}')
        top = inputs.get("top_module", "")
        tcl_parts.append(f'link_design {top}' if top else 'link_design')
        tcl_parts.append(f'read_sdc {{{inputs["sdc"]}}}')

        spef = inputs.get("spef") or os.environ.get("SPEF_PATH", "")
        if spef:
            tcl_parts.append(f'read_parasitics {{{spef}}}')

        lines, err = session.run('\n'.join(tcl_parts), timeout)
        return {"loaded": not err, "messages": lines[:20], "had_error": err}

    elif tool_name == "report_timing":
        n = inputs.get("path_count", 5)
        pt = inputs.get("path_type", "max")
        corner = inputs.get("corner", "")
        corner_flag = f'-corner {corner}' if corner else ''
        if pt == "both":
            tcl = (
                f'report_timing -path_type summary -nworst {n} {corner_flag}\n'
                f'report_timing -path_type summary -nworst {n} -path_type min {corner_flag}'
            )
        else:
            path_flag = '-path_type min' if pt == "min" else ''
            tcl = f'report_timing -path_type summary -nworst {n} {path_flag} {corner_flag}'
        lines, err = session.run(tcl, timeout)
        parsed = _parse_timing(lines)
        parsed["had_error"] = err
        return parsed

    elif tool_name == "report_slack_histogram":
        bins = inputs.get("bins", 10)
        lines, err = session.run(f'report_slack_histogram -digits 3 -bins {bins}', timeout)
        text = '\n'.join(lines)
        buckets: list[dict] = []
        for m in re.finditer(r'([-\d.]+)\s+([-\d.]+)\s+(\d+)', text):
            buckets.append({
                "slack_low_ns": float(m.group(1)),
                "slack_high_ns": float(m.group(2)),
                "count": int(m.group(3)),
            })
        return {"buckets": buckets, "had_error": err, "raw_lines": len(lines)}

    elif tool_name == "check_timing":
        lines, err = session.run('check_timing', timeout)
        text = '\n'.join(lines)
        unconstrained = len(re.findall(r'unconstrained', text, re.I))
        multi_driven  = len(re.findall(r'multiple.driven|multi.driven', text, re.I))
        return {
            "unconstrained_endpoints": unconstrained,
            "multi_driven_nets": multi_driven,
            "output_lines": lines[:30],
            "had_error": err,
        }

    elif tool_name == "run_tcl":
        script = inputs["script"]
        t = inputs.get("timeout_s", timeout)
        lines, err = session.run(script, t)
        return {"output_lines": lines, "had_error": err, "line_count": len(lines)}

    elif tool_name == "close_design":
        lines, err = session.run('remove_design', timeout)
        return {"reset": True, "messages": lines[:10], "had_error": err}

    return {"error": f"unknown tool: {tool_name}"}


# ---------------------------------------------------------------------------
# Main server loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persistent MCP stdio session adapter for OpenROAD / OpenSTA"
    )
    parser.add_argument(
        "--tool",
        required=True,
        choices=["openroad", "opensta"],
        help="Which tool to manage: openroad or opensta",
    )
    parser.add_argument("--version", default="1.0.0")
    args = parser.parse_args()

    tool_type = args.tool
    cmd_timeout = int(os.environ.get("SESSION_TIMEOUT_S", "120"))
    startup_timeout = int(os.environ.get("SESSION_STARTUP_S", "10"))

    if tool_type == "openroad":
        exe = os.environ.get("OPENROAD_EXE", "openroad")
        tools_list = _TOOLS_OPENROAD
        server_name = "openroad-session-mcp"
    else:
        exe = os.environ.get("OPENSTA_EXE", "sta")
        tools_list = _TOOLS_OPENSTA
        server_name = "opensta-session-mcp"

    session: Optional[TclSession] = None

    def _get_session() -> TclSession:
        nonlocal session
        if session is None or not session.is_alive():
            _log(f"(re)starting {tool_type} session with: {exe}")
            session = TclSession(exe, startup_timeout)
        return session

    _log(f"starting {server_name} (exe={exe}, cmd_timeout={cmd_timeout}s)")

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        try:
            req = json.loads(raw_line)
        except json.JSONDecodeError:
            _log(f"malformed JSON ignored: {raw_line[:80]}")
            continue

        method: str = req.get("method", "")
        req_id = req.get("id")
        params: dict = req.get("params") or {}

        if req_id is None:
            _log(f"notification: {method}")
            continue

        _log(f"request id={req_id} method={method}")

        if method == "initialize":
            _send(_ok(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": server_name, "version": args.version},
            }))

        elif method == "ping":
            _send(_ok(req_id, {}))

        elif method == "tools/list":
            _send(_ok(req_id, {"tools": tools_list}))

        elif method == "tools/call":
            call_name: str = params.get("name", "")
            call_inputs: dict = params.get("arguments") or {}

            known = {t["name"] for t in tools_list}
            if call_name not in known:
                _send(_err(req_id, -32602, f"Unknown tool '{call_name}'"))
                continue

            try:
                sess = _get_session()
                if tool_type == "openroad":
                    result = _dispatch_openroad(sess, call_name, call_inputs, cmd_timeout)
                else:
                    result = _dispatch_opensta(sess, call_name, call_inputs, cmd_timeout)
            except Exception as exc:
                _log(f"dispatch error: {exc}")
                result = {"had_error": True, "error": str(exc)}

            is_error = result.get("had_error", False)
            _send(_ok(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": is_error,
            }))

        else:
            _send(_err(req_id, -32601, f"Method not found: {method}"))

    # Clean up session on EOF
    if session and session.is_alive():
        session.close()


if __name__ == "__main__":
    main()
