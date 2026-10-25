#!/usr/bin/env bash
# wrap-starrc.sh — run Synopsys StarRC and emit a compact JSON summary
# Usage: wrap-starrc.sh [StarXtract args...]  e.g. wrap-starrc.sh star_cmd
#
# The result is the parasitics file, not the log: the wrapper reads NETLIST_FILE: from
# the StarRC command file (the last argument) and requires that file to exist, to be
# written by this run, and to start with a *SPEF header when NETLIST_FORMAT is SPEF (the
# default here). It reports the *D_NET count. A missing, stale or empty parasitics file
# is WARN / verified=false whatever the exit code says. Errors are "ERROR: ..." lines.
# The command-file keywords are the documented StarRC syntax; UNMEASURED on the
# reference host (StarRC X-2025.06-SP1).
#
# Contract (identical to every wrapper here): FAIL on a non-zero exit, an error line,
# a tool-specific fail marker, or a missing tool; WARN with verified=false when the
# tool exits 0 without a result this wrapper recognises; WARN (verified) when a result
# is present together with warnings; PASS only on a recognised result and no warnings.
# stdin is /dev/null, so a vendor shell that is accidentally left interactive reaches
# EOF and exits instead of hanging; with no arguments the tool is not started at all.
set -euo pipefail

TOOL="StarXtract"

if ! command -v "$TOOL" &>/dev/null; then
  python3 - "$TOOL" <<'PYEOF'
import json, sys
print(json.dumps({"tool":"starrc","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["tool not found: " + sys.argv[1] + " (Synopsys StarRC)"],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

LOG=$(mktemp /tmp/starrc-XXXXXX.log)
STAMP=$(mktemp /tmp/starrc-stamp-XXXXXX)
if [[ $# -eq 0 ]]; then
  echo "error: no arguments provided; StarXtract needs a script or command file (interactive mode not supported)" >"$LOG"
  EXIT_CODE=1
else
  set +e
  "$TOOL" "$@" </dev/null >"$LOG" 2>&1
  EXIT_CODE=$?
  set -e
fi

python3 - "$LOG" "$EXIT_CODE" "$STAMP" "$@" <<'PYEOF'
import json, os, re, sys

log_path, exit_code, stamp = sys.argv[1], int(sys.argv[2]), sys.argv[3]
args = sys.argv[4:]

with open(log_path, encoding='utf-8', errors='replace') as f:
    text = f.read()
lines = text.splitlines()

# Message prefixes, anchored at the start of a line so a summary such as
# "0 error(s)" or "Error count: 0" is not an error:
#   Synopsys  "Error: ... (UID-341)"      "Warning: ... (OPT-150)"
#   Cadence   "**ERROR: (IMPSYT-1)"       "**WARN: (IMPEXT-2)"   Genus "Error   : ... [CODE-1]"
#   Conformal "// Error: ..."             "// Warning: ..."
ERR  = re.compile(r'^\s*(?://\s*)?\**\s*ERROR\b\s*[:(]', re.I)
WARN = re.compile(r'^\s*(?://\s*)?\**\s*\[?WARN(?:ING)?\b', re.I)
CODE = re.compile(r'[(\[]([A-Z][A-Z0-9_]*-\d+)[)\]]')

errors   = [l.strip() for l in lines if ERR.search(l)]
warnings = [l.strip() for l in lines if WARN.search(l) and not ERR.search(l)]
codes = {}
for l in warnings:
    m = CODE.search(l)
    if m:
        codes[m.group(1)] = codes.get(m.group(1), 0) + 1
first_code = next((CODE.search(l).group(1) for l in errors if CODE.search(l)), None)

def floats(pattern, flags=0):
    return [float(v) for v in re.findall(pattern, text, flags)]

def fresh(path):
    """A report file counts only if this run wrote it."""
    return bool(path) and os.path.isfile(path) and os.path.getmtime(path) >= os.path.getmtime(stamp)

summary = {}
fail_markers = []   # tool-specific verdicts that fail the run even at exit 0
result_warnings = []  # a recognised result that is not clean (violations, property errors)

cmd_file = args[-1] if args else None
netlist, fmt = None, "SPEF"
if cmd_file and os.path.isfile(cmd_file):
    with open(cmd_file, encoding='utf-8', errors='replace') as f:
        for raw in f:
            line = raw.split("*", 1)[0].strip() if raw.lstrip().startswith("*") else raw.strip()
            m = re.match(r'NETLIST_FILE\s*:\s*(\S+)', line)
            if m:
                netlist = m.group(1)
            m = re.match(r'NETLIST_FORMAT\s*:\s*(\S+)', line)
            if m:
                fmt = m.group(1).upper()
summary["command_file"] = cmd_file
summary["netlist_file"] = os.path.abspath(netlist) if netlist else None
summary["netlist_format"] = fmt
evidence = False
why = None
if not netlist:
    why = "no NETLIST_FILE: in the command file"
elif not os.path.isfile(netlist):
    why = f"parasitics file {netlist} was not written"
elif not fresh(netlist):
    why = f"parasitics file {netlist} is older than this run (stale)"
else:
    nets = 0
    with open(netlist, encoding='utf-8', errors='replace') as f:
        head = f.read(4096)
        f.seek(0)
        for line in f:
            if line.startswith("*D_NET"):
                nets += 1
    if fmt == "SPEF" and not head.lstrip().startswith("*SPEF"):
        why = f"{netlist} has no *SPEF header"
    elif fmt == "SPEF" and nets == 0:
        why = f"{netlist} holds no *D_NET entries"
    else:
        summary["d_nets"] = nets if fmt == "SPEF" else None
        evidence = True
if why:
    summary["no_result_reason"] = why

os.unlink(stamp)
summary["error_count"] = len(errors)
summary["warning_count"] = len(warnings)
summary["first_error_code"] = first_code
if codes:
    summary["warnings_by_code"] = codes

warnings = result_warnings + warnings
if exit_code != 0 or errors or fail_markers:
    status = "FAIL"
    errors = fail_markers + errors
elif not evidence:
    status = "WARN"
    warnings.insert(0, "no recognisable result in tool output (exit 0) - not verified; read raw_log")
elif warnings:
    status = "WARN"
else:
    status = "PASS"

print(json.dumps({
    "tool":      "starrc",
    "exit_code": exit_code,
    "status":    status,
    "verified":  status == "FAIL" or evidence,
    "summary":   summary,
    "errors":    errors[:10],
    "warnings":  warnings[:10],
    "raw_log":   log_path
}, indent=2))
PYEOF

exit $EXIT_CODE
