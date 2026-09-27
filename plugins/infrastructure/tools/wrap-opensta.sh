#!/usr/bin/env bash
# wrap-opensta.sh — run OpenSTA and emit a compact JSON summary
set -euo pipefail

TOOL="sta"

if ! command -v "$TOOL" &>/dev/null; then
  python3 - <<'PYEOF'
import json
print(json.dumps({"tool":"opensta","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["tool not found: sta (OpenSTA)"],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

LOG=$(mktemp /tmp/opensta-XXXXXX.log)
if [[ $# -eq 0 ]]; then
  echo "error: no arguments provided; sta requires a script file (interactive mode not supported)" >"$LOG"
  EXIT_CODE=1
else
  set +e
  "$TOOL" "$@" >"$LOG" 2>&1
  EXIT_CODE=$?
  set -e
fi

python3 - "$LOG" "$EXIT_CODE" <<'PYEOF'
import json, re, sys

log_path = sys.argv[1]
exit_code = int(sys.argv[2])

with open(log_path, encoding='utf-8', errors='replace') as f:
    text = f.read()

errors   = [l.strip() for l in text.splitlines() if re.search(r'\bERROR\b', l, re.I)]
warnings = [l.strip() for l in text.splitlines() if re.search(r'\bWARN(?:ING)?\b', l, re.I)]

wns_m     = re.search(r'wns\s+([-\d.]+)', text)
tns_m     = re.search(r'tns\s+([-\d.]+)', text)
endpoint_m = re.search(r'Worst slack.*?endpoint\s+(\S+)', text, re.I | re.S)

summary = {}
if wns_m:      summary["wns_ns"]            = float(wns_m.group(1))
if tns_m:      summary["tns_ns"]            = float(tns_m.group(1))
if endpoint_m: summary["worst_endpoint"]    = endpoint_m.group(1)
summary["error_count"]   = len(errors)
summary["warning_count"] = len(warnings)

# PASS needs a result found in the output; exit 0 alone is not one.
evidence = bool(wns_m or tns_m or endpoint_m)

if exit_code != 0 or errors:
    status = "FAIL"
elif not evidence:
    status = "WARN"
    warnings.insert(0, "no recognisable result in tool output (exit 0) - not verified; read raw_log")
elif warnings:
    status = "WARN"
else:
    status = "PASS"

print(json.dumps({
    "tool":      "opensta",
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
