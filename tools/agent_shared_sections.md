# Shared orchestrator sections

This file is the single source for the sections that every orchestrator carries
word for word. Edit the text here, then run:

    python3 tools/sync_agent_sections.py

The script writes each block into its targets between `BEGIN SHARED` / `END SHARED`
marker comments. CI runs `python3 tools/sync_agent_sections.py --check` and fails
when a target has drifted, so do not edit the text between the markers by hand.

Blocks are inserted immediately before the next `## ` heading that follows the
heading matched by `after`. Agents are named by their directory under `plugins/`.
Domain-specific rules stay in the agent files themselves; only text that is
identical everywhere belongs here.

<!-- BLOCK execution-direct
targets: agents
only: compiler, firmware
after: ^## Tool Options$
-->
### MCP Preference
No MCP server or wrapper script exists for this domain's toolchain (cross-compilers,
assemblers, linkers, debuggers, emulators). Do not route these tools through the EDA wrappers
in `plugins/infrastructure/tools/` — they parse EDA logs, not compiler or test output. Use
direct execution:
1. Redirect stdout and stderr of every build, test, or emulator run to a log file and record
   the exit code.
2. Read summaries, not raw logs: the exit code, the final summary lines, and a targeted search
   for `error`, `warning`, `FAIL`, `undefined reference`. Open the full log only around a
   reported failure.
3. For a hardware or emulator run, capture the target's console output to a file the same way.
   A session you watched but did not capture is not evidence.
<!-- END BLOCK execution-direct -->

<!-- BLOCK failure-classification
targets: agents
except: meta
after: ^## Behaviour Rules$
-->
## Failure Classification & Retry Strategy
Every `history[]` entry carries both fields. `failure_class` says *what* went wrong;
`retry_strategy` says *how* to recover and is **derived from it by this table, not chosen**.

| `failure_class` | `retry_strategy` |
|---|---|
| `none` | `none` |
| `functional` | `refine` |
| `timing` | `refine` |
| `power_area` | `refine` |
| `coverage_gap` | `refine` |
| `connectivity` | `refine` |
| `drc_lvs` | `regenerate` |
| `tool_error` | `regenerate` |
| `input_setup` | `escalate` |
| `spec_gap` | `escalate` |
| `resource_limit` | `escalate` |

- **regenerate** — discard the faulty artifact and re-run the *generating* stage from a clean
  slate, using the error log as context. Action is usually `retry_stage` or
  `loop_back_to:<generating stage>`.
- **refine** — keep the artifact and re-run the stage against a *specific* identified defect
  with detailed feedback (failing test plus waveform, timing path, coverage hole, violated
  interface). Iterative, not from scratch; usually `loop_back_to:<stage>` carrying a
  `fix_request`.
- **escalate** — halt and request human input: the result cannot be improved automatically
  (ambiguous spec), or a budget or cap was hit. Action is `escalate` or `abandon`.
- **none** — no failure. Pairs only with `failure_class: "none"` (PASS, `await_approval`).

`input_setup` means the tool ran correctly on the wrong inputs: a filelist, include path,
project or config file, generated header or library view that resolves to the wrong tree. It
is not `tool_error` — a retry reproduces it verbatim — and it is not evidence about the
artifact under check, which was never evaluated. Record it whenever the evidence points at
the input set (two paths named for one file, a file this run did not write, a check that
aborted before it ran), change nothing in the artifact, and escalate with the input to
repoint.

A FAIL or WARN that a Loop-Back Rules row sends to another stage records
`decision: "loop_back"`, not `"proceed"`. `"proceed"` means the stage's own result
allowed the flow to continue; `"escalate"` is terminal. The target stage is named by
`suggested_next_step: "loop_back_to:<stage>"`.

This table covers `history[]` entries only. A `fix_requests[]` entry uses its own smaller
enum (`functional | protocol | coverage_gap | formal_cex`) and always carries
`retry_strategy: "refine"` — do not look those classes up here, and do not force one of them
into a row above.

