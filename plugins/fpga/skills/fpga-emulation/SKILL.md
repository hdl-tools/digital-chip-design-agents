---
name: fpga-emulation
description: >
  FPGA prototyping — ASIC-to-FPGA RTL adaptation, multi-FPGA partitioning,
  synthesis and timing closure on FPGA, hardware bring-up, and software
  validation on the prototype. Use when porting an ASIC design to Xilinx or
  Intel FPGA for pre-silicon software development and hardware validation.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: FPGA Emulation & Prototyping

## Invocation

- **If invoked by a user** presenting an FPGA prototyping task: immediately spawn
  the `digital-chip-design-agents:fpga-orchestrator` agent and pass the full user
  request and any available context. Do not execute stages directly.
- **If invoked by the `fpga-orchestrator` mid-flow**: do not spawn a new agent.
  Treat this file as read-only — return the requested stage rules, sign-off
  criteria, or loop-back guidance to the calling orchestrator.

Spawning the orchestrator from within an active orchestrator run causes recursive
delegation and must never happen.

## Pre-run Context

Before executing or advising on **any** stage, read the following files if they exist:

1. `memory/fpga/knowledge.md` — known failure patterns, successful tool flags, PDK/tool quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `memory/fpga/run_state.md` — current run identity (`run_id`, `design_name`, `tool`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Port an ASIC design to an FPGA prototype platform for pre-silicon hardware/
software co-development. The FPGA prototype is not cycle-accurate but
provides functional and architectural validation months before silicon.

---

## Supported EDA Tools

### Open-Source
- **Yosys** (`yosys`) — open-source synthesis for Xilinx/Intel/Lattice FPGA targets
- **nextpnr** (`nextpnr-xilinx`, `nextpnr-ice40`, `nextpnr-ecp5`) — place-and-route for open-source flows
- **OpenFPGALoader** (`openFPGALoader`) — universal FPGA programmer
- **Project IceStorm** — iCE40 FPGA toolchain (icepack, iceprog, icetime)
- **Project X-Ray** — Xilinx 7-series bitstream documentation

### Proprietary
- **Xilinx Vivado** (`vivado`, dialect `xilinx`) — synthesis, implementation, and bitstream generation for AMD/Xilinx
- **Intel Quartus** (`quartus_sh`, dialect `intel`) — synthesis and programming for Intel/Altera FPGAs
- **Microchip Libero** (`libero`, dialect `microchip`) — synthesis and programming for PolarFire/SmartFusion FPGAs
- **Synopsys Synplify** (dialect `synopsys`) — FPGA synthesis front-end targeting multiple device families

---

## Stage: rtl_adaptation

### ASIC → FPGA Substitutions
| ASIC Element | FPGA Replacement |
|---|---|
| SRAM macros | BRAM/URAM (Xilinx) or M20K (Intel) |
| Analog PLLs | MMCM (Xilinx) or ALTPLL (Intel) |
| IO pad cells | FPGA IOB + IOBUF primitives |
| Analog/mixed-signal | Stub model or remove |
| DFT scan logic | Remove — not needed on prototype |
| Power management cells | Remove — FPGA handles internally |

### Memory Replacement Rules
1. Match port configuration (single-port vs dual-port)
2. BRAM has 1-cycle read latency — verify RTL handles this
3. Memories > available BRAM: use external DDR via MIG/HBM controller
4. Use `XPM_MEMORY` (Xilinx) or equivalent portable macros

### Clock Replacement Rules
1. Replace ASIC PLL with MMCM (Xilinx) or ALTPLL (Intel)
2. Scale all clocks to FPGA prototype frequency (typically 50–100 MHz from ≥ 1 GHz ASIC)
3. Maintain same ratio between clock domains
4. Use BUFG for all global clocks — never route clocks on data fabric

### Adapted RTL Rules
1. Adapted RTL meets the rtl-design skill's `lint_check` ERROR rules (latches, multiple
   drivers, undriven outputs). Re-lint after every edit, including edits made on a loop-back
   from `fpga_synthesis`, `bring_up` or `sw_validation`
2. Match the conventions of the ASIC file being adapted; do not restyle RTL you are only
   retargeting
