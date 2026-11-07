# Physical Design Domain Knowledge

## Known Failure Patterns

- **ORFS density > 65% → routing congestion**: OpenROAD/ORFS placement density above 65% almost
  always correlates with routing congestion (DRC violations in routing stage). Reduce target
  density in `floorplan` to 60–65% before retrying; do not push past 70% without manual congestion
  analysis.
- **CTS target skew for sky130 at 500 MHz**: Use 50 ps target skew for 500 MHz designs in sky130.
  Tighter targets (< 30 ps) are unreachable with OpenROAD CTS and will cause the CTS stage to
  loop indefinitely.
- **Post-route timing closure ECO rounds**: Post-route timing closure typically requires 2–3 ECO
  rounds. If WNS has not converged after 3 rounds, escalate to floorplan revision — incremental
  ECO will not close timing if the root cause is placement congestion.
- **LVS failures from missing substrate tie-offs**: The most common LVS failure in sky130 is
  missing n-well tie-offs and substrate tie-offs for standard cells. Ensure the PDK standard
  cell library includes tie-off cells and that the floorplan inserts them at the required pitch.
- **ICC2 li1 ban ignored (ICC2 X-2025.06-SP1)**: `set_ignored_layers -min_routing_layer met1`
  alone let the router run long li1 wires through SRAM macros, because
  `route.common.global_min_layer_mode` defaults to `soft`. Set it to `hard`.
- **ICC2 met4 spacing to PG straps not enforced**: the `.tf` fat table is present but route and
  `check_routes` do not apply it between a signal wire and a wide strap; KLayout `m4.5ab` finds
  it. Put 0.1 um met4 routing blockages around straps wider than 3 um from the PDN stage on.
- **tt-only hold repair in ICC2 builds weak ZBUF/ZINV delay chains** that then violate
  max-transition; upsizing them destroyed hold. Use ff+tt hold scenarios and restrict hold cells
  to real delay cells (`set_lib_cell_purpose -include hold`). (Seen in the b5 and b6 runs.)
- **Innovus drops I/O clock latency from a new view**: each analysis view keeps its own
  `latency.sdc`, re-applied after the SDC; a view created without `-latency_file` starts empty
  (bogus -1.8 ns hold). Give every view `-latency_file` and re-apply the latency interactively
  after `update_constraint_mode`.
- **Innovus primitives that fail silently (23.14)**: `create_inst` placed nothing (use
  `addInst -physical`); `create_shape` does not exist and `editAddRoute` did nothing (use
  `add_shape`); `attachDiode` drops diodes off-grid (run `refinePlace` before `ecoRoute`).
- **Commercial native antenna checks are lenient on Sky130**: ICC2 under `diode_mode 1` and
  Innovus `verifyProcessAntenna` (no side-area rule) read 0-1 where OpenROAD `check_antennas`
  found hundreds. Drive the diode ECO from the OpenROAD list. (Confirmed across 4 runs.)

## Successful Tool Flags

- `make DESIGN_CONFIG=... finish` (ORFS) — run the full pipeline to completion before reading
  `reports/.../metrics.json`; partial runs leave stale metrics files.
- `klayout -rd input=<gds> -r <drc_script.rb> -zz` — batch DRC mode; `-zz` suppresses GUI and
  is required for CI/CD integration.
- `openroad -no_init` with `read_lef`/`read_def`/`report_checks` TCL sequence — useful for
  one-shot timing queries on a routed design without reloading the full ORFS database.
- `icc2_lm_shell`: one workspace, `read_lef` once, `read_db` tt/ss/ff, `check_workspace
  -allow_missing`, `commit_workspace` — a three-pane NDM; then per corner `set_process_number`,
  `set_voltage`, `set_temperature -corners <c>` in ICC2. Separate per-corner NDMs with shared
  cell names bind every instance to the first library (PVT-030).
- ICC2 export for Netgen LVS: `change_names` with a `-case_insensitive` net rule and
  `write_verilog -exclude supply_statements` (`-include` and `-exclude` cannot be combined).
- Innovus `setOptMode -holdTargetSlack 0.2` with the ff view active: Innovus ff hold read about
  0.17 ns optimistic against PrimeTime on StarRC SPEF.
- RedHawk 2025 R2.2: `INSTANCE_POWER_FILES` (plural; the singular is accepted and ignored),
  escape-free instance names, `ENABLE_AUTO_EM 1`, `perform emcheck -mode AVG|RMS` (PEAK mode vs a
  DC limit is not a pass/fail).

## PDK / Tool Quirks

- **sky130 antenna rules**: sky130 antenna rules are stricter than most commercial PDKs. Enable
  antenna repair (`repair_antennas`) in OpenROAD after routing; expect 5–15% of nets to need
  repair on a typical design.
- **OpenROAD global routing vs detailed routing DRC**: Global routing DRC (overflow) does not
  guarantee detailed routing DRC clean. Always run `detailed_route` and check `drc_count` from
  the metrics file — not the global routing overflow count.
- **Sky130 commercial views**: `lc_shell` segfaults at exit after `read_lib` (the `.db` is
  written; judge from the read-back); `icc2_lm_shell` needs a `.tf` derived from the tech LEF
  (LIB-007) and per-block routing directions (DPUI-924); `generateCapTbl` treats `li1` as POLY,
  so rename it `met0` in a derived ICT before building the Innovus cap table.
- **StarRC on an authored Sky130 ITF matched OpenRCX** only after `COUPLING_ABS_THRESHOLD 0.1`,
  `COUPLING_REL_THRESHOLD 0` and `LEF_USE_OBS NO`; ICC2 DEFs need a supplementary LEF for their
  ContactCode via names or StarRC opens 33k nets (SX-2064).
- **Magic DRC on a Sky130 macro with real SRAM GDS needs ~11 GiB**; run it alone. ~28 M of its
  violations sit inside the SRAM footprints and ~3,000-3,600 `nwell.4` along the SRAM edges are
  the same abstract artefact on every flow; classify by footprint before reading the count.

## Notes

- `core_area_util_pct` above 85% at sign-off is a hard stop — route congestion and ECO closure
  become intractable above this threshold in sky130 with OpenROAD.

_Last distilled: 2026-11-07 from 25 pd experience records of a commercial Sky130 RTL→GDS comparison (ICC2 X-2025.06-SP1, Innovus 23.14, StarRC, RedHawk 2025 R2.2, Magic/KLayout/Netgen; 2026-10-25 → 2026-11-07). Comparison runs, no sign-off by scope; entries are measured results._
