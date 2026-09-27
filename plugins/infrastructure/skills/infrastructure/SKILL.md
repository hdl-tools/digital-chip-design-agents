---
name: infrastructure
description: >
  EDA tool detection, wrapper deployment, and MCP configuration for digital chip
  design environments. Use when setting up a new workstation, verifying tool
  availability before a domain flow, or generating per-tool install scripts with
  TCL modulefiles.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: Infrastructure Setup

## Invocation

- **If invoked by a user** presenting a setup task: immediately spawn the
  `digital-chip-design-agents:infrastructure-orchestrator` agent and pass the full
  user request and any available context. Do not execute stages directly.
- **If invoked by the `infrastructure-orchestrator` mid-flow**: do not spawn a new
  agent. Treat this file as read-only — return the requested stage rules,
  sign-off criteria, or loop-back guidance to the calling orchestrator.

Spawning the orchestrator from within an active orchestrator run causes recursive
delegation and must never happen.

## Purpose
Detect open-source and proprietary EDA tools, generate an installation script for
missing tools, deploy output-filtering shell wrappers that emit compact JSON instead
of raw 10,000–50,000-line logs, configure MCP server templates, and validate the
complete environment before any domain orchestrator begins work.

---

## Supported EDA Tools

### Open-Source
- **Verilator** (`verilator`) — fast RTL simulator and linter
- **Slang** (`slang`) — SystemVerilog compiler and language server
- **Surelog** (`surelog`) — SystemVerilog pre-processor and parser
- **sv2v** (`sv2v`) — SystemVerilog to Verilog converter
- **Icarus Verilog** (`iverilog`) — Verilog simulator
- **Yosys** (`yosys`) — open synthesis framework
- **ABC** (`abc`) — logic synthesis and verification tool
- **OpenROAD** (`openroad`) — RTL-to-GDS flow
- **LibreLane / OpenLane2** (`openlane`) — open-source ASIC flow
- **KLayout** (`klayout`) — GDS/OASIS viewer and DRC engine
- **OpenSTA** (`sta`) — gate-level static timing analysis
- **SymbiYosys** (`sby`) — formal hardware verification
- **gem5** (`gem5`) — full-system micro-architectural simulator
- **Bambu HLS** (`bambu-hls`) — high-level synthesis from C/C++
- **nextpnr** (`nextpnr`) — FPGA place-and-route
- **openFPGALoader** (`openFPGALoader`) — FPGA programming tool
- **cocotb** (Python package `cocotb`) — Python-based RTL co-simulation
- **LLVM** (`llvm-config`) — compiler infrastructure
- **GCC** (`gcc`) — GNU compiler collection
- **OpenOCD** (`openocd`) — on-chip debugger
- **xschem** (`xschem`) — schematic capture and simulation netlist tool
- **GTKWave** (`gtkwave`) — waveform viewer for VCD/FST simulation output
- **uv** (`uv`) — fast Python package and project manager (required for cocotb installs)

### Proprietary (detect only — never install)
- **Synopsys VCS** (`vcs`) — industry-standard RTL simulator
- **Cadence Xcelium** (`xrun`, alt: `xmsim`) — next-generation simulation platform
- **Synopsys Design Compiler** (`dc_shell`, alt: `dc_shell-t`) — logic synthesis
- **Cadence Innovus** (`innovus`) — physical implementation
- **Mentor QuestaSim** (`vsim`, alt: `questa`, `questasim`) — advanced simulation and verification
- **Synopsys PrimeTime** (`pt_shell`, alt: `pt_shell64`) — sign-off static timing analysis
- **Synopsys Formality** (`formality`, alt: `fm_shell`) — formal equivalence checking

---

## MCP Architecture — Two Tiers

### Tier 1: Batch MCP servers (short, self-contained runs)
Use these for tools whose output fits inside a single request/response cycle (seconds to
a few minutes).  Each call spawns the wrapper script, captures its compact JSON output,
and returns it.

