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

#### Roles and dialects (open-source)

`role` groups tools that do the same job. `dialect` names the command-line option and
source-language vocabulary a tool accepts. Two tools with the same `role` and a
different `dialect` are **not** substitutable — a command line built for one is not
valid for the other.

| Tool command | `role` | `dialect` |
|---|---|---|
| `verilator` | `rtl_simulator` | `verilator` |
| `iverilog` | `rtl_simulator` | `icarus` |
| `yosys` | `synthesis` | `yosys` |
| `openroad` | `physical_design` | `openroad` |
| `openlane` | `physical_design` | `openlane` |
| `sta` | `sta` | `opensta` |
| `sby` | `formal` | `symbiyosys` |
| `klayout` | `drc_lvs` | `klayout` |
| `bambu-hls` | `hls` | `bambu` |
| `gem5` | `arch_simulator` | `gem5` |
| `nextpnr` | `fpga_pnr` | `nextpnr` |

Every other open-source tool — `slang`, `surelog`, `sv2v`, `abc`, `openFPGALoader`,
`cocotb`, `llvm-config`, `gcc`, `openocd`, `xschem`, `gtkwave`, `uv`, `python3` — has
no same-role peer here and is recorded `"role": null, "dialect": null`. Never invent a
role to fill the field: a `null` cannot produce a false conflict.

### Proprietary (detect only — never install)

| Tool | Command (alt) | `role` | `dialect` | Version probe (license-free) |
|---|---|---|---|---|
| Synopsys VCS | `vcs` | `rtl_simulator` | `synopsys` | `vcs -ID` — parse the `Compiler version` line only |
| Cadence Xcelium | `xrun` (`xmsim`) | `rtl_simulator` | `cadence` | `xrun -version` — parse the `TOOL:<tab>xrun(64)<tab><version>` line |
| Mentor QuestaSim | `vsim` (`questa`, `questasim`) | `rtl_simulator` | `siemens` | none — UNVERIFIED |
| Synopsys Design Compiler | `dc_shell` (`dc_shell-t`) | `synthesis` | `synopsys` | `dc_shell -version` — parse the `dc_shell version` line |
| Cadence Innovus | `innovus` | `physical_design` | `cadence` | none — UNVERIFIED |
| Synopsys PrimeTime | `pt_shell` (`pt_shell64`) | `sta` | `synopsys` | `pt_shell -version` — parse the `pt_shell version` line |
| Synopsys Formality | `fm_shell` (`formality`) | `lec` | `synopsys` | `fm_shell -version` — parse the `Formality (R) Version` line |

**`vcs -ID` also prints a FLEXlm host ID.** Parse and store the `Compiler version`
value only — never write the host ID into `tool-status.json`.

**A probe flag is listed only once confirmed on a real install** — a guessed flag can open
an interactive shell or check out a license. The flags above were each measured: exit 0
with the named line present, in 1–26 s, no license queue. `dc_shell -version` prints an
unrelated ASLR advisory first, so parse the line containing `version`, never the first line
of output.

**The two `UNVERIFIED` rows are unverified upstream, not an oversight.** Neither could be
confirmed on the reference host, and in both cases the obstacle was the install rather than
the flag: `innovus -version` exits 0 reporting an expired build authorisation, and
`vsim -version` exits 0 failing to load `libXext.so.6`. A site with a working install of
either should confirm the flag and contribute it here.

Note on Formality: the primary command is `fm_shell`. `formality` is the legacy GUI wrapper
and is absent from recent installs, so it is listed as the alternate.

Same `role` with a different `dialect` means the two tools are not interchangeable
however similar their purpose. `environment_validation` reports such coexistence.

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
| `mcp-verilator.json` | Verilator lint (`mode: "lint"`) or a compiled sim binary (`mode: "sim"`) | seconds–minutes |
| `mcp-bambu.json` | Bambu HLS synthesis | minutes |
| `mcp-gem5.json` | gem5 short benchmark run | minutes (set TOOL_TIMEOUT_S) |
| `mcp-symbiflow.json` | SymbiYosys bounded proof | minutes–hours (set TOOL_TIMEOUT_S) |

