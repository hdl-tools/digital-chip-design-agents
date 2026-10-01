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


INFRA_AGENT = (
    REPO_ROOT / "plugins" / "infrastructure" / "agents" / "infrastructure-orchestrator.md"
)

MODULE_SYSTEM_ENUM = frozenset({"tclmod", "custom", "none"})
# Only the enum form matches: `"module_system": null` in the run-state object has no quotes,
# and `module_system: "none"` in prose does not quote the key.
MODULE_SYSTEM_FIELD = re.compile(r'"module_system"\s*:\s*"([^"]*\|[^"]*)"')


def _module_system_enum(path: Path, text: str) -> set[str]:
    enums = MODULE_SYSTEM_FIELD.findall(text)
    assert len(enums) == 1, (
        f"{_rel(path)}: expected exactly one module_system enum, found {enums}"
    )
    return {value.strip() for value in enums[0].split("|")}


def test_module_system_records_a_custom_wrapper_and_a_listing_status():
    """A two-value `tclmod | none` enum forced every site whose `module` is a custom
    shell wrapper to be recorded as classic Environment Modules (issue #87), and an
    empty `tools_via_modules` could not be told apart from a listing that never ran -
    which silently lost the seven tools that host provided only via modules."""
    stage = (
        _read(INFRA_SKILL)
        .split("## Stage: module_discovery", 1)[1]
        .split("## Stage: tool_installation", 1)[0]
    )

    assert _module_system_enum(INFRA_SKILL, stage) == set(MODULE_SYSTEM_ENUM), (
        "module-status.json cannot record a module system that is neither Environment "
        "Modules nor absent"
    )

    # The memory record carries its own copy of the enum and nothing cross-checks it.
    assert _module_system_enum(INFRA_AGENT, _read(INFRA_AGENT)) == set(MODULE_SYSTEM_ENUM), (
        "the orchestrator's memory template has drifted from the skill's enum"
    )

    # Trustworthiness of the listing has to be recorded separately from what is installed,
    # or an unreachable `module` is indistinguishable from a host with no modules.
    assert '"module_listing"' in stage, (
        "module-status.json schema omits module_listing - an empty tools_via_modules is "
        "then unreadable"
    )
    assert "because the listing failed" in stage, (
        "module_discovery no longer states that an empty tools_via_modules may mean the "
        "listing failed rather than that no modules exist"
    )


CRITICAL_PATH_COMMANDS = ("yosys", "verilator", "openroad", "sta")

# "critical-path tool (...)" / "critical tool (...)" -- the parenthesised set a rule enumerates.
CRITICAL_SET = re.compile(r"critical(?:-path)? tools? \(([^)]*)\)")
PRODUCT_NAMES = re.compile(r"Yosys|Verilator|OpenROAD|OpenSTA")

# Open-Source list entries: - **Verilator** (`verilator`) -- ...
OPEN_SOURCE_ENTRY = re.compile(r"^- \*\*[^*]+\*\* \(`([^`]+)`\)", re.M)

# Proprietary table: | Synopsys Formality | `fm_shell` (`formality`) | lec | synopsys | probe |
PROPRIETARY_PRIMARY = re.compile(
    r"^\|\s*(?:Synopsys|Cadence|Mentor|Siemens)[^|]*\|\s*`([^`]+)`", re.M
)
MAPPING_KEY = re.compile(r"^\|\s*`([^`]+)`\s*\|", re.M)


def _loop_back_rows(text: str) -> list[str]:
    block = text.split("## Loop-Back Rules", 1)[1].split("\n## ", 1)[0]
    return [line for line in block.splitlines() if line.startswith("- ")]


