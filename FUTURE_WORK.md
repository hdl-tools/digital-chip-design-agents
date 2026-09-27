# Future Work

Items deferred from the two-tier agent memory system implementation (see `memory/README.md`).
Track these as follow-up issues after the initial memory system ships.

## 1. Memory-Keeper Skill ✓ IMPLEMENTED

**Status:** Shipped — `plugins/infrastructure/skills/memory-keeper/`

A skill that periodically distils `memory/<domain>/experiences.jsonl`
into an updated `memory/<domain>/knowledge.md` summary. Implementation includes:

- `SKILL.md` — three-stage agent skill (load_experiences → distil_knowledge → report)
- `distill.py` — CLI helper: parses JSONL, computes issue/fix pairs, metric ranges, and
  tool-flag candidates; emits a structured JSON summary for the agent to use
- Invocable via `/chip-design-infrastructure:memory-keeper --domain <name>` or `--all`
- Threshold guard: skips domains with fewer than N records (default: 5)

## 2. Semantic Search Over Experiences ✓ IMPLEMENTED (phased)

**Status:** Shipped (phased) — `tools/experience_search.py`,
`plugins/infrastructure/tools/mcp-memory.py`, and
`plugins/infrastructure/mcp/mcp-memory.json`.

An MCP memory server (`chip-design-memory`, tool `query_experiences`) that lets
orchestrators query experience records by similarity
(e.g., "what fixed WNS issues on sky130 before?") rather than full-file read.

Built **fallback-first** to respect both the deferral (the experience log must be
large enough to justify embeddings — target ~50 records/domain) and the repo's
zero-dependency, stdlib-only convention:

- **Default keyword backend** — pure-stdlib TF-IDF + cosine over the free-text
  fields. Adds value at any dataset size; no index or dependency required.
- **Optional embedding backend** — wired in but dormant; activates only when an
  embedding library is supplied via `get_embedding_backend()` **and** the domain
  has ≥ `--min-records` records (default 50). Vectors cache in a stdlib `sqlite3`
  index keyed by record content hash (incremental re-embedding via `--reindex`).
  Below the threshold or with no backend, it transparently falls back to keyword
  and flags `fell_back: true`.
- All 16 orchestrators carry an optional session-start read-path note that calls
  the MCP tool when available and otherwise proceeds with `knowledge.md`.

The original options below were **rejected** to preserve the zero-dependency
convention (no new deps, no native extensions, no external service); a deployment
that wants true semantic ranking only needs to implement `get_embedding_backend`:
- ~~SQLite + sqlite-vec extension~~ (sqlite-vec is a native extension, not stdlib)
- ~~Chroma or Qdrant (local Docker container)~~
- ~~Hosted: Pinecone, Weaviate Cloud~~

## 3. Cross-Design Metric Trending ✓ IMPLEMENTED

**Status:** Shipped — `tools/qor_trends.py`

A reporting utility that reads all `memory/<domain>/experiences.jsonl` files and
produces QoR trend tables and optional matplotlib charts for a named design. Use cases:

- Regression detection: flags when a metric degrades across runs (⚠ alert column)
- PDK comparison: compare WNS/area across sky130 vs GF180 for the same RTL — use `--group-by pdk` (note: tools/qor_trends.py applies `--pdk` filtering before `--group-by`, so combining `--group-by pdk` with a specific `--pdk VALUE` will collapse to a single group and defeat the comparison)
- Tool comparison: compare Yosys vs DC synthesis area for the same design — use `--group-by tool` (note: tools/qor_trends.py applies `--tool` filtering before `--group-by`, so combining `--group-by tool` with a specific `--tool VALUE` will collapse to a single group and defeat the comparison)

Usage:
```bash
# Text table for all domains where design "aes_core" appears
python3 tools/qor_trends.py --design aes_core

# WNS trend for synthesis only
python3 tools/qor_trends.py --design aes_core --domain synthesis --metric wns_ns

# Save a matplotlib chart
python3 tools/qor_trends.py --design aes_core --plot --output aes_core_qor.png
```

## 4. Infrastructure Orchestrator Memory ✓ IMPLEMENTED

**Status:** Shipped — `memory/infrastructure/` + infrastructure-orchestrator opt-in memory rule.

Track tool versions, module versions, and MCP/setup configuration across runs in
`memory/infrastructure/`, following the two-tier memory pattern. Because the original deferral
rationale still holds — infrastructure state is environment-specific (machine A ≠ machine B),
tool versions are better pinned in a lockfile, and MCP config lives in `.claude/settings.json` —
tracking is **opt-in and default off**:

