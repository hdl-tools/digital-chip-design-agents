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

### Measured on Sky130 (`sky130_fd_sc_hd` + OpenRAM SRAM macro)

One host, one licensed tool at a time. Versions: `lc_shell` and `icc2_lm_shell` **X-2025.06**,
`grdgenxo`/StarRC **X-2025.06-SP1**, `Techgen` **23.11**, Innovus **23.14-s088_1**, Genus
**23.14-s090_1**, RedHawk **2025 R2.2**. Every load test below used a two-cell netlist (one flop,
one SRAM) first; it costs seconds and catches most view errors before a real run.

- **`.lib` → `.db`.** `lc_shell`: `read_lib <lib>`, `check_library`, `write_lib <name> -format db -output <db>`, then read every `.db` back
  with `read_db` in a fresh session. **`lc_shell` segfaults at process exit after any `read_lib`**
  (exit 139, after "Thank you for using Library Compiler"); the `.db` is already written, so judge
  success from the write message, a non-empty `.db` and the read-back, not the exit code. The
  LBDB/LIBG warnings on the stock Sky130 libs need no Liberty edit; LIBG-10/LIBG-243 cells
  (decap, diode, bleeder; enable/scan flops with no `nextstate_type`) go on the dont-use list.
  Leakage units can differ between the stdcell lib (nW) and a macro lib (mW): convert before
  summing by hand
- **ICC2 technology file.** `icc2_lm_shell create_workspace -technology` needs a `.tf`; a tech LEF
  is rejected (LIB-007). Derive the `.tf` from the tech LEF (layers, pitches, widths, spacing
  tables, min area, cut sizes, via enclosures, sites). The fat-spacing table must be N x N,
  non-redundant and start at threshold 0 (TECH-008/032); via enclosures must be crossed
  (TECH-083w); ContactCode `minCutNum` is unsupported. ICC2 mask names must be gapless
  `metal1..N`, so `li1` is `metal1` and `met1..met5` are `metal2..metal6`. The `.tf` carries
  **no routing directions**: set them per block with `set_attribute` before
  `initialize_floorplan`, or ICC2 derives them wrongly (DPUI-924)
- **NDM.** Stdcells and the SRAM cannot share a `normal`-flow workspace (different cell sets and
  rail names VPWR/VGND vs vccd1/vssd1, LM-014/LM-025): build one NDM per macro. The 9 LEF-only
  cells (fill, tap) need a `physical_only` NDM. For **multi-corner** P&R build **one stdcell NDM
  with one pane per corner**: one workspace, `read_lef` once, `read_db` tt, ss and ff into it,
  `check_workspace -allow_missing` (the plain check fails on pulse-width arcs present in only
  some corners), `commit_workspace`. Three separate per-corner NDMs with shared cell names do
  **not** give multi-corner timing: every instance binds to the first library (`report_pvt`
  "Library has 1 pane", PVT-030); see the ICC2 Tool Notes for the corner selection
- **DC/ICC2 dont-use.** `set_dont_use */<cell>` is rejected (UID-109); use
  `set_dont_use [get_lib_cells */<cell>]`. Genus/Innovus: `set_db [get_db base_cells <c>] .dont_use true`.
  DC `check_library` LIBCHK-213 on PG pin direction (`unknown` in the `.db`) is noise; do not edit
  the Liberty for it
- **ITF → `nxtgrd` / TLU+ (StarRC, ICC2, DC).** `grdgenxo <itf>` (single-threaded field solver,
  **~40-63 min per corner** here) and `grdgenxo -itf2TLUPlus` (fast). Give every grdgenxo run a
  timeout of hours, not minutes. The ITF reader needs the stack top to bottom with each
  conductor embedded in the dielectric listed above it. The StarRC layer map names every LEF
  routing and cut layer (the Sky130 tech LEF calls the first cut `via`, the ITF `via1`)