def test_critical_path_tools_are_keyed_by_command():
    """`tool-status.json` keys entries by command, and OpenSTA's command is `sta`
    (issue #92). A rule naming the product matches no entry and concludes the tool
    is absent from the table, not that it is missing -- a silent pass on a FAIL
    gate. Issue #86 is the companion: the loop-back that gate used could never
    change a tool's status, because `tool_installation` never runs installs."""
    skill = _read(INFRA_SKILL)
    agent = _read(INFRA_AGENT)

    # 1. No enumerated critical-path set may name a product. This is the assertion
    #    that would have caught the third site, added by the #87 fix.
    for found in CRITICAL_SET.findall(skill):
        assert not PRODUCT_NAMES.search(found), (
            f"critical-path set names a product rather than a command: ({found}) -- "
            "tool-status.json has no entry keyed 'OpenSTA'"
        )

    # 2. The commands are grounded in the authoritative Open-Source list, so the set
    #    cannot drift from the table it is supposed to key against.
    listed = set(OPEN_SOURCE_ENTRY.findall(skill))
    for command in CRITICAL_PATH_COMMANDS:
        assert command in listed, (
            f"critical-path command {command!r} is not listed as a command in the "
            "Open-Source tool table"
        )

    # 3. No loop-back row may route a missing critical tool back to tool_installation:
    #    that stage only generates install scripts and never executes them, so the
    #    condition cannot change and the cap is spent on identical checks (issue #86).
    #    Matched on the closing paren so MISSING_LOAD_MODULE rows are not caught, and
    #    on the row's target rather than its prose -- an escalation row may legitimately
    #    name the stage while explaining why looping back to it cannot work.
    for row in _loop_back_rows(agent):
        if "critical tool MISSING)" in row and "\u2192" in row:
            target = row.split("\u2192", 1)[1].strip()
            assert not target.startswith("tool_installation"), (
                "loop-back routes a missing critical tool to tool_installation, which "
                f"never installs anything, so the loop cannot succeed: {row.strip()!r}"
            )

    # 4. Every proprietary tool's module-mapping row is keyed on its primary command.
    #    Formality's was keyed on the legacy `formality` while #82 made `fm_shell`
    #    primary, so the module upgrade silently skipped it on a modern install.
    stage = skill.split("## Stage: module_discovery", 1)[1].split(
        "## Stage: tool_installation", 1
    )[0]
    table = stage.split("#### Module-to-tool mapping table", 1)[1].split("#### Rules", 1)[0]
    mapping_keys = set(MAPPING_KEY.findall(table))
    for primary in PROPRIETARY_PRIMARY.findall(skill):
        assert primary in mapping_keys, (
            f"proprietary primary command {primary!r} has no module-mapping row keyed "
            "on it, so module_discovery cannot upgrade its tool-status entry"
        )


# A `.json` artifact a stage promises to produce.
JSON_ARTIFACT = re.compile(r"`([A-Za-z0-9_.-]+\.json)`")
# Per-tool fields that live in tool-status.json; a second artifact restating them
# becomes a second source of truth for the same facts.
TOOL_STATUS_FIELDS = ('"status"', '"version"', '"command"', '"module_names"', '"versions_available"')