`retry_strategy` is the strategy *label* and `suggested_next_step` the concrete *action* —
complementary, not redundant. **Where they disagree, the stage-specific Loop-Back Rules row
wins** and `suggested_next_step` follows it: a row that says `proceed` on a WARN is not
overridden by a mapped `regenerate`, and a row that still has an iteration left is not
overridden by a mapped `escalate`. Record the mapped `retry_strategy` anyway, so the
disagreement stays visible in `history[]` instead of being resolved silently. Stage Gating and
Escalation items 4 and 7 are different in kind: they stop a loop on evidence (the fault is
upstream, or the retries are not converging), whatever the row still allows. `input_setup` is
the one class that does the same: no Loop-Back Rules row overrides it, because every row that
loops back sends the failure to a stage that edits the artifact, and the artifact is not what
is wrong.

Where a condition has **no** Loop-Back Rules row at all, there is nothing to defer to and no
class to map from. Do not invent a `failure_class` to manufacture one: record the stage
result, set `suggested_next_step` to the least destructive action consistent with it, and name
the missing row in the entry's `reason`. A gap in the rules then surfaces as a gap, rather
than as an invented class whose mapped strategy escalates a run that should have continued.

Where a Loop-Back Rules row exists but names no class, that is an authoring gap in the row, not
a reason to skip classification: pick the closest class from the table above and name it in the
entry's `reason` as inferred rather than written into the row, so the gap is still visible for
the row to be fixed. Do not leave `failure_class` empty or invent a twelfth value to avoid the
choice.

This table mirrors the authoritative copy in
`plugins/meta/skills/pipeline-orchestration/SKILL.md`, so every orchestrator carries the
mapping without loading that skill; `tests/test_agent_contract.py` fails if the two drift.
<!-- END BLOCK failure-classification -->

<!-- BLOCK stage-gating
targets: agents
except: meta
after: ^## Behaviour Rules$
-->
## Stage Gating and Escalation
These rules apply to every stage and take precedence over keeping the flow moving.

1. **Read the result before deciding.** After every tool run, read what it produced — the exit
   code plus the wrapper/MCP JSON (`status`, `summary`, `errors`) or the tool's own report or
   log summary — before assigning the stage `status`. A command having returned is not a result.
2. **Never proceed past a FAIL without applying the loop-back rule.** A stage that returns FAIL
   follows its row in Loop-Back Rules or ends the run. It is never skipped, downgraded to WARN,
   or deferred to a later stage.
3. **Loop cap exhausted: escalate clearly — show state and root cause.** When a loop-back row
   has used its `max N×`, do not run the stage again. Append the terminal `history[]` entry
   with `decision: "escalate"`, `failure_class: "resource_limit"`, `retry_strategy: "escalate"`,
   `suggested_next_step: "escalate"`, and a `reason` stating the cap reached, the last measured
   failure, and what the user must relax, supply, or accept. Then report the stage, the
   iterations used, what each iteration changed, the last measured QoR, and the suspected root
   cause.
4. **Fault is upstream: stop looping and hand back.** If the evidence shows the defect is in an
   input this domain consumes but does not own (RTL, netlist, constraints, IP views, a generated
   image), retrying here cannot fix it. Do not spend the remaining loop iterations and do not
   patch the upstream artifact yourself. Append the terminal `history[]` entry with
   `decision: "escalate"`, the observed `failure_class` with its mapped `retry_strategy`,
   `suggested_next_step: "escalate"`, and a `reason` naming the upstream domain, the artifact,
   and the evidence. If your Loop-Back Rules or Behaviour Rules define a `fix_request` hand-off
   for this case, follow it exactly. If this file has an Architecture Refinement Request
   section and the fault is the architecture, follow that section too. Otherwise the history
   entry and your final report are the hand-off — do not write to `fix_requests[]`.
5. **`pending_approval` is for gates only.** Set it only where your Behaviour Rules say so (the
   checkpoint gate and, where present, constraint validation). `type: "escalation"` is reserved
   for the pipeline-orchestrator.
