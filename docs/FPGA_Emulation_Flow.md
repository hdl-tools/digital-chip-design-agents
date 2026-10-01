# FPGA Emulation & Prototyping Flow — Full Architecture Design
## Orchestrator + Stage Agents + Skills

> **Purpose**: AI-driven flow for porting an ASIC design to an FPGA prototype platform. Enables pre-silicon hardware/software co-development, performance validation, and early firmware bring-up — months before silicon is available.

---

## 1. Shared State Object

```json
{
  "run_id": "fpga_proto_001",
  "design_name": "my_soc",
  "inputs": {
    "rtl_filelist":      "filelist.f",
    "fpga_platform":     "Xilinx VCU118 | Intel Stratix 10 | Aldec HES",
    "fpga_part":         "xcvu9p-flga2104-2L-e",
    "target_freq":       "50MHz",
    "asic_target_freq":  "1GHz",
    "memory_map":        "path/to/memory_map.md",
    "debug_requirements":["JTAG", "ILA", "UART_console"]
  },
  "stages": {
    "rtl_adaptation":    { "status": "pending", "output": {} },
    "partitioning":      { "status": "pending", "output": {} },
    "fpga_synthesis":    { "status": "pending", "output": {} },
    "bring_up":          { "status": "pending", "output": {} },
    "sw_validation":     { "status": "pending", "output": {} },
    "proto_signoff":     { "status": "pending", "output": {} }
  },
  "fpga_utilization": {},
  "timing_met": false,
  "sw_tests_passing": 0,
  "flow_status": "not_started"
}
```

---

## 2. Stage Sequence

```text
rtl_adaptation → partitioning → fpga_synthesis → bring_up → sw_validation → proto_signoff
```

Loop-back rules — the target stage, the iteration cap, and which failures escalate
instead of looping — are in `## Loop-Back Rules` of [`fpga-orchestrator.md`](../plugins/fpga/agents/fpga-orchestrator.md). That file is
authoritative; this document does not restate them.

---

## 3. Skill File Specifications

### 3.1 `sv-fpga-rtl-adapt/SKILL.md`

```markdown
# Skill: FPGA — RTL Adaptation

## Purpose
Modify ASIC RTL to be FPGA-compatible, replacing ASIC-specific
elements with FPGA equivalents.

## ASIC → FPGA Substitutions
| ASIC Element              | FPGA Replacement                        |
|---------------------------|-----------------------------------------|
| Memory macros (SRAM)      | Block RAM (BRAM) or URAM                |
| Clock PLLs (analog)       | FPGA MMCM/PLL primitives                |
| IO pad cells              | FPGA IOB + IOBUF primitives             |
| Analog/mixed-signal       | Stub model or remove                    |
| DFT scan logic            | Bypass or remove scan                   |
| Power management cells    | Remove (FPGA handles internally)        |
| Custom standard cells     | Generic behavioral model                |

## Memory Replacement Rules
1. Single-port SRAM → simple_dual_port or true_dual_port BRAM
2. Match port widths: BRAM has fixed width (36Kb, 18Kb)
3. Verify read latency: BRAM has 1-cycle read latency (vs 0 for some ASICs)
4. Register output option: can pipeline for timing closure
5. Large memories (> BRAM budget): use DRAM via MIG/DDR controller

## Clock Adaptation
1. Replace ASIC PLL with MMCM (Xilinx) or ALTPLL (Intel)
2. Scale all clocks to FPGA prototype frequency (typically 50–100MHz)
3. Multi-clock designs: maintain same ratio between domains
4. FPGA clock routing: use BUFG for global clocks, BUFR for regional

## QoR Metrics
- No ASIC-specific primitives in adapted RTL
- All memories mapped to FPGA resources
- Adapted RTL: lint clean
- Functional equivalence vs ASIC RTL (behavioral sim match)

## Output Required
- Adapted RTL file set
- Substitution log (what was replaced and why)
- BRAM utilization estimate
```

---

### 3.2 `sv-fpga-partition/SKILL.md`

```markdown
# Skill: FPGA — Multi-FPGA Partitioning

## Purpose
If the design exceeds a single FPGA capacity, partition it across
multiple FPGAs with correct inter-FPGA communication.

## Partitioning Guidelines
1. Aim for < 70% LUT utilization per FPGA (leave room for debug)
2. Minimize inter-FPGA signal count (each signal = physical connector pin)
3. Cut logic paths, not timing-critical paths
4. Keep clock domains intact within a single FPGA where possible
5. Inter-FPGA protocol: Aurora, GTH SERDES, or GPIO + sync

## Partitioning Strategies
| Strategy          | Best For                                  |
|-------------------|-------------------------------------------|
| Hierarchical      | Clean block boundaries in design          |
| Functional        | CPU on one FPGA, memory/IO on another     |
| Pipeline-based    | Deep pipelines with natural stage cuts    |

## Inter-FPGA Interface
1. Serialize wide buses across high-speed SERDES
2. Flow control: handshake for every inter-FPGA transaction
3. Latency budget: inter-FPGA adds latency — model in simulation
4. Debug: route status signals to FPGA LEDs or UART

## QoR Metrics
- Per FPGA: < 70% LUT, < 80% BRAM, < 80% DSP
- Inter-FPGA signal count: within connector pin budget
- No clock domain splits at partition boundary (unless CDC bridge)

## Output Required
- Partition plan (block → FPGA mapping)
- Inter-FPGA signal list
- Physical connector pin assignment
```

