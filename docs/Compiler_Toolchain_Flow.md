# Compiler Toolchain Development Flow — Full Architecture Design
## Orchestrator + Stage Agents + Skills

> **Purpose**: AI-driven flow for developing and validating a compiler toolchain targeting a custom processor ISA or embedded SoC. Covers ISA specification, compiler backend development, assembler, linker, runtime libraries, and toolchain validation. This is the software layer that enables code to run on the designed chip.

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│              COMPILER TOOLCHAIN ORCHESTRATOR                 │
│  Input:  ISA spec, processor microarch, ABI requirements     │
│  Output: Validated compiler toolchain (GCC/LLVM-based)       │
└────────────────────────┬─────────────────────────────────────┘
                         │
     ┌───────────────────┼────────────────────────────┐
     ▼                   ▼                            ▼
  ISA Spec           Backend Dev               Toolchain
  Agent              Agent                     Validation Agent
     │                   │                            │
  SKILL              SKILL                        SKILL
```

---

## 2. Shared State Object

```json
{
  "run_id": "compiler_001",
  "processor_name": "my_cpu",
  "inputs": {
    "isa_spec":          "path/to/isa.md",
    "microarch_doc":     "path/to/microarch.md",
    "base_toolchain":    "LLVM-17 | GCC-13",
    "abi_spec":          "path/to/abi.md",
    "target_triple":     "mycpu-unknown-elf",
    "register_file":     "32x 32-bit GPR + 16x 64-bit FPR",
    "endianness":        "little",
    "word_size":         32
  },
  "stages": {
    "isa_analysis":        { "status": "pending", "output": {} },
    "backend_dev":         { "status": "pending", "output": {} },
    "assembler_dev":       { "status": "pending", "output": {} },
    "linker_config":       { "status": "pending", "output": {} },
    "runtime_libs":        { "status": "pending", "output": {} },
    "toolchain_validation":{ "status": "pending", "output": {} },
    "toolchain_signoff":   { "status": "pending", "output": {} }
  },
  "test_results": {
    "compile_tests": 0, "asm_tests": 0,
    "link_tests": 0, "runtime_tests": 0,
    "regression_pass_rate": 0.0
  },
  "flow_status": "not_started"
}
```

---

## 3. Stage Sequence

```text
isa_analysis → backend_dev → assembler_dev → linker_config → runtime_libs → toolchain_validation → toolchain_signoff
```

Loop-back rules — the target stage, the iteration cap, and which failures escalate
instead of looping — are in `## Loop-Back Rules` of [`compiler-orchestrator.md`](../plugins/compiler/agents/compiler-orchestrator.md). That file is
authoritative; this document does not restate them.

---

## 4. Skill File Specifications

### 4.1 `sv-compiler-isa/SKILL.md`

```markdown
# Skill: Compiler — ISA Analysis

## Purpose
Analyze the processor ISA to identify all features that require
compiler support, and map them to toolchain components.

## ISA Feature → Toolchain Component Mapping
| ISA Feature              | Affects                              |
|--------------------------|--------------------------------------|
| Instruction encoding     | Assembler, disassembler              |
| Register file            | Register allocator, ABI              |
| Calling convention       | ABI, function call lowering          |
| Branch/jump instructions | Control flow lowering, branch delay  |
| Load/store addressing    | Memory access patterns               |
| SIMD/vector instructions | Auto-vectorization, intrinsics       |
| Atomic instructions      | Memory model, concurrency support    |
| Multiply/divide          | Integer arithmetic lowering          |
| FPU presence             | Floating-point ABI (hard vs soft)    |
| Privileged instructions  | Runtime, OS support layer            |
| Custom instructions      | Intrinsics, builtin functions        |

## ABI Requirements to Define
1. Calling convention: argument passing (registers vs stack)
2. Return value convention: which registers
3. Callee-saved vs caller-saved registers
4. Stack alignment: 8 or 16 byte
5. Data type sizes and alignments (int, long, pointer)
6. Struct layout rules (padding, packing)
7. Thread-local storage model

## QoR Metrics
- All ISA instruction classes mapped to toolchain component
- ABI fully specified (no ambiguities)
- Custom instructions: intrinsic interface defined

## Output Required
- ISA-to-toolchain mapping table
- ABI specification document
- List of LLVM/GCC backend files to create/modify
```

---

### 4.2 `sv-compiler-backend/SKILL.md`

