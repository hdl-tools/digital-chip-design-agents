# Static Timing Analysis (STA) Flow — Full Architecture Design
## Orchestrator + Stage Agents + Skills

> **Purpose**: AI-driven STA flow for multi-corner, multi-mode timing closure. Covers constraint validation, timing analysis, exception handling, and timing sign-off for both pre-silicon and ECO cycles.

---

## 1. Shared State Object

```json
{
  "run_id": "sta_001",
  "design_name": "my_chip",
  "inputs": {
    "netlist":     "routed.v",
    "spef":        ["rc_best.spef", "rc_worst.spef"],
    "sdc":         "constraints.sdc",
    "libs":        { "ss": "ss_lib.lib", "ff": "ff_lib.lib", "tt": "tt_lib.lib" },
    "corners": [
      { "name": "setup_worst", "lib": "ss", "spef": "rc_worst", "voltage": 0.9, "temp": 125 },
      { "name": "hold_best",   "lib": "ff", "spef": "rc_best",  "voltage": 1.1, "temp": -40 },
      { "name": "typical",     "lib": "tt", "spef": "rc_worst", "voltage": 1.0, "temp": 25  }
    ]
  },
  "stages": {
    "constraint_validation": { "status": "pending", "output": {} },
    "multi_corner_analysis": { "status": "pending", "output": {} },
    "path_analysis":         { "status": "pending", "output": {} },
    "exception_review":      { "status": "pending", "output": {} },
    "eco_guidance":          { "status": "pending", "output": {} },
    "sta_signoff":           { "status": "pending", "output": {} }
  },
  "timing": {
    "setup_wns": null, "setup_tns": null,
    "hold_wns":  null, "hold_tns":  null,
    "failing_paths": []
  },
  "flow_status": "not_started"
}
```

---

## 2. Stage Sequence

```text
constraint_validation → multi_corner_analysis → path_analysis → exception_review → eco_guidance → sta_signoff
```

Loop-back rules — the target stage, the iteration cap, and which failures escalate
instead of looping — are in `## Loop-Back Rules` of [`sta-orchestrator.md`](../plugins/sta/agents/sta-orchestrator.md). That file is
authoritative; this document does not restate them.

---

## 3. Skill File Specifications

### 3.1 `sv-sta-constraints/SKILL.md`

```markdown
# Skill: STA — Constraint Validation

## Purpose
Validate all SDC constraints are complete, consistent,
and correctly model the design intent before timing analysis.

## Validation Checks
1. All clocks defined with correct period and waveform
2. All generated clocks: correct source and division/multiplication
3. No unconstrained paths: verify with report_timing -unconstrained
4. Clock domain crossings: correct false_path or max_delay applied
5. Multicycle paths: both setup (-setup N) and hold (-hold 1) specified
6. Input/output delays: match system-level timing budget
7. Timing exceptions: not overly broad (masking real violations)
8. Operating conditions: consistent with corner being analyzed
9. Propagated vs ideal clocks: correct mode for pre-CTS vs post-CTS

## Common Constraint Errors
- Multicycle path without hold correction → hold violations
- False path too broad → masks real timing issue
- Generated clock missing → paths unconstrained
- Wrong clock period → over/under-constraining
- set_case_analysis for test mode missing → incorrect mode analysis

## QoR Metrics
- 0 unconstrained paths
- 0 clock definition errors
- All exceptions: reviewed and documented

## Output Required
- Constraint QA report
- Clock summary (all clocks, sources, periods)
- Exception list with justifications
```

---

### 3.2 `sv-sta-analysis/SKILL.md`

```markdown
# Skill: STA — Multi-Corner Timing Analysis

## Purpose
Run and interpret timing analysis at all required PVT corners
for setup and hold closure.

## Required Corner Matrix
| Mode/Corner    | Setup Corner      | Hold Corner       |
|----------------|-------------------|-------------------|
| Functional     | SS/0.9V/125°C     | FF/1.1V/-40°C     |
| Test (at-speed)| SS/0.9V/125°C     | FF/1.1V/25°C      |
| Low Power      | SS/0.9V/125°C     | FF/1.1V/25°C      |

## POCV/AOCV Application
1. AOCV: apply depth and location-based derating (pre-POCV designs)
2. POCV: apply parametric variation (sigma-based, tool-specific)
3. OCV guard-band: early design (flat derating), sign-off (POCV)
4. Clock uncertainty: pre-CTS (ideal) vs post-CTS (propagated)

## Path Analysis Priority
1. WNS path per corner (most critical single path)
2. TNS contribution (how many paths fail, by how much)
3. Clock domain crossings: CDC paths with max_delay
4. At-speed paths: launch/capture pair STA

## QoR Metrics — Sign-off Targets
| Metric    | Target           |
|-----------|------------------|
| Setup WNS | ≥ 0 all corners  |
| Setup TNS | = 0 all corners  |
| Hold WNS  | ≥ 0 all corners  |
| Hold TNS  | = 0 all corners  |

## Output Required
- Timing report per corner (setup and hold)
- WNS/TNS summary table (all corners)
- Top 100 violating paths (for ECO guidance)
```

---

### 3.3 `sv-sta-eco/SKILL.md`

```markdown
# Skill: STA — ECO Guidance

## Purpose
Analyze timing violations and recommend specific ECO actions
(resize, buffer, reroute, retime) to close timing.

## ECO Decision Tree
```
Setup violation on path:
  → Logic depth > target?     YES → Retime / pipeline stage
  → Long wire?                YES → Buffer / reroute
  → Weak driver?              YES → Upsize driver
  → High-Vt cell on crit path?YES → Swap to SVT/LVT
  → Reconvergent fanout?      YES → Clone cell / split net

Hold violation on path:
  → After CTS (skew-induced)? YES → Useful skew / delay buffer
  → Short path?               YES → Insert delay buffer (HVT preferred)
  → After ECO (new path)?     YES → Targeted hold buffer insertion
```

## ECO Rules
1. Minimum ECO footprint: change fewest cells to fix most violations
2. Prefer resizing over adding new cells (less routing impact)
3. ECO cells: place in pre-reserved ECO sites (spare cells or free sites)
4. Re-run STA after every ECO batch (don't accumulate blind)
5. LEC after every ECO: verify equivalence preserved
6. Don't introduce new hold violations while fixing setup (and vice versa)

## QoR Metrics
- ECO efficiency: violations fixed per ECO change
- ECO cell count: < 2% of total cells (flag if exceeded)
- Post-ECO LEC: EQUIVALENT

## Output Required
- ECO change list (cell, action, justification)
- Pre/post ECO timing comparison
- ECO LEC result
```

---

## 4. Orchestrator System Prompt

The orchestrator's system prompt is its agent definition, [`sta-orchestrator.md`](../plugins/sta/agents/sta-orchestrator.md): stage
sequence, loop-back rules, stage gating and escalation. This document does not
restate it.
