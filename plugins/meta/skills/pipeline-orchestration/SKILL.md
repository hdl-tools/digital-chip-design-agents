---
name: pipeline-orchestration
description: >
  Cross-domain loop orchestration for the chip design pipeline. Provides the
  fix_request protocol, iteration-cap logic, escalation templates, and dispatch
  patterns for routing verification/formal failures to the RTL orchestrator and
  back. Use when driving the closed-loop verification↔RTL feedback cycle.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: Pipeline Orchestration

## Invocation

- **If invoked by a user** presenting a pipeline loop task: immediately spawn the
  `digital-chip-design-agents:pipeline-orchestrator` agent and pass the full user
  request and any available context. Do not execute stages directly.
- **If invoked inside another orchestrator**: read `design_state.json`, summarise open
  `fix_requests[]`, and return — do not spawn subagents (anti-recursion rule).

## Purpose

This skill provides the closed-loop verification↔RTL feedback protocol. When a DUT bug
is found during simulation or formal verification, it must be communicated to the RTL
orchestrator in a machine-actionable way and the pipeline must iterate until the bug is
fixed or the iteration limit is reached.

The protocol has three participants:

| Participant | Role |
|---|---|
| **verification-orchestrator** / **formal-orchestrator** | Detects the bug; writes a `fix_request` entry to `design_state.fix_requests[]` with `status=open`; terminates with `decision=escalate`. |
| **rtl-design-orchestrator** | Reads the open `fix_request`; sets `status=claimed`; fixes the RTL; sets `status=fixed` with `rtl_response`; terminates. |
| **pipeline-orchestrator** | Detects open entries; assigns a `pipeline_session_id`; dispatches RTL then re-verification in sequence; enforces a configurable cap (default 3, via `pipeline_config.max_cross_domain_iterations`); scopes divergence checks to the current session; archives resolved entries on signoff; escalates via `pending_approval` if cap exceeded. |

## Domain Rules

### fix_request Schema (authoritative)

All entries in `design_state.fix_requests[]` must conform to this schema. The
machine-readable companion is `docs/design_state.schema.json` (JSON Schema Draft
2020-12), which CI validates fixtures against — it is the authoritative encoding
of the enums, required fields, and the `failure_class → retry_strategy` map below.

```json
{
  "id": "fr_<pipeline_session_id>_<YYYYMMDD>_<HHMMSS>_<seq>",
  "created_at": "<ISO-8601>",
  "updated_at": "<ISO-8601>",
  "created_by": "verification-orchestrator | formal-orchestrator",
  "failure_class": "functional | protocol | coverage_gap | formal_cex",
  "retry_strategy": "refine",
  "test_name": "<directed test or property name>",
  "property_or_assertion": "<assertion id or null>",
  "seed": 0,
  "waveform_path": "<path or null>",
  "log_path": "<path or null>",
  "suspected_rtl": {
    "module": "<module name>",
    "signal": "<signal or null>",
    "file": "<rtl/path.sv or null>",
    "line_range": [0, 0],
    "basis": "traced | hypothesis"
  },
  "summary": "<one-line bug description>",
  "expected_behavior": "<spec excerpt or null>",
  "observed_behavior": "<observed RTL behaviour>",
  "session_id": "<pipeline_session_id or null>",
  "status": "open | claimed | fixed | abandoned",
  "rtl_response": null,
  "history": []
}
```

> **`suspected_rtl.basis` (optional).** `traced` means the producer followed the failure to
> this signal in a waveform or CEX trace; `hypothesis` means the location is inferred from the
> symptom. The RTL orchestrator treats `hypothesis`, an absent `basis`, or `line_range: [0, 0]`
> as a guess and confirms the cause before editing. A misdiagnosed `suspected_rtl` is the usual
> root cause of a loop that reaches the iteration cap, so producers should not claim `traced`
> for a location they did not observe.

