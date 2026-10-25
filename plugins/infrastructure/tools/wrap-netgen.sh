#!/usr/bin/env bash
# wrap-netgen.sh — run Netgen LVS and emit a compact JSON summary
# Usage: wrap-netgen.sh [netgen args...]     e.g. wrap-netgen.sh -batch lvs "a.spice top" "b.v top" setup.tcl comp.out
#
# Verdict: "Circuits match uniquely." / "Circuits match correctly." pass; "Netlists do not
# match." fails; "Property errors were found." or "port errors" make a match a verified
# WARN. netgen writes the full LVS report to the output file (the argument four places
# after `lvs`), so that file is read too when this run wrote it. Not installed on the
# reference host (it runs in the LibreLane container); strings from netgen's
# documented output, UNMEASURED here.
#
# Contract (identical to every wrapper here): FAIL on a non-zero exit, an error line,
# a tool-specific fail marker, or a missing tool; WARN with verified=false when the
# tool exits 0 without a result this wrapper recognises; WARN (verified) when a result
# is present together with warnings; PASS only on a recognised result and no warnings.
# stdin is /dev/null, so a vendor shell that is accidentally left interactive reaches
# EOF and exits instead of hanging; with no arguments the tool is not started at all.
set -euo pipefail

TOOL="netgen"

if ! command -v "$TOOL" &>/dev/null; then
  python3 - "$TOOL" <<'PYEOF'
import json, sys
print(json.dumps({"tool":"netgen","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["tool not found: " + sys.argv[1] + " (Netgen LVS)"],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

# The deploy-time smoke test calls --version/--help. Answer it here instead of starting
# the vendor shell, which checks out a licence and can take minutes to print a version.
if [[ $# -eq 1 && ( "$1" == "--version" || "$1" == "--help" || "$1" == "-h" ) ]]; then
  python3 - "$TOOL" <<'PYEOF'
import json, shutil, sys
print(json.dumps({"tool":"netgen","exit_code":0,"status":"WARN","verified":False,"summary":{"tool_path":shutil.which(sys.argv[1])},"errors":[],"warnings":["usage: wrap-netgen.sh [netgen args...] - answered by the wrapper; netgen was found but not started (no licence checked out)"],"raw_log":""}))
PYEOF
  exit 0
fi

LOG=$(mktemp /tmp/netgen-XXXXXX.log)
STAMP=$(mktemp /tmp/netgen-stamp-XXXXXX)
if [[ $# -eq 0 ]]; then
  echo "error: no arguments provided; netgen needs a script or command file (interactive mode not supported)" >"$LOG"
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

report = None
if "lvs" in args:
    i = args.index("lvs") + 4
    if i < len(args) and fresh(args[i]):
        report = args[i]
        with open(report, encoding='utf-8', errors='replace') as f:
            text = text + "\n" + f.read()
summary["report_file"] = os.path.abspath(report) if report else None
match = re.search(r'Circuits match (uniquely|correctly)', text)
nomatch = re.search(r'Netlists do not match', text)
if nomatch:
    fail_markers.append("Netlists do not match")
    summary["verdict"] = "mismatch"
elif match:
    summary["verdict"] = "match"
if re.search(r'Property errors were found', text):
    result_warnings.append("Property errors were found")
if re.search(r'port errors', text, re.I):
    result_warnings.append("netlists match with port errors")
evidence = bool(match or nomatch)

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
    "tool":      "netgen",
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
