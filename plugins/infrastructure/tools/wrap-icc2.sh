#!/usr/bin/env bash
# wrap-icc2.sh — run Synopsys IC Compiler II / Fusion Compiler and emit a compact JSON summary
# Usage: wrap-icc2.sh [icc2_shell args...]     e.g. wrap-icc2.sh -batch -f route.tcl
# Set WRAP_ICC2_TOOL=fc_shell to run Fusion Compiler through the same parser.
#
# Result markers: report_qor / report_timing (as wrap-dc.sh) plus check_routes /
# route_detail "Total number of DRCs = N" (N > 0 is a verified WARN, not a pass).
# UNMEASURED on the reference host: marker strings are the documented report formats.
#
# Contract (identical to every wrapper here): FAIL on a non-zero exit, an error line,
# a tool-specific fail marker, or a missing tool; WARN with verified=false when the
# tool exits 0 without a result this wrapper recognises; WARN (verified) when a result
# is present together with warnings; PASS only on a recognised result and no warnings.
# stdin is /dev/null, so a vendor shell that is accidentally left interactive reaches
# EOF and exits instead of hanging; with no arguments the tool is not started at all.
set -euo pipefail

TOOL="${WRAP_ICC2_TOOL:-icc2_shell}"

if ! command -v "$TOOL" &>/dev/null; then
  python3 - "$TOOL" <<'PYEOF'
import json, sys
print(json.dumps({"tool":"icc2","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["tool not found: " + sys.argv[1] + " (Synopsys IC Compiler II / Fusion Compiler)"],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

LOG=$(mktemp /tmp/icc2-XXXXXX.log)
STAMP=$(mktemp /tmp/icc2-stamp-XXXXXX)
if [[ $# -eq 0 ]]; then
  echo "error: no arguments provided; icc2_shell needs a script or command file (interactive mode not supported)" >"$LOG"
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

# Synopsys report_timing / report_qor / report_area lines (DC, ICC2, FC, PrimeTime).
slacks = floats(r'slack \((?:MET|VIOLATED)[^)]*\)\s+(-?[\d.]+)')
qor_slack = floats(r'Critical Path Slack:\s*(-?[\d.]+)')
tns = floats(r'Total Negative Slack:\s*(-?[\d.]+)')
area = floats(r'Total cell area:\s*([\d.]+)')
if slacks or qor_slack:
    summary["worst_slack"] = min(slacks + qor_slack)
if tns:
    summary["tns"] = min(tns)
if area:
    summary["total_cell_area"] = area[-1]
evidence = bool(slacks or qor_slack or tns or area)

drcs = [int(v) for v in re.findall(r'Total number of DRCs\s*=\s*(\d+)', text)]
if drcs:
    summary["drc_total"] = drcs[-1]
    evidence = True
    if drcs[-1] > 0:
        result_warnings.append(f"{drcs[-1]} routing DRC violations reported")

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
    "tool":      "icc2",
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
