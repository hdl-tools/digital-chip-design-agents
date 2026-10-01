# Changelog

## [Unreleased] — issue #102: `lec_run` looped back to a stage that cannot fix a netlist

### Fixed

- **`formal-orchestrator`'s `lec_run: unmatched points` row retried `lec_run` itself** on a
  netlist mismatch, but `lec_run` only compares the RTL/golden model against a netlist produced
  by synthesis — it never regenerates either side. Each retry re-ran the same comparison against
  the same unchanged netlist and reproduced the identical mismatch, spending all 3 permitted
  iterations before escalating on an input nothing in the retry loop could change. Same defect
  class, and same shared precedence rule, as #86 (fixed for `infrastructure-orchestrator`): the
  Stage Gating block already says a stage must stop looping and hand back when the fault is in
  an upstream artifact it does not own, but the row granted three iterations anyway, and a row
  wins over that rule where the two disagree. The row now escalates immediately, naming the
  netlist mismatch and that synthesis — not `lec_run` — must produce the fix.

### Added

- **Test** `tests/test_agent_contract.py::test_lec_mismatch_escalates_instead_of_looping_back_to_lec_run`,
  so the row cannot regress back into looping to `lec_run`.

## [Unreleased] — issue #94: a loop-back FAIL had no `decision` value of its own

### Fixed

- **A stage that FAILed and looped back was recorded as `decision: "proceed"`.** The
  `history[]` schema's `decision` enum (`proceed | escalate | abandoned | await_approval`)
  had no value for the commonest non-terminal outcome: the stage FAILed, and a Loop-Back
  Rules row sent the run to another stage to retry. Behaviour Rule 6 requires one entry per
  completed stage including failing ones, so every such entry had to pick the closest
  existing value — `proceed`, the one that means the opposite of what happened. Measured on a
  real host: `environment_validation` FAILed twice on critical tools MISSING and looped back
  to `tool_installation` each time, and both were written as `decision: "proceed"`.
  `design_state.json`'s `history[]` is the cross-orchestrator hand-off the
  pipeline-orchestrator reads to decide whether to retry, loop across domains, or escalate —
  a FAIL filed as `proceed` is indistinguishable there from a clean PASS. Added `loop_back` to
  the `decision` enum in all 15 domain orchestrators. `plugins/meta/agents/pipeline-orchestrator.md`
  keeps its narrower `proceed | escalate` enum, with a note explaining why: its own history
  entry is written only at the two terminal branches of `signoff_or_escalate`, never at the
  internal loop back inside `check_iteration_cap`.
- **`tools/agent_shared_sections.md`'s `failure-classification` block** now states when to
  write `decision: "loop_back"` instead of `"proceed"`, synced into all 15 agents via
  `tools/sync_agent_sections.py`.

### Added

- **Test** `tests/test_agent_contract.py::test_decision_enum_lists_loop_back_for_agents_with_loop_back_rules`,
  parametrized over every agent with a `## Loop-Back Rules` section, so a new loop-back row
  cannot be added to an orchestrator whose `decision` enum omits the value it needs to record.

## [Unreleased] — issue #98: module version selection

### Fixed

- **"Latest version" was selected by sorting version strings as text**, in two rules — `tool_discovery` rule 2 Step A c and `module_discovery` rule 9 — both saying "highest semver/lexicographic" as though the two orderings agree. Measured on the reference host, a 13-version Python tree spanning 3.6.x–3.14.x has newest `3.14.6` and lexicographic maximum `3.9.7`, the **fourth-oldest**, because `"9" > "1"` at the second segment. Step A runs *before* the PATH check and wins over it, so the stage replaced the host's `3.12.2` interpreter with an older module one and kept it loaded for all five remaining stages; `load-modules.sh` recorded the same wrong choice per tool with the newest version commented out as an "alternative". Selection is now specified once, in a new `#### Module version selection` rule that both call sites defer to.
- **The module system's own default was being discarded.** `module avail` annotates it — `klayout/adi/0.27.11 (adi default)` — and the entry-format rule added by #87 said to take the version "after stripping any trailing `(...)` annotation", so the site's answer to "which version" was present in the parsed data and thrown away as noise. Measured: **372 of 3813** listing entries carry that annotation. It is now captured, and the annotated default outranks anything this stage computes.
- **Non-release builds could be selected as "latest".** The trees carry `3.12.2_test`, `3.6.2-debug`, `5.24-dev` and similar alongside releases. A version with any segment equal to `dev`, `test`, `debug`, `rc`, `alpha`, `beta`, `snapshot` or `nightly` is now excluded from an automatic choice while a release exists — it stays in `versions_available`, since a user may want one. The marker list is deliberately short: a site revision tag like `3.12.2.R10`, or a patch letter like `3.9.7n`, is a release and is ordered by the comparator.

### Changed

- **The result is "the version this host should use", not "the newest".** Where the module system marks a default, that default wins, and a site default is commonly an older qualified build — measured on the reference host, the annotated default differs from the newest available for every tool checked, and is several versions behind for some. That is deliberate and the rule says so, so the wording no longer promises newest.
- **`module-status.json` records `selected`, `selected_basis` (`site_default | highest_release | highest_prerelease`) and `candidates`** per tool, so a wrong pick is visible in the artifact rather than only in the loaded environment. `highest_prerelease` should be rare and is the value worth noticing.
- **`load-modules.sh`'s selected line states the basis** — `# selected: <basis>; alternatives: <versions>`, replacing `# latest; alternatives: …` — and the Stage Output Summary prints the basis and candidate count per tool.
- **`memory/infrastructure/knowledge.md`**'s quirk entry described the behaviour as lexicographic with "pin the intended module explicitly" as the mitigation. Rewritten: pinning is now only for where the site default is wrong for a particular flow, not the routine workaround it was when selection was a plain sort.

### Added

- **Test** `tests/test_agent_contract.py::test_module_version_selection_is_specified`, four assertions, each mutation-checked: no call site may sort lexicographically (the word survives only inside the rule, which cites it as the defect); the rule exists once and both call sites defer to it; the site default is first in the selection order and every non-release marker is named; and the three selection fields are in the schema.

The comparator's specification was corrected during implementation by executing it against the measured set. A clause ranking an extra *non-numeric* segment lower — justified by `5.24` > `5.24-dev` — gave `3.12.2.R10` < `3.12.2`, which is wrong. Its motivating case is already handled by the non-release exclusion, so inside the release pool the only remaining extras are post-release revision tags, for which longer genuinely is newer. The tie-break is now simply "more segments ranks higher", which also reduces the comparator to a plain tuple comparison.

## [Unreleased] — issues #91, #90: one sentence, two defects in `environment_validation` rule 2

### Fixed

