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
- **tt-only compile with area recovery builds a slow adder (DC-NXT X-2025.06-SP3)**: with only
  the tt corner and the SDC's `set_max_area 0`, DC met 0 ps at tt with a ~30-cell `fa_1`
  ripple-carry adder and was -10.5 ns at ss zero-wire. Re-synthesise with MCMM scenarios (setup
  ss+tt, hold ff+tt, per-scenario TLU+, `set_fix_hold` in the hold scenarios): +1.16 ns at ss for
  +10 % area. Genus 23.14 on the same RTL was +0.6 ns at ss tt-only, so check each netlist at ss
  with a zero-wire PrimeTime probe before re-running.
- **Genus iSpatial without a QRC tech file**: `syn_opt -spatial` fails with PHYS-1015 when no
  `qrcTechFile` exists; run plain physical-aware `syn_opt` and record it. Genus ignores the SDC's
  `set_max_area 0` (SDC-200) where DC honours it.

## Successful Tool Flags

- `yosys -p "synth -top <top> -flatten; dfflibmap -liberty <lib.lib>; abc -liberty <lib.lib> -D <period_ps>"` —
  complete Yosys synthesis command for sky130; `-D <period_ps>` sets the timing target for ABC
  delay optimization.
- `dc_shell -f <script.tcl> -output_log_file <log>` — always capture the log; `check_design`
  warnings about unresolved references are the most common root cause of synthesis failures.
- `genus -legacy_ui -files <script.tcl>` — `-legacy_ui` mode is more stable for scripted flows
  than the default UI mode; avoids interactive prompts that hang batch jobs.
- `dcnxt_shell -topographical_mode -f <script.tcl>` — NDM topographical synthesis (DC-NXT
  X-2025.06-SP3). Plain `dc_shell -topographical_mode` is the Milkyway flow and has no
  `create_lib` (CMD-005). The `dc_shell -f` entry above stays right for wire-load/Milkyway runs.
- `set_svf <file>` before `analyze`, `set_svf -off` at the end — Formality needs DC's SVF; without
  it 143 constant/merged registers stayed unmatched.
- `set_tlu_plus_files -max_tluplus -min_tluplus -tech2itf_map` + `check_tlu_plus_files`, set
  before `extract_physical_constraints` (else PSYN-100); `read_parasitic_tech` does not exist in
  `dcnxt_shell`.
- `genus -no_gui -overwrite -f <script.tcl>` with `read_mmmc`, `read_physical -lef`,
  `syn_generic -physical`, `syn_map -physical`, `syn_opt` (Genus 23.14-s090_1, default UI). The
  `-legacy_ui` entry above was not exercised by these runs.

## PDK / Tool Quirks

- **`ultra` effort past 2× loop-backs** (Design Compiler): `compile_ultra` with `ultra` effort rarely closes WNS
  past 2 loop-back iterations — further effort yields < 1% improvement at 3–5× runtime cost.
  Switch to targeted path optimization (`compile_ultra -only_design_rule` + `optimize_registers`)
  after 2 failed `compile_ultra` runs.
- **ABC liberty compatibility**: ABC requires liberty files without `pg_pin` (power/ground pin)
  entries. Strip `pg_pin` blocks from sky130 liberty with `sed '/pg_pin/,/^  }/d'` before passing
  to Yosys/ABC — `pg_pin` entries cause ABC to silently ignore the cell.
- **One MMMC file for Genus and Innovus must branch**: Genus 23.14 delay corners need
  `create_timing_condition` + `-timing_condition`; Innovus 23.1x rejects that form (TCLCMD-992).
- **`set_dont_use */<cell>` is rejected by DC/ICC2** (UID-109): use
  `set_dont_use [get_lib_cells */<cell>]`; Genus uses `set_db [get_db base_cells <c>] .dont_use true`.

## Notes

- LEC must be run after every netlist change — not just at signoff. A single unverified netlist
  change that reaches PD and fails LEC there costs a full PD re-run.

_Last distilled: 2026-11-07 from 3 synthesis experience records (commercial Sky130 comparison runs, 2026-10-25 → 2026-11-01). They are comparison runs (no sign-off by scope); each entry is a measured result, not a recommendation from a single unverified run._
