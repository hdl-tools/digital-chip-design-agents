---
name: architecture
description: >
  Microarchitecture exploration, PPA estimation, risk assessment, and architecture
  sign-off for digital chip design. Use when evaluating design candidates, estimating
  power/area/performance, assessing technical risk, or producing a microarchitecture
  document for handoff to RTL design.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: Architecture Evaluation

## Invocation

- **If invoked by a user** presenting a design task: immediately spawn the
  `digital-chip-design-agents:architecture-orchestrator` agent and pass the full
  user request and any available context. Do not execute stages directly.
- **If invoked by the `architecture-orchestrator` mid-flow**: do not spawn a new
  agent. Treat this file as read-only — return the requested stage rules,
  sign-off criteria, or loop-back guidance to the calling orchestrator.

Spawning the orchestrator from within an active orchestrator run causes recursive
delegation and must never happen.

## Pre-run Context

Before executing or advising on **any** stage, read the following files if they exist:

1. `memory/architecture/knowledge.md` — known failure patterns, successful tool flags, PDK/tool quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `memory/architecture/run_state.md` — current run identity (`run_id`, `design_name`, `tool`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Guide the full microarchitecture evaluation process from product specification
through to a signed-off microarchitecture document ready for RTL handoff. Covers
specification decomposition, candidate architecture exploration, performance and
PPA modelling, risk assessment, and sign-off.

---

## Supported EDA Tools

### Open-Source
- **gem5** (`gem5`) — full-system micro-architectural simulator for performance modelling
- **McPAT** (`mcpat`) — processor power, area, and timing estimator
- **CACTI** (`cacti`) — SRAM/cache power and area estimator
- **Python estimation scripts** (`python3 estimate.py`) — custom PPA models

### Proprietary
- **Synopsys Platform Architect** (dialect `synopsys`) — IP-level performance and power exploration
- **ARM Performance Models** (dialect `arm`) — cycle-accurate ARM subsystem models
- **Cadence Virtual System Platform (VSP)** (dialect `cadence`) — SoC-level virtual prototyping

---

## Stage: spec_analysis

### Domain Rules
1. Classify every requirement: functional, performance, power, area, interface, safety/security
2. Identify under-specified areas and flag as open questions for the product team
3. Map each use case to required hardware blocks (datapath, control, memory, IO)
4. Extract all interface requirements with protocols (AXI, PCIe, USB, Ethernet, etc.)
5. Identify safety/security requirements (ISO 26262, FIPS, CC) if applicable
6. Assign priority: Must-Have / Should-Have / Nice-to-Have
7. Produce a structured requirements document before any architecture work begins

### QoR Metrics to Evaluate
- Requirements coverage: 100% of spec sections mapped to at least one requirement
- Ambiguity count: all unresolved items captured in open questions list
- Interface completeness: all external interfaces named with protocol and bandwidth

### Common Issues & Fixes
| Issue | Fix |
|-------|-----|
| Spec section not mapped | Add to open questions; do not assume |
| Interface bandwidth unspecified | Request from product team before proceeding |
| Conflicting requirements | Flag as blocker; request resolution |

### Output Required
- Structured requirements document (JSON or Markdown)
- Interface list with protocols and bandwidths
- Open questions list

---

## Stage: arch_exploration

### Domain Rules
1. Generate minimum 3 candidate architectures: conservative, balanced, aggressive
2. Evaluate pipeline depth trade-offs (deeper = higher frequency, more area/power)
3. Evaluate parallelism: SIMD, superscalar, spatial unrolling — with area/power cost
4. Cache/memory hierarchy: size, associativity, latency vs area trade-off per use case
5. Interconnect topology: bus, crossbar, NoC — evaluate bandwidth vs complexity
6. Consider IP reuse: identify hard macros or licensed IPs before designing custom
7. Document all assumptions for each candidate explicitly
8. Produce a trade-off matrix comparing all candidates

### Trade-off Matrix Template
| Candidate | Freq Target | Area Est. | Power Est. | Risk  | Notes |
|-----------|-------------|-----------|------------|-------|-------|
| Option A  | 1GHz        | 3mm²      | 300mW      | Low   | ...   |
| Option B  | 2GHz        | 6mm²      | 700mW      | High  | ...   |

### QoR Metrics to Evaluate
- Minimum 3 candidates explored with distinct trade-off profiles
- Each candidate: performance estimate within 20% of target
- Single recommended candidate with clear quantitative justification

### Output Required
- Trade-off matrix with all candidates
- Recommended candidate with quantitative justification
- Assumptions and risk summary per candidate
- The same matrix persisted to `design_state.architecture.candidates[]`, one entry per
  candidate — rejected ones included, each with a `rejection_reason` — so a downstream
  refinement can resume from it (architecture-orchestrator Behaviour Rule 10)

---

## Stage: perf_modelling

### Domain Rules
1. Use analytical models (Amdahl, Roofline) for initial estimates
2. Build TLM/SystemC or Python models for complex pipelines
3. Model all bottlenecks: compute, memory bandwidth, IO throughput
4. Sweep key parameters: clock frequency, parallelism, cache size
5. Validate with representative workloads from the use-case list
6. Include best/typical/worst-case scenarios
7. Flag any model assumption that has not been validated
8. Refinement mode (entered here when `architecture.refinement_needed` is set): the
   downstream measurement in `refinement_request.measured` replaces the model estimate for
   the selected candidate. Recalibrate the model so it reproduces that measurement, then
   re-score every persisted candidate with the recalibrated model before choosing one. A
   model that still predicts the old estimate is uncalibrated, and its scores are not evidence.

### QoR Metrics to Evaluate
- Throughput: meets or exceeds target by ≥ 10% margin
- Latency: meets target at worst-case workload
- Memory bandwidth: does not exceed DRAM/SRAM ceiling
- Model confidence: HIGH / MEDIUM / LOW

### Output Required
- Performance model (script or spreadsheet)
- Throughput/latency results per use case
- Sensitivity analysis
- Comparison table: modelled vs target

---

## Stage: power_area_estimation

### Domain Rules
1. Area: use technology library scaling data (gates/mm² at target node)
2. Dynamic power: P = α × C × V² × f (get activity factor from use cases)
3. Leakage: estimate from library characterisation at target Vt mix
4. Memory area: use SRAM compiler estimates for given depth × width
5. IO pad area: per pad ring design rules
6. Apply 15–20% margin — RTL is never minimal
7. Flag immediately if any estimate exceeds 80% of budget

### Clock Gating Opportunity Analysis
Perform this analysis using the activity factors already collected for dynamic power:

1. For each identified clock domain, record its activity factor α derived from the
   use-case workload sweep (gem5 simulation or analytical model).
2. Classify each domain using thresholds from `design_state.constraints.power.activity_factors` (defaults: `{"default": 0.15, "high": 0.40}`):
   - α < `activity_factors.default` (default: 0.15) — **high gating opportunity**: clock gating will save > 30% dynamic power
     for that domain; flag as a must-have RTL requirement.
   - `activity_factors.default` ≤ α < `activity_factors.high` (defaults: 0.15–0.40) — **moderate gating opportunity**: clock gating recommended;
     flag as should-have RTL requirement.
   - α ≥ `activity_factors.high` (default: 0.40) — **always-active**: no gating benefit; document as always-on.
3. Produce a `clock_power_budget` table (one row per domain):

   | Domain | Frequency | α (activity) | Est. Clock Power (mW) | Gating Class |
   |--------|-----------|-------------|----------------------|--------------|
   | core   | 1 GHz     | 0.08        | 45                   | high         |
   | dsp    | 500 MHz   | 0.55        | 30                   | always-on    |

4. McPAT `clocking` component already models clock network power — ensure the
   frequency-sweep input reflects per-domain frequencies, not a single global clock.
5. Include the `clock_power_budget` table in the hand-off package to RTL design.
   The RTL agent will use it to target ICG (Integrated Clock Gate) insertion.

### Supported Tools for Clock/Power Analysis
| Tool | Type | Use |
|------|------|-----|
| McPAT | Open-source | Clock network + dynamic/leakage power (already in flow) |
| gem5 | Open-source | Workload activity factor extraction (already in flow) |
| CACTI | Open-source | Memory clock power estimate (already in flow) |
| Yosys + ABC | Open-source | Post-synth switching activity cross-check (optional) |
| Synopsys PrimePower | Proprietary, dialect `synopsys` | RTL-level power sign-off (optional) |
| Cadence Joules RTL | Proprietary, dialect `cadence` | RTL power analysis (optional) |

### QoR Metrics to Evaluate
- Area estimate: < 80% of `design_state.constraints.area.area_um2` budget (required constraint — see architecture-orchestrator Behaviour Rule 9)
- Dynamic power: < 80% of `design_state.constraints.power.power_mw` budget (required constraint)
- Leakage: < `design_state.constraints.power.leakage_pct_max`% of total estimated power (default: 15%)
- Clock-gating coverage: ≥ `design_state.constraints.power.gating_coverage_pct_min`% of register-bank bits in high-opportunity domains (default: 60%)
  (measured using planned register-map estimates from the microarchitecture specification;
  mark estimate confidence as HIGH if register counts are frozen, MEDIUM if approximate,
  LOW if based on scaling from similar designs)
- Confidence: HIGH / MEDIUM / LOW

### Output Required
- Area breakdown by block
- Power breakdown: dynamic, leakage, per domain
- Margin analysis vs targets
- `clock_power_budget` table (domain → frequency, activity factor, estimated clock power mW, gating class)

---

## Stage: risk_assessment

### Domain Rules
1. Risk categories: schedule, technical feasibility, IP availability, tool support,
   verification complexity, power closure, manufacturing yield
2. Score every risk: Probability (1–5) × Impact (1–5) = Risk Score
3. Risk score ≥ 15: classified HIGH — must have mitigation plan before sign-off
4. IP risks: verify availability, licensing timeline, silicon-proven status
5. Tool risks: verify EDA tool certification for chosen technology node
6. Verification risks: flag if testbench complexity > 6 months estimated effort
7. Every risk must have an assigned owner

### QoR Metrics to Evaluate
- No unmitigated HIGH risks at sign-off
- All risks: assigned owner and mitigation plan
- Schedule risk assessed vs team capacity

### Output Required
- Risk register (ID, description, score, mitigation, owner)
- Top 5 risks for management review

---

## Stage: arch_signoff

### Sign-off Checklist
- [ ] All Must-Have requirements addressed
- [ ] Performance targets met in model (≥ 10% margin)
- [ ] Power and area within budget (< 80% of `design_state.constraints.area.area_um2` / `power.power_mw`)
- [ ] All HIGH risks have mitigation plans and owners
- [ ] Interface specifications complete and agreed
- [ ] Memory map defined
- [ ] Clock domains identified; CDC strategy agreed
- [ ] Reset strategy defined
- [ ] DFT strategy agreed
- [ ] Verification strategy agreed
- [ ] RTL coding guidelines documented
- [ ] `clock_power_budget` table produced; gating class assigned per domain
- [ ] Clock-gating coverage ≥ `design_state.constraints.power.gating_coverage_pct_min`% of register bits in high-opportunity domains (default: 60%)
- [ ] Hand-off package complete for RTL team (includes `clock_power_budget` table)

### Output Required
- Signed-off microarchitecture document
- Final trade-off decision record
- RTL design guidelines
- Hand-off package

---

## Constraint Validation

See `plugins/meta/skills/pipeline-orchestration/SKILL.md` §Constraints Schema for the authoritative schema and stage-entry validation rule.

**Required at entry (`spec_analysis`) — hard-fail if missing:**
- `constraints.clock.clk_mhz` — target frequency
- `constraints.area.area_um2` — area budget
- `constraints.power.power_mw` — power budget

**Optional (schema defaults apply when absent):**
- `constraints.power.leakage_pct_max` (default: 15%) — leakage threshold
- `constraints.power.gating_coverage_pct_min` (default: 60%) — ICG coverage target
- `constraints.power.activity_factors` (defaults: `{default: 0.15, high: 0.40}`) — domain classification thresholds

---

## Memory

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
write or overwrite one JSON record in `memory/architecture/experiences.jsonl` keyed by
`run_id`. This ensures data is persisted even if the flow is interrupted or called
without full orchestrator context.

Use `run_id` = `architecture_<YYYYMMDD>_<HHMMSS>` (set once at flow start; reuse on each
stage update). Set `signoff_achieved: false` until the final sign-off stage completes.
### Run state (write before first stage, update after each stage)
Write `memory/architecture/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:      architecture_<YYYYMMDD>_<HHMMSS>
design_name: <design>
tool:        <primary tool>
start_time:  <ISO-8601>
last_stage:  null
```
Update `last_stage` to the completed stage name only after each stage finishes successfully. This file lets wakeup-loop prompts
and resumed sessions identify the correct run without relying on in-memory state.
Create the file and parent directories if they do not exist.

### Optional: claude-mem index
If `mcp__plugin_ecc_memory__add_observations` is available in this session, emit each
applied fix as an observation to entity `chip-design-architecture-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.