The adapter is `plugins/infrastructure/tools/mcp-adapter.py`. Each server runs the one wrapper
named by `--wrapper`, except `verilator`: `mode: "lint"` runs `wrap-verilator-lint.sh` from the
same directory as the configured `wrap-verilator-sim.sh`, because the sim wrapper's first
argument is a compiled simulation binary. The 8 batch servers therefore use 9 wrappers.

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
   a. Classify the module system and prove it is invocable using the detection rules and the
      invocation ladder in `module_discovery` below. Do not re-derive either here, and never treat
      `$MODULESHOME` alone as proof that `module` can be run.
   b. If a listing was obtained (`module_listing` is `"LISTED"`), search it for entries matching
      `python` or `python3` (case-insensitive).
   c. If one or more Python module entries are found: select one per **Module version selection** in
      `module_discovery` below — never by a plain sort — then load it via
      `module load <python-module>` and run `which python3` to resolve `PYTHON_EXEC`. The non-release
      exclusion matters more here than anywhere else: an interpreter chosen here stays loaded for the
      whole run, so a `_test` or `-debug` build selected at this step becomes the Python every later
      stage resolves against. Set `python_env.type = "module"` and record `python_env.module_name` with the loaded module name. **Keep the module loaded for the entire orchestrator run** — do not unload it; subsequent stages (tool_installation, wrapper_deployment, environment_validation) all depend on `PYTHON_EXEC` being resolvable. The generated `load-modules.sh` handles persistent loading for future shell sessions.
   d. Proceed to Step B where `module_system` is `"none"`, where the ladder was exhausted
      (`module_listing` is `"UNAVAILABLE"`), or where the listing holds no Python module entries.
      A detected-but-unlistable module system is **not** the same as no module system: it still
      falls through to the PATH interpreter here, but the WARN it owes is emitted by
      `module_discovery` and is not suppressed because this step recovered an interpreter.

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
4. **Proprietary tools**: check PATH using `which <primary-executable>` (primary and
   alternate names are in the Proprietary table above); never attempt install; record as
   `PROPRIETARY_ONLY` if found, `MISSING` otherwise. For a tool found in PATH that has a
   version probe in that table, run the probe with a 60 s timeout, parse the documented
   line, and store the parsed string in `version`. Do not use a short timeout: a Cadence
   Common UI tool starts a full shell to answer `-version` and takes tens of seconds on a
   cold NFS cache (`genus -version` measured 26 s cold, 12 s warm). For `vcs`, store the
   `Compiler version` value only — discard the FLEXlm host ID.

   Leave `version` empty and emit a WARN naming the tool and the reason when the table
   lists no probe, when the probe times out, when it exits non-zero, **or when it exits 0
   without printing the documented line**. Record a version only when that line was actually
   found: exit 0 does not mean a version was printed.

   Measured on the reference host by invoking each tool directly: `innovus -version` answers
   0 with an expired build authorisation, `voltus -version` answers 0 with "cannot find a
   proper installation", and `vsim -version` answers 0 having failed to load a shared
   library. **None of those three has a probe in the table above**, so this stage reaches an
   empty `version` for them through the no-probe condition, not the last one. They are cited
   as evidence that a broken install answers 0 whatever the vendor — which is why the last
   condition has to guard the five tools that *do* carry a probe, whose installs can break
   the same way. A version probe never fails the stage.
5. Record each tool as one of: `FOUND`, `MISSING`, or `PROPRIETARY_ONLY`
6. Capture the exact version string for every tool found in PATH — `FOUND` tools via
   rule 1, and `PROPRIETARY_ONLY` tools that have a version probe in the Proprietary
   table via rule 4
7. Set `role` and `dialect` on every entry in the `tools` array from the Proprietary and
   Roles-and-dialects tables above; use `null` for both where the tool appears in neither
8. Never attempt installation in this stage
9. Write results to `tool-status.json` before advancing

### QoR Metrics to Evaluate
- `tools_detected`: count of FOUND tools (target ≥ 10 for a functional open-source flow)
- `tools_missing`: count of MISSING open-source tools
- `proprietary_found`: count of PROPRIETARY_ONLY tools detected in PATH
- `proprietary_versioned`: count of PROPRIETARY_ONLY tools with a non-empty `version`
- `dialect_conflicts`: count of **roles** (not pairs) held by detected tools of two or more
  differing `dialect` values where at least one is `PROPRIETARY_ONLY`

### Output Required
- `tool-status.json` — contains two top-level keys:
  - `python_env`: `{ "exec": "", "type": "module|system|custom", "bin_dir": "", "module_name": "" }` — populated by rule 2
  - `tools`: array of `{ "tool": "", "command": "", "status": "FOUND|MISSING|PROPRIETARY_ONLY", "version": "", "path": "", "role": null, "dialect": null }`

`role` and `dialect` are always present on every entry — a string from the tables above,
or `null`. `version` is non-empty for every `FOUND` tool and for every `PROPRIETARY_ONLY`
tool whose probe succeeded.

