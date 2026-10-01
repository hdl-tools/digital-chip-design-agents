# SoC IP Integration Flow — Full Architecture Design
## Orchestrator + Stage Agents + Skills

> **Purpose**: AI-driven flow for assembling a complete SoC from first-party RTL blocks, licensed hard/soft IPs, and memory macros. Covers IP procurement, integration, bus fabric configuration, and chip-level verification.

---

## 1. Shared State Object

```json
{
  "run_id": "soc_integration_001",
  "soc_name": "my_soc",
  "inputs": {
    "arch_doc":        "path/to/microarch.md",
    "ip_list": [
      { "name": "ARM_Cortex_M33", "type": "hard_ip", "vendor": "ARM" },
      { "name": "USB3_PHY",       "type": "hard_ip", "vendor": "Synopsys" },
      { "name": "AXI_Interconnect","type": "soft_ip","vendor": "internal" },
      { "name": "SRAM_256K",      "type": "memory_macro", "vendor": "foundry" }
    ],
    "bus_fabric":      "AXI4 + APB3",
    "technology":      "tsmc7nm"
  },
  "stages": {
    "ip_procurement":     { "status": "pending", "output": {} },
    "ip_configuration":   { "status": "pending", "output": {} },
    "bus_fabric_setup":   { "status": "pending", "output": {} },
    "top_integration":    { "status": "pending", "output": {} },
    "chip_level_sim":     { "status": "pending", "output": {} },
    "integration_signoff":{ "status": "pending", "output": {} }
  },
  "ip_status": {},
  "connectivity_errors": [],
  "flow_status": "not_started"
}
```

---

## 2. Stage Sequence

```text
ip_procurement → ip_configuration → bus_fabric_setup → top_integration → chip_level_sim → integration_signoff
```

Loop-back rules — the target stage, the iteration cap, and which failures escalate
instead of looping — are in `## Loop-Back Rules` of [`soc-integration-orchestrator.md`](../plugins/soc/agents/soc-integration-orchestrator.md). That file is
authoritative; this document does not restate them.

---

## 3. Skill File Specifications

### 3.1 `sv-soc-ip-procurement/SKILL.md`

```markdown
# Skill: SoC — IP Procurement and Quality Check

## Purpose
Evaluate, procure, and qualify all third-party IPs before integration.

## IP Qualification Checklist
- [ ] Deliverable format: RTL (.v/.sv), GDSII, or encrypted netlist?
- [ ] Technology node: certified for target process?
- [ ] Timing libraries: SS/TT/FF corners available?
- [ ] LEF/DEF: available for PD flow?
- [ ] Simulation models: behavioral/RTL for verification?
- [ ] UPF: power intent delivered?
- [ ] Databook: register map, timing diagrams, integration guide?
- [ ] DFT: scan-enabled? BIST available?
- [ ] Silicon proven: on which node/process?
- [ ] Support: SLA for bug fixes and updates?

## Hard IP vs Soft IP Integration Differences
| Aspect         | Hard IP (GDSII)          | Soft IP (RTL)              |
|----------------|--------------------------|----------------------------|
| Area           | Fixed                    | Synthesis-dependent        |
| Timing         | Characterized libs only  | Optimizable                |
| PD effort      | Place as macro           | Goes through full PD flow  |
| Customization  | None                     | Parameterizable            |
| Verification   | Behavioral model only    | Full RTL simulation        |

## Memory Macro Qualification
1. Verify compiler-generated views: .lib, .lef, .v (behavioral)
2. Check access time vs target frequency
3. Verify retention and power-down modes (if UPF power domain)
4. MBIST compatibility: verify BIST ports available

## Output Required
- IP qualification report per IP
- IP deliverable checklist (all views received)
- IP risk register (any gaps in deliverables)
```

---

### 3.2 `sv-soc-bus-fabric/SKILL.md`

