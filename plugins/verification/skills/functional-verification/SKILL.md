---
name: functional-verification
description: >
  UVM-based functional verification — testbench architecture, test planning,
  directed and constrained-random stimulus, functional and code coverage closure,
  formal assist, and regression sign-off. Use when building a UVM testbench,
  writing tests, analysing coverage, or managing a verification regression.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: Functional Verification (UVM)

## Invocation

When this skill is loaded and a user presents a verification task, **do not
execute stages directly**. Immediately spawn the
`digital-chip-design-agents:verification-orchestrator` agent and pass the full
user request and any available context to it. The orchestrator enforces the stage
sequence, loop-back rules, and sign-off criteria defined below.

Use the domain rules in this file only when the orchestrator reads this skill
mid-flow for stage-specific guidance, or when the user asks a targeted reference
question rather than requesting a full flow execution.

## Pre-run Context

Before executing or advising on **any** stage, read the following files if they exist:

1. `memory/verification/knowledge.md` — known failure patterns, successful tool flags, PDK/tool quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `memory/verification/run_state.md` — current run identity (`run_id`, `design_name`, `tool`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Guide the complete UVM functional verification flow from testbench architecture
through coverage-closed regression sign-off. Produces a verified RTL package
with documented coverage and a clean regression.

---

## Supported EDA Tools

### Open-Source
- **Verilator** (`verilator`) — fast cycle-accurate simulator; UVM support via verilator+UVM
- **Icarus Verilog** (`iverilog`) — event-driven simulation for quick testbench checks
- **cocotb** — Python-based co-simulation framework (`pip install cocotb`)
- **PyUVM** — UVM implementation in Python for cocotb environments
- **UVVM** — VHDL verification methodology library

### Proprietary
- **Synopsys VCS** (`vcs`) — industry-standard SV/UVM simulator
- **Cadence Xcelium** (`xrun`) — multi-language simulator with coverage engine
- **Siemens Questa** (`vsim` / `vlog` / `vcom`) — mixed-language simulation with UVM support

---

## Stage: tb_architecture

### Domain Rules
1. Follow UVM 1.2 standard (IEEE 1800.2)
2. One UVM agent per DUT interface (driver, monitor, sequencer)
3. Active agents: drive stimulus; passive agents: monitor only
4. Scoreboard: checks DUT output against reference model output
5. Reference model: functional model of DUT — SystemVerilog or C++ via DPI
6. Coverage collector: separate component from scoreboard
7. Virtual sequencer: coordinates multi-agent stimulus scenarios
8. All TB parameters via uvm_config_db — no hardcoded values in components

### UVM Hierarchy Template
```
uvm_test
  └─ uvm_env
       ├─ agent_A (active)   driver + monitor + sequencer
       ├─ agent_B (passive)  monitor only
       ├─ scoreboard
       ├─ coverage_collector
       └─ virtual_sequencer
```

### QoR Metrics to Evaluate
- All DUT interfaces covered by an agent
- Reference model: adequate to check all DUT outputs
- TB compile: 0 errors

### Output Required
- TB architecture diagram
- UVM component list and hierarchy
- Interface-to-agent mapping table

---

## Stage: test_planning

### Domain Rules
1. Every functional requirement → at least one directed test
2. Every interface → protocol compliance test
3. Error/exception cases: explicit directed tests (not left to random)
4. Corner cases: boundary values, max/min, overflow, underflow
5. Concurrency: multi-threaded stimulus for pipeline stress
6. Back-pressure: tests under flow control conditions
7. Reset: in-operation resets, reset during active transaction
8. Define covergroups before writing tests
9. Plan the corner cases a directed test rarely reaches, one V-plan entry each:
   - simultaneous events — load and increment, read and write when empty, flush and enable,
     full and empty together
   - the first cycle out of reset
   - sustained back-pressure (`ready` low for many cycles) and maximum-rate input with no gaps
   - an input deasserting mid-transaction
   - both extremes of the clock ratio for a multi-clock block
10. Test at boundary parameter values, not only the default configuration: `WIDTH=1`,
    `DEPTH=1` and `2`, `N=1`, and a non-power-of-two value. A value the RTL is meant to
    reject gets a test that it refuses to elaborate
11. Take the RTL hand-off as an input: each entry in `design_state.rtl.unverified[]` (claims
    the RTL flow concluded without a tool run) gets a test or is marked as assigned to formal.
    `cdc` and `reset` entries cannot be closed by functional simulation — record them as
    needing a CDC/RDC tool run rather than as covered

### V-Plan Entry Template (per feature)
```
feature_id:   F001
description:  AXI write burst handling
tests:        [direct_single_write, burst_len_256, narrow_transfer]
assertions:   [axi_valid_stable, axi_handshake_check]
covergroups:  [burst_len_cg, burst_type_cg]
priority:     P0
```

### QoR Metrics to Evaluate
- Requirement coverage: 100% of spec features mapped
- P0 tests: must pass before random testing begins
- Estimated test count: reasonable vs schedule

### Output Required
- V-plan document
- Covergroup definitions
- Assertion list with expected behaviour

---

## Stage: uvm_tb_build

### Domain Rules — Sequences
1. Base sequence: minimum valid transaction
2. Extended sequences: specific scenarios from V-plan
3. Sequence library: register all sequences for random selection
4. Never hardcode values — use randomised fields with constraints

### Domain Rules — Testbench Coding
Testbench code is exempt from the RTL synthesis rules — `initial`, `#delay` and blocking
assignments are correct here — but it is still SystemVerilog that has to elaborate the same
way in every simulator.
1. `` `default_nettype none `` at the top of every testbench, interface and bind file, restored
   with `` `default_nettype wire `` at the end so library code compiled after it is unaffected;
   a typo in a DUT connection must be an error, not an implicit one-bit net
2. Instantiate the DUT with named port connections and named parameter overrides
   (`#(.WIDTH(8))`), never positional — a positional connection mis-wires silently when a
   port list is reordered
3. Type every parameter and constant (`int unsigned`, `logic [W-1:0]`). An untyped parameter
   and a size-cast bare literal (`WIDTH'(1)`) are signed; in a scoreboard comparison that
   yields a false pass or a false mismatch on values with the top bit set
4. Compare expected and actual at the same width and signedness, and compare with `!==` so
   an X or Z on the DUT output is a mismatch, not a silent pass
5. Comment the why: each assumption about the DUT, each waiver, each deliberately illegal
   stimulus

### Domain Rules — Drivers
1. Drive signals cycle-accurate to protocol specification
2. Handle back-pressure per the ready/valid contract. As a source: assert `valid` without
   waiting for `ready`, then hold `valid` and the payload stable until the beat is accepted. As
   a sink: `ready` may depend on `valid`. A driver that waits for `ready` before asserting
   `valid` deadlocks against a DUT that waits for `valid`, and hides DUT bugs that only appear
   under back-pressure
3. Protocol assertion in driver to catch illegal stimulus early

### Domain Rules — Scoreboard
1. Predict expected output from reference model before DUT output arrives
2. Report mismatches with full context (stimulus, expected, actual)
3. Track: total checks, pass, fail, untriggered

### Domain Rules — SVA Assertions
1. Protocol assertions: in interface bind, not DUT
2. Functional assertions: in checker or bind module
3. All assertions: clearly named with descriptive failure message
4. Every ready/valid interface carries the contract as assertions: transfer only on
   `valid && ready`; `valid` not retracted before the beat is accepted; payload stable while
   `valid && !ready`; `valid` and `ready` deasserted (not X) in reset

### QoR Metrics to Evaluate
- TB compile: 0 errors, 0 warnings
- Sanity test: passes with known-good RTL
- All components active in simulation log

### Output Required
- UVM component source files
- SVA assertion files (bind-based)
- Compile script

---

## Stage: directed_tests

### Domain Rules
1. Implement one directed test per V-plan entry — tests must be deterministic
2. Each test: verify the exact functional requirement it targets (no catch-all tests)
3. Error/exception paths: explicit stimulus to trigger each one
4. Corner cases: boundary values, max/min, overflow, underflow — one test each
5. Reset during active transaction: at least one test per interface
6. P0 tests must all pass before constrained-random phase begins
7. DUT bug found during directed test: write a `fix_request` entry to `design_state.fix_requests[]` per the schema in the verification-orchestrator Design State section; terminate with `decision=escalate`. The pipeline-orchestrator (`chip-design-meta`) handles RTL re-invocation — do not loop locally or wait for user confirmation.
8. Before filing, classify the failure as DUT bug or testbench bug, and name the mechanism,
   not just the location — the reported symptom is not necessarily the bug. Set
   `suspected_rtl.basis` to `traced` only when you followed the mismatch back to that signal
   in the waveform; otherwise `hypothesis`. Start from the symptom:

   | Symptom | Look first at |
   |---|---|
   | Intermittent, rate scales with clock ratio | Clock-domain crossing |
   | Fails at bring-up, fine once running | Reset release and reset values |
   | Hangs until reset | FSM state with no exit, protocol wait-for cycle |
   | Wrong only for large values | Width truncation, arithmetic overflow |
   | Wrong only for negative values | Signed/unsigned mix |
   | Fails only under sustained load | Arbitration fairness, retracted `valid`, unstable payload |
   | Passes in RTL sim, fails in gate sim | Blocking assignment in clocked block, incomplete sensitivity list, X-optimism |
   | Degrades slowly over a long run | Leaked credit or token |
9. Never make a failing test pass by weakening the check: do not loosen the scoreboard
   comparison, disable or waive an assertion, or constrain stimulus away from the failing case
   unless that stimulus was illegal per the spec. A fix to the testbench must leave every
   other test's checking at least as strict as before

### QoR Metrics to Evaluate
- All V-plan features covered by at least one directed test
- P0 directed tests: 100% pass before proceeding
- 0 UVM FATAL or ERROR during directed test phase

### Output Required
- Directed test source files (one UVM sequence per feature)
- Directed test pass/fail report
- Bug report (if any DUT bugs found)

---

## Stage: constrained_random

### Domain Rules
1. Constraint blocks: randomise all stimulus fields within protocol-legal ranges
2. Bias constraints: weight toward uncovered coverage bins identified in prior runs
3. Seeds: use at least 10 distinct seeds before evaluating coverage
4. Scoreboards active throughout: every transaction checked against reference model
5. Any UVM FATAL: stop immediately — do not accumulate errors across seeds
6. Any scoreboard mismatch: classify as DUT bug or testbench bug before continuing, using the
   symptom table in `directed_tests` rule 8
7. Run until coverage targets are met or max seed budget exhausted

### QoR Metrics to Evaluate
- Functional coverage: trending toward 100% across seeds
- No persistent scoreboard mismatches (classify and fix before more seeds)
- Regression pass rate: 100% (no failing seeds)

### Output Required
- Coverage report (merged across all seeds run so far)
- Uncovered bin list for directed test closure
- Seed log (seed number, pass/fail, coverage achieved)

---

## Stage: coverage_analysis

### Coverage Targets
| Type | Target | Priority |
|------|--------|----------|
| Functional (V-plan) | `design_state.constraints.coverage.functional_pct`% (default: 100%) | P0 |
| Code Line | ≥ `design_state.constraints.coverage.line_pct`% (default: 95%) | P1 |
| Code Branch | ≥ `design_state.constraints.coverage.branch_pct`% (default: 90%) | P1 |
| Code Toggle | ≥ `design_state.constraints.coverage.toggle_pct`% (default: 85%) | P2 |
| FSM State | `design_state.constraints.coverage.fsm_state_pct`% (default: 100%) | P0 |
| FSM Transition | ≥ `design_state.constraints.coverage.fsm_transition_pct`% (default: 95%) | P0 |
| Assertion triggered | `design_state.constraints.coverage.assertion_pct`% (default: 100%) | P1 |

### Closure Strategy
1. Identify uncovered bins after N random seeds
2. Write targeted directed tests for hard-to-hit bins
3. Adjust constraints to bias toward uncovered areas
4. Waive unreachable bins with justification (dead code)

### QoR Metrics to Evaluate
- Functional coverage: 100% (no unwaived misses)
- Code coverage: per targets above
- Waiver file: all entries approved by verification lead

### Output Required
- Coverage report (merged across all seeds)
- Uncovered bin list with closure plan
- Waiver file

---

## Stage: formal_assist

### Use Cases for Formal
1. Protocol compliance: prove handshake never violates
2. Deadlock freedom: prove no state where valid=1 and ready never comes
3. Liveness: every request eventually gets a response
4. One-hot FSM: state encoding never has 0 or >1 bits set
5. Coverage closure: hit bins unreachable by simulation

### Domain Rules
1. Write properties in concurrent SVA
2. Group properties by feature in separate .sva files
3. Constrain environment with assumptions that match valid stimulus
4. Run vacuity check: assumption disabled → property should NOT hold
5. Bound liveness properties (##[1:BOUND])

### QoR Metrics to Evaluate
- All properties: PROVEN or clearly UNREACHABLE
- No vacuous proofs
- Additional coverage bins closed vs simulation baseline

### Output Required
- SVA property file
- Formal run report (proven/failed/vacuous per property)
- CEX waveform descriptions for any failures

---

## Stage: regression_signoff

### Regression Tiers
| Tier | Trigger | Duration | Contents |
|------|---------|----------|----------|
| Smoke | Every RTL commit | < 30 min | P0 directed tests |
| Nightly | Every night | < 8 hr | All directed + 100 random seeds |
| Weekly | Weekly gate | < 48 hr | Full suite, 1000 seeds |
| Sign-off | Tape-out gate | Unlimited | Full suite, 10,000 seeds |

### Pass Criteria
- 0 simulation failures (excluding waived known bugs)
- 0 UVM FATAL or UVM ERROR messages
- All coverage targets met (see `coverage_analysis` targets; driven by `design_state.constraints.coverage.*`)
- Formal: all P0 properties proven
- All P0/P1 bugs: closed

### Output Required
- Regression pass/fail report
- Final merged coverage report
- Open bug list
- Sign-off checklist

---

## Constraint Validation

See `plugins/meta/skills/pipeline-orchestration/SKILL.md` §Constraints Schema for the authoritative schema and stage-entry validation rule.

**No required keys** for functional verification — all constraints in this domain are optional with schema defaults.

**Optional (schema defaults apply when absent):**
- `constraints.coverage.functional_pct` (default: 100) — functional/V-plan coverage target %
- `constraints.coverage.line_pct` (default: 95) — code line coverage target %
- `constraints.coverage.branch_pct` (default: 90) — code branch coverage target %
- `constraints.coverage.toggle_pct` (default: 85) — toggle coverage target %
- `constraints.coverage.fsm_state_pct` (default: 100) — FSM state coverage target %
- `constraints.coverage.fsm_transition_pct` (default: 95) — FSM transition coverage target %
- `constraints.coverage.assertion_pct` (default: 100) — assertion trigger coverage target %

Tag `constraint_ref` in history entries when evaluating QoR against these values (e.g. `"coverage.functional_pct"`).

---

## Memory

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
write or overwrite one JSON record in `memory/verification/experiences.jsonl` keyed by
`run_id`. This ensures data is persisted even if the flow is interrupted or called
without full orchestrator context.

Use `run_id` = `verification_<YYYYMMDD>_<HHMMSS>` (set once at flow start; reuse on each
stage update). Set `signoff_achieved: false` until the final sign-off stage completes.
### Run state (write before first stage, update after each stage)
Write `memory/verification/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:      verification_<YYYYMMDD>_<HHMMSS>
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
applied fix as an observation to entity `chip-design-verification-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.
