# Design for Test (DFT) Flow — Full Architecture Design
## Orchestrator + Stage Agents + Skills

> **Purpose**: AI-driven DFT flow covering scan insertion, ATPG, BIST, JTAG/boundary scan, and DFT sign-off. Ensures the manufactured chip is fully testable and meets quality targets (DPPM, fault coverage).

---

## 1. Shared State Object

```json
{
  "run_id": "dft_001",
  "design_name": "my_chip",
  "inputs": {
    "netlist":          "path/to/netlist.v",
    "sdc":              "constraints.sdc",
    "dft_spec":         "dft_architecture.md",
    "tech_lib":         "cells.lib",
    "fault_coverage_target": 99.0,
    "dppm_target":      10
  },
  "stages": {
    "dft_architecture":   { "status": "pending", "output": {} },
    "scan_insertion":     { "status": "pending", "output": {} },
    "atpg":               { "status": "pending", "output": {} },
    "bist_insertion":     { "status": "pending", "output": {} },
    "jtag_setup":         { "status": "pending", "output": {} },
    "dft_signoff":        { "status": "pending", "output": {} }
  },
  "fault_coverage": 0.0,
  "scan_chains":    [],
  "flow_status": "not_started"
}
```

---

## 2. Stage Sequence

```text
dft_architecture → scan_insertion → atpg → bist_insertion → jtag_setup → dft_signoff
```

Loop-back rules — the target stage, the iteration cap, and which failures escalate
instead of looping — are in `## Loop-Back Rules` of [`dft-orchestrator.md`](../plugins/dft/agents/dft-orchestrator.md). That file is
authoritative; this document does not restate them.

---

## 3. Skill File Specifications

### 3.1 `sv-dft-architecture/SKILL.md`

```markdown
# Skill: DFT — Architecture Planning

## Purpose
Define the complete DFT strategy before any DFT insertion begins.

## DFT Strategy Elements
1. Scan architecture: full-scan vs partial-scan decision
2. Scan chain count: balance test time vs routing overhead
   - Rule of thumb: sqrt(total flip-flops) chains
3. Scan chain length: equal length balancing (± 5%)
4. Compression: EDT/OPMISR for large designs (> 1M FFs)
5. BIST: MBIST for all embedded SRAMs; LBIST for logic (optional)
6. JTAG: IEEE 1149.1 TAP controller; boundary scan for IO test
7. At-speed test: launch-on-capture (LOC) or launch-on-shift (LOS)
8. Test modes: scan_mode, mbist_mode, jtag_mode (exclusive)
9. Power domain consideration: scan must respect UPF power domains

## DFT Constraints
- Scan enable (SE): primary input, must be controllable
- Scan data in (SDI): one per chain
- Scan data out (SDO): one per chain
- Test clock: separate from functional clock (or gated)

## QoR Metrics
- DFT spec completeness: all elements defined
- Estimated fault coverage: analytical pre-insertion estimate
- Estimated test time: within ATE budget

## Output Required
- DFT architecture document
- Scan chain plan (count, estimated length, IOs)
- Test mode definitions
```

---

### 3.2 `sv-dft-scan/SKILL.md`

```markdown
# Skill: DFT — Scan Insertion

## Purpose
Insert scan flip-flops and connect scan chains into the gate-level netlist.

## Domain Rules
1. Replace all standard FFs with scan-equivalent cells (SDFF, SDFFRQ, etc.)
2. Avoid scan in: clock gating enables, async set/reset paths (without care)
3. Exclude from scan: memory-mapped registers, MBIST controllers, JTAG cells
4. Balance chain lengths: longest chain = test time bottleneck
5. EDT compression: insert compressor/decompressor if > 100K FFs
6. Lockup latches: insert between chains crossing clock domains
7. Scan re-order: minimize routing wirelength (place-aware reordering)
8. Test point insertion: controllability/observability points for low-coverage nets

## Scan DRC Rules (must pass)
- No clock feeds into scan data path
- No combinational feedback loops through scan
- Scan enable is glitch-free during functional mode
- All scan FFs have proper SI/SE connections

## QoR Metrics
- Scan FF count: N (target: 100% of sequential elements, minus exclusions)
- Chain count: per architecture spec
- Chain length balance: ± 5% of target
- Scan DRC: 0 errors

## Output Required
- Scan-inserted netlist
- Scan chain definition file (.scandef)
- Scan DRC report
```

