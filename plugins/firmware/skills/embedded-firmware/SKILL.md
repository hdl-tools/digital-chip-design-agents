---
name: embedded-firmware
description: >
  Embedded firmware and device drivers — BSP development, peripheral driver
  implementation (UART, SPI, I2C, GPIO, DMA, Timer), RTOS integration (FreeRTOS,
  Zephyr), and system validation. Use when writing chip bring-up firmware,
  implementing HAL drivers, porting an RTOS, or validating firmware on hardware.
version: 1.0.0
author: chuanseng-ng
license: MIT
allowed-tools: Read, Write, Bash
---

# Skill: Embedded Firmware & Device Drivers

## Invocation

When this skill is loaded and a user presents a firmware or BSP task, **do not
execute stages directly**. Immediately spawn the
`digital-chip-design-agents:firmware-orchestrator` agent and pass the full user
request and any available context to it. The orchestrator enforces the stage
sequence, loop-back rules, and sign-off criteria defined below.

Use the domain rules in this file only when the orchestrator reads this skill
mid-flow for stage-specific guidance, or when the user asks a targeted reference
question rather than requesting a full flow execution.

## Pre-run Context

Before executing or advising on **any** stage, read the following files if they exist:

1. `memory/firmware/knowledge.md` — known failure patterns, successful tool flags, PDK/tool quirks.
   Incorporate its guidance into every stage decision. If absent, proceed without it.
2. `memory/firmware/run_state.md` — current run identity (`run_id`, `design_name`, `tool`,
   `last_stage`). Use this to resume correctly after interruption. If absent, a new run
   is starting; the orchestrator will create this file before the first stage.

This pre-run read applies whether this skill is loaded by a user or called by the
orchestrator mid-flow. It ensures the fix database is consulted before any diagnosis step.

## Purpose
Guide BSP creation, peripheral driver development, RTOS integration, and
system-level firmware validation. The firmware layer is the first software
to run on real silicon — correctness here enables all subsequent SW development.

---

## Supported EDA Tools

### Open-Source
- **GCC cross-compiler** (`arm-none-eabi-gcc`, `riscv64-unknown-elf-gcc`) — bare-metal firmware compilation
- **OpenOCD** (`openocd`) — open-source on-chip debugger; supports JTAG/SWD for bring-up
- **GDB cross-debugger** (`arm-none-eabi-gdb`) — source-level debugging over OpenOCD
- **QEMU** (`qemu-system-arm`, `qemu-system-riscv64`) — firmware validation before hardware is available

### Proprietary
- **J-Link GDB Server** (`JLinkGDBServer`, dialect `segger`) — high-speed JTAG/SWD probe from SEGGER
- **Lauterbach TRACE32** (`t32marm`, dialect `lauterbach`) — hardware trace and debug for bring-up
- **Arm Development Studio** (`armds`, dialect `arm`) — Eclipse-based IDE with Arm compiler and debugger

---

## Stage: bsp_development

### Domain Rules
1. Startup code (`crt0.S`/`startup.c`) must in order:
   - Set stack pointer to `__stack_top` (from linker script)
   - Copy `.data` LMA → VMA
   - Zero `.bss`
   - Call `SystemInit()`
   - Branch to `main()`
2. `SystemInit()` order: power stable → PLLs → clock mux → peripherals
3. Interrupt controller: define vector table, IRQ enable/disable API, priority API
4. `memory_map.h`: ALL peripheral base addresses and register offsets — no magic numbers
5. All hardware register accesses: `volatile` pointer dereference
6. Atomic read-modify-write on hardware registers: disable IRQ or use atomic ops
7. Memory barriers (DMB/DSB or equivalent) around hardware access sequences
8. BSP must be RTOS-agnostic — no OS API calls in BSP layer

### QoR Metrics to Evaluate
- Boot: chip reaches `main()` within expected startup time
- Clocks: all PLLs locked; peripherals clocked correctly
- Interrupts: vector table valid; default handler traps unhandled exceptions
- Memory: `.data` initialised; `.bss` zeroed (verify with memory read)

### Common Issues & Fixes
| Issue | Fix |
|-------|-----|
| PLL not locking | Check reference clock source; verify input frequency range |
| Hang before `main()` | Toggle debug LED at each init step to isolate |
| Stack overflow at boot | Increase `STACK_SIZE` in linker script |
| `.data` not initialised | Verify crt0 LMA→VMA copy range; check AT clause |

### Output Required
- `startup.S` and `system_init.c`
- `memory_map.h` (complete register definitions)
- Linker scripts
- BSP build system

---

## Stage: peripheral_drivers

### Driver Architecture (HAL pattern)
```c
status_t PERIPH_Init(PERIPH_Type *base, const periph_config_t *config);
status_t PERIPH_WriteBlocking(PERIPH_Type *base, const uint8_t *data, size_t len);
status_t PERIPH_TransferNonBlocking(PERIPH_Type *base, periph_handle_t *h, periph_xfer_t *x);
void     PERIPH_HandleIRQ(PERIPH_Type *base, periph_handle_t *handle);
```

