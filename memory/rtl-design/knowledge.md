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
- **Legal SystemVerilog that sv2v cannot lower breaks synthesis behind a green regression**: A
  part-select on a function-call result (`strb_expand(pstrb)[N-1:0]`) passes Verilator, slang
  and every simulation, but sv2v passes it through verbatim and yosys rejects the output with
  `syntax error, unexpected '['`. Assign the call to a named signal and select from that. Only
  parsing the converted file catches the class — the front-end check in `lint_check`.
- **A module missing from one source list is black-boxed silently**: Simulation, lint,
  synthesis, PD and formal usually read separate lists (often Makefile variables). Adding one
  peripheral took seven list edits in one project; missing the PD list let sv2v black-box the
  module with no error while the simulation regression stayed green. Run
  `check_design_inputs.py --rtl-dir <rtl> --list <name>=<file> ...` after adding a module, and
  never record an unknown first-party module as a stub.

## Successful Tool Flags

- `verilator --lint-only -Wall -Wno-DECLFILENAME <files>` — `-Wno-DECLFILENAME` suppresses the
  common false positive where file name doesn't match module name; keep all other `-Wall` checks.
- `slang -Weverything --ignore-unknown-modules --allow-use-before-declare --strict-driver-checking <files>`
  — full elaboration; `--strict-driver-checking` catches multi-driven signals that Verilator misses.
  Never add `--lint-only` to a slang run: it skips elaboration and silently drops inferred-latch
  and multiple-driver diagnostics, so a latch reports as clean. `-Wall` is a Verilator and
  Icarus flag, not a slang one — slang rejects it; use `-Weverything`.
- `sv2v --top <module> <files> > out.v && yosys -q -p 'read_verilog out.v; hierarchy -check -top <module>'`
  — the front-end check. Required, not optional, wherever a downstream flow reads sv2v output:
  it catches constructs that are legal SystemVerilog but not Verilog-2005, which no SV-native
  lint or simulator sees. Parse with the tool the flow actually uses, not `iverilog`.

## PDK / Tool Quirks

- **SpyGlass CDC vs JasperGold CDC**: SpyGlass CDC reports more false positives on Gray-encoded
  buses; JasperGold CDC gives fewer false positives but misses some structural CDC patterns.
  Use SpyGlass first to get full coverage, then waive false positives with documented rationale.
- **Yosys synth_check with sky130**: native Yosys SystemVerilog support is incomplete for
  complex parameter overrides, so `yosys -p "synth -top <top>; check"` needs an SV front-end.
  Use the one the downstream PD flow uses. If that flow is sv2v-fronted, run synth_check on sv2v
  output: Surelog accepts SystemVerilog the sv2v → yosys path rejects, so a Surelog-fronted
  synth_check passes RTL that breaks PD.

## Notes

- RTL sign-off package must include `filelist.f` with relative paths. Absolute paths in filelist
  break downstream synthesis flows that run from a different working directory.