---

### 3.3 `sv-dft-atpg/SKILL.md`

```markdown
# Skill: DFT — ATPG (Automatic Test Pattern Generation)

## Purpose
Generate test patterns that achieve target fault coverage and
produce a test program for ATE.

## Fault Models
| Fault Model      | Description                          | Target Coverage |
|------------------|--------------------------------------|-----------------|
| Stuck-at (SAF)   | Net stuck at 0 or 1                  | ≥ 99%           |
| Transition Delay | Slow-to-rise / slow-to-fall          | ≥ 95%           |
| Path Delay       | Timing faults on critical paths      | Critical paths  |
| Bridging         | Two nets shorted together            | ≥ 90%           |
| Cell-Aware       | Intra-cell defects (PDK-based)       | ≥ 95%           |

## ATPG Domain Rules
1. Run ATPG at multiple capture clocks (slow/fast)
2. X-bounding: improve pattern quality with X-pessimism reduction
3. Abort limit: set per tool (patterns per fault target)
4. Untestable faults: classify as Redundant or ATPG-Untestable; document
5. Pattern compression: use compressed patterns for EDT designs
6. At-speed patterns: verify with STA that launch/capture timing is met
7. Simulate patterns: verify 0 good-machine simulation failures

## QoR Metrics
- SAF coverage: ≥ 99%
- Transition coverage: ≥ 95%
- Pattern count: minimized (ATE time = cost)
- Good-machine simulation: 0 failures

## Output Required
- Test pattern file (STIL or WGL format)
- Fault report (coverage per model)
- Untestable fault list with classification
```

---

### 3.4 `sv-dft-bist/SKILL.md`

```markdown
# Skill: DFT — BIST (Built-In Self Test)

## Purpose
Insert and verify MBIST controllers for embedded memories
and optionally LBIST for logic self-test.

## MBIST Rules
1. One MBIST controller per memory group (same width/depth class)
2. March algorithms: MATS+, March-C, or algorithm per quality target
3. MBIST must cover: stuck-at, transition, coupling faults in SRAM
4. MBIST isolation: memories disconnected from logic during BIST
5. MBIST power: verify IR drop during simultaneous BIST (all memories)
6. MBIST access: via JTAG TAP or dedicated BIST port

## LBIST Rules (if applicable)
1. STUMPS architecture: PRPG + MISR + scan chains
2. Alias probability: target < 1e-10
3. LBIST clock: separate from functional (usually divided)
4. Exclude: analog, IO, and hard-macro internals

## QoR Metrics
- MBIST: all memory instances covered
- MBIST fault coverage: ≥ 99% for target fault models
- BIST power: within IR drop budget during test
- LBIST (if used): alias probability within target

## Output Required
- BIST-inserted netlist
- BIST controller connection report
- MBIST fault coverage report
- BIST power estimate
```

---

### 3.5 `sv-dft-jtag/SKILL.md`

```markdown
# Skill: DFT — JTAG and Boundary Scan

## Purpose
Implement IEEE 1149.1 TAP controller and boundary scan for
chip-level interconnect test and debug access.

## Domain Rules
1. TAP signals: TCK, TMS, TDI, TDO, TRST_N — dedicated pins required
2. Boundary scan cells: all digital IO pins must have BSR cells
3. Instructions: BYPASS, IDCODE, SAMPLE/PRELOAD, EXTEST at minimum
4. IDCODE register: 32-bit, unique per device per IEEE 1149.1
5. DR chain: boundary scan register → BYPASS → user registers
6. Isolation: TAP must be accessible when core is in reset
7. IEEE 1149.7: optional Compact JTAG (2-pin) for pin-limited designs
8. Security: JTAG lockout mechanism for production (OTP/fuse based)

## QoR Metrics
- TAP DRC: all required instructions implemented
- Boundary scan chain: all IOs included
- JTAG connectivity test: passes in simulation
- IDCODE: unique and correctly programmed

## Output Required
- JTAG-inserted netlist
- BSDL file (Boundary Scan Description Language)
- TAP connectivity report
```

---

## 4. Orchestrator System Prompt

The orchestrator's system prompt is its agent definition, [`dft-orchestrator.md`](../plugins/dft/agents/dft-orchestrator.md): stage
sequence, loop-back rules, stage gating and escalation. This document does not
restate it.
