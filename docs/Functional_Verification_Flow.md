# Functional Verification Flow — Full Architecture Design
## Orchestrator + Stage Agents + Skills (UVM-Based)

> **Purpose**: AI-driven functional verification flow using UVM. Covers testbench architecture, test planning, stimulus generation, coverage closure, assertion-based verification, and regression sign-off.

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│             VERIFICATION ORCHESTRATOR                        │
│  Input:  RTL, Microarch doc, verification plan               │
│  Output: Coverage-closed, regression-passing RTL sign-off    │
└────────────────────────┬─────────────────────────────────────┘
                         │
     ┌───────────────────┼───────────────────────┐
     ▼                   ▼                       ▼
  TB Architecture    Test Planning           Regression
  Agent              Agent                   Agent
     │                   │                       │
  SKILL              SKILL                   SKILL
```

---

## 2. Shared State Object

```json
{
  "run_id": "verif_001",
  "design_name": "my_block",
  "inputs": {
    "rtl_filelist":    "path/to/filelist.f",
    "dut_spec":        "path/to/spec.md",
    "microarch_doc":   "path/to/microarch.md",
    "interface_list":  ["AXI4", "APB", "custom_if"]
  },
  "stages": {
    "tb_architecture":     { "status": "pending", "output": {} },
    "test_planning":       { "status": "pending", "output": {} },
    "uvm_tb_build":        { "status": "pending", "output": {} },
    "directed_tests":      { "status": "pending", "output": {} },
    "constrained_random":  { "status": "pending", "output": {} },
    "coverage_analysis":   { "status": "pending", "output": {} },
    "formal_assist":       { "status": "pending", "output": {} },
    "regression_signoff":  { "status": "pending", "output": {} }
  },
  "coverage": {
    "functional":  0.0,
    "code_line":   0.0,
    "code_branch": 0.0,
    "code_toggle": 0.0,
    "assertion":   0.0
  },
  "bugs_found": [],
  "flow_status": "not_started"
}
```

---

## 3. Stage Sequence

```text
tb_architecture → test_planning → uvm_tb_build → directed_tests → constrained_random → coverage_analysis → formal_assist → regression_signoff
```

Loop-back rules — the target stage, the iteration cap, and which failures escalate
instead of looping — are in `## Loop-Back Rules` of [`verification-orchestrator.md`](../plugins/verification/agents/verification-orchestrator.md). That file is
authoritative; this document does not restate them.

---

## 4. Skill File Specifications

### 4.1 `sv-verif-tb-arch/SKILL.md`

```markdown
# Skill: Verification — UVM Testbench Architecture

## Purpose
Design the UVM testbench structure before any code is written.

## Domain Rules
1. Follow UVM 1.2 standard (IEEE 1800.2)
2. One UVM agent per DUT interface (driver, monitor, sequencer)
3. Agents: active (drives stimulus) vs passive (monitors only)
4. Scoreboard: checks DUT output against reference model
5. Reference model: functional model of DUT in SV or C++
6. Coverage collector: separate from scoreboard
7. Virtual sequencer: coordinates multi-agent scenarios
8. Configuration object: all TB parameters via uvm_config_db

## UVM TB Hierarchy Template
```
uvm_test
  └─ uvm_env
       ├─ agent_A (active)
       │    ├─ driver_A
       │    ├─ monitor_A
       │    └─ sequencer_A
       ├─ agent_B (passive)
       │    └─ monitor_B
       ├─ scoreboard
       ├─ coverage_collector
       └─ virtual_sequencer
```

## QoR Metrics
- All DUT interfaces covered by agent
- Reference model complexity: adequate to check all outputs
- TB compile: 0 errors

## Output Required
- TB architecture diagram
- UVM component list and hierarchy
- Interface and agent mapping table
```

---

### 4.2 `sv-verif-test-plan/SKILL.md`

```markdown
# Skill: Verification — Test Planning

## Purpose
Produce a comprehensive verification plan (V-plan) that maps
every spec requirement to a test or property.

## Domain Rules
1. Every functional requirement → at least one test
2. Every interface → protocol compliance test
3. Error/exception cases: explicit tests (not just random)
4. Corner cases: boundary values, max/min, overflow, underflow
5. Concurrency: multi-threaded stimulus for pipeline stress
6. Back-pressure: test DUT under flow control conditions
7. Reset: in-operation resets, reset during transaction
8. Coverage model: define covergroups before writing tests

## V-Plan Template (per feature)
{
  "feature_id": "F001",
  "feature_desc": "AXI write burst handling",
  "tests": ["direct_single_write", "burst_len_256", "narrow_transfer"],
  "assertions": ["axi_valid_stable", "axi_handshake"],
  "covergroups": ["burst_len_cg", "burst_type_cg"],
  "priority": "P0"
}

## QoR Metrics
- Requirement coverage: 100% of spec features mapped
- P0 tests: must pass before any random testing
- Estimated test count: reasonable vs schedule

## Output Required
- V-plan document (JSON or Markdown)
- Covergroup definitions
- Assertion list with expected behavior
```

---

### 4.3 `sv-verif-uvm-build/SKILL.md`

