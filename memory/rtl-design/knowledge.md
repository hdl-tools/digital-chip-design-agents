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