- **ICT → `qrcTechFile` (Quantus, Genus iSpatial, Innovus).** `Techgen -simulation_FS_off
  -2d_only` progressed at about 3 % in 7 min single-threaded (**about 4 h per corner**; a 4 h timeout killed one run). Techgen rejects a diffusion whose top
  touches poly (`LBMISC-215479`, negative poly thickness): leave a gate-oxide gap. Until a
  `qrcTechFile` exists, Innovus can use a **cap table from `generateCapTbl -ict`** (55 min), but
  `generateCapTbl` classifies a conductor named `li1` as POLY (IMPEXT-6091) and emits five metal
  layers against a six-layer tech LEF, so Innovus rejects the table (IMPEXT-3548). Rename the
  conductor `li1` → `met0` in a derived ICT (and its via references) and regenerate: M1=li1 ..
  M6=met5. `generateCapTbl -lef` crashed on the `licon` cut layer; run it without `-lef`
- **Correlation result (StarRC on an authored ITF vs OpenRCX, same DEF, 34-42k nets).** R agreed
  within 1-4 % (median) from the start. C needed two StarRC settings, not stack changes:
  `COUPLING_ABS_THRESHOLD: 0.1`, `COUPLING_REL_THRESHOLD: 0` (the 3 % relative default lumps a
  third of the coupling into ground) and `LEF_USE_OBS: NO`. Corner multipliers had to come from
  the OpenRCX deck the open flow actually uses (`.calibre`, not `.spef_extractor`, whose 4th
  column is resistance). The remaining median C offset (+8-10 %) is the ~0.16 fF per pin that
  StarRC extracts and OpenRCX does not; it was left, and the results stayed `indicative`
- **RedHawk tech.** The ITF converter shipped with RedHawk (`adsTechConverter.pl`) needs a
  comment-free ITF and, on perl 5.26, a one-line patch (`defined %hash`). RedHawk 2025 R2
  rejects `EM_Adjust` inside `via{}` blocks (TEC-011). EM limits come from the tech LEF
  `DCCURRENTDENSITY AVERAGE`; there is no li1/poly limit and no AC RMS limit in this format, so
  record EM on those as not checked
- **MMMC.** One file for Genus and Innovus must branch: Genus 23.14 wants
  `create_timing_condition` + `create_delay_corner -timing_condition`, Innovus rejects that
  (TCLCMD-992) and wants `-library_set`. Under Innovus `[info script]` is not the MMMC file;
  pass its directory in an environment variable. A Tcl MMMC file runs in the caller's scope, so
  its variable names can overwrite the caller's
- **Innovus tracks.** Innovus's automatic tracks do not follow the tech LEF pitches, and
  `add_tracks -offsets` is accepted but not honoured. Load the tracks from a TRACKS-only DEF
  (`defIn`) written from the LEF pitches and offsets
- **PT link test.** PrimeTime's Verilog reader rejects ANSI port headers in a hand-written test
  netlist (SVR-4); write the link-test netlist non-ANSI

---

## Tool Notes: Cadence Innovus

Measured with **Innovus 23.14-s088_1** on a Sky130 CPU macro (3600 x 1800 um, about 30k cells,
10 SRAM macros, max routing layer met4), Genus netlist, 2 CPUs (`setMultiCpuUsage -localCpu 2`),
peak RSS about 7 GB in the finish stage. Batch: `innovus -nowin -files <stage.tcl> -log <log>
-overwrite` through `wrap-innovus.sh`, stdin `/dev/null`, one stage per session saving a
database label. Session start and exit took 10-25 min on a loaded host.

| Stage | Commands that worked |
|---|---|
| Import | `init_lef_file` (tech LEF first), `init_verilog`, `init_top_cell`, `init_mmmc_file`, `init_pwr_net`/`init_gnd_net`, then `init_design`; `floorPlan -site unithd -b <die> <io> <core>`; tracks from a TRACKS-only DEF and pins from a pin DEF (`defIn`) |
| PDN, taps | `addEndCap -preCap/-postCap`, `addWellTap -cellInterval -checkerBoard`, `sroute -connect corePin`, `addStripe`, `sroute -connect blockPin` for macro rails; `verify_connectivity -type special -net <n>` per power net |
| Placement | `setOptMode -fixFanoutLoad true -fixDrc true`, `place_opt_design`; input-port diodes with `attachDiode` then `refinePlace` |
| CTS | `clock_opt_design -cts` (`ccopt_design` was rejected on this database, IMPCCOPT-2440), `optDesign -postCTS` and `optDesign -postCTS -hold` |
| Routing | `routeDesign -globalDetail`, `setAnalysisMode -analysisType onChipVariation -cppr both` (post-route `optDesign` refuses without OCV, IMPOPT-7027), `optDesign -postRoute` and `-postRoute -hold`, then `ecoRoute -fix_drc` until `verify_drc` reports 0 |
| Output | `saveNetlist -flat -excludeLeafCell -removePowerGround -excludeCellInst <physical cells>` (logical, for LEC), `saveNetlist ... -includePowerGround -includePhysicalInst` (for LVS), `defOut -routing -floorplan -netlist -usedVia`, `write_sdc -view <v>`, `streamOut -mapFile <map> -merge {<cell gds> <macro gds>} -units 1000 -mode ALL` |

