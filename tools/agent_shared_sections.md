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
<!-- END BLOCK ide-guards -->