```markdown
# Skill: Verification — UVM Testbench Implementation

## Purpose
Build all UVM testbench components following UVM methodology.

## Domain Rules — Sequences
1. Base sequence: minimum valid transaction
2. Extended sequences: specific scenarios from V-plan
3. Sequence library: register all sequences for random selection
4. Never hard-code values: use randomized fields with constraints

## Domain Rules — Drivers
1. Drive signals cycle-accurate to protocol spec
2. Handle back-pressure: check ready/valid correctly
3. Protocol assertion in driver: catch illegal stimuli early

## Domain Rules — Monitors
1. Passive: never drive signals
2. Capture complete transactions, not individual signals
3. Write to analysis port for scoreboard and coverage

## Domain Rules — Scoreboard
1. Predict expected output from reference model before DUT output arrives
2. Report mismatches with full context (stimulus, expected, actual)
3. Track: total checks, pass, fail, untriggered

## Domain Rules — Assertions (SVA)
1. Protocol assertions: in interface, not DUT
2. Functional assertions: in checker or bind module
3. All assertions: clearly named with failure message

## QoR Metrics
- TB compile: 0 errors, 0 warnings
- Basic sanity test: passes with known-good RTL
- All components connected and active in simulation log

## Output Required
- UVM component source files
- SVA assertion files (bind-based)
- Compile script
```

---

### 4.4 `sv-verif-coverage/SKILL.md`

```markdown
# Skill: Verification — Coverage Analysis and Closure

## Purpose
Analyze coverage results and drive coverage closure efficiently.

## Coverage Types and Targets
| Type             | Target | Priority |
|------------------|--------|----------|
| Functional (V-plan) | 100% | P0 |
| Code Line        | ≥ 95%  | P1 |
| Code Branch      | ≥ 90%  | P1 |
| Code Toggle      | ≥ 85%  | P2 |
| FSM State        | 100%   | P0 |
| FSM Transition   | ≥ 95%  | P0 |
| Assertion        | 100% triggered | P1 |

## Coverage Closure Strategy
1. Identify uncovered bins after N random seeds
2. Write targeted directed tests for hard-to-hit bins
3. Adjust constraints to bias toward uncovered areas
4. Use coverage-driven test selection (CDTS)
5. Waive unreachable bins with justification (dead code)

## Waiver Process
- Unreachable code: justify with static analysis evidence
- Don't-care state combinations: document in V-plan
- All waivers approved by verification lead

## QoR Metrics
- Functional coverage: 100% (no unwaived misses)
- Code coverage: per targets above
- Coverage closure rate: tracked per regression

## Output Required
- Coverage report (merged across all seeds)
- Uncovered bin list with closure plan
- Waiver file
```

---

### 4.5 `sv-verif-formal/SKILL.md`

```markdown
# Skill: Verification — Formal Verification Assist

## Purpose
Use formal property verification to close gaps that simulation
cannot efficiently reach and to prove absence of bugs.

## Use Cases for Formal
1. Protocol compliance: prove AXI/APB handshake never violates
2. Deadlock freedom: prove no state where valid=1 and ready never comes
3. Liveness: prove every request eventually gets a response
4. One-hot FSM: prove state encoding never has 0 or >1 bits set
5. Coverage closure: use formal to hit hard-to-reach simulation bins
6. Reset verification: prove all registers reach reset state

## Domain Rules
1. Write properties in SVA (concurrent assertions)
2. Group properties by feature in separate .sva files
3. Constrain the environment (assumptions) to match valid stimulus
4. Over-constraining assumptions invalidates the proof — verify with vacuity check
5. Bounded model checking (BMC): for deep pipelines, set bound = pipeline depth + margin

## QoR Metrics
- All properties: PROVEN or UNREACHABLE (no CEX without fix)
- No vacuous proofs
- Formal coverage: additional bins closed vs simulation baseline

## Output Required
- SVA property file
- Formal run report (proven/failed/vacuous)
- Any counterexamples with waveform description
```

---

### 4.6 `sv-verif-regression/SKILL.md`

```markdown
# Skill: Verification — Regression Sign-off

## Purpose
Define and manage the regression suite to confirm DUT correctness
before RTL sign-off.

## Regression Tiers
| Tier   | Trigger          | Duration | Contents                        |
|--------|------------------|----------|---------------------------------|
| Smoke  | Every RTL commit | < 30min  | P0 directed tests only          |
| Nightly| Every night      | < 8hr    | All directed + 100 random seeds |
| Weekly | Weekly gate      | < 48hr   | Full suite, 1000 random seeds   |
| Signoff| Tape-out gate    | Unlimited| Full suite, 10,000 seeds        |

## Pass Criteria (Sign-off)
- 0 simulation failures (not counting known waived bugs)
- 0 UVM FATAL or UVM ERROR messages
- All coverage targets met
- Formal: all properties proven
- All open bugs: P0/P1 closed; P2/P3 documented

## Bug Tracking Template
{
  "bug_id": "BUG_001",
  "description": "...",
  "severity": "P0|P1|P2|P3",
  "status": "open|fixed|waived",
  "rtl_fix_commit": "abc123",
  "test_that_found": "test_burst_overflow"
}

## Output Required
- Regression pass/fail report
- Coverage merged report (final)
- Open bug list
- Sign-off checklist
```

---

## 5. Orchestrator System Prompt

The orchestrator's system prompt is its agent definition, [`verification-orchestrator.md`](../plugins/verification/agents/verification-orchestrator.md): stage
sequence, loop-back rules, stage gating and escalation. This document does not
restate it.
