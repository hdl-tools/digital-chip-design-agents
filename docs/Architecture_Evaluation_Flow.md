# Architecture Evaluation Flow — Full Architecture Design
## Orchestrator + Stage Agents + Skills

> **Purpose**: AI-driven microarchitecture evaluation flow. Covers specification analysis, micro-architecture trade-off exploration, performance modelling, power/area estimation, and architecture sign-off. Designed to feed into RTL Design as the first stage of the digital design pipeline.

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│               ARCHITECTURE EVALUATION ORCHESTRATOR           │
│  Input:  Product spec, performance targets, power budget      │
│  Output: Microarchitecture document, validated trade-off      │
└────────────────────────┬─────────────────────────────────────┘
                         │
     ┌───────────────────┼───────────────────────┐
     ▼                   ▼                       ▼
┌──────────┐     ┌──────────────┐       ┌───────────────┐
│  Stage   │     │   Stage      │       │   Stage       │
│  Agent   │     │   Agent      │  ...  │   Agent       │
│  Spec    │     │  MicroArch   │       │  Sign-off     │
│  Analysis│     │  Exploration │       │               │
└────┬─────┘     └──────┬───────┘       └───────┬───────┘
     │                  │                       │
     ▼                  ▼                       ▼
┌──────────┐     ┌──────────────┐       ┌───────────────┐
│  SKILL   │     │    SKILL     │       │    SKILL      │
│  spec    │     │  microarch   │       │   arch-signoff│
└──────────┘     └──────────────┘       └───────────────┘
```

---

## 2. Shared State Object

```json
{
  "run_id": "arch_eval_001",
  "design_name": "my_soc",
  "inputs": {
    "product_spec":     "path/to/spec.pdf",
    "perf_targets":     { "throughput": "10Gbps", "latency": "<10ns" },
    "power_budget":     "500mW",
    "area_budget":      "5mm2",
    "technology":       "tsmc7nm",
    "use_cases":        ["streaming", "inference", "control"]
  },
  "stages": {
    "spec_analysis":         { "status": "pending", "output": {} },
    "arch_exploration":      { "status": "pending", "output": {} },
    "perf_modelling":        { "status": "pending", "output": {} },
    "power_area_estimation": { "status": "pending", "output": {} },
    "risk_assessment":       { "status": "pending", "output": {} },
    "arch_signoff":          { "status": "pending", "output": {} }
  },
  "selected_architecture": null,
  "trade_off_matrix": [],
  "flow_status": "not_started"
}
```

---

## 3. Stage Sequence

```text
spec_analysis → arch_exploration → perf_modelling → power_area_estimation → risk_assessment → arch_signoff
```

Loop-back rules — the target stage, the iteration cap, and which failures escalate
instead of looping — are in `## Loop-Back Rules` of [`architecture-orchestrator.md`](../plugins/architecture/agents/architecture-orchestrator.md). That file is
authoritative; this document does not restate them.

---

## 4. Skill File Specifications

### 4.1 `sv-arch-spec/SKILL.md`

```markdown
# Skill: Architecture — Specification Analysis

## Purpose
Decompose product specification into formal architectural requirements,
identify ambiguities, and produce a structured requirements document.

## Domain Rules
1. Classify requirements: functional, performance, power, area, interface
2. Identify under-specified areas and flag for clarification
3. Map use cases to required hardware blocks (datapath, control, memory, IO)
4. Extract interface requirements: protocols (AXI, PCIe, USB, Ethernet, etc.)
5. Identify safety/security requirements (ISO 26262, FIPS, etc.) if applicable
6. Assign priority to each requirement: Must-Have / Should-Have / Nice-to-Have

## QoR Metrics
- Requirements coverage: all spec sections mapped to arch requirement
- Ambiguity count: flag any unresolved spec ambiguities
- Interface completeness: all external interfaces identified

## Output Required
- Structured requirements document (JSON or Markdown)
- Interface list with protocols and bandwidths
- Open questions list for product/system team
```

---

### 4.2 `sv-arch-exploration/SKILL.md`

