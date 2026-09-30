"""Static contract checks on the orchestrator agent and skill markdown.

These guard wording that orchestrators copy verbatim into the records they write,
so a defect in the template becomes a defect in every run's output.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

AGENT_FILES = sorted(REPO_ROOT.glob("plugins/*/agents/*.md"))
SKILL_FILES = sorted(REPO_ROOT.glob("plugins/*/skills/*/SKILL.md"))
MEMORY_README = REPO_ROOT / "memory" / "README.md"

# A JSON example that hardcodes success. Prose such as `signoff_achieved: true`
# (no JSON quotes) is how the rules describe the success case and is allowed.
HARDCODED_SIGNOFF = re.compile(r'"signoff_achieved"\s*:\s*true')


JSON_FENCE = re.compile(r"```json\r?\n(.*?)```", re.DOTALL)


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_agent_files_discovered():
    assert AGENT_FILES, "no agent files found under plugins/*/agents/"


@pytest.mark.parametrize(
    "path", AGENT_FILES + SKILL_FILES + [MEMORY_README], ids=_rel
)
def test_signoff_achieved_not_hardcoded_true(path):
    """distill.py counts sign-off with ``is True``; a template defaulting to true
    records escalated and abandoned runs as successes."""
    lines = [
        f"{_rel(path)}:{n}"
        for n, line in enumerate(_read(path).splitlines(), 1)
        if HARDCODED_SIGNOFF.search(line)
    ]
    assert not lines, f"template hardcodes signoff_achieved true: {lines}"


@pytest.mark.parametrize("path", AGENT_FILES + SKILL_FILES, ids=_rel)
def test_experience_records_are_not_append_only(path):
    """Records are upserted by run_id (memory/README.md). An append per stage or
    per re-run gives one run several records, and distill.py does not dedup."""
    text = _read(path)
    for phrase in ("append one JSON line", "always append"):
        assert phrase not in text, f"{_rel(path)}: append-only wording: {phrase!r}"


@pytest.mark.parametrize("path", AGENT_FILES, ids=_rel)
def test_experience_template_carries_run_id(path):
    templates = [
        block
        for block in JSON_FENCE.findall(_read(path))
        if '"signoff_achieved"' in block
    ]
    for block in templates:
        assert '"run_id"' in block, (
            f"{_rel(path)}: experience template has no run_id to upsert by"
        )


DECISION_ENUM = re.compile(r'"decision"\s*:\s*"([^"]*\|[^"]*)"')


@pytest.mark.parametrize("path", AGENT_FILES, ids=_rel)
def test_decision_enum_lists_every_value_the_agent_writes(path):
    """The checkpoint gate writes decision "await_approval"; the history-entry
    enum the agent copies from must offer it."""
    text = _read(path)
    if 'decision: "await_approval"' not in text:
        pytest.skip("agent has no checkpoint gate")
    enums = DECISION_ENUM.findall(text)
    assert enums, f"{_rel(path)}: no history decision enum found"
    for enum in enums:
        values = [v.strip() for v in enum.split("|")]
        assert "await_approval" in values, (
            f"{_rel(path)}: decision enum {values} omits await_approval"
        )


@pytest.mark.parametrize("path", AGENT_FILES, ids=_rel)
def test_escalation_guidance_goes_in_history_reason(path):
    """Domain orchestrators set pending_approval only at their gates; type
    "escalation" belongs to the pipeline-orchestrator. A rule that puts every
    escalation's guidance in pending_approval.reason implies otherwise."""
    assert "When escalating, `pending_approval.reason` must state" not in _read(path)


INFRA_SKILL = REPO_ROOT / "plugins" / "infrastructure" / "skills" / "infrastructure" / "SKILL.md"

# The Proprietary table rows: | Tool | Command (alt) | role | dialect | probe |
PROPRIETARY_ROW = re.compile(r"^\|\s*(?:Synopsys|Cadence|Mentor|Siemens)\s[^|]*\|(.*)$", re.M)


def test_proprietary_tools_carry_role_and_dialect():
    """A proprietary tool with no role/dialect is modelled as substitutable with
    every other tool of its kind (issue #82): a command line built for one vendor
    then looks portable to another whose option vocabulary is disjoint."""
    text = _read(INFRA_SKILL)
    rows = PROPRIETARY_ROW.findall(text)
    assert len(rows) == 7, f"expected 7 proprietary rows, found {len(rows)}"

    for row in rows:
        command, role, dialect, probe = [c.strip() for c in row.split("|")[:4]]
        assert role and role != "-", f"proprietary row {command!r} has no role"
        assert dialect and dialect != "-", f"proprietary row {command!r} has no dialect"
        # Every row states its probe or says UNVERIFIED -- never blank, and never a
        # flag with no provenance, which is how a guessed flag that grabs a license
        # or opens an interactive shell would get in.
        if "UNVERIFIED" in probe:
            assert not probe.startswith("`"), (
                f"{command}: row is both UNVERIFIED and carries a command"
            )
        else:
            assert probe.startswith("`"), (
                f"{command}: probe must be a command in backticks, or say UNVERIFIED"
            )
        # vcs and xrun were verified first and must never regress to UNVERIFIED.
        if "`vcs`" in command or "`xrun`" in command:
            assert "UNVERIFIED" not in probe, f"{command}: verified probe expected"

    # The schema downstream stages read must carry both fields, or the table above
    # is documentation with no recorded output.
    schema = text.split("## Stage: tool_discovery", 1)[1].split("## Stage: module_discovery", 1)[0]
    for field in ('"role"', '"dialect"'):
        assert field in schema, f"tool_discovery output schema omits {field}"