> **Reserved field — `route_to` (optional).** The schema accepts an optional
> `route_to` string naming the servicer domain for a fix (default: `rtl-design`).
> It is **forward-compatible scaffolding only**: the pipeline-orchestrator
> currently always dispatches the RTL orchestrator (`dispatch_to_producer`), so
> producers need not set it. It exists so multi-servicer dispatch can be added
> later without a schema migration, mirroring the analog pipeline.

`rtl_response` (populated by rtl-design-orchestrator on close):
```json
{
  "fixed_at": "<ISO-8601>",
  "diff_summary": "<one-paragraph description of changes>",
  "files_changed": ["rtl/path.sv"],
  "commit_ref": null
}
```

`fix_request.history[]` — one entry per state transition:
```json
{
  "timestamp": "<ISO-8601>",
  "agent": "<agent name>",
  "from_status": "<previous status>",
  "to_status": "<new status>",
  "note": "<optional one-liner>"
}
```

### Ownership rules

- `rtl-design-orchestrator` owns the `open→claimed` and `claimed→fixed|abandoned` transitions.
- Only the `rtl-design-orchestrator` sets `status=claimed→fixed` or `claimed→abandoned`.
- Only the `pipeline-orchestrator` sets `cross_domain_iteration_count`, `pipeline_session_id`, `pipeline_config`, and moves resolved entries to `archive_fix_requests[]`.
- Domain orchestrators **may** set `pending_approval` only at their two gates: `type: "checkpoint"` at their own sign-off stage, and `type: "constraint_gap"` at stage-entry constraint validation. `type: "escalation"` remains the sole responsibility of the `pipeline-orchestrator`. A domain orchestrator that escalates for any other reason (loop cap exhausted, fault in an upstream artifact) records it in the terminal `history[]` entry and does not set `pending_approval`.
- `approved_checkpoints[]` is written by the user (or by an orchestrator executing an explicit approval instruction) and read by all orchestrators.
- All agents may append to `fix_request.history[]` but must not overwrite each other's entries.

### Iteration cap

`cross_domain_iteration_count` in `design_state.json` tracks the total number of
verification↔RTL dispatch cycles for the current pipeline session. The cap is controlled by
`pipeline_config.max_cross_domain_iterations` (default: 3 if absent). The orchestrator treats the cap as "reaches or exceeds" (use `>= max_cross_domain_iterations`), writing a `pending_approval` entry and exiting as soon as the iteration count is equal to or greater than the cap, preventing an off-by-one extra cycle before escalation:

```json
{
  "pending_approval": {
    "type": "escalation",
    "stage": null,
    "agent": "pipeline-orchestrator",
    "reason": "fix_request loop exceeded 3 cross-domain iterations",
    "fix_request_id": "<id>",
    "last_summary": "<last rtl_response.diff_summary>",
    "requires_user": true
  }
}
```

The user must review the escalation, manually fix the RTL or adjust the testbench, then
clear `pending_approval` (set to `null`) and reset `cross_domain_iteration_count` to 0
before invoking the pipeline-orchestrator again. Optionally increase
`pipeline_config.max_cross_domain_iterations` if more iterations are warranted.

### Pipeline session fields

Top-level fields in `design_state.json` managed by the `pipeline-orchestrator` and related infrastructure:

