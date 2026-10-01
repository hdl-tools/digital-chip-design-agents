# Logic Synthesis Flow — Full Architecture Design
## Orchestrator + Stage Agents + Skills

> **Purpose**: AI-driven logic synthesis flow from RTL to gate-level netlist. Covers constraint setup, synthesis optimization (speed/area/power), netlist quality check, and handoff to physical design.

---

## 1. Shared State Object

```json
{
  "run_id": "synth_001",
  "design_name": "my_block",
  "inputs": {
    "rtl_filelist":   "filelist.f",
    "sdc":            "constraints.sdc",
    "liberty_files":  ["tt.lib", "ss.lib", "ff.lib"],
    "target_freq":    "1GHz",
    "target_corner":  "ss_0p9v_125c",
    "effort":         "high"
  },
  "stages": {
    "constraint_setup":   { "status": "pending", "output": {} },
    "compile_explore":    { "status": "pending", "output": {} },
    "compile_final":      { "status": "pending", "output": {} },
    "netlist_qc":         { "status": "pending", "output": {} },
    "synthesis_signoff":  { "status": "pending", "output": {} }
  },
  "qor": {
    "wns": null, "tns": null,
    "area_um2": null, "cell_count": null,
    "power_mw": null
  },
  "flow_status": "not_started"
}
```

---

## 2. Stage Sequence

```text
constraint_setup → compile_explore → compile_final → netlist_qc → synthesis_signoff
```

Loop-back rules — the target stage, the iteration cap, and which failures escalate
instead of looping — are in `## Loop-Back Rules` of [`synthesis-orchestrator.md`](../plugins/synthesis/agents/synthesis-orchestrator.md). That file is
authoritative; this document does not restate them.

---

## 3. Skill File Specifications

### 3.1 `sv-synth-constraints/SKILL.md`

```markdown
# Skill: Synthesis — Constraint Setup (SDC)

## Purpose
Create and validate all SDC constraints before synthesis.

## Domain Rules
1. create_clock: all primary clocks with period, waveform, name
2. create_generated_clock: all derived/divided clocks
3. set_clock_uncertainty: setup (pre-CTS) = skew + jitter (typ. 200–500ps)
4. set_clock_latency: set if known from CTS estimates
5. set_input_delay / set_output_delay: all primary IOs constrained
6. set_false_path: multi-cycle paths, test modes, async resets
7. set_multicycle_path: correctly constrained (both setup and hold)
8. set_dont_touch: IPs, memory macros, hand-crafted cells
9. set_max_fanout: per library recommendation (typ. 32)
10. set_max_transition: per technology rule
11. Operating conditions: explicitly set (not relying on defaults)

## Common SDC Mistakes to Check
- Missing generated clocks on clock dividers
- set_multicycle_path without corresponding hold adjustment
- Over-constraining IOs (tighter than needed wastes area)
- Under-constraining IOs (may hide real timing issues)

## QoR Metrics
- All clocks defined (check with report_clocks)
- All IOs constrained (check with report_port -verbose)
- No unconstrained paths in report_timing

## Output Required
- Validated SDC file
- Clock tree summary
- Constraint QA report
```

---

### 3.2 `sv-synth-compile/SKILL.md`

```markdown
# Skill: Synthesis — Compile and Optimization

## Purpose
Run logic synthesis with the appropriate effort and optimization
strategy to meet timing, area, and power targets.

## Recommended Flow (Synopsys DC / Genus)
1. read_hdl / analyze+elaborate
2. Check design (report_lint, check_design)
3. Compile explore (faster, finds architecture)
4. Incremental compile (targeted path optimization)
5. Final compile (high effort, all paths)
6. report_timing, report_area, report_power

## Optimization Strategies
| Priority  | Strategy                                          |
|-----------|---------------------------------------------------|
| Timing    | compile_ultra, path_group weighting, retiming     |
| Area      | compile -area_effort high, resource sharing       |
| Power     | compile -power, clock gating insertion            |
| Balanced  | compile_ultra -no_autoungroup + incremental       |

## Domain Rules
1. Always compile at worst-case timing corner (SS, low voltage, high temp)
2. Use multi-scenario compilation if available (setup + hold simultaneously)
3. Enable clock gating synthesis for sequential power reduction
4. Preserve hierarchy for blocks with existing placement intent
5. Ungroup small modules for better optimization across boundaries
6. Review critical paths manually for RTL restructuring opportunities

## QoR Metrics
- WNS: ≥ 0 at signoff corner (or per agreed target)
- TNS: = 0 for clean sign-off
- Area: within budget
- Power: within budget
- No unmapped cells in final netlist

## Output Required
- Gate-level netlist (.v)
- Timing report (setup and hold)
- Area report
- Power report
- Synthesis run log
```

---

### 3.3 `sv-synth-netlist-qc/SKILL.md`

```markdown
# Skill: Synthesis — Netlist Quality Check

## Purpose
Verify the gate-level netlist is correct and ready for PD handoff.

## Checks to Perform
1. Netlist completeness: all modules elaborated and mapped
2. No black boxes (undefined modules)
3. All scan chains intact (if DFT-enabled compile)
4. Power/ground connections correct (tie cells, well ties)
5. Antenna cells: verify tie-offs for floating gates
6. Check for combinational loops (report_loop)
7. Formal equivalence check (RTL vs netlist): PASS required
8. SDC consistency: netlist SDC matches RTL SDC intent

## Formal Equivalence (LEC / Conformal)
- Golden: RTL (post-lint, post-CDC-clean)
- Revised: gate-level netlist
- Result: all points proven EQUIVALENT
- Any UNMATCHED point: must be resolved before PD

## QoR Metrics
- LEC: 100% equivalent (no unmatched points)
- No black boxes
- No combinational loops
- Scan chain integrity: verified

## Output Required
- LEC report (pass/fail)
- Netlist QC checklist
- Final gate netlist (ready for PD)
- Back-annotated SDC for PD
```

---

## 4. Orchestrator System Prompt

The orchestrator's system prompt is its agent definition, [`synthesis-orchestrator.md`](../plugins/synthesis/agents/synthesis-orchestrator.md): stage
sequence, loop-back rules, stage gating and escalation. This document does not
restate it.