- **Clock latency lives in the view, not only in the SDC.** Innovus keeps clock latencies in each
  analysis view's `latency.sdc` and re-applies that file **after** the SDC on restore and on
  `update_constraint_mode`. **Every view needs an explicit `create_analysis_view -latency_file`**
  (a view created without one starts with an empty file: a virtual I/O clock got network latency
  0 and hold read -1.8 ns). After `update_constraint_mode`, re-apply the I/O latency in the
  interactive mode (`set_interactive_constraint_modes <mode>`, `set_clock_latency <L>
  [get_clocks clk_io]`, `set_interactive_constraint_modes {}`); `update_analysis_view -name <v>
  -latency_file <f>` also works after CTS
- **I/O latency model.** CTS rewrites I/O latencies by default; `set_ccopt_property
  update_io_latency false` and a **virtual ideal I/O clock** whose network latency is the measured
  mean insertion delay made the I/O constraints visible in the exported SDC. A single fixed value
  is wrong at other corners (tree 1.95 ns at ff, 5.7-6.7 ns at ss vs 3.3 ns at tt): the ss/ff I/O
  failures that remain are that model, not the layout
- **Full MMMC in implementation.** With setup views {ss, tt} and hold views {ff, tt} active in
  placement, CTS and post-route, the judge's reg-to-reg setup loss at ss (-7.1 to -8.8 ns, 641-1064
  violators with tt-only views) went to 0 violators at all 9 corners, for 2.1x the buffers and
  +8 % power. `report_timing -view` needs `-late` for a setup view and `-early` for a hold view
  (TCLCMD-997). `report_power` in MMMC uses the first power view (ss here): quote PrimePower
- **Hold vs the judge.** Innovus's own ff hold read +0.01..+0.02 ns while PrimeTime on StarRC SPEF
  read -0.16 ns: about 0.17 ns optimistic at ff (tt agreed to 1 ps). `setOptMode -holdTargetSlack
  0.2` with the ff view active closed it in the judge
- **Power activity.** Native `report_power` defaults to activity 0.2; PrimePower's default is 0.1.
  `set_default_switching_activity -input_activity 0.1 -seq_activity 0.1` before comparing
  (87.5 vs 70.6 mW on the same layout)
- **RC.** Without a cap table or `qrcTechFile` Innovus uses tech-LEF RC (total C 1.25x StarRC,
  setup 1.2 ns and power 5 mW off). With the `li1`→`met0` cap table (see `## PDK Enablement`)
  total C median was 1.06x and R 1.01x of StarRC. Innovus's rcOut SPEF lumps coupling into ground
- **Primitives that fail silently.** `create_inst` returned without placing anything (with and
  without `-physical`): use **`addInst -cell <c> -inst <n> -loc {x y} -ori <o> -physical`**.
  `create_shape` does not exist and **`editAddRoute` did nothing** in 23.14: use **`add_shape
  -layer <l> -net <n> -rect {...}`** (used for 37-54 met3 pin stubs from die-edge pin pads that
  KLayout `m3.6` flagged and `verify_drc` did not, because it counts the pin shape)
- **Antenna.** `verifyProcessAntenna` has no side-area rule (`setAntennaMode` does not exist), so
  its count cannot match the deck. Drive the ECO from OpenROAD `check_antennas` on the exported
  DEF: `attachDiode -diodeCell sky130_fd_sc_hd__diode_2 -pin <inst> <pin>` per violating pin,
  then **`refinePlace` before `ecoRoute`** (attachDiode drops diodes off-grid on top of
  neighbours; skipping `refinePlace` gave 45 KLayout hits and an LVS net mismatch)
