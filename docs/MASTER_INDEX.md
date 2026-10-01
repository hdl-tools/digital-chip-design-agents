# Digital Design & Software Pipeline — Master Index
## Complete Agent + Skill Architecture for Chip Design

> **Purpose**: This document is the master index for the full digital design pipeline. It maps every flow document to its position in the end-to-end chip design process and defines how orchestrators hand off to each other across the complete design journey from specification to tape-out and firmware.

---

## Full Pipeline Overview

```
                     ┌─────────────────────────────────────────────────────┐
                     │          0. INFRASTRUCTURE SETUP                    │
                     │  Tool detection, wrappers, MCP config               │
                     └────────────────────┬────────────────────────────────┘
                                          │
                     ┌────────────────────▼────────────────────────────────┐
                     │             PRODUCT SPECIFICATION                   │
                     └────────────────────┬────────────────────────────────┘
                                          │
                     ┌────────────────────▼────────────────────────────────┐
                     │  1. ARCHITECTURE EVALUATION                         │
                     │     Microarch doc, PPA estimates, risk register      │
                     └────────────────────┬────────────────────────────────┘
                                          │
               ┌──────────────────────────┼──────────────────────────┐
               ▼                          ▼                          ▼
    ┌──────────────────┐      ┌───────────────────┐      ┌──────────────────────┐
    │ 2. RTL DESIGN    │      │ 3. HLS FLOW        │      │ 14. FPGA EMULATION   │
    │ SV coding, lint, │      │ C/C++ → RTL        │      │ Early SW bring-up    │
    │ CDC, synth check │      │ (for algo blocks)  │      │ (runs in parallel)   │
    └────────┬─────────┘      └─────────┬──────────┘      └──────────────────────┘
             │                          │
             └──────────────────────────┘
                                        │ RTL package
               ┌────────────────────────┼────────────────────────────────┐
               ▼                        ▼                                ▼
    ┌──────────────────┐   ┌────────────────────────┐   ┌───────────────────────┐
    │ 4. FUNCTIONAL    │   │ 5. FORMAL VERIFICATION  │   │ 10. SoC IP INTEGRATION│
    │ VERIFICATION     │   │ FPV + LEC              │   │ (if SoC-level work)   │
    │ UVM, coverage,   │   │                        │   │                       │
    │ regression       │   │                        │   │                       │
    └──────────────────┘   └────────────────────────┘   └───────────────────────┘
                                                        ┌───────────────────────┐
                                                        │ 11. MEMORY IP DESIGN  │
                                                        │ Macros, banking, ECC, │
                                                        │ repair, view QA       │
                                                        │ → DFT / PD / STA      │
                                                        └───────────────────────┘
                                        │ Verified RTL
                     ┌──────────────────▼──────────────────────────────────┐
                     │  6. LOGIC SYNTHESIS                                  │
                     │     SDC, gate netlist, LEC                          │
                     └────────────────────┬────────────────────────────────┘
                                          │ Gate netlist
               ┌──────────────────────────┼──────────────────────────┐
               ▼                          ▼                          ▼
    ┌──────────────────┐      ┌───────────────────┐      ┌──────────────────┐
    │ 7. DFT FLOW      │      │ 8. PHYSICAL DESIGN │      │ 9. STA FLOW      │
    │ Scan, ATPG, BIST │      │ PD Full Flow       │      │ Multi-corner     │
    │ JTAG             │      │ (see PD doc)       │      │ timing closure   │
    └──────────────────┘      └─────────┬──────────┘      └──────────────────┘
                                        │ GDS II
                     ┌──────────────────▼──────────────────────────────────┐
                     │  TAPE-OUT                                            │
                     └────────────────────┬────────────────────────────────┘
                                          │
               ┌──────────────────────────┼──────────────────────────┐
               ▼                          ▼                          ▼
    ┌──────────────────┐      ┌───────────────────┐      ┌──────────────────┐
    │ 12. COMPILER     │      │ 13. EMBEDDED       │      │  Silicon Bring-up│
    │ TOOLCHAIN        │      │ FIRMWARE           │      │  (extends FPGA   │
    │ (for custom CPU) │      │ BSP, drivers, RTOS │      │  proto flow)     │
    └──────────────────┘      └───────────────────┘      └──────────────────┘
```

