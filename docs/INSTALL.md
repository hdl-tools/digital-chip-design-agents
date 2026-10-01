# Installation

Choose the install path that fits your setup. For most users, **Option A (npm)**
is the simplest — no clone and no Python required.

## Option A — npm (recommended, no clone)

If you have Node.js (≥18), run a single command — no `git clone` and no Python
required. With no flags the installer **detects which AI coding agents you have
installed** (Claude Code, OpenAI Codex, OpenCode, Gemini, GitHub Copilot), shows
what it found and where each would write, and installs to them after a
confirmation:

```bash
npx digital-chip-design-agents            # detect installed agents + confirm
npx digital-chip-design-agents --yes      # detect + install, no prompt (CI-friendly)
```

Detection treats an agent as installed if its CLI is on `PATH` **or** its config
directory exists (e.g. `~/.claude`, `~/.codex`, `~/.config/opencode`,
`~/.gemini`). For Claude Code it copies every plugin into your plugin cache and
enables them in `settings.json`; for the others it generates the matching context
files (see Option D). All five targets are handled natively in Node — no Python.

To target a specific agent (or all of them) explicitly and skip detection:

```bash
npx digital-chip-design-agents --ide claude     # or codex | opencode | gemini | copilot | all
npx digital-chip-design-agents --ide gemini --global
```

Re-run any of these to pick up future updates. Works identically on macOS, Linux,
and Windows (a single Node process copies plugins sequentially, so there is no
concurrent-write contention on the cache directory).

## Option B — Install script

Clone the repo and run one script. Like the npm installer, running it with no
flags **auto-detects your installed agents** and installs to them after a
confirmation (add `--yes` / `-y` on `install.sh`, or `-Yes` on `install.ps1`, to
skip the prompt). The shell scripts require `python3`; for a Python-free install
use the npm path (Option A).

**macOS / Linux / Git Bash:**
```bash
git clone https://github.com/hdl-tools/digital-chip-design-agents.git
cd digital-chip-design-agents
bash install.sh
```

**Windows (PowerShell):**
```powershell
git clone https://github.com/hdl-tools/digital-chip-design-agents.git
cd digital-chip-design-agents
.\install.ps1
```

Restart Claude Code after running — all 17 skills and 16 agents will be active.

## Option C — Marketplace (selective install)

If you only need specific domains, install them individually via the Claude Code
marketplace. First register the marketplace, then install the domains you need:

```text
/plugin marketplace add github:hdl-tools/digital-chip-design-agents
```

<details>
<summary>Individual plugin install commands (click to expand)</summary>

```text
/plugin install chip-design-architecture@digital-chip-design-agents
/plugin install chip-design-rtl@digital-chip-design-agents
/plugin install chip-design-verification@digital-chip-design-agents
/plugin install chip-design-formal@digital-chip-design-agents
/plugin install chip-design-synthesis@digital-chip-design-agents
/plugin install chip-design-dft@digital-chip-design-agents
/plugin install chip-design-sta@digital-chip-design-agents
/plugin install chip-design-hls@digital-chip-design-agents
/plugin install chip-design-pd@digital-chip-design-agents
/plugin install chip-design-soc@digital-chip-design-agents
/plugin install chip-design-memory-ip@digital-chip-design-agents
/plugin install chip-design-compiler@digital-chip-design-agents
/plugin install chip-design-firmware@digital-chip-design-agents
/plugin install chip-design-fpga@digital-chip-design-agents
```

</details>

## Option D — Other AI assistants (Copilot / Gemini / OpenCode / Codex CLI)

These targets are auto-detected by Options A and B, but you can also install one
explicitly. The npm installer (`npx digital-chip-design-agents --ide <target>`)
and the shell scripts both support every target natively; run from your chip
design project directory with `--ide`:

```bash
# GitHub Copilot — creates .github/instructions/ in your project
bash /path/to/digital-chip-design-agents/install.sh --ide copilot
# Commit the generated .github/ files to share rules with your team.

# Gemini Code Assist — creates GEMINI.md in your project (or ~/GEMINI.md with --global)
bash /path/to/digital-chip-design-agents/install.sh --ide gemini

# OpenCode — creates opencode.json in your project; use /mode chip-<domain> to activate
bash /path/to/digital-chip-design-agents/install.sh --ide opencode

# OpenAI Codex CLI — creates AGENTS.md in your project (or ~/.codex/instructions.md with --global)
bash /path/to/digital-chip-design-agents/install.sh --ide codex

# All IDEs at once (also installs Claude Code)
bash /path/to/digital-chip-design-agents/install.sh --ide all
```

**Windows (PowerShell):** replace `bash install.sh` with `.\install.ps1` and `--ide` with `-IDE`.

Domain knowledge is loaded directly from the plugin source files — no duplicate content.
Re-run the install command to pick up any future updates.

## Usage — describe your task in natural language

```
Run the RTL design flow for my AXI DMA controller block
Analyse timing violations on this routed DEF and suggest ECOs
Generate ATPG patterns for this DFT-inserted netlist
Build a UVM testbench for my FIFO block
```

Claude automatically loads the correct skill before executing.
