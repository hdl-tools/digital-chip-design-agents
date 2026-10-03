---
name: rtl-design
description: >
  SystemVerilog RTL design — module planning, coding standards enforcement, lint
  checking, CDC/RDC analysis, and synthesis readiness verification. Use when
  writing, reviewing, or debugging RTL for ASIC or FPGA targets, or when
  checking an existing RTL package for synthesis readiness.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: RTL Design (SystemVerilog)

## Invocation

When this skill is loaded and a user presents an RTL design task, **do not
execute stages directly**. Immediately spawn the
`digital-chip-design-agents:rtl-design-orchestrator` agent and pass the full
user request and any available context to it. The orchestrator enforces the stage
sequence, loop-back rules, and sign-off criteria defined below.

Use the domain rules in this file only when the orchestrator reads this skill
mid-flow for stage-specific guidance, or when the user asks a targeted reference
question rather than requesting a full flow execution.

## Pre-run Context

Before executing or advising on **any** stage, read the following files if they exist:

1. `memory/rtl-design/knowledge.md` — known failure patterns, successful tool flags, PDK/tool quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `memory/rtl-design/run_state.md` — current run identity (`run_id`, `design_name`, `tool`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Guide RTL development from module hierarchy planning through lint-clean,
CDC-clean, synthesis-ready RTL. Enforces industry-standard SystemVerilog
coding practices and produces a signed-off RTL package ready for simulation
and synthesis handoff.

---

## Supported EDA Tools

### Open-Source
- **Verilator** (`verilator --lint-only`) — fast lint and simulation
- **Slang** (`slang`) — modern, standards-compliant SV parser and elaborator; lint with
  `slang -Weverything --ignore-unknown-modules` (full elaboration — see `lint_check` rule 6)
- **Surelog** (`surelog`) — SystemVerilog pre-processor and front-end for Yosys
- **sv2v** (`sv2v`) — SystemVerilog-to-Verilog converter; the front-end check (`lint_check`
  rule 15) parses its output with the tool that consumes it
- **Icarus Verilog** (`iverilog`) — Verilog/SV simulator for quick sanity checks

### Proprietary
- **Synopsys SpyGlass** (`spyglass`, dialect `synopsys`) — lint, CDC, RDC, and clock-domain analysis
- **Cadence JasperGold CDC** (`jg`, dialect `cadence`) — formal CDC verification
- **Siemens Questa CDC** (`vsim`, dialect `siemens`) — CDC analysis and sign-off

---

## Stage: module_planning

### Domain Rules
1. Top-down decomposition: start with top-level module, recurse to leaf cells
2. Each module: single clear responsibility (single responsibility principle)
3. Define all port lists before coding (direction, width, type)
4. Identify all clock domains per module; mark CDC crossings explicitly
5. Identify all reset domains; mark synchronous vs asynchronous
6. Parameterise widths and depths wherever possible
7. No logic in top-level integration modules — wiring only
8. Separate datapath and control into distinct sub-modules

### Output Required
- Module hierarchy tree
- Module descriptor (name, purpose, clock domain, ports, sub-modules) per module
- Interface/port list document

---

## Stage: rtl_coding

Scope: the rules in this stage govern synthesisable RTL. Testbenches (`*_tb.sv`, `tb_*.sv`,
anything under `tb/`), bind-only assertion files and simulation-only behavioural models are
out of scope — `initial`, `#delay` and blocking assignments are correct there, and the
functional-verification skill carries the coding rules for them.

### Domain Rules — General
1. Always use `logic` type (not wire/reg distinction)
2. All ports: explicitly typed and directioned
3. `default_nettype none` at top of every file
4. No latches: all always_comb blocks must have complete case and assignment coverage
5. No blocking assignments (=) in always_ff blocks
6. No non-blocking assignments (<=) in always_comb blocks
7. One always block per register or coherent register group
8. Reset all registers explicitly; synchronous reset preferred for ASIC

### Domain Rules — Naming Conventions
- Clocks:       `clk_[domain]`
- Resets:       `rst_n_[domain]` (active-low) or `rst_[domain]`
- Active-low:   `signal_n` suffix
- Registered:   `signal_q` suffix
- Next-state:   `signal_d` suffix
- Parameters:   `UPPER_SNAKE_CASE`
- Modules/Signals: `lower_snake_case`
- Port direction: `_i` / `_o` suffixes are permitted, not required

Precedence: these conventions are this suite's project standard for new RTL. When modifying
an existing file, match that file's conventions instead — one block in a different style is a
worse outcome than the deviation — and record the difference as informational, not as a
lint finding.

### Domain Rules — Synthesis Safety
1. No delays (#) in RTL — simulation only
2. No `initial` blocks for logic in ASIC RTL. One exception: an elaboration-time parameter
   assertion (`initial` + `$fatal` on an illegal parameter value), wrapped in
   `// synthesis translate_off` / `// synthesis translate_on` so it is never read as
   synthesised logic. A parameterised block must refuse to elaborate on a value it cannot
   implement (e.g. a gray-coded FIFO at a non-power-of-two depth) rather than build broken logic
3. No `casex`; `casez` only with a written justification; no `full_case` / `parallel_case`
   pragmas. Write don't-care decodes as explicit `case` items
4. Flag any net with fanout > `design_state.constraints.timing.fanout_max` (default: 32) for buffering intent review
5. No combinational loops — will cause synthesis errors
6. Pipeline registers: clearly marked with `_q` suffix at each stage
7. FSM case policy — pick one per FSM and state it in a comment:
   - **Default:** plain `case` with a `default` arm that goes to a recovery or error state.
     Illegal states are reachable in silicon (SEU, X during bring-up); the FSM must not wedge
   - **Alternative:** `unique case` with no `default`, plus a concurrent assertion that covers
     illegal-state recovery. Keeps the simulation/formal uniqueness check
   - Never `unique case` together with `default`: `unique` asserts the illegal state cannot
     occur, `default` exists to recover when it does (slang: `-Wcase-redundant-default`)

### Domain Rules — CDC
1. Two-FF synchroniser for every single-bit CDC crossing
2. Async FIFO for multi-bit CDC data paths
3. Gray-coded pointers for async FIFO crossing
4. Never sample asynchronous data directly in synchronous logic

### Domain Rules — Scan Readiness
RTL that blocks scan is cheapest to fix here; the DFT flow can only report it after insertion.
1. No RTL-generated clocks (`assign gclk = clk & en;`): flops behind one are unreachable in
   scan mode. Use a flop enable, or a library clock-gate cell with a test-enable input (Power
   Intent rule 5)
2. Every asynchronous set/reset must be controllable from a primary input in test mode. A
   reset derived from internal logic cannot be held inactive during scan shift — give it a
   `scan_mode` bypass to the top-level reset
3. No asynchronous set/reset generated from combinational logic
4. No on-chip tri-state buses — contention is untestable; use a mux
5. A deliberate latch (lockup latch, clock-gate cell internals) is instantiated as a library
   cell and waived by instance name in `lint_waivers.csv`, never inferred from RTL

### Domain Rules — Power Intent (Clock Gating)
Apply these rules for every clock domain. Read `clock_power_budget` from the architecture
hand-off package. **For orchestrated Architecture → RTL runs, the `clock_power_budget` table
is a required handoff contract; if missing, treat as a handoff violation and abort with a
clear error directing the user to notify upstream packaging.** For non-orchestrated or local
RTL-only runs, classify domains using toggle-count estimates from Verilator simulation as
a fallback.

1. **High gating opportunity domains** (α < `design_state.constraints.power.activity_factors.default` (default: 0.15) from architecture, or toggle rate below that threshold from Verilator): insert an ICG cell (`CLKGATETST_X*` or technology-equivalent) at the outermost clock enable boundary. Do not rely on synthesis to infer clock gates — explicit ICG insertion at RTL is required.
2. **Moderate gating opportunity domains** (`activity_factors.default` ≤ α < `activity_factors.high` (defaults: 0.15–0.40)): insert ICG at the sub-block level for any register file or datapath wider than 32 bits.
3. **Always-on domains** (α ≥ `activity_factors.high` (default: 0.40), or documented as always-on in architecture hand-off):
   no ICG required; add a `/* always-on: <reason> */` comment at the clock port declaration.
4. ICG enable signal: must be registered (setup-timing safe); combinational enable
   is a lint error.
5. ICG cells: use only library-approved cells (`CLKGATETST_*` for testability with
   scan-enable override); do not use behavioural `if (enable) clk_gated = clk` constructs.
6. After inserting ICGs, measure `clock_gating_coverage`:
   `coverage = (register bits behind an ICG) / (total register bits in domain) × 100%`
   Report this metric in the `rtl_signoff` output.

### Supported Tools for Power Intent

| Tool | Type | Use |
|------|------|-----|
| Verilator | Open-source | Toggle coverage → activity factor for gating classification |
| SpyGlass (Synopsys) | Proprietary, dialect `synopsys` | RTL power lint, missing ICG detection |
| VC Static (Synopsys) | Proprietary, dialect `synopsys` | Power-intent rule checking |
| Questa PowerPro (Siemens) | Proprietary, dialect `siemens` | Formal power analysis |

### Output Required
- RTL source files (.sv) per module
- SVA assertion files per module
- Inline comments on all non-obvious logic
- Unverified-claims entries: each CDC, reset, FSM, protocol, arithmetic or parameter
  conclusion reached in review without a tool run, appended to the unverified-claims list
  (see `rtl_signoff`) now, not at sign-off
- `clock_gating_coverage` metric per domain (appended to sign-off record)

---

## Stage: design_input_check

A lint tool reports on the files it was given. This stage checks that those are the intended
files **before** any lint message is read as a statement about the RTL. It edits nothing: its
only outputs are a report and a PASS or FAIL.

### Domain Rules
1. Resolve and print the **absolute** path of the filelist the tool will read, and of the
   project or config file that selected it. Where several candidates exist (a managed project
   file and a user-override directory, two filelists of the same name), state which one the
   tool uses and why. A stale override directory silently bypasses the managed project file and
   every variable it would have set
2. Resolve every include directory to an absolute path, in search order. Include search is
   first-match-wins: a file name that exists in two include directories with different content
   is an **ERROR**, not a warning — the tool silently uses the first and ignores the second.
   Name the file, every directory that holds it, and the one that wins
3. Flag include directories and sources that resolve outside the declared design root, and
   sibling trees reachable from the include set: `X` beside `X_v2`, `X_old`, `X_bak`, or
   parallel version directories that hold the same file names
4. For generated inputs (register-map headers, IP configuration headers): exactly one
   generation's output tree is on the include path, and it is newer than its generator source
5. Every path in the filelist exists. A missing include directory is an ERROR: the tool falls
   through to the next directory that has the file
6. Where the input set is a `.f` filelist, run `check_design_inputs.py` (in this skill's
   directory) and report its JSON:
   `python3 check_design_inputs.py <filelist.f> --root <design root> [--env NAME=VALUE] [--generated OUT_DIR=SOURCE]`.
   It applies rules 2, 3 and 5, rule 4's age check for each `--generated` pair, and rule 8
   with `--rtl-dir` and `--list`. Rule 1, and any flow driven by a vendor project file instead
   of a `.f` filelist, is checked by hand against the rules above
7. On FAIL, change no design file. The fix is in the input set — usually one line of a filelist
   — and choosing between two trees is the owner's decision: report `failure_class:
   "input_setup"`, `suggested_next_step: "escalate"`, the file, both absolute paths and the
   line to change. Never loop back to `rtl_coding` — the one exception is rule 8's
   registration of a module this run added
8. Registration: every module on disk must reach every tool. Projects keep separate source
   lists for simulation, lint, synthesis, PD and formal, often as Makefile variables, and a
   module missing from one of them is black-boxed by converters and synthesisers (sv2v,
   yosys) without an error — the simulation regression cannot notice, because it reads a
   different list. Enumerate every source list that feeds a tool in the project, dump any kept
   in a Makefile variable to a file
   (`make -s --eval='print-%:;@echo $($*)' print-<VAR> > <var>.f`), and run
   `python3 check_design_inputs.py <filelist.f> --rtl-dir <rtl dir> --list <name>=<file> ...
   [--exempt <list>:<module>]`. Each `module_not_in_list` is an ERROR naming the list and the
   file. Exempt a module only with a stated reason (a simulation-only model absent from the PD
   list). This is the one `design_input_check` failure that is not escalated: when the module
   was added by this run, adding it to the list is this run's job — a list edit, no RTL edit.
   A pre-existing module missing from a list, or a list you cannot edit, is `input_setup` per
   rule 7

### QoR Metrics to Evaluate
- Modules on disk missing from a tool's source list, not exempted: must be 0
- Include file names present in two directories with different content: must be 0
- Missing filelists, include directories and sources: must be 0
- Generated output trees on the include path, per generator: exactly 1
- Sibling trees, paths outside the design root, identical duplicate headers: review each;
  proceed only with the reason recorded

### Output Required
- Design-input report: absolute filelist and config paths, ordered absolute include
  directories, and every finding with the paths it names
- Registration report: every source list checked, each module missing from one, and each
  exemption with its reason
- Stage status: PASS, or FAIL with `failure_class: "input_setup"`

---

## Stage: lint_check

### Domain Rules
1. ERROR level (must fix): latches, incomplete sensitivity lists,
   undriven outputs, multiply-driven signals, X-propagation sources
2. WARNING level (review): unused ports, truncated assignments,
   bit-width mismatches, constant conditions
3. All waivers: must include signal name, rule ID, justification, approver
4. No ERROR-level waivers without architect approval
5. All waivers logged in `lint_waivers.csv`
6. Slang must run full elaboration: `slang -Weverything --ignore-unknown-modules <files>`.
   Never pass `--lint-only` — it skips elaboration and silently drops inferred-latch and
   multiple-driver diagnostics, both ERROR level here, so a latch reports as clean. `-Wall` is
   not a slang option. Verilator is unaffected: `verilator --lint-only -Wall` is correct
7. Lint in filelist context: compile the block's filelist as one unit, then report findings
   for the files written or changed. A file linted alone reports its submodules as unknown and
   its cross-file widths as unchecked
8. A module missing from the filelist (library cell, hard macro, black-boxed IP) is a stub.
   Undriven or unused findings on nets that only a stub drives are not ERRORs; record them as
   informational and name the stubbed module and the library, macro or IP it stands for. A
   stub is benign only if you can name that: an unknown module that resolves to first-party
   RTL in this repository is a missing filelist entry (`design_input_check` rule 8), not a stub
9. Every finding states its evidence. Tool-proven: quote the tool's message and rule name.
   Reasoned without a tool run: label it `UNVERIFIED`. A clean lint run proves nothing about
   CDC, reset sequencing, FSM reachability, protocol deadlock or arithmetic overflow
10. Fixing a finding must not change what the module does. After each fix compare the set of
    findings, not the count: a new ERROR is a regression — revert it; the same findings twice
    running is no progress — escalate rather than spend the remaining iterations; a fix that
    changes behaviour to silence a warning (narrowing a signal to stop a truncation warning
    implements the truncation) is intent drift — revert and escalate
11. Where a tool reports its own severities, map them onto the levels above so waivers still
    apply: `BLOCKER` / `HIGH` → ERROR, `MEDIUM` → WARNING, `LOW` / `INFO` → informational
12. A run whose rule check did not complete ran **zero** rules. A parse or elaboration fatal,
    a tool message that rule checking was aborted or skipped, or a missing file means the
    ERROR and WARNING counts are unknown — record them as `null`, never `0` — and the result is
    not evidence about the RTL. Such a run is never classified `functional`
13. Attribute every fatal of an aborted run before editing any file. It is an input-set
    failure (`input_setup` — escalate, edit no RTL) when: duplicate-declaration **and**
    undeclared-identifier fatals appear in the same run (two generations of a generated header
    on the include path); a message names two paths for one file; an include or source file is
    not found; or the fatal is in a file this run did not write. Deleting the "duplicate" port
    or declaring the "undeclared" signal silences the message and corrupts correct RTL. Only a
    parse error in a file this run wrote or changed, with `design_input_check` passing on the
    current input set, goes back to `rtl_coding` — as malformed output (`tool_error`), to
    repair the syntax and nothing else
14. Triage findings by cause before severity: (a) setup or input failures — rule 13; (b)
    library-model noise — findings inside behavioural macro models, standard-cell `specify`
    blocks and vendor primitives, an expected floor to waive once with the model named; (c)
    findings in the RTL itself, which are the ones the levels in rules 1–2 apply to. A flow
    wrapper's non-zero exit is not "lint failed": a wrapper may gate on log text and fail a run
    in which the lint tool reported 0 errors. Read the tool's own error count
15. Front-end check: lint does not prove the downstream front-end accepts the RTL. Verilator,
    slang and every simulator read SystemVerilog natively; a flow that converts the RTL before
    synthesis (sv2v, Surelog/UHDM, a vendor SV-to-Verilog step) produces a file none of them
    read. Where any downstream flow does that, run the conversion over the filelist and parse
    its output with the consuming tool:
    `sv2v <files> > out.v && yosys -q -p 'read_verilog out.v; hierarchy -check -top <top>'`
    (read rule 8 stubs first with `read_verilog -lib <stubs>`). Report it as its own gate with
    the command and exit status. A construct legal in SystemVerilog and illegal in Verilog-2005
    (IEEE 1364) — a part-select on a function-call result, `f(x)[N-1:0]`, is the canonical
    case; assign the result to a named signal and select from that — passes lint and the whole
    regression and fails only here. Fix the source construct, never the converted file. No
    conversion tool available: report the gate NOT RUN

### QoR Metrics to Evaluate
- Rule check completed: must be true — an aborted run has no ERROR count
- Front-end check, where a downstream flow converts the RTL: exit 0 with no parse error
- ERROR count: must be 0 before proceeding
- WARNING count: review all; waive with documented justification
- All RTL files checked (not just top-level)

### Output Required
- Lint report (per file, per rule)
- Unverified-claims entries: every finding labelled `UNVERIFIED` under rule 9, appended to the
  unverified-claims list in this stage
- Waiver file
- Clean lint summary
- Front-end check: conversion and parse commands with exit status, or NOT RUN and why

---

## Stage: cdc_rdc_analysis

### CDC Rules
1. Every CDC crossing: approved synchroniser primitive
2. Single-bit control: 2-FF synchroniser minimum
3. Multi-bit data: async FIFO or handshake protocol
4. Pulse crossings: pulse stretcher + synchroniser
5. Zero CDC violations (unwaived) before proceeding
6. No CDC tool available: the stage is NOT RUN, not PASS. Every crossing you reasoned about
   instead is an `UNVERIFIED` `cdc` (or `reset`) claim — append one entry per crossing to the
   unverified-claims list in this stage, naming the synchroniser you relied on. Downstream
   formal and verification can then check each one

### RDC Rules
1. All reset domains explicitly defined in constraints
2. Reset de-assertion: synchronous to receiving clock domain
3. No combinational logic between reset sources
4. Retention registers: correct UPF annotation

### QoR Metrics to Evaluate
- CDC violations (unwaived): 0
- RDC violations (unwaived): 0
- All clock domains verified in tool constraints

### Output Required
- CDC/RDC report
- Unverified-claims entries for every crossing not closed by a tool run (rule 6)
- Synchroniser instance list
- Waiver file

---

## Stage: synth_check

### Domain Rules
1. Run synthesis at target frequency with typical corner
2. Check for unmapped cells (technology library gaps)
3. Identify critical paths — report to architect if WNS < −0.5 ns
4. Check area vs microarch estimate (< 120% acceptable)
5. Check for multi-driven nets or unresolved X
6. Flag high-fanout nets needing buffering strategy
7. Verify all clock definitions synthesise correctly
8. Use the front-end the downstream flows use. If PD or synthesis reads sv2v output, run
   synth_check on sv2v output, not through a SystemVerilog-native front-end (Surelog, slang
   plugin) that accepts constructs the real flow rejects
9. A parse or elaboration error is not a QoR result: fix the source construct in
   `rtl_coding` (`lint_check` rule 15). A black box (undefined module) that resolves to
   first-party RTL is a missing source-list entry (`design_input_check` rule 8); one with no
   first-party RTL is a missing library or macro view — escalate as `input_setup`

### QoR Metrics to Evaluate
- Front-end parse and `hierarchy -check`: no error, no undefined module
- WNS at target frequency: > −0.5 ns acceptable at this stage (sign-off target: `design_state.constraints.timing.wns_ns_target`, default: 0)
- Area: < 120% of microarch estimate
- No unmapped cells
- No multi-driven nets

### Output Required
- Synthesis area report
- Timing report (critical paths)
- Recommendations for RTL fixes if needed

---

## Stage: rtl_signoff

### Sign-off Checklist
- [ ] All modules from planning implemented
- [ ] Lint: 0 errors, all warnings reviewed
- [ ] CDC: 0 unwaived violations
- [ ] RDC: 0 unwaived violations
- [ ] Synthesis check: WNS within acceptable range
- [ ] All ports connected in integration
- [ ] SVA assertions in place for key properties
- [ ] Code review completed; any CDC, reset or protocol conclusion not closed by a tool run is recorded as `UNVERIFIED`
- [ ] File list and compile order documented
- [ ] Every module in every tool's source list (simulation, lint, synthesis, PD, formal), or exempted with a reason
- [ ] Converted RTL parses in each downstream front-end (front-end check), or the gate is reported NOT RUN
- [ ] ICG cells inserted for all high/moderate gating opportunity domains
- [ ] Always-on domains annotated with `/* always-on: <reason> */`
- [ ] `clock_gating_coverage` ≥ `design_state.constraints.power.gating_coverage_pct_min`% for high-opportunity domains (default: 60%); reported in sign-off record

### Output Required
- RTL file package (all .sv files)
- File list (filelist.f)
- Compile order document
- Assertion library (.sva files)
- RTL sign-off record
- Unverified-claims list: every `UNVERIFIED` conclusion from code review, lint and CDC, one
  entry per claim as `{module, category, claim}` with `category` one of `cdc`, `reset`, `fsm`,
  `protocol`, `arithmetic`, `parameter`. Include one `fsm` entry for every FSM that uses
  `unique case` without `default`, naming its recovery assertion. This list is the hand-off to
  verification and formal — a claim left off it is a claim nobody downstream will check. An
  empty list must be stated as empty, not omitted. The list is built up by `rtl_coding`,
  `lint_check` and `cdc_rdc_analysis` as each stage reaches its conclusions; this stage
  completes it. It is handed off on every termination path, including a run that stops
  before this stage or withholds signoff — a run that never reaches sign-off still hands over
  every claim it made

---

## Constraint Validation

See `plugins/meta/skills/pipeline-orchestration/SKILL.md` §Constraints Schema for the authoritative schema and stage-entry validation rule.

**Required at entry (`module_planning`) — hard-fail if missing:**
- `constraints.clock.clk_mhz` — target frequency for synth_check timing evaluation

**Optional (schema defaults apply when absent):**
- `constraints.timing.fanout_max` (default: 32) — high-fanout threshold
- `constraints.timing.wns_ns_target` (default: 0) — WNS sign-off target
- `constraints.power.gating_coverage_pct_min` (default: 60%) — ICG coverage target
- `constraints.power.activity_factors` (defaults: `{default: 0.15, high: 0.40}`) — domain classification

---

## Memory

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
write or overwrite one JSON record in `memory/rtl-design/experiences.jsonl` keyed by
`run_id`. This ensures data is persisted even if the flow is interrupted or called
without full orchestrator context.

Use `run_id` = `rtl-design_<YYYYMMDD>_<HHMMSS>` (set once at flow start; reuse on each
stage update). Set `signoff_achieved: false` until the final sign-off stage completes.
### Run state (write before first stage, update after each stage)
Write `memory/rtl-design/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:      rtl-design_<YYYYMMDD>_<HHMMSS>
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
applied fix as an observation to entity `chip-design-rtl-design-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.

### Optional: hdl-rtl-skill
If the `hdl-rtl-skill` skills (`rtl-style-guide`, `rtl-golden-templates`, `rtl-anti-patterns`,
`rtl-review-signoff`, `rtl-workflow`) are available in this session, use them alongside this
skill: its `rtl-lint` script as the slang runner at `lint_check` (it applies rules 6–8 and
reports the severities mapped by rule 11), its golden templates as the starting point at
`rtl_coding` for FIFOs, synchronisers, arbiters, FSMs and ready/valid stages, and its
anti-pattern catalogue during code review. The rules in this file are the project standard
its style guide defers to, so where the two differ — clock/reset naming, `_i`/`_o` — follow
this file. Skip silently if it is absent — every rule above stands on its own.
