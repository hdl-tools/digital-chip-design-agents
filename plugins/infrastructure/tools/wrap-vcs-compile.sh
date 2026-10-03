#!/usr/bin/env bash
# wrap-vcs-compile.sh — run Synopsys VCS compile and emit a compact JSON summary
# Usage: wrap-vcs-compile.sh [vcs args...]
set -euo pipefail

TOOL="vcs"

if ! command -v "$TOOL" &>/dev/null; then
  python3 - <<'PYEOF'
import json
print(json.dumps({"tool":"vcs-compile","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["tool not found: vcs (Synopsys VCS)"],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

LOG=$(mktemp /tmp/vcs-compile-XXXXXX.log)
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

# #82: 8 switches (including +access+rwc) were silently dropped as
# Warning-[UNKWN_OPTVSIM]/Warning-[UNK_COMP_ARG] - a clean exit with these
# present is a real defect, not noise, so they are counted like any other warning.
fail_m     = re.search(r'Error-\[(\w+)\]', text)
evidence_m = re.search(r'CPU time:\s*[\d.]+\s*seconds?\s+to compile', text, re.I)
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
    "tool":      "vcs-compile",
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
