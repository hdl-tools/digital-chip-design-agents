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

Measured with **PrimeTime X-2025.06** (`pt_shell`, through `wrap-pt.sh`) as the judge for three
P&R flows of one Sky130 CPU macro, on StarRC X-2025.06-SP1 SPEFs: 27 runs per flow (9 corners x 3
SDC variants), **one `pt_shell` per (library corner, RC corner)**, 2 cores, 8-43 s wall and
1.0-1.3 GB RSS per run, one licensed tool at a time. The flow, per run:

1. `set_app_var search_path` / `link_path {* <stdcell corner>.db <every macro>.db}`; a macro
   with a single characterisation (TT-only SRAM) is linked at every corner and that limitation
   is written next to every ss/ff figure. Physical-only cells (fill, tap, `decap_12`) are not in
   the `.db` and are black-boxed (LNK-005), harmless
2. `read_verilog` + `current_design` + `link_design`; assert the SDC md5 inside the script and
   abort on mismatch, then `read_sdc`; `set_propagated_clock` on the real clocks only (a
   propagated **virtual** clock ignores its network latency)
3. `read_parasitics -format spef <spef>` of the RC corner paired with the library corner. The
   9-corner matrix was every pairing of {tt, ss, ff} with {nom, min, max}; the pairing is
   written in each run's metrics. Copy the SPEF into the run directory and record its md5
   before and after the copy, so a SPEF replaced mid-sweep is caught
4. `update_timing`, then the **annotation gate**: `report_annotated_parasitics -check
   -internal_nets -boundary_nets -driverless_nets -loadless_nets -pin_to_pin_nets`, gated on the
   pin-to-pin row (PT splits out driverless and loadless nets, which have no timing arc), plus
   the same report with `-list_not_annotated` on the clock nets (`get_nets -of_objects
   [all_fanout -flat -clock_tree]`; `-clock_tree` takes no `-from`). `read_parasitics` writes
   its own summary to `parasitics_command.log` in the cwd, not stdout. Result here: 0
   unannotated pin-to-pin nets in every run. SPEF nets absent from the netlist (PARA-124, e.g.
   ICC2 `_dummynet*`) are counted, not failed
5. `check_timing -verbose`, `report_global_timing`, `report_qor`, `report_constraint
   -all_violators -max_transition -max_capacitance`, and per-endpoint WNS/TNS/violators from
   `get_timing_paths -delay_type max|min -max_paths 1000000 -nworst 1 -slack_lesser_than 0`.
   `report_global_timing` prints `No setup violations found.` instead of a table when clean;
   `set_app_var report_default_significant_digits 4` (the default 2 hid a -0.0046 ns slack).
   Its reg-to-reg / in-to-reg categories move when I/O constraints change: for a reg-to-reg
   figure use explicit `-from [all_registers] -to [all_registers]`
6. Accept the run only with non-empty setup and hold WNS: a run whose `read_sdc` aborted
   produced a "done" run with empty metrics until this check was added

- **`read_sdc` stops at the first unsupported command and drops everything after it, without
  failing the session.** An **Innovus-exported SDC is not PT-readable as is**: remove the
  `current_design` line and replace `get_designs` with `current_design`, then diff the result.
  The first own-SDC results (+2.85 / +0.34 ns) came from a half-read SDC and were invalid
- **A tool-written SDC is a different constraint set.** ICC2's `write_sdc` added
  `set_clock_latency 1.77814` "for io paths" (`-origin useful_skew`) that the shared SDC lacks
  (a 1.2 ns native-vs-judge hold gap on I/O); Innovus keeps I/O latency in each view's
  `latency.sdc` and exports only part of it. Diff every tool-written SDC against the shared one
  and record each variant's md5 (shared / I/O-latency variant / the tool's own); rank flows only
  on the shared SDC, and report the others as diagnostics
- **Native vs judge.** With identical inputs (same SPEF, SDC, SI off) PT matched Innovus within
  0.06 ns setup, so the judge engine was not the gap. The measured Innovus native-vs-judge ladder
  was SI on vs off (+1.0 ns), hidden I/O latency (-2.9 ns), tech-LEF RC vs StarRC (+1.2 ns) and
  activity 0.2 vs 0.1 (17 mW). Explain a gap by swapping one input at a time
- **PrimePower.** `set_app_var power_enable_analysis true`, `power_analysis_mode averaged`,
  vectorless with `power_default_toggle_rate 0.1` and `power_default_static_probability 0.5`,
  `update_power`, `report_power -nosplit`. PT propagates activity through registers from D;
  OpenSTA gives register outputs the default activity, a **15 % difference** on the same design.
  Adding `set_switching_activity -toggle_rate 0.1 -static_probability 0.5 -base_clock <clk>
  [all_registers -output_pins]` matched OpenSTA within 2-3 %. With PT's own default the judge
  reproduced ICC2's native power (same engine) to 0.3 %. State which activity a number uses
- **SRAM paths.** PT and OpenSTA disagreed on an SRAM clk→dout delay (0.43 vs 2.25 ns, same net
  and load) because the load lay outside the macro's Liberty table and the engines extrapolate
  differently; check macro output loads against the table range

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
7. **Prove each judged run used the inputs it claims.** Record the md5 of the netlist, the SPEF
   and the SDC in every run and compare them with the files the flow delivered; a stale SPEF
   or a half-read SDC produces plausible numbers. In the measured three-flow comparison this,
   with the annotation gate, is what made a 27-run sweep per flow trustworthy
8. **Close the implementation in the corners you judge in.** Flows implemented with tt-only
   views lost 7.8-14.7 ns at ss in the judge, almost all reg-to-reg; the same tools with
   ss/tt setup and ff/tt hold views in implementation lost none. A tt-only flow judged at 9
   corners measures the corner scope of the run, not the tool

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
