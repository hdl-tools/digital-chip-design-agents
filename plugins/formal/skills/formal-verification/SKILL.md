---
name: formal-verification
description: >
  Formal property verification (FPV) and logical equivalence checking (LEC).
  Use when proving design properties exhaustively, checking RTL vs gate-level
  netlist equivalence, verifying CDC crossings formally, or closing verification
  coverage gaps that simulation cannot efficiently reach.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: Formal Verification (FPV + LEC)

## Invocation

When this skill is loaded and a user presents a formal verification task, **do not
execute stages directly**. Immediately spawn the
`digital-chip-design-agents:formal-orchestrator` agent and pass the full user
request and any available context to it. The orchestrator enforces the stage
sequence, loop-back rules, and sign-off criteria defined below.

Use the domain rules in this file only when the orchestrator reads this skill
mid-flow for stage-specific guidance, or when the user asks a targeted reference
question rather than requesting a full flow execution.

## Pre-run Context

Before executing or advising on **any** stage, read the following files if they exist:

1. `memory/formal/knowledge.md` — known failure patterns, successful tool flags, PDK/tool quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `memory/formal/run_state.md` — current run identity (`run_id`, `design_name`, `tool`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Exhaustively prove design properties and equivalence using formal methods.
Complements simulation-based verification for correctness proofs, protocol
compliance, and equivalence checking between RTL and gate-level netlists.

---

## Supported EDA Tools

### Open-Source
- **SymbiYosys** (`sby`) — formal property verification front-end for open-source solvers
- **Yosys** (`yosys`) — synthesis and equivalence checking back-end
- **Boolector** — SMT solver for bit-vector arithmetic
- **Z3** — general-purpose SMT solver from Microsoft Research
- **ABC** — logic synthesis and verification framework (sequential equivalence)
- **Tabby CAD Suite** — commercial bundle of sby + solvers (from YosysHQ)

### Proprietary
- **Cadence JasperGold** (`jg`, dialect `cadence`) — industry-standard FPV, CDC, DFT formal
- **Synopsys VC Formal** (`vcf`, dialect `synopsys`) — property checking and equivalence verification
- **Siemens Questa Formal** (`qformal`, dialect `siemens`) — FPV and coverage closure

---

## Stage: property_planning

### Property Categories
1. **Safety**: "something bad never happens"
   `assert property (@(posedge clk) !(error && valid));`
2. **Liveness**: "something good eventually happens" (always bound the interval)
   `assert property (@(posedge clk) req |-> ##[1:MAX] ack);`
3. **Stability**: "output is stable while condition holds"
   `assert property (@(posedge clk) valid |-> $stable(data));`
4. **Reachability**: "a state is reachable" (use cover, not assert)
   `cover property (@(posedge clk) state == DONE);`

### Domain Rules
1. Every spec feature: at least one property or cover point
2. All properties: include descriptive name and failure message
3. Liveness properties: always bound with ##[1:BOUND]
4. Use `$past()`, `$rose()`, `$fell()` over manual delay logic
5. `disable iff`: use for reset gating
6. Take the RTL hand-off as an input: every entry in `design_state.rtl.unverified[]` (claims
   the RTL flow concluded without a tool run) gets a property, a cover, or a written reason it
   is not formally tractable and who checks it instead. If `rtl.unverified` is absent the RTL
   flow did not report — say so in the property plan and derive the targets below from the RTL
   yourself; do not read "absent" as "nothing to prove"
7. Prove at boundary parameter values, not only the default: a proof holds for one
   parameterisation. Re-run at `WIDTH=1`, `DEPTH=1` and `2`, `N=1`, and any non-power-of-two
   value the module accepts. A guarded `initial`/`$fatal` parameter assertion in the RTL sits
   inside `synthesis translate_off` and may be invisible to the formal front-end, so restate
   the legal parameter range in the environment

### Property Targets Lint Cannot Prove
A clean lint run says nothing about these. Each applies wherever the structure exists:

| Structure | Properties |
|-----------|-----------|
| Ready/valid interface | Transfer only on `valid && ready`; `valid` not retracted before acceptance; payload stable while `valid && !ready`; `valid` and `ready` low in reset |
| FSM | Every state reachable (cover); every state has an exit (bounded liveness); from any illegal encoding the machine reaches a legal state — mandatory for an FSM using `unique case` without `default`, where this assertion is the only recovery check |
| Arbiter | Grant is one-hot or zero; a continuously asserting requester is granted within N grants; rotation advances only on a consumed grant |
| FIFO | No write when full, no read when empty; `empty` is 1 and `full` is 0 out of reset; occupancy never exceeds depth |
| Arithmetic | Every `+`, `-`, `*` and accumulator stays within its result width, or wraps only where the spec says so |
| Reset | Every control flop has its specified value in the first cycle out of reset |
| Deadlock | No wait-for cycle: bounded liveness on every request/acknowledge and every credit return |

### QoR Metrics to Evaluate
- All spec features mapped to property or cover
- Every `rtl.unverified[]` entry mapped to a property, a cover, or a stated reason
- Cover points: key states are reachable

### Output Required
- Property plan (feature → property mapping)
- SVA property file (.sva)
- SVA assumption file

---

## Stage: environment_setup

### Domain Rules
1. Constrain all primary inputs to legal values only
2. Protocol assumptions: model upstream block behaviour
3. Reset assumption: force correct reset sequence at time 0
4. **Over-constraining → vacuous proof** (nothing can be proven wrong) — always run vacuity check
5. **Under-constraining → false CEX** (environment bug, not DUT) — check all CEX carefully
6. Vacuity check: disable each assume — property should NOT hold without it
7. Document every assumption with justification

### Common Assumption Templates
```systemverilog
// Reset sequence
assume property (@(posedge clk) $rose(rst_n) |-> ##[1:5] rst_n);

// AXI valid stability
assume property (@(posedge clk)
  (s_axi_awvalid && !s_axi_awready) |=> $stable(s_axi_awaddr));
```

### QoR Metrics to Evaluate
- Vacuity check: PASS for all properties
- No over-constraining: formal tool reports reasonable state space
- Environment signed off by verification lead

### Output Required
- Formal environment file (constraints/assumptions)
- Vacuity check report
- Environment review record

---

## Stage: fpv_run

### Result Classifications
| Result | Meaning | Action |
|--------|---------|--------|
| PROVEN | Holds for all reachable states | Log and continue |
| CEX | Counterexample found | Analyse in `cex_analysis`; hand an RTL bug to the RTL flow, or fix the assumption |
| VACUOUS | Antecedent never fires | Fix assumption or property |
| INCONCLUSIVE | Bound too small or state space too large | Increase bound / abstract |
| UNREACHABLE | Cover never reachable | Verify or waive |

### Strategies for Inconclusive
1. Increase BMC bound (k-induction)
2. Apply abstractions (data abstraction, counter abstraction)
3. Decompose: prove sub-properties; compose to main property
4. If intractable, record the property as `UNVERIFIED` with the bound reached and the
   justification. A bounded proof is not PROVEN and an assumed-correct property is not a
   result — neither counts toward the PROVEN total, and a P0 property left `UNVERIFIED`
   blocks sign-off

### QoR Metrics to Evaluate
- Target: 100% PROVEN or UNREACHABLE (no unanalysed CEX)
- All INCONCLUSIVE: documented with justification and bound used

### Output Required
- FPV run report (per property: result, CEX trace if applicable)
- CEX waveform descriptions for failures

---

## Stage: cex_analysis

### Domain Rules
1. Every CEX: determine if it is a real DUT bug or an assumption/environment bug
2. Real DUT bug: do not edit the RTL from this flow. Write a `fix_request` entry to
   `design_state.fix_requests[]` (`failure_class=formal_cex`, CEX trace path, the property that
   failed) and stop; the RTL flow applies the fix under its own lint rules and FPV is re-run on
   the result. Counts as an RTL bug, not a formal bug
3. Assumption bug: tighten assumption → re-run vacuity check
4. False CEX from under-constraining: document clearly before adding assumption
5. Never waive a CEX without root cause
6. A CEX must not be cleared by narrowing the environment. Before adding or tightening an
   assumption, confirm the excluded behaviour is illegal per the spec or the upstream block's
   contract; an assumption that removes legal stimulus hides the bug instead of fixing it.
   Likewise never weaken or delete the failing property to get a pass
7. State what located the bug: set `suspected_rtl.basis` to `traced` when the CEX trace shows
   the faulty signal and cycle, `hypothesis` when the location is inferred

### Output Required
- CEX analysis report (bug or false alarm, root cause, fix applied)

---

## Stage: lec_run

### LEC Flow
1. Read golden: RTL or pre-ECO netlist
2. Read revised: post-synthesis netlist or post-ECO netlist
3. Map points: match sequential/combinational key points
4. Verify all points: compare cone-of-influence
5. Report: EQUIVALENT / UNMATCHED / ABORTED

### Domain Rules
1. Use same SDC for both golden and revised
2. Scan mode: flatten scan chains or use scan-unaware mode
3. Black boxes: handle consistently in both netlists
4. Unmatched points: must be root-caused — not waived without RTL team approval
5. Post-ECO: run LEC after every ECO, not just at sign-off

### Common LEC Failures
| Failure | Fix |
|---------|-----|
| Optimizer removed logic | Verify with report_removal; add set_dont_touch if needed |
| SDC mismatch | Ensure same clock groupings in both netlists |
| Scan chain reordering | Use scan-unaware LEC mode |
| Black box mismatch | Align black box list in both netlists |

### QoR Metrics to Evaluate
- All compare points: EQUIVALENT
- 0 UNMATCHED points
- 0 ABORTED points

### Output Required
- LEC run report
- Unmatched point analysis (if any)
- EQUIVALENT sign-off record

---

## Stage: formal_signoff

### Sign-off Checklist
- [ ] All P0 properties: PROVEN
- [ ] No unanalysed CEX
- [ ] No vacuous proofs
- [ ] LEC: 100% EQUIVALENT
- [ ] All INCONCLUSIVE: documented with justification and recorded as `UNVERIFIED`, not PROVEN
- [ ] Every `rtl.unverified[]` entry: proven, covered, or dispositioned with a reason
- [ ] Additional coverage closed vs simulation baseline

### Output Required
- Formal sign-off report
- Final property status table
- LEC clean record

---

## Constraint Validation

See `plugins/meta/skills/pipeline-orchestration/SKILL.md` §Constraints Schema for the authoritative schema and stage-entry validation rule.

**No required keys** for formal verification — all constraints in this domain are optional.

There are no numeric coverage thresholds unique to formal; this domain shares coverage targets
with the functional-verification domain (`coverage.*`) and timing targets with the STA domain
(`timing.wns_ns_target`). When evaluating LEC equivalence or FPV property results, tag
`constraint_ref` in history entries with the relevant dot-path key if a constraint value was
consulted (e.g. `"coverage.functional_pct"` when reporting coverage contribution).

---

## Memory

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
write or overwrite one JSON record in `memory/formal/experiences.jsonl` keyed by
`run_id`. This ensures data is persisted even if the flow is interrupted or called
without full orchestrator context.

Use `run_id` = `formal_<YYYYMMDD>_<HHMMSS>` (set once at flow start; reuse on each
stage update). Every JSON record written must include a top-level `"run_id"` field
whose value matches this key — stage writes must upsert/overwrite by matching this
persisted `run_id`. Set `signoff_achieved: false` until the final sign-off stage
completes.
### Run state (write before first stage, update after each stage)
Write `memory/formal/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:       formal_<YYYYMMDD>_<HHMMSS>
design_name:  <design>
tool:         <primary tool>
start_time:   <ISO-8601>
last_stage:   null
current_stage: <first stage name>
```
Update `current_stage` when a stage starts, and set `last_stage` to the completed stage
name only after successful completion (then clear `current_stage`). This file lets
wakeup-loop prompts and resumed sessions identify the correct run and distinguish
completed vs in-flight work. Create the file and parent directories if they do not exist.

### Optional: claude-mem index
If `mcp__plugin_ecc_memory__add_observations` is available in this session, emit each
applied fix as an observation to entity `chip-design-formal-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.
