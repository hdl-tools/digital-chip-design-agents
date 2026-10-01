# Formal Verification Flow — Full Architecture Design
## Orchestrator + Stage Agents + Skills

> **Purpose**: AI-driven formal verification flow covering formal property verification (FPV), logical equivalence checking (LEC), and CDC/RDC formal analysis. Complements simulation-based verification for exhaustive proof of correctness.

---

## 1. Shared State Object

```json
{
  "run_id": "formal_001",
  "design_name": "my_block",
  "inputs": {
    "rtl_filelist":  "filelist.f",
    "properties":    "properties.sva",
    "assumptions":   "assumptions.sva",
    "golden_netlist": "rtl.v",
    "revised_netlist": "netlist.v"
  },
  "stages": {
    "property_planning":   { "status": "pending", "output": {} },
    "environment_setup":   { "status": "pending", "output": {} },
    "fpv_run":             { "status": "pending", "output": {} },
    "cex_analysis":        { "status": "pending", "output": {} },
    "lec_run":             { "status": "pending", "output": {} },
    "formal_signoff":      { "status": "pending", "output": {} }
  },
  "properties": {
    "proven": [], "failed": [], "vacuous": [], "inconclusive": []
  },
  "lec_result": null,
  "flow_status": "not_started"
}
```

---

## 2. Stage Sequence

```text
property_planning → environment_setup → fpv_run → cex_analysis → lec_run → formal_signoff
```

Loop-back rules — the target stage, the iteration cap, and which failures escalate
instead of looping — are in `## Loop-Back Rules` of [`formal-orchestrator.md`](../plugins/formal/agents/formal-orchestrator.md). That file is
authoritative; this document does not restate them.

---

## 3. Skill File Specifications

### 3.1 `sv-formal-property/SKILL.md`

```markdown
# Skill: Formal — Property Planning

## Purpose
Define the complete set of properties to be proven formally.

## Property Categories
1. Safety: "something bad never happens"
   → assert property (@(posedge clk) !(error && valid));
2. Liveness: "something good eventually happens"
   → assert property (@(posedge clk) req |-> ##[1:MAX] ack);
3. Stability: "output is stable while condition holds"
   → assert property (@(posedge clk) valid |-> $stable(data));
4. Reachability: "a state is reachable" (use cover)
   → cover property (@(posedge clk) state == DONE);
5. Equivalence: "two implementations are equal"
   → used in LEC flow

## Property Writing Rules
1. All properties: include descriptive name and failure message
2. Liveness properties: always bound the "eventually" (##[1:BOUND])
3. Assumptions (restrict_): must be validated for vacuity
4. Use $past(), $rose(), $fell() over manual delay modeling
5. Disable iff: use for reset conditions

## QoR Metrics
- All spec features mapped to at least one property or cover point
- Cover points: verifiable reachability for key states

## Output Required
- Property plan document (feature → property mapping)
- SVA property file (.sva)
- SVA assumption file
```

---

### 3.2 `sv-formal-environment/SKILL.md`

```markdown
# Skill: Formal — Environment Setup

## Purpose
Build a correct and complete formal verification environment
(constraints/assumptions) that accurately models the DUT's context.

## Domain Rules
1. Constrain all primary inputs to legal values only
2. Protocol assumptions: model upstream block behavior
3. Reset assumption: force correct reset sequence at time 0
4. Over-constraining → vacuous proof (nothing can be proven wrong)
5. Under-constraining → false CEX (bug in environment, not DUT)
6. Vacuity check: run with assume disabled — property should NOT hold
7. Use helper assumptions sparingly and document each one

## Common Assumptions Template
```
// Reset behavior
assume property (@(posedge clk) $rose(rst_n) |-> ##1 !rst_n throughout ##[0:5] rst_n);

// AXI valid stability
assume property (@(posedge clk) (s_axi_awvalid && !s_axi_awready) |=>
                                 $stable(s_axi_awaddr));
```

## QoR Metrics
- Vacuity check: PASS for all properties
- No over-constraining: formal tool reports reasonable state space
- Environment review: signed off by verification lead

## Output Required
- Formal environment file (constraints)
- Vacuity check report
- Environment review record
```

---

### 3.3 `sv-formal-fpv/SKILL.md`

```markdown
# Skill: Formal — Property Verification (FPV) Execution

## Purpose
Run formal property verification and classify all property results.

## Result Classifications
| Result        | Meaning                                    | Action              |
|---------------|--------------------------------------------|---------------------|
| PROVEN        | Property holds for all reachable states    | Log and continue    |
| CEX           | Counterexample found — property violated   | Analyze, fix        |
| VACUOUS       | Holds because antecedent never fires       | Fix assumption/prop |
| INCONCLUSIVE  | Bound too small or state space too large   | Increase bound / abstract |
| UNREACHABLE   | Cover point never reachable                | Verify or waive     |

## Strategies for Inconclusive Results
1. Increase BMC bound (k-induction)
2. Apply abstractions (data abstraction, counter abstraction)
3. Decompose: prove sub-properties, compose to main property
4. Hybrid: use formal to close, simulation to reach deep states
5. Document as "assumed correct" with justification if intractable

## QoR Metrics
- Target: 100% PROVEN or VACUOUS-FREE
- No unanalyzed CEX
- All INCONCLUSIVE: documented with justification

## Output Required
- FPV run report (per property: result, CEX trace if applicable)
- CEX waveform descriptions for any failures
```

---

### 3.4 `sv-formal-lec/SKILL.md`

```markdown
# Skill: Formal — Logical Equivalence Checking (LEC)

## Purpose
Prove that two representations of the same design (RTL vs netlist,
pre-ECO vs post-ECO, etc.) are logically equivalent.

## LEC Flow
1. Read golden (reference): RTL or pre-ECO netlist
2. Read revised: post-synthesis netlist or post-ECO netlist
3. Map points: match sequential/combinational key points
4. Verify all points: compare cone-of-influence
5. Report: EQUIVALENT / UNMATCHED / ABORTED

## Domain Rules
1. Always use same SDC for both golden and revised
2. Scan mode: flatten scan chains for LEC or use scan-unaware mode
3. Black boxes: handle consistently in both netlists
4. Clock gating: verify gating logic is preserved
5. Unmatched points: must be analyzed — not waived without root cause
6. Post-ECO: run LEC after every ECO, not just at sign-off

## Common LEC Failures
- Optimizer removed logic (verify with tool report)
- SDC mismatch between RTL and netlist
- Scan chain reordering introduced difference
- Black box in one but not other

## QoR Metrics
- All compare points: EQUIVALENT
- 0 UNMATCHED points (no waivers without RTL team approval)
- 0 ABORTED points

## Output Required
- LEC run report
- Unmatched point analysis (if any)
- EQUIVALENT sign-off record
```

---

## 4. Orchestrator System Prompt

The orchestrator's system prompt is its agent definition, [`formal-orchestrator.md`](../plugins/formal/agents/formal-orchestrator.md): stage
sequence, loop-back rules, stage gating and escalation. This document does not
restate it.