```markdown
# Skill: Architecture — Microarchitecture Exploration

## Purpose
Enumerate and evaluate candidate microarchitecture options against
performance, power, and area targets.

## Domain Rules
1. Generate at least 3 candidate architectures (conservative, balanced, aggressive)
2. Evaluate pipeline depth trade-offs (deeper = higher frequency, more area/power)
3. Evaluate parallelism options: SIMD, superscalar, spatial unrolling
4. Cache/memory hierarchy: size, associativity, latency vs area trade-off
5. Interconnect topology: bus, crossbar, NoC — evaluate bandwidth vs complexity
6. Consider IP reuse: identify available hard macros or licensed IPs
7. Document assumptions for each candidate

## Trade-off Matrix Template
| Candidate | Freq Target | Area Est. | Power Est. | Risk | Notes |
|-----------|-------------|-----------|------------|------|-------|
| Option A  | 1GHz        | 3mm2      | 300mW      | Low  | ...   |
| Option B  | 2GHz        | 6mm2      | 700mW      | High | ...   |

## QoR Metrics
- Number of candidates explored: minimum 3
- Each candidate: performance estimate within 20% of target
- Recommendation: single preferred candidate with rationale

## Output Required
- Trade-off matrix
- Recommended candidate with justification
- Assumptions and risks per candidate
```

---

### 4.3 `sv-arch-perf/SKILL.md`

```markdown
# Skill: Architecture — Performance Modelling

## Purpose
Build analytical or simulation-based performance models to validate
that the selected microarchitecture meets throughput and latency targets.

## Domain Rules
1. Use analytical models (Amdahl, Roofline) for initial estimates
2. Build transaction-level models (TLM/SystemC or Python) for complex pipelines
3. Model all bottlenecks: compute, memory bandwidth, IO throughput
4. Sweep key parameters: clock frequency, parallelism, cache size
5. Validate with representative workloads from use-case list
6. Include best/typical/worst-case scenarios

## QoR Metrics
- Throughput: must meet or exceed target by ≥ 10% margin
- Latency: must meet target at worst-case workload
- Memory bandwidth: must not exceed DRAM/SRAM bandwidth limit
- Model confidence: flag if model assumptions are unvalidated

## Output Required
- Performance model (script or spreadsheet)
- Throughput/latency results per use case
- Sensitivity analysis (which parameter matters most)
- Comparison against targets
```

---

### 4.4 `sv-arch-ppa/SKILL.md`

```markdown
# Skill: Architecture — Power and Area Estimation

## Purpose
Produce early-stage power and area estimates for the selected
microarchitecture before RTL is written.

## Domain Rules
1. Use technology library scaling data for area estimates (gates/mm2)
2. Activity-based dynamic power estimate: P = alpha * C * V^2 * f
3. Leakage estimate: from library characterization at target Vt mix
4. Memory area: use compiler estimates (SRAM, ROM, register files)
5. IO pad area: per pad ring design rules
6. Apply 15–20% margin to all estimates (RTL is never minimal)
7. Compare against budget; flag if estimate exceeds 80% of budget

## Clock Gating Opportunity Analysis
Using activity factors already collected for dynamic power:

1. For each clock domain, record activity factor α from use-case workload sweep.
2. Classify each domain:
   - α < 0.15 — **high gating opportunity**: flag as must-have RTL requirement
   - 0.15 ≤ α < 0.40 — **moderate gating opportunity**: flag as should-have RTL requirement
   - α ≥ 0.40 — **always-active**: document as always-on; no ICG needed
3. Produce a `clock_power_budget` table (one row per domain):

   | Domain | Frequency | α (activity) | Est. Clock Power (mW) | Gating Class |
   |--------|-----------|-------------|----------------------|--------------|
   | core   | 1 GHz     | 0.08        | 45                   | high         |
   | dsp    | 500 MHz   | 0.55        | 30                   | always-on    |

4. Include `clock_power_budget` table in the RTL hand-off package.

## QoR Metrics
- Area estimate: < 80% of budget (to allow RTL overhead margin)
- Dynamic power: < 80% of budget
- Leakage power: < 15% of total estimated power
- Clock-gating coverage: ≥ 60% of register-bank bits in high-opportunity domains
- Confidence level: HIGH / MEDIUM / LOW (based on model fidelity)

## Output Required
- Area breakdown by block
- Power breakdown: dynamic, leakage, per domain
- Comparison against targets with margin analysis
- `clock_power_budget` table (domain → frequency, activity factor, estimated clock power, gating class)
```