`tool` and `command` both hold the **command** — the executable name `which` is run against,
as listed in backticks in the Open-Source and Proprietary tables above. `module-status.json`
records the same value (`"tool": "<command>"`), which is what lets `module_discovery` match its
entries back into this file. Product names belong in prose and in the first column of the
Proprietary table; **never in a field a rule matches on**. A rule that names a product cannot
find its entry wherever the two differ — OpenSTA's command is `sta`, Formality's is `fm_shell` —
and "no entry found" is not the same answer as "tool missing".

This applies to `tool-status.json` and `module-status.json` only. The Wrapper JSON Output Schema
below deliberately uses a different convention — `"tool": "<tool-name>"`, a wrapper label such as
`opensta` or `verilator-sim` — because that field identifies which wrapper produced the record, not
an entry to match. Do not "correct" the wrappers to emit commands.

Note: module-based availability (`FOUND_PREFER_MODULE`, `MISSING_LOAD_MODULE`) and the `module_names`/`versions_available` fields are added in the next stage (`module_discovery`).

---

## Stage: module_discovery

### Domain Rules

#### Module system detection

A set environment variable is not proof that `module` can be run. Classify first, then **prove
invocability** with the ladder below — the ladder decides, not the classification.

1. `modulecmd` is in PATH ⇒ `module_system: "tclmod"`. Record in `module_system_detail` whether
   `$MODULESHOME` is also set.
2. `$MODULESHOME` is set and `modulecmd` is **not** in PATH ⇒ `module_system: "custom"`. Read this
   as *not confirmed Environment Modules*, never as *proven bespoke*: a classic install can have
   `modulecmd` off PATH, and rung 3 below is what tells the two apart.
3. Neither ⇒ `module_system: "none"`, `module_listing: "UNAVAILABLE"`,
   `module_listing_error: "no module system present"`; emit the "none" WARN below, skip the
   remaining rules, write `module-status.json`, advance to `tool_installation`.

#### Module invocation ladder
`module` is frequently a **shell function or alias**, not a binary, so it is absent from a
non-interactive shell even on a host where a module system is plainly installed. Probe the
invocation; never infer it from an env var. Try these in order, stop at the first rung that
**succeeds** by the test below, and record that rung verbatim in `module_invocation`.

| # | Invocation | When, and what it proves |
|---|---|---|
| 1 | `module avail` | the orchestrator's own shell may already define `module`, if it was started as an interactive or login shell |
| 2 | `modulecmd bash avail` | only where `modulecmd` is in PATH; a listing here confirms `tclmod` |
| 3 | `. "$MODULESHOME/init/bash"; module avail` | classic Environment Modules ships `init/bash`; a listing here **upgrades** `custom` to `tclmod`, and `module_system_detail` records that `modulecmd` was merely off PATH |
| 4 | `. "$MODULESHOME/module.sh"; module avail` | a site wrapper's sh init. Measured on the reference host: `module` becomes a shell function and `module avail` exits 0 in 159.5 s with 3813 lines, 3812 of them entry-shaped. Classification stays `custom` |
| 5 | `MODULESHOME="$MODULESHOME" "$MODULESHOME/module" avail` | last resort, where the wrapper is itself an executable script. Export in addition any path variable the wrapper's own init script sets, which a site wrapper commonly uses in place of `$MODULESHOME` |

- **A rung succeeds only where it exits 0 *and* its output holds at least one entry-shaped line.
  Either test alone is insufficient; a failed rung means advance to the next, never conclude the
  host has no modules.** Both halves are measured. Rung 5 on the reference host exits **1** and
  prints `Usage: [-n] subcommand [arguments ...]` — and that usage text itself contains the lines
  `modulename/scope`, `modulename/version` and `modulename/scope/version`, so an output-shape test
  on its own reads a failed rung as a successful listing of three modules named `modulename`. The
  converse case — exit 0 with no listing — is the failure mode already documented for version
  probes in `tool_discovery` rule 4, where a broken install answers 0 whatever the vendor.
- **Wrap the shell, not the command.** `timeout` execs a binary and cannot wrap a shell function:
  measured, `timeout 60 module avail` returns 127 with `timeout: failed to run command 'module'`
  on a host where rung 4 had just succeeded. Run every rung as
  `timeout 300 bash -c '<rung>; module avail </dev/null 2>&1'`.
- **Budget 300 s, not the 60 s used for version probes.** The listing walks every modulefile tree:
  159.5 s measured on a warm NFS cache, emitting `ls: cannot access ...` noise from stale paths on
  the way. A short budget records a working module system as unprobeable.
- **Always redirect stdin from `/dev/null`.** A wrapper that prompts would otherwise block the
  whole run and produce no output to diagnose.
