#!/usr/bin/env bash
# wrap-lec.sh — run Cadence Conformal LEC and emit a compact JSON summary
# Usage: wrap-lec.sh [lec args...]     e.g. wrap-lec.sh -xl -nogui -dofile lec.do
#
# Result: the compare summary table ("Compared points ... Total" followed by rows such
# as "Equivalent 10 20 30" and, when non-zero, "Non-equivalent", "Abort", "Not-compared").
# The last number of a row is its total. PASS needs an Equivalent row and no
# Non-equivalent or Abort points; a Non-equivalent or Abort total > 0 fails (unproven is
# not equivalent). Messages are "// Error:" / "// Warning:". UNMEASURED on the reference
# host (Conformal 24.10): the row names follow the documented compare report.
#
# Contract (identical to every wrapper here): FAIL on a non-zero exit, an error line,
# a tool-specific fail marker, or a missing tool; WARN with verified=false when the
# tool exits 0 without a result this wrapper recognises; WARN (verified) when a result
# is present together with warnings; PASS only on a recognised result and no warnings.
# stdin is /dev/null, so a vendor shell that is accidentally left interactive reaches
# EOF and exits instead of hanging; with no arguments the tool is not started at all.
set -euo pipefail

TOOL="lec"

if ! command -v "$TOOL" &>/dev/null; then
  python3 - "$TOOL" <<'PYEOF'
import json, sys
print(json.dumps({"tool":"lec","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["tool not found: " + sys.argv[1] + " (Cadence Conformal LEC)"],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

LOG=$(mktemp /tmp/lec-XXXXXX.log)
STAMP=$(mktemp /tmp/lec-stamp-XXXXXX)
if [[ $# -eq 0 ]]; then
  echo "error: no arguments provided; lec needs a script or command file (interactive mode not supported)" >"$LOG"
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

rows = {}
for m in re.finditer(r'^\s*(Non-equivalent|Inverted-equivalent|Equivalent|Abort(?:ed)?|Not-compared)\s+((?:\d+\s+)*\d+)\s*$', text, re.M):
    rows[m.group(1).lower()] = int(m.group(2).split()[-1])
abort = rows.get("abort", rows.get("aborted", 0))
summary["equivalent"] = rows.get("equivalent")
summary["non_equivalent"] = rows.get("non-equivalent", 0) if rows else None
summary["aborted"] = abort if rows else None
if rows.get("non-equivalent", 0) > 0:
    fail_markers.append(f"{rows['non-equivalent']} non-equivalent compare points")
if abort > 0:
    fail_markers.append(f"{abort} aborted compare points - equivalence not proven")
if rows.get("not-compared", 0) > 0:
    result_warnings.append(f"{rows['not-compared']} not-compared points")
evidence = "equivalent" in rows

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
    "tool":      "lec",
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
