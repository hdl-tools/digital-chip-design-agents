---
name: logic-synthesis
description: >
  Logic synthesis from RTL to gate-level netlist — SDC constraint validation,
  compile and optimisation strategy, netlist quality check, and LEC equivalence
  verification. Use when synthesising RTL for ASIC, setting up timing constraints,
  optimising for timing/area/power, or verifying a post-synthesis netlist.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: Logic Synthesis

## Invocation

- **If invoked by a user** presenting a synthesis task: immediately spawn the
  `digital-chip-design-agents:synthesis-orchestrator` agent and pass the full
  user request and any available context. Do not execute stages directly.
- **If invoked by the `synthesis-orchestrator` mid-flow**: do not spawn a new
  agent. Treat this file as read-only — return the requested stage rules,
  sign-off criteria, or loop-back guidance to the calling orchestrator.

Spawning the orchestrator from within an active orchestrator run causes recursive
delegation and must never happen.

## Pre-run Context

`<MEM>` below is the resolved memory root, never the literal `memory/` directory: an
explicit `--memory-root`, else `$CHIP_DESIGN_MEMORY_ROOT`, else the central default, else
the in-repo seed (`python3 plugins/infrastructure/skills/memory-keeper/memory_root.py`
prints it; the orchestrator's `## Memory` section is authoritative).

Before executing or advising on **any** stage, read the following files if they exist:

1. `<MEM>/synthesis/knowledge.md` — known failure patterns, successful tool flags, PDK/tool quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `<MEM>/synthesis/run_state.md` — current run identity (`run_id`, `design_name`, `tool`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Produce a timing-clean, area-efficient, LEC-verified gate-level netlist
from RTL. Covers constraint setup, synthesis compilation strategy, and
quality checks before PD handoff.

---

## Supported EDA Tools

### Open-Source
- **Yosys** (`yosys`) — open-source synthesis suite; runs as a sequential pass pipeline (see sequential flow note below)
- **Surelog** (`surelog`) — SystemVerilog front-end for Yosys
- **ABC** — logic optimisation and technology mapping (invoked automatically by Yosys)

### Proprietary
- **Synopsys Design Compiler** (`dc_shell`, dialect `synopsys`) — industry-standard logic synthesis
- **Cadence Genus** (`genus`, dialect `cadence`) — RTL-to-netlist with concurrent optimisation
- **Synopsys Fusion Compiler** (`fc_shell`, dialect `synopsys`) — combined synthesis and physical guidance

Wrappers: `wrap-dc.sh` and `wrap-genus.sh` (Fusion Compiler through `wrap-icc2.sh` with
`WRAP_ICC2_TOOL=fc_shell`). Prove a netlist with LEC (`wrap-fm.sh` / `wrap-lec.sh`) before
handing it to PD.

### Tool Notes: commercial synthesis (measured)

Measured on one host (8 vCPU, 15 GB) on a Sky130 `sky130_fd_sc_hd` CPU macro of about 30k
cells with 10 OpenRAM SRAM hard macros, 2 cores per tool, one licensed tool at a time (see the
infrastructure skill, *Licensed tools on a small shared host*). Versions: DC-NXT
**X-2025.06-SP3**, Genus **23.14-s090_1**, PrimeTime **X-2025.06** for the neutral probe.
Fusion Compiler was not run: `fc_shell` synthesis is `compile_fusion` (stepwise with
`-to`/`-from`) in the same NDM design library the back end continues from, and
`compile_ultra` is not the FC command; nothing about FC below is measured.

**Design Compiler, topographical on NDM.**
- `dc_shell -topographical_mode` is the **Milkyway** flow: it has no `create_lib` (CMD-005) and
  cannot read NDM reference libraries. NDM topographical synthesis runs in
  **`dcnxt_shell -topographical_mode -f <script.tcl>`**. Build the `.db`/NDM views first
  (physical-design skill, `## PDK Enablement`)
- Wire RC: `set_tlu_plus_files -max_tluplus <f> -min_tluplus <f> -tech2itf_map <map>` then
  `check_tlu_plus_files` (all three checks must pass). `read_parasitic_tech` does not exist in
  `dcnxt_shell`. Set the TLU+ **before** `extract_physical_constraints`, or the floorplan step
  runs without RC (`PSYN-100` per layer)
- Floorplan from DEF: `extract_physical_constraints <fp.def>` for die, rows and pins. A DEF cannot
  name a generate-scope cell (`gen_data_sram[i].u_data_sram`), so place macros with
  `set_cell_location -fixed` and `set_dont_touch` them. Routing layers with `set_ignored_layers`
- `set_svf <file>` **before** `analyze`, `set_svf -off` at the end; Formality needs this SVF to
  match DC's constant-register removals and merges (without it 143 registers stay unmatched)
- `analyze -format sverilog` + `elaborate` read the RTL natively (struct-member part-selects
  elaborated clean, checked by LEC). Compile: `compile_ultra -spg`, then
  `change_names -rules verilog -hierarchy`. `set_dont_use */<cell>` is rejected (UID-109): use
  `set_dont_use [get_lib_cells */<cell>]`
- `write_parasitics -format spef` is not valid in DC (WP-1). `write_sdc` after SPG carries about
  69k per-pin annotations: do not hand it to P&R as the constraints file, use the source SDC
- Cost: `compile_ultra -spg` 219 s, session 9 min, **peak RSS 1.4-1.6 GB**
- **A tt-only compile with area recovery can build a slow adder.** With only the tt corner and
  the SDC's `set_max_area 0`, DC met 0 ps at tt with a ~30-cell `fa_1`/`fah_1` ripple-carry PC
  adder, and the netlist was **-10.5 ns at ss** zero-wire (Yosys -1.9, Genus +0.6). DC stops at
  slack 0 and recovers area, so "+0.00" is not headroom. The fix was **MCMM**:
  `create_scenario` setup `ss` (max TLU+) + `tt` (nom), hold `ff` (min) + `tt`, the same SDC read
  per scenario, `set_fix_hold [get_clocks <clk>]` in the hold scenarios (DC repairs hold only
  when asked). Result +1.16 ns at ss for +10 % std-cell area; Formality still EQUIVALENT
- DRV left after compile (thousands of max-transition nets on a large core) is the long-wire
  effect of the floorplan; it is P&R's job, not a DC sizing failure

**Genus, physically aware.**
- `genus -no_gui -overwrite -f <script.tcl>`: `read_mmmc <mmmc.tcl>`, `read_physical -lef` (tech LEF,
  cell LEF, macro LEFs), `read_hdl -sv -define <defines> <files>`, `elaborate`, `read_def <fp.def>`, then
  `syn_generic -physical` (453 s), `syn_map -physical` (161 s), `syn_opt` (51 s); **peak RSS
  2.0 GB**. Output with `write_hdl`, `write_sdc -view <view>` (needs `-view` in MMMC) and
  `write_do_lec` (the Conformal do-file; see the formal skill)
- **MMMC dialect differs between Genus and Innovus.** Genus 23.14 delay corners need
  `create_timing_condition` + `create_delay_corner -timing_condition`; Innovus 23.1x rejects
  that form (TCLCMD-992) and wants `-library_set`. One shared MMMC file must branch on the tool
- An instance's `.location` is read-only: place macros with `read_def -incremental <macros.def>`
  and set `preserve` on them. Dont-use is `set_db [get_db base_cells <c>] .dont_use true`
- `syn_opt -spatial` (iSpatial) **fails with PHYS-1015 without a `qrcTechFile`** (it needs
  probabilistic extraction); run plain physical-aware `syn_opt` and record it
- The SDC's `set_max_area 0` is **ignored by Genus** (SDC-200) and honoured by DC, which favours
  DC on area in a comparison
- In this release the hold `report_timing` forms, `report_summary` and `write_def` failed and
  `report_power` has no `-depth`: wrap every report and output in `catch`/`try` so one failed
  report does not lose the netlist

**Judge synthesis netlists across corners before choosing a re-run.** Time each netlist in
PrimeTime at every library corner with an ideal clock, no parasitics and the shared SDC (46 s
for three netlists x two corners). That separates an intrinsically slow netlist from a wire
problem: here it confirmed DC's tt-only weakness and refuted it for Genus (+0.6 ns at ss), so
only DC got an MCMM re-run.

### Sequential Flow Log Review (Yosys)

Yosys runs its synthesis script (`yosys -c synth.ys` or `yosys -p "synth_*"`) as a
sequential pass pipeline. Each pass (read_verilog → synth → opt → techmap → abc →
write_verilog) executes in order; errors or warnings in early passes propagate forward.

**After a Yosys run the agent must:**
1. Read the Yosys log (stdout or redirected `yosys.log`) for:
   - `Warning:` / `Error:` lines per pass
   - Final statistics block: number of cells, wires, and logic depth
   - Unmapped cells (search for `$`-prefixed cell names in the output netlist)
2. Verify that the output netlist (`synth_netlist.v`) exists and is non-empty
3. Parse `report_area` / `report_timing` output if ABC timing mode (`abc -constr`) was used

When used inside OpenROAD Flow Scripts (ORFS) or LibreLane, the Yosys log appears at:
`logs/<platform>/<design>/1_1_yosys.log`

---

## Stage: constraint_setup

### Domain Rules
1. `create_clock`: all primary clocks with period, waveform, source pin, name
2. `create_generated_clock`: all derived/divided clocks with correct source
3. `set_clock_uncertainty`: setup = skew + jitter — use `design_state.constraints.timing.clk_uncertainty_ps` if set; otherwise 200–500 ps pre-CTS (default: see `constraints.timing.clk_uncertainty_ps`, schema default null → use 200–500 ps rule-of-thumb)
4. `set_input_delay` / `set_output_delay`: all primary IOs constrained
5. `set_false_path`: multi-clock crossings, test modes, async resets
6. `set_multicycle_path`: both setup (-setup N) and hold (-hold 1) must be set
7. `set_dont_touch`: IPs, memory macros, hand-crafted cells
8. `set_max_fanout`: from `design_state.constraints.timing.fanout_max` (default: 32)
9. `set_max_transition`: per technology DRC rule
10. Operating conditions: explicitly set (never rely on tool defaults)

### Common SDC Mistakes
| Mistake | Consequence |
|---------|------------|
| Missing generated clock | Path unconstrained — may miss timing |
| MCP without hold correction | Hold violations introduced |
| False path too broad | Real timing issues masked |
| No operating conditions set | Wrong library corner used |

### QoR Metrics to Evaluate
- All clocks defined (verify with `report_clocks`)
- All IOs constrained (verify with `report_port -verbose`)
- No unconstrained paths (`report_timing -unconstrained`)

### Output Required
- Validated SDC file
- Clock summary
- Constraint QA report

---

## Stage: compile_explore

### Domain Rules
1. Run at worst-case timing corner (SS, low voltage, high temperature)
2. Compile explore: faster run to find best logic structure
3. Try multiple architectures: retiming on/off, datapath options
4. Identify critical paths for human review before final compile
5. Check area estimate vs microarch estimate

### Optimisation Strategy by Priority
| Priority | Approach |
|----------|---------|
| Timing | compile_ultra, path_group weighting, retiming |
| Area | High area_effort, resource sharing |
| Power | Clock gating insertion, power-aware compile |
| Balanced | compile_ultra -no_autoungroup + incremental |

### Output Required
- Exploration report (timing, area, power summary)
- Critical path list for architect review
- Recommended compile strategy for final compile

---

## Stage: compile_final

### Domain Rules
1. Run multi-scenario if available (setup + hold simultaneously)
2. Enable clock gating synthesis for sequential power reduction
3. Preserve hierarchy for blocks with existing placement intent
4. Ungroup small modules for better cross-boundary optimisation
5. Review critical paths manually — restructure RTL if path cannot close
6. Run incremental compile after initial compile to address remaining violations

### QoR Metrics to Evaluate
- WNS: ≥ `design_state.constraints.timing.wns_ns_target` at worst-case corner for sign-off (default: 0)
- TNS: = `design_state.constraints.timing.tns_ns_target` for clean sign-off (default: 0)
- Area: within `design_state.constraints.area.area_um2` budget (comparison run: recorded, not judged)
- Power: within `design_state.constraints.power.power_mw` budget (comparison run: recorded, not judged)
- No unmapped cells

### Output Required
- Gate-level netlist (.v)
- Timing report (setup and hold, all path groups)
- Area report
- Power report
- Synthesis run log

---

## Stage: netlist_qc

### Checks Required
1. No black boxes (undefined modules) in netlist. A black box is an input-set defect, not a
   compile result: if it resolves to first-party RTL, that file is missing from the synthesis
   source list (sv2v and yosys black-box it without an error); otherwise a library, macro or
   IP view is missing. Either way re-running the compile cannot fix it — name the module, the
   file or view, and the list, and escalate as `input_setup`
2. No combinational loops (`report_loop`)
3. Scan chains intact (if DFT-enabled compile)
4. Power/ground connections correct (tie cells, well ties)
5. Formal equivalence check (RTL vs netlist): PASS required

### LEC Requirements
- Golden: RTL (post-lint, post-CDC-clean)
- Revised: gate-level netlist
- Result: all points EQUIVALENT
- Any UNMATCHED point: must be resolved before PD

### QoR Metrics to Evaluate
- LEC: 100% EQUIVALENT
- No black boxes
- No combinational loops
- Scan chain integrity: verified

### Output Required
- LEC report (pass/fail)
- Netlist QC checklist
- Final gate netlist (ready for PD)
- Back-annotated SDC for PD

---

## Stage: synthesis_signoff

### Sign-off Checklist
- [ ] WNS ≥ `design_state.constraints.timing.wns_ns_target` at all required corners (default: 0)
- [ ] TNS = `design_state.constraints.timing.tns_ns_target` (default: 0)
- [ ] Area within `design_state.constraints.area.area_um2` budget
- [ ] Power within `design_state.constraints.power.power_mw` budget
- [ ] LEC: EQUIVALENT
- [ ] No black boxes
- [ ] No combinational loops
- [ ] Scan chains verified (if DFT)

### Output Required
- PD handoff package: netlist, SDC, timing reports, area/power reports

---

## Constraint Validation

See `plugins/meta/skills/pipeline-orchestration/SKILL.md` §Constraints Schema for the authoritative schema and stage-entry validation rule.

**Required at entry (`constraint_setup`) — hard-fail if missing:**
- `constraints.clock.clk_mhz` — target clock frequency (drives SDC `create_clock`)
- `constraints.area.area_um2` — area budget
- `constraints.power.power_mw` — power budget

**Comparison / benchmark runs** (`pipeline_config.comparison_run: true`, or a user request
that is a tool-vs-tool comparison rather than a product build): `area.area_um2` and
`power.power_mw` may be absent. Record `"comparison run, no target"` for each in the stage
`reason`, report the measured area and power, and do not escalate. `clock.clk_mhz` stays
required — every compared synthesis must use the same clock.

**Optional (schema defaults apply when absent):**
- `constraints.timing.wns_ns_target` (default: 0) — WNS sign-off threshold
- `constraints.timing.tns_ns_target` (default: 0) — TNS sign-off threshold
- `constraints.timing.fanout_max` (default: 32) — `set_max_fanout` value
- `constraints.timing.clk_uncertainty_ps` (default: null → use 200–500 ps rule-of-thumb)

---

## Memory

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
upsert one JSON record in `<MEM>/synthesis/experiences.jsonl` keyed by `run_id`.
Implement the upsert by rewriting the file: read all existing lines, filter out any
record(s) with the same `run_id`, append the updated record, write the full content
back atomically (replace the file). Every record must include a top-level `"run_id"`
field with format `synthesis_<YYYYMMDD>_<HHMMSS>` (set once at flow start; reuse on
each stage update). Set `signoff_achieved: false` until the final sign-off stage
completes.
### Run state (write before first stage, update after each stage)
Write `<MEM>/synthesis/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:      synthesis_<YYYYMMDD>_<HHMMSS>
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
applied fix as an observation to entity `chip-design-synthesis-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.
