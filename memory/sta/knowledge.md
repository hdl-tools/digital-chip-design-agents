# STA Domain Knowledge

## Known Failure Patterns

- **OpenSTA hold analysis without set_propagated_clock**: OpenSTA `set_propagated_clock` is
  required before hold analysis. Without it, OpenSTA uses ideal clock (zero skew) for hold
  checks, which produces false "clean hold" results that fail on silicon. Always call
  `set_propagated_clock [all_clocks]` in the STA script before `report_checks -path_delay min`.
- **Multi-corner hold closure needs target library hold_margin**: Multi-corner hold closure in
  sky130 usually requires setting a `hold_margin` in the target liberty file. The default
  hold_margin of 0 ps is insufficient for signoff at slow-slow corner with RCMAX parasitics —
  add 50–100 ps margin.
- **ECO cells > 2% → upstream issue**: If ECO cell count exceeds 2% of total cells during
  `eco_guidance`, this almost always indicates a floorplan or CTS issue upstream — not a timing
  exception problem. Escalate to the physical design team rather than continuing ECO iteration.
- **rcx extraction accuracy for hold at 28nm and below**: RCX extraction accuracy significantly
  affects hold timing at 28nm and below. OpenROAD's built-in RC estimator (`estimate_parasitics`)
  is not accurate enough for hold signoff — use SPEF from a dedicated extraction tool (Calibre xRC,
  StarRC, or OpenRCX with calibrated rules).
- **PrimeTime `read_sdc` silently drops everything after the first unsupported command**
  (X-2025.06): an Innovus-exported SDC (`current_design` line, `get_designs`) gave plausible but
  invalid slack. Fix the syntax, diff the result, and accept a run only with non-empty setup and
  hold WNS. (Seen in 2 records.)
- **A tool-written SDC is a different constraint set**: ICC2 added `set_clock_latency` "for io
  paths", Innovus keeps I/O latency in per-view `latency.sdc`; native-vs-judge hold gaps of 1.2-2.9
  ns came from that, not from the layouts. Rank flows on one shared SDC and record every md5.
- **tt-only implementation loses 7.8-14.7 ns at ss** in a 9-corner judge, almost all reg-to-reg;
  the same tools with ss/tt setup and ff/tt hold views lost none. (Confirmed on DC→ICC2 and
  Genus→Innovus.)

## Successful Tool Flags

- `sta -exit <script.tcl>` — `-exit` ensures OpenSTA exits cleanly with a return code; required
  for CI/CD integration where a hung process would block the pipeline.
- `report_timing -path_type full_clock_expanded -delay_type max -nworst 10` — `full_clock_expanded`
  shows full clock network paths; essential for diagnosing clock skew contributions to WNS.
- `report_slack_histogram -num_bins 20` — quick overview of slack distribution; use before
  detailed path analysis to understand whether violations are widespread or concentrated.
- PrimeTime judge per (library corner, RC corner): `link_path {* <corner>.db <macro>.db}`,
  md5-asserted `read_sdc`, `read_parasitics -format spef`, then `report_annotated_parasitics -check
  ... -pin_to_pin_nets` gated on the pin-to-pin row and on clock nets; SPEF and netlist md5 per
  run. This made 27-run sweeps per flow trustworthy.
- `set_app_var report_default_significant_digits 4` — the default 2 hid a -0.0046 ns slack.
- PrimePower vectorless `power_default_toggle_rate 0.1` plus `set_switching_activity -toggle_rate
  0.1 -static_probability 0.5 [all_registers -output_pins]` matched OpenSTA's register-output
  assumption within 2-3 % (PT's default differs 15 %).

## PDK / Tool Quirks

- **PrimeTime POCV vs AOCV**: PrimeTime POCV (parametric OCV) is more accurate than AOCV for
  advanced nodes but requires POCV coefficient files from the PDK vendor. Using AOCV on a design
  that has POCV coefficients available leaves pessimism on the table.
- **Tempus multi-mode multi-corner**: Tempus MMMC setup requires a `constraint_mode` and
  `delay_corner` for every combination — missing combinations produce incorrect "all clear" reports
  for unconstrained paths.

## Notes

- STA signoff requires `setup_wns_ns >= 0` AND `setup_tns_ps == 0` AND `hold_wns_ps >= 0`
  AND `hold_tns_ps == 0` at ALL corners. A single failing corner blocks tape-out.

_Last distilled: 2026-11-07 from 9 sta experience records (PrimeTime/PrimePower X-2025.06 judge of three Sky130 flows, 2026-10-26 → 2026-11-07). Comparison runs, no sign-off by scope._
