# digital-chip-design-agents

> Claude Code marketplace plugin — full digital chip design pipeline.  
> 16 plugins · 17 skill files · 14 chip-design domains + infrastructure + pipeline orchestrator · closed-loop verification↔RTL feedback.

[![Validate](https://github.com/hdl-tools/digital-chip-design-agents/actions/workflows/validate.yml/badge.svg)](https://github.com/hdl-tools/digital-chip-design-agents/actions/workflows/validate.yml)

---

## Quick Start

With Node.js (≥18), install everything with one command — no clone, no Python:

```bash
npx digital-chip-design-agents      # detects your AI agents and installs after a confirm
```

Then just describe your task in natural language:

```
Run the RTL design flow for my AXI DMA controller block
Analyse timing violations on this routed DEF and suggest ECOs
Build a UVM testbench for my FIFO block
```

Claude automatically loads the correct skill before executing.

For the install script, selective marketplace install, other AI assistants
(Copilot / Gemini / OpenCode / Codex), and all flags, see
**[docs/INSTALL.md](docs/INSTALL.md)**.

---

## Available Plugins

| Plugin Name | Domain | Invoke When You Want To... |
|-------------|--------|---------------------------|
| `chip-design-architecture` | Architecture Evaluation | Explore microarch candidates, estimate PPA, assess risk |
| `chip-design-rtl` | RTL Design (SystemVerilog) | Write, lint, CDC-check, or synthesis-check RTL |
| `chip-design-verification` | Functional Verification (UVM) | Build testbench, write tests, close coverage, run regression |
| `chip-design-formal` | Formal Verification (FPV/LEC) | Prove properties, check equivalence, close formal gaps |
| `chip-design-synthesis` | Logic Synthesis | Set up SDC, run synthesis, verify netlist with LEC |
| `chip-design-dft` | Design for Test | Plan DFT, insert scan, run ATPG, set up JTAG |
| `chip-design-sta` | Static Timing Analysis | Analyse timing, guide ECO closure, sign off timing |
| `chip-design-hls` | High-Level Synthesis | Convert C/C++ to RTL, optimise directives, co-simulate |
| `chip-design-pd` | Physical Design | Full PD flow: floorplan → placement → CTS → routing → sign-off |
| `chip-design-soc` | SoC IP Integration | Qualify IPs, configure bus fabric, run chip-level sim |
| `chip-design-memory-ip` | Memory IP Design | Select SRAM/RF/ROM macros, architect banking & ECC, allocate repair, qualify views |
| `chip-design-compiler` | Compiler Toolchain | Build LLVM/GCC backend, assembler, linker, runtime for custom ISA |
| `chip-design-firmware` | Embedded Firmware | BSP, HAL drivers, RTOS integration, firmware validation |
| `chip-design-fpga` | FPGA Emulation | Port ASIC to FPGA, bring up hardware, validate SW on prototype |
| `chip-design-infrastructure` | Infrastructure & Memory | Detect EDA tools, deploy wrappers, configure MCP servers, distil domain memory |
| `chip-design-meta` | Pipeline Orchestration | Drive closed-loop verification↔RTL feedback, manage fix_requests, enforce iteration cap |

**Optional companion:** [`hdl-rtl-skill`](https://github.com/hdl-tools/hdl-rtl-skill) adds a
slang-backed per-write lint hook, golden RTL templates and an anti-pattern catalogue (Claude
Code only). The RTL-authoring plugins here (`rtl`, `fpga`, `soc`, `memory-ip`, `hls`) use it
when it is installed and carry the same lint rules themselves when it is not.

---

## How It Works

Each plugin installs two things:

1. **A Skill** (`plugins/<domain>/skills/<domain>/SKILL.md`) — domain knowledge Claude reads
   before executing. Contains stage-by-stage rules, QoR metrics, common fixes, and output
   requirements.

2. **An Orchestrator Agent** (`plugins/<domain>/agents/<domain>-orchestrator.md`) — a subagent
   that manages the full multi-stage flow. It sequences stages, enforces pass/fail criteria,
   applies loop-back rules when a stage fails, and escalates clearly when human input is needed.

Skills are loaded autonomously by Claude when you describe a task. Orchestrators are
invoked explicitly when you want to run a complete flow end-to-end.

Each orchestrator enforces a strict stage sequence with loop-back rules, and the 14 domains
connect into a complete spec→tape-out pipeline. See **[docs/PIPELINE.md](docs/PIPELINE.md)**
for the flow diagram and loop-back details, and [docs/MASTER_INDEX.md](docs/MASTER_INDEX.md)
for per-domain flow documentation.

---

## Memory System

Each domain orchestrator reads from and writes to a two-tier persistent memory store under
`memory/`:

- **`memory/<domain>/knowledge.md`** — distilled summaries (failure patterns, tool flags, PDK
  quirks) read by every orchestrator at session start.
- **`memory/<domain>/experiences.jsonl`** — one record per run, upserted by `run_id`, written on
  every termination path (signoff, escalation, or abandon).

Distil accumulated records back into `knowledge.md` with the `memory-keeper` skill, and track
QoR metrics across runs with `tools/qor_trends.py`. See **[memory/README.md](memory/README.md)**
for the full schema, distilling workflow, and QoR trend examples.

---

## Repo Structure

```
digital-chip-design-agents/
├── .claude-plugin/marketplace.json   ← Marketplace registry (all 16 plugins)
├── plugins/                          ← One isolated directory per plugin (skill + orchestrator)
├── ides/                             ← IDE-specific config files (Copilot / Gemini / OpenCode / Codex)
├── memory/                           ← Persistent two-tier per-domain memory (see memory/README.md)
├── docs/                             ← Install guide, pipeline map, and per-domain flow docs
├── tools/qor_trends.py               ← QoR metric trending and regression detection
└── .github/workflows/                ← CI (validate.yml) and release (release.yml)
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome for:
- Improved domain rules or QoR metrics in any SKILL.md
- New loop-back rules in orchestrators
- New skill domains (e.g., package/assembly, analog integration)

CI validates all files on every PR — the validate workflow must pass before merge.

---

## License

MIT — see [LICENSE](LICENSE).