```markdown
# Skill: Compiler — Backend Development (LLVM-based)

## Purpose
Implement the machine code generation backend targeting the custom ISA.

## LLVM Backend Components to Implement
1. Target description (.td files):
   - Register definitions (RegisterInfo.td)
   - Instruction definitions (InstrInfo.td)
   - Calling convention (CallingConv.td)
   - Scheduling model (SchedModel.td)

2. C++ backend classes:
   - TargetMachine (MyTargetMachine.cpp)
   - RegisterInfo (MyRegisterInfo.cpp)
   - InstrInfo (MyInstrInfo.cpp)
   - ISelDAGToDAG (selection DAG → machine instrs)
   - AsmPrinter (emit assembly text)
   - FrameLowering (stack frame, prologue/epilogue)

3. Optimization hints:
   - Instruction scheduling model (latencies, throughput)
   - Cost model for inlining and unrolling decisions
   - Pipeline hazard recognizer

## Development Order (Recommended)
1. Register file + calling convention
2. Basic integer instructions (ALU, load/store, branch)
3. Function call lowering (call/return)
4. Selection patterns (DAG patterns in .td)
5. FPU instructions (if present)
6. SIMD/vector instructions
7. Custom instructions (intrinsics)
8. Scheduling model

## Testing per Component
- TableGen: check .td files compile with llvm-tblgen
- Codegen: use llc to compile C snippets; verify .s output
- MC layer: verify encoding with llvm-mc --show-encoding

## QoR Metrics
- All ISA instruction classes: code-gennable from LLVM IR
- Calling convention test: function call round-trips correctly
- No illegal instructions in generated code
- Passes llvm test-suite basic subset

## Output Required
- Complete LLVM backend source tree
- Regression test files (llc tests)
- Build instructions
```

---

### 4.3 `sv-compiler-assembler/SKILL.md`

```markdown
# Skill: Compiler — Assembler Development

## Purpose
Implement or configure the assembler for the target ISA,
enabling hand-written assembly and compiler-emitted assembly to be encoded.

## LLVM MC Layer (preferred for LLVM-based toolchains)
1. MCInstrDesc: encoding information from .td files
2. Fixups: relocations for branch targets, symbol references
3. ELF object writer: produces .o files in ELF format
4. Disassembler: decode binary → mnemonic (for debug)

## Assembler Syntax Requirements
1. AT&T vs Intel syntax decision (document in ABI)
2. Directive support: .section, .global, .type, .size, .align
3. Pseudo-instructions: NOP, CALL (expanded by assembler)
4. Relocation types: define all ELF relocation types for ISA
5. Debug info: DWARF emission support

## Encoding Validation
1. For every instruction: write encode/decode round-trip test
2. Verify immediate ranges: correct truncation and sign-extension
3. Verify branch offsets: PC-relative encoding correctness
4. Verify register numbers: match ISA register file numbering

## QoR Metrics
- All instructions: encode/decode round-trip passes
- Relocation types: all defined and tested
- ELF output: verifiable with readelf

## Output Required
- Assembler source (integrated in LLVM MC)
- Encoding test suite
- Relocation definition table
```

---

### 4.4 `sv-compiler-linker/SKILL.md`

```markdown
# Skill: Compiler — Linker Configuration

## Purpose
Configure the linker (GNU ld or LLVM lld) for the target processor
memory map and produce executable binaries.

## Linker Script Requirements
1. Memory regions: FLASH (code), RAM (data/stack/heap) — from chip memory map
2. Section placement: .text, .rodata, .data, .bss, .stack, .heap
3. Entry point: define reset vector / entry symbol
4. Startup code: copy .data from FLASH to RAM, zero .bss
5. Stack/heap sizing: configurable via linker symbols

## Example Linker Script Structure
```ld
MEMORY {
  FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 512K
  RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
}
SECTIONS {
  .text   : { *(.text*) *(.rodata*) } > FLASH
  .data   : { *(.data*) } > RAM AT > FLASH
  .bss    : { *(.bss*) *(COMMON) } > RAM
  .stack  : { . = . + STACK_SIZE; } > RAM
}
```

## Relocation Support
1. All relocation types defined in assembler: handled in linker
2. PLT/GOT: if shared libraries supported
3. Weak symbols: correctly resolved

## QoR Metrics
- Simple "hello world" (or equivalent bare-metal) links and runs
- .data initialized correctly at startup
- .bss zeroed at startup
- No undefined symbol errors on standard library

## Output Required
- Linker script(s) (per memory configuration)
- Startup code (crt0.S or equivalent)
- Linker configuration documentation
```

