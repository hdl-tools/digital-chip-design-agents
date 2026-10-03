---
name: physical-design
description: >
  Full physical design flow — floorplan, placement, clock tree synthesis, routing,
  timing optimisation, power optimisation, area optimisation, and tape-out sign-off.
  Use when implementing a gate-level netlist through to GDS-II, closing timing and
  power, or performing any individual PD stage analysis.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: Physical Design

## Invocation

- **If invoked by a user** presenting a physical design task: immediately spawn
  the `digital-chip-design-agents:physical-design-orchestrator` agent and pass
  the full user request and any available context. Do not execute stages directly.
- **If invoked by the `physical-design-orchestrator` mid-flow**: do not spawn a
  new agent. Treat this file as read-only — return the requested stage rules,
  sign-off criteria, or loop-back guidance to the calling orchestrator.

Spawning the orchestrator from within an active orchestrator run causes recursive
delegation and must never happen.

## Pre-run Context

Before executing or advising on **any** stage, read the following files if they exist:

1. `memory/pd/knowledge.md` — known failure patterns, successful tool flags, PDK quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `memory/pd/run_state.md` — current run identity (`run_id`, `design_name`, `pdk`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Guide the complete physical implementation flow from gate-level netlist to
tape-out-ready GDS-II. Eight stages with explicit QoR gates and loop-back
criteria enforced by the physical-design orchestrator.

---

## Supported EDA Tools

### Open-Source
- **OpenROAD / ORFS** (`make DESIGN_CONFIG=./designs/<platform>/<design>/config.mk`) — full PD pipeline; executes sequentially (see sequential flow note below)
- **LibreLane / OpenLane 2** (`openlane <config.json>`) — sequential PD pipeline built on OpenROAD; (see sequential flow note below)
- **KLayout** (`klayout`) — DRC, LVS, and GDS-II viewing/editing; used for signoff DRC in open-source flows

### Proprietary
- **Cadence Innovus** (`innovus`, dialect `cadence`) — floorplan through signoff; interactive and batch modes
- **Synopsys IC Compiler 2** (`icc2_shell`, dialect `synopsys`) — hierarchical PD with Fusion technology
- **Siemens Aprisa** (dialect `siemens`) — physical implementation for advanced nodes

### Sequential Flow Log Review (OpenROAD / LibreLane)

OpenROAD Flow Scripts (ORFS) and LibreLane execute the **entire PD pipeline in a single
invocation**. Stages run sequentially without pausing for agent intervention. After the
run completes (or fails mid-stage), the agent **must read the per-stage log files** to
evaluate QoR and apply loop-back logic.

**ORFS log layout:**
```
logs/<platform>/<design>/
  1_1_yosys.log         # synthesis (Yosys)
  2_1_floorplan.log     # floorplan (OpenROAD)
  3_1_place.log         # global placement (OpenROAD)
  3_4_resizer.log       # resizer / timing-driven placement
  4_1_cts.log           # clock tree synthesis (OpenROAD)
  5_1_route.log         # global routing (OpenROAD)
  5_3_fillcell.log      # filler cell insertion
  6_1_finishing.log     # signoff: DRC (KLayout/Magic), LVS (Netgen), final STA
```
Invocation: `make DESIGN_CONFIG=./designs/<platform>/<design>/config.mk`
Resume from stage: `make do-<stage>` (e.g. `make do-3_2_place`)

**LibreLane (OpenLane 2) log layout:**
```
runs/<design>/<run_tag>/logs/
  synthesis/            # Yosys synthesis logs
  floorplan/            # OpenROAD floorplan logs
  placement/            # OpenROAD placement logs (global + detail)
  cts/                  # OpenROAD CTS logs
  routing/              # OpenROAD global + detailed routing (DRT) logs
  signoff/              # Magic/Netgen DRC+LVS, OpenSTA final timing
```
Invocation: `openlane <config.json>` (or `python3 -m openlane <config.json>`)
Resume from step: `openlane --from <step_name> <config.json>`

**Agent procedure after run:**
1. Identify the last successfully completed stage from log timestamps or exit codes
2. Read the log for each completed stage and extract the relevant QoR metrics
   (WNS, DRC count, congestion, IR drop) defined in the `## Stage:` sections below
3. Apply loop-back rules from this skill; correct the input config or constraints
4. Re-invoke from the failed stage using the resume command above

---

## Stage: floorplan

### Domain Rules
1. Core utilisation target: `design_state.constraints.area.utilization_pct_target`% (default: 75%) — leave margin for routing congestion
2. Macros: place at die edges or corners with halos (typically 5–10 μm)
3. IO pads: distribute evenly; match package pin assignment
4. Power grid: VDD/VSS straps every N rows (technology-node specific)
5. Blockages: hard blockages around analog/RF macros
6. Aspect ratio: keep close to 1:1 unless package constrains otherwise
7. Voltage island boundaries must align to row boundaries

### QoR Metrics to Evaluate
- Estimated congestion (H and V): flag if > 80%
- Estimated WNS from floorplan-stage STA: flag if < −2 ns
- IR drop estimate: flag if > 2× `design_state.constraints.power.ir_drop_pct_max`% of VDD (default threshold: 10%)

### Output Required
- Floorplan DEF (floorplan.def)
- Power grid DEF or script
- Macro placement report
- Estimated congestion map

---

## Stage: placement

### Domain Rules
1. Sequence: global → legalise → detailed → pre-CTS optimisation
2. Pre-CTS timing: ideal clocks; uncertainty = skew + jitter estimate
3. Max utilisation per partition: 80%
4. High-fanout nets: buffer before placement or apply constraints
5. Timing-critical paths: co-locate related cells with placement constraints
6. Scan chains: re-order after placement for minimum wirelength

### QoR Metrics to Evaluate
- Pre-CTS WNS: > −0.3 ns (early stage gate; sign-off target is `constraints.timing.wns_ns_target`, default: 0)
- Cell density hotspots: flag if any region > 90%
- Max utilisation per partition: `design_state.constraints.area.utilization_pct_max`% (default: 85%); flag if exceeded
- Estimated routing congestion overflow: flag if > 1%

### Output Required
- Placed DEF
- Pre-CTS timing report (setup and hold)
- Cell density and congestion report

---

## Stage: cts

### Domain Rules
1. Target skew: < `design_state.constraints.timing.skew_ps_max` ps (default: 100 ps, or per SDC set_clock_uncertainty)
2. Max transition on clock nets: per technology DRC rule (`design_state.constraints.timing.transition_ps_max` ps, default: 200 ps)
3. Max fanout per clock buffer: per library (`design_state.constraints.timing.fanout_max`, default: 16–32)
4. Useful skew: only with explicit sign-off approval
5. Clock gating: integrate into CTS; verify enable pin timing
6. Multi-clock: handle each domain independently; check CDC after CTS

### QoR Metrics to Evaluate
- Global skew per domain: flag if > 1.5× `design_state.constraints.timing.skew_ps_max` ps (default threshold: 150 ps)
- Max insertion delay: flag if > `design_state.constraints.timing.insertion_delay_ps_max` ps (default: 500 ps)
- Post-CTS WNS (setup): flag if < −0.2 ns
- Post-CTS hold slack: must be ≥ 0 before routing

### Output Required
- Post-CTS DEF
- Clock tree report (skew, insertion delay per domain)
- Post-CTS timing report (setup and hold)

---

## Stage: routing

### Domain Rules
1. Sequence: global → track assignment → detailed → search-and-repair
2. Follow foundry DRC deck (spacing, width, via enclosure)
3. Shield critical clock and analog nets
4. Upper metals for power, lower metals for signals
5. Antenna rules: insert diodes or use jump-via strategy
6. Double/multi-patterning (7 nm and below): resolve same-colour violations

### QoR Metrics to Evaluate
- DRC violations: 0 at sign-off
- LVS errors: 0 at sign-off
- Post-route WNS: flag if < 0
- Routing overflow: 0

### Output Required
- Routed DEF
- DRC report
- LVS report
- Post-route timing report

---

## Stage: timing_optimization

### Domain Rules
1. Multi-corner: SS (setup), FF (hold), TT (typical)
2. Setup: upsize drivers, insert repeaters, retime registers
3. Hold: insert HVT delay buffers
4. Vt swapping: SVT/LVT for speed-critical; HVT for power-insensitive paths
5. ECO: formal ECO → place in reserved sites → re-route ECO nets
6. Do not modify scan chain order without DFT approval
7. Apply POCV/AOCV per foundry sign-off agreement

### QoR Metrics to Evaluate
- WNS: ≥ `design_state.constraints.timing.wns_ns_target` (default: 0) all corners
- TNS: = `design_state.constraints.timing.tns_ns_target` (default: 0) all corners
- Hold slack: ≥ 0 after fixing
- ECO cell count: flag if > 2% of total cells

### Output Required
- Timing closure report (all corners)
- ECO change list
- SPEF
- Updated routed DEF (post-ECO)

---

## Stage: power_optimization

### Domain Rules
1. Dynamic: clock gating insertion, operand isolation, multi-Vt swapping
2. Leakage: swap non-critical cells to HVT; verify timing after each batch
3. Power domains: validate UPF (isolation, level-shifters, retention regs)
4. Voltage islands: verify IR drop per domain
5. Always-on logic: verify correct library cells
6. Power gating: verify wakeup/shutdown sequences before routing changes

### QoR Metrics to Evaluate
- Total power: within `design_state.constraints.power.power_mw` budget
- Leakage: flag if > `design_state.constraints.power.leakage_pct_max`% of total at TT corner (default: 15%)
- IR drop: < `design_state.constraints.power.ir_drop_pct_max`% VDD across all domains (default: 5%)
- Post-power-opt WNS: must remain ≥ `design_state.constraints.timing.wns_ns_target` (default: 0)

### Output Required
- Power analysis report (dynamic + static, per domain)
- IR drop report
- Updated DEF (post-power-opt)
- UPF compliance report

---

## Stage: area_optimization

### Domain Rules
1. Remove redundant buffers and inverter pairs
2. Downsize non-timing-critical cells to minimum drive strength
3. Reclaim unused standard cell sites
4. Do not drop WNS margin below 50 ps buffer
5. Re-run DRC after any area ECO

### QoR Metrics to Evaluate
- Core utilisation: target `design_state.constraints.area.utilization_pct_target`% (default: 75%); hard limit `design_state.constraints.area.utilization_pct_max`% (default: 85%)
- WNS: must remain ≥ `design_state.constraints.timing.wns_ns_target` (default: 0)
- DRC: must remain clean

### Output Required
- Area utilisation report (pre vs post)
- Updated DEF
- Cell count breakdown

---

## Stage: signoff

### Sign-off Pass Criteria (all must pass)
| Check | Criterion |
|-------|-----------|
| Setup WNS | ≥ `design_state.constraints.timing.wns_ns_target` (default: 0) all corners |
| Setup TNS | = `design_state.constraints.timing.tns_ns_target` (default: 0) all corners |
| Hold WNS | ≥ `design_state.constraints.timing.wns_ns_target` (default: 0) all corners |
| DRC violations | = 0 |
| LVS errors | = 0 |
| Antenna violations | = 0 |
| IR drop | < `design_state.constraints.power.ir_drop_pct_max`% VDD (default: 5%) |
| Metal density | Within foundry window |

### Domain Rules
1. STA sign-off: run all required PVT corners with POCV/AOCV
2. DRC: foundry-approved deck — zero violations
3. LVS: netlist vs layout — zero errors
4. ERC: electromigration and IR drop sign-off
5. Final GDS: merge all layers, add seal ring, chip-level DRC

### Failure Escalation
- Timing fail → timing_optimization
- DRC/LVS fail → routing
- Power/EM fail → power_optimization

### Output Required
- Sign-off STA report (all corners)
- DRC clean report
- LVS clean report
- Final GDS-II
- Completed tape-out checklist

---

## Constraint Validation

See `plugins/meta/skills/pipeline-orchestration/SKILL.md` §Constraints Schema for the authoritative schema and stage-entry validation rule.

**Required at entry (`floorplan`) — hard-fail if missing:**
- `constraints.clock.clk_mhz` — target clock frequency
- `constraints.area.area_um2` — die area budget
- `constraints.power.power_mw` — total power budget
- `constraints.pvt_corners` — at least one entry with non-null `voltage_v` and `temp_c`

**Optional (schema defaults apply when absent):**
- `constraints.timing.wns_ns_target` (default: 0) — WNS sign-off threshold
- `constraints.timing.tns_ns_target` (default: 0) — TNS sign-off threshold
- `constraints.timing.skew_ps_max` (default: 100) — CTS skew target
- `constraints.timing.transition_ps_max` (default: 200) — clock transition limit
- `constraints.timing.insertion_delay_ps_max` (default: 500) — max clock insertion delay
- `constraints.timing.fanout_max` (default: 32) — max clock buffer fanout
- `constraints.area.utilization_pct_target` (default: 75) — target core utilisation %
- `constraints.area.utilization_pct_max` (default: 85) — hard utilisation ceiling %
- `constraints.power.leakage_pct_max` (default: 15) — leakage as % of total power
- `constraints.power.ir_drop_pct_max` (default: 5) — IR drop limit as % of VDD

---

## Memory

### Run state (write before first stage, update after each stage)
Write `memory/pd/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:      pd_<YYYYMMDD>_<HHMMSS>
design_name: <design>
pdk:         <pdk or unknown>
tool:        <primary tool>
start_time:  <ISO-8601>
last_stage:  null
```
Update `last_stage` to the completed stage name only after each stage finishes successfully. This file allows wakeup-loop prompts
and resumed sessions to identify the correct run directory without relying on in-memory state.

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
upsert one JSON record in `memory/pd/experiences.jsonl` keyed by `run_id` — do not
append a second line for the same run. Write with the stages completed so far and
`signoff_achieved: false`; overwrite to `true` only when signoff passes.

Use `run_id` = `pd_<YYYYMMDD>_<HHMMSS>` (set once at flow start; reuse on each
stage update). **Every JSON record written to experiences.jsonl must include a top-level
"run_id" field** (string) inside the record itself — upsert behavior is keyed by this field.
Do not rely on external metadata; the "run_id" property must be present in the JSON object.
Records should be written with stages completed and `signoff_achieved: false`, and only
overwritten to `true` when signoff passes. Create the file and parent directories if they
do not exist.

### Optional: claude-mem index
If `mcp__plugin_ecc_memory__add_observations` is available in this session, also emit
each new fix as an observation to entity `chip-design-pd-fixes` after writing to
`experiences.jsonl`. Skip this step silently if the tool is absent — the JSONL file
is the canonical record.
