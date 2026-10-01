# Physical Design Flow — Full Architecture Design
## Orchestrator + Stage Agents + Skills

> **Purpose**: This document defines the complete architecture for an AI-driven Physical Design (PD) flow. It is intended to be copied into a new session for implementation. It covers all skill file structures, stage agent designs, and the top-level orchestrator agent.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                   ORCHESTRATOR AGENT                        │
│  - Receives: Netlist, SDC, LEF/DEF, Technology files        │
│  - Manages: Stage sequencing, QoR state, loop-back logic    │
│  - Outputs: Final GDS, timing/power/area reports            │
└────────────────────┬────────────────────────────────────────┘
                     │ dispatches to
     ┌───────────────┼───────────────────────┐
     ▼               ▼                       ▼
┌─────────┐   ┌─────────────┐         ┌──────────────┐
│ Stage   │   │  Stage      │   ...   │  Stage       │
│ Agent 1 │   │  Agent 2    │         │  Agent N     │
│Floorplan│   │ Placement   │         │  Sign-off    │
└────┬────┘   └──────┬──────┘         └──────┬───────┘
     │               │                       │
     ▼               ▼                       ▼
┌─────────┐   ┌─────────────┐         ┌──────────────┐
│  SKILL  │   │   SKILL     │         │    SKILL     │
│floorplan│   │  placement  │         │   signoff    │
│.md      │   │  .md        │         │   .md        │
└─────────┘   └─────────────┘         └──────────────┘
```

### Core Principle
- **Skills** = domain knowledge per stage (rules, heuristics, SDC syntax, metrics)
- **Stage Agents** = execute one stage, evaluate QoR, return structured results
- **Orchestrator** = sequences stages, passes state, handles failures and loop-backs

---

## 2. Shared Data Contract (State Object)

All agents communicate through a single shared JSON state object. Every stage agent reads from and writes to this object.

```json
{
  "run_id": "pd_run_001",
  "technology": "tsmc7nm",
  "design_name": "my_chip",

  "inputs": {
    "netlist":    "path/to/netlist.v",
    "sdc":        "path/to/constraints.sdc",
    "lef":        ["tech.lef", "cells.lef"],
    "def":        "path/to/floorplan.def",
    "upf":        "path/to/power_intent.upf",
    "lib":        ["tt.lib", "ss.lib", "ff.lib"]
  },

  "stages": {
    "floorplan":          { "status": "pending", "qor": {}, "issues": [], "output": {} },
    "placement":          { "status": "pending", "qor": {}, "issues": [], "output": {} },
    "cts":                { "status": "pending", "qor": {}, "issues": [], "output": {} },
    "routing":            { "status": "pending", "qor": {}, "issues": [], "output": {} },
    "timing_optimization":{ "status": "pending", "qor": {}, "issues": [], "output": {} },
    "power_optimization": { "status": "pending", "qor": {}, "issues": [], "output": {} },
    "area_optimization":  { "status": "pending", "qor": {}, "issues": [], "output": {} },
    "signoff":            { "status": "pending", "qor": {}, "issues": [], "output": {} }
  },

  "global_qor": {
    "wns":          null,
    "tns":          null,
    "worst_slack":  null,
    "total_power":  null,
    "core_area_util": null,
    "drc_violations": null
  },

  "loop_count": {},
  "current_stage": null,
  "flow_status": "not_started"
}
```

---

## 3. Stage Sequence

```text
floorplan → placement → cts → routing → timing_optimization → power_optimization → area_optimization → signoff
```

Loop-back rules — the target stage, the iteration cap, and which failures escalate
instead of looping — are in `## Loop-Back Rules` of [`physical-design-orchestrator.md`](../plugins/pd/agents/physical-design-orchestrator.md). That file is
authoritative; this document does not restate them.

---

## 4. Skill File Specifications

Each skill file should be created at the path shown. Contents define what the stage agent loads before execution.

---

### 4.1 `sv-pd-floorplan/SKILL.md`