- Enabled only when `design_state.pipeline_config.track_infrastructure == true` or the
  orchestrator is invoked with `--track-memory`; otherwise no `memory/infrastructure/` I/O occurs.
- Records are **environment-keyed** (`environment` fingerprint: `host`, `os`, `os_version`,
  `arch`) so cross-machine data never collides.
- `key_metrics.tool_versions` captures a per-tool version map at `environment_validation` — the
  primary value-add for diagnosing repeated version-mismatch debugging across sessions.
- Fully integrated with `memory-keeper`: `infrastructure` is registered in `distill.py`
  `VALID_DOMAINS`/`METRIC_FIELDS` and the SKILL Domains table, so quirks distil into
  `memory/infrastructure/knowledge.md` over time.

See `memory/README.md` § "Infrastructure memory (opt-in, environment-keyed)" and the
infrastructure-orchestrator § "Infrastructure Memory" for full details.

## 5. Central "Design" State ✓ IMPLEMENTED

**Status:** Shipped — all 16 orchestrators read `design_state.json` on entry and write their
domain sub-object plus a `history[]` entry on exit. Schema covers `spec`, `interfaces`,
`constraints`, `architecture`, `rtl`, `verification_status`, `synthesis`, `dft`, `sta`,
`hls`, `pd`, `soc`, `compiler`, `firmware`, `fpga`, `environment`, `tool_feedback`,
`pending_approval`, and `history[]`.

Today each orchestrator maintains its own session-scoped state object. There is no shared
artifact that survives an orchestrator boundary, so downstream agents cannot see upstream
decisions (e.g., RTL coding cannot query the architecture trade-off rationale).

Introduce a persistent `design_state.json` written to the working directory. Every orchestrator
reads it on entry and appends its results on exit. This replaces the ad-hoc inter-orchestrator
handoff packages currently documented in `docs/MASTER_INDEX.md`.

### Minimum fields

```json
{
  "spec": { "raw": "<natural language>", "structured": {} },
  "interfaces": [{ "name": "AXI3-lite", "width": 32, "role": "subordinate" }],
  "constraints": { "clk_mhz": 500, "area_um2": null, "power_mw": null },
  "rtl": { "top_module": null, "files": [], "lint_clean": false, "cdc_clean": false },
  "verification_status": { "coverage_pct": null, "signoff": false },
  "tool_feedback": [],
  "history": []
}
```

`history[]` entries record the agent, stage, decision, reason, and constraint reference so that
the entire evolution of the design is traceable across sessions.

**Prerequisite for:** items 6, 8, 9, 11.

## 6. Continuous Verification Loop

**Status: Shipped** — `plugins/meta/agents/pipeline-orchestrator.md` + structured `fix_request` schema in `design_state.json` (`format_version 1.1`). See `CHANGELOG.md` for details.

**Prerequisite:** item 5 (design_state.json must exist for the fix request handoff).

## 7. Agent Contract Standardization

**Status: Shipped** — All 16 orchestrator `.md` files now emit the extended `output_format`
per stage and the standardized `history[]` entry. `design_state.json` format_version bumped
to `"1.2"`. Canonical schema in `docs/MASTER_INDEX.md`. Programmatic branching decision
table in `plugins/meta/skills/pipeline-orchestration/SKILL.md`.

Shipped schema (replaces the old `recommendation` field):

```json
{
  "stage": "<stage_name>",
  "status": "PASS | FAIL | WARN",
  "confidence": "high | medium | low",
  "failure_class": "none | functional | timing | power_area | drc_lvs | coverage_gap | connectivity | tool_error | spec_gap | resource_limit",
  "qor": {},
  "issues": [{ "severity": "ERROR | WARN", "description": "...", "fix": "..." }],
  "suggested_next_step": "proceed | loop_back_to:<stage> | retry_stage | escalate | abandon",
  "output": {}
}
```

`confidence` (enum `high|medium|low`) drives auto-proceed vs escalate decisions in the
pipeline-orchestrator. `failure_class` feeds the retry strategy table. `suggested_next_step`
supersedes the old `recommendation` string and makes orchestration logic programmatic.

## ~~8. Constraint Awareness~~ ✓ DONE (format_version 1.4)

~~Constraints currently live as prose in SKILL.md files or as file paths (SDC, LEF) in
orchestrator state. Agents embed constraint values in their rules rather than reading them
from a shared source, so a change to the clock target requires editing multiple skill files.~~