| MCP config | Tool | Typical duration |
|------------|------|-----------------|
| `mcp-yosys.json` | Yosys synthesis | seconds–minutes |
| `mcp-openroad.json` | Single OpenROAD stage | minutes |
| `mcp-opensta.json` | OpenSTA batch report | seconds–minutes |
| `mcp-klayout.json` | KLayout DRC/LVS | minutes |
| `mcp-verilator.json` | Verilator lint or sim | seconds–minutes |
| `mcp-bambu.json` | Bambu HLS synthesis | minutes |
| `mcp-gem5.json` | gem5 short benchmark run | minutes (set TOOL_TIMEOUT_S) |
| `mcp-symbiflow.json` | SymbiYosys bounded proof | minutes–hours (set TOOL_TIMEOUT_S) |

The adapter is `plugins/infrastructure/tools/mcp-adapter.py`.

### Tier 2: Interactive session MCP servers (stateful, query-based)
Use these when an agent iterates many times over an already-loaded design (e.g. ECO timing
loops).  The process stays alive between calls — no re-loading per query.

| MCP config | Tool | Exposed tools |
|------------|------|---------------|
| `mcp-openroad-session.json` | OpenROAD Tcl session | `load_design`, `query_timing`, `query_drc`, `get_design_area`, `get_power`, `run_tcl`, `close_design` |
| `mcp-opensta-session.json` | OpenSTA Tcl session | `load_design`, `report_timing`, `report_slack_histogram`, `check_timing`, `run_tcl`, `close_design` |

The adapter is `plugins/infrastructure/tools/mcp-session-adapter.py`.

### Full-flow tools — do NOT use MCP
These tools run for 30 min–2+ hours and produce structured output files on disk.
Agents must launch them via Bash and read the output files directly.

| Tool | Launch command | Read these files |
|------|---------------|-----------------|
| LibreLane / OpenLane 2 | `openlane config.json` | `runs/<design>/<tag>/metrics.json` |
| ORFS / OpenROAD Flow Scripts | `make DESIGN_CONFIG=... finish` | `reports/<platform>/<design>/metrics.json` |
| gem5 full-system simulation | `gem5 config.py ...` | `m5out/stats.txt`, `m5out/simout` |

### Execution Hierarchy (per domain agent)
1. **Tier 2 session MCP** — if the tool supports a session and the design is already loaded
2. **Tier 1 batch MCP** — if the tool has a batch MCP server configured
3. **Wrapper script** — if MCP is not configured; wrapper emits compact JSON
4. **Direct execution** — last resort; raw logs consume significant context

Domain agents must check whether the relevant MCP server is active in `.claude/settings.json`
before falling back to the wrapper or direct execution.

---

## Stage: tool_discovery

### Domain Rules
1. Run `which <command>` and `<command> --version` (or `-version`) for every open-source tool
2. **Python interpreter detection** — run once at the start of tool_discovery, before checking any Python packages. Detection order (first match wins):

   **Step A — Module system probe (runs before PATH check)**:
   a. Check if a module system is available: test `$MODULESHOME` is set OR `modulecmd` exists in PATH.
   b. If a module system is available, run `module avail 2>&1` and search for entries matching `python` or `python3` (case-insensitive).
   c. If one or more Python module entries are found: select the latest version (highest semver/lexicographic), load it via `module load <python-module>`, then run `which python3` to resolve `PYTHON_EXEC`. Set `python_env.type = "module"` and record `python_env.module_name` with the loaded module name. **Keep the module loaded for the entire orchestrator run** — do not unload it; subsequent stages (tool_installation, wrapper_deployment, environment_validation) all depend on `PYTHON_EXEC` being resolvable. The generated `load-modules.sh` handles persistent loading for future shell sessions.
   d. If no module system is available, or no Python module entries are found: proceed to Step B.

   **Step B — PATH-based fallback**:
   e. Run `which python3` to get the interpreter path; store as `PYTHON_EXEC`.
   f. If `which python3` fails or returns empty: record `python3` as `MISSING` in `tool-status.json` and FAIL immediately (required for all wrapper scripts and Python packages).
   g. Classify the interpreter:
      - `system` → `PYTHON_EXEC` == `/usr/bin/python3`
      - `custom` → any other path (pyenv, conda, virtualenv, custom prefix, etc.)

   **Step C — Finalize**:
   h. Set `PYTHON_BIN_DIR = $(dirname "$PYTHON_EXEC")` regardless of how `PYTHON_EXEC` was resolved.
   i. Record under a top-level key `python_env` in `tool-status.json`:
      ```json
      {
        "python_env": {
          "exec": "<absolute path>",
          "type": "module | system | custom",
          "bin_dir": "<absolute dir>",
          "module_name": "<module name, or null if not module-based>"
        }
      }
      ```
   j. Capture `"$PYTHON_EXEC" --version` and store it as a regular entry in the `tools` array (with `"tool": "python3"`, `"command": "python3"`, `"status": "FOUND"`, `"version": "<output>"`, `"path": "<PYTHON_EXEC>"`). This makes `python3` visible to `module_discovery` for module-status upgrades (`FOUND_PREFER_MODULE`).

