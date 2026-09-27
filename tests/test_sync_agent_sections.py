"""Tests for tools/sync_agent_sections.py.

Each test builds a miniature repo under ``tmp_path`` and drives the script
through ``run()``, which returns ``(exit_code, messages)`` without printing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import REPO_ROOT, _load

CANONICAL_REL = "tools/agent_shared_sections.md"

AGENT = """\
---
name: {name}-orchestrator
---

## Stage Sequence
a → b

## Tool Options

### Open-Source
- tool

## Behaviour Rules
1. First rule — with a dash
2. Second rule

## Memory
Read things.
"""

# Behaviour Rules is followed by Design State, not Memory.
AGENT_INFRA_SHAPE = """\
## Stage Sequence
a → b

## Behaviour Rules
1. Only rule

## Design State
State.

## Infrastructure Memory (opt-in)
Memory.
"""

AGENT_RULES_LAST = """\
## Stage Sequence
a → b

## Behaviour Rules
1. Only rule
"""

CANONICAL = """\
# Shared sections

Preamble text that is not part of any block.

<!-- BLOCK gating
targets: agents
except: meta
after: ^## Behaviour Rules$
-->
## Stage Gating
1. Never proceed past a FAIL — ever.
<!-- END BLOCK gating -->

<!-- BLOCK reporting
targets: agents
after: ^## Behaviour Rules$
-->
## Reporting Contract
1. Run before you report.
<!-- END BLOCK reporting -->

<!-- BLOCK direct
targets: agents
only: firmware
after: ^## Tool Options$
-->
### MCP Preference
Use direct execution.
<!-- END BLOCK direct -->
"""

# Names no specific agent, for repos that hold a single arbitrary one.
CANONICAL_ANY_AGENT = """\
<!-- BLOCK gating
targets: agents
after: ^## Behaviour Rules$
-->
## Stage Gating
1. Never proceed past a FAIL — ever.
<!-- END BLOCK gating -->