- **Taps at the source.** `addWellTap` lays taps on a lattice from the row start; in short row
  segments next to macros the last tap ends one site short of the endcap, leaving an untied
  n-well column (146 islands, `nwell.2a`). Add a tap abutting every endcap whose nearest tap is
  0.3-1.0 um away in the PDN stage (293 taps); check islands on the final DEF only (before
  std-cell placement the checker reports hundreds of artefacts)
- **npc.2.** A Sky130 `and2_0` next to a decap cell violates KLayout `npc.2`: mirrored with the
  decap on its right, and also unmirrored with the decap on its left. Swap that decap for fill
- **Long unbuffered port nets** (2-6 mm `axi_*` inputs, 13 ns first stage) were not repaired by
  `optDesign -postRoute`; `ecoAddRepeater -firstSpreadDist 40 -spreadDist 600 -cell buf_8` per
  net was, after checking every repeater legalised (one IMPSP-2020 left two met1 shorts)
- **GDS map.** Pin text: the PDK map's `NAME <layer>/LABEL,<layer>/LEFPIN` form wrote no text for
  design pins; `NAME <layer>/PIN <gds layer> <text datatype>` did. Write `VIA` entries on every
  metal, not only on the cut layers, or via cells stream cut-only (1.85 M KLayout enclosure
  errors)
- **Exported SDC is not PrimeTime-readable as is** (a `current_design` line, `get_designs`); see
  the sta skill. A strap keep-out band across the full core width split the PG grid into
  pieces: check `verify_connectivity -type special` per power net is one piece after the PDN stage

---

## Tool Notes: Synopsys ICC2 / Fusion Compiler

Measured with **`icc2_shell` X-2025.06-SP1** on the same Sky130 CPU macro (DC-NXT netlist, 2
cores, peak RSS about 4 GB). Fusion Compiler was not run (it would run this back end after
`compile_fusion`). Batch: `icc2_shell -f <stage.tcl>` through `wrap-icc2.sh`
(`WRAP_ICC2_TOOL=fc_shell` for FC), one stage per session. **Session start-up took 30-65 min on a
loaded host** (load 20-55; 47 s idle): budget stage timeouts for it, and do not launch a
`grep -r` over run directories while ICC2 runs (it saturated IO and slowed a stage 20x).

| Stage | Commands that worked |
|---|---|
| Library / design | `create_lib -technology <tf> -ref_libs {<ndm>...}`, `read_verilog -top <top>`, `link_block`; per stage `copy_block -from_block <top>/<prev> -to_block <top>/<new>` then `save_lib` (editing an opened block and saving writes back into that label) |
| Floorplan | `initialize_floorplan -boundary ... -core_offset ... -site_def unithd`, routing directions and `set_ignored_layers -min_routing_layer met1 -max_routing_layer met4`, `route.common.global_min_layer_mode hard` |
| PDN, taps | `create_boundary_cells`, `create_tap_cells -distance 26 -pattern stagger`, `set_pg_via_master_rule <r> -contact_code <cc> -cut_spacing {..}` per via layer, `create_pg_mesh_pattern`, `create_pg_std_cell_conn_pattern`, `compile_pg` |
| Placement | `set_lib_cell_purpose` (hold, CTS), `place_opt`, `legalize_placement` |
| CTS | `clock_opt` |
| Routing | antenna rules, `add_port_protection_diodes`, `route_auto`, `route_opt`, repair loop on `check_routes -drc true -antenna true -open_net true` |
| Output | `define_name_rules <r> -type net -case_insensitive` + `change_names -rules <r>`, `write_verilog` (see below), `write_def`, `write_gds -long_names -output_pin all -merge_gds_top_cell <top> -merge_files {<cell gds> <macro gds>} -units 1000` |

- **The li1 ban is soft by default.** `set_ignored_layers -min_routing_layer met1` alone let the
  router run 14 li1 wires (up to 400 um) through SRAM interiors, because
  `route.common.global_min_layer_mode` defaults to `soft` ("discouraged"). Set it to **`hard`**;
  pin-access stubs still use li1 under `allow_pin_connection`
- **Routing directions live in the block, not the `.tf`.** `set_attribute [get_layers ..]
  routing_direction` needs an open block (ATTR-15); re-source the tech setup after every
  `open_block`
- **PG vias.** `.tf` ContactCodes carry no cut spacing, so `compile_pg` via arrays overlapped
  (1.73 M `check_pg_drc` errors) until each via layer got `set_pg_via_master_rule -cut_spacing`
