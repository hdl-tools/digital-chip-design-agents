---
name: dft
description: >
  Design for Test — scan architecture planning, scan insertion, ATPG pattern
  generation, MBIST for embedded memories, and JTAG boundary scan. Use when
  planning a DFT strategy, inserting scan, generating test patterns, or
  verifying that a chip will be testable in manufacturing.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: Design for Test (DFT)

## Invocation

- **If invoked by a user** presenting a DFT task: immediately spawn the
  `digital-chip-design-agents:dft-orchestrator` agent and pass the full user
  request and any available context. Do not execute stages directly.
- **If invoked by the `dft-orchestrator` mid-flow**: do not spawn a new agent.
  Treat this file as read-only — return the requested stage rules, sign-off
  criteria, or loop-back guidance to the calling orchestrator.

Spawning the orchestrator from within an active orchestrator run causes recursive
delegation and must never happen.

## Pre-run Context

Before executing or advising on **any** stage, read the following files if they exist:

1. `memory/dft/knowledge.md` — known failure patterns, successful tool flags, PDK/tool quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `memory/dft/run_state.md` — current run identity (`run_id`, `design_name`, `tool`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Guide the complete DFT flow from architecture planning through ATPG pattern
generation, BIST insertion, JTAG setup, and sign-off. Ensures the manufactured
chip meets quality targets (fault coverage and DPPM).

---

## Supported EDA Tools

### Open-Source
- **Yosys DFT plugins** (`yosys`) — basic scan insertion for open-source flows
- **OpenROAD DFT utilities** (`openroad`) — scan insertion within the OpenROAD/ORFS flow

### Proprietary
- **Synopsys TetraMAX ATPG** (`tmax`, dialect `synopsys`) — pattern generation, fault simulation, and compression
- **Cadence Modus Test** (`modus`, dialect `cadence`) — ATPG, scan DRC, and diagnosis
- **Siemens Tessent** (`tessent`, dialect `siemens`) — full DFT suite: scan, ATPG, MBIST, IJTAG.
  See Tool Notes: Siemens Tessent below for the flow and its traps

---

## Stage: dft_architecture

### Domain Rules
1. Scan architecture: full-scan preferred for ASIC; capture all sequential elements
2. Scan chain count: a chain count the project's DFT architecture fixes (a scan-port budget, a
   tester channel count, a decision record) wins. √(total flip-flops) is a fallback rule of
   thumb only when nothing is specified; balance test time vs routing. Record which source the
   count came from
3. Chain length balance: ±5% of target length across all chains
4. Compression: EDT/OPMISR for designs > 1M FFs to reduce ATE test time
5. MBIST: one controller per memory group (same width/depth class)
6. JTAG: IEEE 1149.1 TAP controller; boundary scan for all IO pins
7. At-speed test: launch-on-capture (LOC) or launch-on-shift (LOS) — agree with test team
8. Test modes: scan_mode, mbist_mode, jtag_mode must be mutually exclusive
9. Power domains: scan must respect UPF power domain boundaries
10. Run the scan-readiness audit below on the incoming design before planning chains. A
    blocker found here costs an RTL edit; the same blocker found at Scan DRC costs an
    insertion run first
11. Any DFT logic delivered as RTL rather than inserted by a tool (TAP controller, BIST
    controller, test-mode muxes, wrappers) is synthesisable RTL: it follows the rtl-design
    skill's coding rules and passes lint with 0 errors before it is integrated

### Scan-Readiness Audit (before insertion)
Check the RTL or pre-DFT netlist for constructs that block scan. Each is owned by the RTL
flow, not by scan insertion:
- RTL-generated clocks (`assign gclk = clk & en;`) — gated flops are unreachable in scan mode
- Clock-gating cells with no test-enable (`test_en` / `scan_en`) OR-ed into the enable
- Asynchronous set/reset driven by internal logic with no test-mode bypass — it cannot be
  held inactive during shift