- Where every rung is exhausted: set `module_listing: "UNAVAILABLE"` and put the last rung's
  stderr in `module_listing_error`. Only an exhausted ladder is a WARN — an individual failed rung
  is not.

#### Listing entry format
Entries hold **two or more** `/`-separated segments and may carry a trailing parenthesised
annotation. Measured on the reference host: `klayout/adi/0.29.0`, `verilator/adi/3.922`,
`klayout/adi/0.27.11 (adi default)`. Take the version as the **last** `/`-separated segment after
removing any trailing `(...)` annotation, and keep the entry string without that annotation in
`module_names`. Never assume `<name>/<version>` — that records `adi` as the version of
`klayout/adi/0.29.0`.

**The annotation is data, not noise.** An entry whose annotation contains `default`
(case-insensitive) is the module system's own default for that tool — on the reference host
`klayout/adi/0.27.11 (adi default)` marks it. Record which entry carried it; the selection rule below
prefers it over any version this stage computes.

Match the mapping table against the entry read as a list of `/`-delimited tokens, case-insensitively:
a pattern matches only where it covers **whole tokens** — one token, or a contiguous run of them for
a pattern that itself contains `/`. **Never match an arbitrary substring.** Measured against a
real 3812-entry listing, substring matching produced two classes of false positive: a module whose
name merely *ends* with a mapped command (an optimisation tool named `...slang` matched `slang`),
and a module whose name or version string merely *contains* one (a verification tool whose version
ends `_python2`, and a GUI tool bundle whose name contains `python3`, both matched `python3`). The
second class is the damaging one: `tool_discovery` Step A loads the selected matched Python module
and keeps it loaded for the whole orchestrator run, and the top-ranking substring match was
that GUI bundle rather than an interpreter. Whole-token matching drops both classes and leaves the
12 genuine tools.

#### Module version selection
Wherever this skill chooses a version for a tool — `tool_discovery` rule 2 Step A c and rule 9 below
— it uses this rule. Do not restate it at the call sites and do not substitute a plain sort:
**"highest lexicographic" and "newest" are different answers**, and on a real tree the lexicographic
one is wrong: measured on the reference host, a 13-version Python tree spanning 3.6.x–3.14.x has
newest `3.14.6` and lexicographic maximum `3.9.7` — the fourth-oldest — because `"9" > "1"` at the
second segment.

The result is *the version this host should use*, which is **not** always the newest one: where the
module system marks a default, that default wins, and a site default is commonly an older, qualified
build. On the same host the annotated default differed from the newest available for every tool
checked, by several versions for some. That is intended, not a bug to work around.

**Selection order.** Take the first that applies:

1. the entry the listing annotates as the system's `default`, where it marks one — that is the site's
   own answer and outranks anything computed here;
2. otherwise the highest **release** version by the comparator below;
3. otherwise the highest version at all — only where every candidate is non-release.

**Non-release versions** are those with any segment equal to `dev`, `test`, `debug`, `rc`, `alpha`,
`beta`, `snapshot` or `nightly`, case-insensitively. They stay in `versions_available` — they exist
and a user may want one — but they are never selected automatically while a release exists. This
matters because such builds sit in the same trees as releases: the reference host carries
`3.12.2_test`, `3.6.2-debug` and `5.24-dev` alongside normal versions. Note the list is deliberately
short: a site revision tag such as `3.12.2.R10`, or a patch letter such as `3.9.7n`, is a **release**
and is ordered by the comparator like any other.

**Comparator.** Split each version on `.`, `-` and `_`, then compare segment by segment:

- both segments numeric — compare as integers, so `3.14.6` > `3.9.7`;
- a segment of digits followed by letters (`7n`, `03b`) — compare its numeric prefix first, then its
  letter suffix as text, so `3.9.7n` > `3.9.7`;
- one numeric and one not — the numeric ranks higher;
- neither numeric — compare as text.

Where every shared segment is equal, the version with **more** segments ranks higher — both
`3.12.2.1` > `3.12.2` and `3.12.2.R10` > `3.12.2`, since an extra segment denotes a revision *of* the
shorter version. Do not special-case a non-numeric extra segment to rank lower: the case that
motivates it, `5.24` over `5.24-dev`, is already handled by the non-release exclusion above, and
inside the release pool the only remaining extras are post-release revision tags, for which longer
genuinely is newer.

