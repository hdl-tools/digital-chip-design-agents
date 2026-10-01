#!/usr/bin/env bash
# wrap-verilator-sim.sh — run Verilator simulation binary and emit a compact JSON summary
# Usage: wrap-verilator-sim.sh <sim_binary> [args...]
set -euo pipefail

if [[ $# -lt 1 ]]; then
  python3 - <<'PYEOF'
import json
print(json.dumps({"tool":"verilator-sim","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["no sim binary provided: usage: wrap-verilator-sim.sh <sim_binary> [args...]"],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

SIM_BIN="$1"

# The first argument is the simulation binary, so --version / --help never reach
# a tool. Answer them here the way the other wrappers do on a --version run:
# nothing was verified, but the wrapper ran and printed its JSON.
if [[ "$SIM_BIN" == "--version" || "$SIM_BIN" == "--help" || "$SIM_BIN" == "-h" ]]; then
  python3 - <<'PYEOF'
import json
print(json.dumps({"tool":"verilator-sim","exit_code":0,"status":"WARN","verified":False,"summary":{},"errors":[],"warnings":["no simulation run - not verified: usage: wrap-verilator-sim.sh <sim_binary> [args...] (for Verilator lint use wrap-verilator-lint.sh)"],"raw_log":""}))
PYEOF
  exit 0
fi

if [[ ! -x "$SIM_BIN" ]]; then
  python3 - "$SIM_BIN" <<'PYEOF'
import json, sys
sim_bin = sys.argv[1]
print(json.dumps({"tool":"verilator-sim","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":[f"sim binary not found or not executable: {sim_bin}"],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

LOG=$(mktemp /tmp/verilator-sim-XXXXXX.log)
set +e
"$@" >"$LOG" 2>&1
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

passed_m   = re.search(r'TEST PASSED', text, re.I)
failed_m   = re.search(r'TEST FAILED', text, re.I)
coverage_m = re.search(r'coverage[^\d]*([\d.]+)\s*%', text, re.I)

summary = {}
summary["test_passed"] = bool(passed_m)
summary["test_failed"] = bool(failed_m)
if coverage_m:
    summary["coverage_pct"] = float(coverage_m.group(1))
summary["error_count"]   = len(errors)
summary["warning_count"] = len(warnings)

# PASS needs the testbench's own pass marker; exit 0 alone is not one. An ERROR
# line does not fail the run by itself, because simulation logs print lines such
# as "Error count: 0", but it keeps the run from passing silently.
evidence = bool(passed_m)

if failed_m or exit_code != 0:
    status = "FAIL"
elif not evidence:
    status = "WARN"
    warnings.insert(0, "no recognisable result in tool output (exit 0) - not verified; read raw_log")
elif warnings or errors:
    status = "WARN"
else:
    status = "PASS"

print(json.dumps({
    "tool":      "verilator-sim",
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