3. **Exception — Python packages**:
   - **cocotb**: detection depends on the Python interpreter type determined in rule 2:
     - If `python_env.type == "custom"` or `"module"`: check `"$PYTHON_BIN_DIR/cocotb-config" --version` first; if that exits zero, record FOUND with the returned version string. Only if absent or non-zero, fall back to `cocotb-config --version` (PATH-based).
     - If `python_env.type == "system"`: use `cocotb-config --version` (PATH-based) only.
     - Report MISSING if all attempted checks fail.
   - **openlane**: run `"$PYTHON_EXEC" -m pip show openlane 2>/dev/null`; if exit code 0 and `Name: openlane` appears in output, record FOUND and extract the `Version:` field; otherwise MISSING.
   - **uv**: if `python_env.type == "custom"` or `"module"`: check `"$PYTHON_BIN_DIR/uv" --version` first; fall back to `uv --version` (PATH). If `python_env.type == "system"`: use `uv --version` only.
4. For proprietary tools: check PATH using `which <primary-executable>` only (see executable names in the Proprietary section above); never attempt install; record as `PROPRIETARY_ONLY` if found, `MISSING` otherwise
5. Record each tool as one of: `FOUND`, `MISSING`, or `PROPRIETARY_ONLY`
6. Capture exact version string for each `FOUND` tool
7. Never attempt installation in this stage
8. Write results to `tool-status.json` before advancing

### QoR Metrics to Evaluate
- `tools_detected`: count of FOUND tools (target ≥ 10 for a functional open-source flow)
- `tools_missing`: count of MISSING open-source tools
- `proprietary_found`: count of PROPRIETARY_ONLY tools detected in PATH

### Output Required
- `tool-status.json` — contains two top-level keys:
  - `python_env`: `{ "exec": "", "type": "module|system|custom", "bin_dir": "", "module_name": "" }` — populated by rule 2
  - `tools`: array of `{ "tool": "", "command": "", "status": "FOUND|MISSING|PROPRIETARY_ONLY", "version": "", "path": "" }`

Note: module-based availability (`FOUND_PREFER_MODULE`, `MISSING_LOAD_MODULE`) and the `module_names`/`versions_available` fields are added in the next stage (`module_discovery`).

---

## Stage: module_discovery

### Domain Rules

#### Module system detection (in order of preference)
1. **Classic Environment Modules (TCL)** — check `$MODULESHOME` is set, or `modulecmd` binary exists in PATH
2. **Neither** — set `module_system: "none"`, emit WARN, skip remaining rules, write empty `module-status.json`, advance to `tool_installation`

#### Module listing commands
- **Classic**: `module avail 2>&1` — parse text; entries appear as `<name>/<version>`
- If the listing command exits non-zero: emit WARN, record the error, proceed

#### Module-to-tool mapping table