```markdown
# Skill: Physical Design — Floorplanning

## Purpose
Guide floorplan creation including die size, core area, IO placement,
macro placement, power grid planning, and blockage definition.

## Key Inputs
- Netlist (gate-level), SDC, LEF files, Technology node specs
- Area estimate from synthesis (from report_area)

## Domain Rules
1. Core utilization target: 70–80% (leave margin for routing)
2. Macros: place at edges or corners, with halos (typically 5–10μm)
3. IO pads: evenly distributed; match pin assignments from package
4. Power grid: VDD/VSS straps every N rows (technology-dependent)
5. Blockages: place hard blockages around analog/RF macros
6. Aspect ratio: keep close to 1:1 unless package constrains otherwise

## QoR Metrics to Evaluate
- Estimated congestion (H/V) — flag if > 80%
- Estimated WNS from floorplan-stage STA — flag if < -2ns
- IR drop estimate — flag if > 10% of VDD

## Common Issues & Fixes
- High congestion in center → spread macros outward
- Negative slack at floorplan → revisit macro placement or increase die size
- Power grid IR drop → add more straps or widen existing

## Output Required
- DEF file (floorplan.def)
- Power grid DEF or script
- Macro placement report
- Estimated congestion map
```

---

### 4.2 `sv-pd-placement/SKILL.md`

```markdown
# Skill: Physical Design — Placement

## Purpose
Guide standard cell placement including coarse placement, legalization,
and pre-CTS optimization.

## Key Inputs
- Floorplan DEF, synthesized netlist, SDC, timing libraries

## Domain Rules
1. Run global placement → legalization → detailed placement
2. Pre-CTS timing optimization should assume ideal clocks
3. Max utilization per partition: 80% (leave room for filler cells)
4. High-fanout nets: buffer before placement or use placement constraints
5. Timing-critical paths: use placement constraints (set_dont_touch, groups)
6. Scan chains: reorder after placement for minimum wirelength

## QoR Metrics to Evaluate
- Pre-CTS WNS: should be > -0.3ns (accounting for clock uncertainty)
- Pre-CTS TNS: review paths with slack < -0.1ns
- Cell density map: flag hotspots > 90% local density
- Estimated routing congestion: flag if overflow > 1%

## Common Issues & Fixes
- Congestion hotspot → add placement blockage, spread cells
- Timing violations on long paths → manually guide placement of critical cells
- High density near macros → adjust macro halos

## Output Required
- Placed DEF (placement.def)
- Pre-CTS timing report (setup and hold)
- Cell density / congestion report
```

---

### 4.3 `sv-pd-cts/SKILL.md`

```markdown
# Skill: Physical Design — Clock Tree Synthesis (CTS)

## Purpose
Build balanced clock trees that meet skew, insertion delay,
and transition time targets.

## Key Inputs
- Placed DEF, SDC (create_clock, clock constraints), CTS spec file

## Domain Rules
1. Target clock skew: < 100ps (or per SDC uncertainty spec)
2. Target insertion delay: minimize; match SDC set_clock_latency if specified
3. Max transition on clock nets: per technology DRC rule (typically 150–200ps)
4. Max fanout per buffer: set per library (typically 16–32)
5. Useful skew: apply only on timing-critical paths with explicit sign-off
6. Clock gating cells: integrate into CTS; ensure enable pin timing is met
7. Multi-clock designs: handle each domain independently; check CDC paths

## QoR Metrics to Evaluate
- Global skew per clock domain: flag if > 150ps
- Max insertion delay: flag if > 500ps (technology-dependent)
- Post-CTS WNS (setup): flag if < -0.2ns
- Post-CTS hold slack: must be > 0 before routing
- Clock tree power: flag if > 20% of dynamic power

## Common Issues & Fixes
- High skew → add balancing buffers, adjust CTS exclusion pins
- Hold violations → fix with delay cells before routing
- Clock transition violations → resize clock buffers

## Output Required
- Post-CTS DEF
- Clock tree report (skew, insertion delay per domain)
- Post-CTS timing report (setup and hold)
```

---

### 4.4 `sv-pd-routing/SKILL.md`

```markdown
# Skill: Physical Design — Routing

## Purpose
Complete signal routing from global routing through detailed routing
to produce a DRC-clean layout.

## Key Inputs
- Post-CTS DEF, LEF, technology routing rules

## Domain Rules
1. Sequence: global route → track assignment → detailed route → search & repair
2. DRC rules: follow technology DRC deck strictly (spacing, width, via rules)
3. Signal integrity: shield critical clock/analog nets; minimize coupling on high-speed signals
4. Layer assignment: prefer upper metals for power, lower metals for signals
5. Antenna rules: insert antenna diodes or use long wire prevention
6. Double patterning (7nm and below): ensure same-color violations are resolved

## QoR Metrics to Evaluate
- DRC violations: must be 0 at signoff
- LVS errors: must be 0 at signoff
- Post-route WNS: flag if < 0
- Post-route TNS: review all failing paths
- Routing congestion overflow: must be 0

## Common Issues & Fixes
- DRC shorts → reroute affected nets, adjust spacing rules
- Antenna violations → insert diodes or jump vias
- Post-route timing degradation → ECO: resize/reroute critical paths

## Output Required
- Routed DEF (routed.def)
- DRC report
- LVS report
- Post-route timing report (setup and hold)
```