<!-- BLOCK reporting
targets: agents
after: ^## Behaviour Rules$
-->
## Reporting Contract
1. Run before you report.
<!-- END BLOCK reporting -->
"""


@pytest.fixture(scope="module")
def sync():
    return _load("sync_agent_sections", "tools/sync_agent_sections.py")


def make_repo(root: Path, agents: dict[str, str], canonical: str = CANONICAL) -> None:
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / CANONICAL_REL).write_bytes(canonical.encode("utf-8"))
    for key, text in agents.items():
        d = root / "plugins" / key / "agents"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{key}-orchestrator.md").write_bytes(text.encode("utf-8"))


def agent_path(root: Path, key: str) -> Path:
    return root / "plugins" / key / "agents" / f"{key}-orchestrator.md"


def read(root: Path, key: str) -> str:
    return agent_path(root, key).read_bytes().decode("utf-8")


def standard_repo(root: Path) -> None:
    make_repo(
        root,
        {
            "firmware": AGENT.format(name="firmware"),
            "pd": AGENT.format(name="pd"),
            "meta": AGENT.format(name="meta"),
        },
    )


# ---------------------------------------------------------------------------
# Canonical file parsing
# ---------------------------------------------------------------------------

def test_parse_preserves_order_and_attributes(sync):
    blocks = sync.parse_canonical(CANONICAL)
    assert [b.id for b in blocks] == ["gating", "reporting", "direct"]
    assert blocks[0].exclude == ["meta"]
    assert blocks[2].only == ["firmware"]
    assert blocks[0].body.splitlines()[0] == "## Stage Gating"
    assert "Preamble" not in blocks[0].body


@pytest.mark.parametrize(
    "canonical",
    [
        CANONICAL.replace("<!-- END BLOCK reporting -->", ""),  # unclosed
        CANONICAL.replace("BLOCK reporting", "BLOCK gating"),  # duplicate id
        CANONICAL.replace("after: ^## Tool Options$\n", ""),  # missing key
        CANONICAL.replace("only: firmware", "only: nonexistent"),  # unknown agent
        CANONICAL.replace("targets: agents\nonly", "targets: nowhere\nonly"),
    ],
    ids=["unclosed", "duplicate-id", "missing-after", "unknown-agent", "bad-targets"],
)
def test_malformed_canonical_is_a_config_error(sync, tmp_path, canonical):
    make_repo(tmp_path, {"firmware": AGENT.format(name="firmware")}, canonical)
    before = read(tmp_path, "firmware")
    code, _ = sync.run(tmp_path, check=False)
    assert code == 2
    assert read(tmp_path, "firmware") == before


# ---------------------------------------------------------------------------
# Write mode
# ---------------------------------------------------------------------------

def test_insert_leaves_text_outside_blocks_unchanged(sync, tmp_path):
    standard_repo(tmp_path)
    original = read(tmp_path, "pd")
    code, _ = sync.run(tmp_path, check=False)
    assert code == 0
    result = read(tmp_path, "pd")
    assert "<!-- BEGIN SHARED:gating " in result
    assert sync.strip_blocks(result) == original


def test_blocks_land_between_behaviour_rules_and_memory(sync, tmp_path):
    standard_repo(tmp_path)
    sync.run(tmp_path, check=False)
    result = read(tmp_path, "pd")
    order = [
        result.index("## Behaviour Rules"),
        result.index("2. Second rule"),
        result.index("## Stage Gating"),
        result.index("## Reporting Contract"),
        result.index("## Memory"),
    ]
    assert order == sorted(order)


def test_second_run_is_a_no_op(sync, tmp_path):
    standard_repo(tmp_path)
    sync.run(tmp_path, check=False)
    first = {k: read(tmp_path, k) for k in ("firmware", "pd", "meta")}
    code, messages = sync.run(tmp_path, check=False)
    assert code == 0
    assert not [m for m in messages if m.startswith("updated")]
    assert {k: read(tmp_path, k) for k in first} == first


def test_canonical_edit_replaces_only_the_block_body(sync, tmp_path):
    standard_repo(tmp_path)
    sync.run(tmp_path, check=False)
    canonical = tmp_path / CANONICAL_REL
    canonical.write_bytes(
        CANONICAL.replace("Run before you report.", "Run, then report.").encode("utf-8")
    )
    before = read(tmp_path, "pd")
    sync.run(tmp_path, check=False)
    after = read(tmp_path, "pd")
    assert after == before.replace("Run before you report.", "Run, then report.")


def test_only_and_except_are_honoured(sync, tmp_path):
    standard_repo(tmp_path)
    sync.run(tmp_path, check=False)
    assert "SHARED:gating" in read(tmp_path, "pd")
    assert "SHARED:gating" not in read(tmp_path, "meta")
    assert "SHARED:reporting" in read(tmp_path, "meta")
    assert "SHARED:direct" in read(tmp_path, "firmware")
    assert "SHARED:direct" not in read(tmp_path, "pd")


def test_only_block_is_placed_at_its_own_anchor(sync, tmp_path):
    standard_repo(tmp_path)
    sync.run(tmp_path, check=False)
    result = read(tmp_path, "firmware")
    assert (
        result.index("### Open-Source")
        < result.index("### MCP Preference")
        < result.index("## Behaviour Rules")
    )


def test_stale_block_in_newly_excluded_agent(sync, tmp_path):
    standard_repo(tmp_path)
    sync.run(tmp_path, check=False)
    (tmp_path / CANONICAL_REL).write_bytes(
        CANONICAL.replace("except: meta", "except: meta, pd").encode("utf-8")
    )
    code, _ = sync.run(tmp_path, check=True)
    assert code == 1
    assert "SHARED:gating" in read(tmp_path, "pd")  # check mode never writes
    sync.run(tmp_path, check=False)
    assert "SHARED:gating" not in read(tmp_path, "pd")
    assert "SHARED:reporting" in read(tmp_path, "pd")


def test_canonical_order_is_restored(sync, tmp_path):
    standard_repo(tmp_path)
    sync.run(tmp_path, check=False)
    synced = read(tmp_path, "pd")
    gating = synced[synced.index("<!-- BEGIN SHARED:gating"):synced.index("<!-- END SHARED:gating -->")]
    gating += "<!-- END SHARED:gating -->"
    reporting = synced[synced.index("<!-- BEGIN SHARED:reporting"):synced.index("<!-- END SHARED:reporting -->")]
    reporting += "<!-- END SHARED:reporting -->"
    swapped = synced.replace(gating, "@@G@@").replace(reporting, gating).replace("@@G@@", reporting)
    assert swapped != synced
    agent_path(tmp_path, "pd").write_bytes(swapped.encode("utf-8"))
    sync.run(tmp_path, check=False)
    assert read(tmp_path, "pd") == synced


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------

def test_anchor_uses_next_heading_whatever_it_is(sync, tmp_path):
    make_repo(tmp_path, {"infrastructure": AGENT_INFRA_SHAPE}, CANONICAL_ANY_AGENT)
    assert sync.run(tmp_path, check=False)[0] == 0
    result = read(tmp_path, "infrastructure")
    assert (
        result.index("1. Only rule")
        < result.index("## Stage Gating")
        < result.index("## Design State")
    )


def test_anchor_section_last_in_file_appends_at_eof(sync, tmp_path):
    make_repo(tmp_path, {"pd": AGENT_RULES_LAST}, CANONICAL_ANY_AGENT)
    assert sync.run(tmp_path, check=False)[0] == 0
    result = read(tmp_path, "pd")
    assert result.rstrip("\n").endswith("<!-- END SHARED:reporting -->")
    assert result.endswith("\n") and not result.endswith("\n\n")
    assert sync.run(tmp_path, check=True)[0] == 0


def test_missing_anchor_names_the_file(sync, tmp_path):
    make_repo(
        tmp_path,
        {"pd": "## Stage Sequence\na → b\n\n## Memory\nx\n"},
        CANONICAL_ANY_AGENT,
    )
    code, messages = sync.run(tmp_path, check=False)
    assert code == 2
    assert any("plugins/pd/agents/pd-orchestrator.md" in m for m in messages)


def test_heading_inside_code_fence_is_not_an_anchor_boundary(sync, tmp_path):
    fenced = AGENT_RULES_LAST + "```markdown\n## Memory\nexample only\n```\nTrailing rule text.\n"
    make_repo(tmp_path, {"pd": fenced}, CANONICAL_ANY_AGENT)
    assert sync.run(tmp_path, check=False)[0] == 0
    result = read(tmp_path, "pd")
    assert result.index("Trailing rule text.") < result.index("## Stage Gating")


# ---------------------------------------------------------------------------
# Encoding and line endings
# ---------------------------------------------------------------------------

def test_crlf_file_stays_crlf(sync, tmp_path):
    standard_repo(tmp_path)
    path = agent_path(tmp_path, "pd")
    path.write_bytes(AGENT.format(name="pd").replace("\n", "\r\n").encode("utf-8"))
    sync.run(tmp_path, check=False)
    data = path.read_bytes()
    assert b"SHARED:gating" in data
    assert data.count(b"\n") == data.count(b"\r\n")


def test_lf_file_stays_lf_with_crlf_canonical(sync, tmp_path):
    standard_repo(tmp_path)
    (tmp_path / CANONICAL_REL).write_bytes(CANONICAL.replace("\n", "\r\n").encode("utf-8"))
    sync.run(tmp_path, check=False)
    assert b"\r" not in agent_path(tmp_path, "pd").read_bytes()


def test_check_passes_for_both_line_endings(sync, tmp_path):
    standard_repo(tmp_path)
    sync.run(tmp_path, check=False)
    path = agent_path(tmp_path, "pd")
    assert sync.run(tmp_path, check=True)[0] == 0
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert sync.run(tmp_path, check=True)[0] == 0


def test_non_ascii_is_preserved(sync, tmp_path):
    standard_repo(tmp_path)
    sync.run(tmp_path, check=False)
    data = agent_path(tmp_path, "pd").read_bytes()
    assert "a → b".encode("utf-8") in data
    assert "First rule — with a dash".encode("utf-8") in data
    assert "Never proceed past a FAIL — ever.".encode("utf-8") in data


# ---------------------------------------------------------------------------
# Check mode
# ---------------------------------------------------------------------------

def test_check_reports_unsynced_repo_without_writing(sync, tmp_path):
    standard_repo(tmp_path)
    before = read(tmp_path, "pd")
    code, messages = sync.run(tmp_path, check=True)
    assert code == 1
    assert read(tmp_path, "pd") == before
    assert any("plugins/pd/agents/pd-orchestrator.md" in m for m in messages)


def test_hand_edit_inside_block_is_drift(sync, tmp_path):
    standard_repo(tmp_path)
    sync.run(tmp_path, check=False)
    path = agent_path(tmp_path, "pd")
    path.write_bytes(path.read_bytes().replace(b"Run before you report.", b"Report freely."))
    assert sync.run(tmp_path, check=True)[0] == 1


def test_shared_heading_outside_markers_is_rejected(sync, tmp_path):
    standard_repo(tmp_path)
    path = agent_path(tmp_path, "pd")
    path.write_bytes(path.read_bytes() + b"\n## Reporting Contract\nhand-written copy\n")
    code, messages = sync.run(tmp_path, check=False)
    assert code == 2
    assert any("Reporting Contract" in m for m in messages)


def test_orphan_marker_is_rejected(sync, tmp_path):
    standard_repo(tmp_path)
    sync.run(tmp_path, check=False)
    path = agent_path(tmp_path, "pd")
    path.write_bytes(path.read_bytes().replace(b"<!-- END SHARED:gating -->", b""))
    assert sync.run(tmp_path, check=False)[0] == 2


# ---------------------------------------------------------------------------
# File targets (IDE headers)
# ---------------------------------------------------------------------------

def test_file_targets(sync, tmp_path):
    canonical = CANONICAL + (
        "\n<!-- BLOCK ide\n"
        "targets: files\n"
        "files: ides/codex/AGENTS.md\n"
        "after: ^## (General Behaviour|Behaviour for All Domains)$\n"
        "-->\n"
        "## Verification and Reporting\n\n- Read the result.\n"
        "<!-- END BLOCK ide -->\n"
    )
    standard_repo(tmp_path)
    (tmp_path / CANONICAL_REL).write_bytes(canonical.encode("utf-8"))
    header = tmp_path / "ides" / "codex" / "AGENTS.md"
    header.parent.mkdir(parents=True)
    header.write_bytes(b"Intro.\n\n## General Behaviour\n\n- Rule.\n\n## Available Domains\n\nx\n")
    assert sync.run(tmp_path, check=False)[0] == 0
    text = header.read_bytes().decode("utf-8")
    assert (
        text.index("- Rule.")
        < text.index("## Verification and Reporting")
        < text.index("## Available Domains")
    )
    assert sync.run(tmp_path, check=True)[0] == 0


# ---------------------------------------------------------------------------
# The real repository
# ---------------------------------------------------------------------------

def test_repo_is_in_sync(sync):
    code, messages = sync.run(REPO_ROOT, check=True)
    assert code == 0, "\n".join(messages)