### Domain Rules
1. All register accesses: via `memory_map.h` — no inline hex addresses
2. All polling loops: timeout counter; return error code on timeout
3. All functions: return `status_t` — never `void` for operations
4. Thread safety: document per-driver; note mutex requirement if not safe
5. DMA: provide DMA variants for all high-bandwidth peripherals
6. Power management: `suspend()`/`resume()` hooks for low-power modes
7. Callbacks: callback function pointers for async completion

### Required Peripheral Coverage
| Peripheral | Key Tests |
|------------|-----------|
| UART | Baud rate, parity, TX/RX loopback, DMA |
| SPI | All 4 modes, master/slave loopback, DMA |
| I2C | 7/10-bit addressing, repeated start, DMA |
| GPIO | Input/output, pull resistors, edge interrupt |
| Timer | Periodic, one-shot, PWM, input capture |
| DMA | Channel config, completion callback, scatter-gather |
| Watchdog | Init, refresh (kick), triggered reset |

### QoR Metrics to Evaluate
- All peripheral loopback tests: PASS
- DMA transfers: correct data at correct address
- No infinite loops — all error paths return timeout status
- All error paths return meaningful status codes

### Output Required
- Driver source files (.c/.h per peripheral)
- Driver unit test suite
- Driver API documentation (Doxygen-compatible)

---

## Stage: rtos_integration

### FreeRTOS Domain Rules
1. Port layer: implement `portmacro.h` for target architecture
2. Tick timer: hardware timer for RTOS tick (default 1 ms)
3. Context switch: implement SVC and PendSV handlers or equivalent
4. Heap: use `heap_4.c` (best-fit with coalescence)
5. Stack sizing: profile with `uxTaskGetStackHighWaterMark()`; add 20% margin
6. `configCHECK_FOR_STACK_OVERFLOW`: set to 2 during development
7. Priority inversion: use mutexes with priority inheritance

### RTOS-Aware Driver Rules
1. Replace busy-wait with semaphore pend (ISR gives semaphore on completion)
2. Shared peripheral: wrap with mutex; document max hold time
3. DMA + RTOS: event flags or semaphore for DMA completion from ISR
4. NEVER call non-`FromISR` FreeRTOS API from within ISR

### QoR Metrics to Evaluate
- RTOS boots: idle task runs; tick at correct rate
- All tasks: created, scheduled, running
- No stack overflow in 24-hour stress test
- No deadlocks under concurrent peripheral access

### Output Required
- RTOS port layer files (if custom architecture)
- `FreeRTOSConfig.h` configured for target
- Multi-task integration test

---

## Stage: driver_validation

### Validation Tiers
| Level | Tests | Environment |
|-------|-------|-------------|
| Unit | Peripheral loopback | Bare-metal on HW |
| Integration | Multi-peripheral DMA chains | RTOS on HW |
| System | Full application scenario | RTOS on HW |
| Stress | 24-hour high-throughput | Overnight on HW |

### QoR Metrics to Evaluate
- All peripheral driver tests: 100% PASS
- Stress test: 24-hour run with 0 failures
- No memory corruption (stack watermark stable)
- Throughput: within 10% of theoretical maximum

### Output Required
- Test results report
- Performance measurements
- Known limitations with workarounds

---

## Stage: system_integration

### Domain Rules
1. All drivers must pass unit validation first
2. Multi-peripheral concurrency: simultaneous UART + SPI + DMA + timer
3. Power mode: enter/exit sleep; verify correct wake-up on each IRQ source
4. Reset: warm and cold reset; verify all peripherals re-initialise
5. Memory: full RAM walking-bit pattern test

### QoR Metrics to Evaluate
- System scenario: correct output vs golden reference
- No lockups or unexpected resets in 1-hour system run
- Power modes: current within 10% of spec
- Reset recovery: fully functional after warm and cold reset

### Output Required
- System integration test report
- Power consumption measurements
- Bug list (HW vs SW classification)

---

## Stage: firmware_signoff

### Sign-off Checklist
- [ ] All peripheral drivers: 100% unit test PASS
- [ ] RTOS: no stack overflow, no deadlock
- [ ] System integration test: PASS
- [ ] 24-hour stress test: clean
- [ ] Power modes: verified and measured
- [ ] Reset: warm and cold verified
- [ ] All P0/P1 bugs closed

### Output Required
- Validated firmware package
- Test results report
- Bring-up guide for silicon team
- Known issues list

---

## Memory

### Write on stage completion
After each stage completes (regardless of whether an orchestrator session is active),
write or overwrite one JSON record in `memory/firmware/experiences.jsonl` keyed by
`run_id`. This ensures data is persisted even if the flow is interrupted or called
without full orchestrator context.

Use `run_id` = `firmware_<YYYYMMDD>_<HHMMSS>` (set once at flow start; reuse on each
stage update). Set `signoff_achieved: false` until the final sign-off stage completes.
### Run state (write before first stage, update after each stage)
Write `memory/firmware/run_state.md` as the **first action** before launching any tool:
```markdown
run_id:      firmware_<YYYYMMDD>_<HHMMSS>
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
applied fix as an observation to entity `chip-design-firmware-fixes` after writing to
`experiences.jsonl`. Skip silently if the tool is absent — JSONL is the canonical record.