Implemented in format_version 1.4: `design_state.constraints` is the single source of truth
for all design constraint values. All 11 constraint-bearing domain SKILL.md files now reference
`design_state.constraints.<key>` instead of hardcoded literals (retained as documented defaults).
Stage-entry validation halts with `pending_approval.type: "constraint_gap"` when required keys
are missing or null. `constraint_ref` in `history[]` entries tags every QoR decision against the
constraint key it evaluated. See `plugins/meta/skills/pipeline-orchestration/SKILL.md`
§ Constraints Schema and `CHANGELOG.md` for full details.

## 9. Architecture Exploration Improvement

The architecture SKILL.md already mandates generating three candidates (conservative,
balanced, aggressive) with a trade-off matrix. The gap is that candidates exist only
in the session context — they are not persisted, and there is no mechanism for a
downstream failure (e.g., synthesis cannot close timing) to trigger a return to
architecture with that constraint violation as input.

**Improvements:**

- Persist the full trade-off matrix to `design_state.json` under
  `architecture.candidates[]` so downstream agents can reference the rejected options.
- Add a `refinement_needed` flag: if synthesis or PD sets
  `design_state.architecture.refinement_needed = true` with a reason, the architecture
  orchestrator re-enters at `perf_modelling` using the persisted candidates as a
  starting point rather than generating from scratch.
- Extend `memory/architecture/experiences.jsonl` schema to record
  `candidates_evaluated` count and `winning_candidate_profile` for cross-design learning.

This reduces early bad decisions without requiring perfect up-front prompts, and
leverages the memory system already in place.

**Prerequisite:** item 5.

## ~~10. Structured Failure Handling~~ ✓ DONE (format_version 1.5)

Implemented in format_version 1.5: every `history[]` entry carries a `retry_strategy`
(`regenerate | refine | escalate | none`) deterministically mapped from `failure_class` via the
authoritative table in `plugins/meta/skills/pipeline-orchestration/SKILL.md` § Failure
Classification & Retry Strategy. The mapping reuses the existing 10-value `failure_class` enum —
the four classes proposed below are reconciled as documented aliases (`invalid_rtl` →
`tool_error`/regenerate, `verification_failure` → `functional`/refine, `interface_mismatch` →
`connectivity`/refine, `incomplete_spec` → `spec_gap`/escalate). The pipeline-orchestrator
decision table branches on `retry_strategy`, and escalations include the `failure_class` plus a
plain-language description of what the user must supply. All 15 history-writing orchestrators,
the example fixtures, and CI (`validate.yml`) were updated.

~~All failures currently land in the same `issues[]` array with only `ERROR | WARN`
severity. Orchestrators apply hardcoded loop-back rules per stage but have no
structured way to distinguish a recoverable code error from an ambiguous spec.~~

**Failure class taxonomy** (maps to `failure_class` field from item 7):

| Class | Definition | Default retry strategy |
|---|---|---|
| `invalid_rtl` | Syntax, lint, or CDC errors in generated RTL | `regenerate` — re-run rtl_coding with error context |
| `verification_failure` | DUT functional bug found by simulation | `refine` — re-run rtl_coding with failing test + waveform |
| `interface_mismatch` | AXI/protocol violation or port width conflict | `refine` — re-run rtl_coding targeting the violated interface |
| `incomplete_spec` | Ambiguous or missing requirement blocks progress | `escalate` — halt and request user clarification |

**Agent behavior changes:**
- Tag every FAIL status with one of the four classes above.
- Attach `retry_strategy` to the issue: `regenerate | refine | escalate`.
- If max loop iterations are reached, the escalation message must include the failure
  class and a plain-language description of what information the user must provide to
  unblock the flow.

**Prerequisite:** item 7 (failure_class field in output contract).

## ~~11. Human-in-the-loop Control Points + Observability~~ ✓ DONE (format_version 1.3)

~~Currently the only human interaction points are invocation and max-iteration escalation.
There are no optional approval gates between pipeline stages, and there is no structured
record of why an agent made a particular decision.~~

Implemented in format_version 1.3: `pipeline_config.checkpoints` config, `approved_checkpoints[]` resume
list, `pending_approval.type` discriminator, per-stage `history[]` trace (one entry per stage),
and checkpoint gate logic in all 15 domain orchestrators. See `plugins/meta/skills/pipeline-orchestration/SKILL.md`
§ Approval Checkpoints.

### Approval Checkpoints