---

## Document Index

| # | Document | Description | Input | Output |
|---|----------|-------------|-------|--------|
| 0 | `Infrastructure_Setup_Flow.md` | EDA tool detection, wrapper deployment, MCP config | Host environment | tool-status.json, module-status.json, tool-manifest.json, wrappers, MCP snippets |
| 1 | `Architecture_Evaluation_Flow.md` | Microarch exploration, PPA estimate, risk | Product spec | Microarch doc |
| 2 | `RTL_Design_Flow.md` | SV RTL coding, lint, CDC, synth check | Microarch doc | Synthesis-ready RTL |
| 3 | `HLS_Flow.md` | C/C++ to RTL for algorithm blocks | C source + TB | Verified RTL |
| 4 | `Functional_Verification_Flow.md` | UVM TB, coverage, regression | RTL + spec | Verified RTL + sign-off |
| 5 | `Formal_Verification_Flow.md` | FPV, LEC, CDC formal | RTL + properties | Proven properties + LEC |
| 6 | `Logic_Synthesis_Flow.md` | Synthesis, constraints, LEC | RTL + SDC | Gate netlist |
| 7 | `DFT_Flow.md` | Scan, ATPG, BIST, JTAG | Gate netlist | Test-ready netlist + patterns |
| 8 | `PD_Flow_Architecture.md` | Full physical design flow | Netlist + SDC | GDS II |
| 9 | `STA_Flow.md` | Multi-corner timing analysis, ECO | Routed DEF + SPEF | Timing closure report |
| 10 | `SoC_IP_Integration_Flow.md` | IP procurement, SoC assembly | IP list + arch | Integrated SoC RTL |
| 11 | `Memory_IP_Design_Flow.md` | Memory macro selection, array arch, repair, view QA | Memory requirements + PDK | Qualified memory IP + views |
| 12 | `Compiler_Toolchain_Flow.md` | LLVM/GCC backend for custom ISA | ISA spec | Validated toolchain |
| 13 | `Embedded_Firmware_Flow.md` | BSP, drivers, RTOS, validation | Chip datasheet | Validated firmware |
| 14 | `FPGA_Emulation_Flow.md` | FPGA port, bring-up, SW validation | ASIC RTL | FPGA prototype + SW |

---

## Inter-Orchestrator Handoff Contracts

Each orchestrator produces a standardized handoff package consumed by the next.

### Architecture → RTL Design
```json
{
  "handoff": "arch_to_rtl",
  "from": "Architecture Evaluation Orchestrator",
  "to":   "RTL Design Orchestrator",
  "package": {
    "microarch_doc":       "path/to/microarch.md",
    "module_hierarchy":    "path/to/hierarchy.json",
    "interface_specs":     "path/to/interfaces.md",
    "memory_map":          "path/to/memory_map.md",
    "clock_domains":       ["clk_core_1GHz", "clk_peri_200MHz"],
    "clock_power_budget":  "path/to/clock_power_budget.md",
    "coding_guidelines":   "path/to/guidelines.md",
    "verification_plan":   "path/to/vplan.md"
  }
}
```

### RTL Design → Verification
```json
{
  "handoff": "rtl_to_verif",
  "from": "RTL Design Orchestrator",
  "to":   "Verification Orchestrator",
  "package": {
    "rtl_filelist":  "filelist.f",
    "lint_report":   "lint_clean.rpt",
    "cdc_report":    "cdc_clean.rpt",
    "compile_order": "compile_order.f",
    "assertions":    "assertions.sva"
  }
}
```

