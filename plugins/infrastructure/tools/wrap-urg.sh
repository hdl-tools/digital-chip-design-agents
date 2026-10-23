#!/usr/bin/env bash
# wrap-urg.sh — run Synopsys urg (coverage merge/report) and emit a compact JSON summary
# Usage: wrap-urg.sh [urg args...]      e.g. wrap-urg.sh -dir a.vdb b.vdb -dbname merged -report rpt -format text
#
# The summary is parsed from <report>/dashboard.txt (the "Total Coverage Summary"
# table), so pass -format text or -format both: the HTML-only default has no
# dashboard.txt and the result is WARN / verified=false. <report> is the -report
# argument, default urgReport. A dashboard.txt older than this run (left by an
# earlier run that this one failed to overwrite) is not a result.
#
# The tool is resolved with `command -v urg` in this non-interactive bash, which
# ignores user shell aliases, then $VCS_HOME/bin/urg.
set -euo pipefail

TOOL=""
if command -v urg &>/dev/null; then
  TOOL=$(command -v urg)
elif [[ -n "${VCS_HOME:-}" && -x "${VCS_HOME}/bin/urg" ]]; then
  TOOL="${VCS_HOME}/bin/urg"
fi

if [[ -z "$TOOL" ]]; then
  python3 - <<'PYEOF'
import json
print(json.dumps({"tool":"urg","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["tool not found: urg (Synopsys URG) - searched PATH and $VCS_HOME/bin"],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

REPORT_DIR="urgReport"
prev=""
for arg in "$@"; do
  if [[ "$prev" == "-report" ]]; then REPORT_DIR="$arg"; fi
  prev="$arg"
done

LOG=$(mktemp /tmp/urg-XXXXXX.log)
STAMP=$(mktemp /tmp/urg-stamp-XXXXXX)
set +e
"$TOOL" "$@" >"$LOG" 2>&1
EXIT_CODE=$?
set -e

python3 - "$LOG" "$EXIT_CODE" "$REPORT_DIR" "$STAMP" <<'PYEOF'
import json, os, re, sys

log_path, exit_code, report_dir, stamp = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]

with open(log_path, encoding='utf-8', errors='replace') as f:
    text = f.read()

errors   = [l.strip() for l in text.splitlines() if re.search(r'\bError-\[', l)]
warnings = [l.strip() for l in text.splitlines() if re.search(r'\bWARN(?:ING)?\b', l, re.I)]

fail_m = re.search(r'Error-\[([\w-]+)\]', text)

summary = {"report_dir": os.path.abspath(report_dir), "tests": None}
metrics = {}
dashboard = os.path.join(report_dir, "dashboard.txt")
stale = False
if os.path.isfile(dashboard):
    stale = os.path.getmtime(dashboard) < os.path.getmtime(stamp)
    if not stale:
        with open(dashboard, encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()
        for n, line in enumerate(lines):
            m = re.match(r'\s*Number of tests:\s*(\d+)', line)
            if m:
                summary["tests"] = int(m.group(1))
            if line.strip().startswith("Total Coverage Summary") and n + 2 < len(lines):
                header = lines[n + 1].split()
                values = lines[n + 2].split()
                for key, value in zip(header, values):
                    try:
                        metrics[key.lower()] = float(value)
                    except ValueError:
                        metrics[key.lower()] = None  # "--": metric not collected
                break
os.unlink(stamp)

summary["metrics"] = metrics
summary["errors"] = len(errors)
summary["warnings"] = len(warnings)
summary["first_error_code"] = fail_m.group(1) if fail_m else None

evidence = any(v is not None for v in metrics.values())
all_dashes = bool(metrics) and not evidence  # urg exits 0 even when nothing was instrumented

if fail_m or exit_code != 0:
    status = "FAIL"
elif not evidence:
    status = "WARN"
    if all_dashes:
        why = "every metric is '--': nothing was instrumented (check -cm flags and the -cm_hier scope)"
    elif stale:
        why = "stale dashboard.txt from an earlier run"
    else:
        why = f"no Total Coverage Summary in {dashboard} (pass -format text or both)"
    warnings.insert(0, f"no recognisable result in tool output (exit 0): {why} - not verified; read raw_log")
elif warnings or errors:
    status = "WARN"
else:
    status = "PASS"

print(json.dumps({
    "tool":      "urg",
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
