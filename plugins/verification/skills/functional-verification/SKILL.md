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
with documented coverage and a clean regression. Also guides **port mode**: bringing an
existing, passing testbench up on another simulator (`simulator_portability`), and reviewing
coverage holes without closing them (`coverage_analysis` report-only mode).

---

## Supported EDA Tools

### Open-Source
- **Verilator** (`verilator`) — fast cycle-accurate simulator; UVM support via verilator+UVM
- **Icarus Verilog** (`iverilog`) — event-driven simulation for quick testbench checks
- **cocotb** — Python-based co-simulation framework (`pip install cocotb`)
- **PyUVM** — UVM implementation in Python for cocotb environments
- **UVVM** — VHDL verification methodology library

### Proprietary
- **Synopsys VCS** (`vcs`, dialect `synopsys`) — industry-standard SV/UVM simulator
- **Cadence Xcelium** (`xrun`, dialect `cadence`) — multi-language simulator with coverage engine
- **Siemens Questa** (`vsim` / `vlog` / `vcom`, dialect `siemens`) — mixed-language simulation with UVM support
- **Synopsys URG** (`urg`, dialect `synopsys`) — merges and reports VCS `.vdb` coverage; wrapper `wrap-urg.sh`
- **Cadence IMC** (`imc`, dialect `cadence`) — merges and reports Xcelium `cov_work` coverage; wrapper `wrap-imc.sh`. Often off PATH, or not installed with Xcelium at all

cocotb runs on any of these through `SIM=` (see `simulator_portability`). Its makefile's exit code
is not a verdict on any simulator; `wrap-cocotb-results.sh` reads `results.xml`.

---

## Stage: simulator_portability

Entered only in **port mode** — an existing, passing testbench (cocotb or UVM) is brought up on a
simulator it has not run on (for example a Verilator-only cocotb regression moved to VCS and
Xcelium). The testbench and its checks are inputs, not artifacts this stage designs: the
`tb_architecture` → `constrained_random` stages do not run. The simulator the regression already
passes on is the **reference simulator**; its results are the baseline every new simulator is
compared against.