### RTL Design → Synthesis
```json
{
  "handoff": "rtl_to_synth",
  "from": "RTL Design Orchestrator",
  "to":   "Synthesis Orchestrator",
  "package": {
    "rtl_filelist": "filelist.f",
    "sdc":          "constraints.sdc",
    "liberty_libs": ["tt.lib", "ss.lib", "ff.lib"],
    "dont_touch":   ["memories.list"],
    "target_freq":  "1GHz"
  }
}
```

### Synthesis → DFT → PD
```json
{
  "handoff": "synth_to_dft_to_pd",
  "from": "Synthesis → DFT Orchestrators",
  "to":   "Physical Design Orchestrator",
  "package": {
    "netlist":     "dft_netlist.v",
    "sdc":         "pd_constraints.sdc",
    "scandef":     "scan_chains.scandef",
    "lef":         ["tech.lef", "cells.lef"],
    "lib":         ["tt.lib", "ss.lib", "ff.lib"],
    "upf":         "power_intent.upf"
  }
}
```

### PD → Firmware (Post Tape-out)
```json
{
  "handoff": "pd_to_firmware",
  "from": "Physical Design Orchestrator",
  "to":   "Firmware Orchestrator",
  "package": {
    "memory_map":    "final_memory_map.md",
    "register_map":  "registers.json",
    "peripheral_list": ["UART0", "SPI0", "I2C0", "GPIO", "DMA"],
    "timing_spec":   "io_timing.md",
    "errata":        "silicon_errata.md"
  }
}
```

---

## Recommended Implementation Order

When building this system in a new session, implement in this order:

### Phase 1 — Core Design Skills (Week 1)
1. Architecture Evaluation skills + stage agents
2. RTL Design skills + stage agents
3. Test with a small synthesizable block

### Phase 2 — Verification Skills (Week 2)
4. Functional Verification (UVM) skills + agents
5. Formal Verification skills + agents
6. Wire Phase 1 → Phase 2 handoff

### Phase 3 — Implementation Skills (Week 3)
7. Logic Synthesis skills + agents
8. DFT skills + agents
9. Physical Design skills + agents (use existing PD_Flow_Architecture.md)
10. STA skills + agents

### Phase 4 — Software Skills (Week 4)
11. HLS skills + agents
12. Compiler Toolchain skills + agents
13. Embedded Firmware skills + agents
14. FPGA Emulation skills + agents

### Phase 5 — Orchestrator Integration (Week 5)
15. Implement all orchestrators
16. Implement inter-orchestrator handoff contracts
17. End-to-end test with a reference design (e.g., RISC-V core or simple SoC)

---

## Global Agent Configuration

All agents in this system share these configurations:

```json
{
  "model": "claude-sonnet-4-20250514",
  "max_tokens": 4096,
  "temperature": 0.2,
  "system_prompt_prefix": "You are a specialized AI agent in a chip design pipeline. You receive a structured state object and skill document. Always return a structured JSON result. Be precise and technically rigorous.",
  "output_format": {
    "stage": "string",
    "status": "PASS | FAIL | WARN",
    "confidence": "high | medium | low",
    "failure_class": "none | functional | timing | power_area | drc_lvs | coverage_gap | connectivity | tool_error | input_setup | spec_gap | resource_limit",
    "qor": "object — metrics per skill definition",
    "issues": "array — [{severity, description, fix}]",
    "suggested_next_step": "proceed | loop_back_to:<stage> | retry_stage | escalate | abandon",
    "output": "object — stage deliverables"
  }
}
```

### Output Field Semantics

**`confidence`** — The orchestrator's self-assessment of result reliability:
- `high`: deterministic result — clean tool evidence, no waivers or estimates, all sign-off criteria met.
- `medium`: result holds but relies on waivers, estimates, assumptions, or a tool fallback path.
- `low`: result depends on unverified assumptions, partial data, or tool errors — human review advised.

