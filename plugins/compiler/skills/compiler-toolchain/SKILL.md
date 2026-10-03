---
name: compiler-toolchain
description: >
  Compiler toolchain development for custom processor ISAs — LLVM/GCC backend,
  assembler, linker scripts, runtime libraries, and regression validation.
  Use when building a compiler for a custom RISC-V extension, proprietary ISA,
  or any processor where no existing toolchain targets it correctly.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: Compiler Toolchain Development

## Invocation

When this skill is loaded and a user presents a compiler or ISA task, **do not
execute stages directly**. Immediately spawn the
`digital-chip-design-agents:compiler-orchestrator` agent and pass the full user
request and any available context to it. The orchestrator enforces the stage
sequence, loop-back rules, and sign-off criteria defined below.

Use the domain rules in this file only when the orchestrator reads this skill
mid-flow for stage-specific guidance, or when the user asks a targeted reference
question rather than requesting a full flow execution.

## Pre-run Context

Before executing or advising on **any** stage, read the following files if they exist:

1. `memory/compiler/knowledge.md` — known failure patterns, successful tool flags, PDK/tool quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `memory/compiler/run_state.md` — current run identity (`run_id`, `design_name`, `tool`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Build and validate a complete compiler toolchain (LLVM or GCC based) for a
custom processor ISA. Bridges hardware and software — without a working
toolchain no software can run on the designed chip.

---

## Supported EDA Tools

### Open-Source
- **LLVM/Clang** (`clang`, `llc`, `llvm-mc`, `llvm-objdump`) — primary toolchain for new ISA backends
- **GCC and GNU Binutils** (`gcc`, `as`, `ld`, `objdump`) — alternative backend; well-tested for RISC-V extensions
- **QEMU** (`qemu-system-*`) — instruction-accurate ISA emulation for toolchain validation without hardware

### Proprietary
- **Green Hills MULTI** (dialect `greenhills`) — safety-critical compiler and debugger IDE
- **IAR Embedded Workbench** (dialect `iar`) — certified compiler for ARM/RISC-V
- **Arm Compiler 6** (`armcc`, dialect `arm`) — LLVM-based compiler for Arm targets

---

## Stage: isa_analysis

### ISA Feature → Toolchain Component Mapping
| ISA Feature | Toolchain Component |
|-------------|-------------------|
| Instruction encoding | Assembler, disassembler |
| Register file | Register allocator, ABI |
| Calling convention | ABI, function call lowering |
| Branch/jump | Control flow, delay slot handling |
| Load/store addressing | Memory access patterns |
| SIMD/vector | Auto-vectorisation, intrinsics |
| Atomics | Memory model, concurrency |
| Multiply/divide | Integer arithmetic lowering |
| FPU presence | FP ABI (hard-float vs soft-float) |
| Custom instructions | Intrinsics, builtin functions |

### ABI Requirements (define before any backend code)
1. Argument passing: which registers, stack spill rules
2. Return value registers
3. Callee-saved vs caller-saved register classification
4. Stack alignment (8 or 16 byte)
5. Data type sizes and alignments
6. Struct layout (padding, packing rules)
7. Thread-local storage model (if RTOS target)

### Output Required
- ISA-to-toolchain mapping table
- ABI specification document
- List of LLVM/GCC backend files to create/modify
- Target triple: `<arch>-<vendor>-<os>`

---

## Stage: backend_dev

### LLVM Backend — Implement in This Order
1. `RegisterInfo.td`: register classes, aliases, reserved registers
2. `InstrInfo.td`: all instruction definitions with encoding
3. `CallingConv.td`: argument and return value register rules
4. `SchedModel.td`: latency and throughput per instruction class
5. `TargetMachine.cpp`: entry point, subtarget selection
6. `ISelDAGToDAG.cpp`: selection DAG → machine instruction lowering
7. `FrameLowering.cpp`: stack frame, prologue/epilogue
8. `AsmPrinter.cpp`: assembly text emission

### Testing per Component
- TableGen: `llvm-tblgen` compiles .td without errors
- Codegen: `llc` compiles C snippets; verify .s output manually
- MC layer: `llvm-mc --show-encoding` verifies instruction encoding

### QoR Metrics to Evaluate
- All ISA instruction classes: lowerable from LLVM IR
- Calling convention: function call round-trip test passes
- No illegal instructions in generated assembly
- Basic integer test program: compiles, links, executes on ISS

### Common Issues & Fixes
| Issue | Fix |
|-------|-----|
| TableGen pattern not matching | Add explicit `Pat<>` with matching operand types |
| Stack corrupt | Verify prologue saves all callee-saved regs |
| Calling convention mismatch | Cross-check CCAssignToReg vs ABI spec |

### Output Required
- Complete LLVM backend source tree
- Regression test files (llc lit tests)
- Build instructions (CMake)

---

## Stage: assembler_dev

### Domain Rules
1. LLVM MC layer provides assembler via .td instruction definitions
2. For every instruction: encode-decode round-trip test
3. Define all ELF relocation types: `R_<ARCH>_*`
4. Directives: `.section`, `.global`, `.type`, `.size`, `.align` all working
5. DWARF: verify `.debug_info` emitted for a C function (needed for GDB)
6. Branch offsets: verify PC-relative encoding for forward and backward branches
7. Immediate ranges: verify truncation and sign-extension at instruction boundaries

### QoR Metrics to Evaluate
- All instructions: encode-decode round-trip passes
- All relocation types: defined and tested
- ELF output: readable by `readelf -a`
- DWARF: basic debug info emitted

### Output Required
- Assembler integrated in LLVM MC layer
- Encoding test suite (one test per instruction format)
- Relocation definition table

---

## Stage: linker_config

### Linker Script Template
```ld
MEMORY {
  FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 512K
  RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
}
ENTRY(_start)
SECTIONS {
  .text   : { *(.text.reset) *(.text*) *(.rodata*) } > FLASH
  .data   : { *(.data*) }  > RAM AT > FLASH
  .bss    : { *(.bss*) *(COMMON); PROVIDE(__bss_end = .); } > RAM
  .stack  : { . = ALIGN(16); PROVIDE(__stack_top = .); . += STACK_SIZE; } > RAM
}
```

### Domain Rules
1. Memory regions must match chip memory map exactly
2. Startup code (`crt0.S`): copy `.data` LMA→VMA; zero `.bss`; call `main()`
3. Stack defined via linker symbol `__stack_top`; size configurable at link time
4. All relocation types from assembler stage must be handled
5. Verify: bare-metal binary links, loads, executes from reset vector

### QoR Metrics to Evaluate
- Binary links without undefined symbols
- `.data` initialised correctly at runtime
- `.bss` zeroed at startup
- Stack pointer: correct value at entry

### Output Required
- Linker scripts per memory configuration
- Startup code (crt0.S)
- Linker configuration documentation

---

## Stage: runtime_libs

### Required Libraries
| Library | Contents | Source |
|---------|----------|--------|
| compiler-rt | Integer multiply/divide, soft-float | LLVM |
| newlib/picolibc | C standard library (bare-metal) | Port |
| libstdc++/libc++ | C++ standard library | LLVM/GCC |
| libm | Math library | newlib |

### Porting newlib
1. Implement syscall stubs: `_write`, `_read`, `_sbrk`, `_exit`, `_close`
2. `_sbrk`: heap using `__heap_start`/`__heap_end` linker symbols
3. `_write`: route to UART or semihosting for debug output
4. C++ global constructors: add `.init_array` section to linker script

### QoR Metrics to Evaluate
- `printf`, `malloc`, `memcpy`, `strlen`: all functional
- Soft-float: bit-exact results vs IEEE 754 (if no HW FPU)
- Heap: no corruption under stress allocation/free test
- C++ constructors: called before `main()`

### Output Required
- Ported and compiled runtime libraries
- Syscall stub implementations
- Library test results

---

## Stage: toolchain_validation

### Validation Tiers
| Tier | Pass Criteria |
|------|--------------|
| Smoke (hello world) | 100% |
| Unit (per-instruction asm tests) | 100% |
| Compiler (C feature tests) | ≥ 99% |
| Runtime (C library tests) | ≥ 99% |
| Application (representative workloads) | Correct output |
| Performance | Within 10% of target |

### QoR Metrics to Evaluate
- Compiler regression: ≥ 99% pass
- Runtime tests: ≥ 99% pass
- Application workloads: correct output vs golden
- No miscompilation (wrong output = P0 blocker)

### Output Required
- Regression report (per tier, pass/fail counts)
- Miscompilation root cause (if any)
- Performance comparison vs target

---

## Stage: toolchain_signoff

### Sign-off Checklist
- [ ] Compiler: generates correct code for custom ISA
- [ ] Assembler: encodes all instructions correctly
- [ ] Linker: correct scripts for all memory configurations
- [ ] Runtime: libgcc/compiler-rt, newlib, libm all pass tests
- [ ] Binutils: objdump, readelf, nm, objcopy work for target
- [ ] Debugger: GDB or LLDB with target support functional
- [ ] ISS: instruction-set simulator available
- [ ] All regression tiers: PASS
- [ ] Documentation: ABI spec, getting started guide, known issues

### Output Required
- Toolchain release package
- Validation report
- ABI specification (final)
- Known issues list

---

## Memory

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
write or overwrite one JSON record in `memory/compiler/experiences.jsonl` keyed by
`run_id`. This ensures data is persisted even if the flow is interrupted or called
without full orchestrator context.

Use `run_id` = `compiler_<YYYYMMDD>_<HHMMSS>` (set once at flow start; reuse on each
stage update). Every JSON record written must include a top-level `"run_id"` field
whose value matches this key — this is what makes overwrites unambiguous. Set
`signoff_achieved: false` until the final sign-off stage completes.
### Run state (write before first stage, update after each stage)
Write `memory/compiler/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:      compiler_<YYYYMMDD>_<HHMMSS>
design_name: <design>
tool:        <primary tool>
start_time:  <ISO-8601>
last_stage:  <first stage name>
```
Update `last_stage` after each stage completes. This file lets wakeup-loop prompts
and resumed sessions identify the correct run without relying on in-memory state.
Create the file and parent directories if they do not exist.

### Optional: claude-mem index
If `mcp__plugin_ecc_memory__add_observations` is available in this session, emit each
applied fix as an observation to entity `chip-design-compiler-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.