| Tool command | Module name patterns to match (case-insensitive substring) |
|---|---|
| `vcs` | `vcs`, `synopsys-vcs`, `synopsys/vcs` |
| `xrun` | `xcelium`, `cadence-xcelium`, `cadence/xcelium` |
| `dc_shell` | `design-compiler`, `synopsys/dc`, `dc_shell` |
| `innovus` | `innovus`, `cadence/innovus`, `cadence-innovus` |
| `vsim` | `questa`, `questasim`, `mentor/questa` |
| `pt_shell` | `primetime`, `synopsys/pt`, `pt_shell` |
| `formality` | `formality`, `synopsys/formality` |
| `verilator` | `verilator` |
| `yosys` | `yosys` |
| `openroad` | `openroad` |
| `klayout` | `klayout` |
| `iverilog` | `icarus`, `iverilog` |
| `sta` | `opensta` |
| `gcc` | `gcc` |
| `llvm-config` | `llvm` |
| `xschem` | `xschem` |
| `gtkwave` | `gtkwave` |
| `uv` | `uv` |
| `python3` | `python`, `python3` |
| `slang` | `slang` |
| `surelog` | `surelog` |
| `sv2v` | `sv2v` |
| `sby` | `symbiyosys`, `sby`, `yosyshq/sby` |
| `bambu-hls` | `bambu`, `bambu-hls`, `panda-bambu` |
| `nextpnr` | `nextpnr` |
| `openFPGALoader` | `openfpgaloader` |
| `openocd` | `openocd` |

#### Rules
1. Detect module system using the detection order above
2. Run the appropriate listing command for the detected system
3. For each entry in the listing, test against the mapping table (case-insensitive)
4. For each matched tool, collect all available version strings
5. Write `module-status.json` before advancing
6. For each tool marked `FOUND` in `tool-status.json` that also has a module available: change status to `FOUND_PREFER_MODULE`, add `module_names` and `versions_available` fields, include in `load-modules.sh` — module takes precedence over PATH version
7. For each tool marked `MISSING` in `tool-status.json` that has modules available: change status to `MISSING_LOAD_MODULE`, add `module_names` and `versions_available` fields
8. Generate `load-modules.sh` for all `FOUND_PREFER_MODULE` and `MISSING_LOAD_MODULE` tools; default to the latest version (highest semver/lexicographic); comment out alternative versions inline
9. Never auto-run `load-modules.sh` — print: "Review and source `load-modules.sh` to load EDA modules, then re-run the flow"

#### Extended `tool-status.json` schema
Fields added by this stage to each entry in the `tools` array (backward-compatible additions):
```json
{
  "tool": "",
  "command": "",
  "status": "FOUND | FOUND_PREFER_MODULE | MISSING | MISSING_LOAD_MODULE | PROPRIETARY_ONLY",
  "version": "",
  "path": "",
  "module_names": [],
  "versions_available": []
}
```

Note: The top-level `python_env` object is **preserved unchanged** during this stage — only entries in the `tools` array are modified. The `python3` tool entry is treated like any other: if `python_env.type == "module"`, its `tools` array status is upgraded from `FOUND` to `FOUND_PREFER_MODULE` and it is included in `load-modules.sh`.

### QoR Metrics to Evaluate
- `module_system_detected`: bool — true if classic Environment Modules (TCL) found
- `tools_found_via_modules`: count of tools with status `MISSING_LOAD_MODULE` or `FOUND_PREFER_MODULE`

### Stage Output Summary
Print a human-readable table before advancing:
```text
Module system : Environment Modules 4.8.0 (TCL)
Tools in PATH : 12
Tools via modules : 5
  vcs        — synopsys/vcs/2020.03, synopsys/vcs/2021.01
  xrun       — cadence/xcelium/20.09
  dc_shell   — synopsys/dc/2022.03
  innovus    — cadence/innovus/21.1
  pt_shell   — synopsys/primetime/2022.06
```

### Output Required
- `module-status.json` — module system details and per-tool module listings
- Updated `tool-status.json` — statuses and module fields added for matched tools
- `load-modules.sh` — generated when any tool has status `FOUND_PREFER_MODULE` or `MISSING_LOAD_MODULE`; omitted when `module_system` is `"none"`

`module-status.json` schema:
```json
{
  "module_system": "tclmod | none",
  "module_system_version": "",
  "tools_via_modules": [
    {
      "tool": "<command>",
      "module_names": ["synopsys/vcs/2020.03", "synopsys/vcs/2021.01"],
      "versions_available": ["2020.03", "2021.01"]
    }
  ]
}
```

