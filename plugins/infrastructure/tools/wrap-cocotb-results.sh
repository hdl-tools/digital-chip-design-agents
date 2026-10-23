#!/usr/bin/env bash
# wrap-cocotb-results.sh — sum one or more cocotb results.xml (JUnit) files into a compact JSON verdict
# Usage: wrap-cocotb-results.sh [--newer-than <file>] <results.xml|dir>...
#
# Runs no tool. cocotb's makefile flow has exited 0 with failing tests on some
# cocotb versions, so the make exit code is not a verdict: this wrapper reads the
# results.xml cocotb writes and counts testcases, failures, errors and skips.
#   - a directory argument is searched recursively for results.xml
#   - a missing, empty or unparsable results.xml is a FAIL, never a skip
#   - zero testcases across all inputs is a FAIL: nothing was checked
#   - every testcase skipped is a WARN with verified=false: nothing ran
#   - --newer-than <file>: a results.xml older than <file> is stale (left by an
#     earlier run that this run never overwrote, e.g. after a compile failure)
#     and is a FAIL
set -euo pipefail

if [[ $# -lt 1 ]]; then
  python3 - <<'PYEOF'
import json
print(json.dumps({"tool":"cocotb-results","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["no input: usage: wrap-cocotb-results.sh [--newer-than <file>] <results.xml|dir>..."],"warnings":[],"raw_log":""}))
PYEOF
  exit 1
fi

if [[ "$1" == "--version" || "$1" == "--help" || "$1" == "-h" ]]; then
  python3 - <<'PYEOF'
import json
print(json.dumps({"tool":"cocotb-results","exit_code":0,"status":"WARN","verified":False,"summary":{},"errors":[],"warnings":["no results read - not verified: usage: wrap-cocotb-results.sh [--newer-than <file>] <results.xml|dir>..."],"raw_log":""}))
PYEOF
  exit 0
fi

LOG=$(mktemp /tmp/cocotb-results-XXXXXX.log)
set +e
python3 - "$LOG" "$@" <<'PYEOF'
import json, os, sys
import xml.etree.ElementTree as ET

log_path = sys.argv[1]
args = sys.argv[2:]

newer_than = None
inputs = []
errors = []
i = 0
while i < len(args):
    if args[i] == "--newer-than":
        if i + 1 >= len(args):
            errors.append("--newer-than needs a reference file")
            i += 1
            continue
        newer_than = args[i + 1]
        i += 2
        continue
    inputs.append(args[i])
    i += 1

ref_mtime = None
if newer_than is not None:
    try:
        ref_mtime = os.path.getmtime(newer_than)
    except OSError:
        errors.append(f"--newer-than reference not found: {newer_than}")

files = []
for item in inputs:
    if os.path.isdir(item):
        found = sorted(
            os.path.join(root, name)
            for root, _, names in os.walk(item)
            for name in names if name == "results.xml"
        )
        if not found:
            errors.append(f"no results.xml under directory: {item}")
        files.extend(found)
    else:
        files.append(item)

totals = {"files": 0, "tests": 0, "passed": 0, "failures": 0, "errors": 0, "skipped": 0}
failed_names, errored_names, skipped_names = [], [], []
per_file = []

for path in files:
    if not os.path.isfile(path):
        errors.append(f"results file not found: {path}")
        continue
    if os.path.getsize(path) == 0:
        errors.append(f"results file is empty: {path}")
        continue
    if ref_mtime is not None and os.path.getmtime(path) < ref_mtime:
        errors.append(f"stale results file (older than {newer_than}): {path}")
        continue
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        errors.append(f"unparsable results file: {path}: {exc}")
        continue
    totals["files"] += 1
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for case in root.iter("testcase"):
        name = case.get("classname", "") + "." + case.get("name", "")
        counts["tests"] += 1
        if case.find("failure") is not None:
            counts["failures"] += 1
            failed_names.append(name)
        elif case.find("error") is not None:
            counts["errors"] += 1
            errored_names.append(name)
        elif case.find("skipped") is not None:
            counts["skipped"] += 1
            skipped_names.append(name)
    for key, value in counts.items():
        totals[key] += value
    per_file.append({"file": os.path.abspath(path), **counts})

totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]

warnings = []
for name in failed_names:
    errors.append(f"FAILED: {name}")
for name in errored_names:
    errors.append(f"ERROR: {name}")

if errors or totals["failures"] or totals["errors"]:
    status = "FAIL"
    evidence = True
elif totals["tests"] == 0:
    status = "FAIL"
    evidence = True
    errors.append("no testcase found in any results.xml - nothing was checked")
elif totals["skipped"] == totals["tests"]:
    status = "WARN"
    evidence = False
    warnings.append("no recognisable result in tool output (every testcase skipped) - not verified")
else:
    status = "PASS"
    evidence = True

with open(log_path, "w", encoding="utf-8") as f:
    json.dump({"per_file": per_file, "failed": failed_names, "errored": errored_names,
               "skipped": skipped_names}, f, indent=2)

summary = dict(totals)
summary["skipped_tests"] = skipped_names[:50]

print(json.dumps({
    "tool":      "cocotb-results",
    "exit_code": 1 if status == "FAIL" else 0,
    "status":    status,
    "verified":  evidence,
    "summary":   summary,
    "errors":    errors[:10],
    "warnings":  warnings[:10],
    "raw_log":   log_path
}, indent=2))
sys.exit(1 if status == "FAIL" else 0)
PYEOF
EXIT_CODE=$?
set -e

exit $EXIT_CODE