- Latches other than deliberate lockup latches and clock-gate cell internals
- Combinational feedback loops — ATPG cannot model them
- On-chip tri-state buses — contention is untestable
- Memories with neither a bypass path nor a BIST wrapper (a FIFO's storage array is a memory)
- Black boxes and analog interfaces with no defined test-mode behaviour

Report each finding with the instance and the rule above. A finding that insertion can
repair (a test point, a tool-inserted reset or clock mux) is planned into `scan_insertion`;
one that needs an RTL change is handed back to the RTL flow — do not edit the RTL here.

### DFT IO Signals Required
- `scan_en` (SE): primary input, must be controllable from ATE
- `scan_in[]` (SDI): one per chain
- `scan_out[]` (SDO): one per chain
- `test_clk`: separate from functional clock or gated version

### QoR Metrics to Evaluate
- DFT spec completeness: all elements defined before insertion
- Scan-readiness audit: 0 findings that need an RTL change left open
- Estimated fault coverage: analytical pre-insertion estimate ≥ target
- Estimated test time: within ATE budget

### Output Required
- DFT architecture document
- Scan-readiness audit report (finding, instance, owner: insertion or RTL)
- Scan chain plan (count, estimated length, IOs)
- Test mode definitions

---

## Stage: scan_insertion

### Domain Rules
1. Replace all standard FFs with scan-equivalent cells (SDFF, SDFFRQ, etc.)
2. Exclude from scan: memory-mapped registers, MBIST controllers, JTAG cells
3. Do not place scan in: clock gating enables, async set/reset paths (without care cells)
4. EDT compression: insert compressor/decompressor for > 100K FFs
5. Lockup latches: insert between chains crossing clock domain boundaries
6. Scan re-ordering: minimise routing wirelength (use placement-aware reorder)
7. Test points: add controllability/observability points for low-coverage nets
8. Classify every Scan DRC error by owner before retrying. An error insertion can repair
   (chain connection, test point, tool-inserted reset or clock mux, lockup latch) is retried
   here. An error caused by the design itself — a generated clock, an uncontrollable
   asynchronous reset, an unintended latch, a combinational loop — is not changed by running
   insertion again: stop and hand it back to the RTL flow with the instance and the rule
9. A fix must not trade coverage for a clean report: do not clear a Scan DRC error by
   excluding the offending flops from scan, or raise ATPG coverage by reclassifying faults as
   untestable, unless the exclusion is justified and recorded
10. The same holds for rule severities. Demoting a Scan DRC rule from error to warning so the
    tool will leave setup mode is allowed only for flops an architecture decision deliberately
    keeps off the chains (a TAP-clocked domain, a BIST controller). Name the decision, the rule
    IDs, and the instance count in the DRC report; any other instance the demoted rule hides is
    an open finding

### Scan DRC Rules (all must pass before ATPG)
- No clock signals feeding into scan data path
- No combinational feedback loops through scan
- Scan enable is glitch-free during functional mode
- All scan FFs: correct SI/SE connections

### QoR Metrics to Evaluate
- Scan FF count: 100% of sequential elements minus explicit exclusions
- Chain count and length: per architecture spec (±5%)
- Scan DRC: 0 errors

### Output Required
- Scan-inserted netlist
- Scan chain definition file (.scandef)
- Scan DRC report

---

## Stage: atpg

### Fault Model Targets
| Fault Model | Target Coverage |
|-------------|----------------|
| Stuck-at (SAF) | ≥ `design_state.constraints.dft.saf_coverage_pct`% (default: 99%) |
| Transition Delay | ≥ `design_state.constraints.dft.transition_coverage_pct`% (default: 95%) |
| Cell-Aware | ≥ `design_state.constraints.dft.cell_aware_coverage_pct`% (default: 95%) |
| Bridging | ≥ `design_state.constraints.dft.bridging_coverage_pct`% (default: 90%) |
| Path Delay | Critical paths only |

### Domain Rules
1. Run ATPG at multiple capture clocks (slow and fast for transition)
2. X-bounding: apply to improve pattern quality
3. Untestable faults: classify as Redundant or ATPG-Untestable; document all
4. Pattern compression: use compressed patterns for EDT designs
5. At-speed patterns: verify capture timing with STA before signing off
6. Good-machine simulation: run all patterns on RTL or gate sim — 0 failures allowed. A run
   of a pattern subset is reported as that subset (`20 of 1574`), never as the full set
7. Prove the pattern testbench can fail: re-run it once on a netlist with one scan link broken
   (or one pattern bit flipped) and confirm it reports mismatches. A testbench that passes the
   broken netlist too has compared nothing, and its good-machine PASS is unverified
8. When the cell models used for ATPG and for pattern simulation are both derived from the same
   source (Verilog generated from a Liberty file because the vendor models are unavailable),
   say so: the two checks then share any misreading of that source and are not independent

### QoR Metrics to Evaluate
- SAF coverage: ≥ `design_state.constraints.dft.saf_coverage_pct`% (default: 99%)
- Transition coverage: ≥ `design_state.constraints.dft.transition_coverage_pct`% (default: 95%)
- Pattern count: minimised (ATE time = test cost)
- Good-machine simulation: 0 failures

### Output Required
- Test pattern file (STIL or WGL)
- Fault report (coverage per model)
- Untestable fault list with classification

---

## Stage: bist_insertion

### MBIST Rules
1. One MBIST controller per memory group (same width/depth class)
2. March algorithm: MATS+, March-C, or as required by quality spec
3. Memory isolation: memories disconnected from logic during BIST
4. Power: verify IR drop with all memories running BIST simultaneously
5. Access: via JTAG TAP or dedicated BIST port
6. Prove detection per fault class, not by a passing run. Inject each fault class the
   algorithm claims (stuck-at per bit and per address bit, transition, coupling, write-mask /
   byte-enable stuck, address decoder) into the memory simulation model, and check every run
   against an independent golden model of the expected verdict. Report detected/injected per
   class. A BIST that passes the fault-free memory proves only that it does not false-fail
7. Run fault proofs on the full address space. Generated MBIST patterns often default to a
   reduced address count to cut simulation time (Tessent: `reduced_address_count` on); a
   fault proof run that way misses faults outside the reduced range
8. When comparing a tool-generated MBIST against an existing in-house one, compare on the same
   memories and fault list: faults detected per class, test cycles per algorithm, and area.
   Count cycles the same way for both: a tool controller can test each logical port as a
   separate pass, which multiplies its cycle count for a multi-port memory

### LBIST Rules (if required)
1. STUMPS architecture: PRPG + MISR + scan chains
2. Alias probability: target < 1e-10
3. LBIST clock: separate from functional clock (usually divided)

### QoR Metrics to Evaluate
- MBIST: all memory instances covered
- MBIST fault coverage: ≥ `design_state.constraints.dft.mbist_coverage_pct`% (default: 99%)
- BIST power: within IR drop budget during test
- LBIST alias probability: within target (if applicable)

### Output Required
- BIST-inserted netlist
- BIST controller connection report
- MBIST fault coverage report
- BIST power estimate

---

## Stage: jtag_setup

### Domain Rules
1. TAP pins: TCK, TMS, TDI, TDO, TRST_N — dedicated pads required
2. Boundary scan cells: all digital IO pins must have BSR cells
3. Mandatory instructions: BYPASS, IDCODE, SAMPLE/PRELOAD, EXTEST
4. IDCODE register: 32-bit, unique per device, per IEEE 1149.1
5. TAP: accessible when core is in reset
6. Security: JTAG lockout mechanism for production (OTP/fuse based)

### QoR Metrics to Evaluate
- TAP DRC: all required instructions implemented
- Boundary scan chain: all IOs included
- JTAG connectivity simulation: passes
- IDCODE: unique and correctly formatted

### Output Required
- JTAG-inserted netlist
- BSDL file
- TAP connectivity report

---

## Stage: dft_signoff

### Sign-off Checklist
- [ ] Scan DRC: 0 errors
- [ ] SAF coverage: ≥ `design_state.constraints.dft.saf_coverage_pct`% (default: 99%)
- [ ] Transition coverage: ≥ `design_state.constraints.dft.transition_coverage_pct`% (default: 95%)
- [ ] Good-machine simulation: 0 failures
- [ ] MBIST: all memories covered; coverage ≥ `design_state.constraints.dft.mbist_coverage_pct`% (default: 99%)
- [ ] JTAG: BSDL generated and verified
- [ ] DFT netlist: LEC vs pre-DFT netlist EQUIVALENT

### Output Required
- DFT sign-off report
- Final test pattern files
- BSDL file
- DFT netlist (input to PD)

---

## Tool Notes: Siemens Tessent

Tessent's modern flow is context-based. The legacy `add_scan_groups` / `add_scan_chains` dofile
path can run to completion and insert nothing, so check the inserted-cell count, not the exit
status. Measured on Tessent 2025.4.

### Running it
- Batch: `tessent -shell -dofile <f>.do -log <f>.log -replace < /dev/null`. Without
  `< /dev/null` the shell waits on stdin after an aborted dofile and the job hangs. Without
  `-replace` an old log survives and reads like a result. Confirm the log's timestamp is this run's
- Remove the TSDB output directory before each scan-insertion run; a stale TSDB is read back
- Check that each option is accepted by the installed version before relying on it
  (2025.4 rejects `add_processors -number`)
- Treat licensed library files (algorithm libraries, `share/UsageExamples`) as read-only
  reference; copy what you adapt into the project

### Cell library (scan insertion and ATPG)
- `read_liberty` supplies cell attributes only. Cell behaviour comes from Verilog models
  compiled with LibComp (`libcomp <models.v> -dofile ... < /dev/null`) into an `.atpglib`;
  read that with `read_cell_library`, add `read_liberty`, and save both with
  `write_cell_library ... -include_created_dft_cell_selections` to a `.tcelllib` that the
  scan and patterns contexts read. Fail the step on any `// Error` line in the LibComp log
- Write the models with gate primitives. A bare `assign y = a;` buffer is modelled as a wire,
  and the cell then fails the tool's buffer check
- Curate the `dft_cell_selection`. The auto-generated one can pick special-purpose cells (for
  sky130, `lpflow_*` low-power cells). A buffer, inverter, 2:1 mux and lockup latch must be
  named explicitly

### Scan insertion and ATPG
1. `set_context dft -scan -no_rtl -design_id gate`, `read_cell_library <.tcelllib>`, read the
   netlist, `set_current_design`, define clocks, `set_scan_enable`, then
   `set_system_mode analysis` (scan DRC runs here)
2. `add_scan_mode <name> -chain_count N -si_connections [get_ports ...] -so_connections
   [get_ports ...]` to bind chains to existing scan ports, then `analyze_scan_chains`,
   `insert_test_logic`, `write_design -tsdb`. If port binding fails and a script falls back
   to tool-created ports, report it: the chains no longer use the architecture's ports
3. ATPG in a fresh session: `set_context patterns -scan`, `read_design <design> -design_id gate`,
   `import_scan_mode <name>`, then pattern generation per fault model
- When flops are deliberately left off the chains (scan_insertion rule 10), the S1/S2 scan
  rules fail on them and DRC will not leave setup mode until those rules are demoted. Record
  the demotion with its justification

### MemoryBIST
1. `set_context dft -rtl -design_id rtl1`; read the RTL and a memory library of TCD
   (`tcd_memory`) descriptions, one per memory macro
2. `check_design_rules`, `create_dft_specification`, edit it with `set_config_value` if needed,
   `process_dft_specification`
3. `extract_icl`, `create_patterns_specification`, `process_patterns_specification`
4. `run_testbench_simulations -simulator vcs` (or the simulator in use)
- Algorithm definitions and sample flows ship with the install
  (`lib/tools/etv/membistipg_algos/`, `share/UsageExamples/*.tgz`); read them before writing a TCD
- TCD traps: `LogicalPorts` lists read, write, then read-write ports in that order
  (`[nR][nW][nRW]`); without column address bits, `BitGrouping` is forced and cannot be set
- `DFT_C1-1`: every memory clock must trace from a primary input. A hand-instantiated library
  clock cell (a clock gate) is a black box to the trace unless its model is read
- Read the memory macro interface-only for insertion; reading its behavioural model as well
  gives a duplicate module in simulation
- Fault proofs: bist_insertion rules 6–7. Pass the injected fault by plusarg, and keep each
  fault's run in its own simulation directory so results cannot mix

---

## Constraint Validation

See `plugins/meta/skills/pipeline-orchestration/SKILL.md` §Constraints Schema for the authoritative schema and stage-entry validation rule.

**No required keys** for DFT — all constraints in this domain are optional with schema defaults.

**Optional (schema defaults apply when absent):**
- `constraints.dft.saf_coverage_pct` (default: 99) — stuck-at fault coverage target %
- `constraints.dft.transition_coverage_pct` (default: 95) — transition delay coverage target %
- `constraints.dft.cell_aware_coverage_pct` (default: 95) — cell-aware fault coverage target %
- `constraints.dft.bridging_coverage_pct` (default: 90) — bridging fault coverage target %
- `constraints.dft.mbist_coverage_pct` (default: 99) — MBIST memory fault coverage target %
- `constraints.dft.chain_balance_pct` (default: 5) — max chain length deviation %

Tag `constraint_ref` in history entries when evaluating QoR against these values (e.g. `"dft.saf_coverage_pct"`).

---

## Memory

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
write or overwrite one JSON record in `memory/dft/experiences.jsonl` keyed by
`run_id`. This ensures data is persisted even if the flow is interrupted or called
without full orchestrator context.

Use `run_id` = `dft_<YYYYMMDD>_<HHMMSS>` (set once at flow start; reuse on each
stage update). Every JSON record written must include a top-level `"run_id"` field
whose value matches this key — reject or regenerate if missing before writing. Set
`signoff_achieved: false` until the final sign-off stage completes.
### Run state (write before first stage, update after each stage)
Write `memory/dft/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:      dft_<YYYYMMDD>_<HHMMSS>
design_name: <design>
tool:        <primary tool>
start_time:  <ISO-8601>
last_stage:  null
```
Update `last_stage` to the completed stage name only after each stage finishes successfully.
This file lets wakeup-loop prompts and resumed sessions identify the correct run without
relying on in-memory state. Create the file and parent directories if they do not exist.

### Optional: claude-mem index
If `mcp__plugin_ecc_memory__add_observations` is available in this session, emit each
applied fix as an observation to entity `chip-design-dft-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.