6. Whenever item 3, 4 or 7 escalates, leave the domain `signoff` field `false` and write
   `signoff_achieved: false` in the experience record.
7. **A retry must make measurable progress toward the same target.** A Loop-Back Rules row
   sets the most attempts a failure may have, not a number that must be spent: this item stops
   a loop early and takes precedence over the iterations a row still allows. For a row marked
   `unlimited` it is the only stop. Keep the last artifact that measured better until its
   replacement has been measured, and after every loop-back iteration compare the stage's
   measured result — the QoR numbers, or the set of failures rather than their count — with
   the previous iteration's:
   - **Regression** — the result is worse, or a failure appeared that was not there before.
     Restore the previous artifact. The iteration still counts against the row's cap.
   - **No progress** — two consecutive iterations leave the result where it was. Do not run
     the stage again; escalate.
   - **Moved target** — the result improved because the thing being checked changed: a
     constraint relaxed, a waiver, exception or exclusion added, a check, test or assumption
     weakened, or the design's behaviour changed to silence a tool. A pass obtained by changing
     the target is not a pass. Undo the change — unless the target itself was wrong, in which
     case name the spec clause or constraint source that says so in the `history[]` `reason`
     and in the stage's waiver or exception record. A target that another domain or the user
     owns (`design_state.constraints`, the spec, an upstream artifact) is never yours to
     change: that is item 4. If the stage can only pass by moving the target, escalate.

   When this item escalates, append the terminal `history[]` entry with `decision: "escalate"`,
   the observed `failure_class` with its mapped `retry_strategy`,
   `suggested_next_step: "escalate"`, and a `reason` naming which of the three fired, the
   measured result of each iteration, and what the user must decide. Do not record
   `resource_limit` — the cap was not reached.
<!-- END BLOCK stage-gating -->

<!-- BLOCK architecture-refinement
targets: agents
only: synthesis, pd, sta
after: ^## Behaviour Rules$
-->
## Architecture Refinement Request
A narrow, explicit exception to "never change another domain's state": when the upstream
fault (Stage Gating and Escalation, item 4) is the **architecture**, flag it for refinement
instead of only reporting it.

1. **When it applies — all three must hold.**
   - Item 4 applies: retrying here cannot close the gap.
   - The evidence points at the microarchitecture, not the RTL coding, the constraints or the
     tool setup. Examples: WNS < 0 across every compile/optimisation strategy tried, with the
     critical path inside a datapath whose depth the architecture chose; utilisation above
     `constraints.area.utilization_pct_max` with the measured cell area above the
     architecture's estimate for the selected candidate; the same structural timing gap at
     every corner. A single failing path an RTL fix can retime is not an architecture fault.
   - `design_state.architecture.selected_candidate` is non-null. With no recorded architecture,
     there is nothing to refine — escalate under item 4 alone.
2. **What to write.** In the session-end atomic read-modify-write, set only these two keys
   under `architecture`; never touch `candidates[]`, `selected_candidate`, `signoff` or any
   other `architecture` field:
   ```json
   {
     "refinement_needed": true,
     "refinement_request": {
       "requested_by": "<this orchestrator, e.g. synthesis-orchestrator>",
       "requested_at": "<ISO-8601>",
       "failure_class": "timing | power_area",
       "constraint_ref": "<dot-path constraint key, e.g. clock.clk_mhz>",
       "measured": "<measured value with unit, e.g. WNS -0.42 ns at ss_setup>",
       "reason": "<why the architecture, not the RTL, is the fault>",
       "evidence_path": "<report path or null>"
     }
   }
   ```
3. **Do not overwrite an open request.** If `architecture.refinement_needed` is already
   `true`, leave the existing `refinement_request` in place and cite your evidence in the
   `history[]` `reason` instead.
