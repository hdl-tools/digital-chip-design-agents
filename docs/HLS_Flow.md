# High-Level Synthesis (HLS) Flow — Full Architecture Design
## Orchestrator + Stage Agents + Skills

> **Purpose**: AI-driven HLS flow converting C/C++/SystemC algorithmic descriptions into RTL. Bridges the software and hardware worlds. Covers algorithm analysis, HLS directives, RTL quality check, and co-simulation verification.

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    HLS ORCHESTRATOR                          │
│  Input:  C/C++ algorithm, performance/area targets, TB       │
│  Output: Verified RTL matching golden C model                │
└────────────────────────┬─────────────────────────────────────┘
                         │
     ┌───────────────────┼───────────────────────┐
     ▼                   ▼                       ▼
  Algorithm          HLS Synthesis          Co-simulation
  Analysis           Agent                  Agent
     │                   │                       │
  SKILL              SKILL                   SKILL
```

---

## 2. Shared State Object

```json
{
  "run_id": "hls_001",
  "design_name": "fft_block",
  "inputs": {
    "source_files":    ["fft.cpp", "fft.h"],
    "testbench":       "fft_tb.cpp",
    "golden_output":   "golden.dat",
    "target_freq":     "500MHz",
    "target_latency":  "256 cycles",
    "target_area":     "50K gates",
    "interface":       "AXI4-Stream",
    "tool":            "Vitis_HLS | Catapult | Stratus"
  },
  "stages": {
    "algorithm_analysis":  { "status": "pending", "output": {} },
    "directive_planning":  { "status": "pending", "output": {} },
    "hls_synthesis":       { "status": "pending", "output": {} },
    "rtl_qc":              { "status": "pending", "output": {} },
    "cosimulation":        { "status": "pending", "output": {} },
    "hls_signoff":         { "status": "pending", "output": {} }
  },
  "hls_report": {
    "latency_cycles": null,
    "ii":             null,
    "area_lut":       null,
    "area_ff":        null,
    "area_dsp":       null
  },
  "cosim_match": null,
  "flow_status": "not_started"
}
```

---

## 3. Stage Sequence

```text
algorithm_analysis → directive_planning → hls_synthesis → rtl_qc → cosimulation → hls_signoff
```

Loop-back rules — the target stage, the iteration cap, and which failures escalate
instead of looping — are in `## Loop-Back Rules` of [`hls-orchestrator.md`](../plugins/hls/agents/hls-orchestrator.md). That file is
authoritative; this document does not restate them.

---

## 4. Skill File Specifications

### 4.1 `sv-hls-algorithm/SKILL.md`

```markdown
# Skill: HLS — Algorithm Analysis

## Purpose
Analyze C/C++ source to identify HLS-friendly and HLS-hostile
patterns before synthesis begins.

## HLS-Friendly Patterns
- Fixed-size arrays (no dynamic allocation)
- Regular loop bounds (no data-dependent exit)
- Integer arithmetic (vs floating point — area expensive)
- Pipeline-able loops (no loop-carried dependencies or resolvable ones)
- Power-of-2 array sizes (memory banking benefit)

## HLS-Hostile Patterns (Must Fix Before Synthesis)
1. Dynamic memory (malloc/new) → replace with static arrays
2. Recursive functions → unroll or convert to iterative
3. Pointer aliasing → use restrict or restructure
4. System calls (printf, file I/O) → remove or #ifdef guard
5. Function pointers → replace with switch/case
6. Data-dependent loop bounds → bound with maximum + early exit
7. Floating point → consider fixed-point conversion (ap_fixed<>)

## Performance Analysis
1. Identify critical loop(s): innermost loop = performance bottleneck
2. Calculate minimum latency: trip count × body latency
3. Identify data dependencies: loop-carried dependencies limit II
4. Memory access pattern: sequential (burst-able) vs random (expensive)

## QoR Metrics
- All HLS-hostile patterns resolved before synthesis
- Critical loop identified with dependency analysis
- Memory access pattern documented

## Output Required
- Algorithm analysis report
- Recommended fixed-point types (if applicable)
- Critical loop dependency graph
```