---

### 4.5 `sv-pd-timing/SKILL.md`

```markdown
# Skill: Physical Design — Timing Optimization

## Purpose
Close timing on setup and hold paths after routing using ECO techniques,
buffer insertion, gate resizing, and Vt swapping.

## Key Inputs
- Routed DEF, SDF/SPEF, SDC, timing libraries (multi-corner)

## Domain Rules
1. Multi-corner analysis: run at SS (setup), FF (hold), and TT corners
2. Setup fixing: upsize drivers, insert repeaters, retime registers
3. Hold fixing: insert delay buffers (prefer HVT delay cells)
4. Vt swapping: SVT for speed-critical paths, HVT for power savings
5. ECO flow: formal ECO → place ECO cells in reserved sites → re-route ECO nets
6. Do not modify scan chain order during ECO
7. OCV/AOCV/POCV: apply per signoff agreement with foundry

## QoR Metrics to Evaluate
- WNS: must be ≥ 0 at all corners for signoff
- TNS: must be 0 for signoff
- Hold slack: must be ≥ 0 (post-hold-fixing)
- Timing ECO cell count: flag if > 2% of total cell count (indicates floorplan/placement issue)

## Common Issues & Fixes
- Persistent setup violations → check for missing multicycle paths or incorrect SDC
- Hold violations reappearing → check CTS skew; may need CTS re-run
- Large ECO count → escalate to orchestrator for upstream loop-back

## Output Required
- Timing closure report (all corners, all modes)
- ECO change list
- SPEF (post-route parasitics)
- Updated routed DEF (post-ECO)
```

---

### 4.6 `sv-pd-power/SKILL.md`

```markdown
# Skill: Physical Design — Power Optimization

## Purpose
Reduce dynamic and static power while meeting power budget and
not degrading timing beyond recovery.

## Key Inputs
- Post-timing DEF, UPF (power intent), activity files (.saif or .vcd), lib files

## Domain Rules
1. Dynamic power: optimize via clock gating, operand isolation, multi-Vt
2. Static power (leakage): swap non-critical cells to HVT; verify timing after swap
3. Power domains: validate UPF — isolation, level-shifters, retention registers
4. Voltage islands: verify power grid integrity per domain
5. Always-on logic: verify correct lib used for retention/isolation cells
6. Power gating: verify wakeup/shutdown sequences in simulation

## QoR Metrics to Evaluate
- Total power: must be within power budget (from spec)
- Dynamic power breakdown: clock, logic, memory
- Leakage power: flag if > 15% of total power at TT corner
- IR drop: must be < 5% VDD across all domains (static and dynamic)
- Post-power-opt timing: WNS must remain ≥ 0

## Common Issues & Fixes
- Power over budget after HVT swap → check which paths prevented full swap
- IR drop hotspot → add decap cells, widen power straps locally
- UPF violations → review isolation cell placement and enable logic

## Output Required
- Power analysis report (dynamic + static per domain)
- IR drop report (static + dynamic)
- Updated DEF (post-power-opt)
- UPF compliance report
```

---

### 4.7 `sv-pd-area/SKILL.md`

```markdown
# Skill: Physical Design — Area Optimization

## Purpose
Reduce die area through cell resizing, logic restructuring,
and layout compaction while maintaining timing and power closure.

## Key Inputs
- Post-power DEF, timing reports, synthesis netlist

## Domain Rules
1. Remove redundant buffers and inverter pairs (buffer removal ECO)
2. Downsize non-timing-critical cells to minimum drive strength
3. Merge equivalent logic cones (if supported by tool)
4. Reclaim unused standard cell sites (remove filler, resize, re-fill)
5. Do not reduce area at the cost of timing margin < 50ps WNS buffer
6. Re-run DRC after any area ECO

## QoR Metrics to Evaluate
- Core area utilization: target 70–80% (not exceeding 85%)
- Cell count delta: track reduction from area optimization
- WNS post-area-opt: must remain ≥ 0
- DRC: must remain clean after optimization

## Common Issues & Fixes
- Area still over target after optimization → escalate to orchestrator; may need RTL-level changes
- Timing degraded after downsizing → revert specific cell changes
- DRC violations after compaction → reroute affected areas

## Output Required
- Area utilization report (pre vs post)
- Updated DEF (post-area-opt)
- Cell count / type breakdown
```

