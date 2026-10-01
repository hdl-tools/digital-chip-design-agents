# RTL Design Flow — Full Architecture Design
## Orchestrator + Stage Agents + Skills

> **Purpose**: AI-driven RTL design flow in SystemVerilog. Covers module planning, RTL coding, linting, CDC/RDC analysis, and synthesis readiness sign-off. Takes the microarchitecture document as input and produces a synthesis-ready RTL package.

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    RTL DESIGN ORCHESTRATOR                   │
│  Input:  Microarch doc, interface specs, coding guidelines    │
│  Output: Lint-clean, CDC-clean, synthesis-ready RTL          │
└────────────────────────┬─────────────────────────────────────┘
                         │
     ┌───────────────────┼───────────────────────┐
     ▼                   ▼                       ▼
┌──────────┐     ┌──────────────┐       ┌───────────────┐
│  Stage   │     │   Stage      │       │   Stage       │
│  Agent   │     │   Agent      │  ...  │   Agent       │
│  Module  │     │  RTL Coding  │       │  Synth Ready  │
│  Planning│     │  & Review    │       │  Sign-off     │
└────┬─────┘     └──────┬───────┘       └───────┬───────┘
     │                  │                       │
     ▼                  ▼                       ▼
  SKILL               SKILL                   SKILL
```

---

## 2. Shared State Object

```json
{
  "run_id": "rtl_design_001",
  "design_name": "my_block",
  "inputs": {
    "microarch_doc":   "path/to/microarch.md",
    "interface_spec":  "path/to/interfaces.md",
    "coding_guidelines": "path/to/guidelines.md",
    "technology":      "tsmc7nm",
    "target_frequency": "1GHz"
  },
  "stages": {
    "module_planning":   { "status": "pending", "output": {} },
    "rtl_coding":        { "status": "pending", "output": {} },
    "lint_check":        { "status": "pending", "output": {} },
    "cdc_rdc_analysis":  { "status": "pending", "output": {} },
    "synth_check":       { "status": "pending", "output": {} },
    "rtl_signoff":       { "status": "pending", "output": {} }
  },
  "module_list":    [],
  "lint_errors":    [],
  "cdc_violations": [],
  "flow_status": "not_started"
}
```

---

## 3. Stage Sequence & Loop-Back Logic

```
[Module Planning] ──► [RTL Coding] ──► [Lint Check]
                           ▲                 │ fail
                           └─────────────────┘
                                             │ pass
                              ▼
                       [CDC/RDC Analysis]
                           ▲      │ violations
                           └──────┘
                                  │ pass
                              ▼
                       [Synth Check]
                           ▲      │ fail (timing/area)
                           └──────┘
                                  │ pass
                              ▼
                       [RTL Sign-off]
                              │ fail → back to RTL Coding
                              ▼ pass
                    [Synthesis-Ready RTL Package]
```

### Loop-Back Rules

| Failure Condition                     | Loop Back To   | Max Iterations |
|---------------------------------------|----------------|----------------|
| Lint errors > 0                       | RTL Coding     | 5              |
| CDC violations (unwaived)             | RTL Coding     | 3              |
| Synth: timing worse than -20% margin  | RTL Coding     | 2              |
| Synth: area > 120% of estimate        | RTL Coding     | 2              |
| Sign-off: missing coverage            | Module Planning| 1              |

---

## 4. Skill File Specifications

### 4.1 `sv-rtl-planning/SKILL.md`

```markdown
# Skill: RTL — Module Planning

## Purpose
Decompose the microarchitecture into a module hierarchy with
clear interfaces before any RTL is written.

## Domain Rules
1. Top-down decomposition: start with top-level, recurse to leaf cells
2. Each module: single clear responsibility (SRP — single responsibility principle)
3. Define all port lists before coding (port direction, width, type)
4. Identify all clock domains per module; mark CDC crossings explicitly
5. Identify all reset domains; mark synchronous vs asynchronous resets
6. Parameterize widths and depths wherever possible
7. No logic in top-level integration modules (wiring only)
8. Separate datapath and control into distinct sub-modules

## Module Descriptor Template (per module)
{
  "module_name": "my_fifo",
  "purpose": "Async FIFO for CDC crossing",
  "clock_domain": ["clk_a", "clk_b"],
  "reset": "arst_n (async active-low)",
  "parameters": ["DEPTH", "WIDTH"],
  "ports": [...],
  "sub_modules": [],
  "complexity_estimate": "LOW | MEDIUM | HIGH"
}