`load-modules.sh` format:
```bash
#!/usr/bin/env bash
# Generated by module_discovery — source this file to load EDA tool modules
# Usage: source load-modules.sh

module load synopsys/vcs/2021.01       # latest; alternatives: 2020.03
module load cadence/xcelium/20.09
# module load cadence/innovus/21.1     # uncomment if needed
```

---

## Stage: tool_installation

### Domain Rules
1. **Never auto-run installs** — only generate per-tool install scripts
2. If `python3` is missing: FAIL immediately and escalate — required for all wrapper scripts
3. Generate one `install-<toolname>.sh` for every tool with status `MISSING`; skip tools with status `FOUND`, `FOUND_PREFER_MODULE`, `MISSING_LOAD_MODULE`, or `PROPRIETARY_ONLY`
4. Each script follows the Per-Tool Script Structure below
5. Use the Package Name Mapping Table to emit correct install commands for the detected OS/PM
6. **Python package install scripts** (`openlane`, `cocotb`, `uv`): read `python_env.exec` from `tool-status.json` and substitute it for `<PYTHON_EXEC>` (and `python_env.bin_dir` for `<PYTHON_BIN_DIR>`). At the top of each Python package install script, emit:
    ```bash
    PYTHON_EXEC="<value of python_env.exec>"
    # Verify this is the intended interpreter before running
    ```
    Use `"$PYTHON_EXEC" -m pip install <package>` as the install command. Never use bare `pip install` when `python_env.type` is `"custom"` or `"module"`.
7. Proprietary tools: no script generated — record a note in the sign-off summary only
8. Modulefile format: always TCL classic (no file extension); always generate modulefiles unconditionally — if `module_system == "none"`, emit WARN that automatic module loading is unavailable but still output the modulefile
9. Each script must end with guidance for registering `$EDA_MODULEFILES_ROOT` in `$MODULEPATH` if not already present
10. Write all `install-<toolname>.sh` scripts to the `install-missing-tools/` directory; create the directory if it does not exist; do **not** create the directory or any scripts if no tools are `MISSING`

### Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| `python3` not found | Escalate immediately — all wrapper scripts depend on it |
| OpenROAD build required | Refer to https://github.com/The-OpenROAD-Project/OpenROAD |
| Bambu HLS Linux only | Wrap with `status: WARN` on macOS/Windows |

### Install Directory Layout

```text
$EDA_TOOLS_ROOT/                         (default: /tools)
  <toolname>/<version>/                  e.g. /tools/verilator/5.028/
    bin/
    lib/
    share/

$EDA_MODULEFILES_ROOT/                   (default: /tools/toolmgr/env/modulefiles)
  <toolname>/<version>                   e.g. /tools/toolmgr/env/modulefiles/verilator/5.028
```

Both roots are read from env vars at script runtime with the defaults above.

### Per-Tool Script Structure

Each `install-<toolname>.sh` — file: `$EDA_MODULEFILES_ROOT/<toolname>/<version>` (TCL, no extension):

```bash
#!/usr/bin/env bash
# install-<toolname>.sh — generated by infrastructure-orchestrator
# Installs <Tool Full Name> to $EDA_TOOLS_ROOT/<toolname>/<version>
# and generates a TCL modulefile at $EDA_MODULEFILES_ROOT/<toolname>/<version>
set -euo pipefail

TOOL_NAME="<toolname>"
TOOL_VERSION="<detected-or-latest>"
EDA_TOOLS_ROOT="${EDA_TOOLS_ROOT:-/tools}"
EDA_MODULEFILES_ROOT="${EDA_MODULEFILES_ROOT:-/tools/toolmgr/env/modulefiles}"
INSTALL_DIR="${EDA_TOOLS_ROOT}/${TOOL_NAME}/${TOOL_VERSION}"

# --- Install ---
# Build-from-source: pass --prefix="${INSTALL_DIR}" to configure/cmake
# Package manager: use apt-get/brew/pacman (see mapping table below)

# --- Generate TCL modulefile ---
MODFILE_DIR="${EDA_MODULEFILES_ROOT}/${TOOL_NAME}"
mkdir -p "${MODFILE_DIR}"

cat > "${MODFILE_DIR}/${TOOL_VERSION}" <<EOF
#%Module1.0
proc ModulesHelp { } {
    puts stderr "<Tool Full Name> ${TOOL_VERSION}"
}
module-whatis "<Tool Full Name> ${TOOL_VERSION} — <one-line description>"

set prefix ${INSTALL_DIR}
prepend-path PATH            \$prefix/bin
prepend-path LD_LIBRARY_PATH \$prefix/lib
prepend-path MANPATH         \$prefix/share/man
# add PYTHONPATH, PKG_CONFIG_PATH, or tool-specific setenv as needed
EOF

echo "Modulefile written: ${MODFILE_DIR}/${TOOL_VERSION}"

# --- Register modulefiles root (if not already set) ---
# export MODULEPATH=${EDA_MODULEFILES_ROOT}:${MODULEPATH}
# Add the above line to ~/.bashrc or /etc/profile.d/eda-modules.sh
```