```markdown
# Skill: SoC — Bus Fabric Configuration

## Purpose
Configure and verify the on-chip bus interconnect that connects
all IP blocks in the SoC.

## Bus Fabric Selection
| Fabric Type      | Use Case                          | Bandwidth  |
|------------------|-----------------------------------|------------|
| AXI4 Crossbar    | High-bandwidth data paths         | High       |
| AXI4-Lite        | Low-bandwidth control registers   | Low        |
| APB3             | Peripheral register access        | Low        |
| AHB              | Legacy peripheral bus             | Medium     |
| NoC              | Many-core, complex topologies     | Very High  |

## Configuration Requirements
1. Master/slave port assignment: every IP mapped to correct bus
2. Address decoding: non-overlapping address regions for all slaves
3. Data width conversion: AXI width adapters where needed
4. Clock domain crossing: async bridges for multi-clock SoC
5. QoS: traffic class assignment for latency-sensitive masters
6. Outstanding transactions: configure per master (depth)
7. Error handling: define response for out-of-range addresses (DECERR)

## Memory Map Validation
- No address region overlaps
- All peripherals accessible from all required masters
- Reserved regions correctly handled (no decode → DECERR)
- Aliasing: verify no unintended address aliases

## QoR Metrics
- Address decode: complete, no gaps, no overlaps
- All IP blocks: connected to correct bus with correct width
- CDC bridges: in place for all clock domain crossings
- Simulation: all registers read/write correctly

## Output Required
- Bus fabric configuration file
- Memory map document (final, versioned)
- Address decoder verification report
```

---

### 3.3 `sv-soc-top-integration/SKILL.md`

```markdown
# Skill: SoC — Top-Level Integration

## Purpose
Assemble all IP blocks, bus fabric, memories, and IOs into
the chip top-level module.

## Top-Level Integration Rules
1. Top module: wiring only — no logic at top level
2. All IPs instantiated once (no duplicate instances without intent)
3. All ports connected — no unconnected ports (use lint to verify)
4. Clock generation: PLL/clock mux module at top or near-top
5. Reset generation: reset synchronizer per domain at top level
6. IO ring: all pads instantiated and connected
7. Tie cells: VDD/VSS tie-offs for floating inputs

## Integration Checklist (Per IP)
- [ ] Correct module name and parameters
- [ ] All required ports connected (no NC ports on active signals)
- [ ] Clock connected to correct domain clock
- [ ] Reset connected to correct domain reset (correct polarity)
- [ ] Power/ground ports connected (for UPF power domains)
- [ ] Scan chain: SI/SO connected to scan chain backbone
- [ ] JTAG: TDI/TDO routed through JTAG chain

## Common Integration Bugs
- Wrong clock domain for a signal → metastability in silicon
- Polarity inversion on reset → block never comes out of reset
- Unconnected valid/enable → block runs freely or never runs
- AXI address offset: peripheral at wrong base address

## QoR Metrics
- Lint: 0 unconnected ports on active signals
- CDC check: no new violations introduced at top level
- Memory map: all IPs respond to correct addresses in simulation
- Smoke test: all IPs accessible via bus in simulation

## Output Required
- Top-level RTL (soc_top.sv)
- Integration lint report
- IP connectivity summary
```

---

### 3.4 `sv-soc-chip-sim/SKILL.md`

```markdown
# Skill: SoC — Chip-Level Simulation and Verification

## Purpose
Verify the assembled SoC through chip-level simulation,
checking all IPs work together correctly.

## Chip-Level Simulation Strategy
1. Boot test: CPU boots, executes from reset vector
2. Peripheral access: read/write all peripheral registers
3. DMA test: DMA transfers between memory regions
4. Interrupt test: each peripheral can interrupt CPU
5. Multi-master: concurrent bus access from multiple masters
6. Clock switching: verify clock mux operates correctly
7. Power mode: enter/exit sleep/deep-sleep modes
8. Reset: warm reset, cold reset, per-domain reset

## Simulation Infrastructure
1. Chip-level testbench: models entire board environment
2. External memory model: DRAM/Flash behavioral model
3. PHY models: for USB, Ethernet, SERDES (or transactor)
4. Protocol checkers: AXI assertion checkers on all buses
5. Self-checking: firmware prints PASS/FAIL to UART model

## Regression Structure
| Test               | Scope                    | Run time |
|--------------------|--------------------------|----------|
| Smoke              | Boot + reg access        | < 1hr    |
| Full regression    | All peripheral tests     | < 24hr   |
| Long-run           | Stress: throughput, IRQ  | 48hr     |

## QoR Metrics
- All peripheral register tests: PASS
- Boot test: CPU reaches application code
- DMA: correct data at correct address
- No AXI protocol violations (checker clean)
- No X propagation at key outputs after reset

## Output Required
- Chip-level simulation report
- Per-test pass/fail log
- Protocol checker clean report
```

---

## 4. Orchestrator System Prompt

The orchestrator's system prompt is its agent definition, [`soc-integration-orchestrator.md`](../plugins/soc/agents/soc-integration-orchestrator.md): stage
sequence, loop-back rules, stage gating and escalation. This document does not
restate it.