**`failure_class`** — Domain-agnostic failure taxonomy; `none` when `status` is `PASS`. Distinct from `fix_request.failure_class` (verification/formal-specific root causes):
- `functional` — logic or behavioral incorrectness
- `timing` — setup/hold/WNS violations
- `power_area` — power or area budget exceeded
- `drc_lvs` — physical verification failure (DRC, LVS, antenna)
- `coverage_gap` — verification coverage shortfall
- `connectivity` — CDC/RDC, protocol, or interface mismatch
- `tool_error` — EDA tool crash, license issue, or infrastructure failure
- `input_setup` — the tool ran correctly on the wrong inputs (filelist, include path, config, generated headers, library views); always escalates, never retried and never looped back
- `spec_gap` — missing or ambiguous specification or requirement
- `resource_limit` — max iterations, max turns, or compute budget exceeded

**`suggested_next_step`** — Recommended consumer action; `loop_back_to:<stage>` must name a stage in the orchestrator's Stage Sequence:
- `proceed` — advance to next stage or hand off to downstream orchestrator
- `loop_back_to:<stage>` — return to an earlier named stage
- `retry_stage` — re-run the current stage (transient `tool_error` failures)
- `escalate` — stop and require human decision
- `abandon` — unrecoverable; terminate the flow

---

## Skill File Directory Structure

```
/skills/
├── sv-arch-spec/SKILL.md
├── sv-arch-exploration/SKILL.md
├── sv-arch-perf/SKILL.md
├── sv-arch-ppa/SKILL.md
├── sv-arch-risk/SKILL.md
├── sv-arch-signoff/SKILL.md
│
├── sv-rtl-planning/SKILL.md
├── sv-rtl-coding/SKILL.md
├── sv-rtl-lint/SKILL.md
├── sv-rtl-cdc/SKILL.md
├── sv-rtl-synth-check/SKILL.md
├── sv-rtl-signoff/SKILL.md
│
├── sv-verif-tb-arch/SKILL.md
├── sv-verif-test-plan/SKILL.md
├── sv-verif-uvm-build/SKILL.md
├── sv-verif-coverage/SKILL.md
├── sv-verif-formal/SKILL.md
├── sv-verif-regression/SKILL.md
│
├── sv-synth-constraints/SKILL.md
├── sv-synth-compile/SKILL.md
├── sv-synth-netlist-qc/SKILL.md
│
├── sv-formal-property/SKILL.md
├── sv-formal-environment/SKILL.md
├── sv-formal-fpv/SKILL.md
├── sv-formal-lec/SKILL.md
│
├── sv-dft-architecture/SKILL.md
├── sv-dft-scan/SKILL.md
├── sv-dft-atpg/SKILL.md
├── sv-dft-bist/SKILL.md
├── sv-dft-jtag/SKILL.md
│
├── sv-sta-constraints/SKILL.md
├── sv-sta-analysis/SKILL.md
├── sv-sta-eco/SKILL.md
│
├── sv-hls-algorithm/SKILL.md
├── sv-hls-directives/SKILL.md
├── sv-hls-cosim/SKILL.md
│
├── sv-compiler-isa/SKILL.md
├── sv-compiler-backend/SKILL.md
├── sv-compiler-assembler/SKILL.md
├── sv-compiler-linker/SKILL.md
├── sv-compiler-runtime/SKILL.md
├── sv-compiler-validation/SKILL.md
│
├── sv-fw-bsp/SKILL.md
├── sv-fw-drivers/SKILL.md
├── sv-fw-rtos/SKILL.md
├── sv-fw-validation/SKILL.md
│
├── sv-soc-ip-procurement/SKILL.md
├── sv-soc-bus-fabric/SKILL.md
├── sv-soc-top-integration/SKILL.md
├── sv-soc-chip-sim/SKILL.md
│
├── sv-fpga-rtl-adapt/SKILL.md
├── sv-fpga-partition/SKILL.md
├── sv-fpga-synthesis/SKILL.md
├── sv-fpga-bringup/SKILL.md
└── sv-fpga-sw-validation/SKILL.md
```

**Total: 16 Orchestrators | 14 Flow Documents | 17 Skill Files**

The tree above is the legacy per-stage skill layout and is kept for reference. Skills now live one per domain under `plugins/<domain>/skills/`.