This set is the one that breaks every naive form, and is worth checking any implementation against —
`3.9.7`, `3.9.7n`, `3.12.2`, `3.12.2.1`, `3.12.2.R10`, `3.14.6`, `5.048`, `5.24-dev`: text comparison
picks `3.9.7`, splitting on `.` and comparing as integers raises on `R10`, and comparing by segment
count alone picks `5.24-dev` unless the non-release exclusion has already removed it.

Record the outcome per tool in `module-status.json` as `selected`, `selected_basis` and `candidates`,
so a wrong pick is visible in the artifact rather than only in the loaded environment.

#### WARN taxonomy
| Condition | Severity | `description` / `fix` |
|---|---|---|
| `module_system: "none"` | WARN, proceed | `"no module system found - $MODULESHOME unset and modulecmd not in PATH; no tools surveyed via modules"` / `"no action needed if every required tool is in PATH"` |
| `module_system` is not `"none"` and `module_listing: "UNAVAILABLE"` | WARN, proceed | `"<module_system> module system detected (<module_system_detail>) but no invocation produced a listing (<module_listing_error>) - tools_via_modules is empty because the listing failed, not because no modules exist"` / `"re-run from a shell where module resolves, or source $MODULESHOME/module.sh (bash) or $MODULESHOME/module.csh (tcsh) first, then re-run module_discovery"` |
| the row above **and** a critical-path tool (`yosys`, `verilator`, `openroad`, `sta`) is `MISSING` in `tool-status.json` | WARN **and escalate** | that description with `" - critical tool(s) <list> are MISSING and could not be checked against the module listing"` appended; `failure_class: "tool_error"`, `suggested_next_step: "escalate"` |

An empty `tools_via_modules` is evidence that the host offers no modules **only** when
`module_listing` is `"LISTED"`. Never report an exhausted ladder as "no modules found": the two
are indistinguishable in the artifact unless `module_listing` is read.

The fix text names both init scripts because the probes all run under `bash -c` regardless of the
user's login shell, but a user re-running by hand may be in either `bash` or `tcsh`.

#### Module-to-tool mapping table

| Tool command | Module name patterns to match (case-insensitive substring) |
|---|---|
| `vcs` | `vcs`, `synopsys-vcs`, `synopsys/vcs` |
| `xrun` | `xcelium`, `cadence-xcelium`, `cadence/xcelium` |
| `dc_shell` | `design-compiler`, `synopsys/dc`, `dc_shell` |
| `innovus` | `innovus`, `cadence/innovus`, `cadence-innovus` |
| `vsim` | `questa`, `questasim`, `mentor/questa` |
| `pt_shell` | `primetime`, `synopsys/pt`, `pt_shell` |
| `fm_shell` | `formality`, `synopsys/formality`, `fm_shell` |
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
1. Classify the module system using the detection rules above
2. Obtain a listing using the invocation ladder above; record `module_invocation` and
   `module_listing`, and on exhaustion `module_listing_error`
3. If `module_listing` is `"UNAVAILABLE"`: emit the matching WARN from the taxonomy above —
   escalating first where a critical-path tool is `MISSING` — write `module-status.json` with
   `tools_via_modules: []`, and advance. Skip rules 4-9: no tool can be matched against a listing
   that was never obtained, and an unmatched tool is not evidence that no module provides it
4. For each entry in the listing, test against the mapping table (case-insensitive)
5. For each matched tool, collect all available version strings per the entry-format rules above
6. Write `module-status.json` before advancing
7. For each tool marked `FOUND` in `tool-status.json` that also has a module available: change status to `FOUND_PREFER_MODULE`, add `module_names` and `versions_available` fields, include in `load-modules.sh` — module takes precedence over PATH version
8. For each tool marked `MISSING` in `tool-status.json` that has modules available: change status to `MISSING_LOAD_MODULE`, add `module_names` and `versions_available` fields
9. Generate `load-modules.sh` for all `FOUND_PREFER_MODULE` and `MISSING_LOAD_MODULE` tools; choose each tool's version per **Module version selection** above; comment out alternative versions inline, and state the basis in the selected line's trailing comment
10. Never auto-run `load-modules.sh` — print: "Review and source `load-modules.sh` to load EDA modules, then re-run the flow"

#### Extended `tool-status.json` schema
Fields added by this stage to each entry in the `tools` array (backward-compatible additions):
```json
{
  "tool": "",
  "command": "",
  "status": "FOUND | FOUND_PREFER_MODULE | MISSING | MISSING_LOAD_MODULE | PROPRIETARY_ONLY",
  "version": "",
  "path": "",
  "role": null,
  "dialect": null,
  "module_names": [],
  "versions_available": []
}
```