---

### 4.5 `sv-compiler-runtime/SKILL.md`

```markdown
# Skill: Compiler — Runtime Libraries

## Purpose
Build or port the runtime libraries required for compiled code to
execute on the target processor.

## Required Libraries
| Library        | Contents                                  | Source         |
|----------------|-------------------------------------------|----------------|
| libgcc/compiler-rt | Integer multiply/divide, FP soft-float| GCC/LLVM       |
| newlib/picolibc | C standard library (bare-metal)         | newlib port    |
| libstdc++/libc++ | C++ standard library                  | GCC/LLVM       |
| crt0.o         | C runtime startup (init, .data, .bss)    | Custom         |
| libm            | Math library                             | newlib         |

## Porting Steps for newlib
1. Implement syscall stubs (_write, _read, _sbrk, _exit, etc.)
2. Implement _sbrk for heap management (increment program break)
3. Wire _write to UART or semihosting for debug output
4. Configure with correct word size and endianness

## Soft-Float Library (if no FPU)
1. compiler-rt or libgcc provides: __addsf3, __mulsf3, __divdf3, etc.
2. Verify with FP operation test suite
3. Performance: profile key FP operations; optimize if bottleneck

## QoR Metrics
- C standard library: passes newlib test suite
- Soft-float (if used): bit-exact results vs reference
- Heap/stack: no corruption under stress test
- C++ constructors: called correctly at startup

## Output Required
- Ported and compiled runtime libraries
- Syscall stub implementations
- Library test results
```

---

### 4.6 `sv-compiler-validation/SKILL.md`

```markdown
# Skill: Compiler — Toolchain Validation

## Purpose
Validate the complete toolchain through a regression suite
that exercises compilation, assembly, linking, and execution.

## Validation Tier Structure
| Tier          | Contents                                     | Pass Criteria   |
|---------------|----------------------------------------------|-----------------|
| Smoke         | Hello world, basic arithmetic                | 100%            |
| Unit          | Per-instruction assembly tests               | 100%            |
| Compiler      | C/C++ feature tests (GCC torture tests)      | ≥ 99%           |
| Runtime       | C library function tests                     | ≥ 99%           |
| Application   | Representative workloads (FFT, sort, etc.)   | Correct output  |
| Performance   | Cycle count vs target spec                   | Within 10%      |

## Execution Environment Options
1. Instruction Set Simulator (ISS): cycle-accurate, fast for testing
2. RTL simulation: slow but exact, use for final validation
3. FPGA prototype: faster than RTL sim, near-cycle-accurate
4. Silicon: final validation

## Key Test Categories
- Integer arithmetic: all operations, edge cases (overflow, zero)
- Branching: forward, backward, indirect, function calls
- Load/store: all widths, alignment, endianness
- FPU: IEEE 754 compliance (if HW FPU present)
- ABI: function call convention, varargs, struct passing
- Atomic: memory ordering (if SMP target)

## QoR Metrics
- Compiler regression: ≥ 99% pass rate
- Runtime tests: ≥ 99% pass rate
- No miscompilation on application workloads
- Performance within 10% of target

## Output Required
- Regression report (pass/fail counts per tier)
- Miscompilation root cause analysis (if any)
- Performance comparison vs target
```

---

## 5. Orchestrator System Prompt

The orchestrator's system prompt is its agent definition, [`compiler-orchestrator.md`](../plugins/compiler/agents/compiler-orchestrator.md): stage
sequence, loop-back rules, stage gating and escalation. This document does not
restate it.

---

## 6. Toolchain Release Package Checklist

```markdown
## Toolchain Release Checklist
- [ ] Compiler (clang/gcc) binary: targets custom ISA
- [ ] Assembler (llvm-as / gas): encodes all ISA instructions
- [ ] Linker (lld/ld): correct linker scripts for memory map
- [ ] Runtime libraries: libgcc/compiler-rt, newlib, libm
- [ ] Binutils: objdump, readelf, nm, objcopy for target
- [ ] GDB / LLDB: debugger with target support
- [ ] ISS: instruction-set simulator for offline testing
- [ ] Documentation: ABI spec, getting started guide
- [ ] Validation report: regression pass rates
- [ ] Known issues: documented with workarounds
```