3. `initial` blocks are permitted for FPGA memory and register initialisation, but only in
   FPGA-only files or under an FPGA-specific `` `ifdef `` — the ASIC source must stay free of
   them
4. Vendor primitives and macros (`XPM_MEMORY`, MMCM, BUFG, IOBUF) are unknown modules to an
   open-source linter. Lint with unknown modules ignored and treat undriven-net findings on
   their outputs as stub artefacts, not errors

### QoR Metrics to Evaluate
- No ASIC-specific primitives remain in adapted RTL
- All memories mapped to BRAM or external DDR
- Adapted RTL: lint clean, 0 errors
- Functional sim: adapted RTL produces same outputs as ASIC RTL

### Output Required
- Adapted RTL file set
- Substitution log (what was replaced and why)
- BRAM and MMCM resource estimate

---

## Stage: partitioning

### Domain Rules
1. Target utilisation per FPGA: < `design_state.constraints.fpga.lut_util_pct_max`% LUT (default: 70%) — leave room for ILA debug cores
2. Minimise inter-FPGA signal count — each signal uses a physical connector pin
3. Never cut timing-critical paths at partition boundaries
4. Keep complete clock domains within a single FPGA wherever possible
5. Inter-FPGA: Aurora or GTH SERDES for high-speed; GPIO for slow control

### QoR Metrics to Evaluate
- Per-FPGA: LUT < `design_state.constraints.fpga.lut_util_pct_max`% (default: 70%), BRAM < `design_state.constraints.fpga.bram_util_pct_max`% (default: 80%), DSP < `design_state.constraints.fpga.dsp_util_pct_max`% (default: 80%)
- Inter-FPGA signal count: within connector pin budget
- No clock domain split without explicit bridge

### Output Required
- Partition plan (block → FPGA mapping)
- Inter-FPGA signal list
- Physical connector pin assignment

---

## Stage: fpga_synthesis

### Domain Rules
1. Full Vivado (Xilinx) or Quartus (Intel) flow:
   synth → opt → place → route → phys_opt → bitstream
2. Timing target: WNS ≥ `design_state.constraints.timing.wns_ns_target` (default: 0) at prototype frequency
3. If WNS < 0: reduce frequency first; add pipeline registers second
4. Utilisation targets: LUT < `design_state.constraints.fpga.lut_util_pct_max`% (default: 70%), BRAM < `design_state.constraints.fpga.bram_util_pct_max`% (default: 80%), DSP < `design_state.constraints.fpga.dsp_util_pct_max`% (default: 80%)

### Debug Infrastructure (add before bitstream)
- ILA: up to 64 probes per core; trigger on errors or key FSM states
- VIO: drive and sample control/status signals from PC
- JTAG-to-AXI: register access from PC without re-synthesising

### Timing Closure Techniques
| Technique | When to Apply |
|-----------|--------------|
| Reduce clock frequency | First option — accept slower prototype |
| Add pipeline registers | When path identifiable and latency increase acceptable |
| Pblock constraints | Co-locate logic near BRAMs/DSPs |
| BUFG on high-fanout net | Break long high-fanout routes |
| phys_opt –directive AggressiveExplore | Last resort |

### QoR Metrics to Evaluate
- WNS ≥ `design_state.constraints.timing.wns_ns_target` (default: 0) at prototype frequency
- LUT < `design_state.constraints.fpga.lut_util_pct_max`% (default: 70%), BRAM < `design_state.constraints.fpga.bram_util_pct_max`% (default: 80%), DSP < `design_state.constraints.fpga.dsp_util_pct_max`% (default: 80%)
- Bitstream: no critical DRC errors
- ILA: configured on key debug signals

### Output Required
- Bitstream (.bit or .sof)
- Timing summary report
- Utilisation report
- ILA probe definition file

---

## Stage: bring_up

### Bring-up Sequence (follow in order)
1. Power-on: measure power rails; current within spec
2. FPGA configuration: load bitstream via JTAG or SPI flash
3. Clock verification: oscilloscope or ILA — verify frequency and stability
4. Reset: toggle reset; verify all status bits de-assert
5. Register access via JTAG-to-AXI: read chip-ID register — first functional test
6. Memory test: write and read-back BRAM and external DDR
7. UART console: CPU outputs boot messages — verify on serial terminal
8. Minimal firmware: bare-metal binary executes and prints PASS

### Common Failures
| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| MMCM lock never sets | PLL input freq out of range | Recheck MMCM config |
| CPU never outputs UART | Wrong reset vector or memory map | Check linker script |
| Register reads 0x00000000 | Base address wrong in SW | Compare memory_map.h vs HW |
| Register reads 0xDEADBEEF | Out-of-range access → DECERR | Fix address in driver |
| Intermittent data corruption | CDC issue in adapted RTL | Review clock crossings |

### QoR Metrics to Evaluate
- All clocks: correct frequency (measured)
- CPU: reaches UART prompt
- All peripheral registers: readable/writable via JTAG
- DDR memory test: passes (if present)

### Output Required
- Bring-up test results log
- ILA captures for any failures
- Known issues list for SW team

---

## Stage: sw_validation

### Domain Rules
1. Run embedded-firmware skill validation suite on FPGA prototype
2. Scale all timeouts by FPGA-to-ASIC frequency ratio (e.g., 20× for 50 MHz vs 1 GHz)
3. Record all performance measurements at FPGA frequency; note scale factor

### Hardware Bug vs Software Bug Triage
1. Reproducible deterministically? → likely HW bug
2. Same failure in RTL simulation? → RTL bug (fix RTL, not just firmware)
3. Different from RTL sim? → FPGA adaptation issue
4. Intermittent? → CDC or timing margin issue

### Validation Tiers on Prototype
| Test | Pass Criteria |
|------|--------------|
| BSP | All peripherals accessible |
| Driver unit | 100% per driver |
| System | Correct output vs golden |
| Long-run (4 hr) | 0 lockups, 0 unexpected resets |

### QoR Metrics to Evaluate
- All driver tests: PASS on prototype
- Application: correct output vs golden reference
- No lockups or unexpected resets in stress test
- Performance baseline: recorded at prototype frequency

### Output Required
- SW validation report
- Performance baseline (labelled as prototype-frequency values)
- Bug list (HW vs SW classification)
- Performance projection to silicon frequency

---

## Stage: proto_signoff

### Sign-off Checklist
- [ ] All clocks verified at correct frequency
- [ ] CPU boots and reaches application code
- [ ] All peripheral registers accessible
- [ ] All driver tests pass on prototype
- [ ] Application produces correct output
- [ ] 4-hour stress: clean
- [ ] All HW bugs filed to RTL team with ILA captures
- [ ] Performance baseline documented

### Output Required
- Prototype sign-off report
- Bug report for RTL team (HW bugs with ILA evidence)
- Performance baseline document
- Prototype user guide for SW development team

---

## Constraint Validation

See `plugins/meta/skills/pipeline-orchestration/SKILL.md` §Constraints Schema for the authoritative schema and stage-entry validation rule.

**Required at entry (`rtl_adaptation`) — hard-fail if missing:**
- `constraints.clock.clk_mhz` — ASIC target clock frequency; used to compute FPGA prototype frequency scale-down ratio

**Optional (schema defaults apply when absent):**
- `constraints.timing.wns_ns_target` (default: 0) — WNS closure threshold at prototype frequency
- `constraints.fpga.lut_util_pct_max` (default: 70) — per-FPGA LUT utilisation ceiling %
- `constraints.fpga.bram_util_pct_max` (default: 80) — per-FPGA BRAM utilisation ceiling %
- `constraints.fpga.dsp_util_pct_max` (default: 80) — per-FPGA DSP utilisation ceiling %

---

## Memory

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
write or overwrite one JSON record in `memory/fpga/experiences.jsonl` keyed by
`run_id`. This ensures data is persisted even if the flow is interrupted or called
without full orchestrator context. Use the experience record schema in
`memory/README.md`, with `key_metrics` fields `lut_count`, `fmax_mhz`, `timing_met`.

Use `run_id` = `fpga_<YYYYMMDD>_<HHMMSS>_<6-char-random>` where the 6-character suffix
is a lowercase hexadecimal string `[0-9a-f]` generated once at flow start using a secure
or pseudorandom RNG and reused unchanged on every stage update for this run.
`signoff_achieved` is a JSON boolean: set `signoff_achieved: false` until the final
sign-off stage completes.
### Run state (write before first stage, update after each stage)
Write `memory/fpga/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:        fpga_<YYYYMMDD>_<HHMMSS>_<6-char-random>
design_name:   <design>
tool:          <primary tool>
start_time:    <ISO-8601>
last_stage:    null
current_stage: <first stage name>
```
The 6-character random suffix must be lowercase hexadecimal [0-9a-f]. Update `current_stage`
when a stage starts, and set `last_stage` to the completed stage name only after successful
completion (then clear `current_stage`). This file lets wakeup-loop prompts and resumed
sessions identify the correct run. Create the file and parent directories if they do not exist.

### Optional: claude-mem index
If `mcp__plugin_ecc_memory__add_observations` is available in this session, emit each
applied fix as an observation to entity `chip-design-fpga-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.