---

### 3.3 `sv-fpga-synthesis/SKILL.md`

```markdown
# Skill: FPGA — FPGA Synthesis and Implementation

## Purpose
Synthesize and implement the adapted RTL for the target FPGA,
achieving timing closure at prototype frequency.

## FPGA Implementation Flow (Xilinx Vivado)
1. Synthesis: vivado -mode batch -source synth.tcl
2. Implementation: opt_design → place_design → route_design → phys_opt_design
3. Timing analysis: report_timing_summary
4. Bitstream: write_bitstream

## Timing Closure Techniques
1. Reduce prototype clock frequency if timing fails
2. Add pipeline registers at critical paths (accept latency increase)
3. Use Pblock constraints to locate related logic near BRAMs/DSPs
4. Avoid long routing: break large fanout nets with BUFG
5. Phys_opt_design: rerun with -directive AggressiveExplore

## Debug Infrastructure
1. ILA (Integrated Logic Analyzer): add to critical signals
   - Max 64 probes per ILA core; use multiple cores
   - Trigger on: protocol errors, state machine states
2. VIO (Virtual IO): drive/sample test signals from PC
3. Debug bridge: JTAG-to-AXI for register access from PC

## QoR Metrics
- Timing: WNS ≥ 0 at prototype frequency
- Utilization: LUT < 70%, BRAM < 80%, DSP < 80%
- Bitstream: generates without DRC errors
- ILA: configured on key debug signals

## Output Required
- Bitstream (.bit file)
- Timing summary report
- Utilization report
- ILA probe definitions
```

---

### 3.4 `sv-fpga-bringup/SKILL.md`

```markdown
# Skill: FPGA — Prototype Bring-up

## Purpose
Bring the FPGA prototype to a functional state, validating
hardware before running software.

## Bring-up Sequence
1. Power-on: verify power rails, current draw within spec
2. FPGA configuration: load bitstream via JTAG or flash
3. Clock verification: measure prototype clock with oscilloscope
4. Reset sequence: verify all blocks come out of reset
5. Register access: read/write peripheral registers via JTAG-to-AXI
6. Memory test: write/read BRAM and external DDR
7. UART console: verify CPU boots and outputs boot messages
8. Minimal OS/RTOS: load and run boot firmware

## Debug Methodology
1. Start with known-good test: simple register read (chip ID register)
2. If fails: check clock, reset, power, bitstream loading
3. Use ILA to capture bus transactions in real-time
4. Use VIO to inject stimulus without re-synthesizing
5. Oscilloscope: check IO signal levels and timing

## Common Bring-up Issues
- Clock not running: MMCM lock bit not set → check PLL configuration
- CPU not booting: wrong reset vector or memory map → check linker script
- Register returns 0x00000000: base address wrong or bus not connected
- Register returns 0xDEADBEEF: out-of-range access returning DECERR value

## QoR Metrics
- All clock domains: running at correct frequency (measured)
- CPU: boots to firmware shell/UART prompt
- All peripheral registers: readable/writable via JTAG
- DDR: memory test passes (if external memory present)

## Output Required
- Bring-up test results log
- ILA capture for any failures
- Known issues list with workarounds
```

---

### 3.5 `sv-fpga-sw-validation/SKILL.md`

```markdown
# Skill: FPGA — Software Validation on Prototype

## Purpose
Run the firmware and software stack on the FPGA prototype
to validate both hardware and software functionality.

## Software Validation Tiers
1. BSP validation: all drivers work on FPGA prototype
2. RTOS validation: RTOS boots, all tasks run
3. Application validation: target application executes correctly
4. Performance profiling: measure real execution times

## Performance Scaling
- FPGA runs at 50MHz vs ASIC at 1GHz = 20x slower
- Timing-sensitive SW: scale timeouts by frequency ratio
- Performance numbers: note all measurements are at prototype frequency

## Key Validation Tests
- Peripheral loopback: UART, SPI, I2C self-tests
- DMA throughput: measure at FPGA frequency
- Interrupt latency: measure IRQ-to-handler entry
- Memory bandwidth: measure DDR throughput
- Application correctness: output matches golden reference

## Hardware Bug vs Software Bug Triage
1. Is the register map correct? (compare datasheet vs implementation)
2. Does the RTL simulation agree with FPGA behavior?
3. Is the timing margin sufficient? (check FPGA timing report)
4. Is the bug reproducible? (deterministic = likely HW)
5. Does it happen in RTL simulation? (yes → RTL bug, no → prototype issue)

## QoR Metrics
- All driver tests: PASS on prototype
- Application: produces correct output
- No hard lockups or unexpected resets
- Performance profiling: baseline established for silicon comparison

## Output Required
- Software validation report
- Performance baseline measurements
- Bug list (HW vs SW classification)
```

---

## 4. Orchestrator System Prompt

The orchestrator's system prompt is its agent definition, [`fpga-orchestrator.md`](../plugins/fpga/agents/fpga-orchestrator.md): stage
sequence, loop-back rules, stage gating and escalation. This document does not
restate it.