---

### 4.5 `sv-arch-risk/SKILL.md`

```markdown
# Skill: Architecture — Risk Assessment

## Purpose
Identify, classify, and propose mitigations for technical risks
in the selected microarchitecture.

## Domain Rules
1. Risk categories: schedule, technical feasibility, IP availability,
   tool support, verification complexity, power closure
2. Score each risk: Probability (1–5) × Impact (1–5) = Risk Score
3. Flag any risk score ≥ 15 as HIGH — requires mitigation plan
4. IP risks: verify availability and licensing timeline
5. Tool risks: verify EDA tool support for chosen technology
6. Verification risks: estimate TB complexity; flag if > 6 months est.

## QoR Metrics
- No unmitigated HIGH risks at sign-off
- All risks have assigned owner and mitigation plan
- Schedule risk: total identified risks vs team capacity

## Output Required
- Risk register (ID, description, score, mitigation, owner)
- Top 5 risks highlighted for management review
```

---

### 4.6 `sv-arch-signoff/SKILL.md`

```markdown
# Skill: Architecture — Sign-off

## Purpose
Confirm that the selected microarchitecture fully satisfies all
requirements and is ready to proceed to RTL design.

## Sign-off Checklist
- [ ] All Must-Have requirements addressed
- [ ] Performance targets met in model (with margin)
- [ ] Power/area estimates within budget
- [ ] All HIGH risks mitigated
- [ ] Interface specifications complete and agreed
- [ ] Memory map defined
- [ ] Clock domains identified and CDC strategy agreed
- [ ] Reset strategy defined
- [ ] DFT strategy agreed (scan, BIST, JTAG)
- [ ] Verification strategy agreed (UVM, formal, emulation split)
- [ ] `clock_power_budget` table produced; gating class assigned per domain
- [ ] Clock-gating coverage ≥ 60% of register bits in high-opportunity domains
- [ ] Hand-off package includes `clock_power_budget` table for RTL team

## Output Required
- Signed-off microarchitecture document
- Final trade-off decision record
- RTL design guidelines derived from architecture
- Hand-off package for RTL team (includes `clock_power_budget` table)
```

---

## 5. Stage Agent Interface

```
INPUT:  { state_object, stage_name, skill_content }
OUTPUT: {
  "stage": "arch_exploration",
  "status": "PASS" | "FAIL" | "WARN",
  "output": { ... structured results ... },
  "issues": [ { "severity": "ERROR|WARN", "description": "...", "fix": "..." } ],
  "suggested_next_step": "proceed | loop_back_to:<stage> | retry_stage | escalate | abandon"
}
```

---

## 6. Orchestrator Specification

### System Prompt

The orchestrator's system prompt is its agent definition, [`architecture-orchestrator.md`](../plugins/architecture/agents/architecture-orchestrator.md): stage
sequence, loop-back rules, stage gating and escalation. This document does not
restate it.

---

## 7. Output: Microarchitecture Document Template

```markdown
# Microarchitecture Specification: [Design Name]
**Version**: 1.0 | **Status**: Approved for RTL

## 1. Design Overview
## 2. Block Diagram
## 3. Performance Summary (vs targets)
## 4. Power/Area Summary (vs budget)
## 5. Block Descriptions (per major block)
## 6. Clock Domain Architecture
## 7. Reset Architecture
## 8. Memory Map
## 9. Interface Specifications
## 10. DFT Strategy
## 11. Verification Strategy
## 12. Risk Register (summary)
## 13. Open Items
```
