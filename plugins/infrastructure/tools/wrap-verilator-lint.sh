#!/usr/bin/env bash
# wrap-verilator-lint.sh — run Verilator lint and emit a compact JSON summary
# Usage: wrap-verilator-lint.sh [verilator args...] <files>
# Runs `verilator --lint-only <args>`; --lint-only is added unless already given.
# Verilator exits non-zero on warnings unless -Wno-fatal is passed, so a
# warnings-only run reports FAIL with error_count 0 and exited_on "warnings".
set -euo pipefail

TOOL="verilator"

if ! command -v "$TOOL" &>/dev/null; then
  python3 - <<'PYEOF'
import json
print(json.dumps({"tool":"verilator-lint","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["tool not found: verilator"],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

HAS_LINT_ONLY=0
for arg in "$@"; do
  if [[ "$arg" == "--lint-only" ]]; then
    HAS_LINT_ONLY=1
  fi
done
if [[ $HAS_LINT_ONLY -eq 0 ]]; then
  set -- --lint-only "$@"
fi

LOG=$(mktemp /tmp/verilator-lint-XXXXXX.log)
set +e
"$TOOL" "$@" >"$LOG" 2>&1
EXIT_CODE=$?
set -e

python3 - "$LOG" "$EXIT_CODE" "$@" <<'PYEOF'
import json, os, re, sys

log_path = sys.argv[1]
exit_code = int(sys.argv[2])
args = sys.argv[3:]

with open(log_path, encoding='utf-8', errors='replace') as f:
    text = f.read()

ERROR_RE   = re.compile(r'^%Error(?:-[A-Z0-9_]+)?:')
WARNING_RE = re.compile(r'^%Warning(?:-([A-Z0-9_]+))?:')
# Verilator's closing lines repeat the totals; they are not findings.
EXIT_RE    = re.compile(r'^%Error: (?:Exiting due to \d+ (error|warning)|Command Failed)')

errors, warnings, closing = [], [], []
warnings_by_code = {}
exited_on = None
for line in text.splitlines():
    line = line.strip()
    exit_m = EXIT_RE.match(line)
    if exit_m:
        closing.append(line)
        if exit_m.group(1):
            exited_on = exit_m.group(1) + "s"
        continue
    if ERROR_RE.match(line):
        errors.append(line)
        continue
    warn_m = WARNING_RE.match(line)
    if warn_m:
        warnings.append(line)
        code = warn_m.group(1) or "UNCODED"
        warnings_by_code[code] = warnings_by_code.get(code, 0) + 1

input_files = [a for a in args if not a.startswith(("-", "+")) and os.path.isfile(a)]
info_only = any(a in ("--version", "-V", "--help") for a in args)

summary = {
    "error_count":      len(errors),
    "warning_count":    len(warnings),
    "warnings_by_code": warnings_by_code,
    "input_files":      len(input_files),
}
if exited_on:
    summary["exited_on"] = exited_on

# A clean lint prints nothing, so empty output with exit 0 is a pass only when
# Verilator was given at least one design file that exists. A diagnostic is a
# result in its own right.
evidence = bool(errors or warnings) or (bool(input_files) and not info_only)

if exit_code != 0 or errors:
    status = "FAIL"
    if not errors:
        errors = closing or [f"verilator exited {exit_code} with no %Error line; read raw_log"]
elif not evidence:
    status = "WARN"
    warnings.insert(0, "no recognisable result in tool output (exit 0) - not verified; read raw_log "
                       "(a clean lint prints nothing, so a pass needs an existing design file among the arguments)")
elif warnings:
    status = "WARN"
else:
    status = "PASS"

print(json.dumps({
    "tool":      "verilator-lint",
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
