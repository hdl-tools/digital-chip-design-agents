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
<!-- END BLOCK ide-guards -->