---

### 4.8 `sv-pd-signoff/SKILL.md`

```markdown
# Skill: Physical Design — Sign-off

## Purpose
Perform final verification including STA sign-off, DRC, LVS, ERC,
and power sign-off to confirm the design is tape-out ready.

## Key Inputs
- Final routed DEF, GDSII, SPEF, SDC, UPF, DRC/LVS decks

## Domain Rules
1. STA sign-off: run at all required PVT corners with POCV/AOCV
2. DRC: run foundry-approved DRC deck; zero violations allowed
3. LVS: netlist vs layout; zero errors allowed
4. ERC: electromigration and IR drop sign-off
5. Antenna check: zero antenna violations
6. Density check: metal density within foundry window (usually 20–80%)
7. Final GDS: merge all layers, add seal ring, verify chip-level DRC

## QoR Metrics (All Must Pass)
- STA: WNS ≥ 0, TNS = 0, Hold ≥ 0 at all corners
- DRC violations: 0
- LVS errors: 0
- ERC: no EM violations, IR drop < 5% VDD
- Antenna violations: 0
- Density check: PASS

## On Failure
Where a sign-off failure goes is set by the orchestrator's `## Loop-Back Rules` in
[`physical-design-orchestrator.md`](../plugins/pd/agents/physical-design-orchestrator.md).

## Output Required
- Sign-off STA report (all corners)
- DRC clean report
- LVS clean report
- Final GDS II file
- Tape-out checklist (completed)
```

---

## 5. Stage Agent Specifications

Each stage agent follows this standard interface:

```
STAGE AGENT INTERFACE
─────────────────────
INPUT:  { state_object, stage_name, skill_content }
OUTPUT: { updated_state_object, stage_result }

INTERNAL STEPS:
  1. Load skill for this stage
  2. Extract relevant inputs from state_object
  3. Analyze / execute the stage task
  4. Evaluate QoR metrics per skill definition
  5. Classify result: PASS | FAIL | WARN
  6. Write results back to state_object.stages[stage_name]
  7. Return updated state to orchestrator
```

### Stage Agent Prompt Template

When implementing each stage agent, use this system prompt structure:

```
SYSTEM PROMPT FOR STAGE AGENT:
───────────────────────────────
You are a Physical Design Stage Agent responsible for: [STAGE NAME].

You have been provided with:
1. The current PD run state (JSON)
2. Your stage skill document (domain rules, QoR metrics, fixes)
3. Any relevant design files or reports

Your job:
- Analyze the inputs for this stage
- Apply domain rules from your skill document
- Evaluate QoR metrics
- Identify issues and recommend fixes
- Return a structured JSON result:

{
  "stage": "[stage_name]",
  "status": "PASS" | "FAIL" | "WARN",
  "qor": { ... metrics ... },
  "issues": [ { "severity": "ERROR|WARN", "description": "...", "fix": "..." } ],
  "suggested_next_step": "proceed | loop_back_to:<stage> | retry_stage | escalate | abandon",
  "output": { ... stage output files/data ... }
}

Do not proceed to the next stage. Return results only.
```

---

## 6. Orchestrator Agent — Full Specification

### 6.1 Orchestrator System Prompt

The orchestrator's system prompt is its agent definition, [`physical-design-orchestrator.md`](../plugins/pd/agents/physical-design-orchestrator.md): stage
sequence, loop-back rules, stage gating and escalation. This document does not
restate it.

### 6.2 Orchestrator Decision Logic (Pseudocode)

```python
def run_pd_flow(state):
    stage_sequence = [
        "floorplan", "placement", "cts", "routing",
        "timing_optimization", "power_optimization",
        "area_optimization", "signoff"
    ]

    current_index = 0

    while current_index < len(stage_sequence):
        stage = stage_sequence[current_index]
        state["current_stage"] = stage

        # Load skill for this stage
        skill = load_skill(f"sv-pd-{stage}/SKILL.md")

        # Dispatch to stage agent
        result = dispatch_stage_agent(stage, state, skill)

        # Write result into state
        state["stages"][stage] = result
        update_global_qor(state, result["qor"])

        if result["status"] == "PASS":
            current_index += 1  # proceed to next stage

        elif result["status"] == "FAIL":
            loop_target = resolve_loop_back(stage, result, state)

            if loop_target is None:
                # No loop-back possible — escalate
                escalate_to_user(state, result)
                return

            loop_key = f"{stage}_to_{loop_target}"
            state["loop_count"][loop_key] = state["loop_count"].get(loop_key, 0) + 1

            max_loops = get_max_loops(loop_key)
            if state["loop_count"][loop_key] > max_loops:
                escalate_to_user(state, result)
                return

            # Jump back
            current_index = stage_sequence.index(loop_target)

        elif result["status"] == "WARN":
            # Log warning, proceed
            log_warning(stage, result)
            current_index += 1

    # All stages passed
    state["flow_status"] = "COMPLETE"
    return generate_final_report(state)