- **`pipeline_session_id`** (`"ps_<YYYYMMDD>_<HHMMSS>"` or `null`): identifies the active pipeline run. Set on entry, cleared (set to null) on successful signoff. Scopes divergence checks and archival to the current session — entries from prior sessions are ignored by the divergence check.
- **`pipeline_config`** (`object`): user-tunable pipeline settings. Written with defaults on first run; never overwritten if already present.
  - `max_cross_domain_iterations` (integer, default 3): the iteration cap for the feedback loop.
  - `checkpoints` (array of strings, default `[]`): stage names that require human approval before the producing orchestrator may declare sign-off. Empty array ⇒ fully autonomous (preserves today's behavior). Example default: `["arch_signoff", "rtl_signoff", "signoff"]`. Written by the user; domain orchestrators read but never overwrite this field.
- **`approved_checkpoints[]`**: list of stages the user has approved. Schema per entry: `{ "stage": "<stage name>", "approved_at": "<ISO-8601>", "approved_by": "user" }`. Written by the user (or by an orchestrator acting on an explicit approval instruction); read by all orchestrators at their sign-off gate check.
- **`archive_fix_requests[]`**: resolved entries from completed pipeline sessions, moved here by the pipeline-orchestrator on successful signoff. Same schema as `fix_requests[]`. Never written by domain orchestrators.

### Constraints Schema (authoritative)

`design_state.constraints` is the single source of truth for design-intent parameters across all
domain orchestrators. Defined once here; domain SKILL.md files reference these keys and document
their default fallbacks.

```json
"constraints": {
  "clock": {
    "clk_mhz": null,
    "clk_uncertainty_ps": null
  },
  "pvt_corners": [
    { "name": "ss_setup", "process": "SS", "voltage_v": null, "temp_c": null, "checks": ["setup"] },
    { "name": "ff_hold",  "process": "FF", "voltage_v": null, "temp_c": null, "checks": ["hold"] }
  ],
  "timing": {
    "wns_ns_target": 0,
    "tns_ns_target": 0,
    "fanout_max": 32,
    "skew_ps_max": 100,
    "transition_ps_max": 200,
    "insertion_delay_ps_max": 500
  },
  "area": {
    "area_um2": null,
    "utilization_pct_target": 75,
    "utilization_pct_max": 85
  },
  "power": {
    "power_mw": null,
    "leakage_pct_max": 15,
    "ir_drop_pct_max": 5,
    "gating_coverage_pct_min": 60,
    "activity_factors": { "default": 0.15, "high": 0.40 }
  },
  "coverage": {
    "functional_pct": 100,
    "line_pct": 95,
    "branch_pct": 90,
    "toggle_pct": 85,
    "fsm_state_pct": 100,
    "fsm_transition_pct": 95,
    "assertion_pct": 100
  },
  "dft": {
    "saf_coverage_pct": 99,
    "transition_coverage_pct": 95,
    "cell_aware_coverage_pct": 95,
    "bridging_coverage_pct": 90,
    "mbist_coverage_pct": 99,
    "chain_balance_pct": 5
  },
  "hls": {
    "target_ii": null,
    "target_latency_cycles": null,
    "cosim_tolerance_pct": 5
  },
  "memory_ip": {
    "vmin_margin_mv": 50,
    "repair_yield_pct_min": 99,
    "ecc_required": false,
    "fit_target_fit_per_mb": 100,
    "max_aspect_ratio": 4.0,
    "retention_required": true
  },
  "fpga": {
    "lut_util_pct_max": 70,
    "bram_util_pct_max": 80,
    "dsp_util_pct_max": 80
  }
}
```

Non-null values are **documented defaults** matching current hardcoded SKILL.md literals.
`null` values must be supplied by the user for constraint-bearing domains.

#### Required vs. optional constraints

| Constraint key | Required by (hard-fail if missing/null) |
|---|---|
| `clock.clk_mhz` | architecture, rtl-design, synthesis, sta, pd, soc, fpga |
| `area.area_um2` | architecture, synthesis, pd |
| `power.power_mw` | architecture, synthesis, pd |
| `pvt_corners` (≥1 entry with non-null `voltage_v` and `temp_c`) | sta, pd |
| `hls.target_ii` or `hls.target_latency_cycles` (at least one non-null) | hls |

All other keys are **optional** — absent keys fall back to the schema default with a WARN.

#### Stage-entry constraint validation rule

Every constraint-bearing domain orchestrator applies this rule at the **first stage** that
consumes design constraints. Skip entirely when invoked in fix-request-servicing mode (a
`fix_request.id` was passed in the prompt):

1. Read `design_state.constraints`. Treat missing key as `{}`.
2. For each key in this domain's **required** set: if missing or `null`, perform atomic RMW —
   set `pending_approval`:
   ```json
   {
     "type": "constraint_gap",
     "stage": "<entry stage name>",
     "agent": "<this-orchestrator>",
     "reason": "required constraint <key> missing from design_state.constraints",
     "fix_request_id": null,
     "last_summary": "<comma-separated list of missing keys>",
     "requires_user": true
   }
   ```
   Append a `history[]` entry: `decision: "escalate"`, `confidence: "high"`,
   `failure_class: "spec_gap"`, `suggested_next_step: "escalate"`,
   `constraint_ref: "<missing key>"`. Print the gate message and **halt**.
3. For **optional** absent constraints: use the schema default, continue, and include a
   fallback note in the stage's history `reason` field.

**Resume path**: populate the missing constraint(s) in `design_state.constraints`, set
`pending_approval = null`, and re-invoke the orchestrator.

#### Decision tagging via `constraint_ref`

In every `history[]` entry emitted after a stage that evaluates QoR against a constraint, set
`constraint_ref` to the primary constraint key compared using dot-path notation
(e.g. `"timing.wns_ns_target"`, `"clock.clk_mhz"`, `"area.utilization_pct_max"`).
Comma-separate if a stage gates on multiple keys. All other history entries retain
`constraint_ref: null`.

#### Decision tagging via `retry_strategy`

In every `history[]` entry, set `retry_strategy` to the value mapped from the entry's
`failure_class` per the Failure Classification & Retry Strategy section. Entries with
`failure_class: "none"` (PASS, `await_approval`) use `retry_strategy: "none"`. This field
is the strategy label read by the pipeline-orchestrator alongside `confidence` and
`suggested_next_step`.

### Failure Classification & Retry Strategy

Every failure is categorised so recovery is determined programmatically rather than by
prose. Two fields work together on each `history[]` entry:

- `failure_class` — *what* went wrong (the existing 10-value enum, unchanged).
- `retry_strategy` — *how* to recover, derived deterministically from `failure_class`.

`retry_strategy` ∈ `none | regenerate | refine | escalate`:

- **regenerate** — discard the faulty artifact and re-run the *generating* stage from a clean
  slate using the error log as context (malformed/invalid output: tool crash, DRC/LVS,
  broken connectivity). Concrete action is typically `retry_stage` or
  `loop_back_to:<generating stage>`.
- **refine** — keep the artifact and re-run the stage targeting a *specific* identified defect
  with detailed feedback (failing test + waveform, timing path, coverage hole, violated
  interface). Iterative, not from scratch. Action is typically `loop_back_to:<stage>`,
  usually carrying a `fix_request`.
- **escalate** — halt and request human input; the result cannot be improved automatically
  (ambiguous spec) or a budget/cap was hit. Action is `escalate` / `abandon`.
- **none** — no failure (PASS or `await_approval`); pairs only with `failure_class: "none"`.

`retry_strategy` is the strategy *label*; `suggested_next_step` remains the concrete *action*.
They are complementary, not redundant.

#### Mapping (authoritative — `failure_class` → default `retry_strategy`)

This table is mirrored into every domain orchestrator by the `failure-classification` block
in `tools/agent_shared_sections.md`, so an orchestrator can derive `retry_strategy` without
loading this skill. **When editing the table below, update that block and run
`python3 tools/sync_agent_sections.py`.**
`tests/test_agent_contract.py::test_retry_strategy_mapping_matches_the_authoritative_table`
fails if the two drift.

| `failure_class` | `retry_strategy` | rationale | legacy alias |
|---|---|---|---|
| `none` | `none` | no failure | — |
| `functional` | `refine` | re-run rtl_coding with failing test + waveform | verification_failure |
| `timing` | `refine` | re-run optimisation targeting failing paths | — |
| `power_area` | `refine` | re-run targeting the budget overage | — |
| `coverage_gap` | `refine` | add targeted stimulus to close holes | — |
| `connectivity` | `refine` | re-run targeting the violated interface/connection | interface_mismatch |
| `drc_lvs` | `regenerate` | re-run place/route from a clean state | — |
| `tool_error` | `regenerate` | re-run the same stage from scratch (≡ `retry_stage`) | invalid_rtl |
| `spec_gap` | `escalate` | ambiguous/missing spec — needs user clarification | incomplete_spec |
| `resource_limit` | `escalate` | iteration cap / memory exceeded — human decision | — |

The "legacy alias" column reconciles the four classes proposed in an earlier draft
(`invalid_rtl | verification_failure | interface_mismatch | incomplete_spec`) onto the live
enum — no separate taxonomy is introduced. Producers that emit a `fix_request`
(verification, formal) set its `retry_strategy` to `refine` (all their classes map to refine).

#### Actionable escalation guidance

Whenever `retry_strategy` resolves to `escalate` **or** a max-iteration cap is hit, the
escalation `reason` must state both the `failure_class` and a plain-language description of
what the user must supply to unblock the flow. For a domain orchestrator that is the terminal
`history[]` entry's `reason`; where `pending_approval` is also set (a gate, or the
`pipeline-orchestrator`'s `type: "escalation"`), its `reason` must say the same. E.g.:

- `spec_gap` → "spec_gap: clarify <ambiguous requirement> — provide the intended <behaviour/value>."
- `resource_limit` → "resource_limit: loop cap (N) reached on <stage> — relax the constraint, raise the cap, or accept current QoR."

### format_version

`design_state.json` version tiers (each tier is a superset of the previous):
- **`"1.1"`**: `fix_requests[]` and `cross_domain_iteration_count` present.
- **`"1.2"`**: `history[]` entries carry standardized `confidence`, `failure_class`, and `suggested_next_step` fields.
- **`"1.3"`**: `pipeline_config.checkpoints`, `approved_checkpoints[]`, `pending_approval.type/stage/agent` present; per-stage `history[]` entries (one entry per completed stage, not just one terminal entry per run).
- **`"1.4"`**: `constraints` object present (authoritative nested schema defined in the Constraints Schema section); stage-entry constraint validation; `pending_approval.type: "constraint_gap"`.
- **`"1.5"`**: every `history[]` entry carries `retry_strategy` (`none | regenerate | refine | escalate`), derived from `failure_class` via the mapping in the Failure Classification & Retry Strategy section; escalations include `failure_class` + actionable guidance in the `history[]` entry's `reason`, and in `pending_approval.reason` where one is set.

All orchestrators must:
- Upgrade to `"1.5"` if absent or currently `"1.0"`, `"1.1"`, `"1.2"`, `"1.3"`, or `"1.4"`; never downgrade.
- All prior-version requirements are subsumed by `"1.5"` — no separate upgrades required.
- Treat missing `fix_requests` or `cross_domain_iteration_count` as `[]` / `0`.
- Treat missing `confidence`, `failure_class`, or `suggested_next_step` in history entries as `null` for backward compatibility.
- Treat missing `retry_strategy` in history entries as derivable from `failure_class` via the mapping (`none` ⇒ `none`) for backward compatibility.
- Treat missing `pipeline_config.checkpoints` as `[]` (no checkpoints — fully autonomous).
- Treat missing `approved_checkpoints` as `[]`.
- Treat missing `pending_approval.type` as `"escalation"` for backward compatibility.
- Treat missing `constraints` as `{}` — apply schema defaults for all optional keys; halt on first missing required key per the Constraints Schema section.

### Approval Checkpoints

Proactive human-in-the-loop gates at configurable stage boundaries. Orthogonal to the
failure-driven `pending_approval` (type `escalation`) set by the pipeline-orchestrator.

#### Checkpoint configuration

```json
{
  "pipeline_config": {
    "checkpoints": ["arch_signoff", "rtl_signoff", "signoff"]
  },
  "approved_checkpoints": [
    { "stage": "arch_signoff", "approved_at": "<ISO-8601>", "approved_by": "user" }
  ]
}
```

Default: `checkpoints: []` → no gates, fully autonomous (backward compatible).

#### Gate logic (applied by every domain orchestrator at its sign-off stage)

Before setting the domain's `signoff=true` and writing it to `design_state.json`:

1. **Skip the gate in fix-request-servicing mode**: if a `fix_request.id` was passed in the
   prompt (invoked by meta to repair a bug), skip the checkpoint check entirely. Checkpoints
   gate forward design progression, not the automated verify↔RTL repair loop.

2. Read `pipeline_config.checkpoints` from `design_state.json`. If the orchestrator's
   sign-off stage name appears in the list **and** does not appear in `approved_checkpoints[].stage`:
   - Atomic RMW: set `pending_approval`:
     ```json
     {
       "type": "checkpoint",
       "stage": "<sign-off stage name>",
       "agent": "<this-orchestrator>",
       "reason": "checkpoint <stage> requires human approval before proceeding",
       "fix_request_id": null,
       "last_summary": "<QoR one-liner>",
       "requires_user": true
     }
     ```
   - Append a `history[]` entry with `decision: "await_approval"`, `confidence: "high"`,
     `failure_class: "none"`, `suggested_next_step: "escalate"`, `reason: "checkpoint <stage> requires human approval"`.
   - **Do not** set `signoff=true`. Print the gate message to the user and halt.

3. On re-invocation: if the stage now appears in `approved_checkpoints[]`, clear
   `pending_approval` (atomic RMW → set to `null`), then proceed to set `signoff=true`.

#### Resume paths

The user may resume a gated orchestrator by either:
- **Manual edit**: append `{ "stage": "<stage>", "approved_at": "<ISO-8601>", "approved_by": "user" }` to `approved_checkpoints[]` and set `pending_approval=null` in `design_state.json`, then re-invoke the orchestrator.
- **Approval instruction**: invoke the orchestrator with "approve checkpoint `<stage>`" in the prompt — the orchestrator performs the `approved_checkpoints[]` append and `pending_approval` clear (atomic RMW) itself, then continues.

#### pending_approval type-awareness (pipeline-orchestrator)

The `pipeline-orchestrator`'s `detect_open_fix_requests` halts on **any** non-null
`pending_approval` (conservative — a domain checkpoint also blocks meta dispatch). It prints
a type-specific message:
- `type: "checkpoint"`: "Checkpoint `<stage>` is awaiting human approval (set by `<agent>`). Approve or skip to continue."
- `type: "escalation"`: (existing message) "Fix-request loop escalation — review required."
- `type: "constraint_gap"`: "Stage `<stage>` is missing required constraint(s) (set by `<agent>`). Populate `design_state.constraints` and clear `pending_approval` to continue."

#### Per-stage history trace (format_version 1.3)

Every domain orchestrator appends one `history[]` entry after each internal stage completes
(PASS, FAIL, WARN), not just at session end. The last entry written is the terminal entry
read by the pipeline-orchestrator's decision table. At format_version 1.5 the entry carries a
`retry_strategy` field derived from `failure_class` (10-field schema). This enables post-run
audits without replaying the full conversation.

### Programmatic branching on standardized history[] fields

After a domain orchestrator completes, the pipeline-orchestrator reads the terminal
`history[]` entry to make retry/escalate decisions without string-parsing prose. Decision
table (evaluated in order):

| `confidence` | `failure_class` | `retry_strategy` | `suggested_next_step` | Pipeline action |
|---|---|---|---|---|
| any | `resource_limit` | `escalate` | any | Escalate via `pending_approval` — cap exceeded |
| `low` | any | any | `escalate` | Escalate — result unreliable, human review required |
| `low` | any | any | any (not escalate) | Escalate — low confidence overrides any retry intent |
| any | `tool_error` | `regenerate` | `retry_stage` | Re-dispatch the same orchestrator once; if still `tool_error`, escalate |
| any | `drc_lvs` \| `connectivity` | `refine` | `loop_back_to:<stage>` | Re-dispatch the generating orchestrator from a clean slate with the error log |
| any | `functional` \| `coverage_gap` | `refine` | `escalate` | Append new `fix_request` and loop back via RTL orchestrator |
| any | `timing` \| `power_area` | `refine` | `loop_back_to:<stage>` | Re-dispatch targeting the violating path/budget with QoR feedback |
| any | `spec_gap` | `escalate` | `escalate` | Escalate — ambiguous spec; reason states what the user must clarify |
| `high` \| `medium` | `none` | `none` | `proceed` | Advance to next stage / signoff |
| any | any | any | `abandon` | Escalate via `pending_approval` — child reports unrecoverable, human decision required |

`retry_strategy` is the deterministic map of `failure_class` (see the Failure Classification &
Retry Strategy section) and serves as a coarse pre-filter; `confidence` and
`suggested_next_step` still refine the final action. Precedence is preserved: `resource_limit`
and `low` confidence escalate regardless of the mapped strategy. For any combination not in the
table, apply the most conservative matching rule (prefer `escalate` over retry). When the action
is an escalation, `pending_approval.reason` must carry the `failure_class` and actionable
guidance (see Actionable escalation guidance). Programmatic branches must read from the history
entry's structured fields — do not re-derive intent from `reason` (free-text, for humans only).

### Dispatch pattern (pipeline-orchestrator)

Sequential dispatch — never parallel:
1. RTL orchestrator (fix the bug) — block until complete.
2. Verification or formal orchestrator (validate the fix) — block until complete.

Spawn form for the Agent/Task tool:
- RTL: `subagent_type: chip-design-rtl:rtl-design-orchestrator`
- Verification: `subagent_type: chip-design-verification:verification-orchestrator`
- Formal: `subagent_type: chip-design-formal:formal-orchestrator`

Always pass the `fix_request.id` in the subagent prompt so the child can locate its work item without scanning the whole array.

### V2 extension points (not wired in V1)

- Architecture↔RTL refinement loop: `architecture.refinement_needed=true` could trigger
  an arch re-run. The `fix_request` schema is intentionally producer-agnostic; only
  `created_by` would need a new value (`architecture-orchestrator`).
- Formal property-bug routing: `failure_class=formal_cex` with `suspected_owner=formal`
  would route to the formal orchestrator instead of RTL. Not implemented in V1.
- **LEC unmatched-points loop**: `lec_run: unmatched points` in `formal-orchestrator.md` is intentionally **not** connected to the fix_request protocol in V1. LEC failures are netlist↔RTL mismatches introduced at synthesis — the correct consumer is `synthesis-orchestrator`, not `rtl-design-orchestrator`. Deferred to V2.

## QoR Metrics

- `cross_domain_iteration_count` — number of RTL↔verify dispatch cycles (target: ≤ 2 for clean designs)
- `time_to_signoff` — wall-clock time from first open `fix_request` to `verification_status.signoff=true`
- `escalation_rate` — fraction of design sessions that hit the 3-iteration cap (target: < 10%)
- `fix_request_abandonment_rate` — fraction of `fix_requests` that reach `status=abandoned` (target: 0%)

## Output Required

- `design_state.json` with all `fix_requests[]` entries at terminal status (`fixed` or `abandoned`)
- `design_state.json` with `cross_domain_iteration_count` updated
- `memory/meta/experiences.jsonl` entry for this run
- A console summary to the user: which fix_requests were processed, how many iterations, and the outcome (converged / escalated / no open requests)
