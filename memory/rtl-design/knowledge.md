# RTL Design Domain Knowledge

## Known Failure Patterns

- **Verilator -Wall catches implicit wire declarations**: Verilator with `-Wall` catches implicit
  wire declarations that SpyGlass and Synopsys DC may silently accept. Always run Verilator lint
  first — it surfaces issues that prevent correct synthesis even when proprietary tools do not error.
- **CDC violations from multi-bit signals**: Multi-bit signals crossing clock domains require both
  a synchronizer AND Gray encoding. A 2-FF synchronizer alone is insufficient for multi-bit vectors;
  the intermediate states cause functional errors that are intermittent and hard to reproduce in
  simulation.
- **Async reset flops need reset-removal SDC constraints**: Asynchronous reset flops require
  explicit reset-removal timing constraints in the SDC (`set_max_delay -datapath_only` from reset
  deassertion to first flop clock edge). Without these, STA will either flag false violations or
  miss real metastability windows.
- **Stale generated headers on the include path look like RTL bugs**: Include search is
  first-match-wins. When two generations of a generated header tree (register map, IP config) are
  both on the include path and the stale one is listed first, lint reports duplicate-declaration
  fatals (the stale header still declares what the RTL now declares) **and** undeclared-identifier
  fatals (fields that exist only in the current generation) in the same run. Check the resolved
  filelist before touching RTL: the fix is one filelist line, and the "duplicate" port is real.
- **A lint run that aborted says nothing about the RTL**: If the tool reports that rule checking
  aborted or did not complete, zero rules ran. Never loop a setup failure back to `rtl_coding`;
  classify it `input_setup` and escalate. Once the input set is fixed, expect the real findings to
  appear for the first time — they were masked by the abort, not introduced by the fix.
- **A user-override config directory can bypass the managed project file**: Several vendor flow
  wrappers prefer a user-override directory over the managed configuration. A stale override
  silently replaces the managed project file and every variable it would have set. Print the
  absolute path of the project file the tool actually read before trusting its result.

## Successful Tool Flags

- `verilator --lint-only -Wall -Wno-DECLFILENAME <files>` — `-Wno-DECLFILENAME` suppresses the
  common false positive where file name doesn't match module name; keep all other `-Wall` checks.
- `slang -Weverything --ignore-unknown-modules --allow-use-before-declare --strict-driver-checking <files>`
  — full elaboration; `--strict-driver-checking` catches multi-driven signals that Verilator misses.
  Never add `--lint-only` to a slang run: it skips elaboration and silently drops inferred-latch
  and multiple-driver diagnostics, so a latch reports as clean. `-Wall` is a Verilator and
  Icarus flag, not a slang one — slang rejects it; use `-Weverything`.
- `sv2v --top <module> <files> > out.v && iverilog -Wall out.v` — useful for catching
  SystemVerilog elaboration issues in tools that don't support SV directly.

## PDK / Tool Quirks

- **SpyGlass CDC vs JasperGold CDC**: SpyGlass CDC reports more false positives on Gray-encoded
  buses; JasperGold CDC gives fewer false positives but misses some structural CDC patterns.
  Use SpyGlass first to get full coverage, then waive false positives with documented rationale.
- **Yosys synth_check with sky130**: `yosys -p "synth -top <top>; check"` on sky130 designs
  requires Surelog for SystemVerilog elaboration — native Yosys SV support is incomplete for
  complex parameter overrides.

## Notes

- RTL sign-off package must include `filelist.f` with relative paths. Absolute paths in filelist
  break downstream synthesis flows that run from a different working directory.