Note: The top-level `python_env` object is **preserved unchanged** during this stage — only entries in the `tools` array are modified. The `python3` tool entry is treated like any other: if `python_env.type == "module"`, its `tools` array status is upgraded from `FOUND` to `FOUND_PREFER_MODULE` and it is included in `load-modules.sh`. The
`version`, `role` and `dialect` fields written by `tool_discovery` are also preserved
unchanged — this stage adds module fields and may change `status`, nothing else.

### QoR Metrics to Evaluate
- `module_system_detected`: bool — true when `module_system` is not `"none"`; a custom wrapper counts
- `module_listing_ok`: bool — true when `module_listing` is `"LISTED"`. `tools_found_via_modules: 0` is only meaningful when this is true; where it is false the count says nothing about what the host offers
- `tools_found_via_modules`: count of tools with status `MISSING_LOAD_MODULE` or `FOUND_PREFER_MODULE`

### Stage Output Summary
Print a human-readable table before advancing:
```text
Module system     : custom - $MODULESHOME=<site path>, no modulecmd in PATH, no init/bash
Module listing    : LISTED via `. "$MODULESHOME/module.sh"; module avail` (3813 entries, 160s)
Tools in PATH     : 12
Tools via modules : 5
  vcs        — selected synopsys/vcs/2021.01 (highest_release, 2 candidates); also 2020.03
  xrun       — selected cadence/xcelium/20.09 (site_default, 1 candidate)
  dc_shell   — selected synopsys/dc/2022.03 (site_default, 3 candidates); also 2021.06, 2020.09
  innovus    — selected cadence/innovus/21.1 (highest_release, 2 candidates); also 20.12
  pt_shell   — selected synopsys/primetime/2022.06 (site_default, 2 candidates); also 2021.06
```

Always print the basis and the candidate count. A `site_default` that is several versions behind the
newest available is normal and intended; `highest_prerelease` is not, and is the one to notice.

Where the invocation ladder was exhausted, the second line reads
`Module listing    : UNAVAILABLE (<module_listing_error>)` and the `Tools via modules` count is
printed as `not surveyed` — never as `0`, which reads as a surveyed host that offers nothing.

### Output Required
- `module-status.json` — module system details and per-tool module listings
- Updated `tool-status.json` — statuses and module fields added for matched tools
- `load-modules.sh` — generated when any tool has status `FOUND_PREFER_MODULE` or `MISSING_LOAD_MODULE`; omitted when **no tool qualifies**, which includes but is not limited to `module_system: "none"`. Never infer the omission from `module_system` alone: a detected system whose `module_listing` is `"UNAVAILABLE"` also yields no qualifying tools, and that is the WARN case above, not a clean skip

`module-status.json` schema:
```json
{
  "module_system": "tclmod | custom | none",
  "module_system_detail": "<evidence: $MODULESHOME value, whether modulecmd was in PATH, what was found under $MODULESHOME>",
  "module_system_version": "",
  "module_listing": "LISTED | UNAVAILABLE",
  "module_invocation": "<the ladder rung that produced the listing, verbatim, or null>",
  "module_listing_error": null,
  "tools_via_modules": [
    {
      "tool": "<command>",
      "module_names": ["synopsys/vcs/2020.03", "synopsys/vcs/2021.01"],
      "versions_available": ["2020.03", "2021.01"],
      "selected": "synopsys/vcs/2021.01",
      "selected_basis": "site_default | highest_release | highest_prerelease",
      "candidates": 2
    }
  ]
}
```

`module_system` says what is installed; `module_listing` says whether `tools_via_modules` can be
trusted. The two are independent: a `tclmod` host can be `UNAVAILABLE`, and a `custom` host can
be `LISTED`. `module_system: "none"` always pairs with `module_listing: "UNAVAILABLE"` and
`module_listing_error: "no module system present"`, so one field answers trustworthiness in every
case.

