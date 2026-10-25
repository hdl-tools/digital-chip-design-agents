---
name: sta
description: >
  Static timing analysis — multi-corner constraint validation, setup and hold
  analysis, timing exception review, and ECO guidance for closure. Use when
  running timing analysis on a design, reviewing timing violations, guiding
  ECO fixes, or performing timing sign-off for tape-out.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: Static Timing Analysis (STA)

## Invocation

When this skill is loaded and a user presents a timing analysis task, **do not
execute stages directly**. Immediately spawn the
`digital-chip-design-agents:sta-orchestrator` agent and pass the full user
request and any available context to it. The orchestrator enforces the stage
sequence, loop-back rules, and sign-off criteria defined below.

Use the domain rules in this file only when the orchestrator reads this skill
mid-flow for stage-specific guidance, or when the user asks a targeted reference
question rather than requesting a full flow execution.

## Pre-run Context

`<MEM>` below is the resolved memory root, never the literal `memory/` directory: an
explicit `--memory-root`, else `$CHIP_DESIGN_MEMORY_ROOT`, else the central default, else
the in-repo seed (`python3 plugins/infrastructure/skills/memory-keeper/memory_root.py`
prints it; the orchestrator's `## Memory` section is authoritative).

Before executing or advising on **any** stage, read the following files if they exist:

1. `<MEM>/sta/knowledge.md` — known failure patterns, successful tool flags, PDK/tool quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `<MEM>/sta/run_state.md` — current run identity (`run_id`, `design_name`, `tool`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Multi-corner, multi-mode timing analysis, exception review, ECO-guided closure,
and timing sign-off. WNS ≥ 0 and TNS = 0 at all corners required for tape-out.

---

## Supported EDA Tools

### Open-Source
- **OpenSTA** (`sta`) — standalone open-source STA; runs tcl scripts in batch mode (see sequential flow note below)
- **OpenROAD STA subsystem** (`openroad -no_init`) — STA within the OpenROAD PD flow; runs sequentially via tcl script

### Proprietary
- **Synopsys PrimeTime** (`pt_shell`, dialect `synopsys`) — gold-standard multi-corner STA and power analysis
- **Cadence Tempus** (`tempus`, dialect `cadence`) — concurrent multi-mode multi-corner STA with ECO guidance;
  optional, absent on some hosts — use PrimeTime there
- **Synopsys StarRC** (`StarXtract`, dialect `synopsys`) — extraction that produces the SPEF read here
  (wrapper `wrap-starrc.sh`); the PD flow's `extraction` stage owns it

### Sequential Flow Log Review (OpenSTA / OpenROAD STA)

OpenSTA (`sta`) and the OpenROAD STA subsystem (`openroad -no_init`) execute tcl script
commands sequentially. When run in batch mode the agent must parse the output log to
extract timing results — there is no interactive prompt to query mid-run.

**Key log patterns to parse after run completion:**
- `report_timing` output → extract WNS (worst negative slack) and critical path
- `report_tns` output → extract TNS (total negative slack) per corner
- `report_clock_skew` output → global skew and insertion delay per clock group
- `check_timing` → missing constraints, unconstrained endpoints, loops

**Batch invocation:**
```
opensta -no_splash -exit timing_check.tcl > sta.log 2>&1
# or via OpenROAD:
openroad -no_init -exit sta.tcl > sta.log 2>&1
```

Parse `sta.log` after completion. Apply loop-back rules (ECO guidance stage) if
setup/hold violations are found.

---

## Tool Notes: Synopsys PrimeTime (multi-corner) and PrimePower

**Outline — measured notes pending.** Process and standard command names only; no option
recipe below has been verified on this suite's reference host yet. Run through `wrap-pt.sh`.

**Multi-corner, one scenario per corner (DMSA or a single multi-scenario session):**
1. Per corner: `create_scenario` (or one `pt_shell` per corner), then `set link_path` /
   `read_db` the library `.db` of **that** corner, including every macro's `.db`
2. `read_verilog` + `link_design` the post-route netlist; `read_sdc` the one SDC every flow
   shares (record its md5)
3. `read_parasitics` the SPEF of the **RC corner mapped to that library corner** (Cmax with
   the slow library for setup, Cmin with the fast library for hold, unless the PDK's signoff
   table says otherwise) — write the mapping down; a scenario reading the wrong SPEF is the
   most common silent error
4. `report_annotated_parasitics -check` (or the version's equivalent) before any timing
   report — see `multi_corner_analysis` annotation rule 2
5. `update_timing`, then `report_qor`, `report_global_timing`, `report_constraint
   -all_violators`, `report_timing -delay_type max|min`
6. Collect WNS/TNS/violator count per scenario into one table; the corner set comes from
   `design_state.constraints.pvt_corners`

**PrimePower:** `set power_enable_analysis true`, same netlist/SPEF/SDC as the timing
scenario; `read_saif`/`read_fsdb` for vector-based power, otherwise vectorless with
`set_switching_activity` default toggle rate and static probability on inputs; then
`update_power` and `report_power`. **Use the same activity assumption for every compared
flow** (the same default toggle rate, the same input activity, the same SAIF if any) and
record it with the number; a power figure without its activity assumption is not comparable.

---

## Fair Cross-Tool Comparison

When the timing or power of designs implemented by **different tools** is compared (for
example Innovus vs ICC2 vs OpenROAD/LibreLane on one netlist and PDK), every flow is judged
the same way, or the comparison measures the judges rather than the implementations:

1. **Same SDC.** Every flow reads the identical constraints file; record its md5 next to
   each result (`sta.sdc_md5`). A tool-specific SDC variant is a different experiment
2. **Same extractor and tech.** Re-extract every flow's final DEF with one extractor and one
   tech file at the same RC corners (`extraction` in the PD flow). A tool's built-in
   extraction is native
3. **Same STA engine.** Time every flow in one signoff engine and version (`sta.engine`),
   with the same libraries, corners and derates
4. **Same activity assumptions** for power — the same vectorless defaults or the same SAIF
5. **Native reports are recorded but labelled `native`** (`sta.judged_by`). They are useful
   for diagnosing a flow and are never ranked against another flow's signoff numbers
6. A comparison that cannot meet 1–4 (for example no common extractor tech) is reported as
   **indicative**, with the unmet condition named

---

## Stage: constraint_validation

### Validation Checks
1. All clocks defined with correct period and waveform
2. All generated clocks: correct source and division/multiplication
3. No unconstrained paths: verify with `report_timing -unconstrained`
4. CDCs: correct false_path or max_delay applied
5. Multicycle paths: both `–setup N` and `–hold 1` specified
6. Input/output delays: match system-level timing budget
7. Timing exceptions: not overly broad (masking real violations)
8. Propagated vs ideal clocks: correct mode (ideal pre-CTS, propagated post-CTS)

### Common Constraint Errors
| Error | Consequence |
|-------|------------|
| MCP without hold correction | Hold violations introduced |
| False path too broad | Real timing issues masked |
| Generated clock missing | Path unconstrained |
| Wrong clock period | Over/under-constraining |

### QoR Metrics to Evaluate
- 0 unconstrained paths
- 0 clock definition errors
- All exceptions reviewed and documented

### Output Required
- Constraint QA report
- Clock summary (all clocks, sources, periods)
- Exception list with justifications

---

## Stage: multi_corner_analysis

### Required Corner Matrix
Corners are driven by `design_state.constraints.pvt_corners[]`. The table below shows the
default corners used when `pvt_corners` is absent or contains no entries with non-null V/T:

| Mode | Setup Corner | Hold Corner |
|------|-------------|-------------|
| Functional | SS/0.9V/125°C (default) | FF/1.1V/−40°C (default) |
| Test (at-speed) | SS/0.9V/125°C (default) | FF/1.1V/25°C (default) |
| Low Power | SS/0.9V/125°C (default) | FF/1.1V/25°C (default) |

When `pvt_corners` is populated, use every entry with `"checks": ["setup"]` for setup and
every entry with `"checks": ["hold"]` for hold; the defaults above are the fallback.

### POCV/AOCV Application
1. AOCV: apply depth and location-based derating (pre-POCV designs)
2. POCV: apply parametric variation (sigma-based, per foundry agreement)
3. Clock uncertainty: pre-CTS ideal values → post-CTS propagated

### Annotation and engine rules
1. One scenario per corner, each reading its own library corner and the SPEF of the RC corner
   mapped to it; record the mapping in the timing report header
2. **Annotation gate.** Before any slack is reported, read the annotation report
   (`report_annotated_parasitics`, or the engine's equivalent): > 1 % of signal nets or any
   clock net unannotated is a FAIL of this stage (`input_setup`), whatever the slack says. An
   STA run on mostly unannotated nets reports clean timing that is false
3. Tempus may be absent; PrimeTime (`pt_shell`) or OpenSTA (`sta`) is then the engine. Name
   the engine and version with every figure

### Path Analysis Priority
1. WNS path per corner (most critical single path)
2. TNS contribution (how many paths fail and by how much)
3. CDC paths with max_delay constraints
4. At-speed paths: launch/capture pair STA

### QoR Metrics — Sign-off Targets
| Metric | Target |
|--------|--------|
| Setup WNS | ≥ `design_state.constraints.timing.wns_ns_target` (default: 0) all corners |
| Setup TNS | = `design_state.constraints.timing.tns_ns_target` (default: 0) all corners |
| Hold WNS | ≥ `design_state.constraints.timing.wns_ns_target` (default: 0) all corners |
| Hold TNS | = `design_state.constraints.timing.tns_ns_target` (default: 0) all corners |

### Output Required
- Timing report per corner (setup and hold)
- WNS/TNS summary table across all corners
- Top 100 violating paths

---

## Stage: path_analysis

### Domain Rules
1. Group failing paths by root cause: long wire, weak driver, logic depth, high-Vt
2. Separate setup violations from hold violations — different fix strategies
3. At-speed violations: check launch/capture pair timing explicitly
4. False paths: verify every exception is still valid after PD changes
5. Reconvergent fanout: flag paths with reconvergence for careful ECO planning

### Output Required
- Failing path analysis (root cause per path group)
- Paths requiring ECO vs paths requiring SDC correction

---

## Stage: exception_review

### Domain Rules
1. Review every timing exception for correctness and scope:
   - `set_false_path`: verify the path is truly non-functional (not just inconvenient)
   - `set_multicycle_path`: verify both `-setup N` and `-hold 1` are set correctly
   - `set_max_delay`: verify value matches system-level timing budget
2. Overly broad exceptions: any exception matching > 1% of all paths requires architect approval
3. Exceptions masking real violations: revoke immediately and re-run path analysis
4. Every exception must have a documented justification (design intent, async crossing, test mode)
5. Post-ECO exceptions: verify any new exceptions added after ECO are still valid

### Common Exception Errors

| Error | Consequence |
|-------|------------|
| `set_false_path` on functional CDC | Real metastability risk hidden |
| MCP without hold correction | Hold violations introduced silently |
| Exception too broad (glob match) | Unintended paths unconstrained |
| Expired exception (removed logic) | Stale SDC — may mask other issues |

### QoR Metrics to Evaluate
- 0 exceptions without documented justification
- 0 overly broad exceptions (flagged for architect review)
- Exception list reviewed and signed off before ECO guidance begins

### Output Required
- Exception audit report (valid / revoked / needs-approval per exception)
- Revised SDC with invalid exceptions removed
- Exception sign-off record

---

## Stage: eco_guidance

### ECO Decision Tree
```
Setup violation:
  Logic depth > target?       → Retime / add pipeline stage
  Long wire (> 500μm)?        → Buffer insertion / reroute on upper metal
  Weak driver?                → Upsize driver cell
  High-Vt on critical path?   → Swap to SVT or LVT
  Reconvergent fanout?        → Clone cell / split net

Hold violation:
  Skew-induced (post-CTS)?    → Useful skew / targeted delay buffer
  Short path (< 1 cycle)?     → Insert HVT delay buffer
  New path from ECO?          → Targeted hold buffer at sink register
```

### ECO Rules
1. Minimum ECO footprint: fewest cell changes to fix the most violations
2. Prefer resize over add new cell (less routing impact)
3. ECO cells: place in pre-reserved ECO sites or free standard cell rows
4. Re-run STA after every ECO batch — never accumulate blind
5. LEC after every ECO: verify equivalence preserved
6. Never introduce new hold violations while fixing setup (and vice versa)

### QoR Metrics to Evaluate
- ECO efficiency: violations fixed per change
- ECO cell count: < 2% of total cells (flag if exceeded — upstream issue)
- Post-ECO LEC: EQUIVALENT

### Output Required
- ECO change list (cell, action, justification)
- Pre/post ECO timing comparison
- ECO LEC result

---

## Stage: sta_signoff

### Sign-off Checklist
- [ ] Setup WNS ≥ `design_state.constraints.timing.wns_ns_target` (default: 0) at all corners
- [ ] Setup TNS = `design_state.constraints.timing.tns_ns_target` (default: 0) at all corners
- [ ] Hold WNS ≥ `design_state.constraints.timing.wns_ns_target` (default: 0) at all corners
- [ ] Hold TNS = `design_state.constraints.timing.tns_ns_target` (default: 0) at all corners
- [ ] All exceptions valid and documented
- [ ] POCV/AOCV applied per foundry spec
- [ ] LEC clean post all ECOs

### Output Required
- Sign-off timing report (all corners, all modes)
- ECO change summary
- Timing sign-off record

---

## Constraint Validation

See `plugins/meta/skills/pipeline-orchestration/SKILL.md` §Constraints Schema for the authoritative schema and stage-entry validation rule.

**Required at entry (`constraint_validation`) — hard-fail if missing:**
- `constraints.clock.clk_mhz` — clock frequency used to interpret timing results
- `constraints.pvt_corners` — at least one entry with non-null `voltage_v` and `temp_c`; missing or invalid entries should hard-fail during `constraint_validation`

**Optional (schema defaults apply when absent):**
- `constraints.timing.wns_ns_target` (default: 0) — WNS sign-off threshold
- `constraints.timing.tns_ns_target` (default: 0) — TNS sign-off threshold
- `constraints.timing.skew_ps_max` (default: 100) — CTS skew limit
- `constraints.timing.transition_ps_max` (default: 200) — max clock transition
- `constraints.timing.insertion_delay_ps_max` (default: 500) — max insertion delay

---

## Memory

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
write or overwrite one JSON record in `<MEM>/sta/experiences.jsonl` keyed by
`run_id`. This ensures data is persisted even if the flow is interrupted or called
without full orchestrator context.

Use `run_id` = `sta_<YYYYMMDD>_<HHMMSS>` (set once at flow start; reuse on each
stage update). Set `signoff_achieved: false` until the final sign-off stage completes.
### Run state (write before first stage, update after each stage)
Write `<MEM>/sta/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:      sta_<YYYYMMDD>_<HHMMSS>
design_name: <design>
tool:        <primary tool>
start_time:  <ISO-8601>
last_stage:  <first stage name>
```
Update `last_stage` after each stage completes. This file lets wakeup-loop prompts
and resumed sessions identify the correct run without relying on in-memory state.
Create the file and parent directories if they do not exist.

### Optional: claude-mem index
If `mcp__plugin_ecc_memory__add_observations` is available in this session, emit each
applied fix as an observation to entity `chip-design-sta-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.
