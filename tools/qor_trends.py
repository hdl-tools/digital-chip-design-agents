#!/usr/bin/env python3
"""
qor_trends.py — Cross-design QoR metric trending for digital chip design agents.

Reads memory/<domain>/experiences.jsonl files and produces a QoR trend table
(and optional matplotlib chart) for a named design across runs.

Usage:
    python3 tools/qor_trends.py --design <name> [options]

Options:
    --design  NAME                  Design name to filter (required)
    --domain  DOMAIN                Limit to one domain (default: all domains)
    --metric  FIELD                 Specific metric field to plot (default: all numeric)
    --pdk     VALUE                 Filter to records with matching pdk (case-insensitive)
    --tool    VALUE                 Filter to records with matching tool_used (case-insensitive)
    --group-by {pdk,tool,pdk+tool}  Group series by dimension for side-by-side comparison
    --plot                          Emit a matplotlib chart (requires matplotlib)
    --output  FILE                  Save chart to FILE instead of displaying (implies --plot)
    --memory-root PATH              Path to the memory/ directory (default: auto-detect)
    --min-runs N                    Minimum runs required to include a series (default: 2)

Examples:
    # Print trend table for all domains where design "aes_core" appears
    python3 tools/qor_trends.py --design aes_core

    # Show WNS trend for synthesis domain only
    python3 tools/qor_trends.py --design aes_core --domain synthesis --metric wns_ns

    # Save a chart of all metrics to a file
    python3 tools/qor_trends.py --design aes_core --plot --output aes_core_qor.png

    # Compare area/timing across sky130 vs gf180mcu
    python3 tools/qor_trends.py --design aes_core --domain synthesis --group-by pdk

    # Compare Yosys vs DC on sky130, with a grouped chart
    python3 tools/qor_trends.py --design aes_core --pdk sky130 --group-by tool --plot

Exit codes:
    0  — table/chart produced
    1  — no matching runs found for the given design
    2  — unexpected error
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

VALID_DOMAINS = [
    "architecture",
    "compiler",
    "dft",
    "firmware",
    "formal",
    "fpga",
    "hls",
    "memory-ip",
    "pd",
    "rtl-design",
    "soc",
    "sta",
    "synthesis",
    "verification",
]

VALID_GROUP_BY = ["pdk", "tool", "pdk+tool"]

# Sentinel used when --group-by is not set (legacy single-series mode)
_ALL_KEY = "__all__"

# Numeric metric fields per domain
NUMERIC_METRICS: dict[str, list[str]] = {
    "architecture": ["estimated_mhz", "estimated_area_um2"],
    "compiler": ["regression_pass_rate"],
    "dft": ["scan_coverage_pct", "atpg_fault_coverage_pct"],
    "firmware": ["flash_size_kb"],
    "formal": ["proved", "failed", "unknown"],
    "fpga": ["lut_count", "fmax_mhz"],
    "hls": ["latency_cycles", "dsp_count"],
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

# Metrics where higher is better (used for regression detection).
# Timing-slack metrics (wns_ns, tns_ns, etc.) are negative when violating and
# approach 0 as they improve, so higher (less negative) is better.
HIGHER_IS_BETTER = {
    "estimated_mhz", "fmax_mhz", "isa_tests_passed", "regression_pass_rate",
    "scan_coverage_pct", "atpg_fault_coverage_pct", "bsp_tests_passed",
    "proved", "ip_blocks_integrated", "functional_coverage_pct",
    "ii_achieved", "timing_met", "abi_compliant", "simulation_pass",
    "synth_check_pass", "build_pass", "projected_repair_yield_pct",
    # Timing slack: 0 = clean, negative = violation; closer to 0 is better
    "wns_ns", "setup_wns_ns", "hold_wns_ns", "tns_ns",
}


def find_memory_root(script_path: Path) -> Path:
    """Walk up from script location to find the memory/ directory."""
    candidate = script_path.resolve().parent
    for _ in range(5):
        mem = candidate / "memory"
        if mem.is_dir():
            return mem
        candidate = candidate.parent
    raise FileNotFoundError(
        "Could not locate memory/ directory. Use --memory-root to specify it explicitly."
    )


def resolve_memory_root(explicit: str | None) -> Path:
    """Resolve the memory root via the shared single-source-of-truth resolver
    (plugins/infrastructure/skills/memory-keeper/memory_root.py), so this reader
    agrees with the orchestrator writers: --memory-root > $CHIP_DESIGN_MEMORY_ROOT
    > central XDG default > in-repo seed. Falls back to walking up from this
    script if the resolver module cannot be located."""
    resolver = (Path(__file__).resolve().parents[1]
                / "plugins/infrastructure/skills/memory-keeper/memory_root.py")
    if resolver.is_file():
        import importlib.util
        spec = importlib.util.spec_from_file_location("memory_root", resolver)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.resolve_memory_root(explicit)
    return Path(explicit) if explicit else find_memory_root(Path(__file__))


def load_domain_records(memory_root: Path, domain: str) -> list[dict]:
    jsonl = memory_root / domain / "experiences.jsonl"
    if not jsonl.exists():
        return []
    records: list[dict] = []
    with jsonl.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                print(f"  [warn] {domain}: malformed JSON on line {lineno}, skipping", file=sys.stderr)
                continue
            if not isinstance(obj, dict):
                print(f"  [warn] {domain}: line {lineno} is valid JSON but not an object, skipping", file=sys.stderr)
                continue
            records.append(obj)
    return records


def filter_by_design(records: list[dict], design_name: str) -> list[dict]:
    name_lower = design_name.lower()
    return [
        r for r in records
        if isinstance(r.get("design_name"), str)
        and r["design_name"].lower() == name_lower
    ]


def filter_by_pdk(records: list[dict], pdk: str) -> list[dict]:
    pdk_lower = pdk.lower()
    return [
        r for r in records
        if isinstance(r.get("pdk"), str) and r["pdk"].lower() == pdk_lower
    ]


def filter_by_tool(records: list[dict], tool: str) -> list[dict]:
    tool_lower = tool.lower()
    return [
        r for r in records
        if isinstance(r.get("tool_used"), str) and r["tool_used"].lower() == tool_lower
    ]


def _group_key_for(rec: dict, group_by: str | None) -> str:
    """Return the group label for a record given the active grouping dimension."""
    if not group_by:
        return _ALL_KEY
    if group_by == "pdk":
        return rec.get("pdk") or "(none)"
    if group_by == "tool":
        return rec.get("tool_used") or "(none)"
    # pdk+tool
    pdk = rec.get("pdk") or "(none)"
    tool = rec.get("tool_used") or "(none)"
    return f"{pdk}|{tool}"


# metric → group_key → [(timestamp, value), ...]
SeriesMap = dict[str, dict[str, list[tuple[str, float]]]]


def extract_series(
    records: list[dict],
    domain: str,
    metric_filter: str | None,
    group_by: str | None,
) -> SeriesMap:
    """
    Returns {metric: {group_key: [(ts, value), ...]}} sorted by timestamp.
    When group_by is None, a single _ALL_KEY group is used (legacy flat behaviour).
    """
    fields = NUMERIC_METRICS.get(domain, [])
    if metric_filter:
        fields = [f for f in fields if f == metric_filter]

    series: dict[str, dict[str, list[tuple[str, float]]]] = defaultdict(lambda: defaultdict(list))
    for rec in records:
        ts = rec.get("timestamp", "")
        km = rec.get("key_metrics") or {}
        gk = _group_key_for(rec, group_by)
        for field in fields:
            val = km.get(field)
            if isinstance(val, (int, float)):
                series[field][gk].append((ts, float(val)))

    result: SeriesMap = {}
    for field, groups in series.items():
        result[field] = {gk: sorted(pts, key=lambda x: x[0]) for gk, pts in groups.items()}
    return result


def detect_regression(field: str, values: list[float]) -> str | None:
    """
    Return a warning string if the last value is worse than the previous,
    otherwise None.
    """
    if len(values) < 2:
        return None
    prev, last = values[-2], values[-1]
    if field in HIGHER_IS_BETTER:
        if last < prev:
            return f"REGRESSION: {prev:.3g} -> {last:.3g} (lower is worse)"
    else:
        if last > prev:
            return f"REGRESSION: {prev:.3g} -> {last:.3g} (higher is worse)"
    return None


def print_table(
    design: str,
    domain_series: dict[str, SeriesMap],
    min_runs: int,
    group_by: str | None,
) -> int:
    """Print the QoR trend table. Returns number of rows printed."""
    rows = 0
    for domain, series in sorted(domain_series.items()):
        if not series:
            continue

        run_count = max(
            len(pts)
            for groups in series.values()
            for pts in groups.values()
        ) if series else 0

        if group_by:
            any_qualifies = any(
                len(pts) >= min_runs
                for groups in series.values()
                for pts in groups.values()
            )
            if not any_qualifies:
                continue
        else:
            if run_count < min_runs:
                continue

        print(f"\n{'='*72}")
        print(f"Domain: {domain}  |  Design: {design}  |  Runs: {run_count}")
        print(f"{'='*72}")

        if group_by:
            print(f"  {'Group':<20} {'Metric':<28} {'Min':>8} {'Max':>8} {'Latest':>8}  Alert")
            print(f"  {'-'*20} {'-'*28} {'-'*8} {'-'*8} {'-'*8}  -----")
            for field, groups in sorted(series.items()):
                for gk, points in sorted(groups.items()):
                    if len(points) < min_runs:
                        continue
                    values = [v for _, v in points]
                    if not values:
                        continue
                    alert = detect_regression(field, values) or ""
                    print(
                        f"  {gk:<20} {field:<28} {min(values):>8.4g} {max(values):>8.4g} "
                        f"{values[-1]:>8.4g}  {alert}"
                    )
                    rows += 1
        else:
            print(f"  {'Metric':<35} {'Min':>10} {'Max':>10} {'Latest':>10}  Alert")
            print(f"  {'-'*35} {'-'*10} {'-'*10} {'-'*10}  -----")
            for field, groups in sorted(series.items()):
                points = groups.get(_ALL_KEY, [])
                values = [v for _, v in points]
                if not values:
                    continue
                alert = detect_regression(field, values) or ""
                print(
                    f"  {field:<35} {min(values):>10.4g} {max(values):>10.4g} "
                    f"{values[-1]:>10.4g}  {alert}"
                )
                rows += 1

    return rows


def plot_chart(
    design: str,
    domain_series: dict[str, SeriesMap],
    min_runs: int,
    output_file: str | None,
    group_by: str | None,
) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print(
            "[error] matplotlib is not installed. Install it with:\n"
            "  pip install matplotlib\n"
            "Or run without --plot for a text-only table.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Collect all (domain, field, qualifying_groups) with enough data
    plots: list[tuple[str, str, dict[str, list[tuple[str, float]]]]] = []
    for domain, series in sorted(domain_series.items()):
        for field, groups in sorted(series.items()):
            qualifying = {gk: pts for gk, pts in groups.items() if len(pts) >= min_runs}
            if qualifying:
                plots.append((domain, field, qualifying))

    if not plots:
        print("[warn] No series with enough runs to plot.", file=sys.stderr)
        return

    colors = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    ]

    ncols = 2
    nrows = (len(plots) + 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 4 * nrows), squeeze=False)
    fig.suptitle(f"QoR Trends — Design: {design}", fontsize=14, fontweight="bold")

    for idx, (domain, field, groups) in enumerate(plots):
        ax = axes[idx // ncols][idx % ncols]
        has_regression = False
        all_group_keys = sorted(groups.keys())

        for g_idx, gk in enumerate(all_group_keys):
            points = groups[gk]
            xs = list(range(1, len(points) + 1))
            ys = [v for _, v in points]
            color = colors[g_idx % len(colors)]
            label = gk if group_by else None
            ax.plot(xs, ys, marker="o", linewidth=1.5, color=color, label=label)

            if len(ys) >= 2 and detect_regression(field, ys):
                ax.axvline(x=xs[-1], color="red", linestyle=":", linewidth=1.2)
                has_regression = True

        # X-axis ticks: use neutral run indices when grouped (not timestamps from one group)
        if len(groups) > 1 or group_by:
            max_runs = max(len(groups[k]) for k in all_group_keys)
            xs_ref = list(range(1, max_runs + 1))
            labels = [str(i) for i in xs_ref]
        else:
            first_pts = groups[all_group_keys[0]]
            xs_ref = list(range(1, len(first_pts) + 1))
            labels = [ts[:10] if ts else str(i) for i, (ts, _) in enumerate(first_pts, 1)]
        ax.set_xticks(xs_ref)
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)

        title = f"{domain} / {field}" + ("  ⚠" if has_regression else "")
        ax.set_title(title, fontsize=9, color="red" if has_regression else "black")
        ax.set_xlabel("Run #")
        ax.set_ylabel(field)
        ax.grid(True, linestyle="--", alpha=0.5)
        if group_by:
            ax.legend(fontsize=7, loc="best")

    for idx in range(len(plots), nrows * ncols):
        axes[idx // ncols][idx % ncols].set_visible(False)

    plt.tight_layout()

    if output_file:
        plt.savefig(output_file, dpi=150, bbox_inches="tight")
        print(f"Chart saved to: {output_file}")
    else:
        plt.show()


def _distinct_values(records: list[dict], field: str) -> list[str]:
    """Return unique non-null string values for a top-level field across records."""
    seen: set[str] = set()
    result: list[str] = []
    for r in records:
        v = r.get(field)
        if isinstance(v, str) and v not in seen:
            seen.add(v)
            result.append(v)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="QoR metric trending across chip-design orchestrator runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--design", required=True, metavar="NAME", help="Design name to filter")
    parser.add_argument(
        "--domain",
        metavar="DOMAIN",
        choices=VALID_DOMAINS,
        default=None,
        help="Limit to one domain (default: all)",
    )
    parser.add_argument(
        "--metric",
        metavar="FIELD",
        default=None,
        help="Specific metric field to show (default: all numeric fields)",
    )
    parser.add_argument(
        "--pdk",
        metavar="VALUE",
        default=None,
        help="Filter to records with matching pdk (case-insensitive)",
    )
    parser.add_argument(
        "--tool",
        metavar="VALUE",
        default=None,
        help="Filter to records with matching tool_used (case-insensitive)",
    )
    parser.add_argument(
        "--group-by",
        metavar="DIM",
        choices=VALID_GROUP_BY,
        default=None,
        help="Group series by dimension: pdk, tool, or pdk+tool",
    )
    parser.add_argument("--plot", action="store_true", help="Show matplotlib chart")
    parser.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Save chart to FILE instead of displaying (implies --plot)",
    )
    parser.add_argument(
        "--memory-root",
        metavar="PATH",
        default=None,
        help="Path to the memory/ directory",
    )
    parser.add_argument(
        "--min-runs",
        type=int,
        default=2,
        metavar="N",
        help="Minimum runs required to include a series (default: 2)",
    )
    args = parser.parse_args()

    try:
        memory_root = resolve_memory_root(args.memory_root)
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(2)

    if not memory_root.is_dir():
        print(f"[error] memory root not found: {memory_root}", file=sys.stderr)
        sys.exit(2)

    domains = [args.domain] if args.domain else VALID_DOMAINS
    group_by: str | None = args.group_by

    domain_series: dict[str, SeriesMap] = {}
    total_runs = 0
    all_design_records: list[dict] = []  # for helpful filter-miss error messages

    for domain in domains:
        all_records = load_domain_records(memory_root, domain)
        design_records = filter_by_design(all_records, args.design)
        if not design_records:
            continue
        all_design_records.extend(design_records)

        filtered = design_records
        if args.pdk:
            filtered = filter_by_pdk(filtered, args.pdk)
        if args.tool:
            filtered = filter_by_tool(filtered, args.tool)
        if not filtered:
            continue

        series = extract_series(filtered, domain, args.metric, group_by)
        if series:
            domain_series[domain] = series
            total_runs += len(filtered)

    if not domain_series:
        if not all_design_records:
            print(
                f"No runs found for design '{args.design}'"
                + (f" in domain '{args.domain}'" if args.domain else "")
                + ".\n"
                "Check that the design name matches exactly what orchestrators recorded\n"
                "in memory/<domain>/experiences.jsonl (field: 'design_name').",
                file=sys.stderr,
            )
        else:
            hints: list[str] = []
            if args.pdk:
                avail = _distinct_values(all_design_records, "pdk")
                hints.append(
                    f"  Available pdks for design '{args.design}': "
                    + (", ".join(avail) if avail else "(none)")
                )
            if args.tool:
                avail = _distinct_values(all_design_records, "tool_used")
                hints.append(
                    f"  Available tools for design '{args.design}': "
                    + (", ".join(avail) if avail else "(none)")
                )
            print(
                f"No runs found for design '{args.design}' after applying filters.\n"
                + "\n".join(hints),
                file=sys.stderr,
            )
        sys.exit(1)

    print("\nQoR Trend Report")
    print(f"Design:      {args.design}")
    print(f"Total runs:  {total_runs}")
    print(f"Domains:     {', '.join(sorted(domain_series))}")
    if args.pdk:
        print(f"PDK filter:  {args.pdk}")
    if args.tool:
        print(f"Tool filter: {args.tool}")
    if group_by:
        print(f"Group by:    {group_by}")
    if args.metric:
        print(f"Metric filter: {args.metric}")

    rows = print_table(args.design, domain_series, args.min_runs, group_by)

    if rows == 0:
        print(
            f"\n[info] No series met the --min-runs={args.min_runs} threshold. "
            "Try --min-runs 1 to see single-run data."
        )

    if args.output or args.plot:
        plot_chart(args.design, domain_series, args.min_runs, args.output, group_by)


if __name__ == "__main__":
    main()
