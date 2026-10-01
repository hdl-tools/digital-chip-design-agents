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
disagreement stays visible in `history[]` instead of being resolved silently.

Where a condition has **no** Loop-Back Rules row at all, there is nothing to defer to and no
class to map from. Do not invent a `failure_class` to manufacture one: record the stage
result, set `suggested_next_step` to the least destructive action consistent with it, and name
the missing row in the entry's `reason`. A gap in the rules then surfaces as a gap, rather
than as an invented class whose mapped strategy escalates a run that should have continued. This table mirrors the authoritative copy in
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
   for this case, follow it exactly. Otherwise the history entry and your final report are the
   hand-off — do not write to `fix_requests[]`.
5. **`pending_approval` is for gates only.** Set it only where your Behaviour Rules say so (the
   checkpoint gate and, where present, constraint validation). `type: "escalation"` is reserved
   for the pipeline-orchestrator.
6. In both escalation cases leave the domain `signoff` field `false` and write
   `signoff_achieved: false` in the experience record.
<!-- END BLOCK stage-gating -->

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
   looking undriven. Record those findings as informational and name the stub.
5. **Say what proved each finding.** Quote the tool's message and rule name for a tool-proven
   finding; label anything you reasoned without a tool run `UNVERIFIED`. A clean lint run proves
   nothing about CDC, reset sequencing, FSM reachability, protocol deadlock or arithmetic
   overflow.
6. **A fix must not change what the module does.** After each fix compare the set of findings,
   not the count. A new error is a regression — revert it. The same findings twice running is
   no progress — escalate now (Stage Gating and Escalation, item 3) rather than spend the
   remaining iterations. A fix that changes behaviour to silence a warning — narrowing a signal
   to stop a truncation warning implements the truncation — is intent drift: revert and
   escalate.
7. **Optional — `hdl-rtl-skill`.** If its `rtl-lint` script is available, use it as the slang
   runner: it applies items 2–4. Treat its `BLOCKER` and `HIGH` findings as errors, `MEDIUM` as
   warnings, `LOW` and `INFO` as informational, and its `MANUAL_REVIEW_REQUIRED` as an
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
- Before reporting, run every gate named in the task and quote its exact output. Never report a
  gate as passing that you did not run; say NOT RUN and why.
- A tool that exits 0 with empty or unparsable output is not a pass.
- Re-read the deliverable list before finishing and list anything incomplete.
- Separate measured values from inference.
- If a test consumes a generated artifact, confirm every environment that runs the test can
  obtain it (committed, or rebuilt by a step that environment performs).
- For a job that outlives a turn, background it with its output captured and check back at an
  interval matched to the job; a quiet log is not a hung job.
- If such a job will outlive your turn budget, stop and report what is running, its log, and
  what remains, rather than waiting on it unverified.
<!-- END BLOCK ide-guards -->