```

### 6.3 Orchestrator Final Report Template

When the flow completes, the orchestrator generates a report in this format:

```markdown
# Physical Design Run Report
**Design**: [design_name]
**Technology**: [technology]
**Run ID**: [run_id]
**Status**: TAPE-OUT READY / FAILED

## QoR Summary
| Metric            | Value     | Target    | Status |
|-------------------|-----------|-----------|--------|
| WNS (setup)       | Xns       | ≥ 0       | PASS   |
| TNS               | 0ps       | 0         | PASS   |
| Hold Slack        | Xps       | ≥ 0       | PASS   |
| Total Power       | XmW       | < [budget]| PASS   |
| Core Utilization  | X%        | 70–80%    | PASS   |
| DRC Violations    | 0         | 0         | PASS   |
| LVS Errors        | 0         | 0         | PASS   |

## Stage Execution Log
| Stage               | Status | Iterations | Key Issues         |
|---------------------|--------|------------|--------------------|
| Floorplan           | PASS   | 1          | —                  |
| Placement           | PASS   | 1          | —                  |
| CTS                 | PASS   | 1          | —                  |
| Routing             | PASS   | 2          | DRC shorts (fixed) |
| Timing Optimization | PASS   | 1          | —                  |
| Power Optimization  | PASS   | 1          | —                  |
| Area Optimization   | WARN   | 1          | 82% util (within)  |
| Sign-off            | PASS   | 1          | —                  |

## Output Files
- Final GDS: [path]
- Sign-off STA report: [path]
- DRC clean report: [path]
- LVS clean report: [path]
- Power report: [path]
```

---

## 7. Implementation Guide for New Session

When starting a new session to implement this, follow these steps in order:

### Step 1 — Create Skill Files
Create each skill file at its specified path. Populate with the content defined in Section 4. These are read-only reference documents.

### Step 2 — Implement Stage Agents
For each of the 8 stages, create a stage agent using the interface defined in Section 5. Each agent:
- Accepts `(state_object, skill_content)` as input
- Returns a structured JSON result
- Uses the Claude API (`claude-sonnet-4-20250514`) for analysis
- Has the stage-specific system prompt injected at call time

### Step 3 — Implement the Orchestrator
Build the orchestrator from its agent definition, [`physical-design-orchestrator.md`](../plugins/pd/agents/physical-design-orchestrator.md) (Section 6.1), and the decision logic in Section 6.2. The orchestrator:
- Is the only agent the user interacts with directly
- Manages all state
- Dispatches to stage agents programmatically
- Handles all loop-back and escalation logic

### Step 4 — Wire Up the State Object
Initialize the state object (Section 2) from user inputs at the start of each run. Pass it through every agent call. Persist it between calls.

### Step 5 — Test with a Simple Design
Before running a full flow, test each stage agent independently with a known-good input to verify skill loading and QoR evaluation are working correctly.

---

## 8. Key Design Decisions Summary

| Decision | Choice | Rationale |
|---|---|---|
| Agent granularity | One agent per PD stage | Isolation of concerns; easier to debug and iterate per stage |
| State management | Single shared JSON object | All agents speak the same language; easy to inspect mid-flow |
| Loop-back enforcement | Orchestrator only | Stage agents don't make flow decisions; cleaner separation |
| Skill format | Markdown per stage | Human-readable; easy to update domain rules without code changes |
| Max loop limits | Hardcoded per transition | Prevents infinite loops; forces escalation with context |
| Model | claude-sonnet-4-20250514 | Balance of reasoning quality and speed for EDA analysis tasks |

---

*End of Architecture Document — Ready for Implementation*
