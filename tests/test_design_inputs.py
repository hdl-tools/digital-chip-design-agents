"""Tests for plugins/rtl-design/skills/rtl-design/check_design_inputs.py (issue #83).

A lint run on the wrong input set reports RTL-looking errors about RTL that is
correct. The originating case: a stale generated-header tree listed first on the
include path shadowed the current one, giving 19 "duplicate declaration" and
"undeclared identifier" fatals whose fix was one filelist line. The checker has
to name that cause from the filelist alone, without touching a design file.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from conftest import _load

STALE_HEADER = "`define REG_CTRL_EN 0\ninput wire legacy_irq;\n"
CURRENT_HEADER = "`define REG_CTRL_EN 0\n`define REG_CTRL_MODE 1\n"


@pytest.fixture(scope="module")
def checker():
    return _load("check_design_inputs", "plugins/rtl-design/skills/rtl-design/check_design_inputs.py")


def write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def design(tmp_path: Path) -> Path:
    """A design root with one source and one include directory."""
    root = tmp_path / "proj"
    write(root / "rtl" / "top.sv", '`include "regmap_fields.vh"\nmodule top; endmodule\n')
    write(root / "inc" / "regmap_fields.vh", CURRENT_HEADER)
    return root


def issues(result, kind):
    return [i for i in result["issues"] if i["kind"] == kind]


def stale_tree_case(tmp_path: Path):
    """The filelist from the issue: two generations of one header tree, stale first."""
    root = tmp_path / "proj"
    write(root / "rtl" / "top.sv", "module top; endmodule\n")
    stale = write(tmp_path / "regmap_gen" / "output" / "verilog" / "regmap_fields.vh", STALE_HEADER)
    current = write(tmp_path / "regmap_gen_v2" / "output" / "verilog" / "regmap_fields.vh",
                    CURRENT_HEADER)
    filelist = write(
        root / "top.f",
        "// register map headers\n"
        "+incdir+$ROOT/../regmap_gen/output/verilog\n"
        "+incdir+$ROOT/../regmap_gen_v2/output/verilog\n"
        "$ROOT/rtl/top.sv\n",
    )
    return root, filelist, stale, current


def test_stale_generated_tree_listed_first_fails_and_names_both_paths(checker, tmp_path):
    """Acceptance criterion 1."""
    root, filelist, stale, current = stale_tree_case(tmp_path)
    result = checker.run(str(filelist), root=str(root), cwd=str(root), env={"ROOT": str(root)})

    assert result["status"] == "FAIL"
    assert result["verified"] is True
    assert result["filelist"] == str(filelist)
    assert result["include_dirs"] == [str(stale.parent), str(current.parent)]

    (dup,) = issues(result, "duplicate_include")
    assert dup["severity"] == "ERROR"
    assert dup["basename"] == "regmap_fields.vh"
    assert dup["paths"] == [str(stale), str(current)]
    assert dup["wins"] == str(stale)
    assert "first-match-wins" in dup["message"]
    assert result["summary"]["duplicate_include_basenames"] == 1

    # The two trees are recognised as versions of one tree, and as outside the root.
    (sibling,) = issues(result, "sibling_tree")
    assert sibling["paths"] == [str(stale.parent), str(current.parent)]
    assert len(issues(result, "outside_root")) == 2


def test_no_design_file_is_modified(checker, tmp_path):
    """Acceptance criterion 2: the checker reports; it never edits."""
    root, filelist, _, _ = stale_tree_case(tmp_path)

    def snapshot():
        return {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(tmp_path.rglob("*")) if p.is_file()
        }

    before = snapshot()
    checker.run(str(filelist), root=str(root), cwd=str(root), env={"ROOT": str(root)})
    assert snapshot() == before


def test_clean_design_passes(checker, tmp_path):
    """Acceptance criterion 4."""
    root = design(tmp_path)
    filelist = write(root / "top.f", "+incdir+inc\nrtl/top.sv\n")
    result = checker.run(str(filelist), root=str(root), cwd=str(root))
    assert result["issues"] == []
    assert result["status"] == "PASS"
    assert result["verified"] is True
    assert result["source_count"] == 1


def test_identical_duplicate_header_is_a_warning(checker, tmp_path):
    root = design(tmp_path)
    write(root / "inc_copy" / "regmap_fields.vh", CURRENT_HEADER)
    filelist = write(root / "top.f", "+incdir+inc+inc_copy\nrtl/top.sv\n")
    result = checker.run(str(filelist), root=str(root), cwd=str(root))
    assert result["status"] == "WARN"
    assert issues(result, "duplicate_include") == []
    (dup,) = issues(result, "duplicate_include_identical")
    assert dup["wins"] == str(root / "inc" / "regmap_fields.vh")


def test_main_prints_json_and_exits_1_on_fail(checker, tmp_path, capsys):
    root, filelist, _, _ = stale_tree_case(tmp_path)
    rc = checker.main([str(filelist), "--cwd", str(root), "--env", f"ROOT={root}"])
    assert rc == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_nested_filelists_resolve_like_a_tool(checker, tmp_path):
    """`-f` paths are relative to the run directory, `-F` paths to the file naming them."""
    root = design(tmp_path)
    write(root / "ip" / "uart" / "uart.sv", "module uart; endmodule\n")
    write(root / "ip" / "uart" / "inc" / "uart_regs.vh", "")
    write(root / "ip" / "uart" / "uart.f", "+incdir+inc\nuart.sv\n")
    write(root / "lists" / "core.f", "-I inc\nrtl/top.sv\n")
    filelist = write(root / "top.f", "-F ip/uart/uart.f\n-f lists/core.f\n")

    result = checker.run(str(filelist), root=str(root), cwd=str(root))
    assert result["status"] == "PASS", result["issues"]
    assert result["include_dirs"] == [str(root / "ip" / "uart" / "inc"), str(root / "inc")]
    assert result["source_count"] == 2
    assert len(result["filelists"]) == 3


def test_filelist_that_includes_itself_is_an_error(checker, tmp_path):
    root = design(tmp_path)
    filelist = write(root / "top.f", "rtl/top.sv\n-f top.f\n")
    result = checker.run(str(filelist), cwd=str(root))
    assert result["status"] == "FAIL"
    assert issues(result, "filelist_cycle")


def test_unresolved_variable_is_reported_not_guessed(checker, tmp_path, monkeypatch):
    monkeypatch.delenv("NO_SUCH_ROOT", raising=False)
    root = design(tmp_path)
    filelist = write(root / "top.f", "+incdir+$NO_SUCH_ROOT/inc\nrtl/top.sv\n")
    result = checker.run(str(filelist), cwd=str(root))
    assert result["status"] == "WARN"
    assert result["include_dirs"] == []
    assert "NO_SUCH_ROOT" in issues(result, "unresolved_variable")[0]["message"]


@pytest.mark.parametrize("form", ["${ROOT}", "$(ROOT)", "$ROOT"])
def test_variable_forms_are_expanded(checker, tmp_path, form):
    root = design(tmp_path)
    filelist = write(root / "top.f", f"+incdir+{form}/inc\n{form}/rtl/top.sv\n")
    result = checker.run(str(filelist), root=str(root), cwd=str(tmp_path), env={"ROOT": str(root)})
    assert result["status"] == "PASS", result["issues"]
    assert result["include_dirs"] == [str(root / "inc")]


def test_missing_include_dir_and_source_are_errors(checker, tmp_path):
    root = design(tmp_path)
    filelist = write(root / "top.f", "+incdir+inc+gone\nrtl/top.sv\nrtl/absent.sv\n")
    result = checker.run(str(filelist), root=str(root), cwd=str(root))
    assert result["status"] == "FAIL"
    assert issues(result, "missing_include_dir")[0]["paths"] == [str(root / "gone")]
    assert issues(result, "missing_source")[0]["paths"] == [str(root / "rtl" / "absent.sv")]


def test_missing_filelist_fails(checker, tmp_path):
    result = checker.run(str(tmp_path / "nope.f"), cwd=str(tmp_path))
    assert result["status"] == "FAIL"
    assert issues(result, "missing_filelist")


def test_empty_filelist_is_not_a_pass(checker, tmp_path):
    filelist = write(tmp_path / "empty.f", "// nothing yet\n+define+SYNTHESIS\n")
    result = checker.run(str(filelist), cwd=str(tmp_path))
    assert result["status"] == "WARN"
    assert result["verified"] is False


def test_sibling_tree_on_disk_but_not_on_the_path_is_reported(checker, tmp_path):
    """Only the old tree is listed; the newer one sits beside it with the same header."""
    root = design(tmp_path)
    write(root / "gen_old" / "inc" / "regs.vh", STALE_HEADER)
    newer = write(root / "gen" / "inc" / "regs.vh", CURRENT_HEADER)
    filelist = write(root / "top.f", "+incdir+gen_old/inc\nrtl/top.sv\n")
    result = checker.run(str(filelist), root=str(root), cwd=str(root))
    assert result["status"] == "WARN"
    (sibling,) = issues(result, "sibling_tree_on_disk")
    assert sibling["paths"] == [str(root / "gen_old" / "inc"), str(newer.parent)]


def test_numbered_instances_are_not_version_siblings(checker, tmp_path):
    """uart0 / uart1 are two instances. Flagging them would bury the real warning."""
    root = design(tmp_path)
    write(root / "ip" / "uart0" / "inc" / "uart0_regs.vh", "")
    write(root / "ip" / "uart1" / "inc" / "uart1_regs.vh", "")
    filelist = write(root / "top.f", "+incdir+ip/uart0/inc+ip/uart1/inc\nrtl/top.sv\n")
    result = checker.run(str(filelist), root=str(root), cwd=str(root))
    assert result["status"] == "PASS", result["issues"]


def test_duplicate_source_basename_is_a_warning(checker, tmp_path):
    root = design(tmp_path)
    write(root / "rtl_b" / "top.sv", "module top; endmodule\n")
    filelist = write(root / "top.f", "rtl/top.sv\nrtl_b/top.sv\n")
    result = checker.run(str(filelist), root=str(root), cwd=str(root))
    assert result["status"] == "WARN"
    assert issues(result, "duplicate_source")[0]["basename"] == "top.sv"


def test_option_values_are_not_mistaken_for_sources(checker, tmp_path):
    root = design(tmp_path)
    filelist = write(root / "top.f", "--top-module top\n+define+SYNTHESIS\n-Wall\nrtl/top.sv\n")
    result = checker.run(str(filelist), root=str(root), cwd=str(root))
    assert result["status"] == "PASS", result["issues"]
    assert result["source_count"] == 1


def test_generated_output_older_than_its_source_is_reported(checker, tmp_path):
    root = design(tmp_path)
    source = write(root / "regmap" / "regmap.yaml", "regs: []\n")
    header = root / "inc" / "regmap_fields.vh"
    os.utime(header, (1_000_000, 1_000_000))
    os.utime(source, (2_000_000, 2_000_000))
    filelist = write(root / "top.f", "+incdir+inc\nrtl/top.sv\n")
    result = checker.run(str(filelist), root=str(root), cwd=str(root),
                         generated=[f"inc={source}"])
    assert result["status"] == "WARN"
    assert issues(result, "stale_generated")

    os.utime(header, (3_000_000, 3_000_000))
    result = checker.run(str(filelist), root=str(root), cwd=str(root),
                         generated=[f"inc={source}"])
    assert result["status"] == "PASS", result["issues"]