4. **Then escalate as item 4 says.** The terminal `history[]` entry keeps `decision:
   "escalate"`, the observed `failure_class` (`timing` or `power_area`) with its mapped
   `retry_strategy`, and `suggested_next_step: "escalate"`. Its `reason` names the
   architecture domain, the measured gap and the constraint, and states that
   `architecture.refinement_needed` was set. The user re-invokes the architecture
   orchestrator, which resumes from its persisted candidates; nothing dispatches it
   automatically.
<!-- END BLOCK architecture-refinement -->

<!-- BLOCK long-running-jobs
targets: agents
after: ^## Behaviour Rules$
-->
## Long-Running Jobs
Builds, simulations, and PD/formal/verification flows routinely exceed a single turn.

1. **Background it, and record how to find it again.** Redirect stdout and stderr to a log
   file and capture the job id. Never run a long job in the foreground, and never busy-poll it
   in a tight loop — a wait loop spends the same turn budget as real work and produces nothing.
2. **Check at intervals matched to the job.** Minutes for a compile or simulation, not seconds.
   Each check costs a turn; pick a cadence the job's expected duration can actually afford.
3. **A quiet log is not a hung job.** A compile or simulation can sit with a completely static
   log for many minutes while its process consumes CPU normally — that is a normal state, not
   a hang. Before concluding a hang, confirm liveness (the process still running and consuming
   CPU, or its output files still growing); log silence alone is evidence of neither state.
4. **If the job will outlive your turn budget, stop and hand it over.** Report what is running,
   its job id and log path, the invocation that started it, how to tell when it has finished,
   and exactly which stages and Sign-off Criteria remain. A partial report naming the job is far
   more useful than an unverified success claim.
5. **Never report a result you have not read.** A gate whose job is still running is NOT RUN —
   see the Reporting Contract's rule on this. "Still running" is a valid, useful answer.
<!-- END BLOCK long-running-jobs -->

<!-- BLOCK reporting-contract
targets: agents
after: ^## Behaviour Rules$
-->
## Reporting Contract
Applies to every report you make: a stage result, an escalation, and the final summary.

1. **Run before you report.** Run every gate named in the task and every Sign-off Criteria item
   you claim, and paste each command with its exact output (or the wrapper/MCP JSON). Trim long
   output to the summary lines, but never paraphrase a number.
2. **Never report a gate as passing unless, in this session, you ran it or read its completed
   result file.** If you could not — tool missing, hardware unavailable, job still running,
   turn budget — say so explicitly, say why, and report the gate as NOT RUN, not as PASS.
3. **Exit 0 is not a pass.** A tool that exits 0 with empty or unparsable output, or a
   wrapper/MCP result with `"verified": false`, is NOT a pass. Find the result the tool was
   meant to produce; if it is absent, report the gate as unverified.
4. **Re-read the deliverable list immediately before finishing.** Go back to the task as
   written and to this orchestrator's `Output:` rule and confirm each item. List any item you
   did not complete, and why.
5. **Separate measured from inferred.** Quote the value you observed and where it came from
   (command, file, line). Mark anything else — estimates, expectations, results carried over
   from memory or an earlier session — as inference.
6. **Check artifact provenance.** If a test or gate consumes a generated artifact (`.hex` or ELF
   image, netlist, `.lib`/`.lef` view, SPEF, GDS, bitstream), verify its provenance in every
   environment that will run the test, not just yours. Either the artifact is committed, or a
   step that environment actually performs regenerates it. Passing locally because the file was
   already on disk is not evidence that CI or a downstream domain can run it. State which of the
   two holds for each such artifact.
7. **Record what you reported.** The domain `signoff` field and `signoff_achieved` may be `true`
   only when every Sign-off Criteria item is measured-PASS. A criterion that is NOT RUN or
   unverified means signoff is false; name it in the `history[]` `reason` and in `notes`.
8. **Run the gates your change triggers, not only the gates you were asked about.** Items 1–7
   bind the gates the task names. A change that lands in a repository with its own CI also
   triggers that repository's gates. Before reporting work complete or pushing, determine which
   CI jobs the paths you changed trigger — read the workflow files and their path filters, do
   not guess — and run every step of each locally, not only the step that last failed. Fixing
   the one step CI happened to report and pushing is not completion: the next step fails on
   the next run, and each cycle costs a full CI run. A new file is covered by whatever job
   matches its directory, even if the task never named that job. If a triggered step cannot
   run locally, name it and say why, as item 2 requires.
