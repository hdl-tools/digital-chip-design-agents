#!/usr/bin/env bash
# wrap-innovus.sh — run Cadence Innovus and emit a compact JSON summary
# Usage: wrap-innovus.sh [innovus args...]    e.g. wrap-innovus.sh -batch -no_gui -files place.tcl
#
# Result markers: the timeDesign / report_timing_summary table row "WNS (ns):| <v> |",
# verify_drc "Total Violations : N" and streamOut "Streamout is finished". DRC N > 0 is a
# verified WARN. Messages are "**ERROR: (IMPxxx-n)" / "**WARN: (IMPxxx-n)".
# UNMEASURED on the reference host.
#
# Contract (identical to every wrapper here): FAIL on a non-zero exit, an error line,
# a tool-specific fail marker, or a missing tool; WARN with verified=false when the
# tool exits 0 without a result this wrapper recognises; WARN (verified) when a result
# is present together with warnings; PASS only on a recognised result and no warnings.
# stdin is /dev/null, so a vendor shell that is accidentally left interactive reaches
# EOF and exits instead of hanging; with no arguments the tool is not started at all.
set -euo pipefail

TOOL="innovus"

if ! command -v "$TOOL" &>/dev/null; then
  python3 - "$TOOL" <<'PYEOF'
import json, sys
print(json.dumps({"tool":"innovus","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["tool not found: " + sys.argv[1] + " (Cadence Innovus)"],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

# The deploy-time smoke test calls --version/--help. Answer it here instead of starting
# the vendor shell, which checks out a licence and can take minutes to print a version.
if [[ $# -eq 1 && ( "$1" == "--version" || "$1" == "--help" || "$1" == "-h" ) ]]; then
  python3 - "$TOOL" <<'PYEOF'
import json, shutil, sys
print(json.dumps({"tool":"innovus","exit_code":0,"status":"WARN","verified":False,"summary":{"tool_path":shutil.which(sys.argv[1])},"errors":[],"warnings":["usage: wrap-innovus.sh [innovus args...] - answered by the wrapper; innovus was found but not started (no licence checked out)"],"raw_log":""}))
PYEOF
  exit 0
fi

LOG=$(mktemp /tmp/innovus-XXXXXX.log)
STAMP=$(mktemp /tmp/innovus-stamp-XXXXXX)
if [[ $# -eq 0 ]]; then
  echo "error: no arguments provided; innovus needs a script or command file (interactive mode not supported)" >"$LOG"
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

wns = floats(r'WNS \(ns\):\s*\|\s*(-?[\d.]+)')
drc = [int(v) for v in re.findall(r'Total Violations\s*:\s*(\d+)', text)]
gds = bool(re.search(r'Streamout is finished', text))
if wns:
    summary["wns_ns"] = min(wns)
if drc:
    summary["drc_total"] = drc[-1]
    if drc[-1] > 0:
        result_warnings.append(f"{drc[-1]} DRC violations reported by verify_drc")
if gds:
    summary["gds_written"] = True
evidence = bool(wns or drc or gds)

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
    "tool":      "innovus",
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
