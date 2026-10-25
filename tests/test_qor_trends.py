"""Unit tests for tools/qor_trends.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

QOR = Path(__file__).resolve().parents[1] / "tools/qor_trends.py"


def test_valid_domains_have_numeric_metrics(qor_trends):
    # Every trending domain must declare a numeric-metric list.
    for dom in qor_trends.VALID_DOMAINS:
        assert dom in qor_trends.NUMERIC_METRICS, f"{dom} missing from NUMERIC_METRICS"


def test_filter_by_design_is_case_insensitive(qor_trends):
    recs = [{"design_name": "AES_Core"}, {"design_name": "other"}, {"foo": 1}]
    assert qor_trends.filter_by_design(recs, "aes_core") == [{"design_name": "AES_Core"}]


def test_filter_by_pdk_and_tool(qor_trends):
    recs = [
        {"pdk": "sky130", "tool_used": "yosys"},
        {"pdk": "gf180mcu", "tool_used": "yosys"},
        {"pdk": "sky130", "tool_used": "dc"},
    ]
    assert qor_trends.filter_by_pdk(recs, "SKY130") == [recs[0], recs[2]]
    assert qor_trends.filter_by_tool(recs, "DC") == [recs[2]]


def test_load_domain_records_skips_malformed(qor_trends, tmp_path):
    mem = tmp_path / "memory"
    d = mem / "synthesis"
    d.mkdir(parents=True)
    (d / "experiences.jsonl").write_text(
        '{"a": 1}\n'
        "\n"                       # blank line ignored
        "not json\n"               # malformed -> skipped
        "[1, 2, 3]\n"              # valid JSON but not an object -> skipped
        '{"b": 2}\n')
    assert qor_trends.load_domain_records(mem, "synthesis") == [{"a": 1}, {"b": 2}]


def test_load_domain_records_missing_returns_empty(qor_trends, tmp_path):
    assert qor_trends.load_domain_records(tmp_path / "memory", "synthesis") == []


def test_extract_series_filters_metric_and_sorts(qor_trends):
    records = [
        {"timestamp": "2026-01-02T00:00:00Z", "key_metrics": {"wns_ns": -0.2, "cells": 100}},
        {"timestamp": "2026-01-01T00:00:00Z", "key_metrics": {"wns_ns": -0.4}},
    ]
    series = qor_trends.extract_series(records, "synthesis", "wns_ns", None)
    pts = series["wns_ns"][qor_trends._ALL_KEY]
    # Sorted by timestamp ascending; only the requested metric is present.
    assert [v for _, v in pts] == [-0.4, -0.2]
    assert "cells" not in series


def test_extract_series_groups_by_pdk(qor_trends):
    records = [
        {"timestamp": "2026-01-01T00:00:00Z", "pdk": "sky130", "key_metrics": {"wns_ns": 0.1}},
        {"timestamp": "2026-01-02T00:00:00Z", "pdk": "gf180mcu", "key_metrics": {"wns_ns": 0.2}},
    ]
    series = qor_trends.extract_series(records, "synthesis", "wns_ns", "pdk")
    assert set(series["wns_ns"].keys()) == {"sky130", "gf180mcu"}


def test_detect_regression_higher_is_better(qor_trends):
    # wns_ns is higher-is-better (closer to 0 is better); a drop is a regression.
    assert qor_trends.detect_regression("wns_ns", [-0.1, -0.5]) is not None
    assert qor_trends.detect_regression("wns_ns", [-0.5, -0.1]) is None


def test_detect_regression_lower_is_better(qor_trends):
    # drc_violations: lower is better; a rise is a regression.
    assert qor_trends.detect_regression("drc_violations", [0, 3]) is not None
    assert qor_trends.detect_regression("drc_violations", [3, 0]) is None


def test_detect_regression_needs_two_points(qor_trends):
    assert qor_trends.detect_regression("wns_ns", [-0.5]) is None
    assert qor_trends.detect_regression("wns_ns", []) is None


def test_group_key_for(qor_trends):
    rec = {"pdk": "sky130", "tool_used": "yosys"}
    assert qor_trends._group_key_for(rec, None) == qor_trends._ALL_KEY
    assert qor_trends._group_key_for(rec, "pdk") == "sky130"
    assert qor_trends._group_key_for(rec, "tool") == "yosys"
    assert qor_trends._group_key_for(rec, "pdk+tool") == "sky130|yosys"
    assert qor_trends._group_key_for({}, "pdk") == "(none)"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(QOR), *args], capture_output=True, text=True)


def test_main_design_not_found_exits_1(tmp_path):
    (tmp_path / "memory").mkdir()
    res = _run("--design", "nope", "--memory-root", str(tmp_path / "memory"))
    assert res.returncode == 1


def test_main_missing_memory_root_exits_2(tmp_path):
    res = _run("--design", "x", "--memory-root", str(tmp_path / "nope"))
    assert res.returncode == 2


def test_main_reports_trend_and_regression(tmp_path, fixtures_dir):
    # The committed fixture loads, trends, and surfaces a regression in the table.
    mem = tmp_path / "memory"
    (mem / "synthesis").mkdir(parents=True)
    (mem / "synthesis" / "experiences.jsonl").write_text(
        (fixtures_dir / "sample_experiences.jsonl").read_text())
    res = _run("--design", "demo_cpu", "--memory-root", str(mem))
    assert res.returncode == 0, res.stderr
    # wns_ns trends 0.05 -> -0.02 -> -0.35 (higher-is-better): a regression.
    assert "REGRESSION" in res.stdout


def test_pd_sta_synthesis_trend_power_runtime_and_memory(qor_trends):
    """A tool-vs-tool comparison reads power, runtime and peak memory per flow; a field
    missing from NUMERIC_METRICS is silently dropped from every trend."""
    for dom in ("pd", "sta", "synthesis"):
        for field in ("power_mw", "runtime_s", "peak_rss_gb"):
            assert field in qor_trends.NUMERIC_METRICS[dom], (dom, field)
    for field in ("hold_wns_ns", "tns_ns", "util_pct", "wirelength_um"):
        assert field in qor_trends.NUMERIC_METRICS["pd"], field
    # Lower is better for cost metrics; slack metrics stay higher-is-better.
    assert not {"power_mw", "runtime_s", "peak_rss_gb", "wirelength_um"} & qor_trends.HIGHER_IS_BETTER
    assert {"hold_wns_ns", "tns_ns"} <= qor_trends.HIGHER_IS_BETTER