- **`tool-manifest.json` had five references, no schema and no creator** (#91). This is a regression, not an omission: `git log -S 'tool-manifest'` returns two commits, and the second (`f1124c5`, "Added modulefile support for infrastructure orchestrator") deleted both the rule that wrote the file and the Output Required line that described it — `6. Write tool-manifest.json reflecting confirmed tool state after user runs the script` and `tool-manifest.json — final confirmed tool list after installation` — while rewriting the reader into today's rule 2 and keeping the comparison. The surviving references all treated the file as pre-existing ("compare against", "written", "**Updated**"), so two independent runs invented two incompatible shapes to satisfy the sign-off checklist and nothing downstream could rely on it. The file now has a schema and a named creator.
- **Rule 2 compared against that same stage's own output** (#91), so on any run there was nothing to compare against. The baseline is now `tool-status.json` — written by `tool_discovery`, updated in place by `module_discovery`, and the only tool record that exists when the rule runs. The rule also states that it never compares against its own output, and that a disagreement is a WARN rather than a status downgrade: the stage stays read-only on `tool-status.json`, which six of its nine rules already were.
- **Rule 2 claimed to use "the same Python-aware detection as `tool_discovery` rules 2–3" and specified detection that was not the same** (#90). Rule 3 gives `cocotb` and `uv` a fallback chain — try `$PYTHON_BIN_DIR/<tool>`, then fall back to PATH — and for `python_env.type == "system"` uses PATH only, never constructing a `$PYTHON_BIN_DIR` probe. Rule 2 dropped the fallback and forbade it, diverging two ways per tool: it dropped a fallback rule 3 grants, and on a system-Python host it probed a path rule 3 never builds. `openlane` never diverged — rule 3 has no fallback for it — and is unchanged. Rule 2 now performs rule 3's detection exactly, so the claim is true rather than aspirational.

### Changed

- **`tool-manifest.json` is a validation receipt, not a tool list.** A tool-keyed manifest would restate every per-tool field `tool-status.json` already carries (`tool`, `command`, `status`, `version`, `path`, `role`, `dialect`, `module_names`, `versions_available`) plus `python_env` — and `module_discovery` already sets the precedent that a later stage updates that file in place rather than forking a parallel copy. Restating them is how the two invented shapes happened. Walking all nine rules, what this stage establishes that `tool-status.json` cannot express is exactly five things, and they are the schema: `python_env` **liveness** (the recorded module may no longer be loaded, the recorded `exec` may no longer match), wrapper executable bits, MCP artifact presence, the computed dialect-conflict set with its members rather than just rule 7's count, and the sign-off verdict. `tool_status_source` names the file it references instead of copying.
- **The deleted `tool_installation` rule 6 is deliberately not restored.** Its semantics were a post-install re-survey, which depended on that stage running the install and emitting one combined `install-missing-tools.sh`. It now never executes anything and emits one script per tool, so restoring the rule would recreate a contract the flow no longer has.
- **`docs/MASTER_INDEX.md`**'s infrastructure row listed `tool-manifest.json` as the flow's only artifact; it now also names `tool-status.json` and `module-status.json`, which are the files anything downstream actually reads.

### Added

- **A WARN for the hazard the strict check was reaching for.** Where a package resolves via the PATH fallback while `python_env.type` is `custom` or `module`, the stage warns that the tool resolved outside the active Python environment's bin dir and may target a different interpreter than `python_env.exec` — never for `system`, where PATH *is* the active environment. It is recorded as `python_packages[].resolved_via` in the manifest, so it is auditable after the run rather than print-only. The issue proposed this *or* mirroring the chain; they are complementary, and the repo shows why the WARN cannot carry the issue's original justification: there is **no** wrapper or MCP config referencing `PYTHON_BIN_DIR`, `uv`, `cocotb-config` or `openlane` anywhere — all 8 wrappers resolve via bare `command -v` on PATH, and the downstream domains invoke bare commands — so "a wrapper invoking it via `PYTHON_BIN_DIR` will not find it" describes a consumer that does not exist. The real hazard is interpreter mismatch, and it is common: `tool_installation` prefers the standalone astral.sh installer for `uv`, which installs outside `$PYTHON_BIN_DIR`. Measured on the reference host, `python_env.type` is `custom`, `$PYTHON_BIN_DIR` holds no `uv`, and `uv` is on PATH under a different prefix — so the old rule reported absent what `tool_discovery` had recorded `FOUND`, and the new rule reports `FOUND` with `resolved_via: "path"` plus this WARN.
- **Test** `tests/test_agent_contract.py::test_environment_validation_artifacts_are_defined`, four assertions, each mutation-checked: every `.json` artifact a stage promises on its Output Required bullet list must be defined and carry a schema (this is the assertion that would have caught `f1124c5`); no rule may compare against an artifact its own stage produces, matched on collapsed text with a negation window so a sentence *forbidding* the comparison is not itself a violation; rule 2 may not forbid a PATH fallback that rule 3 performs; and the manifest may not restate per-tool `tool-status.json` fields.

Not included, deferred: #104 (`environment_validation` and `tool_installation` have no QoR section, and `dialect_conflicts` is declared by a stage that cannot compute it) stays separate — it would only couple to this change if the manifest had been deleted and its facts moved into the QoR object. One finding filed separately rather than fixed here: `docs/MASTER_INDEX.md` points at `docs/Infrastructure_Setup_Flow.md`, which does not exist.

## [Unreleased] — issues #92, #86: critical-path tools keyed by command, and an unwinnable loop-back removed

### Fixed

- **`environment_validation`'s FAIL gate could not see the tool it gates on** (#92). Three rules named the critical-path set by product — `(Yosys, Verilator, OpenROAD, OpenSTA)` — while `tool-status.json` keys entries by command, and OpenSTA's command is `sta`. A run matching `"OpenSTA"` finds no entry and concludes *the tool is absent from the table*, not *the tool is missing*: a silent pass on a sign-off gate. The set is now defined once, by command, at the top of `environment_validation`'s Domain Rules, and the three rules carry `` (`yosys`, `verilator`, `openroad`, `sta`) ``. Defining it once rather than correcting three copies is the point — the third copy was added two commits ago by the #87 fix, which is how a two-site defect became a three-site one.
- **`tool` was never defined.** The root cause under #92: `tool-status.json`'s schema is `{ "tool": "", "command": "", … }` and no prose anywhere in the repo said what `tool` holds. The convention was inferable only from the sibling artifact, whose schema says `"tool": "<command>"`, and from the module-mapping table's "Tool command" column heading. Both fields are now stated to hold the command, with the explicit warning that a rule naming a product cannot find its entry wherever the two differ, and that "no entry found" is not the same answer as "tool missing". Scoped to the two status artifacts, because the Wrapper JSON Output Schema deliberately uses a wrapper *label* (`"tool": "<tool-name>"` — `opensta`, `verilator-sim`) to say which wrapper produced a record rather than to name an entry to match; the note says so, so the wrappers are not "corrected" to emit commands.
- **Formality's module-mapping row was keyed on its legacy command** (#92, same defect class, worse consequence). #82 established `fm_shell` as the primary command and `formality` as the legacy GUI alternate, but the mapping row stayed keyed `formality` and the orchestrator's Proprietary table still named `formality` as the command. On a host where Formality is installed as `fm_shell`, `module_discovery` rules 7–8 look for an entry keyed `formality`, find none, and silently skip the module upgrade — losing a tool rather than merely requiring an inference. The row is now keyed `fm_shell` and still *matches* `formality` and `synopsys/formality`, since sites name modules after the product. All seven proprietary primaries were cross-checked against the mapping table; Formality was the only mismatch.
- **`environment_validation FAIL (critical tool MISSING) → tool_installation (max 2×)` could never succeed** (#86). `tool_installation` only generates `install-<toolname>.sh` and never executes it, and it regenerates scripts only for tools already `MISSING` — so nothing on the loop-back path can change a status. The cap was spent on two identical checks against unchanged inputs before escalating anyway, on every fresh workstation missing a critical tool, which is the case this orchestrator exists for. Worse than the issue argued: the shared precedence rule says the Loop-Back row wins over a mapped `escalate` while an iteration remains, so the orchestrator was not merely permitted to burn both iterations but *instructed* to. The row now escalates, naming the generated scripts, the re-run, and **why** retrying cannot help — the last clause being what stops the row from being "fixed" back into a loop later. This matches the two rows that already got it right, `python3 missing` and `critical tool MISSING_LOAD_MODULE`; `pending_approval` stays unset, since Stage Gating reserves it for gates.

### Changed

- **`environment_validation` rule 5 now states the action, not only the verdict.** It said "FAIL" and nothing else; the recovery lived solely in the agent's Loop-Back table, so skill and agent each carried half the contract. It now carries the same escalation and the same reason.

### Added

- **Test** `tests/test_agent_contract.py::test_critical_path_tools_are_keyed_by_command`, four assertions, each mutation-checked: no enumerated critical-path set may name a product (this is what would have caught the site #87 added); the four commands must appear as commands in the authoritative Open-Source list, so the set cannot drift from the table it keys against; no loop-back row may *target* `tool_installation` for a missing critical tool — matched on the row's target rather than its prose, since an escalation row may legitimately name the stage while explaining why looping to it cannot work; and every proprietary primary command must key a module-mapping row, which is the Formality guard and the one assertion that generalises past these two issues.

Not included, deferred. `failure_class` on loop-back rows stays with #93: strictly zero rows carry a `history[]` class today — the two apparent exceptions carry `fix_request` classes from a separate enum — so annotating one row would make infrastructure a third format before #93 chooses one for all 83. Three same-class findings are filed separately rather than widening this change: the identical unwinnable loop in `formal-orchestrator`'s `lec_run` row, the modulefile tool-var table keyed by product name (`LLVM` cannot match command `llvm-config`), and `environment_validation` having no QoR subsection at all. The product-name list in this file's own #87 entry is left as written — a changelog records what was written at the time, so the new test is scoped to `plugins/`.

## [Unreleased] — issue #87: module-system detection and listing provenance

### Fixed

- **Every site whose `module` is not Environment Modules was recorded as `tclmod`.** Detection tested "`$MODULESHOME` is set **or** `modulecmd` exists in PATH" and the `module-status.json` enum offered only `tclmod | none`, so a host with `$MODULESHOME` set and no `modulecmd` — whose `module` is a site shell wrapper carrying its own path variable — had to be written as classic Environment Modules and hope a caveat was read. Detection now requires `modulecmd` for `tclmod`, records `custom` for `$MODULESHOME` without it, and carries the evidence in `module_system_detail`.
- **An empty `tools_via_modules` could not be told apart from a listing that never ran.** `module` is frequently a shell function, so it is absent from the non-interactive shell the orchestrator uses: measured, `bash -c 'module avail'` returns 127 on a host where the module system is plainly installed. Both verification runs for #82 and #85 wrote `module_system: "tclmod"` with `tools_via_modules: []`, and on that host `verilator`, `iverilog`, `klayout`, `vsim`, `innovus`, `pt_shell` and `formality` are available **only** via modules — so the mis-detection did not merely mislabel a field, it silently lost seven tools and the run then FAILed on critical tools that were installed. `module_listing` now records whether the listing was obtained at all, and the stage states that an empty list is evidence of nothing unless it reads `LISTED`.
- **The availability *test* and the availability *command* checked different things.** Recording `custom` is necessary but not sufficient: a genuine TCL install whose `modulecmd` is off PATH would still fail the listing. Classification from the environment is now a starting guess that a succeeding invocation **upgrades** — a listing via `$MODULESHOME/init/bash` proves `tclmod` even where `modulecmd` was never in PATH. The probe decides, not the env var.
- **`load-modules.sh`'s omission condition named the wrong field.** "Omitted when `module_system` is `"none"`" coincides with "nothing to put in it" only when module detection works, which is the defect above: both #82/#85 runs had `module_system: "tclmod"` with zero qualifying tools, so the literal rule did not authorise omitting the file and there was nothing to write. The condition is now "no tool qualifies", with `module_system: "none"` named as one case among others.
- **Mapping-table patterns were matched as arbitrary substrings.** Latent while detection was broken — with no listing, nothing could be mis-matched — and reachable the moment the listing works. Measured against a real 3812-entry listing, substring matching produced two classes of false positive: a module whose name merely *ends* with a mapped command (an optimisation tool named `...slang` matching `slang`), and one whose name or version string merely *contains* one (a verification tool whose version ends `_python2`, and a GUI tool bundle whose name contains `python3`, both matching `python3`). The second class is damaging, because `tool_discovery` Step A loads the *latest* matched Python module and keeps it loaded for the whole run, and the highest-sorting substring match was that GUI bundle rather than an interpreter. A pattern now matches only whole `/`-delimited tokens — one token, or a contiguous run for a pattern containing `/` — which drops both false positives and leaves the 12 genuine tools. One rule in the shared matching step rather than a patch per pattern.
- **Module entries were parsed as `<name>/<version>`.** Measured entries are `klayout/adi/0.29.0`, `verilator/adi/3.922` and `klayout/adi/0.27.11 (adi default)` — two or more segments plus an optional annotation — so the old rule recorded `adi` as the version. The version is now the last `/`-separated segment after stripping a trailing `(...)`, and the full entry string is kept in `module_names`.

### Added

- **A module invocation ladder**, five rungs tried in order with the winning one recorded verbatim in `module_invocation`: the orchestrator's own shell; `modulecmd bash avail`; `$MODULESHOME/init/bash`; a site wrapper's `$MODULESHOME/module.sh`; the wrapper invoked directly. Rung 4 is the one that works on the reference host — `module` becomes a shell function and `module avail` exits 0 with 3813 entries in 159.5 s — which is what recovers the seven lost tools rather than only labelling the loss.
- **A rung succeeds only where it exits 0 *and* its output holds at least one entry-shaped line** — neither test alone, and a failed rung never means the host has no modules. Both halves are measured: rung 5 on the reference host exits 1 printing `Usage: [-n] subcommand [arguments ...]`, and that usage text itself contains `modulename/scope`, `modulename/version` and `modulename/scope/version`, so an output-shape test alone reads the failure as a successful listing of three modules named `modulename`. The converse — exit 0 with no listing — is the trap #82 already documented for version probes, where a broken install answers 0 whatever the vendor.
- **The timeout wraps the shell, not the command, and the budget is 300 s.** `timeout` execs a binary and cannot wrap a shell function: measured, `timeout 60 module avail` returns 127 with `timeout: failed to run command 'module'` on a host where the rung had just succeeded, so every rung runs as `timeout 300 bash -c '<rung>; module avail </dev/null 2>&1'`. 300 s rather than the 60 s used for version probes because the listing walks every modulefile tree — 159.5 s measured on a warm NFS cache, with `ls: cannot access ...` noise from stale paths along the way — and a short budget records a working module system as unprobeable. Stdin is always `/dev/null`: a wrapper that prompts would otherwise block the whole run with no output to diagnose.
- **A WARN taxonomy that keeps "no module system" distinct from "module system present but not listable"**, the second naming the classification, the evidence and the failure reason, and telling the user to source `$MODULESHOME/module.sh` (bash) or `module.csh` (tcsh) — both, because the probes all run under `bash -c` regardless of the user's login shell while a user re-running by hand may be in either. Where that second case coincides with a critical-path tool (Yosys, Verilator, OpenROAD, OpenSTA) still `MISSING`, the stage escalates with `failure_class: "tool_error"` instead of proceeding. Escalating at `module_discovery` is chosen over qualifying `environment_validation` rule 5 because this is the stage that holds the information: rule 5 would otherwise FAIL five stages later with a diagnosis ("Verilator MISSING") that is simply wrong.
- **QoR metric `module_listing_ok`**, and `module_system_detected` redefined as "`module_system` is not `"none"`" so a custom wrapper counts. `tools_found_via_modules: 0` is documented as meaningful only when `module_listing_ok` is true.
- **Test** `tests/test_agent_contract.py::test_module_system_records_a_custom_wrapper_and_a_listing_status`: the enum must admit `custom`, the orchestrator's memory-record copy of that enum must not drift from the skill's (nothing cross-checked the two before), the schema must carry `module_listing`, and the stage must keep stating that an empty `tools_via_modules` may mean the listing failed.

### Changed

- **`tool_discovery`'s Python probe (Step A)** restated the env-var heuristic instead of using it, and its fall-through covered only "no module system is available" — leaving "present but not invocable" unhandled. It now defers to `module_discovery`'s detection rules and ladder, and falls through explicitly on `UNAVAILABLE`, noting that recovering a PATH interpreter here does not suppress the WARN `module_discovery` owes.
- **The stage output summary** hardcoded `Module system : Environment Modules 4.8.0 (TCL)`. It now prints the classification with its evidence plus a `Module listing` line naming the winning invocation, and prints the module-tool count as `not surveyed` rather than `0` when the ladder was exhausted.

Not included, deferred, both found while verifying this fix: lexicographic "latest version" selection, which on the reference host picks the fourth-oldest of thirteen Python modules and silently downgrades the interpreter the remaining five stages depend on, is now #98. `SKILL.md`'s two `module_system == "none"` guards before the "automatic module loading is unavailable" WARN stay as they are — the comparisons remain literally correct with the wider enum, but a TCL-classic modulefile is not consumed by a `custom` wrapper either, and `custom` is now the one value that reaches those lines without a warning — now #99.

## [Unreleased] — issue #85: retry_strategy mapping reachable by every orchestrator

### Fixed

- **15 of 16 orchestrators derived `retry_strategy` from a table they could not read.** Behaviour Rule 6 told every domain orchestrator to "derive `retry_strategy` from `failure_class` via the mapping in the pipeline-orchestration skill", but none of them declared that skill — only the meta orchestrator, which owns it, did. The values written into `design_state.json`'s `history[]` were therefore each agent's own inference, which contradicts the Reporting Contract's rule against reporting from memory what should be read from source. Since `format_version` 1.5 requires every entry to carry a `retry_strategy` and the pipeline-orchestrator reads those values to choose retry, cross-domain loop, or escalation, per-run inference means silent drift in the cross-domain hand-off.

### Changed

- **New shared section `failure-classification`**, synced into all 15 domain orchestrators by `tools/sync_agent_sections.py`: the 10-row `failure_class` → `retry_strategy` table plus what each of `regenerate`, `refine`, `escalate` and `none` means in practice. Behaviour Rule 6 now points at that table instead of an undeclared skill. Chosen over adding `chip-design-meta:pipeline-orchestration` to each agent's `skills:` list because that would load a 494-line orchestration skill into every domain agent for one table — and that skill carries pipeline-orchestrator-only rules, including the `pending_approval type: "escalation"` the Stage Gating block reserves for it, so handing it to domain agents invites the confusion that guard exists to prevent.

### Added

- **`tests/test_agent_contract.py::test_retry_strategy_mapping_matches_the_authoritative_table`** — the mapping now exists in two places, and `sync_agent_sections.py --check` only compares agents against the shared file, never the shared file against the skill that owns the table. This test closes that gap.
- **`tests/test_agent_contract.py::test_retry_strategy_mapping_is_reachable_by_the_agent`** — an agent that writes `retry_strategy` must either carry the table or declare the skill holding it, and an agent that does not declare the skill may not refer to it. The second half caught a stale citation in `verification-orchestrator.md`, whose rule 6 named the mapping twice with different wording.

## [Unreleased] — issue #82: proprietary tool versions and dialect model

### Added

- **`role` and `dialect` on every `tool-status.json` entry** (issue #82, sections A and B). `role` groups tools that do the same job (`rtl_simulator`, `synthesis`, `sta`, …); `dialect` names the command-line and source-language vocabulary a tool accepts (`synopsys`, `cadence`, `siemens`, `verilator`, …). Both are recorded for open-source and proprietary tools alike, and are `null` for a tool with no same-role peer — never an invented role, since a `null` cannot produce a false conflict. `module_discovery` preserves both unchanged.
- **License-free version probes for proprietary tools**, each measured on a real install (exit 0, named line present, 1–26 s, no license queue): `vcs -ID` (parse the `Compiler version` line only — the FLEXlm host ID it also prints is never written to `tool-status.json`), `xrun -version`, `dc_shell -version`, `pt_shell -version` and `fm_shell -version`. Questa and Innovus remain `UNVERIFIED` rather than given a guessed flag that could open an interactive shell or check out a license; in both cases the reference host's obstacle was the install, not the flag (`innovus` reports an expired build authorisation, `vsim` cannot load `libXext.so.6`).
- **Probe timeout is 60 s, not a short one**: a Cadence Common UI tool starts a full shell to answer `-version`. `genus -version` measured 26 s cold and 12 s warm, so a 10 s budget would record a working probe as unprobeable.
- **A probe that exits 0 without printing the documented line leaves `version` empty and WARNs.** Exit status does not reveal this and it is the common failure: `innovus -version` exits 0 on an expired build authorisation, `voltus -version` exits 0 on a broken platform install, and `vsim -version` exits 0 on a missing shared library — none print a version. The version is recorded only when the documented line was actually found.
- **Formality's primary command is `fm_shell`**; `formality` is the legacy GUI wrapper, absent from recent installs, and is now the alternate rather than the primary.
- **`environment_validation` dialect-conflict WARN**: where detected tools sharing a `role` hold two or more differing `dialect` values and at least one is `PROPRIETARY_ONLY`, the stage emits **one** WARN for that role listing every member — one per role, never one per pair, since a five-member role would otherwise produce ten warnings saying the same thing. `dialect_conflicts` counts roles. This is the one check that would have caught the reported failure — an Xcelium compile line run by VCS, which silently discarded 8 switches plus `+access+rwc` before hard-failing on Cadence-only source — at setup time rather than six stages downstream. The WARN is restricted to pairs involving a proprietary tool so it stays rare enough to be read; two open-source simulators are on nearly every host.
- **QoR metrics** `proprietary_versioned` and `dialect_conflicts`, in the skill and in the orchestrator's stage-output block.
- **Test** `tests/test_agent_contract.py::test_proprietary_tools_carry_role_and_dialect`: fails if a proprietary tool is added without a role or dialect, if a probe marked verified loses its command, or if the `tool_discovery` output schema stops carrying both fields.

### Changed

- **`tool_discovery` rule 6** captured a version for `FOUND` tools only. Proprietary tools are recorded `PROPRIETARY_ONLY`, never `FOUND`, so the rule never applied to them and the schema's `version` field was structurally always empty for that class. It now covers every tool found in PATH, including `PROPRIETARY_ONLY` tools with a verified probe.
- **Infrastructure memory** `key_metrics.tool_versions` was populated from `FOUND` entries only; it now takes every entry with a non-empty `version` (`FOUND`, `FOUND_PREFER_MODULE`, `PROPRIETARY_ONLY`), so a later session can scope a vendor-option lookup to the exact build in use.

Not included, deferred: the opt-in simulator invocation smoke test (#82 section C, now #88) and the proprietary compile wrappers (section D, now #89). Wrapper count stays 8; MCP target stays 10. Extending the table past the original seven tools — and confirming the probe flags for Questa and Innovus, which this host could not verify — is tracked in #84.

## [Unreleased] — feat/reporting-contract branch

### Added

- **All 16 orchestrators**: new `## Reporting Contract` section (issues #75, #78), synced from `tools/agent_shared_sections.md`. Sign-off criteria were declarative properties with no rule that they be observed rather than asserted. The contract requires: run every named gate and quote its exact output; never report a gate as passing that was not run this session (report it NOT RUN, and why); exit 0 with empty or unparsable output is not a pass; re-read the deliverable list before finishing; separate measured values from inference; verify the provenance of any generated artifact a test consumes, in every environment that will run the test; and set `signoff` / `signoff_achieved` true only when every criterion is measured-PASS.
- **Codex, Gemini and Copilot headers**: five condensed lines of the contract added to `## Verification and Reporting`.
- **Wrapper JSON `verified` field**: `true` when `status` rests on a result parsed from the output or on a failure; `false` when the tool exited 0 without a recognisable result, or did not run. Documented in the infrastructure skill's wrapper schema.
- **Tests**: `tests/test_wrappers.py` runs each real wrapper through bash against a fake tool (skipped on Windows unless `RUN_WRAPPER_TESTS=1`); `tests/test_mcp_adapter.py` covers how the adapter interprets wrapper output.

### Changed

- **Behaviour change — all 8 EDA wrappers no longer report `PASS` without evidence.** Status was computed from the exit code and ERROR/WARNING lines alone, so a tool that exited 0 and printed nothing the wrapper recognised was a `PASS`. A wrapper now needs a result it parsed from the output; otherwise it reports `WARN` with `verified: false` and says so in the first warning. Evidence is the set of fields each wrapper already extracted — no new log markers. A quiet run (`yosys -q`, a `--version` smoke test) that returned `PASS` now returns `WARN`. The exit code is still propagated unchanged.
  - `wrap-verilator-sim.sh`: `PASS` requires `TEST PASSED`. An ERROR line with exit 0 gives `WARN`, not `FAIL`, since simulation logs print lines such as "Error count: 0".
  - `wrap-klayout.sh`: a report that parses with no categories is a clean run; with no report and no count in the log, `drc_total` is `null` rather than `0`.
- **Behaviour change — `mcp-adapter.py`**: with exit 0, empty wrapper output was `PASS` and non-JSON output was `WARN`; JSON without a valid `status` was passed through. All three are now `FAIL` with `verified: false`, because the wrapper contract is to emit JSON on every run. Valid wrapper JSON is passed through unchanged. `isError` stays tied to `status == "FAIL"`.
- **`mcp-session-adapter.py`**: `query_drc` returns `drc_total: null`, not `0`, when no count could be parsed.

## [Unreleased] — feat/shared-orchestrator-guards branch

### Added

- **Shared orchestrator sections, synced from one source** (issue #77). `tools/agent_shared_sections.md` holds the text every orchestrator carries word for word; `tools/sync_agent_sections.py` writes it into each target between `BEGIN SHARED` / `END SHARED` marker comments. `--check` reports drift and runs in CI, `--list` prints which block goes where. The script preserves each file's line endings, so a CRLF working tree and LF CI agree. Tests in `tests/test_sync_agent_sections.py`.
- **15 orchestrators**: new `## Stage Gating and Escalation` section — read the tool's result before assigning a stage status; never proceed past a FAIL without applying the loop-back rule; on an exhausted loop cap, stop and escalate with state and root cause; when the fault is in an upstream artifact, stop looping and hand back. These guards previously existed in one or two orchestrators each (`pd`, `rtl-design`, `memory-ip`, `architecture`, `infrastructure`); ten domain orchestrators had no rule at all for an exhausted loop cap. `pipeline-orchestrator` is excluded: it dispatches rather than runs stages and owns `pending_approval` type `escalation`.
- **`compiler` and `firmware` orchestrators**: new `### MCP Preference` section. No MCP server or wrapper exists for their toolchains, so it prescribes direct execution with output captured to a log file rather than the MCP → wrapper → direct tier list the EDA domains carry.
- **Codex, Gemini and Copilot headers**: new `## Verification and Reporting` section with the condensed guards. Copilot and Codex installs receive skills only, never agent files.
- **`.gitattributes`**: `* text=auto`, and `*.sh text eol=lf` so shell scripts are runnable from a Windows checkout.

### Changed

- **`pending_approval` ownership made consistent.** The pipeline skill allowed domain orchestrators only `type: "checkpoint"` while also requiring them to set `type: "constraint_gap"`, and a sentence in 15 orchestrators implied they set `pending_approval` on any escalation. Domain orchestrators now set it only at their two gates (checkpoint, constraint validation); an escalation for an exhausted loop cap or an upstream fault is recorded in the terminal `history[]` entry, whose `reason` carries the `failure_class` and what the user must supply. `type: "escalation"` stays reserved for `pipeline-orchestrator`. No schema change.
- **Existing one-off guards** in `pd`, `architecture`, `infrastructure`, `rtl-design` and `memory-ip` keep their rule numbers and now point at the shared section.
- **`validate.yml`**: agents must contain `## Behaviour Rules` (the anchor for the shared sections); new step runs `tools/sync_agent_sections.py --check`.
- **`CONTRIBUTING.md`**: documents the sync step, corrects the file paths in the "Adding a New Skill" steps and the local validation snippet (both referred to a root `skills/` directory that does not exist), and corrects the count rule (skills may exceed agents).
- Stale counts corrected in `CONTRIBUTING.md`, `docs/MASTER_INDEX.md`, `memory/README.md` and `FUTURE_WORK.md`.

## [Unreleased] — fix/signoff-achieved-template branch

### Fixed

- **13 orchestrators**: the `experiences.jsonl` template showed `"signoff_achieved": true` while the surrounding rules say the record is also written on escalation and abandonment (issue #74). `distill.py` counts sign-off with `is True`, so a template defaulting to `true` records failed runs as successes. The template now defaults to `false`, matching `pd` and `infrastructure`, and each one states the success condition directly beneath it (`soc` had no such sentence). A literal `false` is used rather than a `"<true|false>"` placeholder, because a string value never satisfies `is True`. `memory/README.md` carried the same literal in the canonical schema.
- **8 orchestrators** (`dft`, `firmware`, `fpga`, `memory-ip`, `rtl-design`, `sta`, `synthesis`, `verification`): said "append one JSON line" and gave a template with no `run_id`, contradicting `memory/README.md` and their own skills. They now upsert by `run_id` like the rest. The `fpga` skill's separate append-only schema (`stage`, `outcomes`, `metrics`, `tools`), which `distill.py` could not read metrics from, now points at the shared record schema. `README.md` no longer calls the file append-only.
- **6 orchestrators** (`architecture`, `dft`, `firmware`, `formal`, `fpga`, `hls`): the history `decision` enum omitted `await_approval`, which their own checkpoint gate writes.

### Added

- **`tests/test_agent_contract.py`**: static checks on agent and skill markdown — no hardcoded `"signoff_achieved": true`, no append-only wording, every experience template carries `run_id`, and every `decision` enum lists `await_approval` where the agent writes it.

## [1.8.0] — Memory IP Design domain

### Added

- **`chip-design-memory-ip` — 16th plugin, 14th design domain.** Embedded memory IP design (SRAM / register file / ROM): the pipeline previously treated memories as an externally supplied black box — PD placed them, synthesis `dont_touch`ed them, DFT tested them, SoC qualified their views, FPGA swapped them for BRAM — but nothing *produced* one. This domain fills that gap.
  - **`plugins/memory-ip/skills/memory-ip-design/SKILL.md`** — seven stages: `memory_requirements → macro_selection → array_architecture → redundancy_repair → view_generation → integration_prep → memory_signoff`. Covers bandwidth and ECC sizing, column-mux/banking trade-offs, slow-corner access-time selection, write/read assist and Vmin, SECDED check-bit sizing and scrubbing, spare row/column allocation from defect density, soft vs. hard repair and efuse mapping, and view QA (pin consistency across `.lib`/`.lef`/`.v`, timing-arc completeness, corner coverage, LEF obstructions).
  - **`plugins/memory-ip/agents/memory-ip-orchestrator.md`** — stage sequence, seven loop-back rules, sign-off criteria, and an explicit boundary rule: never insert MBIST or claim MBIST coverage (owned by `chip-design-dft`), never floorplan (`chip-design-pd`), never sign off timing (`chip-design-sta`), never assign the memory map (`chip-design-soc`).
  - **`design_state.json` handoff** — new `memory_ip` block carrying `instances`, `views`, `repair` (scheme, spare counts, repair-register width, efuse map), `placement_constraints`, `ecc`, and `power_modes`. DFT consumes `instances` + `repair`; PD consumes `placement_constraints`; STA consumes `views.lib`; verification consumes `views.verilog`.
  - **`constraints.memory_ip`** — `vmin_margin_mv` (50), `repair_yield_pct_min` (99), `ecc_required` (false), `max_aspect_ratio` (4.0), `retention_required` (true). `constraints.dft.mbist_coverage_pct` is read-only here.
  - **`memory/memory-ip/knowledge.md`** seed and `docs/Memory_IP_Design_Flow.md`.
  - `key_metrics`: `memory_instances`, `total_memory_area_um2`, `worst_access_time_ns`, `view_qa_errors`, `projected_repair_yield_pct`.

### Changed

- Counts bumped to **16 plugins / 17 skills / 16 agents / 14 design domains** across `marketplace.json`, `package.json`, `README.md`, `CLAUDE.md`, `docs/PIPELINE.md`, `docs/MASTER_INDEX.md`, `docs/INSTALL.md`, the Codex/Gemini/Copilot IDE headers, and `.github/workflows/release.yml`.
- **Manifest version realigned to the release tag line.** `package.json` and `.claude-plugin/marketplace.json` had drifted to `1.3.0` while tags advanced to `v1.7.0`, and PR #71 bumped them to `1.4.0` — which matched neither the drift nor the tag line, and implied a `v1.4.0` tag after `v1.7.0`. Both now read `1.8.0`, the next tag for this MINOR change (new orchestrator domain, per `CONTRIBUTING.md`). The `npm-publish` job in `release.yml` stamps these fields from the tag at publish time, so the in-repo values are informational — but they should not contradict the tag they will be released under.
- `validate.yml` count asserts 15 → 16 (agents/marketplace and `applyto-map.json`); `tests/test_distill.py` domain count 14 → 15.
- `distill.py`, `tools/qor_trends.py`, `memory/README.md`, and `memory-keeper/SKILL.md` registered the new domain; `projected_repair_yield_pct` added to `HIGHER_IS_BETTER`.
- Installers updated: `install.sh` and `install.ps1` (plugin list, dir map, `enabledPlugins`, OpenCode mode map, completion message) and `bin/install.mjs` (`OPENCODE_MODE_DISPLAY`).

## [Unreleased] — feat/semantic-experience-search branch

### Added

- **Semantic / keyword search over experiences** (FUTURE_WORK item 2): a new way for orchestrators to retrieve prior fixes by relevance to a natural-language query (e.g. "what fixed WNS issues on sky130 before?") instead of reading the whole `experiences.jsonl`.
  - **`tools/experience_search.py`** — core library + standalone CLI. Default backend is a pure-stdlib **TF-IDF + cosine** ranker over the free-text fields (`issues_encountered`, `fixes_applied`, `notes`); reuses the shared `resolve_memory_root`, `load_records`, and `filter_by_design/pdk/tool` helpers so it sees exactly what orchestrators wrote. Returns ranked records with `score`, `matched_terms`, the `backend` used, and a `fell_back`/`fallback_reason` flag. CLI exit codes mirror the repo convention (`0` results, `1` no match, `2` error/bad memory root).
  - **Optional embedding backend, dormant by default** — `get_embedding_backend()` returns `None` until a deployment wires in an embedding library, keeping the repo stdlib-only. It activates only when a backend is available **and** the domain has ≥ `--min-records` records (default **50**, per the issue threshold); otherwise the tool transparently falls back to keyword. Embeddings cache in a stdlib `sqlite3` index (`<domain>/.experience_index.sqlite3`) keyed by record content hash, with incremental `--reindex`.
  - **`plugins/infrastructure/tools/mcp-memory.py`** — dedicated MCP stdio server (protocol `2024-11-05`, same scaffolding as `mcp-adapter.py`) exposing the `query_experiences` tool; **`plugins/infrastructure/mcp/mcp-memory.json`** — config template (server name `chip-design-memory`).
  - **Tests** — `tests/test_experience_search.py` (tokenizer, TF-IDF ranking, filter pre-narrowing, threshold/backend selection, sqlite cache incrementality + stale-hash eviction, CLI exit codes) and `tests/test_mcp_memory.py` (JSON-RPC `initialize`/`tools/list`/`tools/call` smoke + error codes).

### Changed

- **All 15 orchestrators**: added an optional "semantic experience lookup" note to the session-start memory block — call the `query_experiences` MCP tool when available, otherwise proceed with `knowledge.md` only (augments, never replaces). The note is tailored for the router (`pipeline-orchestrator`, queries the target producer domain) and the opt-in `infrastructure-orchestrator`.
- **`memory/README.md`**: new "Semantic / Keyword Experience Search" section documenting the CLI, the MCP server/config, the threshold/fallback semantics, the sqlite cache + `--reindex`, and the optional orchestrator read-path.
- **`FUTURE_WORK.md`**: item 2 marked implemented (phased); documented why the sqlite-vec/Chroma/hosted options were rejected in favor of a stdlib-only keyword default with a pluggable embedding hook.

## [Unreleased] — feat/agent-auto-detect branch

### Added

- **Auto-detection of installed AI coding agents**: running the installer with no `--ide` flag now detects which of the five supported agents (Claude Code, OpenAI Codex, OpenCode, Gemini, GitHub Copilot) are present, prints what it found and where each would write, and installs to them after a confirmation prompt. An agent counts as installed if its CLI is on `PATH` **or** its config directory exists (`~/.claude`, `~/.codex`, `~/.config/opencode`, `~/.gemini`); Copilot is project-scoped and detected via the `gh` / `copilot` CLI. New `bin/detect.mjs` is the single source of truth for the detection signatures.
- **`--yes` / `-y` (sh, mjs) and `-Yes` (ps1)** to skip the confirmation prompt; detection also auto-proceeds in non-interactive shells (CI, pipes).

### Changed

- **`bin/install.mjs` now installs all five targets natively in Node** — no Python dependency. The Copilot / Gemini / OpenCode / Codex generators that previously lived only in the Python blocks of `install.sh` were ported to Node, producing byte-identical output (modulo absolute paths and the "Generated by" comment). Gemini and OpenCode embed runtime file references, so under `npx` the referenced payload is copied to a durable `~/.digital-chip-design-agents/payload/` so the references survive package-dir reclamation. Explicit `--ide` (including `all`) bypasses detection and keeps its prior behaviour.
- **`install.sh` / `install.ps1`** gained the same detection mode (default when no `--ide`/`-IDE`). They still require `python3` (their Claude block reads plugin versions and merges `settings.json` via Python); the fully Python-free path is now the npm installer.
- **`README.md`**: documented auto-detection, the `--yes` flag, and that the npm path now installs every supported target.

## [Unreleased] — feat/structured-failure-handling branch

### Added

- **failure_class → retry_strategy mapping** (FUTURE_WORK item 10): every failure is now categorised into a recovery *strategy* — `regenerate | refine | escalate` — so retry behaviour is determined programmatically rather than by prose. The authoritative mapping is defined once in `plugins/meta/skills/pipeline-orchestration/SKILL.md` under `### Failure Classification & Retry Strategy`, reusing the existing 10-value `failure_class` enum (no new taxonomy). The four classes from the original draft (`invalid_rtl | verification_failure | interface_mismatch | incomplete_spec`) are reconciled as documented aliases.
  - **`regenerate`** — discard the faulty artifact and re-run the generating stage from a clean slate (`drc_lvs`, `connectivity`, `tool_error`).
  - **`refine`** — re-run targeting a specific defect with detailed feedback (`functional`, `timing`, `power_area`, `coverage_gap`).
  - **`escalate`** — halt and request human input (`spec_gap`, `resource_limit`); `none` ⇒ no retry.
- **`retry_strategy` history-entry field (`format_version "1.5"`)**: every `history[]` entry now carries `retry_strategy`, derived deterministically from `failure_class`. The pipeline-orchestrator decision table gains a `retry_strategy` column and branches on it as a coarse pre-filter (existing `confidence`/`suggested_next_step` precedence preserved; `resource_limit` and `low` confidence still always escalate).
- **Actionable escalation guidance**: when a strategy resolves to `escalate` or a max-iteration cap is hit, `pending_approval.reason` must state the `failure_class` plus a plain-language description of what the user must supply to unblock the flow.
- **Updated example fixtures**: `design_state.checkpoint.json` and `design_state.fix_request.json` bumped to `"1.5"` with `retry_strategy` on every history entry; the checkpoint fixture adds an illustrative `timing`/`refine` `synth_check` loop-back entry to exercise the non-`none` path.

### Changed

- **`format_version "1.5"`**: new capability tier covering the `retry_strategy` field and programmatic retry branching. All 14 history-writing orchestrators (the 13 domain orchestrators + infrastructure) upgrade to `"1.5"` on first write — including compiler/firmware/infrastructure, which advance from `"1.3"`; prior-version files remain readable (`retry_strategy` absent → derive from `failure_class`).
- **All 14 orchestrators + `pipeline-orchestrator.md`**: added `retry_strategy` to the Stage Agent Output Format and `history[]` schema (now 10 fields), updated the per-stage-trace behaviour rule to set and require it, and bumped the format_version upgrade step.
- **CI** (`validate.yml`): added `"1.5"` to `VALID_FORMAT_VERSIONS`, a `VALID_RETRY_STRATEGY` set and `RETRY_STRATEGY_MAP`, and a `check_retry_strategy` helper that validates each 1.5 history entry's `retry_strategy` against the value **and** its `failure_class` mapping, applied to both example fixtures.
- **`memory/README.md`**: documented `retry_strategy` in the `history[]` field list and added the `"1.4"` and `"1.5"` format_version tiers.

## [Unreleased] — feat/infrastructure-memory branch

### Added

- **Infrastructure orchestrator memory** (FUTURE_WORK item 4): opt-in, environment-keyed persistent tracking of tool versions and setup configuration under `memory/infrastructure/`, following the existing two-tier memory pattern (`knowledge.md` + `experiences.jsonl`).
  - **Opt-in, default off**: the infrastructure-orchestrator reads/writes `memory/infrastructure/` only when `design_state.pipeline_config.track_infrastructure == true` or it is invoked with `--track-memory`. When unset, no `memory/infrastructure/` I/O occurs — prior (memory-free) behavior is unchanged. This respects the original deferral rationale (infra state is environment-specific; lockfiles remain the primary version source of truth).
  - **Environment-keyed records**: each `experiences.jsonl` record carries an `environment` fingerprint (`host`, `os`, `os_version`, `arch`) and a `key_metrics.tool_versions` per-tool version map captured at `environment_validation` — the core value-add for diagnosing repeated version-mismatch debugging across sessions. Records are differentiated by environment, not by design (`design_name` is typically `null`).
  - **Seeded `memory/infrastructure/knowledge.md`**: Tier-2 summary with known env-mismatch failure patterns (e.g. Verilator < 5.0 lacks `--timing`, OpenROAD nightly vs release ABI drift, module-unload python3 fallback), successful flags/install notes, and tool quirks.
  - **Full memory-keeper integration**: `infrastructure` registered in `distill.py` `VALID_DOMAINS` and `METRIC_FIELDS` (`tools_detected`, `tools_missing`, `wrappers_deployed`, `mcp_servers_configured`) and added to the memory-keeper SKILL Domains table, so infrastructure quirks distil into `knowledge.md` via `/chip-design-infrastructure:memory-keeper --domain infrastructure`.

### Changed

- **`memory/README.md`**: added `infrastructure/` to the Directory Layout, an `infrastructure` row to the Domain key_metrics Fields table, and a new "Infrastructure memory (opt-in, environment-keyed)" subsection documenting the activation flag and env-keyed records.
- **`infrastructure-orchestrator.md`**: added Behaviour Rule 8 and an "Infrastructure Memory" section specifying the activation gate, session-start read, post-`environment_validation` upsert, and the environment-keyed record schema.

## [Unreleased] — feat/central-constraint-handling branch

### Added

- **Dynamic constraint loading from `design_state.constraints`** (FUTURE_WORK item 8): `design_state.constraints` is now the single source of truth for all design constraint values — clock target, area/power budgets, timing sign-off thresholds (WNS/TNS), utilisation targets, IR-drop limits, leakage budget, coverage targets, fault-coverage targets, HLS II/latency, and FPGA resource limits. All 11 constraint-bearing domain SKILL.md files now reference constraint keys (e.g. `design_state.constraints.timing.wns_ns_target`) instead of hardcoded literals; the literals are retained as documented defaults for backward compatibility.
- **Comprehensive `constraints` schema (`format_version "1.4"`)**: authoritative schema defined once in `plugins/meta/skills/pipeline-orchestration/SKILL.md` under `### Constraints Schema`. Nested by category: `clock`, `pvt_corners[]`, `timing`, `area`, `power`, `coverage`, `dft`, `hls`, `fpga`. All non-null defaults match the literals previously hardcoded in SKILL.md files.
- **Stage-entry constraint validation** (hard-fail on missing required constraints): every constraint-bearing orchestrator now reads `design_state.constraints` at its entry stage and, for each key in its required subset, performs an atomic RMW to set `pending_approval.type = "constraint_gap"` and halts when the key is missing or null. Optional constraints fall back to schema defaults with a WARN history entry. Required subsets: `clock.clk_mhz` (architecture, rtl-design, synthesis, sta, pd, soc, fpga); `area.area_um2` + `power.power_mw` (architecture, synthesis, pd); `pvt_corners` with non-null V/T (sta, pd); at least one of `hls.target_ii` or `hls.target_latency_cycles` (hls).
- **`pending_approval.type: "constraint_gap"`**: new discriminator value for the existing `pending_approval` mechanism. Pipeline-orchestrator prints a type-specific message directing the user to populate the missing constraint keys and clear `pending_approval` to resume.
- **`constraint_ref` tagging**: `history[]` entries now carry the dot-path constraint key compared at each QoR evaluation step (e.g. `"timing.wns_ns_target"`, `"power.power_mw"`, `"clock.clk_mhz"`), making every stage decision traceable to the constraint that gated it.
- **Updated `design_state.checkpoint.json` example**: `format_version` bumped to `"1.4"`, full `constraints` block added for `example_dsp_core` (500 MHz, 28nm), and `constraint_ref` set to real dot-path keys on `perf_modelling` (`"power.power_mw"`), `power_area_estimation`, `module_planning` (`"clock.clk_mhz"`), and `synth_check` (`"timing.wns_ns_target"`) history entries.

### Changed

- **`format_version "1.4"`**: new capability tier covering the full `constraints` object, stage-entry constraint validation, and `pending_approval.type: "constraint_gap"`. All 15 orchestrators upgrade to `"1.4"` on first write; prior-version files remain readable (`constraints` absent → apply schema defaults; missing `pending_approval.type` → treat as `"escalation"`).
- **Architecture orchestrator** (`architecture-orchestrator.md`): expanded `constraints` stub from `{clk_mhz, area_um2, power_mw}` to the full nested schema; added Behaviour Rule 8 (populate constraints during `spec_analysis`) and Behaviour Rule 9 (hard-fail if required keys remain null after extraction).
- **All 11 domain SKILL.md files** updated: `### QoR Metrics` and constraint-bearing `### Domain Rules` sections reworded to reference `design_state.constraints.<key>` with the prior literal as a documented default; each file gained a `## Constraint Validation` section listing the domain's required and optional keys.
- **`formal` and `dft` orchestrators**: `constraints` added to Design State Read extract list (was previously missing).
- **CI**: no schema-validation changes required — the edits are to tracked `.md` and `.json` files already covered by the existing lint checks.

---

## [Unreleased] — feat/approval-gates-traceability branch

### Added

- **Approval checkpoints** (FUTURE_WORK item 11, part A): proactive human-in-the-loop gates at any orchestrator's sign-off boundary, controlled by `pipeline_config.checkpoints[]` in `design_state.json`. Default positions: `arch_signoff`, `rtl_signoff`, and `signoff` (PD tape-out). When a checkpoint fires, the orchestrator sets `pending_approval { type: "checkpoint", stage, agent }` and halts without completing sign-off; the user resumes by adding the stage to `approved_checkpoints[]` and re-invoking. Empty `checkpoints` ⇒ fully autonomous (backward compatible).
- **Per-stage execution trace** (FUTURE_WORK item 11, part B): all 15 orchestrators now append one `history[]` entry per completed stage (PASS/FAIL/WARN) rather than a single terminal entry per run. Enables post-run audits without replaying the full agent conversation. Entry shape is unchanged (9-field schema).
- **`format_version "1.3"`**: new capability tier in `design_state.json` covering checkpoints + per-stage trace. All orchestrators upgrade to `"1.3"` on first write; prior-version files remain readable.
- **`design_state.checkpoint.json` fixture**: new golden example under `plugins/meta/skills/pipeline-orchestration/examples/` demonstrating a `pending_approval { type: "checkpoint" }` pause, `approved_checkpoints[]` entry, and per-stage history trace across architecture → RTL stages.

### Changed

- **`pending_approval` schema extended**: added `type` (`checkpoint` | `escalation`), `stage`, and `agent` fields. Backward-compatible — readers treating missing `type` as `"escalation"` remain correct.
- **Ownership rules amended**: domain orchestrators may now set `pending_approval` with `type: "checkpoint"` at their own sign-off stage; `type: "escalation"` remains the sole responsibility of the pipeline-orchestrator.
- **`pipeline_config` extended**: added `checkpoints` array (list of stage name strings, default `[]`).
- **`approved_checkpoints[]` added**: new top-level field; each entry `{ "stage", "approved_at", "approved_by" }`. Written by the user or by an orchestrator acting on an explicit approval instruction.
- **All 15 orchestrators updated**: Design State Read now extracts `pipeline_config` and `approved_checkpoints`; Design State Write upgrades `format_version` to `"1.3"`; all orchestrators carry two new Behaviour Rules (per-stage trace + checkpoint gate).
- **CI validation extended**: `VALID_FORMAT_VERSIONS` now includes `"1.3"`; new inline Python checks for `pipeline_config.checkpoints`, `approved_checkpoints`, `pending_approval.type`; both fixtures validated on every PR.
- **`memory/README.md`** updated with `format_version 1.3` tier, `checkpoints`, `approved_checkpoints`, and extended `pending_approval` field documentation.

---

## [Unreleased] — feat/rtl-verify-feedback-loop branch

### Added

- **Closed-loop verification↔RTL feedback** (FUTURE_WORK item 6): verification and formal orchestrators now write structured `fix_request` entries to `design_state.json` when a DUT bug or formal CEX is found, instead of suspending with prose-only output. The new `chip-design-meta` plugin (`plugins/meta/agents/pipeline-orchestrator.md`) detects open `fix_requests`, dispatches the RTL orchestrator to fix the bug, re-runs the originating verification or formal check, and loops up to 3 cross-domain iterations before escalating via `pending_approval`.
- **`fix_request` schema** (`format_version 1.1`): two new top-level fields in `design_state.json` — `fix_requests[]` (structured bug handoff with id, failure_class, suspected_rtl, waveform_path, status lifecycle) and `cross_domain_iteration_count` (integer cap enforced by the pipeline-orchestrator). Fully backward-compatible — all existing readers treat missing keys as null/zero.
- **`chip-design-meta` plugin** (`plugins/meta/`): 15th plugin in the marketplace, with `pipeline-orchestrator` agent, `pipeline-orchestration` skill (hosts authoritative fix_request schema and dispatch patterns), and persistent memory under `memory/meta/`.
- **Formal orchestrator fix_request support**: `formal-orchestrator.md` now writes `failure_class=formal_cex` fix_requests (including CEX trace path) on property counter-example, matching the verification orchestrator's protocol. Both route to the RTL orchestrator for fixing in V1.

### Changed

- **Plugin count**: 14 → 15 plugins. CI assertion in `validate.yml` and `ides/copilot/applyto-map.json` domain count updated accordingly.
- **`verification-orchestrator.md`**: loop-back rule for `directed_tests DUT bug found` and Behaviour Rule 4 updated to write structured fix_requests and exit with `decision=escalate`; Design State Read step extended to handle re-invocation context.
- **`rtl-design-orchestrator.md`**: Design State Read step extended to detect and claim open fix_requests; new Behaviour Rule 6 documents the fix_request close protocol.
- **`functional-verification/SKILL.md`**: Domain Rule 7 updated from "suspend and wait for confirmation" to "write fix_request and terminate for pipeline-orchestrator dispatch".
- **`memory/README.md`**: design_state.json schema documentation updated with `fix_requests[]`, `cross_domain_iteration_count`, and `format_version 1.1` details.
- **Divergence detection scoped to current session** (`pipeline_session_id`): the pipeline-orchestrator divergence check now compares only against `status=fixed` entries sharing the same `pipeline_session_id`, preventing false escalations when the same bug class legitimately recurs after a refactor in a later session.
- **Archival on signoff**: pipeline-orchestrator success branch moves resolved `fix_requests[]` entries into `design_state.archive_fix_requests[]` and resets session state, preventing unbounded array growth across long-running designs.
- **Configurable iteration cap** (`pipeline_config.max_cross_domain_iterations`): iteration limit lifted from hardcoded `3` to a user-tunable field in `design_state.json` (default 3 if absent). Set the field to tune per-design without editing agent files.
- **LEC unmatched-points loop intentionally deferred to V2**: `lec_run: unmatched points` in `formal-orchestrator.md` is not connected to the fix_request protocol in V1 — proper support requires `synthesis-orchestrator` as a consumer. Documented in `pipeline-orchestration/SKILL.md` V2 extension points.
- **Removed vestigial per-entry `iteration_count`** (S1): `fix_request` schema no longer includes `iteration_count` — the field was always 0 or 1 in practice because re-failures open a *new* entry. The top-level `cross_domain_iteration_count` is the sole iteration counter. Removed from `meta/SKILL.md`, both producer agent schemas, `rtl-design-orchestrator.md` Behaviour Rule 6 and Write step 5a, the fixture, and CI `REQUIRED_FIELDS`.
- **Seeded `memory/meta/experiences.jsonl`** (S7): two illustrative records added — one `converged` (single-iteration MAC unit fix) and one `escalated` (AXI DMA cap exceeded after 3 iterations).
- **Marketplace version bump** and **README reconciliation** (Cosmetic): `metadata.version` bumped to `1.3.0`; README header updated to "15 plugins · 16 skill files"; `chip-design-meta` added to the Available Plugins table.

---

## [Unreleased] — agent-scope-review branch

### Added
- **Pre-run context** (`## Pre-run Context`) section added to all 13 domain SKILL.md files:
  agents now read `knowledge.md` and `run_state.md` at every invocation point, not only
  at orchestrator session start.
- **Run-state tracking**: all 13 domain SKILL.md files and the PD orchestrator now write
  `memory/<domain>/run_state.md` as the first action before any tool invocation; `last_stage`
  is updated after each stage so wakeup-loop prompts can resume correctly.
- **Per-stage experience writes**: PD orchestrator (and all domain skills) now upsert to
  `experiences.jsonl` after each stage rather than only on session end; partial runs are
  persisted even if the session is interrupted.
- **Optional claude-mem integration**: all 13 domain skills and the memory-keeper skill now
  emit applied fixes to `mcp__plugin_ecc_memory__add_observations` when the MCP tool is
  present; guard clause skips silently when absent so JSONL remains the canonical record.
- **Clock gating opportunity analysis** added to `architecture` SKILL.md
  (`power_area_estimation` stage): classifies each clock domain by activity factor α,
  produces a `clock_power_budget` hand-off table (domain → frequency, α, est. clock power,
  gating class), and enforces a new QoR gate (≥ 70% of register bits in gateable domains).
- **Power intent / ICG insertion rules** added to `rtl-design` SKILL.md (`rtl_coding` stage):
  RTL agent reads `clock_power_budget` from architecture hand-off and inserts ICG cells for
  high/moderate gating domains; enforces `clock_gating_coverage` ≥ 60% QoR gate.
- **Architecture → RTL handoff contract** updated in `docs/MASTER_INDEX.md` to include
  `clock_power_budget` artifact.
- `memory/README.md` updated to document run_state.md, per-stage write semantics, `run_id`
  schema field, and the optional claude-mem index pattern.
- `docs/Architecture_Evaluation_Flow.md` and `docs/RTL_Design_Flow.md` updated to match
  the new clock gating analysis and ICG insertion rules added to the live SKILL.md files.
- OpenROAD MCP config (`mcp-openroad.json`) comment improved to call out the two placeholder
  values that require substitution during installation.

---

## [1.2.0] — 2026-04-14

### Added
- Multiple IDE support: GitHub Copilot, Google Gemini Code Assist, and OpenCode
- `ides/copilot/` — Copilot workspace instructions and per-domain file-glob mapping (`applyto-map.json`)
- `ides/gemini/` — preamble header injected into a generated `GEMINI.md`
- `ides/opencode/` — base OpenCode config template with all 13 chip-design modes
- `install.sh --ide <copilot|gemini|opencode|all>` flag to deploy IDE-specific config into the target project
- `install.ps1 -IDE <copilot|gemini|opencode|all>` equivalent for Windows PowerShell
- CI/CD validation extended to lint IDE config files on every PR

### Changed
- Agents and skills updated with explicit EDA tool usage annotations
- AgentShield CI step removed (no `.claude` directory present in repo)

---

## [1.1.1] — 2026-04-13

### Added
- AgentShield CI check to validate Claude agent files on every PR

### Fixed
- Issues reported after CodeRabbit review pass on the AgentShield integration

---

## [1.1.0] — 2026-04-13

### Added
- Install scripts for all OS: `install.sh` (macOS / Linux / Git Bash) and `install.ps1` (Windows PowerShell)
- `strict: true` set in `marketplace.json` to enforce exact plugin paths

### Changed
- **Breaking restructure:** all 13 agents and skills split from a shared flat directory into isolated per-plugin subdirectories (`plugins/<domain>/agents/` and `plugins/<domain>/skills/`) to eliminate file-system racing conditions when multiple plugins load concurrently
- Each plugin now has its own `.claude-plugin/plugin.json` manifest
- CI/CD updated for the new directory layout
- README updated to document the new structure and remove the prior racing-issue caveat

### Fixed
- Recursion guard added to agent and skill invocation chains
- Agents now read their skill file before executing; skills now spawn the corresponding orchestrator before executing

---

## [1.0.3] — 2026-04-12

### Fixed
- Marketplace recursive-directory bug: strengthened schema checks to enforce path typing and prevent the marketplace registry from resolving into subdirectories recursively

---

## [1.0.2] — 2026-04-12

### Fixed
- Validate CI and `plugin.json` incorrect formatting (follow-up to v1.0.1)

---

## [1.0.1] — 2026-04-12

### Fixed
- Validate CI pipeline failures on initial setup
- `plugin.json` formatting errors flagged by the CI linter
- Minor environment file corrections reported by CodeRabbit
- Removed stray `.claude` settings file from repo root

---

## [1.0.0] — 2026-04-12 — Initial Release

### Added
- 13 Claude Code marketplace plugins covering the complete digital chip design pipeline
- 13 skill files with YAML frontmatter, staged domain rules, QoR metrics, and fix guidance
- 13 orchestrator agent markdown files with stage sequences, loop-back rules, and sign-off criteria
- `.claude-plugin/plugin.json` — Claude Code plugin manifest
- `.claude-plugin/marketplace.json` — marketplace registry for all 13 plugins
- CI validation workflow (GitHub Actions) — validates every PR
- Automated release workflow with tar.gz archive generation

### Domains in v1.0.0
Architecture Evaluation · RTL Design (SystemVerilog) · Functional Verification (UVM) ·
Formal Verification (FPV/LEC) · Logic Synthesis · Design for Test (DFT) ·
Static Timing Analysis (STA) · High-Level Synthesis (HLS) · Physical Design ·
SoC IP Integration · Compiler Toolchain (LLVM) · Embedded Firmware · FPGA Emulation
