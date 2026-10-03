# Infrastructure Setup Flow
## Orchestrator + Stage Skill

**Plugin:** `chip-design-infrastructure`
**Agent:** [`infrastructure-orchestrator.md`](../plugins/infrastructure/agents/infrastructure-orchestrator.md)
**Skill:** [`infrastructure/SKILL.md`](../plugins/infrastructure/skills/infrastructure/SKILL.md)

This document is a map of the flow. The agent and the skill are authoritative. Tool tables,
probe commands, wrapper and MCP config lists, and their counts live there and are not repeated
here, because a restated copy drifts (see #118).

---

## 1. Architecture Overview

Infrastructure is stage 0 of the pipeline. It prepares a workstation before any design-domain
orchestrator runs:

- it finds out which EDA tools exist, on `PATH` or behind a module system;
- it generates (never runs) install scripts for the ones that are missing;
- it deploys shell wrappers that turn 10,000–50,000-line tool logs into one compact JSON object;
- it writes MCP server configs so domain agents can call those wrappers as tools.

Every other orchestrator depends on it without reading its output directly. The domain skills
assume the wrappers and MCP servers it sets up, and fall back to direct execution, with raw logs
filling the context, when they are absent.

```
host ──► tool_discovery ──► module_discovery ──► tool_installation
                                                       │ (scripts only)
         environment_validation ◄── mcp_configuration ◄── wrapper_deployment
                │
                ▼
     tool-manifest.json + environment.signoff
```

---

## 2. Shared State

Infrastructure keeps its state in files in the working directory. Each file has one writer.

| File | Written by | Read by | What it is |
|---|---|---|---|
| `tool-status.json` | `tool_discovery`, updated in place by `module_discovery` | every later stage | The **only** per-tool record: `tool`/`command` (always the executable name, never the product name), `status`, `version`, `path`, `role`, `dialect`, module fields, and `python_env` |
| `module-status.json` | `module_discovery` | `tool_installation`, `environment_validation` | Which module system exists (`module_system`) and whether its listing can be trusted (`module_listing`) — two independent facts |
| `load-modules.sh` | `module_discovery`, only when some tool qualifies | the user | `module load` lines with the selected versions |
| `install-missing-tools/install-<tool>.sh` | `tool_installation` | the user | One script per `MISSING` tool. **Never executed by the flow** |
| `plugins/infrastructure/mcp/mcp-*.json` | `mcp_configuration` | the user, who pastes them into `.claude/settings.json` | MCP configs with resolved absolute paths |
| `tool-manifest.json` | `environment_validation` | the user, a later re-run | A validation **receipt**: what the stage measured (Python env liveness, wrapper bits, MCP presence, dialect conflicts, verdict). It references `tool-status.json` rather than copying it |
| `design_state.json` | the orchestrator, at session end | the pipeline | `environment.{tools_validated, pdk_installed, signoff}` and a `history[]` entry |

The schemas are in each stage's **Output Required** in the skill.

---

## 3. Stage Sequence

```text
tool_discovery → module_discovery → tool_installation → wrapper_deployment → mcp_configuration → environment_validation
```

Loop-back rules — the target stage, the iteration cap, and which failures escalate
instead of looping — are in `## Loop-Back Rules` of [`infrastructure-orchestrator.md`](../plugins/infrastructure/agents/infrastructure-orchestrator.md). That file is
authoritative; this document does not restate them.

---

## 4. Stage Summaries

Each stage's rules are in the skill under `## Stage: <name>`.

- **`tool_discovery`.** Probes every open-source and proprietary tool and records the active
  Python environment (`module`, `custom` or `system`). Each entry carries a `role` (what the tool
  does) and a `dialect` (whose command-line vocabulary it speaks). Proprietary tools are detected
  and version-probed, never installed.
- **`module_discovery`.** Classifies the module system, proves the listing can be obtained by
  walking an invocation ladder, and maps module-only tools back into `tool-status.json`
  (`FOUND_PREFER_MODULE`, `MISSING_LOAD_MODULE`). An unlistable module system is a WARN, and it
  becomes an escalation when a critical-path tool is still missing, because those tools were
  never checked.
- **`tool_installation`.** Generates one install script per `MISSING` tool, with TCL modulefiles,
  using the detected OS and package manager. Python packages install through
  `python_env.exec -m pip`. It never runs anything, so a `MISSING` status can only change after
  the user runs a script.
- **`wrapper_deployment`.** Makes the wrappers executable and smoke-tests each with `--version`.
  The expected answer is `WARN` with `verified: false`: the wrapper ran and emitted valid JSON,
  but there was no design result.
- **`mcp_configuration`.** Writes the MCP configs with resolved paths and prints them. It never
  edits `.claude/settings.json`; registering the servers is the user's step.
- **`environment_validation`.** Re-runs detection exactly as `tool_discovery` does, and checks that
  the Python environment is still live, that the wrappers are executable and that the MCP files
  are present. It reports same-role/different-dialect coexistence and writes `tool-manifest.json`.
  A missing critical-path tool (`yosys`, `verilator`, `openroad`, `sta`) escalates rather than
  looping, because no stage of this flow can install it.

---

## 5. How Domain Agents Run a Tool

The skill's **MCP Architecture — Two Tiers** section defines the order. In short:

1. **Session MCP:** a persistent Tcl process for tools that support one, when the design is
   already loaded (ECO loops).
2. **Batch MCP:** one wrapper run per call, returning the wrapper's JSON.
3. **Wrapper script:** run directly through Bash when no MCP server is registered.
4. **Direct execution:** the last resort; the raw log goes into context.

Full-flow tools (LibreLane/OpenLane 2, ORFS, full-system gem5) run for 30 minutes to hours and
are never called through MCP. Agents launch them through Bash and read their `metrics.json` /
`stats.txt`.

Every wrapper prints one JSON object (`status`, `verified`, `summary`, `errors`, `warnings`,
`raw_log`) on every run, whatever the exit code. **`verified: false` is not a pass**: the agent
reads `raw_log` or the tool's report before assigning a stage status. The schema is in
`## Stage: wrapper_deployment`.

---

## 6. Adding a Tool

A tool touches several places, and the stated counts are checked by
`tests/test_agent_contract.py`:

1. **Discovery.** Add a row to the skill's Open-Source or Proprietary table, keyed by its
   command, with `role` and `dialect`. Add it to the agent's **Tool Options** too. A
   proprietary tool needs a probe that is verified or marked `UNVERIFIED`. It also needs a
   row in `module_discovery`'s Module-to-tool mapping table keyed on that same command --
   `test_critical_path_tools_are_keyed_by_command` fails without one.
2. **Installation.** Add it to the skill's Package Name Mapping Table if it can be installed.
3. **Wrapper (if it has one).** Add `plugins/infrastructure/tools/wrap-<tool>.sh`, which must
   follow the Wrapper JSON Output Schema. Update every stated wrapper count in the skill and
   agent; `test_stated_wrapper_count_matches_the_tools_directory` fails until they all match.
4. **MCP config (if it has one).** Add `plugins/infrastructure/mcp/mcp-<tool>.json`, running
   `python3` with `mcp-adapter.py` (batch) or `mcp-session-adapter.py` (session), never the
   wrapper itself. Name it in `mcp_configuration` and update the tool-server count.
5. **Critical path.** Only if downstream flows cannot run without it, extend the critical-path
   set. Match on the command key, never the product name.

---

## 7. Handoff

On sign-off the orchestrator sets `environment.signoff=true` in `design_state.json`; a
configured `environment_validation` checkpoint holds it for human approval first.

No domain orchestrator reads `environment.signoff` today. The skill's Execution Hierarchy
instead tells each domain agent to check whether its MCP server is active in
`.claude/settings.json` before falling back to the wrapper. That check matters:
`mcp_configuration` writes and prints the configs, but they do nothing until the user pastes them
into `.claude/settings.json`.

---

## 8. Orchestrator System Prompt

The orchestrator's system prompt is its agent definition, [`infrastructure-orchestrator.md`](../plugins/infrastructure/agents/infrastructure-orchestrator.md): stage
sequence, loop-back rules, stage gating and escalation. This document does not
restate it.
