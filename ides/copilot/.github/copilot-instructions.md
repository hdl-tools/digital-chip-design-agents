# Digital Chip Design — Copilot Workspace Instructions

This workspace contains digital ASIC/FPGA chip design work spanning 14 domains:
architecture evaluation, RTL design, functional verification, formal verification,
logic synthesis, DFT, static timing analysis, HLS, physical design, SoC integration,
memory IP design, compiler toolchain, embedded firmware, and FPGA emulation.

## Behaviour for All Domains

- Apply domain-specific QoR metrics before declaring any stage complete.
- Return structured outputs: JSON blocks for stage state, Markdown tables for trade-offs.
- Execute one stage at a time and report **PASS / FAIL / WARN** after each stage.
- Flag ambiguities before proceeding — chip design is safety-critical.
- When a stage loop limit is exceeded, escalate to the user with full state and recommendations.

<!-- BEGIN SHARED:ide-guards (synced from tools/agent_shared_sections.md - edit there, then run tools/sync_agent_sections.py) -->
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
<!-- END SHARED:ide-guards -->

## Domain-Specific Rules

Per-domain rules, QoR metrics, and stage sequences are loaded from
`.github/instructions/<domain>.instructions.md` based on the files you are working with.
These files are generated from the plugin SKILL.md sources and contain the full
domain knowledge for each chip design stage.
