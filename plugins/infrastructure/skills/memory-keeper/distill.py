#!/usr/bin/env python3
"""
distill.py — Memory-Keeper helper: parse experiences.jsonl and emit a
structured distillation summary for a chip-design domain.

Usage:
    python3 distill.py <domain> [--min-records N] [--memory-root PATH]

Outputs a JSON object to stdout that the memory-keeper agent uses to
decide what new entries to add to knowledge.md.  Exits with code 2 when
the record count is below the threshold (agent should skip).

Exit codes:
    0  — summary emitted; enough records
    1  — unexpected error
    2  — skipped; fewer than --min-records records
"""

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

# Resolve the memory root via the shared single-source-of-truth resolver that
# lives alongside this script, so writers and readers agree on the location.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_root import resolve_memory_root  # noqa: E402

VALID_DOMAINS = [
    "architecture",
    "compiler",
    "dft",
    "firmware",
    "formal",
    "fpga",
    "hls",
    "infrastructure",
    "memory-ip",
    "pd",
    "rtl-design",
    "soc",
    "sta",
    "synthesis",
    "verification",
]

# Numeric key_metrics fields per domain (used for range computation)
METRIC_FIELDS = {
    "architecture": ["estimated_mhz", "estimated_area_um2"],
    "compiler": ["regression_pass_rate"],
    "dft": ["scan_coverage_pct", "atpg_fault_coverage_pct"],
    "firmware": ["flash_size_kb"],
    "formal": ["proved", "failed", "unknown"],
    "fpga": ["lut_count", "fmax_mhz"],
    "hls": ["latency_cycles", "dsp_count"],
    "infrastructure": ["tools_detected", "tools_missing", "wrappers_deployed", "mcp_servers_configured"],
    "memory-ip": ["memory_instances", "total_memory_area_um2", "worst_access_time_ns", "view_qa_errors", "projected_repair_yield_pct"],
    "pd": ["wns_ns", "hold_wns_ns", "tns_ns", "drc_violations", "lvs_errors", "gds_area_um2",
           "power_mw", "util_pct", "wirelength_um", "runtime_s", "peak_rss_gb"],
    "rtl-design": ["lint_errors", "cdc_violations"],
    "soc": ["ip_blocks_integrated", "memory_map_conflicts"],
    "sta": ["setup_wns_ns", "hold_wns_ns", "tns_ns", "failing_paths", "power_mw", "runtime_s",
            "peak_rss_gb"],
    "synthesis": ["wns_ns", "tns_ns", "cells", "area_um2", "lec_unmatched", "power_mw", "runtime_s",
                  "peak_rss_gb"],
    "verification": ["functional_coverage_pct", "regression_failures", "assertions_triggered"],
}


def load_records(jsonl_path: Path) -> list[dict]:
    records = []
    malformed = 0
    if not jsonl_path.exists():
        return records
    with jsonl_path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                malformed += 1
                print(f"  [warn] malformed JSON on line {lineno}, skipping", file=sys.stderr)
                continue
            if not isinstance(obj, dict):
                malformed += 1
                print(f"  [warn] line {lineno} is valid JSON but not an object, skipping", file=sys.stderr)
                continue
            records.append(obj)
    if malformed:
        print(f"  [warn] {malformed} malformed line(s) ignored", file=sys.stderr)
    return records


def compute_metric_ranges(records: list[dict], domain: str) -> dict:
    fields = METRIC_FIELDS.get(domain, [])
    ranges = {}
    for field in fields:
        values = []
        for rec in records:
            km = rec.get("key_metrics", {}) or {}
            v = km.get(field)
            if isinstance(v, (int, float)):
                values.append(v)
        if not values:
            continue
        ranges[field] = {
            "min": min(values),
            "max": max(values),
            "median": statistics.median(values),
            "latest": values[-1],
            "count": len(values),
        }
    return ranges


def extract_issue_fix_pairs(records: list[dict]) -> list[dict]:
    """
    Build a frequency table of (issue, fix) pairs across all records.
    Issues and fixes are matched positionally where both lists are non-empty
    and same length; otherwise issues and fixes are paired with None.
    """
    pair_counter: Counter = Counter()

    for rec in records:
        issues = rec.get("issues_encountered") or []
        fixes = rec.get("fixes_applied") or []
        if issues and fixes and len(issues) == len(fixes):
            for iss, fix in zip(issues, fixes):
                pair_counter[(iss.strip(), fix.strip())] += 1
        else:
            for iss in issues:
                pair_counter[(iss.strip(), None)] += 1
            for fix in fixes:
                pair_counter[(None, fix.strip())] += 1

    result = []
    for (issue, fix), count in pair_counter.most_common():
        result.append({"issue": issue, "fix": fix, "count": count})
    return result


def extract_tool_flag_candidates(records: list[dict]) -> list[str]:
    """
    Scan notes and fixes_applied for lines that look like tool flags or commands:
    lines containing ' -', ' --', or backtick-quoted text.
    """
    import re
    # Match backtick-quoted tokens OR flags preceded by whitespace, start-of-string,
    # or start-of-line (re.MULTILINE makes ^ match after each newline).
    flag_pattern = re.compile(r"(`[^`]+`|(?:(?:^|\s))(--?\w[\w\-]*))", re.MULTILINE)
    seen = set()
    candidates = []
    for rec in records:
        sources = list(rec.get("fixes_applied") or []) + [rec.get("notes") or ""]
        for text in sources:
            for match in flag_pattern.finditer(text):
                token = match.group(0).strip("`").strip()
                if token and token not in seen:
                    seen.add(token)
                    candidates.append(token)
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Distil experiences.jsonl for a domain")
    parser.add_argument("domain", choices=VALID_DOMAINS, help="Domain name")
    parser.add_argument(
        "--min-records",
        type=int,
        default=5,
        metavar="N",
        help="Minimum record count required (default: 5)",
    )
    parser.add_argument(
        "--memory-root",
        default=None,
        metavar="PATH",
        help="Path to the memory/ directory (default: auto-detect from script location)",
    )
    args = parser.parse_args()

    # Resolve memory root: --memory-root > $CHIP_DESIGN_MEMORY_ROOT > central
    # XDG default > in-repo seed (see memory_root.resolve_memory_root).
    memory_root = resolve_memory_root(args.memory_root)

    jsonl_path = memory_root / args.domain / "experiences.jsonl"

    records = load_records(jsonl_path)
    n = len(records)

    if n < args.min_records:
        print(
            json.dumps({
                "skipped": True,
                "domain": args.domain,
                "record_count": n,
                "min_records": args.min_records,
                "reason": f"Only {n} record(s); threshold is {args.min_records}",
            }),
            flush=True,
        )
        sys.exit(2)

    timestamps = sorted(
        r["timestamp"] for r in records if isinstance(r.get("timestamp"), str)
    )
    signoff_count = sum(1 for r in records if r.get("signoff_achieved") is True)

    summary = {
        "skipped": False,
        "domain": args.domain,
        "record_count": n,
        "date_range": [timestamps[0] if timestamps else None, timestamps[-1] if timestamps else None],
        "signoff_rate": round(signoff_count / n, 3) if n else 0.0,
        "issue_fix_pairs": extract_issue_fix_pairs(records),
        "tool_flag_candidates": extract_tool_flag_candidates(records),
        "metric_ranges": compute_metric_ranges(records, args.domain),
        "free_notes": [
            r["notes"] for r in records if r.get("notes") and isinstance(r["notes"], str)
        ],
    }

    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