Add a `require_approval` flag to configurable stage transitions in `design_state.json`.
When set, the orchestrator writes a human-readable summary to
`design_state.pending_approval` and halts. The user resumes by setting
`design_state.approved_by_human: true` (manually or via a `--approve` flag).

Suggested default checkpoint positions:
- After `arch_signoff` — before RTL coding begins
- After `rtl_signoff` — before verification or synthesis begins
- Before tape-out (PD `signoff` stage)

### Execution Trace

Each stage completion appends an entry to `design_state.history[]`:

```json
{
  "timestamp": "2026-04-18T10:00:00Z",
  "agent": "architecture-orchestrator",
  "stage": "arch_signoff",
  "decision": "proceed",
  "reason": "Balanced candidate meets timing with >20% WNS headroom.",
  "constraint_ref": "clk_core_500MHz"
}
```

This provides a clear relationship between each decision and its output, and enables
post-run audits without replaying the full agent conversation.

**Prerequisite:** item 5 (design_state.json), item 7 (confidence score informs whether
approval is required).

## 12. New Adjacent Agent Domains

The following domains are adjacent to the current 16-plugin pipeline and are not yet covered.
Each represents a distinct discipline with its own toolchain and sign-off criteria.

> **Implemented:** *Memory IP Design* was previously an unlisted gap and shipped as
> `chip-design-memory-ip` (16th plugin). It owns memory macro selection, array
> architecture, redundancy/repair, and view QA, deferring MBIST insertion to DFT,
> floorplanning to PD, and timing sign-off to STA.

| Domain | Rationale | Key tools |
|--------|-----------|-----------|
| **Power Intent / UPF** | Multi-voltage, low-power design (UPF/CPF authoring, power domain verification, isolation/retention cell insertion). Mandatory for mobile/IoT chips and not covered by RTL, Synthesis, or PD agents. | Synopsys MVSIM, Cadence CPF tools, open-source: uvmf-power |
| **Silicon Validation / Debug** | Post-silicon failure analysis, ATE interface bring-up, scan dump triage, silicon characterisation. Completely unaddressed by any current agent. | Teradyne UltraFLEX, Advantest V93000, internal ATE scripts |
| **Package & Chiplet / 2.5D-3D** | Die-to-die interface definition (UCIe, HBM), bump/RDL floorplanning, package-level SI/PI analysis. Distinct from chip-level PD. | Cadence Sigrity, Synopsys 3DIC Compiler, open-source: KiCad |
| **Security / Hardware Roots-of-Trust** | Side-channel analysis (power/EM), fault injection modelling, secure boot ROM design, PUF integration. Cross-cuts RTL and firmware but warrants its own specialist agent. | ChipWhisperer, SideChannelMarvels, Synopsys DesignWare Security |
| **NoC / Interconnect Design** | Network-on-Chip topology exploration, latency/bandwidth modelling, flit-level simulation. Currently assumed inside SoC integration but deep enough for a dedicated agent. | gem5 (network mode), Noxim, open-source: OpenSoC Fabric |
| **Emulation Platform (ZeBu/Palladium)** | Hardware emulation bringup (Synopsys ZeBu, Cadence Palladium) is distinct from FPGA prototyping — different partitioning problem, transaction-based interfaces, and tool flow. | Synopsys ZeBu, Cadence Palladium, Mentor Veloce |
| **AMS Integration** | Qualifying analog IP blocks (PLLs, ADCs, LDOs, SerDes), generating behavioral/Verilog-A models for digital co-simulation, and guiding analog peripheral firmware bring-up. Scoped as an *integration* agent rather than a full analog design agent (full analog closure requires human waveform review and is not automatable end-to-end). | ngspice, Xyce, Xschem, Spectre (behavioral model generation only) |

**Recommended priority:** Power Intent/UPF and Silicon Validation fill the most immediate gaps
and connect directly to existing agents. AMS Integration adds value for SoC flows that pull in
analog IP. The remaining domains are longer-term additions.

## 13. Domain Breakdown: Sub-Agent Specialisation

Several existing agents cover broad enough scope that splitting them into focused sub-agents
would improve parallelism, reduce context window pressure, and sharpen sign-off criteria.
The central design state (item 5) is a prerequisite for clean handoffs between sub-agents.

### Proposed Splits

**Physical Design → 3 sub-agents** *(highest priority — broadest current scope)*
- `pd-floorplan`: I/O placement, macro placement, power grid planning (70–80% utilisation target)
- `pd-implementation`: Placement, CTS (skew <150 ps), routing, DRC/LVS clean
- `pd-signoff`: Antenna fix, fill insertion, GDS export, tape-out checklist

