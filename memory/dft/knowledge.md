# DFT Domain Knowledge

## Known Failure Patterns

- **Scan DRC errors from clock gating cells**: The most common source of scan DRC errors is clock
  gating cells without test control logic. Add test-enable (`TE`) ports to all ICG cells and verify
  they connect to the scan enable network before running `scan_insertion`.
- **ATPG coverage below 95%**: Coverage below 95% after full ATPG is almost always caused by
  unpowered logic domains or missing tie-offs on unused inputs. Audit power domain boundaries and
  ensure all unused inputs are tied high or low before retrying ATPG.
- **BIST MISR false-pass**: MISR polynomial selection directly affects the probability of a
  false-pass (aliasing). Use a primitive polynomial of degree equal to the MISR register width.
  Default TetraMAX/Modus MISR polynomials are safe; custom implementations must be verified.

## Successful Tool Flags

- `tmax -scan_chain_length <N>` — setting explicit chain length prevents TetraMAX from creating
  excessively long chains that degrade test application time.
- `modus -coverage_model full_fault` — enables both SAF and TDF coverage tracking in a single run;
  avoids a separate TDF run later in the flow.
- `tessent -shell -dofile <script.do>` — batch mode avoids GUI overhead; use with structured dofiles
  for repeatable flows.

## PDK / Tool Quirks

- **OpenROAD DFT**: `openroad -dft` scan insertion is functional for simple designs but does not
  support hierarchical scan chain stitching across IP boundaries — use Yosys DFT plugin or
  proprietary tools for SoC-level scan.
- **Yosys `synth -flatten` interaction**: Flattening before scan insertion eliminates hierarchy
  boundaries that block chain stitching, but significantly increases runtime on large designs.
  Flatten selectively at the scan boundary level.

- **Tessent 2025.4 (measured)**: the legacy `add_scan_groups` / `add_scan_chains` path ran clean
  and inserted nothing; use the context flow in the dft skill's Tool Notes. `tessent -shell`
  hangs on stdin after an aborted dofile unless run with `< /dev/null`; without `-replace` the
  previous log survives and looks like a result. `add_processors -number` is rejected.
- **Tessent cell library for sky130_fd_sc_hd**: Liberty alone gives no cell behaviour. Generate
  Verilog models (gate primitives, not bare `assign`), compile with LibComp, and curate the
  `dft_cell_selection`: the auto-generated one picked `lpflow_*` cells.
- **Tessent MemoryBIST**: generated patterns default to `reduced_address_count` on; turn it off
  for fault-injection proofs. The controller tests each logical port in its own pass, so its
  cycle count for a 1RW1R macro is not comparable to a single-pass in-house March count.

## Notes

- JTAG boundary scan connectivity (`jtag_setup`) should be validated with a BSDL file checker
  before silicon — BSDL syntax errors cause test equipment to reject the device at incoming
  inspection.
