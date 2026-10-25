# Formal Verification Domain Knowledge

## Known Failure Patterns

- **Vacuous proofs from over-constrained environment**: A vacuous proof means the `assume`
  constraints in `environment_setup` make the input space unreachable. Check it after every
  environment iteration with `cover` properties on each assertion's antecedent, run as an
  sby task in `mode cover` (sby has no `--vacuity` command-line flag). If vacuity is detected, relax constraints
  one at a time — do not remove all constraints and re-add, as this loses context.
- **Insufficient bound depth**: the SymbiYosys bound (`depth N` under `[options]` in the `.sby`
  file, not a command-line flag) must be at least `pipeline_depth + 2`
  to exercise all pipeline stages. Shallow bounds produce false "PASS" results for properties that
  only fire at the end of a pipeline.
- **LEC failures after synthesis**: LEC unmatched points after synthesis almost always indicate
  clock-gating cells that need equivalence mapping (`set_dont_touch` or explicit mapping script).
  Provide the synthesis tool's clock-gating cell list to the LEC tool before running.

## Successful Tool Flags

- `sby -f <task>.sby` (`-f` overwrites an existing work directory) with `depth <N>` set
  explicitly under `[options]` in the `.sby` file; never rely on the default bound.
- `multiclock on` under `[options]` in the `.sby` file — required when the design has multiple
  clocks or asynchronous logic; without it the clocks are treated as one global clock.
  (Earlier text here gave `--depth`, `--vacuity` and `--multiclock` as sby command-line flags;
  they are not — depth and multiclock are `.sby` options, and vacuity is checked with cover.)
- An earlier entry recommended `jg -allow_empty_cex`. Removed: the string occurs nowhere in the
  JasperGold 2024.12 console binary (`jg_console`, which does contain the real
  `-allow_unsupported_OS` flag) or its HTML help, so it is not a JasperGold option. Check
  vacuity with cover properties instead.

## PDK / Tool Quirks

- **Z3 vs Boolector for bitvector arithmetic**: Z3 is generally faster for designs with heavy
  arithmetic; Boolector outperforms Z3 on pure Boolean problems. Try both when a proof runs
  for > 30 minutes without result.
- **Yosys `prep` before sby**: Running `yosys -p "prep -top <top>"` on the design before
  invoking SymbiYosys catches synthesis elaboration errors early and significantly reduces
  proof setup time.

## LEC (Formality / Conformal)

- A clean `Verification SUCCEEDED` (Formality) or an all-Equivalent compare (Conformal) counts
  only once the same script has reported a deliberately mutated netlist non-equivalent; a
  black-boxed or unlinked module makes the verdict vacuous for everything inside it.
- `INCONCLUSIVE` (Formality) and `Abort` points (Conformal) are unproven, not equivalent.

## Notes

- CEX found for a P0 property = hard blocker. Suspend the formal flow, report to the RTL
  team with the full counterexample trace, and do not retry until RTL fix is confirmed.