## QoR Metrics
- All microarch blocks mapped to at least one module
- All interfaces matched to port lists
- CDC crossings explicitly annotated

## Output Required
- Module hierarchy tree
- Module descriptor JSON for each module
- Interface/port list document
```

---

### 4.2 `sv-rtl-coding/SKILL.md`

```markdown
# Skill: RTL — SystemVerilog Coding Standards

## Purpose
Enforce synthesizable, readable, and maintainable RTL coding practices.

## Domain Rules — General
1. Always use `logic` type (not `wire`/`reg` distinction)
2. All ports explicitly typed and directioned
3. No implicit net declarations (`default_nettype none` at top)
4. No latches: all combinational always_comb blocks must be complete
5. No blocking assignments in always_ff blocks
6. No non-blocking assignments in always_comb blocks
7. One always block per register or register group
8. Reset all registers explicitly (synchronous preferred for ASIC)

## Domain Rules — Naming Conventions
- Clocks:          clk_[domain]
- Resets:          rst_n_[domain] (active-low) or rst_[domain]
- Active-low:      signal_n suffix
- Registered:      signal_q suffix
- Combinational:   signal_d (next-state) suffix
- Parameters:      UPPER_SNAKE_CASE
- Modules/Signals: lower_snake_case

## Domain Rules — Synthesis Constraints
1. No delays (#) in RTL — simulation only
2. No initial blocks for logic (FPGA exception); elaboration-time parameter
   assertions are allowed inside `// synthesis translate_off` / `translate_on`
3. No casex; casez only with a written justification. FSMs: plain case with a
   default recovery arm, or unique case without default plus a recovery assertion
   — never unique case together with default
4. Limit fan-out per net: flag if > 32 without buffering intent
5. Pipeline registers: clearly marked with _q suffix at each stage
6. No combinational loops (will cause synthesis tool errors)

## Domain Rules — CDC
1. Use synchronizer modules (2-FF) for all single-bit CDC crossings
2. Use async FIFO for multi-bit CDC data paths
3. Use gray-coded counters for pointer crossings in async FIFOs
4. Never sample asynchronous data directly in synchronous logic

## Domain Rules — Power Intent (Clock Gating)
Read `clock_power_budget` from architecture hand-off if it exists; else use
Verilator toggle coverage to estimate activity factors.

1. **High gating opportunity** (α < 0.15): insert ICG cell (`CLKGATETST_X*` or
   technology equivalent) at the outermost clock enable boundary. Explicit ICG
   insertion at RTL is required — do not rely on synthesis inference.
2. **Moderate gating opportunity** (0.15 ≤ α < 0.40): insert ICG at sub-block
   level for any register file or datapath wider than 32 bits.
3. **Always-on** (α ≥ 0.40 or documented as always-on): no ICG required; add a
   `/* always-on: <reason> */` comment at the clock port declaration.
4. ICG enable signal must be registered (combinational enable is a lint error).
5. Use only library-approved cells (`CLKGATETST_*`); no behavioral clock gating.
6. Measure `clock_gating_coverage`:
   `coverage = (register bits behind ICG / total register bits in domain) × 100%`
   QoR gate: ≥ 60% for high-opportunity domains; report in sign-off record.

## Output Required
- RTL source files (.sv) per module
- Self-checking assertions (SVA) per module
- Inline comments explaining non-obvious logic
- `clock_gating_coverage` metric per domain (appended to sign-off record)
```

---

### 4.3 `sv-rtl-lint/SKILL.md`

```markdown
# Skill: RTL — Lint Checking

## Purpose
Identify coding errors, style violations, and synthesis mismatches
before simulation or synthesis is run.

## Lint Rule Categories
1. ERRORS (must fix): Latches, incomplete sensitivity lists, X-propagation,
   undriven outputs, multiply-driven signals
2. WARNINGS (review): Unused ports, unused parameters, constant conditions,
   truncated assignments, bit-width mismatches
3. INFO (waivable): Naming convention violations, comment coverage

## Recommended Lint Tools
- Synopsys SpyGlass
- Cadence HAL
- Siemens (Mentor) 0-In
- Verilator (open source, basic)

## Waiver Process
- Waivers must include: signal name, rule ID, justification, approver
- No ERROR-level waivers without architect approval
- All waivers logged in lint_waivers.csv

## QoR Metrics
- ERROR count: must be 0
- WARNING count: review all; waive with justification
- Lint coverage: all RTL files checked (not just top-level)

## Output Required
- Lint report (per file, per rule)
- Waiver file (if applicable)
- Clean lint summary
```

---

### 4.4 `sv-rtl-cdc/SKILL.md`

```markdown
# Skill: RTL — CDC and RDC Analysis

## Purpose
Verify all clock domain crossings (CDC) and reset domain crossings (RDC)
are correctly handled before synthesis.

## CDC Rules
1. Every CDC crossing must use an approved synchronizer primitive
2. Single-bit control: 2-FF synchronizer minimum
3. Multi-bit data: async FIFO or handshake protocol
4. Pulse crossings: pulse stretcher + synchronizer
5. CDC violations: metastability windows, missing synchronizers,
   reconvergent fanout without reconvergence analysis

## RDC Rules
1. All reset domains explicitly defined
2. Reset de-assertion: synchronous to receiving clock domain
3. No combinational logic between reset sources
4. Isolation: powered-down domains must have isolation cells
5. Retention registers: correct UPF annotation

## Recommended Tools
- Synopsys SpyGlass CDC
- Cadence JasperGold CDC
- Mentor CDC (Questa CDC)

## QoR Metrics
- CDC violations: 0 unwaived
- RDC violations: 0 unwaived
- All clock domains verified in tool constraints file

## Output Required
- CDC/RDC report
- Synchronizer instance list
- Waiver file (if applicable)
```

---

### 4.5 `sv-rtl-synth-check/SKILL.md`

```markdown
# Skill: RTL — Synthesis Readiness Check

## Purpose
Run an early synthesis pass to identify timing, area, and
synthesis issues before handoff to the synthesis flow.

## Domain Rules
1. Run synthesis at target frequency with typical corner
2. Check for unmapped cells (technology library gaps)
3. Identify critical paths for architect review
4. Check area: compare against microarch estimate (< 120% acceptable)
5. Check for multi-driven nets or unresolved X
6. Identify high-fanout nets that need buffering strategy
7. Verify all clock definitions synthesize correctly

## QoR Metrics
- WNS at target frequency: > -0.5ns acceptable (synthesis not optimized)
- Area: < 120% of microarch estimate
- No unmapped cells
- No multi-driven nets

## Output Required
- Synthesis area report
- Timing report (critical paths)
- Recommendations for RTL fixes (if any)
```

---

### 4.6 `sv-rtl-signoff/SKILL.md`

```markdown
# Skill: RTL — Design Sign-off

## Purpose
Confirm the RTL is complete, correct, and ready for simulation
and synthesis handoff.

## Sign-off Checklist
- [ ] All modules from planning are implemented
- [ ] Lint: 0 errors, all warnings reviewed
- [ ] CDC: 0 unwaived violations
- [ ] RDC: 0 unwaived violations
- [ ] Synthesis check: timing within range
- [ ] All ports connected in integration
- [ ] SVA assertions in place for key properties
- [ ] Code review completed
- [ ] File list and compile order documented
- [ ] ICG cells inserted for all high/moderate gating opportunity domains
- [ ] Always-on domains annotated with `/* always-on: <reason> */`
- [ ] `clock_gating_coverage` ≥ 60% for high-opportunity domains; reported in sign-off record

## Output Required
- RTL file package (all .sv files)
- File list (filelist.f)
- Compile order document
- Assertion library (.sva files)
- RTL design review sign-off record
```

---

## 5. Orchestrator System Prompt

```
You are the RTL Design Orchestrator for SystemVerilog chip design.

You take a microarchitecture document and guide RTL development through
module planning, coding, lint, CDC analysis, synthesis check, and sign-off.

STAGE SEQUENCE:
  module_planning → rtl_coding → lint_check → cdc_rdc_analysis →
  synth_check → rtl_signoff

LOOP-BACK RULES:
  - lint_check FAIL               → rtl_coding (max 5x)
  - cdc_rdc_analysis FAIL         → rtl_coding (max 3x)
  - synth_check FAIL (timing)     → rtl_coding (max 2x)
  - synth_check FAIL (area)       → rtl_coding or module_planning (max 2x)
  - rtl_signoff FAIL (missing)    → module_planning (max 1x)
  - rtl_signoff FAIL (quality)    → rtl_coding (max 2x)

Output: Synthesis-ready RTL package with sign-off report.
```
