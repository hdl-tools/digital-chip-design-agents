# Synthesis Domain Knowledge

## Known Failure Patterns

- **Yosys -flatten required for hierarchical sky130 designs**: Yosys synthesis of hierarchical
  designs targeting sky130 PDK requires `-flatten` in the `synth` pass. Without flattening,
  technology mapping fails to optimize across hierarchy boundaries, producing ~15–20% area
  overhead vs. flattened synthesis. Use `synth -top <top> -flatten` for sky130 targets.
- **An area target alone does not close WNS**: an area constraint (`set_max_area 0`) does not
  drive timing closure. Apply the timing constraints (`create_clock`, `set_input_delay`,
  `set_output_delay`) before optimisation — before `compile_ultra` in Design Compiler, before
  `syn_generic`/`syn_map`/`syn_opt` in Genus, before `compile_fusion` in Fusion Compiler — so
  area recovery runs inside the timing budget. (Corrected: this entry attributed
  `compile_ultra` to Genus; it is a Design Compiler command.)
- **Scan chain false paths before compile**: scan chain false paths must be declared in the SDC
  (`set_false_path -from [get_ports scan_in] -to [get_ports scan_out]`) before the compile —
  `compile_ultra` in Design Compiler, `compile_fusion` in Fusion Compiler. Declaring them after
  lets the tool re-optimise scan paths, breaking chain continuity and requiring an LEC re-run.
  (Corrected: this entry tied `compile_ultra` to Fusion Compiler, whose compile is
  `compile_fusion`.)

## Successful Tool Flags

- `yosys -p "synth -top <top> -flatten; dfflibmap -liberty <lib.lib>; abc -liberty <lib.lib> -D <period_ps>"` —
  complete Yosys synthesis command for sky130; `-D <period_ps>` sets the timing target for ABC
  delay optimization.
- `dc_shell -f <script.tcl> -output_log_file <log>` — always capture the log; `check_design`
  warnings about unresolved references are the most common root cause of synthesis failures.
- `genus -legacy_ui -files <script.tcl>` — `-legacy_ui` mode is more stable for scripted flows
  than the default UI mode; avoids interactive prompts that hang batch jobs.

## PDK / Tool Quirks

- **`ultra` effort past 2× loop-backs** (Design Compiler): `compile_ultra` with `ultra` effort rarely closes WNS
  past 2 loop-back iterations — further effort yields < 1% improvement at 3–5× runtime cost.
  Switch to targeted path optimization (`compile_ultra -only_design_rule` + `optimize_registers`)
  after 2 failed `compile_ultra` runs.
- **ABC liberty compatibility**: ABC requires liberty files without `pg_pin` (power/ground pin)
  entries. Strip `pg_pin` blocks from sky130 liberty with `sed '/pg_pin/,/^  }/d'` before passing
  to Yosys/ABC — `pg_pin` entries cause ABC to silently ignore the cell.

## Notes

- LEC must be run after every netlist change — not just at signoff. A single unverified netlist
  change that reaches PD and fails LEC there costs a full PD re-run.
