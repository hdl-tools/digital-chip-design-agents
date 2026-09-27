#!/usr/bin/env bash
# wrap-bambu.sh — run Bambu HLS and emit a compact JSON summary
set -euo pipefail

TOOL="bambu-hls"

if ! command -v "$TOOL" &>/dev/null; then
  _LOG=$(mktemp /tmp/bambu-notfound-XXXXXX.log)
  echo "tool not found: bambu-hls" > "$_LOG"
  python3 - "$_LOG" <<'PYEOF'
import json, sys
log_path = sys.argv[1]
print(json.dumps({"tool":"bambu","exit_code":1,"status":"FAIL","verified":False,"summary":{},"errors":["tool not found: bambu-hls"],"warnings":[],"raw_log":log_path}))
PYEOF
  exit 1
fi

LOG=$(mktemp /tmp/bambu-XXXXXX.log)
START_TS=$(date +%s)
set +e
"$TOOL" "$@" >"$LOG" 2>&1
EXIT_CODE=$?
set -e

python3 - "$LOG" "$EXIT_CODE" "$START_TS" <<'PYEOF'
import json, re, sys, os

log_path        = sys.argv[1]
exit_code       = int(sys.argv[2])
invocation_start = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0

with open(log_path, encoding='utf-8', errors='replace') as f:
    text = f.read()

errors   = [l.strip() for l in text.splitlines() if re.search(r'\bERROR\b', l, re.I)]
warnings = [l.strip() for l in text.splitlines() if re.search(r'\bWARN(?:ING)?\b', l, re.I)]

# Bambu may write an XML report; try to parse it
latency_m = re.search(r'Total latency[^\d]*([\d.]+)\s*cycles?', text, re.I)
dsp_m     = re.search(r'DSP\s+(\d+)', text, re.I)
bram_m    = re.search(r'BRAM\s+(\d+)', text, re.I)

# Also try parsing HLS report XML if present
import xml.etree.ElementTree as ET
import sys as _sys
summary_from_xml = {}
xml_candidates = [f for f in os.listdir('.') if (f.endswith('_results.xml') or 'hls_report' in f)
                  and os.path.getmtime(f) >= invocation_start]
for xf in xml_candidates:
    try:
        tree = ET.parse(xf)
        root = tree.getroot()
        for tag, key in [('Latency', 'latency_cycles'), ('DSPs', 'dsp_count'), ('BRAMs', 'bram_count')]:
            el = root.find('.//' + tag)
            if el is not None and el.text:
                try:
                    summary_from_xml[key] = int(el.text)
                except ValueError:
                    pass
    except Exception as e:
        print(f"[wrap-bambu] warning: could not parse {xf}: {e}", file=_sys.stderr)

summary = {}
if latency_m: summary["latency_cycles"] = float(latency_m.group(1))
if dsp_m:     summary["dsp_count"]      = int(dsp_m.group(1))
if bram_m:    summary["bram_count"]     = int(bram_m.group(1))
# Merge XML-derived values for any metrics not already captured by regex
if "latency_cycles" not in summary and "latency_cycles" in summary_from_xml:
    summary["latency_cycles"] = float(summary_from_xml["latency_cycles"])
if "dsp_count" not in summary and "dsp_count" in summary_from_xml:
    summary["dsp_count"] = int(summary_from_xml["dsp_count"])
if "bram_count" not in summary and "bram_count" in summary_from_xml:
    summary["bram_count"] = int(summary_from_xml["bram_count"])
# PASS needs a result found in the log or the report; exit 0 alone is not one.
evidence = bool(summary)
summary["error_count"]   = len(errors)
summary["warning_count"] = len(warnings)

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
    "tool":      "bambu",
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
