#!/usr/bin/env bash
# wrap-xrun-compile.sh — run Cadence Xcelium (xrun) compile and emit a compact JSON summary
# Usage: wrap-xrun-compile.sh [xrun args...]
set -euo pipefail

TOOL="xrun"

if ! command -v "$TOOL" &>/dev/null; then
  python3 - <<'PYEOF'
import json
print(json.dumps({"tool":"xrun-compile","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["tool not found: xrun (Cadence Xcelium)"],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

LOG=$(mktemp /tmp/xrun-compile-XXXXXX.log)
set +e
"$TOOL" "$@" >"$LOG" 2>&1
EXIT_CODE=$?
set -e

python3 - "$LOG" "$EXIT_CODE" <<'PYEOF'
import json, re, sys

log_path = sys.argv[1]
exit_code = int(sys.argv[2])

with open(log_path, encoding='utf-8', errors='replace') as f:
    text = f.read()

errors   = [l.strip() for l in text.splitlines() if re.search(r'\bERROR\b', l, re.I)]
warnings = [l.strip() for l in text.splitlines() if re.search(r'\bWARN(?:ING)?\b', l, re.I)]

# Cadence tools prefix diagnostics with a message-ID code, e.g.
# "xrun: *E,NOFILE: cannot find file" or "xrun: *F,CUVCCM".
fail_m     = re.search(r'\*[EF],(\w+)', text)
evidence_m = re.search(r'xrun: compile complete', text, re.I)
file_m     = re.search(r'([^\s:]+\.(?:v|sv|vams|vh|svh)):\d+', text) if fail_m else None

summary = {
    "errors":   len(errors),
    "warnings": len(warnings),
    "first_error_code": fail_m.group(1) if fail_m else None,
    "first_error_file": file_m.group(1) if file_m else None,
}

evidence = bool(evidence_m)

if fail_m or exit_code != 0:
    status = "FAIL"
elif not evidence:
    status = "WARN"
    warnings.insert(0, "no recognisable result in tool output (exit 0) - not verified; read raw_log")
elif warnings or errors:
    status = "WARN"
else:
    status = "PASS"

print(json.dumps({
    "tool":      "xrun-compile",
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
