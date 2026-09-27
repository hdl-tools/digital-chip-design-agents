#!/usr/bin/env bash
# wrap-symbiflow.sh — run SymbiYosys (sby) and emit a compact JSON summary
set -euo pipefail

TOOL="sby"

if ! command -v "$TOOL" &>/dev/null; then
  python3 - <<'PYEOF'
import json
print(json.dumps({"tool":"symbiflow","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["tool not found: sby (SymbiYosys)"],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

LOG=$(mktemp /tmp/symbiflow-XXXXXX.log)
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
warnings = [l.strip() for l in text.splitlines() if re.search(r'\bWARN\b',  l, re.I)]

proved_props  = re.findall(r'PROVED\s+(\S+)', text, re.I)
failed_props  = re.findall(r'FAILED\s+(\S+)', text, re.I)
unknown_props = re.findall(r'UNKNOWN\s+(\S+)', text, re.I)

# Counterexample info: look for trace file references
counterexample_m = re.search(r'Counterexample\s+written\s+to\s+(\S+)', text, re.I)

summary = {
    "proved":  proved_props,
    "failed":  failed_props,
    "unknown": unknown_props,
    "proved_count":  len(proved_props),
    "failed_count":  len(failed_props),
    "unknown_count": len(unknown_props),
}
if counterexample_m:
    summary["counterexample_trace"] = counterexample_m.group(1)
summary["error_count"]   = len(errors)
summary["warning_count"] = len(warnings)

# PASS needs a property result found in the output; exit 0 alone is not one.
evidence = bool(proved_props or failed_props or unknown_props)

if errors or failed_props or exit_code != 0:
    status = "FAIL"
elif not evidence:
    status = "WARN"
    warnings.insert(0, "no recognisable result in tool output (exit 0) - not verified; read raw_log")
elif warnings or unknown_props:
    status = "WARN"
else:
    status = "PASS"

print(json.dumps({
    "tool":      "symbiflow",
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