---

### 4.2 `sv-hls-directives/SKILL.md`

```markdown
# Skill: HLS — Directive Planning

## Purpose
Select and apply HLS pragmas/directives to achieve target
latency, throughput (II), and area.

## Core Directives (Vitis HLS syntax shown; adapt for Catapult/Stratus)

### Throughput / Pipelining
```cpp
#pragma HLS PIPELINE II=1         // Pipeline loop with II=1
#pragma HLS DATAFLOW               // Task-level pipelining (producer-consumer)
#pragma HLS LOOP_FLATTEN           // Flatten nested loops for pipelining
#pragma HLS LOOP_MERGE             // Merge sequential loops into one
```

### Latency / Unrolling
```cpp
#pragma HLS UNROLL factor=4       // Partial unroll (4 parallel copies)
#pragma HLS UNROLL                 // Full unroll (all iterations in parallel)
```

### Memory / Interfaces
```cpp
#pragma HLS ARRAY_PARTITION variable=buf cyclic factor=4  // Parallel access
#pragma HLS ARRAY_RESHAPE variable=buf cyclic factor=4    // Reshape for port width
#pragma HLS INTERFACE mode=axis port=data                 // AXI4-Stream
#pragma HLS INTERFACE mode=m_axi port=mem                 // AXI4 master (DRAM)
```

### Resource Binding
```cpp
#pragma HLS BIND_OP variable=result op=mul impl=fabric    // LUT multiplier
#pragma HLS BIND_OP variable=result op=mul impl=dsp       // DSP multiplier
#pragma HLS ALLOCATION operation=mul limit=4              // Max 4 multipliers
```

## Directive Strategy by Target
| Target          | Primary Directives                              |
|-----------------|-------------------------------------------------|
| Low latency     | UNROLL, PIPELINE II=1                          |
| High throughput | PIPELINE + DATAFLOW, ARRAY_PARTITION           |
| Low area        | ALLOCATION limits, share resources, no unroll  |
| Balanced        | PIPELINE II=1 on inner loop + ARRAY_PARTITION  |

## QoR Metrics
- Achieved II: ≤ target II
- Latency: ≤ target cycles
- Area: within gate budget
- No directives causing synthesis errors

## Output Required
- Annotated source with all directives
- Directive justification table
- Expected QoR from HLS report
```

---

### 4.3 `sv-hls-cosim/SKILL.md`

```markdown
# Skill: HLS — Co-simulation and Verification

## Purpose
Verify that the generated RTL is functionally equivalent to the
original C/C++ golden model.

## Co-simulation Flow
1. HLS tool wraps RTL in SystemC/Verilog simulation wrapper
2. C testbench drives RTL through wrapper
3. RTL outputs compared against C golden model automatically
4. Waveforms available for debug

## Verification Requirements
1. Testbench must exercise all code paths (line coverage in C)
2. Corner cases: max values, zero, overflow conditions
3. Back-to-back transactions: verify pipeline not broken
4. Latency verification: measure RTL latency vs HLS report
5. II verification: confirm initiation interval matches report

## Common Co-sim Failures
- AXI interface handshake timing mismatch → fix interface directives
- Overflow in fixed-point conversion → increase bit widths
- Initialization differences (C vs RTL reset behavior) → align reset
- Loop exit condition mismatch → check data-dependent bounds

## QoR Metrics
- Co-simulation: 100% output match with golden C model
- Latency measured: within 5% of HLS report
- II measured: matches HLS report
- No simulation errors or X propagation

## Output Required
- Co-simulation pass/fail report
- Latency/II measurement
- Waveform for debug (if fail)
```

---

## 5. Orchestrator System Prompt

The orchestrator's system prompt is its agent definition, [`hls-orchestrator.md`](../plugins/hls/agents/hls-orchestrator.md): stage
sequence, loop-back rules, stage gating and escalation. This document does not
restate it.
