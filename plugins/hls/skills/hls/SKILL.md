---
name: hls
description: >
  High-Level Synthesis — C/C++ algorithm analysis, HLS directive optimisation,
  synthesis execution, and co-simulation verification. Use when converting C/C++
  to synthesisable RTL, optimising for latency/throughput/area targets using
  pragmas, or verifying that generated RTL matches the golden C model.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: High-Level Synthesis (HLS)

## Invocation

- **If invoked by a user** presenting an HLS task: immediately spawn the
  `digital-chip-design-agents:hls-orchestrator` agent and pass the full user
  request and any available context. Do not execute stages directly.
- **If invoked by the `hls-orchestrator` mid-flow**: do not spawn a new agent.
  Treat this file as read-only — return the requested stage rules, sign-off
  criteria, or loop-back guidance to the calling orchestrator.

Spawning the orchestrator from within an active orchestrator run causes recursive
delegation and must never happen.

## Pre-run Context

Before executing or advising on **any** stage, read the following files if they exist:

1. `memory/hls/knowledge.md` — known failure patterns, successful tool flags, PDK/tool quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `memory/hls/run_state.md` — current run identity (`run_id`, `design_name`, `tool`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Convert C/C++/SystemC algorithmic descriptions to synthesisable RTL.
Covers algorithm analysis for HLS compatibility, pragma/directive optimisation,
and co-simulation to verify RTL matches the golden C model.

---

## Supported EDA Tools

### Open-Source
- **Bambu HLS** (`bambu`) — open-source HLS from Politecnico di Milano
- **LegUp HLS** — FPGA-targeted HLS built on LLVM
- **Calyx / Futil** — infrastructure for HLS compilers (academic)
- **MLIR/CIRCT** (`circt-opt`) — compiler infrastructure for hardware design

### Proprietary
- **Xilinx Vitis HLS** (`vitis_hls`) — C/C++ to RTL for AMD/Xilinx devices
- **Cadence Stratus** (`stratus`) — SystemC/C++ HLS for ASIC and FPGA
- **Siemens Catapult** (`catapult`) — algorithmic synthesis from C++/SystemC

---

## Stage: algorithm_analysis

### HLS-Hostile Patterns (must fix before synthesis)
1. Dynamic memory (malloc/new) → replace with fixed-size static arrays
2. Recursive functions → convert to iterative with explicit stack
3. Pointer aliasing → use `restrict` keyword or restructure accesses
4. System calls (printf, file I/O) → wrap in `#ifndef __SYNTHESIS__`
5. Function pointers → replace with switch/case dispatch
6. Data-dependent loop bounds → add maximum bound + early-exit flag
7. Floating-point → evaluate fixed-point (`ap_fixed<W,I>` for Vitis HLS)

### Analysis Steps
1. Identify innermost critical loop — the performance bottleneck
2. Analyse loop-carried dependencies — limit achievable II
3. Classify memory access: sequential (burst-able) vs random (expensive)
4. Calculate theoretical minimum latency: trip_count × body_latency

### QoR Metrics to Evaluate
- All HLS-hostile patterns resolved
- Critical loop identified with dependency graph
- Theoretical II lower bound computed

### Output Required
- Algorithm analysis report
- Fixed-point type recommendations (if applicable)
- Critical loop dependency graph

---

## Stage: directive_planning

### Pipelining and Throughput
```cpp
#pragma HLS PIPELINE II=1          // Pipeline loop, target II=1
#pragma HLS DATAFLOW                // Task-level pipelining
#pragma HLS LOOP_FLATTEN            // Flatten nested loops
#pragma HLS LOOP_MERGE              // Merge sequential loops
```

### Latency and Unrolling
```cpp
#pragma HLS UNROLL factor=4        // Partial unroll (4 parallel copies)
#pragma HLS UNROLL                  // Full unroll (small trip counts only)
```

### Memory and Interfaces
```cpp
#pragma HLS ARRAY_PARTITION variable=buf cyclic factor=4
#pragma HLS INTERFACE mode=axis port=data       // AXI4-Stream
#pragma HLS INTERFACE mode=m_axi port=mem       // AXI4 master
#pragma HLS INTERFACE mode=s_axilite port=ctrl  // AXI4-Lite registers
```

### Resource Binding
```cpp
#pragma HLS BIND_OP op=mul impl=dsp      // Force multiply to DSP
#pragma HLS ALLOCATION operation=mul limit=4   // Cap DSP count
```

### Strategy by Target
| Target | Primary Directives |
|--------|--------------------|
| Low latency | UNROLL + PIPELINE II=1 |
| High throughput | PIPELINE + DATAFLOW + ARRAY_PARTITION |
| Low area | ALLOCATION limits + no UNROLL |
| Balanced | PIPELINE II=1 inner loop + ARRAY_PARTITION |

### QoR Metrics to Evaluate
- Achieved II: ≤ `design_state.constraints.hls.target_ii` (one of target_ii or target_latency_cycles must be set; prefer target_ii if both — see Constraint Validation section)
- Latency: ≤ `design_state.constraints.hls.target_latency_cycles` cycles (one of target_ii or target_latency_cycles must be set)
- Area: within budget
- No directive synthesis errors

### Output Required
- Annotated source with all directives and justifications
- Directive justification table

---

## Stage: hls_synthesis

### Domain Rules
1. Synthesise at target clock period
2. Check HLS report: latency, II, resource usage
3. Compare achieved vs target — loop back to directives if miss
4. Flag any warnings: unresolved dependencies, failed II, inferred latches
5. Verify interface protocols match system integration requirements

### QoR Metrics to Evaluate
- II: matches or beats `design_state.constraints.hls.target_ii` (one of target_ii or target_latency_cycles must be set; prefer target_ii if both)
- Latency: within `design_state.constraints.hls.target_latency_cycles` cycles (one of target_ii or target_latency_cycles must be set)
- Area: within budget
- No latch inference warnings

### Output Required
- HLS synthesis report (latency, II, resource summary)
- Generated RTL files
- Unresolved warnings with justification

---

## Stage: rtl_qc

### Domain Rules
1. Run lint on HLS-generated RTL using the rtl-design skill's `lint_check` ERROR and WARNING
   levels. Generated RTL is linted for correctness — latches, multiple drivers, undriven
   outputs, width truncation — not for the rtl-design naming and style rules, which a
   generator will not follow; do not hand-edit generated RTL to satisfy them
2. Verify no latches in generated RTL. With slang this requires full elaboration
   (`slang -Weverything --ignore-unknown-modules <files>`); `--lint-only` skips elaboration and
   reports zero latches on any input, so it can never fail this check
3. Verify interface signal names match integration requirements
4. Check all registers reset correctly

### QoR Metrics to Evaluate
- Lint: 0 errors
- No latches inferred
- Interface ports match integration spec

### Output Required
- Lint report on HLS-generated RTL

---

## Stage: cosimulation

### Domain Rules
1. C testbench drives RTL through HLS wrapper
2. RTL outputs compared against C golden model automatically
3. Measure actual latency and II — must match HLS report ±5%
4. Exercise all code paths; test boundary conditions

### Common Failures
| Failure | Fix |
|---------|-----|
| Output mismatch | Check fixed-point overflow; increase bit widths |
| AXI handshake error | Fix INTERFACE pragma configuration |
| Latency differs | Verify loop bounds are static |
| X propagation | Initialise all variables in C source |

### QoR Metrics to Evaluate
- Co-simulation: 100% output match with C golden model
- Latency measured: within `design_state.constraints.hls.cosim_tolerance_pct`% of HLS report (default: 5%)
- II measured: matches HLS report exactly
- No simulation errors or X propagation

### Output Required
- Co-simulation pass/fail report
- Latency and II measurement log

---

## Stage: hls_signoff

### Sign-off Checklist
- [ ] All HLS-hostile patterns resolved
- [ ] Achieved II ≤ `design_state.constraints.hls.target_ii` (one of target_ii or target_latency_cycles must be set; prefer target_ii if both)
- [ ] Latency ≤ `design_state.constraints.hls.target_latency_cycles` cycles (one of target_ii or target_latency_cycles must be set)
- [ ] Area within budget
- [ ] RTL QC: lint clean, no latches
- [ ] Co-simulation: 100% output match; latency within `design_state.constraints.hls.cosim_tolerance_pct`% (default: 5%)
- [ ] Interface ports match system integration spec

### Output Required
- HLS RTL package (generated .v/.sv files)
- Co-simulation pass report
- HLS QoR report (latency, II, area)
- Interface documentation

---

## Constraint Validation

See `plugins/meta/skills/pipeline-orchestration/SKILL.md` §Constraints Schema for the authoritative schema and stage-entry validation rule.

**Required at entry (`algorithm_analysis`) — at least one must be non-null:**
- `constraints.hls.target_ii` — target initiation interval (one of target_ii or target_latency_cycles must be set; prefer target_ii if both)
- `constraints.hls.target_latency_cycles` — target latency in clock cycles (one of target_ii or target_latency_cycles must be set)

**Optional (schema defaults apply when absent):**
- `constraints.hls.cosim_tolerance_pct` (default: 5) — acceptable co-simulation latency deviation %
- `constraints.clock.clk_mhz` — target clock for synthesis (used if set; otherwise tool default)

---

## Memory

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
write or overwrite one JSON record in `memory/hls/experiences.jsonl` keyed by
`run_id`. This ensures data is persisted even if the flow is interrupted or called
without full orchestrator context.

Use `run_id` = `hls_<YYYYMMDD>_<HHMMSS>` (set once at flow start; reuse on each
stage update). Every JSON record written must include a top-level `"run_id"` field
whose value matches this key — this is what makes overwrites unambiguous. Set
`signoff_achieved: false` until the final sign-off stage completes.
### Run state (write before first stage, update after each stage)
Write `memory/hls/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:      hls_<YYYYMMDD>_<HHMMSS>
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
applied fix as an observation to entity `chip-design-hls-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.