def _stage_sections(text: str) -> dict[str, str]:
    """Map stage name -> that stage's body."""
    parts = re.split(r"^## Stage: (\w+)\s*$", text, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def _subsection(body: str, heading: str) -> str:
    if heading not in body:
        return ""
    return re.split(r"^#{3,4} ", body.split(heading, 1)[1], maxsplit=1, flags=re.M)[0]


def _promised_artifacts(body: str) -> set[str]:
    """.json artifacts on the Output Required bullet list -- not every artifact its
    explanatory prose happens to name."""
    bullets = [
        line for line in _subsection(body, "### Output Required").splitlines()
        if line.startswith("- ")
    ]
    return set(JSON_ARTIFACT.findall("\n".join(bullets)))


def test_environment_validation_artifacts_are_defined():
    """`tool-manifest.json` was specified once and the spec was deleted (issue #91),
    leaving five references to a file with no schema and no creator -- so independent
    runs invented incompatible shapes. Rule 2 also compared against it, which is that
    same stage's output, and re-detected Python packages by a method `tool_discovery`
    does not use (issue #90)."""
    skill = _read(INFRA_SKILL)
    stages = _stage_sections(skill)
    assert "environment_validation" in stages, "stage headings changed"

    # 1. Every .json artifact a stage promises must have a definition in the skill, and
    #    that definition must be followed by a schema. This is what f1124c5 broke.
    for stage, body in stages.items():
        for artifact in _promised_artifacts(body):
            markers = [f"`{artifact}` schema", f"`{artifact}` is a"]
            found = [m for m in markers if m in skill]
            assert found, (
                f"{stage} promises {artifact} but the skill never defines it -- a reference "
                "can outlive its spec, which is how two runs invented two shapes"
            )
            after = skill.split(found[0], 1)[1].split("\n## ", 1)[0]
            assert "```json" in after, f"{artifact} is named as defined but carries no schema"

    # 2. No rule may compare against an artifact its own stage produces: on any run there
    #    is nothing to compare against. A line that forbids it is not a violation.
    for stage, body in stages.items():
        produced = _promised_artifacts(body)
        # Collapse newlines: the rules wrap, so a negation can sit on the line above
        # the match. A sentence forbidding the comparison is not a violation of it.
        rules = " ".join(_subsection(body, "### Domain Rules").split())
        for artifact in produced:
            needle = f"against `{artifact}`"
            for match in re.finditer(re.escape(needle), rules):
                preceding = rules[max(0, match.start() - 40):match.start()].lower()
                if "never" in preceding or "not " in preceding:
                    continue
                raise AssertionError(
                    f"{stage} rule compares against its own output {artifact}: "
                    f"...{rules[max(0, match.start() - 60):match.end() + 40]}..."
                )

    # 3. environment_validation rule 2 may not forbid a fallback that tool_discovery
    #    rule 3 performs -- two stages detecting one tool by different methods disagree
    #    on real installs, silently.
    rule_2 = re.split(
        r"^3\. ", _subsection(stages["environment_validation"], "### Domain Rules")
        .split("2. Re-run tool presence checks", 1)[1], maxsplit=1, flags=re.M
    )[0]
    assert "fall back to" in stages["tool_discovery"], "tool_discovery lost its fallback chain"
    assert "do not fall back" not in rule_2.lower(), (
        "rule 2 forbids a PATH fallback that tool_discovery rule 3 performs"
    )

    # 4. The manifest must not restate per-tool state. Duplicating tool-status.json is
    #    what produced two incompatible invented shapes.
    receipt = skill.split("`tool-manifest.json` is a", 1)[1].split("\n## ", 1)[0]
    schema = JSON_FENCE.search(receipt)
    assert schema, "tool-manifest.json has no JSON schema block"
    for field in TOOL_STATUS_FIELDS:
        assert field not in schema.group(1), (
            f"tool-manifest.json restates the tool-status.json field {field} -- it should "
            "reference that file, not copy it"
        )


VERSION_SELECTION_HEADING = "#### Module version selection"
NON_RELEASE_MARKERS = ("dev", "test", "debug", "rc", "alpha", "beta", "snapshot", "nightly")


def test_module_version_selection_is_specified():
    """Two rules picked a module version by sorting version strings as text (issue
    #98). On a 13-version Python tree the lexicographic maximum is the fourth-oldest,
    and `tool_discovery` Step A loads its pick for the whole run -- so the stage
    replaced a newer PATH interpreter with an older module one."""
    skill = _read(INFRA_SKILL)

    # 1. Neither call site may sort text. The phrase may survive only inside the rule
    #    itself, which cites it to say it is wrong.
    rule_start = skill.index(VERSION_SELECTION_HEADING)
    rule = skill[rule_start:].split("\n#### ", 1)[0]
    outside = skill[:rule_start] + skill[rule_start + len(rule):]
    assert "lexicographic" not in outside, (
        "a call site still selects a version lexicographically; the only permitted "
        "mention is inside the selection rule, which cites it as the defect"
    )

    # 2. The rule exists once and both call sites defer to it, so it cannot be
    #    restated per site and drift -- which is how two copies came to exist.
    assert skill.count(VERSION_SELECTION_HEADING) == 1, "selection rule is duplicated"
    stages = _stage_sections(skill)
    for stage in ("tool_discovery", "module_discovery"):
        assert "Module version selection" in stages[stage], (
            f"{stage} chooses a version without deferring to the selection rule"
        )

    # 3. The site default outranks any computed maximum, and non-release builds are
    #    excluded -- both measured hazards: the trees carry _test/-debug/-dev builds,
    #    and the annotated default differs from the newest build.
    # Scope to the numbered list: the surrounding prose also says "default", so
    # searching the whole rule cannot see the list itself being reordered.
    assert "**Selection order.**" in rule, "the rule states no selection order"
    order = rule.split("**Selection order.**", 1)[1].split("\n\n**", 1)[0]
    ranked = [line for line in order.splitlines() if re.match(r"^\d+\. ", line)]
    assert len(ranked) >= 2, f"selection order has {len(ranked)} ranked entries"
    assert "default" in ranked[0].lower(), (
        f"the site default is not first in the selection order: {ranked[0].strip()!r}"
    )
    assert any("release" in line for line in ranked[1:]), (
        "the selection order never falls back to a release maximum"
    )
    for marker in NON_RELEASE_MARKERS:
        assert f"`{marker}`" in rule, f"non-release marker {marker!r} is not excluded"

    # 4. The choice must be recorded, or a wrong pick is invisible in the artifact.
    stage = stages["module_discovery"]
    for field in ('"selected"', '"selected_basis"', '"candidates"'):
        assert field in stage, f"module-status.json does not record {field}"
