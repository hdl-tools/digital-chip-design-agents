# Infrastructure Domain Knowledge

Tracking is **opt-in** (`pipeline_config.track_infrastructure: true` or `--track-memory`) and
records in `experiences.jsonl` are **environment-keyed** (`host` / `os` / `arch`). When reading
this file, prefer entries whose environment matches the current host — tool versions and quirks
are machine-specific. Lockfiles remain the primary source of truth for exact versions; this
memory captures the *debugging cost* of mismatches, not the canonical version pin.

## Known Failure Patterns

- **Verilator < 5.0 lacks `--timing`**: Designs using `#delay` or event controls fail to
  simulate on Verilator 4.x with `%Error: ... timing controls are not supported`. The fix is to
  build/load Verilator ≥ 5.0 (which adds `--timing`) rather than rewriting RTL. Record the
  detected Verilator version in `tool_versions` so the mismatch is caught at setup, not mid-sim.
- **OpenROAD nightly vs release ABI drift**: Mixing an OpenROAD nightly binary with ORFS scripts
  pinned to a release tag produces opaque Tcl command-not-found errors (`query_drc`, `get_power`
  signatures change between builds). Pin OpenROAD and ORFS to matching tags; when a session
  inherits a different `openroad --version` than the last successful run, flag it before
  debugging the flow itself.
- **`python3` resolves to the wrong interpreter after module unload**: When `python_env.type ==
  "module"`, a fresh shell that did not `source load-modules.sh` falls back to system python3,
  so cocotb/openlane appear MISSING even though they were FOUND last run. The fix is to source
  `load-modules.sh` first; record `python_env.module_name` in notes so the resolution path is
  reproducible.
- **`pgrep`-based "one licensed tool at a time" gates race**: two gates checked, both saw an
  idle host, and two licensed tools started together (twice). A host-wide `flock` held for the
  tool's whole lifetime fixed it; also wait on exact names (`pgrep -x`) for callers not yet using
  the lock. `pgrep -f`/`pkill -f` matched the caller's own command line.
- **A bare `timeout` leaves the vendor `*_exec` child holding a licence**: run each tool with
  `setsid` and kill the process group; cap memory with `systemd-run --user --scope -p
  MemoryMax=...` (`podman --memory` was not enforced for the container).
- **Licensed-tool start-up is slow on a loaded VM**: ICC2 took 30-65 min to start at load 20-55
  (47 s idle); Innovus start plus exit 10-25 min. Record load with any runtime.

## Successful Tool Flags / Install Notes

- `module load <python-module>` before any Python-package detection — keep it loaded for the
  whole orchestrator run; subsequent stages all depend on `PYTHON_EXEC` resolving consistently.
- `"$PYTHON_EXEC" -m pip show openlane` / `"$PYTHON_BIN_DIR/cocotb-config" --version` — always
  use the resolved interpreter path for Python packages; bare `which` gives false MISSING under
  custom/module Python.
- `EDA_TOOLS_ROOT` + `EDA_MODULEFILES_ROOT` env vars drive the install layout; recording their
  values in notes makes a setup reproducible on a sibling workstation.
- `safe_run.sh <log> <cmd>` (wait for load < 6 and enough `MemAvailable`, `MemoryMax` cap,
  `nice`, `setsid`, <= 2 threads, group kill on timeout) inside `licensed_lock.sh <cmd>` (flock)
  ran every commercial tool of a two-week Sky130 campaign on an 8 vCPU / 15 GB VMware guest.
- `ckout_test` for a licence yes/no answer: `lmutil lmstat -a` on the Cadence server printed
  "No socket connection" per feature although checkouts succeeded.

## PDK / Tool Quirks

- **Bambu HLS is Linux-only**: detection on macOS/Windows should land as WARN, not FAIL — record
  `os` in the environment fingerprint so a "missing on macOS" record is not mistaken for a broken
  Linux install.
- **Module version selection follows the site default first, then a release comparator** (was
  lexicographic until issue #98): `module_discovery` prefers the entry `module avail` annotates as
  the system default, falls back to the highest release version, and only picks a non-release build
  (`-dev`, `_test`, `-debug`) when nothing else exists. A site default is frequently *older* than the
  newest build on the shelf — that is deliberate, and `module-status.json` records `selected_basis`
  so the choice is auditable. Pin a module explicitly in `load-modules.sh` only where the site
  default is wrong for a particular flow; it is no longer the routine mitigation it was when
  selection was a plain sort.

## Notes

- This domain is design-independent: `design_name` is usually `null`. Records are differentiated
  by the `environment` fingerprint, not by design.
- `key_metrics.tool_versions` is the primary value-add — a per-tool version map captured at
  `environment_validation`. Comparing it across runs surfaces the exact tool that changed when a
  previously-passing flow starts failing.

_Last distilled: 2026-11-07 from the B0 environment records plus the host-handling issues logged in the pd/sta/formal/synthesis records of the same commercial campaign (2026-10-25 → 2026-11-07)._