If `module_system == "none"`: emit WARN in stage output that automatic module loading is unavailable, but still generate the modulefile block in the install script.

**Modulefile content rules:**
- Minimum env vars in every modulefile: `PATH`, `LD_LIBRARY_PATH`
- Add where applicable: `MANPATH`, `PKG_CONFIG_PATH`, `PYTHONPATH`
- Tool-specific root vars (set these when present):
  - Verilator → `VERILATOR_ROOT`
  - Yosys → `YOSYS_DATDIR`
  - LLVM → `LLVM_DIR`
  - cocotb → `COCOTB_SHARE_DIR`

### Package Name Mapping Table

| Tool command | apt package(s) | brew formula | pacman pkg | fallback / notes |
|---|---|---|---|---|
| `verilator` | `verilator` | `verilator` | `verilator` | — |
| `slang` | build-from-source | — | — | https://github.com/MikePopoloski/slang |
| `surelog` | build-from-source | — | — | https://github.com/chipsalliance/Surelog |
| `sv2v` | build-from-source | — | — | https://github.com/zachjs/sv2v |
| `iverilog` | `iverilog` | `icarus-verilog` | `iverilog` | — |
| `yosys` | `yosys` | `yosys` | `yosys` | — |
| `abc` | build-from-source | `berkeley-abc` | — | https://github.com/berkeley-abc/abc |
| `openroad` | build-from-source | — | — | https://github.com/The-OpenROAD-Project/OpenROAD |
| `openlane` | `<PYTHON_EXEC> -m pip install openlane` | `<PYTHON_EXEC> -m pip install openlane` | `<PYTHON_EXEC> -m pip install openlane` | Python package; substitute `<PYTHON_EXEC>` with `python_env.exec` from `tool-status.json` |
| `klayout` | `klayout` | `klayout` | `klayout` (AUR) | — |
| `sta` | build-from-source | — | — | https://github.com/The-OpenROAD-Project/OpenSTA |
| `sby` | `symbiyosys` | — | — | https://github.com/YosysHQ/sby |
| `gem5` | build-from-source | — | — | https://github.com/gem5/gem5 |
| `bambu-hls` | vendor download (Linux only) | — | — | https://github.com/ferrandi/PandA-bambu; WARN on macOS/Windows |
| `nextpnr` | `nextpnr-ice40 nextpnr-ecp5` | `nextpnr` | `nextpnr` | — |
| `openFPGALoader` | `openfpgaloader` | — | — | https://github.com/trabucayre/openFPGALoader |
| `cocotb` | `<PYTHON_EXEC> -m pip install cocotb` | `<PYTHON_EXEC> -m pip install cocotb` | `<PYTHON_EXEC> -m pip install cocotb` | Python package; use `<PYTHON_BIN_DIR>/cocotb-config` or `cocotb-config` to detect |
| `llvm-config` | `llvm-dev` | `llvm` | `llvm` | — |
| `gcc` | `build-essential` | `gcc` | `gcc` | — |
| `openocd` | `openocd` | `open-ocd` | `openocd` | — |
| `xschem` | `xschem` | build-from-source | — | https://github.com/StefanSchippers/xschem |
| `gtkwave` | `gtkwave` | `gtkwave` | `gtkwave` | — |
| `uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (standalone) or `<PYTHON_EXEC> -m pip install uv` | `uv` (brew) or `<PYTHON_EXEC> -m pip install uv` | `<PYTHON_EXEC> -m pip install uv` | Prefer standalone astral.sh installer; pip fallback when custom/module Python is active |

### Output Required
- One `install-<toolname>.sh` per MISSING tool written to `install-missing-tools/` (no single combined script)

---

## Stage: wrapper_deployment

### Domain Rules
1. Deploy all 8 wrapper scripts to `plugins/infrastructure/tools/`
2. Run `chmod +x` on every wrapper; if permission denied: FAIL and escalate with
   `sudo chmod +x` instructions
3. Every wrapper must emit JSON conforming to the schema below regardless of exit code
4. Test each wrapper with `--version` or `--help` after deploy; tolerate MISSING tools
   (wrappers must handle tool-not-found gracefully with `status: "FAIL"`). A `--version`
   run prints no design result, so it returns `status: "WARN"` with `verified: false` —
   that is the expected outcome and confirms the wrapper runs and emits valid JSON
5. Never suppress the tool's original exit code
6. Never report `PASS` without a result: a wrapper that finds nothing it recognises in the
   tool's output reports `WARN` with `verified: false`, even when the tool exited 0

### Wrapper JSON Output Schema
Every wrapper script must print exactly this JSON structure to stdout:
```json
{
  "tool": "<tool-name>",
  "exit_code": 0,
  "status": "PASS|FAIL|WARN",
  "verified": true,
  "summary": {},
  "errors": [],
  "warnings": [],
  "raw_log": "/tmp/<tool>-XXXXXX.log"
}
```

Fields:
- `status`, evaluated in this order:
  1. `FAIL` if exit_code != 0, the output contains an error, a tool-specific fail marker is
     present, or the tool was not found
  2. `WARN` if exit_code == 0 but the wrapper found no result it recognises in the output
     (`verified: false`); the first entry in `warnings` says so
  3. `WARN` if a result was found and the output contains warnings
  4. `PASS` if a result was found and there are no warnings
- `verified`: `true` when `status` rests on something the wrapper observed — a result parsed
  from the output, or a failure. `false` when the tool exited 0 without a recognisable result,
  or did not run. **A result with `verified: false` is not a pass**: read `raw_log`, or the
  tool's own report file, before assigning a stage status
- `summary`: tool-specific metrics (cells, timing, coverage, etc.). A metric the wrapper could
  not find is omitted or `null`, never `0`
- `raw_log`: absolute path to temp file containing full unfiltered output

The MCP adapter (`mcp-adapter.py`) returns `status: "FAIL"` with `verified: false` when a
wrapper prints nothing, prints something that is not JSON, or prints JSON without a valid
`status`: the wrapper contract is to emit this JSON on every run, so anything else means the
wrapper itself produced no result.

### QoR Metrics to Evaluate
- `wrappers_deployed`: count of wrapper scripts with executable bit set (target: 8)

### Output Required
- 8 executable wrapper scripts in `plugins/infrastructure/tools/`

---

## Stage: mcp_configuration

### Domain Rules
1. Emit MCP config snippets for all 10 MCP configs (8 batch + 2 session)
2. All batch configs use `"command": "python3"` with `mcp-adapter.py` — never point
   directly to the wrapper script as the command; wrapper scripts are not MCP servers
3. Session configs use `mcp-session-adapter.py` with `--tool openroad` or `--tool opensta`
4. Resolve the absolute adapter and wrapper paths at runtime using `realpath` or `pwd` —
   never leave the placeholder `/absolute/path/to/` in the emitted snippets
5. Print each snippet with explicit instruction:
   "Paste the `mcpServers` block into your `.claude/settings.json`"
6. Write the snippet files to `plugins/infrastructure/mcp/`
7. Do not modify `.claude/settings.json` automatically — user must do this manually

### MCP Config Template
```json
{
  "mcpServers": {
    "<tool>": {
      "type": "stdio",
      "command": "/absolute/path/to/plugins/infrastructure/tools/wrap-<tool>.sh",
      "args": []
    }
  }
}
```

### QoR Metrics to Evaluate
- `mcp_servers_configured`: count of MCP snippet files written (target: 10)

### Output Required
Batch MCP configs (Tier 1):
- `plugins/infrastructure/mcp/mcp-yosys.json`
- `plugins/infrastructure/mcp/mcp-openroad.json`
- `plugins/infrastructure/mcp/mcp-opensta.json`
- `plugins/infrastructure/mcp/mcp-klayout.json`
- `plugins/infrastructure/mcp/mcp-verilator.json`
- `plugins/infrastructure/mcp/mcp-bambu.json`
- `plugins/infrastructure/mcp/mcp-gem5.json`
- `plugins/infrastructure/mcp/mcp-symbiflow.json`

Session MCP configs (Tier 2):
- `plugins/infrastructure/mcp/mcp-openroad-session.json`
- `plugins/infrastructure/mcp/mcp-opensta-session.json`

Adapter scripts (required — MCP servers will not start without these):
- `plugins/infrastructure/tools/mcp-adapter.py`
- `plugins/infrastructure/tools/mcp-session-adapter.py`

Printed MCP config snippets for each tool with resolved absolute paths

---

## Stage: environment_validation

### Domain Rules
1. **Python environment check** — before any other check: read `python_env` from `tool-status.json`:
   - If `python_env.type == "module"`: run `which python3` to verify the module is still loaded. If it fails, FAIL immediately with: `"Python environment not active — source load-modules.sh (module: <python_env.module_name>) and re-run environment_validation."`
   - If `python_env.type == "custom"` or `"system"`: run `which python3` and verify the path matches `python_env.exec`; emit WARN if it differs.
2. Re-run tool presence checks using the same Python-aware detection as `tool_discovery` rules 2–3: use `"$PYTHON_EXEC" -m pip show` for `openlane`, `"$PYTHON_BIN_DIR/cocotb-config"` for `cocotb`, `"$PYTHON_BIN_DIR/uv"` for `uv` — do not fall back to bare `which` for Python packages. Compare results against `tool-manifest.json`.
3. Verify all 8 wrapper scripts exist and have executable bit set
4. Verify MCP snippet files are present in `plugins/infrastructure/mcp/` (all 10 snippets) and that `mcp-adapter.py` + `mcp-session-adapter.py` are present in `plugins/infrastructure/tools/`
5. FAIL if any critical-path tool (Yosys, Verilator, OpenROAD, OpenSTA) is still `MISSING`
6. For each tool with status `MISSING_LOAD_MODULE` in `tool-status.json`: emit a WARN issue with description `"<tool> not in PATH — available via module"` and fix `"source load-modules.sh, then re-run environment_validation"`
7. If any critical-path tool (Yosys, Verilator, OpenROAD, OpenSTA) has status `MISSING_LOAD_MODULE`: emit WARN and set `suggested_next_step: "escalate"` with message `"Critical tool <tool> requires module load before downstream flows can run. Source load-modules.sh and re-run environment_validation."`
8. Print final sign-off summary: tools detected, tools via modules, wrappers deployed, MCP servers configured

### Sign-off Checklist
- [ ] `tool-status.json` written with all tools surveyed (includes `python_env` object)
- [ ] `module-status.json` written (even if `module_system` is `"none"`)
- [ ] `install-<toolname>.sh` scripts generated for all MISSING tools in `install-missing-tools/` (auto-run is user's choice)
- [ ] `load-modules.sh` generated if any module-available tools found (auto-run is user's choice)
- [ ] `tool-manifest.json` written
- [ ] All 8 wrappers deployed and executable
- [ ] `mcp-adapter.py` and `mcp-session-adapter.py` present in `plugins/infrastructure/tools/`
- [ ] All 10 MCP config snippets written with resolved absolute paths and printed
- [ ] No critical-path tools with status `MISSING` or `MISSING_LOAD_MODULE`

### Output Required
- Printed environment validation report
- Updated `tool-manifest.json` with final confirmed state
