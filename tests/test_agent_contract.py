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


SHARED_SECTIONS = REPO_ROOT / "tools" / "agent_shared_sections.md"
PIPELINE_SKILL = (
    REPO_ROOT / "plugins" / "meta" / "skills" / "pipeline-orchestration" / "SKILL.md"
)

FAILURE_CLASSES = frozenset({
    "none", "functional", "timing", "power_area", "coverage_gap",
    "connectivity", "drc_lvs", "tool_error", "spec_gap", "resource_limit",
})
MAPPING_ROW = re.compile(r"^\|\s*`(\w+)`\s*\|\s*`(\w+)`\s*\|", re.M)
MAPPING_HEADING = "Failure Classification & Retry Strategy"


def _retry_mapping(path: Path) -> dict[str, str]:
    return {
        cls: strategy
        for cls, strategy in MAPPING_ROW.findall(_read(path))
        if cls in FAILURE_CLASSES
    }


def test_retry_strategy_mapping_matches_the_authoritative_table():
    """Agents carry the mapping as a shared section so they need not load the
    whole pipeline-orchestration skill (issue #85). That leaves two copies, and
    ``sync_agent_sections.py --check`` compares agents against the shared file,
    never the shared file against the skill that owns the table."""
    skill = _retry_mapping(PIPELINE_SKILL)
    shared = _retry_mapping(SHARED_SECTIONS)
    assert len(skill) == len(FAILURE_CLASSES), (
        f"pipeline-orchestration maps {sorted(skill)}; expected all of {sorted(FAILURE_CLASSES)}"
    )
    assert shared == skill, (
        "shared section has drifted from the authoritative mapping: "
        f"{sorted(set(shared.items()) ^ set(skill.items()))}"
    )


@pytest.mark.parametrize("path", AGENT_FILES, ids=_rel)
def test_retry_strategy_mapping_is_reachable_by_the_agent(path):
    """An agent told to derive ``retry_strategy`` from a mapping must be able to
    reach one: either it carries the table, or it declares the skill holding it.
    Before issue #85, 15 of 16 did neither and inferred the values."""
    text = _read(path)
    if "retry_strategy" not in text:
        pytest.skip("agent does not write retry_strategy")
    carries_table = MAPPING_HEADING in text and len(_retry_mapping(path)) == len(FAILURE_CLASSES)
    frontmatter = text.split("---", 2)[1] if text.startswith("---") else ""
    declares_skill = "pipeline-orchestration" in frontmatter
    assert carries_table or declares_skill, (
        f"{_rel(path)}: derives retry_strategy from a mapping it cannot reach "
        "- it neither carries the table nor declares the pipeline-orchestration skill"
    )
    # Pointing at a skill it does not declare is the defect itself: an agent that
    # carries the table can still send a reader to an unreachable file.
    if not declares_skill:
        assert "pipeline-orchestration skill" not in text, (
            f"{_rel(path)}: refers to the pipeline-orchestration skill without declaring it"
        )