`load-modules.sh` format:
```bash
#!/usr/bin/env bash
# Generated by module_discovery — source this file to load EDA tool modules
# Usage: source load-modules.sh

module load synopsys/vcs/2021.01       # selected: highest_release; alternatives: 2020.03
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
1. Deploy all 9 wrapper scripts to `plugins/infrastructure/tools/`
2. Run `chmod +x` on every wrapper; if permission denied: FAIL and escalate with
   `sudo chmod +x` instructions
3. Every wrapper must emit JSON conforming to the schema below regardless of exit code
4. Test each wrapper with `--version` or `--help` after deploy; tolerate MISSING tools
   (wrappers must handle tool-not-found gracefully with `status: "FAIL"`). A `--version`
   run prints no design result, so it returns `status: "WARN"` with `verified: false` —
   that is the expected outcome and confirms the wrapper runs and emits valid JSON.
   `wrap-verilator-sim.sh` takes a simulation binary, not tool arguments, so it answers
   `--version` / `--help` itself with the same `WARN`. A `FAIL` from this test therefore always
   means a missing tool or a broken wrapper, never a mis-invocation
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
- `wrappers_deployed`: count of wrapper scripts with executable bit set (target: 9)

### Output Required
- 9 executable wrapper scripts in `plugins/infrastructure/tools/`

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

**Critical-path tools** are the `tool-status.json` entries whose `tool` is `yosys`, `verilator`,
`openroad` or `sta` — Yosys, Verilator, OpenROAD and OpenSTA. Every rule below that tests them
matches **on that key, never on the product name**: OpenSTA's command is `sta`, so a rule looking
for `"OpenSTA"` matches no entry and cannot conclude the tool is missing. On a FAIL gate that is a
silent pass.

1. **Python environment check** — before any other check: read `python_env` from `tool-status.json`:
   - If `python_env.type == "module"`: run `which python3` to verify the module is still loaded. If it fails, FAIL immediately with: `"Python environment not active — source load-modules.sh (module: <python_env.module_name>) and re-run environment_validation."`
   - If `python_env.type == "custom"` or `"system"`: run `which python3` and verify the path matches `python_env.exec`; emit WARN if it differs.
2. Re-run tool presence checks using **exactly** the detection `tool_discovery` rules 2–3 perform —
   including their PATH fallbacks, and including their `python_env.type` branches. A stage that
   detects the same tool by a different method will disagree with `tool_discovery` on real installs,
   and the disagreement is silent:
   - `openlane`: `"$PYTHON_EXEC" -m pip show openlane` — unchanged, rule 3 has no fallback for it
   - `cocotb`, `uv`: where `python_env.type` is `custom` or `module`, try
     `"$PYTHON_BIN_DIR/<tool>"` first and **fall back to the PATH command**; where it is `system`,
     use the PATH command only — rule 3 never builds a `$PYTHON_BIN_DIR` probe in that case, so
     neither may this rule.

   Record for each package which path resolved it, as `resolved_via` in `tool-manifest.json`. Where
   a package resolved **via the PATH fallback** while `python_env.type` is `custom` or `module`,
   emit a WARN — the tool exists, so this is never an absence:
   - description: `"<tool> resolved on PATH at <path>, outside the active Python environment's bin dir (<python_env.bin_dir>) — it may target a different interpreter than <python_env.exec>"`
   - fix: `"confirm <tool> operates on the intended interpreter, or reinstall it into the active environment with \"$PYTHON_EXEC\" -m pip install <tool>"`

   This is the hazard the probe is for, and it is common: `tool_installation` prefers the standalone
   astral.sh installer for `uv`, which installs into its own prefix rather than `$PYTHON_BIN_DIR`.
   Measured on the reference host, `uv` resolves from a shared `bin` directory unrelated to the
   active interpreter's prefix, which is exactly this case.
   Never emit it for `python_env.type == "system"`, where PATH *is* the active environment.

   Compare results against `tool-status.json` — written by `tool_discovery`, updated in place by
   `module_discovery`, and the only tool record that exists when this rule runs. Never compare
   against `tool-manifest.json`: that is this stage's own output, so on any run there is nothing to
   compare against. This stage reads `tool-status.json` and does not write it; a disagreement is a
   WARN, never a status downgrade.
3. Verify all 9 wrapper scripts exist and have executable bit set
4. Verify MCP snippet files are present in `plugins/infrastructure/mcp/` (all 10 snippets) and that `mcp-adapter.py` + `mcp-session-adapter.py` are present in `plugins/infrastructure/tools/`
5. FAIL if any critical-path tool (`yosys`, `verilator`, `openroad`, `sta`) is still `MISSING`.
   Escalate — do not loop back to `tool_installation`: that stage only *generates*
   `install-<toolname>.sh` and never executes it (`tool_installation` rule 1), so no retry can
   change a tool's status. Report the missing commands and tell the user to review and run the
   generated scripts in `install-missing-tools/`, then re-run `environment_validation`.
6. For each tool with status `MISSING_LOAD_MODULE` in `tool-status.json`: emit a WARN issue with description `"<tool> not in PATH — available via module"` and fix `"source load-modules.sh, then re-run environment_validation"`
7. **Dialect-conflict check** — group by `role` every tool whose status is `FOUND`,
   `FOUND_PREFER_MODULE`, `PROPRIETARY_ONLY` or `MISSING_LOAD_MODULE`, ignoring entries whose
   `role` is `null`. A `MISSING_LOAD_MODULE` tool counts: it is one the user will load and
   build a command line for, which is exactly what this check warns about. Only `MISSING`
   is excluded. Emit **one** WARN issue per `role` that holds two or more distinct `dialect`
   values **and** at least one `PROPRIETARY_ONLY` tool.
   One WARN per role, never one per pair: a role with five members yields ten pairs saying
   the same thing, and that volume is what makes a warning ignorable.
   - description: `"role <role> is held by tools of differing dialects: <tool_a> (<dialect_a>), <tool_b> (<dialect_b>), … — command lines are not portable between them"`
   - fix: `"pick one dialect per role for this flow and build command lines from that vendor's option set; do not reuse a command line across dialects"`

   List every member tool in the one description, so the reader sees the whole conflicting
   set. Report the number of such **roles** — not pairs, not tools — as `dialect_conflicts`.
   This is WARN only: it never FAILs the stage and never blocks `environment.signoff`.
   Coexistence is normal — what is not normal is assuming substitutability. Requiring at
   least one proprietary tool in the group keeps the WARN rare enough to be read; two
   open-source simulators are on nearly every host.
8. If any critical-path tool (`yosys`, `verilator`, `openroad`, `sta`) has status `MISSING_LOAD_MODULE`: emit WARN and set `suggested_next_step: "escalate"` with message `"Critical tool <tool> requires module load before downstream flows can run. Source load-modules.sh and re-run environment_validation."`
9. Print final sign-off summary: tools detected, tools via modules, wrappers deployed, MCP servers configured

### Sign-off Checklist
- [ ] `tool-status.json` written with all tools surveyed (includes `python_env` object)
- [ ] `module-status.json` written (even if `module_system` is `"none"`)
- [ ] `install-<toolname>.sh` scripts generated for all MISSING tools in `install-missing-tools/` (auto-run is user's choice)
- [ ] `load-modules.sh` generated if any module-available tools found (auto-run is user's choice)
- [ ] `tool-manifest.json` written by this stage, matching the schema in Output Required
- [ ] All 9 wrappers deployed and executable
- [ ] `mcp-adapter.py` and `mcp-session-adapter.py` present in `plugins/infrastructure/tools/`
- [ ] All 10 MCP config snippets written with resolved absolute paths and printed
- [ ] No critical-path tools with status `MISSING` or `MISSING_LOAD_MODULE`
- [ ] `role` and `dialect` recorded on every entry in `tool-status.json`, and every
      same-role/different-dialect coexistence involving a proprietary tool reported

### Output Required
- Printed environment validation report
- `tool-manifest.json` — written by this stage. There is no prior manifest to update: no earlier
  stage produces one, so this stage creates it.

`tool-manifest.json` is a **validation receipt, not a tool list.** It records what this stage
measured and *references* per-tool state rather than copying it — `tool-status.json` already carries
every per-tool field (`tool`, `command`, `status`, `version`, `path`, `role`, `dialect`,
`module_names`, `versions_available`) and `python_env`, and `module_discovery` sets the precedent
that a later stage updates that file in place rather than forking a parallel copy. A manifest that
restated those fields would be a second source of truth for the same facts.

What this stage establishes that `tool-status.json` cannot express is `python_env` **liveness** (the
recorded module may no longer be loaded, the recorded `exec` may no longer match), wrapper
executable bits, MCP artifact presence, the computed dialect-conflict set, and the sign-off verdict:

```json
{
  "run_id": "",
  "timestamp": "<ISO-8601>",
  "host": "",
  "tool_status_source": "tool-status.json",
  "python_env_live": {
    "type": "module | system | custom",
    "exec_expected": "",
    "exec_actual": "",
    "matches": false
  },
  "python_packages": [
    {
      "tool": "",
      "resolved_via": "python_env_bin_dir | path | pip_show",
      "path": ""
    }
  ],
  "wrappers": { "expected": 8, "executable": 0, "missing": [] },
  "mcp": { "snippets_expected": 10, "snippets_present": 0, "adapters_present": false, "missing": [] },
  "dialect_conflicts": [
    { "role": "", "members": [ { "tool": "", "dialect": "" } ] }
  ],
  "critical_path": { "required": ["yosys", "verilator", "openroad", "sta"], "missing": [] },
  "signoff": false
}
```

`python_packages[].resolved_via` is the record behind rule 2's WARN: it is what makes "found, but
outside the active environment" auditable after the run instead of print-only. `dialect_conflicts`
lists the members per role, not just the count rule 7 reports, so the conflict can be read back
without re-deriving it.
