---
name: soc-integration
description: >
  SoC IP integration — IP procurement and qualification, IP configuration,
  bus fabric setup, top-level RTL integration, and chip-level simulation.
  Use when assembling a SoC from multiple IP blocks, configuring an AXI
  bus interconnect, integrating memory macros, or running chip-level tests.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: SoC IP Integration

## Invocation

When this skill is loaded and a user presents a SoC integration task, **do not
execute stages directly**. Immediately spawn the
`digital-chip-design-agents:soc-integration-orchestrator` agent and pass the full
user request and any available context to it. The orchestrator enforces the stage
sequence, loop-back rules, and sign-off criteria defined below.

Use the domain rules in this file only when the orchestrator reads this skill
mid-flow for stage-specific guidance, or when the user asks a targeted reference
question rather than requesting a full flow execution.

## Pre-run Context

Before executing or advising on **any** stage, read the following files if they exist:

1. `memory/soc/knowledge.md` — known failure patterns, successful tool flags, PDK/tool quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `memory/soc/run_state.md` — current run identity (`run_id`, `design_name`, `tool`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Assemble a complete SoC from first-party RTL, licensed hard/soft IPs, and
memory macros. Covers IP procurement, bus fabric configuration, top-level
integration, and chip-level simulation sign-off.

---

## Supported EDA Tools

### Open-Source
- **Verilator** (`verilator`) — fast simulation of the integrated top-level
- **cocotb** — Python co-simulation for bus-fabric and peripheral tests
- **FuseSoC** (`fusesoc`) — IP package manager and build system for SoC integration
- **Edalize** — EDA tool abstraction layer used with FuseSoC

### Proprietary
- **Synopsys VCS** (`vcs`) — chip-level simulation with coverage
- **Cadence Xcelium** (`xrun`) — multi-language chip-level simulation
- **Siemens Questa** (`vsim`) — chip-level simulation and protocol checking

---

## Stage: ip_procurement

### IP Qualification Checklist
- [ ] Deliverable format: RTL (.v/.sv), GDSII, or encrypted netlist?
- [ ] Technology node: certified for target process?
- [ ] Timing libraries: SS/TT/FF corners available?
- [ ] LEF/DEF: available for PD flow?
- [ ] Simulation models: behavioural/RTL for verification?
- [ ] UPF: power intent delivered?
- [ ] Databook: register map, timing diagrams, integration guide?
- [ ] DFT: scan-enabled? BIST available?
- [ ] Silicon proven: on which node?
- [ ] Support SLA: bug-fix and update commitment?

### Hard IP vs Soft IP
| Aspect | Hard IP (GDSII) | Soft IP (RTL) |
|--------|----------------|---------------|
| Area | Fixed | Synthesis-dependent |
| Timing | Characterised libs only | Optimisable |
| PD effort | Place as macro | Full PD flow |
| Customisation | None | Parameterisable |

### Memory Macro Qualification
1. Verify compiler-generated views: .lib, .lef, .v (behavioural)
2. Check access time vs target frequency
3. Verify retention/power-down modes (for UPF power domains)
4. Confirm MBIST ports available

### Output Required
- IP qualification report per IP
- IP deliverable checklist (all views received)
- IP risk register (gaps in deliverables)

---

## Stage: ip_configuration

### Domain Rules
1. Configure each IP per its databook for target use case
2. Parameterise data widths, FIFO depths, feature enables
3. Verify configured timing meets `design_state.constraints.clock.clk_mhz` MHz target frequency at worst-case corner
4. Verify interface widths match bus fabric port requirements
5. Generate integration wrapper if IP port names differ from system conventions

### Output Required
- Configured IP files and wrappers
- Timing verification report (configured corner)

---

## Stage: bus_fabric_setup

### Bus Fabric Selection
| Fabric Type | Use Case | Bandwidth |
|-------------|---------|-----------|
| AXI4 Crossbar | High-bandwidth data paths | High |
| AXI4-Lite | Low-bandwidth control registers | Low |
| APB3 | Peripheral register access | Low |
| NoC | Many-core topologies | Very High |

### Domain Rules
1. Non-overlapping address regions for all slaves
2. AXI width adapters for any width mismatches
3. Async bridges for all cross-clock-domain connections
4. QoS: assign traffic class for latency-sensitive masters
5. Error handling: out-of-range address → DECERR response defined

### Memory Map Validation
- No address region overlaps
- All peripherals accessible from all required masters
- Reserved regions return DECERR
- No unintended address aliasing

### QoR Metrics to Evaluate
- Address decode: complete, no gaps, no overlaps
- All IP blocks connected with correct port width
- CDC bridges in place for all clock crossings

### Output Required
- Bus fabric configuration file
- Memory map document (final, versioned)
- Address decoder verification report

---

## Stage: top_integration

### Domain Rules
1. Top module: wiring only — no logic at top level
2. All IPs instantiated once (no unintended duplicates)
3. All ports connected — lint check for unconnected active signals
4. Clock generation: PLL/mux module at or near top level
5. Reset generation: synchroniser per domain at top level
6. Tie cells: VDD/VSS tie-offs for all floating inputs
7. Scan chain: SI/SO routed through scan backbone
8. JTAG: TDI/TDO routed through JTAG chain
9. Instantiate every IP with named port connections — a positional connection silently
   mis-wires when an IP revision reorders its ports
10. Lint `soc_top.sv` in the context of the full SoC filelist, compiled as one unit. Linted
    alone, every IP is an unknown module and port-width mismatches go unchecked
11. An IP that is deliberately black-boxed (hard macro, analog block, encrypted IP) is a stub:
    undriven-net findings on its outputs are not connectivity errors. Record them as
    informational and name the stub, so a real unconnected port is not lost among them. A
    stub is benign only if you can name the macro or IP it stands for: an unknown module that
    resolves to first-party RTL in this repository is a missing filelist entry (rule 12)
12. An IP or module is not integrated until every tool's source list can see it. Simulation,
    lint, synthesis, PD and formal usually read separate lists, often Makefile variables, and a
    module missing from one is black-boxed by sv2v and yosys without an error while the
    chip-level regression, reading another list, stays green. Enumerate every list and confirm
    each new file is in each, or state why not; for `.f` lists run
    `plugins/rtl-design/skills/rtl-design/check_design_inputs.py <filelist.f> --rtl-dir <rtl>
    --list <name>=<file> ...`
13. Where a downstream flow converts the RTL before synthesis (sv2v, Surelog/UHDM), run the
    conversion on the SoC filelist and parse the output with the consuming tool
    (`sv2v <files> > out.v && yosys -q -p 'read_verilog out.v; hierarchy -check -top soc_top'`).
    A construct legal in SystemVerilog and not in Verilog-2005 passes lint and chip-level
    simulation and fails only there

### Integration Checklist (per IP)
- [ ] Correct module name and parameters
- [ ] All active ports connected
- [ ] Clock: correct domain
- [ ] Reset: correct domain and polarity
- [ ] Power ports: correct UPF domain
- [ ] Scan: SI/SO connected
- [ ] Source files registered in every tool's source list (simulation, lint, synthesis, PD, formal)

### Common Integration Bugs
| Bug | Consequence |
|-----|------------|
| Wrong clock domain | Metastability in silicon |
| Reset polarity inversion | Block never exits reset |
| Unconnected valid/enable | Block runs freely or never |
| AXI address offset wrong | Peripheral at wrong base address |
| Module missing from the synthesis or PD source list | Silently black-boxed: wrong netlist behind a green simulation regression |
| SystemVerilog construct the converter cannot lower | Synthesis or PD front-end syntax error that lint and simulation never see |

### Output Required
- Top-level RTL (soc_top.sv)
- Integration lint report
- IP connectivity summary

---

## Stage: chip_level_sim

### Required Tests
1. Boot test: CPU boots from reset vector, executes code
2. Peripheral access: read/write all peripheral registers
3. DMA: transfers between memory regions verified
4. Interrupt: each peripheral can interrupt CPU and ISR fires
5. Multi-master: concurrent bus access from multiple masters
6. Clock switching: clock mux operates correctly
7. Power modes: enter and exit sleep/deep-sleep
8. Reset: warm and cold reset; all blocks re-initialise

### QoR Metrics to Evaluate
- All peripheral register tests: PASS
- Boot test: CPU reaches application code
- DMA: correct data at correct address
- No AXI protocol violations (checker clean)
- No X propagation at key outputs after reset

### Output Required
- Chip-level simulation report
- Per-test pass/fail log
- Protocol checker clean report

---

## Stage: integration_signoff

### Sign-off Checklist
- [ ] All IP qualification issues resolved
- [ ] Memory map: final, agreed, no overlaps
- [ ] Top-level lint: 0 unconnected active ports
- [ ] CDC: 0 violations at chip level
- [ ] All chip-level simulation tests: PASS
- [ ] AXI protocol checker: clean
- [ ] Every module visible to every tool's source list, exemptions named with a reason
- [ ] Converted RTL parses in each downstream front-end, or the check is reported NOT RUN

### Output Required
- Integration sign-off report
- Final memory map document
- Integrated SoC RTL package (ready for synthesis)

---

## Constraint Validation

See `plugins/meta/skills/pipeline-orchestration/SKILL.md` §Constraints Schema for the authoritative schema and stage-entry validation rule.

**Required at entry (`ip_procurement`) — hard-fail if missing:**
- `constraints.clock.clk_mhz` — target SoC clock frequency; used to verify IP timing at `ip_configuration`

**Optional (schema defaults apply when absent):**
- `constraints.timing.wns_ns_target` (default: 0) — WNS sign-off threshold for chip-level timing
- `constraints.area.area_um2` — total SoC area budget (used to cross-check IP area estimates)
- `constraints.power.power_mw` — SoC power budget

---

## Memory

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
write or overwrite one JSON record in `memory/soc/experiences.jsonl` keyed by
`run_id`. This ensures data is persisted even if the flow is interrupted or called
without full orchestrator context.

Use `run_id` = `soc_<YYYYMMDD>_<HHMMSS>` (set once at flow start; reuse on each
stage update). Set `signoff_achieved: false` until the final sign-off stage completes.
### Run state (write before first stage, update after each stage)
Write `memory/soc/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:      soc_<YYYYMMDD>_<HHMMSS>
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
applied fix as an observation to entity `chip-design-soc-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.
