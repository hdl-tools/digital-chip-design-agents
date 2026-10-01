---
name: memory-ip-design
description: >
  Embedded memory IP design — SRAM/register-file/ROM requirements capture, memory
  compiler and macro selection, array architecture (banking, ports, ECC wrapper),
  redundancy and repair allocation, view generation and QA, and integration handoff
  to DFT, PD, and STA. Use when specifying or selecting memory macros, architecting
  a memory subsystem, sizing spare rows/columns for repair, or qualifying a memory
  view set for a chip.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: Memory IP Design (SRAM / Register File / ROM)

## Invocation

When this skill is loaded and a user presents a memory IP design task, **do not
execute stages directly**. Immediately spawn the
`digital-chip-design-agents:memory-ip-orchestrator` agent and pass the full
user request and any available context to it. The orchestrator enforces the stage
sequence, loop-back rules, and sign-off criteria defined below.

Use the domain rules in this file only when the orchestrator reads this skill
mid-flow for stage-specific guidance, or when the user asks a targeted reference
question rather than requesting a full flow execution.

## Pre-run Context

Before executing or advising on **any** stage, read the following files if they exist:

1. `memory/memory-ip/knowledge.md` — known failure patterns, successful tool flags, PDK/tool quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `memory/memory-ip/run_state.md` — current run identity (`run_id`, `design_name`, `tool`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Guide embedded memory IP development from requirements capture through macro
selection, array architecture, repair allocation, and view qualification. Produces
a signed-off memory IP package: an instance inventory, a selected macro per
instance, a QA-clean view set across all PVT corners, a repair architecture, and
placement/timing constraints for downstream handoff.

### Scope boundary — what this domain does NOT do
This domain treats the memory as the *product*. It stops at the handoff and does
not duplicate work owned elsewhere:

| Not owned here | Owner |
|---|---|
| MBIST controller insertion, March pattern generation, MBIST fault coverage, ATPG | `chip-design-dft` (`bist_insertion` stage) |
| Floorplanning, actual macro placement, power grid over macros | `chip-design-pd` (`floorplan` stage) |
| Timing sign-off, multi-corner STA runs, ECO closure | `chip-design-sta` |
| Address/memory map assignment, bus fabric attachment | `chip-design-soc` |
| Cache hierarchy and DDR controller architecture | `chip-design-architecture` |

This domain **produces the inputs** those domains consume: memory inventory and
repair-register map for DFT, placement constraints for PD, `.lib` set and derates
for STA, behavioural models for verification.

---

## Supported EDA Tools

### Open-Source
- **OpenRAM** (`openram`) — open-source memory compiler; generates GDS, LEF, Liberty, and Verilog for SRAM
- **CACTI** (`cacti`) — early access-time, area, and power estimation before a compiler run
- **sky130 / gf180mcu SRAM macros** — PDK-provided pre-hardened macro sets with fixed configurations
- **Magic** (`magic`) — DRC and LVS on generated macro layout
- **KLayout** (`klayout`) — GDS QA, layer/obstruction inspection, boundary checks
- **OpenSTA** (`sta`) — `.lib` load sanity check and macro timing arc inspection

### Proprietary
- **ARM Artisan memory compilers** (`artisan`) — production SRAM/register-file/ROM compilers
- **Synopsys memory compilers + SiliconSmart** (`siliconsmart`) — compilation and Liberty characterisation
- **Cadence Liberate** (`liberate`) — Liberty characterisation across PVT corners
- **Siemens Tessent MBIST/BISR** (`tessent`) — repair-register and BISR architecture reference (insertion owned by DFT)

---

## Stage: memory_requirements

### Domain Rules
1. Capture depth × width × port count for every memory instance in the design; source from `design_state.architecture` and `design_state.rtl` where available
2. Establish memory type and port requirements by this precedence, and record which source supplied each instance:
   1. **`design_state.rtl`** — the implementation is authoritative for port count, widths, and depth, because that is what must actually be instantiated
   2. **`design_state.architecture`** — authoritative for type intent and sizing where RTL is silent (typically pre-RTL runs)
   3. **Inference** — only when both are silent. Infer from the whole picture, not depth alone: port count and concurrency (multi-port and bypass-heavy structures are register files regardless of depth), access-latency budget, and what the target PDK actually offers. Depth is a weak tiebreaker (~256 words) that misclassifies both shallow SRAMs and deep register files, so record any inferred type as an assumption to confirm, not a fact

   **On conflict, do not silently pick a winner.** If `rtl` and `architecture` disagree on type, port arrangement, depth, or width for the same instance, halt with a `constraint_gap` escalation naming the instance and both values. A mismatch here selects the wrong macro interface and is not recoverable after `view_generation`
3. Compute required read/write bandwidth per instance and check it against the target `constraints.clock.clk_mhz` — bandwidth shortfalls must be resolved here, not by over-selecting macros later
4. Decide the ECC scheme per instance with this deterministic policy, so two runs on the same inputs resolve identically. Compute `budgeted_FIT = fit_target_fit_per_mb × instance_Mb` (`constraints.memory_ip.fit_target_fit_per_mb`, default 100) and `raw_FIT` from the PDK's SER rate for the chosen bitcell:

   | Condition | Resolved scheme |
   |---|---|
   | `ecc_required: true` | **SECDED** — the forced floor is correction, not merely "a scheme". Parity only if the spec explicitly permits detect-only, recorded with rationale |
   | `raw_FIT ≤ budgeted_FIT` | `none` |
   | `raw_FIT > budgeted_FIT`, detect-and-retry available at system level | `parity` |
   | `raw_FIT > budgeted_FIT`, no system-level retry | **SECDED** |
   | `raw_FIT > budgeted_FIT` even with SECDED + scrubbing | escalate — ECC alone cannot meet the budget; revisit bitcell or partitioning |

   Record `raw_FIT`, `budgeted_FIT`, the PDK SER source, and the resolved scheme per instance into `memory_ip.ecc`. An unaudited ECC choice is not reproducible on a re-spin
5. Enumerate required power modes per instance — active, light sleep (periphery off, array retained), deep sleep (retained at reduced voltage), shutdown (contents lost) — and resolve retention with an explicit precedence: **a per-instance retention requirement from the spec/architecture always wins**; `constraints.memory_ip.retention_required` is the *default* applied only to instances that state nothing. The global flag never overrides an explicit per-instance value in either direction — forcing retention onto an instance declared non-retained over-constrains macro selection and costs area, while dropping it from one declared retained is a functional bug. Where the global is `true` and an instance is explicitly non-retained, record the resolved value and the rationale rather than silently reconciling. Write the resolved per-instance value into `memory_ip.power_modes`
6. Record the dual-rail requirement: whether array and periphery supplies are separate, since this constrains both the macro choice and the UPF power intent
7. Flag any instance needing multi-port behaviour and whether it can be met by banking instead of a true multi-port bitcell (much larger)

### QoR Metrics to Evaluate
- Total memory bit count and instance count
- Aggregate bandwidth required (GB/s) vs. available at target frequency
- Fraction of total die area budget provisionally allocated to memory

### Output Required
- Memory instance inventory (name, type, depth, width, ports, retention requirement)
- Bandwidth and ECC decision table with rationale
- Power-mode requirement per instance

---

## Stage: macro_selection

### Domain Rules
1. Confirm compiler family and macro availability in the target PDK before evaluating options; a configuration the compiler cannot generate is not a candidate
2. Column mux factor (4/8/16) trades aspect ratio against access time: higher mux gives a squarer, shorter macro but a longer bitline-to-sense path. Sweep it rather than accepting the default
3. Evaluate bank count against single-array access time — splitting a deep array into banks shortens bitlines and improves access time at the cost of periphery area duplication
4. Compare every candidate on access-time margin at the **slow corner** (not typical), area, and leakage. A candidate with no slow-corner margin is a fail regardless of typical-corner numbers
5. Prefer fewer, larger instances to amortise periphery (decoders, sense amps, control) overhead — bounded by `constraints.memory_ip.max_aspect_ratio` (default 4.0), beyond which placement and routing become impractical
6. Verify the bitcell type against the Vmin requirement: 6T is denser, 8T gives better read stability and lower Vmin for low-voltage or dual-rail operation
7. Record why each rejected candidate lost — this is the single most reusable artefact for later re-spins and belongs in `knowledge.md`

### QoR Metrics to Evaluate
- Access-time margin at slow corner (ns) per instance — must be > 0
- Area per instance and total (µm²)
- Leakage (µW) and active power (mW) per instance
- Aspect ratio per instance vs. `constraints.memory_ip.max_aspect_ratio`

### Output Required
- Selected macro/compiler configuration per instance
- Candidate comparison table with the rejection rationale for each loser
- Slow-corner access-time margin report

---

## Stage: array_architecture

### Domain Rules
1. Choose banking for bandwidth before reaching for a true multi-port bitcell — independent banks with address interleaving serve most concurrent-access needs at far lower area cost
2. Fix the port arrangement per instance (1RW, 1R1W, 2RW) and define the write-during-read collision policy explicitly: read-old-data, read-new-data, or X/undefined. This policy must match the behavioural model written in `view_generation`
3. Define wrapper responsibilities: byte-enable decode, output pipelining/registering, and clock gating of the macro enable. Keep the wrapper thin — logic that belongs in the consuming RTL should not migrate into the memory wrapper
4. Place the ECC wrapper on the correct side of the pipeline boundary and account for its latency: SECDED check-bit count is the smallest `c` satisfying `2^c ≥ data_bits + c + 1` (8 data bits → 5, 32 → 7, 64 → 8). Record encode and decode latency separately — decode is on the critical read path
5. Define the scrubbing policy where ECC is used: background scrub interval must be short enough that the probability of a second bit flip accumulating in one word stays below the FIT-rate target
6. Determine Vmin and assist-circuit requirements per bitcell type — read assist (wordline underdrive, negative bitline) and write assist (boosted wordline, collapsed cell supply) are what make low-Vmin operation viable, and they cost area and complexity
7. Verify the resulting architecture still meets the bandwidth figure computed at `memory_requirements`; loop back rather than compensating downstream
8. Where the wrapper is delivered as RTL rather than only specified (byte-enable decode, pipelining, ECC encode/decode), it is synthesisable RTL: it follows the rtl-design skill's coding rules and must pass lint with 0 errors. The macro it instantiates is a stub in that lint run — undriven-net findings on the macro's outputs are not wrapper bugs

### QoR Metrics to Evaluate
- Bandwidth achieved (GB/s) vs. target
- Total memory area (µm²) vs. budget — fail above 120%
- ECC decode latency added to the read path (ns or cycles)
- Vmin margin (mV) vs. `constraints.memory_ip.vmin_margin_mv` (default 50)

### Output Required
- Bank/port architecture diagram per instance
- Wrapper specification (byte enable, pipelining, clock gating, collision policy)
- ECC scheme with data/check bit widths, latency, and scrubbing policy

---

## Stage: redundancy_repair

### Domain Rules
1. Size spare rows and columns from defect density × array bit count — not from a fixed rule of thumb. A small array may need no redundancy at all; provisioning it wastes area and repair-register bits
2. Choose the repair scheme against the projected-yield target: column-only repair addresses bitline and sense-amp defects, row-only addresses wordline and decoder defects, both is needed when either class dominates
3. Size the repair register: bits ≈ (spare rows × log2(rows)) + (spare cols × log2(cols)) per repairable unit, plus enable bits. This width is a hard handoff number for DFT's BISR chain
4. Decide soft repair (BISR reloads the repair map at every power-on) vs. hard repair (efuse/OTP blown once at test). Soft repair needs a non-volatile source and boot-time sequencing; hard repair needs an efuse programming path and is irreversible
5. Build the efuse/OTP map with the address allocation per instance; leave documented spare capacity for post-silicon re-repair
6. **ECC and redundancy are not substitutes.** Redundancy replaces hard, permanent defects found at test; ECC corrects soft, transient errors in the field. A design needing both must have both — do not trade one for the other in the yield calculation
7. Recompute projected post-repair yield and compare against `constraints.memory_ip.repair_yield_pct_min` (default 99). Loop back to `array_architecture` if the target is unreachable — more spare elements cannot fix an array that is simply too large for the defect density

### QoR Metrics to Evaluate
- Projected post-repair yield (%) vs. `constraints.memory_ip.repair_yield_pct_min`
- Spare row/column count and the area overhead they add (%)
- Repair-register width (bits) — handoff figure for DFT
- Efuse/OTP bits consumed vs. available

### Output Required
- Repair scheme per instance (row/column/both/none) with spare counts
- Repair-register map and bit-width
- Efuse/OTP address allocation
- Projected yield calculation showing defect-density assumptions

---

## Stage: view_generation

### Domain Rules
1. Generate the full required view set per instance: `.lib` (every PVT corner in `constraints.pvt_corners`), `.lef`, `.db`, `.v` behavioural model, `.gds`, and `.cdl` netlist. A missing view blocks a downstream domain, so treat any gap as a hard fail
2. QA pin-name consistency across `.lib`, `.lef`, and `.v` — a mismatch here is the single most common cause of late integration failures and is silent until PD or LEC runs
3. Verify every port has complete timing arcs in the `.lib`: setup/hold on all inputs, clock-to-Q on all outputs. Missing arcs cause STA to under-report violations rather than error out
4. Check corner count matches the required PVT list exactly; a `.lib` set characterised at only typical is not sign-off usable
5. Verify `.lef` obstruction layers are complete — missing obstructions let the router place wires over the array and produce DRC or noise failures found only at PD
6. Confirm the behavioural model matches the timing model: it must enforce the same setup/hold via timing checks and must propagate X on the write-during-read collision policy fixed at `array_architecture`. A permissive behavioural model hides bugs until silicon. The behavioural model is simulation-only: `initial` blocks, `#delay` and timing checks are correct in it, and the RTL synthesis-safety rules and lint gate do not apply to it
7. Run macro-level DRC/LVS on the generated layout where the flow produces layout (OpenRAM, custom); skip for vendor pre-hardened macros where these are pre-signed-off

### QoR Metrics to Evaluate
- View QA error count — must be 0 for sign-off
- Corners characterised vs. corners required
- Macro DRC/LVS violation count (where layout is generated)
- Pin-consistency mismatches across `.lib`/`.lef`/`.v`

### Output Required
- Complete view set per instance, with file paths
- View QA report enumerating every check and its result
- DRC/LVS report where layout was generated

---

## Stage: integration_prep

### Domain Rules
1. Emit placement constraints for PD, do not place: orientation so that pins face the intended routing channel, halo width, inter-bank channel width sized for the expected wire count, and bank grouping so related instances stay together
2. Emit the memory instance inventory and repair-register map for DFT's `bist_insertion` — group instances by width/depth class, since DFT allocates one MBIST controller per group
3. Confirm BIST ports are exposed on every instance wrapper and reachable; DFT owns connecting them, this domain owns their existence
4. Emit the `.lib` set and any memory-specific timing derates for STA; note explicitly where derates differ from standard-cell derates
5. Emit the behavioural model path for verification, together with the collision policy so the testbench can predict X-propagation correctly
6. Confirm `set_dont_touch` is applied to every memory macro for synthesis, and that macros are excluded from scan insertion
7. Cross-check the memory map assignment from `chip-design-soc` against the actual instance depths — a mismatch between the architectural map and the delivered macro sizes must be caught here, not at chip assembly

### QoR Metrics to Evaluate
- Instances with complete placement constraints vs. total
- Instances with exposed and reachable BIST ports vs. total
- Memory-map conflicts detected (must be 0)

### Output Required
- Placement constraint file for PD
- Memory inventory + repair-register map for DFT
- `.lib` set and derate notes for STA
- Behavioural model paths and collision policy for verification

---

## Stage: memory_signoff

### Sign-off Checklist
- [ ] Every instance in the inventory has a selected macro with positive slow-corner access-time margin
- [ ] Total memory area within budget
- [ ] Bandwidth target met at `constraints.clock.clk_mhz`
- [ ] ECC scheme implemented where required, with latency accounted for on the read path
- [ ] Vmin margin meets `constraints.memory_ip.vmin_margin_mv`
- [ ] Redundancy allocated and projected yield ≥ `constraints.memory_ip.repair_yield_pct_min`
- [ ] Repair-register map complete and handed to DFT
- [ ] View set complete for every instance, all corners, view QA errors = 0
- [ ] Behavioural model collision policy matches the timing model
- [ ] Placement constraints emitted for PD
- [ ] BIST ports exposed on every instance
- [ ] `set_dont_touch` confirmed for synthesis

### Output Required
- Signed-off memory IP package (inventory, macros, views, repair architecture, constraints)
- Sign-off report with every checklist item and its evidence
- `design_state.json` `memory_ip` block populated with `signoff: true`

---

## Constraint Validation

See `plugins/meta/skills/pipeline-orchestration/SKILL.md` §Constraints Schema for the authoritative schema and stage-entry validation rule.

**Required at entry (`memory_requirements`) — hard-fail if missing:**
- `constraints.clock.clk_mhz` — target frequency, sets the access-time budget for macro selection

**Optional (schema defaults apply when absent):**
- `constraints.memory_ip.vmin_margin_mv` (default: 50) — minimum Vmin margin
- `constraints.memory_ip.repair_yield_pct_min` (default: 99) — projected post-repair yield floor
- `constraints.memory_ip.ecc_required` (default: false) — when `true`, forces **SECDED** as the floor regardless of the FIT calculation (see the `memory_requirements` ECC policy table)
- `constraints.memory_ip.fit_target_fit_per_mb` (default: 100) — soft-error budget in FIT per Mb; the audited input to the ECC decision at `memory_requirements`
- `constraints.memory_ip.max_aspect_ratio` (default: 4.0) — macro aspect-ratio ceiling
- `constraints.memory_ip.retention_required` (default: true) — the **default** applied only to instances with no explicit per-instance retention requirement; an explicit per-instance value always wins in both directions. When the constraint is absent the default is assumed and must be stated in the stage `reason`
- `constraints.pvt_corners` — corner list that `view_generation` must fully characterise. **Not defaultable:** if absent, or if no entry has non-null `voltage_v` and `temp_c`, escalate as a `constraint_gap` at `view_generation` entry rather than characterising at typical only
- `constraints.dft.mbist_coverage_pct` — **owned by `chip-design-dft`**; read only, never redefined here

---

## Memory

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
write or overwrite one JSON record in `memory/memory-ip/experiences.jsonl` keyed by
`run_id`. This ensures data is persisted even if the flow is interrupted or called
without full orchestrator context.

Use `run_id` = `memory-ip_<YYYYMMDD>_<HHMMSS>` (set once at flow start; reuse on each
stage update). Set `signoff_achieved: false` until the final sign-off stage completes.

### Run state (write before first stage, update after each stage)
Write `memory/memory-ip/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:      memory-ip_<YYYYMMDD>_<HHMMSS>
design_name: <design>
tool:        <primary tool>
start_time:  <ISO-8601>
last_stage:  null
```
Update `last_stage` to the completed stage name only after each stage finishes successfully. This file lets wakeup-loop prompts
and resumed sessions identify the correct run without relying on in-memory state.
Create the file and parent directories if they do not exist.

### Optional: claude-mem index
If `mcp__plugin_ecc_memory__add_observations` is available in this session, emit each
applied fix as an observation to entity `chip-design-memory-ip-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.