9. **Hand off what you established, whatever the outcome.** The domain fields you merge into
   `design_state.json` are the next domain's input, and an absent key reads there as "not
   reported", so nothing is assumed covered. On every termination path — signoff, escalation,
   max-iterations, a NOT RUN gate, turn budget, interruption — merge every domain field with
   what this run actually established, not only what the final stage would have produced:
   - a list (files, unverified claims, waivers, open issues) is written in full from the
     stages that ran, and `[]` only when it is genuinely empty;
   - a status or metric this run did not measure is `false` or `null`, with the reason in
     `notes`, never carried over from an earlier run as if measured.

   Build a hand-off list in the stage that produces each entry, not in the sign-off stage.
   Withholding signoff (item 7) never means withholding the hand-off.
<!-- END BLOCK reporting-contract -->

<!-- BLOCK rtl-lint-gate
targets: agents
only: rtl-design, fpga, soc, memory-ip, hls
after: ^## Behaviour Rules$
-->
## RTL Lint Gate
Applies to every synthesisable RTL file this orchestrator writes, modifies or generates —
including edits made on a loop-back or while servicing a `fix_request`. Testbenches
(`*_tb.sv`, `tb_*.sv`) and simulation-only behavioural models are exempt: `initial`, `#delay`
and blocking assignments are correct there.

1. **Lint before the file leaves the stage.** RTL that has not been linted since its last edit
   is NOT RUN under the Reporting Contract, however small the edit.
2. **Slang needs full elaboration.** Run `slang -Weverything --ignore-unknown-modules <files>`.
   Never pass `--lint-only`: it skips elaboration and silently drops inferred-latch and
   multiple-driver diagnostics, so a latch reports as clean. `-Wall` is not a slang option.
   Verilator is unaffected — `verilator --lint-only -Wall` is correct.
3. **Lint in filelist context.** Compile the block's filelist as one unit and report findings
   for the files you touched. A file linted alone reports its submodules as unknown.
4. **A stubbed module is not a bug in the file that instantiates it.** A library cell, hard
   macro, vendor primitive or black-boxed IP missing from the filelist leaves the nets it drives
   looking undriven. Record those findings as informational and name the stub and the library,
   macro or IP it stands for. A stub is benign only if you can name that. An unknown module
   that resolves to first-party RTL in this repository is not a stub: it is a missing filelist
   entry (item 9).
5. **Say what proved each finding.** Quote the tool's message and rule name for a tool-proven
   finding; label anything you reasoned without a tool run `UNVERIFIED`. A clean lint run proves
   nothing about CDC, reset sequencing, FSM reachability, protocol deadlock or arithmetic
   overflow.
6. **A fix must not change what the module does.** Stage Gating and Escalation item 7 applies
   to every lint fix, with the set of findings as the measured result. A new error is a
   regression. The same findings two iterations running is no progress. A fix that changes
   behaviour to silence a warning — narrowing a signal to stop a truncation warning implements
   the truncation — is intent drift, the RTL form of a moved target: revert and escalate.
7. **An aborted run is not a lint result.** If the tool stopped before rule checking completed
   (a parse or elaboration fatal, "aborted", a missing file), zero rules ran: the counts are
   unknown, not 0, and nothing was learned about the RTL. Before editing any file, attribute
   each fatal. A duplicate declaration together with an undeclared identifier, a message that
   names two paths for one file, a missing include, or a fatal in a file this run did not
   write points at the input set — include search is first-match-wins, so a stale tree listed
   first shadows the current one. Record `input_setup`, edit no RTL, and escalate with the
   paths. Only a parse error in a file this run wrote, with the input set checked, is yours to
   repair.