### Domain Rules — cocotb invocation
1. cocotb selects the simulator by `SIM`: `verilator`, `icarus`, `vcs`, `xcelium`, `questa`
   (the value is the makefile name under cocotb's `share/makefiles/simulators/`, so check
   `cocotb-config --makefiles` for the installed version). Pass flags through cocotb's own
   variables, never by editing cocotb's makefiles:

   | Variable | Reaches | Use for |
   |---|---|---|
   | `COMPILE_ARGS` | the compile/elaborate command | defines, include dirs, parameter overrides, timescale, access flags |
   | `EXTRA_ARGS` | compile and, on some simulators, elaborate | options the reference simulator already passes here (Verilator's `-G`, `-Wno-*`) — translate, do not copy |
   | `SIM_ARGS` | the run command | run-time options (`-licqueue`, coverage run flags) |
   | `PLUSARGS` | the run command, as `+arg` | test plusargs (`+SEED=`, `+UVM_TESTNAME=`) |
   | `SIM_BUILD` | build directory (default `sim_build`) | one directory per simulator, rule 6 |

   cocotb 2.x renamed `MODULE`/`TOPLEVEL` to `COCOTB_TEST_MODULES`/`COCOTB_TOPLEVEL`; read the
   names from the installed version rather than assuming either
2. Read the `COMPILE_ARGS`/`EXTRA_ARGS` that cocotb's `Makefile.<sim>` already supplies
   (`make -n SIM=<sim>`) before adding any: cocotb passes its own VPI-load and debug flags, and a
   duplicate is at best noise. **Never set `EXTRA_ARGS` on the `make` command line for
   `SIM=xcelium`**: a command-line variable overrides every makefile assignment, so it silently
   discards cocotb's own `EXTRA_ARGS +=` in `Makefile.xcelium`, which carries `-top`,
   `-xmlibdirpath` and `-licqueue` (observed). Translate the reference value inside the shared
   include into a separate variable (or `override undefine EXTRA_ARGS` there, then append), and
   confirm with `make -n` that cocotb's own flags are still present

### Domain Rules — Translating Verilator-only idioms
3. Translate every reference-simulator flag through this table. A flag with no row is
   investigated and added to the table in the stage output, never passed through untranslated:

   | Verilator | VCS | Xcelium (`xrun`) |
   |---|---|---|
   | `-G<P>=<v>` (top-level parameter) | `-pvalue+<top>.<P>=<v>` | `-defparam <top>.<P>=<v>` |
   | `-G<P>='"str"'` (string parameter) | `-pvalue+<top>.<P>=\"str\"`, escaped once more for the recipe's `sh` (else `Warning-[PRM_ILLG]` and the value is ignored) | **not `-defparam`** — `xrun` ignores it for a string parameter (`*W,BDDSTR ... ignored`, observed); generate an extra top module holding `defparam <top>.<P> = "str";` and add it as a second `-top` |
   | `+define+X=1`, `-DX=1` | `+define+X=1` | `+define+X=1` (or `-define X=1`) |
   | `-I<dir>`, `+incdir+<dir>` | `+incdir+<dir>` **and** `-y <dir> +libext+.sv+.v` | `+incdir+<dir>` (or `-incdir <dir>`) **and** `-y <dir> +libext+.sv+.v` |
   | `--timescale 1ns/1ps` | `-timescale=1ns/1ps` | `-timescale 1ns/1ps` |
   | `--timescale-override ...` | `-override_timescale=1ns/1ps` | `-override_timescale 1ns/1ps` |
   | VPI signal access (implicit with `--public-flat-rw` / `--vpi`) | `-debug_access+all` (or `+acc`) | `-access +rwc` |
   | `-Wno-*`, `-Wall`, `-Wno-fatal`, `--lint-only` | drop | drop |
   | `--trace`, `--trace-fst`, `--trace-structs` | drop (waves via `-debug_access` + UCLI/FSDB only when asked) | drop (`-access +r` + SHM probe only when asked) |
   | `--x-assign`, `--x-initial` | drop — **changes semantics, rule 10** | drop — **changes semantics, rule 10** |
   | `--coverage`, `--coverage-line`, `--coverage-toggle` | replace with `-cm ...` (`coverage_analysis`) | replace with `-coverage ...` (`coverage_analysis`) |
   | `-O0`..`-O3`, `--threads N`, `-j N`, `--build`, `--exe` | drop | drop |

   Quoting a string parameter goes through make *and* the shell; prove each override took effect
   by reading the parameter back in the smoke run (`dut.<P>.value` in cocotb, or a `$display`)
   and comparing it with the reference simulator's value — a mis-quoted string silently becomes
   the default. **Any parameter-override warning (`PRM_ILLG`, `BDDSTR`, "parameter not found",
   "ignored") is a FAIL of the translation, not noise**: the run that follows simulated the
   default value. Verilator's `-I` also resolves *modules* by file name, so a filelist can omit a
   module and still build on Verilator; map `-I` to the library search (`-y`/`+libext+`) as well
   as `+incdir+`, or — better — add the missing file to the filelist and record which modules
   were found only by search. Add a VPI access flag only when a test fails to find a signal (cocotb
   `AttributeError` on a handle) under cocotb's own default, and record which signal needed it
4. **One shared make include, not per-target edits.** Put the whole translation in one file
   (e.g. `sim_portability.mk`) that every test makefile includes, with every rule guarded on
   `SIM` (`ifeq ($(SIM),vcs)` … `else ifeq ($(SIM),xcelium)` …). A per-target copy drifts: the
   tenth makefile edited is the one that misses a define
5. **The reference simulator's command lines stay byte-identical.** Before the include is added,
   capture `make -n SIM=<reference> <target>` for every target into `before/<target>.txt`; after,
   capture the same into `after/`, and compare with `cmp -s` (exit 0 per file). Any difference is a
   FAIL of this stage until explained and accepted by the user — not `diff` output read by eye,
   and not a filtered diff, which can report changed files as identical. Where the reference
   simulator is not installed on the porting host, use `make -n -i` with a stub executable of the
   same name first on `PATH` (Verilator's build recipe runs `make -C` even under `-n`), and
   normalise make's own `Makefile:NNN:` line numbers in its warnings (`sed -E
   's/(Makefile[^:]*):[0-9]+:/\1:N:/'`) in both captures before `cmp`; say in the output that the
   proof used a stub. Parity of the command lines is not parity of the result: before handing a
   port back, run the reference simulator's lint and regression at the version CI executes (read it
   from the CI log or lockfile, not a comment). A testbench or model edit made for the new simulator
   can fail a lint rule that only a newer reference release has (`PROCASSINIT` in Verilator 5.048)
6. **One `SIM_BUILD` per simulator** (`sim_build_vcs`, `sim_build_xcelium`), set inside the
   `SIM`-guarded branches so the reference simulator keeps its existing directory (rule 5). A
   shared directory lets one simulator's stale objects or `results.xml` be read as the other's
7. **A `verilator --lint-only` prerequisite is skipped or replaced, never counted.** Where a make
   target runs Verilator lint before simulating, guard it on `SIM=verilator`, or replace it with
   the target simulator's compile as the gate. Report lint as NOT RUN for that simulator — a lint
   step that ran under another simulator's name is not evidence that the RTL compiles clean there.
   The same holds for every **Verilator-only test**: elaboration-guard checks (a parameter value
   that must fail to elaborate), `*_neg` targets and lint-based tests inside suites. List each one
   by name as NOT RUN for the commercial simulator, and account for them explicitly against any
   pass floor (`expected = reference_passed − not_run_verilator_only`). Never drop them silently,
   and never count them as passed
8. **Resolve the simulator from a non-interactive shell.** A user alias (`alias vcs 'vcs -full64'`
   was observed) does not exist inside `make`; write `-full64` into the VCS compile arguments
   explicitly, and record the binary path `command -v vcs` resolved to

### Domain Rules — Triage
9. **LRM strictness: classify before changing anything.** An error from VCS or Xcelium on code
   Verilator accepted is one of:
   - **RTL defect** — the RTL violates IEEE 1800 (use before declaration, multiple drivers on a
     variable, an `always_ff` variable also written elsewhere, a missing `automatic` on a
     recursive function, an implicit net). Cite the LRM clause. Write a `fix_request`
     (`failure_class: functional`) routed to RTL and escalate per Behaviour Rule 4 — **never** a
     testbench, define or flag workaround (`+define+` hack, `-error=noFOO`, `+lint=none`,
     `-nowarn`/`-ignore` on an error) that makes the RTL compile. "Verilator accepts, the LRM
     rejects" is this class, not a dialect: observed cases are use before declaration (an
     implicit net later re-declared, an `always_ff` reading a `logic` declared further down) and
     a variable written by `always_ff` that also has a declaration initialiser or an `initial`
     write — LRM 9.2.2.4, VCS error `ICPD`. The compiler message names file and line, so the
     `fix_request` carries `suspected_rtl.basis: traced`
   - **Testbench defect** — the same LRM test applied to testbench or bind code: fix the
     testbench, keeping every check at least as strict (`directed_tests` rule 9)
   - **Tool dialect** — legal code the simulator rejects, or an option it spells differently:
     add the vendor flag to the shared include with the reason and the vendor's message ID in a
     comment
   Record every compile message the stage acted on with its class, evidence and owner
10. **Simulator semantics differences are root-caused, never absorbed.** A test whose result
    differs between simulators is a FAIL until its cause is named and recorded in
    `sim_differences` (test, per-simulator result, mechanism, class, owner). Look first at:
    - **X-propagation / initialisation** — Verilator is 2-state and `--x-assign`/`--x-initial`
      zero or randomise unknowns; VCS and Xcelium start uninitialised variables at `X`. A
      register read before reset, or a missing reset, passes on Verilator only. A missing reset
      the spec requires is an RTL defect (rule 9); a testbench reading before reset is a TB defect
    - **Scheduling races** — Verilator is not a full event-driven scheduler. A testbench that
      drives and samples on the same edge passes on one simulator by ordering luck: drive on the
      opposite edge or after `ReadOnly()`/`NextTimeStep()`; a race inside the RTL is an RTL defect
    - **Random seeding** — `$random`/`$urandom` and Python `random` sequences differ per
      simulator and per seed handling; record the seed (`RANDOM_SEED`, `+ntb_random_seed`,
      `-svseed`) for every failing test so it reproduces
    - **4-state vs 2-state values — the dominant first-contact failure class.** An undriven
      top-level input, or a register or memory word never written, reads `0` on Verilator and `X`
      on VCS/Xcelium; `int(handle.value)` then raises. Stimulus that relied on the `0` is a
      **testbench defect**: drive every DUT input to a defined value during reset/setup, and treat
      a Verilator pass that depends on an `X` reading as `0` as non-portable, not as passing.
      Observed: an instruction encoding whose immediate overlapped the `rs2` field selected a
      register the test never wrote. Fix the cause of the `X`; never resolve it away
      (`COCOTB_RESOLVE_X`, masking with `& mask`) to make the test pass — that is weakening the
      check (Behaviour Rule 11)
11. **Known-harmless VCS + cocotb log lines are not failures.** `ERROR gpi ... Unable to register
    a callback handle ... cbStartOfSimulation` / `cbEndOfSimulation` with `Warning-[VPI-CT-NS]`
    (from cocotb's compile-time `-load`), `DEBUG_DEP` and `DBGACC_DBG`/`DBGACC_CMB` (cocotb passes
    both `-debug` and `-debug_access`), and the `VCS_SAVE_RESTORE_INFO` ASLR note are expected.
    Never grep a simulation log for `ERROR` to decide pass/fail — `results.xml` is the verdict
    (rule 12)

### Domain Rules — Pass/fail and scope
12. **Pass/fail comes from `results.xml`, never from `make`'s exit code.** cocotb 1.9.2's makefile
    was observed exiting 0 with failing tests on both VCS and Xcelium. Delete stale `results.xml`
    before each run (or pass `--newer-than` a stamp file), then read every run through
    `wrap-cocotb-results.sh <results.xml|SIM_BUILD dir>...`: it counts testcases, failures, errors
    and skipped, and reports FAIL for any failure or error, for zero testcases, and for a missing,
    empty or unparsable `results.xml`
13. **Negative control before trusting any PASS.** On each simulator, inject one known-failing
    check — a single `assert False, "negative control"` test, or one deliberately wrong expected
    value — run it, and confirm `wrap-cocotb-results.sh` reports FAIL with exactly that test in
    `errors`. Remove it and confirm the count returns. A simulator whose pipeline cannot report
    a FAIL has not demonstrated any PASS
14. **Staged scope.** (a) Compile every test module on each new simulator; (b) run a smoke
    subset — at least one test per test module, P0 tests first — on the reference and each new
    simulator, and triage to zero unexplained differences; (c) only then the full regression on
    each new simulator, backgrounded and sharded per Behaviour Rule 13 of the orchestrator. Never
    launch the full regression on a simulator whose smoke subset has an untriaged failure
15. **Skips must match the reference.** The set of skipped testcase names on each new simulator
    equals the reference simulator's set. A test skipped only on the new simulator is a FAIL unless
    its skip condition is recorded with the reason (a simulator-specific feature); a test skipped
    only on the reference is reported too. Compare test **names**, not counts — equal counts can
    hide a swapped pair
16. **License and resources before launch** — see `regression_signoff` rules 1–3; they apply to
    the smoke and full runs of this stage
17. **One results file per run, and serialise what cannot be separated.** A rollup target that
    runs several test modules in one invocation writes one `results.xml`, so only the last
    module's results survive; concurrent jobs sharing a directory clobber `results.xml`,
    `ucli.key` and `xrun.log`. Give each target its own results file (`COCOTB_RESULTS_FILE`, or
    `SIM_RESULTS_IN_BUILD` where the installed cocotb supports it) and its own `SIM_BUILD`;
    anything that cannot be relocated runs serially. Check the summed testcase count of every
    `results.xml` against the reference's — a shortfall is a collision until shown otherwise
18. **Hierarchy access through one helper, not per-test hacks.** VPI names differ between
    simulators: VCS exposes generate-block children as flattened names (`"g_aes.u_aes"` as one
    child) and a packed-struct port as a scope of members with no `.value`; Xcelium differs from
    both and from Verilator. Put every lookup a test makes below the toplevel through one helper
    that tries the dotted path, then the flattened name, then the parent signal with a slice,
    and records which form each simulator needed. A per-test `try/except` hides which form
    worked and diverges between tests
19. **UTF-8 locale for every run.** cocotb's logging raises `UnicodeEncodeError` on a non-ASCII
    test docstring unless the environment has a UTF-8 locale; export `LANG`/`LC_ALL` as
    `C.UTF-8` (or `en_US.UTF-8`) in the run environment, not only in an interactive shell

### QoR Metrics to Evaluate
- `reference_cmdlines_identical`: `true` — every target's `make -n SIM=<reference>` output
  byte-identical before/after (`cmp -s` exit 0)
- `compile_errors_per_sim`: 0 for every simulator
- `negative_control_detected`: `true` for every simulator
- `smoke_pass_pct`: 100 % per simulator, or every failure classified in `sim_differences`
- `testcase_count_delta`: 0 — same testcase names collected on every simulator
- `skip_set_match`: `true` per simulator (rule 15)
- `unexplained_sim_differences`: 0
- `lint_counted_as_compile`: 0 — no Verilator lint step reported as another simulator's compile
- `param_override_warnings`: 0 per simulator (rule 3)
- `verilator_only_not_run`: listed by name and subtracted from the pass floor, never counted as passed (rule 7)

### Common Issues & Fixes
| Issue | Fix |
|---|---|
| `make` exits 0, tests failed | Read `results.xml` with `wrap-cocotb-results.sh` (rule 12) |
| String parameter becomes its default | Fix quoting through make and the shell; read the value back (rule 3) |
| Signal handle not found on VCS/Xcelium only | Add `-debug_access+all` / `-access +rwc` for that scope, record it |
| Test passes on Verilator, `X` on VCS/Xcelium | Missing reset or read-before-reset: rule 10, RTL or TB defect |
| Xcelium job hangs at start | `-licqueue` waiting for a seat: run under `timeout`, check `lmstat` |
| `vcs: command not found` inside make, works by hand | User alias; call the binary and add `-full64` (rule 8) |
| `*W,BDDSTR ... ignored` on `xrun` | String parameter: generated `defparam` top module, not `-defparam` (rule 3) |
| `Warning-[PRM_ILLG]` on VCS | `-pvalue+` string mis-escaped for the recipe shell (rule 3) |
| Xcelium loses `-top` / `-licqueue` | `EXTRA_ARGS` given on the make command line (rule 2) |
| Module not found on VCS/Xcelium, builds on Verilator | Missing from the filelist, found by Verilator's `-I` search (rule 3) |
| `ICPD` error on VCS | `always_ff` variable also initialised or written in `initial`: RTL defect (rule 9) |
| Fewer testcases than the reference | `results.xml` overwritten by a rollup or a concurrent job (rule 17) |
| `UnicodeEncodeError` in cocotb logging | No UTF-8 locale (rule 19) |

### Output Required
- The shared make include (`sim_portability.mk` or equivalent) and the translation table it implements
- `before/` and `after/` `make -n` captures with the `cmp -s` result per target
- Per-simulator `wrap-cocotb-results.sh` JSON for the negative control, the smoke subset and the full run
- Triage log: every acted-on compile message with class (RTL / TB / dialect), evidence and owner
- `sim_differences` record: one entry per test whose result differs between simulators
- Skip-set comparison per simulator against the reference

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

### Collecting and Merging Code Coverage
| Simulator | Compile | Run | Scope | Merge + report | Exclusions |
|---|---|---|---|---|---|
| VCS | `-cm line+cond+fsm+tgl+branch+assert -cm_dir <db>.vdb` | same `-cm` metrics, `-cm_dir <db>.vdb -cm_name <test>_<seed>` | `-cm_hier <file>`: `+tree <dut_top>` / `-tree <tb_wrapper>` / `-module <model>`, or a leading `+filelist <rtl.f>` when there are many testbench tops (rule 5) | one top: `wrap-urg.sh -dir a.vdb b.vdb ... -dbname merged -report <dir> -format both`; databases from **different testbench tops**: add `-lca -flex_merge modules` (rule 6) | `urg -elfile <file>.el` |
| Xcelium | `-coverage all` (or `-coverage b:e:f:t:u`) | `-covworkdir <dir> -covscope <scope> -covtest <test>_<seed> -covoverwrite` | `-covfile <file>.ccf` (`select_coverage -all -instance <dut_top>...`, `deselect_coverage` for TB/models) | `wrap-imc.sh -execcmd "merge <dir>/<scope>/* -out merged; load -run merged; report -summary -metrics overall"` | vRefine file (`.vRefine`) loaded in IMC before the report |
| Verilator | `--coverage-line --coverage-toggle` (and `--coverage-user` for SVA cover) | writes `coverage.dat` per run (`+verilator+coverage+file+<test>.dat`) | `/*verilator coverage_off*/` … `coverage_on` or `--coverage-max-width` | `verilator_coverage --write-info merged.info a.dat b.dat ...` (lcov), `--annotate <dir>` | `--write` after filtering in the `.info`; record each filter |

`wrap-urg.sh` parses `dashboard.txt`, so pass `-format text` (or `both`). `wrap-imc.sh` parses
IMC's stdout, so the report command carries no `-out`. Where `imc` is absent (recorded as a
coverage-reporting gap by infrastructure `tool_discovery`), Xcelium coverage can still be
collected into `cov_work/**/*.ucd` but not merged or reported: record the metric as NOT RUN
for that simulator, never as 0 % and never as a coverage FAIL.

### Domain Rules — Coverage mechanics
1. **Scope coverage to the design.** Exclude testbench wrappers, bind/checker modules, behavioural
   memory and simulation models, and cocotb's own toplevel shims from the coverage scope at
   compile time (`-cm_hier` / `-covfile`), not by filtering the report afterwards. Including them
   inflates the denominator with code no test is meant to cover and hides real holes
2. **Unique per-test database names in parallel runs.** Give every test and seed its own name
   (`-cm_name <test>_<seed>`, `-covtest <test>_<seed>`, `+verilator+coverage+file+<test>_<seed>.dat`).
   Two jobs writing the same name **overwrite silently**: the merged report then counts one of
   them and the run shows no error
3. **Merge every per-test database before reporting.** A report of one test's database is that
   test's coverage, not the regression's. Record the number of databases merged and check it
   against the number of tests that ran (`urg` prints `Number of tests:`)
4. **Exclusions are waivers.** Every exclusion-file entry carries the reason and is listed in the
   waiver file (approval per QoR below); an exclusion added to raise a number is a moved
   target (Stage Gating item 7)
5. **Scope a many-top regression by file list, not by tree.** A cocotb regression usually has one
   testbench top per suite, so `+tree <dut_top>` has to be repeated per build and still lets the
   wrapper of every other build in. Give each build a `-cm_hier` file whose first rule is
   `+filelist <the design files this build compiles>`: the first `+` rule turns the file into an
   include list, so everything not listed (testbench wrappers, cocotb glue, simulation models) is
   excluded at compile time. Generate the list from the build's own source list, not by hand
6. **Merging databases from different testbench tops needs `urg -lca ... -flex_merge modules`.**
   Plain `urg -dir a.vdb b.vdb ...` keeps the design of the **first** database as the base and
   silently drops design that only the others contain; measured on VCS Y-2026.03, a two-database
   merge lost a whole module from the report with no error or warning. `-flex_merge modules`
   merges by module definition and is a limited-availability feature, so it needs `-lca`. Report
   coverage per module definition from such a merge; the instance-hierarchy view is per
   testbench and cannot be summed across tops
7. **An all-`--` summary is not a result.** When the scope file excludes everything, or the
   `-cm` flags did not reach the compile, `urg` still exits 0 and writes a dashboard whose every
   metric is `--`. Treat that as NOT RUN and fix the instrumentation; `wrap-urg.sh` reports it as
   an unverified WARN. Also check that the merged `Number of tests:` equals the number of
   simulations that ran. Note that `urg -f <file>` does not accept `-dir` inside the file: pass
   the databases on the command line or with `-dir` repeated
8. **Hole counts do not carry over between simulators.** VCS counts each generate-loop iteration's
   lines and branches separately (Verilator reports them once), and VCS honours neither Verilator
   `/*verilator coverage_off*/` pragmas nor a Verilator-side waiver file: every arm waived there
   reappears as a hole. Before comparing numbers or ranking holes, translate the existing waivers
   into the simulator's exclusion format (`urg -elfile`, IMC vRefine), or list the re-surfaced
   items separately as "waived on <reference simulator>" instead of as new holes

### Report-only mode
When the user asks to **review** coverage holes rather than close them (`coverage_mode:
report_only`, set by the orchestrator per its Behaviour Rule 14):
1. Collect, merge and report as above; do **not** write tests, constraints or waivers, and do not
   take the `coverage_analysis` loop-backs (line < 95 % → `directed_tests`, functional < 100 % →
   `constrained_random`) — the stage result is the report
2. Rank the holes, highest first: FSM states and transitions never reached; error, `default` and
   illegal-state branches; reset, flush and abort paths; CDC and synchroniser paths; then other
   branches, conditions, toggles and lines. Within a class, rank by the size of the uncovered block
3. For each hole give the file and line (or FSM state/arc), the metric, and either a proposed test
   (stimulus that would reach it, in one or two sentences) or a proposed waiver with its
   justification (unreachable by construction, tied-off parameter, debug-only logic). Write no
   test unless the user then asks
4. Coverage below target in this mode is reported as WARN with `failure_class: coverage_gap`, not
   FAIL, and never sets sign-off

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
- Coverage report (merged across all seeds and tests), with the number of databases merged
- Uncovered bin list with closure plan — or, in report-only mode, the ranked hole list with a proposed test or waiver justification per hole
- Waiver file (closure mode only)
- Coverage scope file (`-cm_hier` / `-covfile`) and exclusion files used

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

### Domain Rules
1. **License checkout smoke before the regression.** On each proprietary simulator, compile and
   run a trivial module (or one real smoke test) under `timeout 300` immediately before launching
   — `vcs -ID` and `xrun -version` check out nothing, and VCS takes a separate runtime feature
   when `simv` starts. Xcelium launched by cocotb passes `-licqueue`, so a missing seat **hangs**
   instead of failing: a timeout expiry is a license problem, not a slow test. Reuse the
   infrastructure `environment_validation` smoke result only if it ran in this session
2. **Bound parallel jobs** at `min(cores, floor(free_RAM / per-job peak RSS), free license seats)`
   and record the value and its limiting term in the regression report and `run_state.md`. Take
   the terms from infrastructure `tool-manifest.json` `regression_resources` when present, else
   measure them (`nproc`, `MemAvailable`, peak RSS of the smoke run, `lmstat` free seats). A
   job count above the seat count queues or fails jobs that then look like test failures
3. **Put `SIM_BUILD` and coverage databases on a filesystem with room.** Check `df -P` on the
   target directory before launch; require free space ≥ jobs × per-job build size from the smoke
   run (`du -s`). Route builds to a scratch filesystem when the project disk is short
4. **Verdict from `results.xml`.** Every run's pass/fail is `wrap-cocotb-results.sh` over that
   run's `results.xml` files (cocotb) or the simulator's own test report (UVM) — never `make`'s
   exit code and never a grep for `ERROR` in a simulation log. A missing or empty `results.xml`
   is a FAIL of that shard, not a skip. Run the negative control (`simulator_portability` rule 13)
   on any simulator whose pipeline has not demonstrated a FAIL in this session
5. **Long regressions run in the background, sharded, with progress checkpointed.** Split the
   test list into shards no larger than the job bound, give each shard its own `SIM_BUILD` and
   log, launch in the background, and after each shard completes record in
   `memory/verification/run_state.md` (see Memory below) the shard id, simulator, command,
   `results.xml` path, and the `wrap-cocotb-results.sh` counts. A resumed session reads
   `run_state.md`, skips shards marked complete and re-launches only pending or failed ones —
   it never restarts a regression from the beginning. **Waiting costs turns**: launch each shard
   with the agent runtime's background-job facility and act on its completion notification; where
   there is none, wait with one bounded blocking command per turn
   (`timeout 1800 bash -c 'while ! test -s <results.xml>; do sleep 30; done'`), never repeated
   short status polls. A ~24-suite smoke exhausted an 80-turn budget through polling

### Pass Criteria
- 0 simulation failures (excluding waived known bugs)
- 0 UVM FATAL or UVM ERROR messages
- All coverage targets met (see `coverage_analysis` targets; driven by `design_state.constraints.coverage.*`)
- Formal: all P0 properties proven
- All P0/P1 bugs: closed

### QoR Metrics to Evaluate
- `regression_failures`: 0 (sum of `failures` + `errors` from `wrap-cocotb-results.sh` across all shards)
- `shards_complete`: equal to `shards_total`
- `max_parallel_jobs`: recorded with its limiting term (cores / RAM / license seats)
- `license_smoke_passed`: `true` per proprietary simulator used

### Output Required
- Regression pass/fail report (per simulator, per shard, from `results.xml`)
- Final merged coverage report
- Open bug list
- Sign-off checklist
- Job-bound and license-smoke record

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
This applies to every task invocation, including a scoped single-stage task (for example "only
run the coverage report"): the end of the task is the end of a run, and it gets a record. When a
later result in the same task invalidates one already recorded, the upsert replaces the record and
its `notes` say what was superseded and why; when the invalidated result belongs to an earlier
run, write this run's record with `supersedes: <earlier run_id>` and leave the earlier record
untouched.
### Run state (write before first stage, update after each stage)
Write `memory/verification/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:      verification_<YYYYMMDD>_<HHMMSS>
design_name: <design>
tool:        <primary tool>
start_time:  <ISO-8601>
last_stage:  <first stage name>
mode:        full | port | report_only_coverage
simulators:  <reference>, <new sim>, ...
job_bound:   <N> (limited by cores | ram | license_seats)
shards:
  - id: <sim>_<nn>   status: pending | running | complete | failed
    cmd: <launch command>   log: <path>   results: <results.xml path or dir>
    counts: tests=<n> failures=<n> errors=<n> skipped=<n>
```
Update `last_stage` after each stage completes, and the shard entry each time a shard is
launched or finishes. This file lets wakeup-loop prompts
and resumed sessions identify the correct run without relying on in-memory state.
Create the file and parent directories if they do not exist.

### Optional: claude-mem index
If `mcp__plugin_ecc_memory__add_observations` is available in this session, emit each
applied fix as an observation to entity `chip-design-verification-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.
