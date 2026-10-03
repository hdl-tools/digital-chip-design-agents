"""Static contract checks on the orchestrator agent and skill markdown.

These guard wording that orchestrators copy verbatim into the records they write,
so a defect in the template becomes a defect in every run's output.
"""

from __future__ import annotations

import json
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
def test_decision_enum_lists_loop_back_for_agents_with_loop_back_rules(path):
    """A FAIL/WARN that a Loop-Back Rules row sends to another stage is recorded as
    decision "loop_back" (see tools/agent_shared_sections.md), not "proceed" — the
    enum every such agent copies from must offer it. Unlike await_approval, this
    condition doesn't depend on the agent declaring the literal value anywhere, since
    the previous gap (#94) was exactly that nothing declared it."""
    text = _read(path)
    if path.parent.parent.name == "meta":
        pytest.skip(
            "pipeline-orchestrator writes history only at signoff_or_escalate's "
            "two terminal branches, never per internal loop-back"
        )
    if "## Loop-Back Rules" not in text:
        pytest.skip("agent has no Loop-Back Rules section")
    enums = DECISION_ENUM.findall(text)
    assert enums, f"{_rel(path)}: no history decision enum found"
    for enum in enums:
        values = [v.strip() for v in enum.split("|")]
        assert "loop_back" in values, (
            f"{_rel(path)}: decision enum {values} omits loop_back"
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
    "connectivity", "drc_lvs", "tool_error", "input_setup", "spec_gap", "resource_limit",
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


@pytest.mark.parametrize("path", AGENT_FILES, ids=_rel)
def test_long_running_jobs_guidance_present(path):
    """Issue #76: an agent with no guidance for jobs outliving a turn busy-waited on
    its own background build for ~250k tokens and never finished. Every orchestrator
    must carry the shared block's load-bearing clauses, not just its heading."""
    text = _read(path)
    assert "## Long-Running Jobs" in text, (
        f"{_rel(path)}: missing the Long-Running Jobs section"
    )
    for clause in (
        "never busy-poll it",
        "A quiet log is not a hung job",
        "stop and hand it over",
    ):
        assert clause in text, (
            f"{_rel(path)}: Long-Running Jobs section is missing clause {clause!r}"
        )

@pytest.mark.parametrize("path", AGENT_FILES, ids=_rel)
def test_progress_guard_present_in_stage_gating(path):
    """A loop-back cap bounds how many retries a failure gets, not whether they
    converge: a retry that made things worse, changed nothing, or passed by relaxing
    the constraint or check that failed was stopped only when the cap ran out, and
    three rows are marked `unlimited`. Every orchestrator that carries Stage Gating
    must carry item 7's load-bearing clauses; the pipeline-orchestrator has its own
    divergence check and carries neither."""
    text = _read(path)
    if "## Stage Gating and Escalation" not in text:
        assert path.parent.parent.name == "meta", (
            f"{_rel(path)}: missing the Stage Gating and Escalation section"
        )
        return
    # The block is hard-wrapped; compare with whitespace collapsed so re-wrapping the
    # canonical text does not read as a missing clause.
    flat = " ".join(text.split())
    for clause in (
        "not a number that must be spent",
        "two consecutive iterations",
        "A pass obtained by changing the target is not a pass",
        "`resource_limit` — the cap was not reached",
    ):
        assert clause in flat, (
            f"{_rel(path)}: Stage Gating item 7 is missing clause {clause!r}"
        )


INFRA_SKILL = REPO_ROOT / "plugins" / "infrastructure" / "skills" / "infrastructure" / "SKILL.md"

# A proprietary table data row: | Tool | Command (alt) | `role` | `dialect` | probe |
# Not vendor-anchored -- the table also carries Xilinx/Intel/Microchip/Arm/SEGGER/
# Lauterbach rows, which a Synopsys|Cadence|Mentor|Siemens anchor cannot see.
TABLE_ROW = re.compile(r"^\|(.*)\|\s*$", re.M)

# A domain skill's flat Proprietary bullet, with or without a command:
# "- **Cadence Genus** (`genus`, dialect `cadence`) -- ..." or
# "- **Siemens Aprisa** (dialect `siemens`) -- ...". The parenthetical right after
# the bold name is captured whole; command backticks are pulled out of the part
# before ", dialect" so the dialect value's own backticks are never mistaken for
# a command.
DOMAIN_PROPRIETARY_BULLET = re.compile(r"^- \*\*[^*]+\*\* \(([^)]*)\)", re.M)


def _proprietary_rows(text: str) -> list[list[str]]:
    """Data rows of the infra skill's Proprietary table, as stripped columns.

    Slices from the section heading to the next ``---`` (the same idiom
    ``_module_system_enum``/``_stage_sections`` use for other sections), then
    drops the header and separator row so only `Tool | Command (alt) | role |
    dialect | probe` rows remain.
    """
    section = text.split("### Proprietary (detect only", 1)[1].split("\n---", 1)[0]
    lines = [m.group(1) for m in TABLE_ROW.finditer(section)]
    data_lines = lines[2:]  # drop header + `|---|---|...` separator
    return [[c.strip() for c in line.split("|")] for line in data_lines]


def _domain_proprietary_commands() -> set[str]:
    """Every backticked command a domain skill's Proprietary list names.

    Commandless bullets (no backtick before ", dialect") contribute nothing --
    by decision, a product with no documented command gets no table row.
    """
    commands: set[str] = set()
    for path in SKILL_FILES:
        if path == INFRA_SKILL:
            continue
        text = _read(path)
        if "### Proprietary" not in text:
            continue
        section = text.split("### Proprietary", 1)[1].split("\n### ", 1)[0]
        for paren in DOMAIN_PROPRIETARY_BULLET.findall(section):
            if paren.startswith("dialect"):
                continue  # commandless bullet: "(dialect `synopsys`)", no comma to split on
            before_dialect = paren.split(", dialect", 1)[0]
            commands.update(re.findall(r"`([^`]+)`", before_dialect))
    return commands


def test_proprietary_tools_carry_role_and_dialect():
    """A proprietary tool with no role/dialect is modelled as substitutable with
    every other tool of its kind (issue #82): a command line built for one vendor
    then looks portable to another whose option vocabulary is disjoint. Issue #84
    is the follow-up: 27 of the 34 tools domain skills actually tell agents to use
    had no row at all, so the WARN could never fire for them."""
    text = _read(INFRA_SKILL)
    rows = _proprietary_rows(text)
    assert rows, "no proprietary rows found -- section heading or `---` fence moved"

    all_commands: set[str] = set()
    for cols in rows:
        tool, command_col, role, dialect, probe = cols[:5]
        assert role and role != "-", f"{tool}: proprietary row has no role"
        assert dialect and dialect != "-", f"{tool}: proprietary row has no dialect"
        # Every row states its probe or says UNVERIFIED -- never blank, and never a
        # flag with no provenance, which is how a guessed flag that grabs a license
        # or opens an interactive shell would get in.
        if "UNVERIFIED" in probe:
            assert not probe.startswith("`"), (
                f"{tool}: row is both UNVERIFIED and carries a command"
            )
        else:
            assert probe.startswith("`"), (
                f"{tool}: probe must be a command in backticks, or say UNVERIFIED"
            )
        all_commands.update(re.findall(r"`([^`]+)`", command_col))

    # vcs, xrun and genus were verified first and must never regress to UNVERIFIED.
    for cols in rows:
        command_col, probe = cols[1], cols[4]
        if any(f"`{c}`" in command_col for c in ("vcs", "xrun", "genus")):
            assert "UNVERIFIED" not in probe, f"{command_col}: verified probe expected"

    # Criterion (a): every tool a domain skill tells an agent to use is detectable
    # here, as a primary or an alternate command. This makes the row count
    # self-deriving -- naming a new proprietary tool in a domain skill and
    # forgetting the infra table row fails here instead of drifting unnoticed.
    missing = _domain_proprietary_commands() - all_commands
    assert not missing, (
        f"domain skills name these proprietary commands with no infra table row: {missing}"
    )

    # The schema downstream stages read must carry both fields, or the table above
    # is documentation with no recorded output.
    schema = text.split("## Stage: tool_discovery", 1)[1].split("## Stage: module_discovery", 1)[0]
    for field in ('"role"', '"dialect"'):
        assert field in schema, f"tool_discovery output schema omits {field}"


INFRA_AGENT = (
    REPO_ROOT / "plugins" / "infrastructure" / "agents" / "infrastructure-orchestrator.md"
)

WRAPPER_COUNT = re.compile(
    r"all (\d+) wrappers?\b|(\d+) executable wrapper scripts|"
    r"wrapper scripts with executable bit set \(target: (\d+)\)|"
    r'"wrappers": \{ "expected": (\d+)',
    re.I,
)


def test_stated_wrapper_count_matches_the_tools_directory():
    """The wrapper count is written out in six places across the infrastructure
    skill and agent, and `environment_validation` checks against it. Adding
    `wrap-verilator-lint.sh` (issue #112) without them would have every install
    report one wrapper more than the stage expects."""
    on_disk = len(list((REPO_ROOT / "plugins" / "infrastructure" / "tools").glob("wrap-*.sh")))
    stated = []
    for path in (INFRA_SKILL, INFRA_AGENT):
        for match in WRAPPER_COUNT.finditer(_read(path)):
            stated.append((_rel(path), int(next(g for g in match.groups() if g))))
    assert len(stated) >= 6, f"expected the count in at least 6 places, found {stated}"
    wrong = [s for s in stated if s[1] != on_disk]
    assert not wrong, f"{on_disk} wrap-*.sh on disk, but these say otherwise: {wrong}"


def test_smoke_test_rule_covers_the_wrapper_that_takes_a_binary():
    """Issue #95: `wrapper_deployment` rule 4 assumes `--version` reaches a tool.
    `wrap-verilator-sim.sh` takes a simulation binary instead, so the rule has to
    say what that wrapper returns - a rule that is silent lets the same FAIL mean
    either "broken" or "mis-invoked"."""
    stage = (
        _read(INFRA_SKILL)
        .split("## Stage: wrapper_deployment", 1)[1]
        .split("\n## Stage: ", 1)[0]
    )
    flat = " ".join(stage.split())
    assert "`wrap-verilator-sim.sh` takes a simulation binary" in flat
    assert "never a mis-invocation" in flat


INFRA_TOOLS = REPO_ROOT / "plugins" / "infrastructure" / "tools"
MCP_DIR = REPO_ROOT / "plugins" / "infrastructure" / "mcp"
MCP_CONFIGS = sorted(MCP_DIR.glob("mcp-*.json"))
MCP_SERVER_SCRIPTS = frozenset({"mcp-adapter.py", "mcp-session-adapter.py", "mcp-memory.py"})
# The memory server is optional and is not one of the tool servers the stage counts.
OPTIONAL_MCP_CONFIGS = frozenset({"mcp-memory.json"})
MCP_COUNT = re.compile(
    r"(\d+) tool-server|(\d+) tool servers|"
    r"tool-server snippet files written \(target: (\d+)|"
    r'"snippets_expected": (\d+)|"mcp_target": (\d+)',
    re.I,
)


def _mcp_stage() -> str:
    return (
        _read(INFRA_SKILL)
        .split("## Stage: mcp_configuration", 1)[1]
        .split("\n## Stage: ", 1)[0]
    )


def _mcp_servers():
    """(source, server name, server object) for every MCP server the infrastructure
    skill shows as a template and every config on disk."""
    sources = [
        (f"{_rel(INFRA_SKILL)} json block {n}", json.loads(block))
        for n, block in enumerate(JSON_FENCE.findall(_read(INFRA_SKILL)), 1)
        if '"mcpServers"' in block
    ]
    assert sources, "no mcpServers template found in the infrastructure skill"
    sources += [(_rel(p), json.loads(_read(p))) for p in MCP_CONFIGS]
    for source, doc in sources:
        for name, server in doc["mcpServers"].items():
            yield source, name, server


def test_mcp_configs_run_a_server_script_not_a_wrapper():
    """Issue #117: the `mcp_configuration` template set `command` to `wrap-<tool>.sh`,
    contradicting rule 2 directly above it. A wrapper prints one JSON object and
    exits; it does not speak MCP, so a config copied from the template never
    completes `initialize` - and rule 6 writes it over the working config."""
    for source, name, server in _mcp_servers():
        command = server["command"]
        assert not command.endswith(".sh"), f"{source} {name}: command is a wrapper: {command}"
        assert command == "python3", f"{source} {name}: command is {command!r}, not python3"
        script = server["args"][0].rsplit("/", 1)[-1]
        assert script in MCP_SERVER_SCRIPTS, f"{source} {name}: args[0] runs {script!r}"
        assert (INFRA_TOOLS / script).is_file(), f"{source} {name}: {script} not in tools/"


def test_no_mcp_config_credits_an_installer():
    """Issue #117: `mcp-openroad.json` said `install.sh` copies and path-substitutes
    the template. No installer ever has; the user is left with `/absolute/path/to/`."""
    for path in MCP_CONFIGS:
        for name in ("install.sh", "install.ps1", "install.mjs"):
            assert name not in _read(path), f"{_rel(path)} credits {name} with MCP setup"


def test_stated_mcp_count_matches_the_mcp_directory():
    """Issue #117: `mcp-memory.json` was the eleventh file in `mcp/` while the stage
    named ten, so its path was never resolved and every "10" read as wrong.
    Every config on disk must be named in the stage, and each stated count must
    count the tool servers - the files on disk minus the optional ones."""
    stage = _mcp_stage()
    unnamed = [p.name for p in MCP_CONFIGS if p.name not in stage]
    assert not unnamed, f"mcp_configuration does not name {unnamed}"

    tool_servers = len([p for p in MCP_CONFIGS if p.name not in OPTIONAL_MCP_CONFIGS])
    stated = []
    for path in (INFRA_SKILL, INFRA_AGENT):
        for match in MCP_COUNT.finditer(_read(path)):
            stated.append((_rel(path), int(next(g for g in match.groups() if g))))
    assert len(stated) >= 5, f"expected the count in at least 5 places, found {stated}"
    wrong = [s for s in stated if s[1] != tool_servers]
    assert not wrong, f"{tool_servers} tool-server configs on disk, but these say otherwise: {wrong}"
    # No bare "N MCP config" count may survive that could mean all files on disk.
    for path in (INFRA_SKILL, INFRA_AGENT):
        bare = re.findall(r"\ball (\d+) (?:MCP|snippets)", _read(path))
        assert not bare, f"{_rel(path)}: ambiguous MCP count(s) {bare}"


# A metric bullet under `### QoR Metrics to Evaluate`: "- `name`: ...".
QOR_BULLET = re.compile(r"^- `(\w+)`", re.M)


def _agent_qor_keys(text: str) -> set[str]:
    block = text.split("## Stage Agent Output Format", 1)[1]
    return set(json.loads(JSON_FENCE.search(block).group(1))["qor"])


def test_every_infrastructure_qor_key_is_declared_by_the_stage_that_computes_it():
    """Issue #104: two stages had no QoR section, so `install_scripts_generated` was
    declared nowhere, and `dialect_conflicts` was declared by `tool_discovery`
    although only `environment_validation` rule 7 computes it."""
    stages = _stage_sections(_read(INFRA_SKILL))
    declared: dict[str, str] = {}
    for stage, body in stages.items():
        section = _subsection(body, "### QoR Metrics to Evaluate")
        assert section, f"infrastructure stage {stage} has no QoR Metrics to Evaluate"
        for key in QOR_BULLET.findall(section):
            assert key not in declared, f"{key} declared by both {declared[key]} and {stage}"
            declared[key] = stage

    assert declared["dialect_conflicts"] == "environment_validation"
    assert declared["install_scripts_generated"] == "tool_installation"
    assert _agent_qor_keys(_read(INFRA_AGENT)) == set(declared), (
        "the agent's qor block and the stages' declared metrics differ"
    )
    # A stage returns only the metrics it owns, so none is obliged to invent a value.
    assert "omit" in _flat(_read(INFRA_AGENT).split("## Stage Agent Output Format", 1)[1].split("\n## ", 1)[0])


TOOL_COMMANDS = re.compile(r"^\| `([^`]+)` \|", re.M)
ROOT_VAR_ROW = re.compile(r"^\s+- `([^`]+)` \([^)]*\) → `([A-Z_]+)`", re.M)


def test_modulefile_root_vars_are_keyed_by_command():
    """Issue #103: the table was keyed by product name, so the `LLVM` row could never
    match the `llvm-config` entry and a generated LLVM modulefile omitted LLVM_DIR."""
    stage = _stage_sections(_read(INFRA_SKILL))["tool_installation"]
    commands = set(TOOL_COMMANDS.findall(_subsection(stage, "### Package Name Mapping Table")))
    rows = dict(ROOT_VAR_ROW.findall(stage))
    assert len(rows) >= 4, f"expected the root-var rows keyed by command, found {rows}"
    unknown = set(rows) - commands
    assert not unknown, f"root-var rows keyed by something other than a command: {unknown}"
    assert rows["llvm-config"] == "LLVM_DIR"
    assert "`cocotb-config`" in stage.split("Tool-specific root vars", 1)[1].split("###", 1)[0]


def test_custom_module_system_is_warned_about_tcl_modulefiles():
    """Issue #99: both warnings tested `module_system == "none"` only, so a `custom`
    wrapper - the case least likely to read a TCL-classic modulefile - got none, and
    the `$MODULEPATH` registration was presented as universal."""
    flat = _flat(_stage_sections(_read(INFRA_SKILL))["tool_installation"])
    assert flat.count('module_system == "custom"') >= 2, "both guards must name custom"
    assert "TCL classic" in flat and "module_system_detail" in flat
    assert "site's own documentation" in flat, "custom registration must not reuse $MODULEPATH"


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
PRIMARY_COMMAND = re.compile(r"^`([^`]+)`")
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
    for cols in _proprietary_rows(skill):
        primary_match = PRIMARY_COMMAND.match(cols[1])
        if not primary_match:
            continue  # UNVERIFIED, commandless row -- nothing to key a mapping on
        primary = primary_match.group(1)
        assert primary in mapping_keys, (
            f"proprietary primary command {primary!r} has no module-mapping row keyed "
            "on it, so module_discovery cannot upgrade its tool-status entry"
        )


FORMAL_AGENT = REPO_ROOT / "plugins" / "formal" / "agents" / "formal-orchestrator.md"


def test_lec_mismatch_escalates_instead_of_looping_back_to_lec_run():
    """lec_run compares an RTL/golden model against a netlist produced by synthesis,
    a stage it never invokes. Looping an unmatched-points mismatch back to lec_run
    (issue #102, the same unwinnable-loop-back defect as #86) re-runs the same
    comparison against the same unchanged netlist and reproduces the mismatch
    deterministically, burning the cap before escalating. The row must escalate
    immediately instead."""
    agent = _read(FORMAL_AGENT)
    for row in _loop_back_rows(agent):
        if "lec_run: unmatched points" in row:
            assert "escalate" in row, (
                f"lec_run unmatched-points row does not escalate: {row.strip()!r}"
            )
            target = row.split("→", 1)[1].strip() if "→" in row else ""
            assert not target.startswith("lec_run"), (
                "lec_run unmatched-points row loops back to lec_run, which cannot "
                f"regenerate the netlist: {row.strip()!r}"
            )
            return
    pytest.fail("lec_run: unmatched points row not found in Loop-Back Rules")


KNOWLEDGE_FILES = sorted(REPO_ROOT.glob("memory/*/knowledge.md"))
RTL_SKILL = REPO_ROOT / "plugins" / "rtl-design" / "skills" / "rtl-design" / "SKILL.md"

# A backticked command line that invokes slang, e.g. `slang -Weverything top.sv`.
# Prose that names a flag on its own (`--lint-only`) is how the rules forbid it and
# is allowed; only a slang command carrying the flag is a recommendation to run it.
SLANG_COMMAND = re.compile(r"`(slang\s[^`]*)`")
SLANG_BAD_FLAGS = ("--lint-only", "-Wall")

# Orchestrators that write, modify or generate synthesisable RTL (issue #107).
RTL_AUTHORING_AGENTS = frozenset({"rtl-design", "fpga", "soc", "memory-ip", "hls"})


@pytest.mark.parametrize(
    "path",
    AGENT_FILES + SKILL_FILES + KNOWLEDGE_FILES + [SHARED_SECTIONS],
    ids=_rel,
)
def test_slang_is_never_invoked_with_lint_only_or_wall(path):
    """Issue #107: `slang --lint-only` skips elaboration and silently drops
    inferred-latch and multiple-driver diagnostics, both ERROR level in lint_check,
    so a latch reports as clean. `-Wall` is not a slang option at all. Neither may
    appear in a slang command an agent could copy."""
    offenders = [
        f"{_rel(path)}:{n}: {cmd}"
        for n, line in enumerate(_read(path).splitlines(), 1)
        for cmd in SLANG_COMMAND.findall(line)
        if any(flag in cmd.split() for flag in SLANG_BAD_FLAGS)
    ]
    assert not offenders, f"slang command uses a flag that hides errors: {offenders}"


@pytest.mark.parametrize("path", AGENT_FILES, ids=_rel)
def test_rtl_lint_gate_present_in_rtl_authoring_agents(path):
    """Issue #107: only rtl-design loads the rtl-design skill, so the other
    orchestrators that touch RTL had no lint rules of their own. Each must carry the
    shared gate's load-bearing clauses, not just its heading; orchestrators that
    author no RTL must not carry it."""
    text = _read(path)
    domain = path.parent.parent.name
    if domain not in RTL_AUTHORING_AGENTS:
        assert "## RTL Lint Gate" not in text, (
            f"{_rel(path)}: carries the RTL Lint Gate but authors no RTL"
        )
        return
    assert "## RTL Lint Gate" in text, f"{_rel(path)}: missing the RTL Lint Gate section"
    for clause in (
        "slang -Weverything --ignore-unknown-modules",
        "Never pass `--lint-only`",
        "`UNVERIFIED`",
        "intent drift",
    ):
        assert clause in text, (
            f"{_rel(path)}: RTL Lint Gate section is missing clause {clause!r}"
        )


def test_rtl_design_rules_do_not_contradict_safe_fsm_recovery():
    """Issue #107: Synthesis Safety told agents to use `unique case` in place of
    casez/casex, which cannot coexist with the `default` recovery arm an FSM needs
    (slang -Wcase-redundant-default), and forbade every `initial` block, including
    the guarded parameter assertion that stops an illegal configuration from
    elaborating. The amended rules must not regress to either."""
    text = _read(RTL_SKILL)
    assert "Use `unique case` with explicit don't-cares" not in text, (
        "rtl-design mandates `unique case` again"
    )
    assert "2. No initial blocks in ASIC RTL" not in text, (
        "rtl-design forbids every `initial` block again, including guarded "
        "parameter assertions"
    )
    for clause in ("-Wcase-redundant-default", "synthesis translate_off", "$fatal"):
        assert clause in text, f"rtl-design Synthesis Safety is missing {clause!r}"


FORMAL_SKILL = (
    REPO_ROOT / "plugins" / "formal" / "skills" / "formal-verification" / "SKILL.md"
)
RTL_AGENT = REPO_ROOT / "plugins" / "rtl-design" / "agents" / "rtl-design-orchestrator.md"
DFT_AGENT = REPO_ROOT / "plugins" / "dft" / "agents" / "dft-orchestrator.md"
VERIFICATION_AGENT = (
    REPO_ROOT / "plugins" / "verification" / "agents" / "verification-orchestrator.md"
)


def test_formal_skill_hands_rtl_bugs_to_the_rtl_flow():
    """The formal agent writes a fix_request for an RTL bug and never edits RTL, but
    the skill told the reader to "fix RTL → re-run FPV". An IDE that loads skills
    without agents (Copilot, Codex) got only the skill, so formal edited RTL itself
    with none of the RTL lint rules behind it."""
    text = _read(FORMAL_SKILL)
    for phrase in ("fix RTL → re-run FPV", "fix RTL or assumption"):
        assert phrase not in text, (
            f"formal skill tells the formal flow to edit RTL itself: {phrase!r}"
        )
    assert "fix_request" in text, "formal skill does not name the fix_request hand-off"


def test_scan_drc_design_fault_escalates_instead_of_retrying_insertion():
    """A Scan DRC error caused by the incoming design (generated clock, uncontrollable
    async reset, latch, combinational loop) is not changed by re-running scan
    insertion. The single `DRC errors > 0 → scan_insertion (max 3×)` row spent three
    insertion runs on it before escalating — the unwinnable loop-back of #86/#102."""
    rows = _loop_back_rows(_read(DFT_AGENT))
    design_rows = [r for r in rows if "caused by the design" in r]
    assert design_rows, "no Loop-Back Rules row for a Scan DRC error caused by the design"
    for row in design_rows:
        target = row.split("→", 1)[1].strip() if "→" in row else ""
        assert target.startswith("escalate"), (
            f"design-caused Scan DRC row does not escalate: {row.strip()!r}"
        )
    for row in rows:
        if row.startswith("- scan_insertion FAIL") and "→" in row:
            target = row.split("→", 1)[1].strip()
            if target.startswith("scan_insertion"):
                assert "repairable by insertion" in row, (
                    "a scan_insertion retry row is not limited to errors insertion "
                    f"can repair: {row.strip()!r}"
                )


def test_rtl_unverified_handoff_has_a_producer_and_consumers():
    """rtl-design labels conclusions no tool proved `UNVERIFIED`. Unless the list is
    written to design_state and read downstream, the label is where the claim stops:
    formal and verification never learn which claims were left for them."""
    assert "Unverified-claims list" in _read(RTL_SKILL), (
        "rtl-design rtl_signoff no longer outputs the unverified-claims list"
    )
    assert '"unverified"' in _read(RTL_AGENT), (
        "rtl-design-orchestrator does not write rtl.unverified to design_state"
    )
    for agent in (FORMAL_AGENT, VERIFICATION_AGENT):
        assert "rtl.unverified[]" in _read(agent), (
            f"{_rel(agent)}: does not read the RTL unverified-claims hand-off"
        )


@pytest.mark.parametrize("path", AGENT_FILES + SKILL_FILES, ids=_rel)
def test_suspected_rtl_schema_carries_basis(path):
    """A fix_request's `suspected_rtl` is routed to directly by the RTL orchestrator.
    Without `basis`, a location guessed from a symptom is indistinguishable from one
    traced in a waveform, and a misdiagnosed location is the usual cause of a loop
    that reaches the iteration cap."""
    for block in JSON_FENCE.findall(_read(path)):
        if '"suspected_rtl": {' in block:
            assert '"basis"' in block, (
                f"{_rel(path)}: fix_request schema shows suspected_rtl without basis"
            )


def test_rtl_design_scopes_out_testbenches():
    """The Copilot adapter applies rtl-design to every `**/*.sv`, testbenches
    included. The exemption lived only in the agents' shared RTL Lint Gate, so an
    IDE loading the skill alone applied the synthesis rules to testbench code."""
    text = _read(RTL_SKILL)
    assert "Testbenches (`*_tb.sv`, `tb_*.sv`" in text, (
        "rtl-design skill does not scope testbenches out of the RTL rules"
    )


# --- issue #83: a lint failure caused by the input set is not an RTL defect ----
# A stale generated header tree listed first on the include path produced
# duplicate-declaration and undeclared-identifier fatals. The single
# `lint_check FAIL -> rtl_coding` row sent that to the stage that edits RTL, where
# the plausible "fix" deletes a real port.

SCHEMA = REPO_ROOT / "docs" / "design_state.schema.json"
RTL_FLOW_DOC = REPO_ROOT / "docs" / "RTL_Design_Flow.md"
RTL_KNOWLEDGE = REPO_ROOT / "memory" / "rtl-design" / "knowledge.md"
ENUM_LINE = re.compile(r'"failure_class": "(none \|[^"]*)"')


def _flat(text: str) -> str:
    return " ".join(text.split())


def _stage_sequence(text: str) -> list[str]:
    line = text.split("## Stage Sequence", 1)[1].strip().splitlines()[0]
    return [stage.strip() for stage in line.split("→")]


def test_input_setup_always_escalates():
    """A wrong input set reproduces verbatim on a retry, and the artifact was never
    evaluated: the class must map to escalate everywhere the mapping is written,
    and the schema must reject any other pairing."""
    import json

    assert _retry_mapping(PIPELINE_SKILL)["input_setup"] == "escalate"
    assert _retry_mapping(SHARED_SECTIONS)["input_setup"] == "escalate"

    schema = json.loads(_read(SCHEMA))
    assert "input_setup" in schema["$defs"]["historyFailureClass"]["enum"]
    rows = {
        rule["if"]["properties"]["failure_class"]["const"]:
            rule["then"]["properties"]["retry_strategy"]["const"]
        for rule in schema["$defs"]["historyEntry"]["allOf"]
    }
    assert rows["input_setup"] == "escalate"
    assert set(rows) == set(FAILURE_CLASSES), "schema map and FAILURE_CLASSES differ"

    decision_table = _read(PIPELINE_SKILL).split(
        "### Programmatic branching on standardized history[] fields", 1
    )[1]
    row = next(
        (line for line in decision_table.splitlines() if "`input_setup`" in line), ""
    )
    assert "never re-dispatch" in row and "never open a `fix_request`" in row, (
        "pipeline decision table has no input_setup row that forbids a retry"
    )


def test_no_loop_back_row_overrides_input_setup():
    """The shared section says a Loop-Back Rules row with iterations left is not
    overridden by a mapped `escalate`. Left unqualified, that sentence sends
    `input_setup` straight back down the row it was created to bypass."""
    flat = _flat(_read(SHARED_SECTIONS))
    assert "no Loop-Back Rules row overrides it" in flat
    assert "the tool ran correctly on the wrong inputs" in flat


@pytest.mark.parametrize("path", AGENT_FILES, ids=_rel)
def test_failure_class_enum_lists_input_setup(path):
    """The enum strings are hand-written in every agent, outside the synced blocks.
    An agent copies its `failure_class` from them, so a value missing here is a value
    that agent cannot record."""
    enums = ENUM_LINE.findall(_read(path))
    assert enums, f"{_rel(path)}: no failure_class enum found"
    for enum in enums:
        values = {v.strip() for v in enum.split("|")}
        assert values == set(FAILURE_CLASSES), (
            f"{_rel(path)}: failure_class enum differs from the mapping table: "
            f"{sorted(values ^ set(FAILURE_CLASSES))}"
        )


_CLASS_ALTERNATION = "|".join(sorted(FAILURE_CLASSES - {"none"}, key=len, reverse=True))
ROW_NAMES_A_CLASS = re.compile(
    r"`(?:" + _CLASS_ALTERNATION + r")`|\"(?:" + _CLASS_ALTERNATION + r"):"
)


@pytest.mark.parametrize("path", AGENT_FILES, ids=_rel)
def test_every_fail_or_warn_loop_back_row_names_a_failure_class(path):
    """Issue #93: a Loop-Back Rules row sends a FAIL/WARN to another stage, but
    only 3 of 88 rows across the agents named the `failure_class` the resulting
    `history[]` entry must carry -- every other row left it to be inferred from
    the condition prose at record time. Skip `meta` (no Loop-Back Rules section,
    per test_decision_enum_lists_loop_back_for_agents_with_loop_back_rules) and any
    row whose target is `proceed`: those WARNs never block sign-off and produce no
    escalation to classify."""
    text = _read(path)
    if path.parent.parent.name == "meta":
        pytest.skip("pipeline-orchestrator has no Loop-Back Rules section")
    if "## Loop-Back Rules" not in text:
        pytest.skip("agent has no Loop-Back Rules section")
    for row in _loop_back_rows(text):
        condition = row.split("→", 1)[0] if "→" in row else row
        if "FAIL" not in condition and "WARN" not in condition:
            continue
        target = row.split("→", 1)[1].strip() if "→" in row else ""
        if target.startswith("proceed"):
            continue
        assert ROW_NAMES_A_CLASS.search(row), (
            f"{_rel(path)}: FAIL/WARN row names no failure_class: {row.strip()!r}"
        )


def test_rtl_design_checks_its_inputs_before_linting_them():
    text = _read(RTL_AGENT)
    stages = _stage_sequence(text)
    assert stages.index("rtl_coding") + 1 == stages.index("design_input_check")
    assert stages.index("design_input_check") + 1 == stages.index("lint_check")

    rows = _loop_back_rows(text)
    input_rows = [r for r in rows if r.startswith("- design_input_check FAIL")]
    assert input_rows, "no Loop-Back Rules row for design_input_check FAIL"
    # Issue #127: a module this run added but did not register in a tool's source
    # list is the run's own omission. Its fix is a list edit, never an RTL edit.
    registration = [r for r in input_rows if "registration only" in r]
    assert len(registration) == 1, "no design_input_check row for an unregistered module"
    assert "edit no RTL" in registration[0] and "max 1×" in registration[0]
    for row in (r for r in input_rows if r not in registration):
        target = row.split("→", 1)[1].strip()
        assert target.startswith("escalate") and "input_setup" in target, (
            f"design_input_check FAIL does not escalate as input_setup: {row.strip()!r}"
        )

    # A lint run whose rule check did not complete is not evidence about the RTL. It
    # reaches rtl_coding only as a parse error in RTL this run wrote, with the input
    # set already checked, and never as `functional`.
    aborted = [r for r in rows if r.startswith("- lint_check FAIL") and "did not complete" in r]
    assert len(aborted) == 2, f"expected two aborted-lint rows, found {aborted}"
    for row in aborted:
        condition, target = (part.strip() for part in row.split("→", 1))
        if target.startswith("rtl_coding"):
            assert "RTL this run wrote" in condition and "design_input_check PASS" in condition
            assert "never `functional`" in target
        else:
            assert target.startswith("escalate") and "input_setup" in target

    completed = [
        r for r in rows
        if r.startswith("- lint_check FAIL")
        and "did not complete" not in r
        and "front-end check" not in r
    ]
    assert len(completed) == 1 and "rule check completed" in completed[0], (
        "the plain lint_check row must say it applies to a completed rule check"
    )

    flat = _flat(text)
    assert "edit no `.v`/`.sv` file" in flat
    assert "Never delete a port, signal or declaration" in flat


def test_rtl_skill_defines_the_input_check_and_aborted_run_rules():
    text = _read(RTL_SKILL)
    stage = text.split("## Stage: design_input_check", 1)[1].split("\n## Stage: ", 1)[0]
    assert text.index("## Stage: rtl_coding") < text.index("## Stage: design_input_check") \
        < text.index("## Stage: lint_check")
    flat = _flat(stage)
    for clause in (
        "first-match-wins",
        "is an **ERROR**, not a warning",
        "check_design_inputs.py",
        '"input_setup"',
        "Never loop back to `rtl_coding`",
    ):
        assert clause in flat, f"design_input_check stage is missing clause {clause!r}"
    for heading in ("### Domain Rules", "### QoR Metrics to Evaluate", "### Output Required"):
        assert heading in stage, f"design_input_check stage has no {heading!r}"

    lint = _flat(text.split("## Stage: lint_check", 1)[1].split("\n## Stage: ", 1)[0])
    for clause in (
        "ran **zero** rules",
        "never `0`",
        "not evidence about the RTL",
        "never classified `functional`",
        "duplicate-declaration **and** undeclared-identifier",
        'non-zero exit is not "lint failed"',
    ):
        assert clause in lint, f"lint_check is missing clause {clause!r}"

    script = RTL_SKILL.parent / "check_design_inputs.py"
    assert script.is_file(), "the skill names check_design_inputs.py but does not ship it"


@pytest.mark.parametrize("path", AGENT_FILES, ids=_rel)
def test_rtl_lint_gate_covers_an_aborted_run(path):
    """soc, fpga, hls and memory-ip lint RTL without loading the rtl-design skill, so
    the aborted-run rule has to reach them through the shared gate."""
    if path.parent.parent.name not in RTL_AUTHORING_AGENTS:
        return
    flat = _flat(_read(path))
    for clause in (
        "An aborted run is not a lint result",
        "zero rules ran",
        "first-match-wins",
        "Record `input_setup`, edit no RTL",
    ):
        assert clause in flat, f"{_rel(path)}: RTL Lint Gate is missing clause {clause!r}"


@pytest.mark.parametrize("path", AGENT_FILES, ids=_rel)
def test_rtl_lint_gate_reaches_the_converted_file_and_every_source_list(path):
    """Issues #126 and #127. Verilator, slang and the simulator all read the
    SystemVerilog; none reads sv2v output or the PD source list. A part-select on a
    function-call result and a module missing from one list both pass every gate the
    agent ran and break the netlist. And the stub carve-out pre-labelled the second
    one's only lint symptom as informational."""
    if path.parent.parent.name not in RTL_AUTHORING_AGENTS:
        return
    flat = _flat(_read(path))
    for clause in (
        "Lint does not prove the downstream front-end accepts the RTL",
        "hierarchy -check",
        "`f(x)[N-1:0]`",
        "never in the converted file",
        "A new module is not integrated until every tool's source list can see it",
        "--rtl-dir",
        "A stub is benign only if you can name that",
        "is not a stub: it is a missing filelist entry",
    ):
        assert clause in flat, f"{_rel(path)}: RTL Lint Gate is missing clause {clause!r}"


IDE_GUARD_FILES = [
    REPO_ROOT / "ides" / "codex" / "AGENTS.md",
    REPO_ROOT / "ides" / "gemini" / "gemini-header.md",
    REPO_ROOT / "ides" / "copilot" / ".github" / "copilot-instructions.md",
]


@pytest.mark.parametrize("path", AGENT_FILES + IDE_GUARD_FILES, ids=_rel)
def test_reporting_obliges_the_gates_a_change_triggers(path):
    """Issue #128: item 1 bound only "every gate named in the task", so fixing the
    one CI step that failed and pushing was compliant, and the next step failed on
    the next run. A file that lands in a path-filtered job's directory is covered by
    that job whether or not the task named it."""
    flat = _flat(_read(path))
    if path in IDE_GUARD_FILES:
        clauses = ("workflow path filters", "not only the step that last failed")
    else:
        clauses = (
            "Run the gates your change triggers, not only the gates you were asked about",
            "path filters, do not guess",
            "run every step of each locally",
            "even if the task never named that job",
        )
    for clause in clauses:
        assert clause in flat, f"{_rel(path)}: missing triggered-gates clause {clause!r}"


@pytest.mark.parametrize("path", AGENT_FILES + IDE_GUARD_FILES, ids=_rel)
def test_hand_off_is_written_whatever_the_outcome(path):
    """Issue #129: the hand-off was produced only by the sign-off stage, so a run
    that honestly withheld signoff handed downstream nothing, and the next domain
    read the absent key as "not reported"."""
    flat = _flat(_read(path))
    if path in IDE_GUARD_FILES:
        clauses = ("Whenever you stop, with or without signoff",)
    else:
        clauses = (
            "Hand off what you established, whatever the outcome",
            "On every termination path",
            "never carried over from an earlier run as if measured",
            "Build a hand-off list in the stage that produces each entry",
            "Withholding signoff (item 7) never means withholding the hand-off",
        )
    for clause in clauses:
        assert clause in flat, f"{_rel(path)}: missing hand-off clause {clause!r}"


def test_rtl_unverified_claims_accumulate_before_signoff():
    """Issue #129: `rtl.unverified[]` was an Output Required of `rtl_signoff` only.
    Each stage that reaches a conclusion without a tool run now appends to it, and a
    CDC stage with no tool turns every reasoned crossing into a claim."""
    skill = _read(RTL_SKILL)
    for stage in ("rtl_coding", "lint_check", "cdc_rdc_analysis"):
        body = skill.split(f"## Stage: {stage}", 1)[1].split("\n## Stage: ", 1)[0]
        assert "Unverified-claims entries" in body, f"{stage} does not append unverified claims"
    cdc = _flat(skill.split("## Stage: cdc_rdc_analysis", 1)[1].split("\n## Stage: ", 1)[0])
    assert "No CDC tool available: the stage is NOT RUN, not PASS" in cdc
    assert "handed off on every termination path" in _flat(skill)

    agent = _flat(_read(RTL_AGENT))
    for clause in (
        "Write it on every termination path",
        "`rtl.files[]` is the block's complete current file set",
        "`true` only when measured clean in this run",
    ):
        assert clause in agent, f"rtl-design-orchestrator is missing {clause!r}"


def test_fix_request_gate_covers_every_gate_the_edit_affects():
    """Issue #128: Behaviour Rule 10 closed a fix_request on `lint_check` alone, so a
    repair that broke a synchroniser or a timed path was marked fixed."""
    rule = next(
        line for line in _read(RTL_AGENT).splitlines() if line.startswith("10. Fix-request gate")
    )
    for clause in (
        "every gate the edit could affect",
        "re-run `cdc_rdc_analysis`",
        "`synth_check`",
        "front-end check",
        "reported NOT RUN with the reason",
    ):
        assert clause in rule, f"Behaviour Rule 10 is missing {clause!r}"


def test_frontend_and_black_box_failures_have_a_route():
    """Issue #126: a yosys syntax error in synth_check had no Loop-Back row, so it had
    no classified route back to the stage that wrote the construct. Issue #127:
    synthesis checked for black boxes but had no row for one either."""
    rtl_rows = _loop_back_rows(_read(RTL_AGENT))
    parse = [r for r in rtl_rows if r.startswith("- synth_check FAIL (parse")]
    assert parse and parse[0].split("→", 1)[1].strip().startswith("rtl_coding")
    assert any(r.startswith("- lint_check FAIL (front-end check") for r in rtl_rows)

    synth_agent = REPO_ROOT / "plugins" / "synthesis" / "agents" / "synthesis-orchestrator.md"
    black_box = [r for r in _loop_back_rows(_read(synth_agent)) if "black box" in r]
    assert len(black_box) == 2, "synthesis needs a first-party and a missing-view black-box row"
    for row in black_box:
        assert row.split("→", 1)[1].strip().startswith("escalate") and "input_setup" in row

    knowledge = _flat(_read(RTL_KNOWLEDGE))
    assert "iverilog -Wall out.v" not in knowledge, "knowledge still parses sv2v output with iverilog"
    assert "a Surelog-fronted synth_check passes RTL that breaks PD" in knowledge


def test_rtl_flow_doc_and_knowledge_follow_the_agent():
    """The flow doc's shared-state object names the new stage (its stage sequence is
    checked for every flow doc below), and the knowledge file is read before the
    first stage - the cheapest place to stop the misroute."""
    assert '"design_input_check"' in _read(RTL_FLOW_DOC)

    knowledge = _flat(_read(RTL_KNOWLEDGE))
    for clause in ("first-match-wins", "zero rules ran", "user-override"):
        assert clause in knowledge, f"rtl-design knowledge.md is missing {clause!r}"


# --- issue #118: flow docs point at the agent instead of restating its rules ----
# Each docs/*Flow*.md restated its orchestrator's loop-back rules in a table and a
# system-prompt block. The agents were corrected (#86, #102, #113, #83) and the
# docs were not, so 8 of 13 disagreed - three describing loop-backs the agent
# escalates instead. The agent file is the one copy; the docs link to it.

FLOW_DOCS = {
    "Architecture_Evaluation_Flow.md": "architecture/agents/architecture-orchestrator.md",
    "Compiler_Toolchain_Flow.md": "compiler/agents/compiler-orchestrator.md",
    "DFT_Flow.md": "dft/agents/dft-orchestrator.md",
    "Embedded_Firmware_Flow.md": "firmware/agents/firmware-orchestrator.md",
    "Formal_Verification_Flow.md": "formal/agents/formal-orchestrator.md",
    "FPGA_Emulation_Flow.md": "fpga/agents/fpga-orchestrator.md",
    "Functional_Verification_Flow.md": "verification/agents/verification-orchestrator.md",
    "HLS_Flow.md": "hls/agents/hls-orchestrator.md",
    "Infrastructure_Setup_Flow.md": "infrastructure/agents/infrastructure-orchestrator.md",
    "Logic_Synthesis_Flow.md": "synthesis/agents/synthesis-orchestrator.md",
    "Memory_IP_Design_Flow.md": "memory-ip/agents/memory-ip-orchestrator.md",
    "PD_Flow_Architecture.md": "pd/agents/physical-design-orchestrator.md",
    "RTL_Design_Flow.md": "rtl-design/agents/rtl-design-orchestrator.md",
    "SoC_IP_Integration_Flow.md": "soc/agents/soc-integration-orchestrator.md",
    "STA_Flow.md": "sta/agents/sta-orchestrator.md",
}
# A restated rule, in any of the forms the docs used.
RESTATED_RULES = re.compile(
    r"LOOP-BACK RULES:|^#+ .*Loop-Back Rules|\|\s*Loops? back to\s*\||"
    r"^## Failure Escalation|loop back to|→ back to",
    re.I | re.M,
)


def test_every_flow_doc_is_mapped_to_its_agent():
    on_disk = {p.name for p in (REPO_ROOT / "docs").glob("*Flow*.md")}
    assert on_disk == set(FLOW_DOCS), f"unmapped or missing flow docs: {on_disk ^ set(FLOW_DOCS)}"


@pytest.mark.parametrize("doc", sorted(FLOW_DOCS))
def test_flow_docs_do_not_restate_loop_back_rules(doc):
    text = _read(REPO_ROOT / "docs" / doc)
    restated = [m.group(0) for m in RESTATED_RULES.finditer(text)]
    assert not restated, f"docs/{doc} restates loop-back rules: {restated}"

    agent = REPO_ROOT / "plugins" / FLOW_DOCS[doc]
    assert f"](../plugins/{FLOW_DOCS[doc]})" in text, f"docs/{doc} does not link to {_rel(agent)}"
    assert "## Loop-Back Rules" in _read(agent), f"{_rel(agent)} has no Loop-Back Rules"


@pytest.mark.parametrize("doc", sorted(FLOW_DOCS))
def test_flow_doc_stage_sequence_matches_the_agent(doc):
    text = _read(REPO_ROOT / "docs" / doc)
    section = re.split(r"^#+ (?:\d+\. )?Stage Sequence\s*$", text, maxsplit=1, flags=re.M)
    assert len(section) == 2, f"docs/{doc} has no Stage Sequence heading"
    line = next(l for l in section[1].splitlines() if "→" in l)
    doc_stages = [stage.strip() for stage in line.split("→")]
    agent = _read(REPO_ROOT / "plugins" / FLOW_DOCS[doc])
    assert doc_stages == _stage_sequence(agent)


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


ARCH_AGENT = REPO_ROOT / "plugins" / "architecture" / "agents" / "architecture-orchestrator.md"
REFINEMENT_REQUESTERS = {
    "synthesis": REPO_ROOT / "plugins" / "synthesis" / "agents" / "synthesis-orchestrator.md",
    "pd": REPO_ROOT / "plugins" / "pd" / "agents" / "physical-design-orchestrator.md",
    "sta": REPO_ROOT / "plugins" / "sta" / "agents" / "sta-orchestrator.md",
}
REFINEMENT_HEADING = "## Architecture Refinement Request"


def test_architecture_persists_candidates_and_resumes_from_them():
    """Issue #35: candidates lived only in session context, so a downstream failure
    restarted exploration from nothing. The orchestrator must persist every candidate
    and, when flagged, re-enter at perf_modelling from them."""
    text = _read(ARCH_AGENT)
    rule = text.split("10. Candidate persistence and refinement mode:", 1)
    assert len(rule) == 2, "architecture orchestrator lost Behaviour Rule 10"
    rule = rule[1].split("\n<!-- BEGIN SHARED", 1)[0]

    assert "`design_state.architecture.candidates[]`" in rule
    assert "rejected" in rule and "never clear the array" in rule, (
        "rejected candidates must persist, and the array is upserted, not rewritten"
    )
    assert "start at `perf_modelling`" in rule, "refinement mode does not enter at perf_modelling"
    assert "candidates[]` is empty" in rule, "no fallback for a state with no persisted candidates"
    assert "refinement_history[]" in rule, "a serviced request is not archived"
    # The flag is cleared only on sign-off; an escalated refinement run must leave it set.
    assert "only when `arch_signoff` passes" in rule

    read = text.split("## Design State", 1)[1].split("### Write", 1)[0]
    assert "`architecture`" in read, "the session-start read does not extract architecture"

    merge = JSON_FENCE.findall(text.split("Domain fields to merge:", 1)[1])[0]
    for field in ('"candidates"', '"rejection_reason"', '"refinement_request"', '"refinement_history"'):
        assert field in merge, f"design_state merge block lacks {field}"

    record = JSON_FENCE.findall(text.split("### Write (session end)", 1)[1])[0]
    for field in ("candidates_evaluated", "winning_candidate_profile", "refinement_of"):
        assert field in record, f"experience record lacks key_metrics.{field}"


@pytest.mark.parametrize("domain", sorted(REFINEMENT_REQUESTERS))
def test_downstream_refinement_request_is_narrow(domain):
    """The refinement request is the one place a downstream domain writes architecture
    state. It must be limited to the flag and the request, and never overwrite an open one."""
    text = _read(REFINEMENT_REQUESTERS[domain])
    assert text.count(REFINEMENT_HEADING) == 1, f"{domain} lacks the refinement section"
    section = text.split(REFINEMENT_HEADING, 1)[1].split("\n## ", 1)[0]
    assert "set only these two keys" in section
    # Collapse newlines: the forbidden list wraps across lines.
    forbid = " ".join(section.split()).split("never touch", 1)[1].split(" field", 1)[0]
    for field in ("`candidates[]`", "`selected_candidate`", "`signoff`"):
        assert field in forbid, f"{domain} section does not forbid touching {field}"
    assert "Do not overwrite an open request" in section
    assert "nothing dispatches it" in section, "the section implies automatic re-entry"

    read = text.split("## Design State", 1)[1].split("### Write", 1)[0]
    assert "`architecture`" in read, f"{domain} never reads architecture.selected_candidate"


def test_only_designated_domains_request_refinement():
    """Any other domain writing refinement_needed would be an unreviewed cross-domain write."""
    allowed = {ARCH_AGENT, *REFINEMENT_REQUESTERS.values()}
    offenders = [
        _rel(path) for path in AGENT_FILES
        if path not in allowed and "refinement_needed" in _read(path)
    ]
    assert not offenders, f"refinement_needed referenced outside the designated agents: {offenders}"