8. **Lint does not prove the downstream front-end accepts the RTL.** Verilator, slang and the
   simulation regression all read SystemVerilog natively. If any downstream flow converts this
   RTL before synthesis — sv2v, Surelog/UHDM, a vendor SV-to-Verilog step — run that conversion
   over the filelist and parse its output with the tool that will consume it, e.g.
   `sv2v <files> > out.v && yosys -q -p 'read_verilog out.v; hierarchy -check -top <top>'`.
   Report it as its own gate, the front-end check, with the command and its exit status. A
   construct that is legal SystemVerilog and illegal in the target revision — a part-select on
   a function-call result, `f(x)[N-1:0]`, is the canonical case — passes lint and every
   simulation and fails only here, because nothing else reads the converted file. Fix such an
   error in the source construct, never in the converted file. Read the item 4 stubs into the
   consuming tool as black boxes first (`read_verilog -lib <stubs>`), so `hierarchy -check`
   fails only on modules that are really missing. If no conversion tool is available, report
   the gate NOT RUN.
9. **A new module is not integrated until every tool's source list can see it.** Projects keep
   separate source lists for simulation, lint, synthesis, PD and formal, often as Makefile
   variables. When you add an RTL file, enumerate every source list that feeds a tool in this
   project and confirm the file is in each, or state why it should not be. Converters and
   synthesisers black-box a module missing from their list without an error, and the
   simulation regression cannot notice because it reads a different list. Where the lists are
   `.f` files, or can be dumped to one, run `check_design_inputs.py <filelist.f> --rtl-dir <rtl>
   --list <name>=<file> ...` from `plugins/rtl-design/skills/rtl-design/`: it names each list
   that misses a module on disk.
10. **Optional — `hdl-rtl-skill`.** If its `rtl-lint` script is available, use it as the slang
    runner: it applies items 2–4. Treat its `BLOCKER` and `HIGH` findings as errors, `MEDIUM`
    as warnings, `LOW` and `INFO` as informational, and its `MANUAL_REVIEW_REQUIRED` as an
    escalation. If it is unavailable, the items above stand on their own — it augments, never
    replaces, this gate.
<!-- END BLOCK rtl-lint-gate -->

<!-- BLOCK ide-guards
targets: files
files: ides/codex/AGENTS.md, ides/gemini/gemini-header.md, ides/copilot/.github/copilot-instructions.md
after: ^## (General Behaviour|Behaviour for All Domains)$
-->
## Verification and Reporting

- Read a tool's exit code and report before assigning a stage status.
- Never proceed past a FAIL without applying the stage's loop-back rule.
- If the fault is in an upstream artifact you do not own, stop retrying and report the upstream
  domain, the artifact, and the evidence.
- A retry must improve the measured result against the same target: revert one that makes it
  worse, stop and report after two that change nothing, and never get a pass by relaxing the
  constraint, check or test that failed.
- Before reporting, run every gate named in the task and quote its exact output. Never report a
  gate as passing that you did not run; say NOT RUN and why.
- Before pushing to a repository with its own CI, read its workflow path filters, find every
  job the changed paths trigger, and run all of each job's steps locally, not only the step
  that last failed. Name any step you could not run.
- A tool that exits 0 with empty or unparsable output is not a pass.
- If a tool aborted before checking the design, or ran on the wrong inputs (filelist, include
  path, config, generated headers), change nothing in the design: report the input and stop.
- Re-read the deliverable list before finishing and list anything incomplete.
- Whenever you stop, with or without signoff, record what you established for the next stage:
  the files you produced and every conclusion you reached without a tool run. Not claiming
  signoff never means handing over nothing.
- Separate measured values from inference.
- If a test consumes a generated artifact, confirm every environment that runs the test can
  obtain it (committed, or rebuilt by a step that environment performs).
- For a job that outlives a turn, background it with its output captured and check back at an
  interval matched to the job; a quiet log is not a hung job.
- If such a job will outlive your turn budget, stop and report what is running, its log, and
  what remains, rather than waiting on it unverified.
<!-- END BLOCK ide-guards -->
