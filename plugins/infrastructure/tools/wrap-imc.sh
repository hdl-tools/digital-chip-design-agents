#!/usr/bin/env bash
# wrap-imc.sh — run Cadence IMC in batch (-execcmd / -exec) and emit a compact JSON summary
# Usage: wrap-imc.sh -execcmd "merge cov_work/scope/* -out merged; load -run merged; report -summary -metrics overall"
#        wrap-imc.sh -exec cmds.tcl
#
# The summary is parsed from IMC's stdout, so the report command must print to
# stdout (no `-out <file>` on the report). Parsed metrics: overall, block,
# expression, toggle, fsm (and assertion / covergroup where present), each a
# percentage, from either a "<metric> ...: N%" line or a header row naming the
# metrics followed by a row of percentages. The table layout is UNVERIFIED on a
# real install (no imc on the reference host): a layout this parser does not
# recognise yields WARN / verified=false, never a PASS.
#
# imc ships with Xcelium under $XCELIUM_HOME/tools/bin, or separately with
# vManager / IMC, and is often NOT on PATH even when xrun is. Measured on the
# reference host: XCELIUM 24.03 carries only tools/bin/launch_rmi_imc.sh and no
# imc binary at all. Search order: PATH, $IMC_HOME/bin, $XCELIUM_HOME/{tools/bin,
# bin,tools.lnx86/bin}, the same three under the install root of `command -v xrun`,
# $VMANAGER_HOME/bin. User shell aliases are not seen (non-interactive bash).
set -euo pipefail

TOOL=""
SEARCHED=()
candidate() {
  [[ -n "$TOOL" ]] && return 0
  local seen
  for seen in "${SEARCHED[@]}"; do [[ "$seen" == "$1" ]] && return 0; done
  SEARCHED+=("$1")
  if [[ -x "$1/imc" && ! -d "$1/imc" ]]; then TOOL="$1/imc"; fi
}

if command -v imc &>/dev/null; then
  TOOL=$(command -v imc)
fi
SEARCHED+=("PATH")
[[ -n "${IMC_HOME:-}" ]] && candidate "${IMC_HOME}/bin"
if [[ -n "${XCELIUM_HOME:-}" ]]; then
  candidate "${XCELIUM_HOME}/tools/bin"
  candidate "${XCELIUM_HOME}/bin"
  candidate "${XCELIUM_HOME}/tools.lnx86/bin"
fi
if [[ -z "$TOOL" ]] && command -v xrun &>/dev/null; then
  XRUN_DIR=$(dirname "$(command -v xrun)")
  # xrun lives at <root>/bin/xrun or <root>/tools/bin/xrun
  ROOT=$(dirname "$XRUN_DIR")
  [[ "$(basename "$ROOT")" == "tools" ]] && ROOT=$(dirname "$ROOT")
  candidate "${ROOT}/tools/bin"
  candidate "${ROOT}/bin"
  candidate "${ROOT}/tools.lnx86/bin"
fi
[[ -n "${VMANAGER_HOME:-}" ]] && candidate "${VMANAGER_HOME}/bin"

if [[ -z "$TOOL" ]]; then
  python3 - "${SEARCHED[@]}" <<'PYEOF'
import json, sys
where = ", ".join(sys.argv[1:])
print(json.dumps({"tool":"imc","exit_code":1,"status":"FAIL","verified":False,"summary":{"searched":sys.argv[1:]},
    "errors":[f"tool not found: imc (Cadence IMC) - searched {where}; Xcelium coverage databases (cov_work/*.ucd) can be collected but not merged or reported without imc"],
    "warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

BATCH=(-batch)
for arg in "$@"; do if [[ "$arg" == "-batch" ]]; then BATCH=(); fi; done

LOG=$(mktemp /tmp/imc-XXXXXX.log)
set +e
"$TOOL" ${BATCH[@]+"${BATCH[@]}"} "$@" </dev/null >"$LOG" 2>&1
EXIT_CODE=$?
set -e

python3 - "$LOG" "$EXIT_CODE" "$TOOL" <<'PYEOF'
import json, re, sys

log_path, exit_code, tool_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]

with open(log_path, encoding='utf-8', errors='replace') as f:
    text = f.read()
lines = text.splitlines()

errors   = [l.strip() for l in lines if re.search(r'\*[EF],', l)]
warnings = [l.strip() for l in lines if re.search(r'\*W,|\bWARN(?:ING)?\b', l, re.I)]

fail_m = re.search(r'\*[EF],(\w+)', text)

METRICS = ("overall", "block", "expression", "toggle", "fsm", "assertion", "covergroup")
PCT = re.compile(r'(\d+(?:\.\d+)?)\s*%')

metrics = {}
mapping = None

# Form 1: "<metric> ... : N%" on one line.
for line in lines:
    low = line.lower()
    m = re.match(r'\s*(\w+)[^:%]*:\s*(\d+(?:\.\d+)?)\s*%', low)
    if m and m.group(1) in METRICS and m.group(1) not in metrics:
        metrics[m.group(1)] = float(m.group(2))
if metrics:
    mapping = "key_value"

# Form 2: a header row naming two or more metrics, then the first row of percentages.
if not metrics:
    for n, line in enumerate(lines):
        low = line.lower()
        order = sorted(
            (low.find(k), k) for k in METRICS if re.search(r'\b' + k + r'\b', low)
        )
        if len(order) < 2:
            continue
        names = [k for _, k in order]
        for row in lines[n + 1:]:
            pcts = PCT.findall(row)
            if not pcts:
                continue
            if len(pcts) % len(names) == 0:
                stride = len(pcts) // len(names)
                for i, k in enumerate(names):
                    metrics[k] = float(pcts[i * stride])
                mapping = "table" if stride == 1 else f"table_stride_{stride}"
            break
        if metrics:
            break

summary = {
    "tool_path": tool_path,
    "metrics": metrics,
    "column_mapping": mapping,
    "errors": len(errors),
    "warnings": len(warnings),
    "first_error_code": fail_m.group(1) if fail_m else None,
}

evidence = bool(metrics)

if fail_m or exit_code != 0:
    status = "FAIL"
elif not evidence:
    status = "WARN"
    warnings.insert(0, "no recognisable result in tool output (exit 0): no coverage summary on stdout (report -summary without -out?) - not verified; read raw_log")
elif warnings or errors:
    status = "WARN"
else:
    status = "PASS"

print(json.dumps({
    "tool":      "imc",
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