- **Multi-corner needs the multi-pane NDM** (`## PDK Enablement`). Per corner:
  `create_corner`, `create_scenario -mode <m> -corner <c>`, `read_sdc` (the same file per
  scenario), `read_parasitic_tech -tlup <file> -layermap <map> -name <n>` then
  `set_parasitic_parameters -corners <c> -early_spec <n> -late_spec <n>`, and select the pane with
  **`set_process_number`, `set_voltage`, `set_temperature -corners <c>`** (`report_pvt`: "no
  mismatches"). Pin a single-PVT macro (TT-only SRAM) per corner with `-object_list`.
  `set_scenario_status` sets setup on ss+tt, hold on ff+tt. With panes, `get_lib_cells */<c>`
  returns one cell per pane (CHF-002 in `create_boundary_cells`): use the explicit library prefix.
  `report_timing` in MCMM reports the worst scenario; add `-scenarios <s>` per scenario
- **tt-only hold repair builds weak delay chains.** With only the tt view, the optimiser met hold
  with chains of weak `ZBUF`/`ZINV` cells (2.8 ns transitions). Upsizing those for max-transition
  collapsed hold (-0.0016 → -0.205 ns): DRV repair and hold were in direct conflict. With ff+tt
  hold views and `set_lib_cell_purpose -include hold` restricted to `dlygate*`, `dlymetal*`,
  `clkdlybuf*`, hold closed in `clock_opt`/`route_opt` with 106 real delay cells and no DRV ECO
- **`add_buffer` drops the new cell off the row grid** on top of its neighbours; after
  `set_cell_location` + `legalize_placement` (0 failures reported) `check_lvs` still found 3-4
  cell/rail overlaps in a dense site, and `remove_buffers` on revert left an open and 2 min-area
  DRCs. Fix hold in the optimiser with the right views, not with a hand ECO in a dense site
- **met4 wide-metal spacing to PG straps is not enforced.** The `.tf` has the fat table
  (`fat_table_threshold 0 3`, spacing 0.3/0.4, equal to the tech LEF), but `route_detail` and
  `check_routes` do not apply it between a signal wire and a PG stripe: KLayout `m4.5ab` found
  132. Put **0.1 um met4 routing blockages around every PG strap wider than 3 um**
  (`create_routing_blockage -layers met4`) in the PDN stage, keep them through routing, remove them
  in the ECO stage before saving; trim strap ends that sit 0.3 um from a via-stack pad
- **Route convergence.** With the hard li1 ban the first route was 291 DRC / 439 shorts; 12 plain
  repair passes and a 248-net rip-up did not converge (the rip-up regressed to 1073). Setting
  `route.global.effort_level high`, `route.global.macro_boundary_track_utilization 60` and
  `route.detail.optimize_partition_size_for_drc true` from the first route gave 2 / 4 after
  `route_opt`. A short that survived plain and neighbour rip-up (a long repeater net crossing pin
  access on met2 in a macro gap) cleared with **`set_routing_rule -min_routing_layer met3
  -min_layer_mode allow_pin_connection`** on that net, then rip-up and `route_eco`
- **Antenna.** The generated piecewise-linear `diode_ratio` rule was invalid in ICC2, so the flow
  used `define_antenna_rule -mode 1 -diode_mode 1` (a net with a diode counts as protected).
  ICC2's own check then reads 0 while the deck-style OpenROAD `check_antennas` found 492-582 nets:
  **drive the antenna ECO from the OpenROAD list** (one `diode_2` per violating sink pin,
  `create_cell`, `legalize_placement -cells`, `route_eco`); three rounds took 582 → 11 → 2 → 1
- **Netlist export for LVS and LEC.** Netgen merges case-colliding names (`N1435` vs `n1435`)
  and turns `supply1`/`supply0` declarations into phantom devices: rename with
  **`change_names` using a `-case_insensitive` net rule** and write with **`write_verilog
  -exclude supply_statements`**. `write_verilog -include` and `-exclude` cannot be combined.
  `set_fix_multiple_port_nets` is replaced by `opt.port.eliminate_verilog_assign true`; the
  SDC's `set_max_fanout` is ignored (use `opt.common.max_fanout`)
- **GDS.** Without `-merge_gds_top_cell` the SRAM reference was truncated to a 32-character
  structure name (empty cell) and 245 orphan structures became extra top cells; `-output_pin text`
  gave floating pin text with no pin metal
- **Decap/fill vs li1 stubs.** Decap and fill cells (li1 frame blockage) shorted with the router's
  li1 pin-access stubs; the first run dropped decaps and removed the 428 colliding fills. Check
  well continuity afterwards: the removed fills left floating n-well islands next to the stubs
- **`write_sdc` carries no I/O clock latency**, unlike Innovus; a stage script ending in `exit`
  returns 0 even when its repair loop did not converge, so a chain driver must read the
  script's own result lines, not the exit code

---

## Tool Notes: Synopsys StarRC

Measured with **StarRC X-2025.06-SP1** (`StarXtract <cmd>` through `wrap-starrc.sh`), one
extraction per RC corner on routed DEFs from OpenROAD, ICC2 and Innovus (35-42k nets): about
2-3.5 min wall and **0.4-0.5 GB peak RSS** each at 2 cores. Command-file keys that worked:
`BLOCK`, `TCAD_GRD_FILE` (`nxtgrd`), `MAPPING_FILE`, one `LEF_FILE` per LEF (tech LEF of that
corner first), `TOP_DEF_FILE`, `STAR_DIRECTORY`, `EXTRACTION: RC`, `COUPLE_TO_GROUND: NO`,
`REDUCTION: NO_EXTRA_LOOPS`, `NETS: *`, `POWER_EXTRACT: NO`, `NETLIST_FORMAT: SPEF`,
`NETLIST_FILE`, `NUM_CORES`.

- `DEF_FILE` is not a keyword (SX-0271): use **`TOP_DEF_FILE`**. An absolute `SUMMARY_FILE` is
  rejected (SX-3978). A `#` comment line in the mapping file is parsed as a section (SX-1907):
  strip comments when generating it
- **ICC2 DEFs name signal vias by ContactCode** (`mcon_cc`, `via_cc`, ...), which no LEF defines:
  33,375 nets came out open (SX-2064) until a supplementary LEF declared those vias (generated
  from the `.tf` ContactCodes). Innovus and OpenROAD DEFs use LEF via names and needed nothing.
  Cells from `sky130_ef_sc_hd` (decap_12) need `sky130_ef_sc_hd.lef` (SX-2144)
- Set `SHORTS_LIMIT` high and read `star/shorts_all.sum` and the `report_opens` count: the
  capacitance of a shorted net (SX-0955) is unreliable, and a short StarRC reports is often a
  real layout short (it matched the LVS and ICC2 `check_lvs` finding)
- **Coupling threshold.** By default StarRC lumps any coupling below 3 % of a net's total C into
  ground (coupling share 34 % vs OpenRCX 55 % on the same DEF). `COUPLING_ABS_THRESHOLD: 0.1`
  and `COUPLING_REL_THRESHOLD: 0` matched OpenRCX's 0.1 fF absolute rule; `LEF_USE_OBS: NO`
  moved total C 2 %. Use the same settings for every compared flow
- Prove the SPEF is the result (`*SPEF` header, `*D_NET` count equal to the DEF net count,
  written by this run); a stale SPEF from an earlier layout is the silent failure

---

## Tool Notes: Ansys RedHawk

Measured with **RedHawk 2025 R2.2** (`redhawk -b <run.tcl>` through `wrap-redhawk.sh`) on the
three routed DEFs of the CPU macro (630k components including fill), power and timing windows
from PrimePower/PrimeTime X-2025.06: static about 45 s, vectorless dynamic about 66 s, **peak
RSS 1.0-1.4 GB** (2 threads, `MULTI_THREADS 1 2`).

- **Flow.** `import gsr <gsr>`, `setup design`, `perform pwrcalc`, `perform extraction -power
  -ground -c`, `perform analysis -static` or `-vectorless`. Results: `adsRpt/Static/*.inst`
  (per-instance drop), `*.em.worst`, `adsRpt/Dynamic/*.dvd`, `adsRpt/power_summary.rpt`
- **`INSTANCE_POWER_FILES` must be plural.** The singular `INSTANCE_POWER_FILE` (as written in
  the manual body) is accepted silently and ignored; RedHawk then uses its own toggle power
  (51.8 mW instead of the 70.8 mW PrimePower total). Check the log line "N% of instances
  specified in <ipf> have corresponding instances" and that `power_summary.rpt` equals the
  PrimePower total before reading any drop
- **Names in the instance power file must be escape-free.** An ICC2 DEF writes
  `u_core_u_dcache\/U100`; IPF lines with the backslash matched 86 % of instances, without it
  100 %. Unmatched names go to `adsRpt/<design>.ipfMissing`
- **PrimePower → IPF.** After `update_power`, sum `internal_power + switching_power +
  leakage_power` per leaf cell (`get_cells -hier -filter "is_hierarchical==false"`); the sum
  equalled `report_power` to 4 digits. `set timing_save_pin_arrival_and_slack true`, then
  `write_rh_file -filetype irdrop -output <f>` writes the timing windows (it appends `.gz`), read
  with `STA_FILE { <top> <f>.gz }`
- **DEF import.** ICC2 signal vias missing from the LEF stop the run (DEF-019) unless
  `IGNORE_DEF_ERROR 1` (signal vias do not matter for PG analysis). Fill and `sky130_ef_sc_hd`
  cells without Liberty are fatal (ITG-016): give them a custom lib (`cell <name> { pgarc { VPWR
  VGND } }`) listed as `<file> custom` in `LIB_FILES`
- **Supply on a macro with no pad ring.** A `.ploc` with one source per met5 stripe end (`<name>
  <x> <y> <layer> <net>`, net name rather than POWER/GROUND when there are two supplies); this
  is an ideal edge feed with zero package R/L, and the result says so
- **EM.** Static EM needs **`ENABLE_AUTO_EM 1`** (off by default). Dynamic EM defaults to PEAK
  mode, which compares peak current with the DC-average limit: **not a valid pass/fail** when
  the PDK publishes no peak limit (it flagged 384-658 met1 segments that AVG and RMS mode left
  below 10 % and 28 %). Run `perform emcheck -mode AVG` and `-mode RMS` after the dynamic
  analysis and copy `adsRpt/Dynamic/<design>.em.worst` between calls (each call overwrites it)
- **Dynamic results depend on decap.** RedHawk did not read the Sky130 decap cells' capacitance
  from LEF/Liberty; declare them with `DECAP_CELL { <cell> <w> <h> <C_pF> <R_ohm> <layer>
  <leak> }`. Without it the worst-instance dynamic drop changed from 79 to 210 mV on one flow
  and the flow ranking reversed. Without characterised decap and APL current models, report
  dynamic IR as indicative and prefer the mean drop to the worst instance

---

## Tool Notes: Magic, KLayout and Netgen on a commercial GDS

Measured with **Magic 8.3.489, Netgen 1.5.278, KLayout 0.29.4** inside the LibreLane container,
on GDS streamed by ICC2 and Innovus with the real SRAM GDS merged.

- **Magic DRC needs about 11 GiB** on this 3600 x 1800 um macro with the real SRAM layout: a
  9 GiB RSS watchdog killed it (container RSS 9.16 GiB), and it completed under an 11 GiB guard
  with `MemAvailable` >= 11 GiB as the start gate. `podman --memory` was not enforced, so the
  guard has to be your own. Run it **alone**, last, with nothing else heavy on the host (24 min)
- **Classify Magic counts before reading them.** 27.7-28.3 M violations, of which all but a few
  thousand sit inside the SRAM footprints (the PDK's SRAM abstract seen through the LEF, every
  rule except `nwell.4` 100 % inside); and about 3,000-3,600 `nwell.4` outside the footprints
  are long well strips along the SRAM edges, identical in count and geometry across all three
  flows. Classify by rule x inside / straddle / outside each macro footprint; what remains
  outside both classes is the real finding (here 1,191 Innovus tap wells in one pocket)
- **Netgen LVS on a commercial netlist** needs the case-collision and `supply1/supply0` fixes from
  the ICC2 notes; GDS-mode extraction is the result (DEF-mode extraction dropped vias). Magic
  `port makeall` does nothing for GDS text labels; `port make` after `findlabel <name>` does
- **KLayout DRC finds what the P&R checkers miss**: met4 spacing to wide straps (ICC2), die-edge
  met3 pin pads and `npc.2` (Innovus), untied n-well columns. On a loaded host it took about 3 h
  on the Innovus GDS

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
