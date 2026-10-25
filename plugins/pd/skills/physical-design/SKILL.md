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

`<MEM>` below is the resolved memory root, never the literal `memory/` directory: an
explicit `--memory-root`, else `$CHIP_DESIGN_MEMORY_ROOT`, else the central default, else
the in-repo seed (`python3 plugins/infrastructure/skills/memory-keeper/memory_root.py`
prints it; the orchestrator's `## Memory` section is authoritative).

Before executing or advising on **any** stage, read the following files if they exist:

1. `<MEM>/pd/knowledge.md` — known failure patterns, successful tool flags, PDK quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `<MEM>/pd/run_state.md` — current run identity (`run_id`, `design_name`, `pdk`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Guide the complete physical implementation flow from gate-level netlist to
tape-out-ready GDS-II. Ten stages with explicit QoR gates and loop-back
criteria enforced by the physical-design orchestrator.

---

## Supported EDA Tools

### Open-Source
- **OpenROAD / ORFS** (`make DESIGN_CONFIG=./designs/<platform>/<design>/config.mk`) — full PD pipeline; executes sequentially (see sequential flow note below)
- **LibreLane / OpenLane 2** (`openlane <config.json>`) — sequential PD pipeline built on OpenROAD; (see sequential flow note below)
- **KLayout** (`klayout`) — DRC, LVS, and GDS-II viewing/editing; used for signoff DRC in open-source flows
- **Magic** (`magic`) — DRC and extraction; Sky130 sign-off DRC (wrapper `wrap-magic.sh`)
- **Netgen** (`netgen`) — LVS; Sky130 sign-off LVS (wrapper `wrap-netgen.sh`)
- **OpenRCX** (OpenROAD `extract_parasitics`) — open RC extraction; the correlation reference
  for a commercial extraction tech authored for an open PDK

### Proprietary
- **Cadence Innovus** (`innovus`, dialect `cadence`) — floorplan through signoff; interactive and batch modes
- **Synopsys IC Compiler 2** (`icc2_shell`, dialect `synopsys`) — hierarchical PD with Fusion technology
- **Synopsys Fusion Compiler** (`fc_shell`, dialect `synopsys`) — synthesis + P&R in one database
- **Siemens Aprisa** (dialect `siemens`) — physical implementation for advanced nodes
- **Synopsys StarRC** (`StarXtract`, dialect `synopsys`) — signoff extraction; tech file from `grdgenxo`
- **Synopsys StarRC grdgenxo** (`grdgenxo`, dialect `synopsys`) — ITF → `nxtgrd` extraction tech
- **Cadence Quantus** (`quantus`, dialect `cadence`) — signoff extraction; tech file `qrcTech`
- **Cadence Quantus Techgen** (`Techgen`, dialect `cadence`) — ICT → `qrcTech` extraction tech
- **Synopsys Library Compiler** (`lc_shell`, dialect `synopsys`) — `.lib` → `.db` per corner
- **Synopsys IC Compiler II Library Manager** (`icc2_lm_shell`, dialect `synopsys`) — NDM reference libraries
- **Synopsys PrimeTime / PrimePower** (`pt_shell`, dialect `synopsys`) — signoff STA and power on extracted parasitics
- **Ansys RedHawk** (`redhawk`, dialect `ansys`) — static/dynamic IR and EM
- **Ansys Totem** (`totem`, dialect `ansys`) — IR/EM (transistor-level and mixed-signal)
- **Siemens Calibre** (`calibre`, dialect `siemens`) — DRC/LVS where the PDK ships Calibre decks
- **Cadence PVS** (`pvs`, dialect `cadence`) — DRC/LVS where the PDK ships PVS decks

Cadence Voltus and Tempus are absent on some hosts; use RedHawk/Totem and PrimeTime/PrimePower
there. Wrappers: `wrap-innovus.sh`, `wrap-icc2.sh`, `wrap-starrc.sh`, `wrap-pt.sh`,
`wrap-redhawk.sh`, `wrap-magic.sh`, `wrap-netgen.sh`. On a host with ≤ 16 GB RAM run one of
these heavy tools at a time (infrastructure `environment_validation` rule 12).

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

## Stage: extraction

### Domain Rules
1. Extract every RC corner the signoff STA needs (typically Cmin/Cmax or RCbest/RCworst and
   typical) from the **final routed database**, and write one SPEF per corner. Record which
   library corner each RC corner pairs with; an unmapped corner is a FAIL, not a default
2. The extraction tech must match the PDK metal stack (layer order, thickness, dielectric) and
   the layer map must name every routing and via layer in the DEF. Where the PDK ships no tech
   for this extractor, build one per `## PDK Enablement` and label results `indicative` until
   correlation holds
3. Prove the file is the result: it exists, was written by this run, has a `*SPEF` header
   (or the stated format's header) and holds `*D_NET` entries; `wrap-starrc.sh` checks exactly
   this. An exit-0 extraction with a stale or empty file is not a result
4. Unannotated nets: read the STA tool's annotation report (`report_annotated_parasitics` in
   PrimeTime/OpenSTA, or the extractor's own summary). Above 1 % of signal nets unannotated is a
   FAIL; any unannotated clock net is a FAIL. A timing run on largely unannotated nets reports
   falsely clean slack
5. Every later ECO (timing, power, area optimisation) invalidates the SPEF. `signoff` must read
   parasitics extracted after the last database change, and say which run produced them
6. Correlation, when two extractors are available (or a commercial tech was authored for an
   open PDK): extract the same DEF with both, compare total net capacitance and resistance per
   net and the resulting worst-path slack, and state the tolerance used (for example 5 % median
   net C, 10 % worst-slack delta). Outside tolerance → WARN; downstream figures are `indicative`

### QoR Metrics to Evaluate
- `spef_files`: one per RC corner, all fresh and non-empty
- `unannotated_nets_pct`: flag if > 1 %
- `extractor_correlation_pct`: median per-net C delta vs the reference extractor, when measured

### Output Required
- SPEF per RC corner (paths recorded in `pd.spef`)
- RC-corner ↔ library-corner map
- Annotation report from the STA engine
- Correlation report, when two extractors were run

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

## Stage: ir_em

### Domain Rules
1. Run on the final routed database with the **power grid present**: count the PG shapes
   (`VDD`/`VSS` special wires) before analysis. Zero shapes, or macro power pins with no
   connection, is a power-grid defect to fix in `floorplan`, not an IR result — a grid that was
   never committed reports zero drop
2. Static IR first (average current from the signoff power run, same activity assumption as
   `power_optimization`), then dynamic IR when a vector or vectorless switching scenario is
   specified; record which
3. Report worst drop as % of nominal VDD per domain, and the location of the worst instance
4. EM: check signal and power nets against the PDK's current-density rules; a missing EM rule
   set is recorded as "EM not checked", never as zero violations
5. Use the IR tool the PDK supports. For an open PDK without a RedHawk/Totem/Voltus tech file,
   author it per `## PDK Enablement` and label the result `indicative`; OpenROAD
   `analyze_power_grid` (PSM) is the open reference and needs via resistances in the tech
   data, or it aborts
6. `wrap-redhawk.sh` recognises a result only from a `WRAP_RESULT worst_ir_drop_pct=<v>` line
   the run script prints after reading its own report; without it the run is unverified

### QoR Metrics to Evaluate
- `ir_drop_pct`: worst of static/dynamic, < `design_state.constraints.power.ir_drop_pct_max`% (default: 5)
- `em_violations`: 0 (or "not checked" with the reason)
- `pg_shapes`: > 0 per power net

### Output Required
- IR drop report (static, and dynamic when run) per domain
- EM report, or the reason EM was not checked
- PG shape count per power net

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
| IR drop | < `design_state.constraints.power.ir_drop_pct_max`% VDD (default: 5%), from `ir_em` |
| EM violations | = 0 (or recorded as not checked, which blocks sign-off) |
| Total power | ≤ `design_state.constraints.power.power_mw` when set; recorded only in a comparison run |
| Metal density | Within foundry window |

Timing and power in this table come from the signoff STA/power engine on parasitics from
`extraction`, not from the implementation tool's internal estimate. When flows from different
tools are compared, judge them all with the sta skill's fair cross-tool comparison rule; a
tool's own report is recorded and labelled `native`.

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

## PDK Enablement

Commercial tools on an **open PDK** (Sky130, GF180, IHP) usually need views the PDK does not
ship. Build them once per PDK, record every derived file and its source, and treat any number
that depends on an authored (not foundry-supplied) file as `indicative` until correlated.

1. **Liberty → `.db` (Synopsys).** `lc_shell`: `read_lib` each `.lib` and `write_lib` to `.db`,
   **per corner, including every macro's `.lib`** (SRAM, PLL, IO). A corner with a missing macro
   `.db` silently times the macro as a black box
2. **NDM reference libraries (ICC2 / Fusion Compiler).** `icc2_lm_shell`: create a workspace
   whose technology comes from the PDK **tech LEF** (no Milkyway `.tf` in an open PDK), read the
   cell LEF and the `.db` files per corner, check and commit to `.ndm`. Macros get their own NDM
3. **Innovus / Genus.** Read the tech LEF first, then cell and macro LEFs; timing through an
   MMMC file (`create_library_set` per corner, `create_rc_corner` per RC corner,
   `create_delay_corner`, `create_constraint_mode` with the SDC, `create_analysis_view`), loaded
   with `read_mmmc`
4. **Extraction tech when the PDK ships none.** Author an ITF (StarRC) or ICT (Quantus) from the
   PDK's published metal/dielectric stack (layer thickness, width/spacing, ε_r, via
   resistance), then generate the tech: `grdgenxo` → `nxtgrd` plus a LEF/DEF↔ITF layer map, or
   `Techgen` → `qrcTech`. **Correlate** against OpenRCX (or Magic extraction) on the **same
   routed DEF**: per-net total C and R, and worst-path slack. State the tolerance; beyond it,
   label every result that used the authored tech `indicative`
5. **IR/EM tech (RedHawk/Totem).** A tech file with layer resistance, via resistance and EM
   current limits, from the same published stack; the same correlation duty applies against
   OpenROAD PSM
6. **DRC/LVS decks.** Open PDKs usually have no Calibre or PVS deck. Use the PDK's open decks —
   Magic and KLayout for DRC, Netgen for LVS — on the commercial tool's GDS/netlist; record
   which deck judged sign-off. Never call a run DRC-clean against a deck that was not the
   foundry's sign-off deck without saying so
7. **Record the enablement** in the run's notes: tool versions, every derived file with the
   command that produced it, and whether each is foundry-supplied or authored

Detailed, measured recipes for each tool on Sky130 are pending (they follow the first real runs).

---

## Tool Notes: Cadence Innovus

**Outline — measured notes pending.** Standard stage commands only; no option recipe here has
been verified on this suite's reference host yet.

| Stage | Command |
|---|---|
| Design import | `read_mmmc`, `read_physical -lef`, `read_netlist`, `init_design` |
| Floorplan | `create_floorplan`, power grid (`add_rings`, `add_stripes`, `route_special`) |
| Placement | `place_opt_design` |
| CTS | `ccopt_design` |
| Routing | `routeDesign` (legacy name) / `route_design`, then `opt_design -post_route` |
| Timing report | `time_design` / `timeDesign` (native estimate — label it `native`) |
| Output | `write_def`, `write_netlist`, `streamOut` / `write_stream` |

Run in batch: `innovus -batch -no_gui -files <script.tcl>` through `wrap-innovus.sh`, which also
gives it `/dev/null` as stdin.

---

## Tool Notes: Synopsys ICC2 / Fusion Compiler

**Outline — measured notes pending.** Standard stage commands only.

| Stage | Command |
|---|---|
| Library / design | `create_lib -technology <tech> -ref_libs <ndm>`, `read_verilog`, `link_block` |
| Floorplan | `initialize_floorplan`, or `read_def` of an existing floorplan; `create_pg_mesh_pattern` / `compile_pg` |
| Placement | `place_opt` |
| CTS | `clock_opt` |
| Routing | `route_auto`, then `route_opt` |
| Timing report | `report_qor`, `report_timing` (native — label it `native`) |
| Output | `write_def`, `write_verilog`, `write_gds` |

Fusion Compiler runs the same back end after `compile_fusion`. Run through `wrap-icc2.sh`
(`WRAP_ICC2_TOOL=fc_shell` for Fusion Compiler).

---

## Constraint Validation

See `plugins/meta/skills/pipeline-orchestration/SKILL.md` §Constraints Schema for the authoritative schema and stage-entry validation rule.

**Required at entry (`floorplan`) — hard-fail if missing:**
- `constraints.clock.clk_mhz` — target clock frequency
- `constraints.area.area_um2` — die area budget
- `constraints.power.power_mw` — total power budget
- `constraints.pvt_corners` — at least one entry with non-null `voltage_v` and `temp_c`

**Comparison runs** (`pipeline_config.comparison_run: true`): `area.area_um2` and
`power.power_mw` may be absent; record `"comparison run, no target"` and proceed.
`clock.clk_mhz` and `pvt_corners` stay required — every compared flow is judged at the same
clock and corners.

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

### Design-state fields
Besides `gds`, `util_pct`, `wns_ns`, `drc_violations`, `lvs_errors` and `signoff`, record
`pd.tool` (the implementation tool command), `pd.def`, `pd.netlist`, `pd.spef` (a list, one per
RC corner), `pd.power_mw` and `pd.ir_drop_pct`, so a comparison can read every flow the same way.

### Run state (write before first stage, update after each stage)
Write `<MEM>/pd/run_state.md` as the **first action** before launching any tool:
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
upsert one JSON record in `<MEM>/pd/experiences.jsonl` keyed by `run_id` — do not
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