**Verification → 3 sub-agents** *(after design state is implemented)*
- `verification-tb`: UVM TB architecture, agent design, scoreboard, coverage model definition
- `verification-regression`: Test plan execution, constrained-random stimulus, coverage closure (≥95%)
- `verification-emulation`: Firmware-driven verification on FPGA/emulator prototype

**Firmware → 3 sub-agents** *(after design state is implemented)*
- `firmware-bsp`: Board support package, linker scripts, startup code, peripheral drivers
- `firmware-rtos`: RTOS porting (FreeRTOS/Zephyr), task design, IPC primitives
- `firmware-bringup`: Chip bring-up scripts, JTAG/UART debug, post-silicon smoke tests

**Hold (do not split yet):** STA and DFT — already well-scoped; fragmentation overhead
outweighs benefit at current agent count.

### Pros of Finer-Grained Breakdown

| # | Benefit |
|---|---------|
| 1 | Tighter SKILL.md focus — one clear responsibility per file, easier to maintain |
| 2 | Smaller context window per run — more tokens available for design artefacts |
| 3 | Parallel execution — independent sub-agents (e.g., `pd-floorplan` + `verification-tb`) run concurrently |
| 4 | Deeper tool integration — a dedicated agent can specialise on one tool without cluttering a broad skill |
| 5 | Cleaner per-stage sign-off gates — one well-defined done criterion per agent |

### Cons of Finer-Grained Breakdown

| # | Risk |
|---|------|
| 1 | Cross-agent state explosion — more handoffs break without central design state (item 5) |
| 2 | Orchestration overhead — parent orchestrator must sequence more children; more failure modes |
| 3 | Redundant context loading — shared context (PDK rules, timing targets) re-loaded on each cold start |
| 4 | Marketplace discoverability — 20+ entries increases cognitive load for users choosing an agent |
| 5 | Maintenance burden — more `plugin.json` manifests, SKILL.md files, and memory directories to keep in sync |

**Prerequisite for all splits:** item 5 (central design state) must be implemented first
so sub-agents can share artefacts without dropping data at boundaries.

## 14. Multi-Servicer Fix Dispatch (`route_to`)

The pipeline-orchestrator's `dispatch_to_producer` currently always spawns a single
producer — the RTL orchestrator (`plugins/meta/agents/pipeline-orchestrator.md`,
`dispatch_to_producer` step). This is correct today because RTL is the only
fix-servicer domain: every open `fix_request` is a DUT/formal bug routed back to RTL,
and re-validation is already routed to the originator via `fix_request.created_by`
(`verification-orchestrator` | `formal-orchestrator`).

A machine-readable `route_to` field is **already reserved** in the schema as an optional,
forward-compatible hint (default servicer `rtl-design`) — see
`docs/design_state.schema.json` (`$defs.fixRequest.route_to`) and
`plugins/meta/skills/pipeline-orchestration/SKILL.md` § fix_request Schema. The field is
documented but **not yet consumed** by any dispatch logic, so no schema migration is
required when this lands.

The sibling `analog-chip-design-agents` repo already implements the full pattern: its
pipeline-orchestrator reads `route_to` and dispatches an open fix to one of several
servicer domains (`circuit-design` | `behavioral-modeling` | `custom-layout` |
`em-modeling`), then re-validates via the `created_by` originator. That implementation is
the reference template for digital.

**When to implement:** once digital gains additional fix-servicer domains — i.e. domains
that can *resolve* a fix rather than only *detect* one. Plausible producers beyond RTL
include synthesis (constraint/UPF fixes), PD (DRC/LVS/floorplan fixes), or the new
domains in item 12. Until then, multi-target dispatch would be scaffolding with no
targets to route to.

**Work when it lands:**
- Teach `dispatch_to_producer` to read `fix_request.route_to` and spawn the named servicer
  orchestrator (default `rtl-design` when absent), mirroring analog's routing table.
- Constrain `route_to` to an enum in `docs/design_state.schema.json` once the servicer set
  is fixed (it is an unconstrained optional string today).
- Have detectors (`verification`/`formal`/future producers) set `route_to` when the fix
  belongs to a non-RTL domain; default-absent continues to mean RTL.
- Add positive/negative fixtures exercising each `route_to` target and extend
  `validate.yml`'s schema check accordingly.

**Prerequisite:** item 12 and/or item 13 (additional fix-servicer domains must exist);
item 5 (central design state) for the cross-domain handoff.
