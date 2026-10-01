# Embedded Firmware & Device Driver Development Flow
## Orchestrator + Stage Agents + Skills

> **Purpose**: AI-driven flow for developing firmware and device drivers that run on or interface with the designed chip. Covers BSP development, peripheral drivers, RTOS integration, and firmware validation.

---

## 1. Shared State Object

```json
{
  "run_id": "firmware_001",
  "chip_name": "my_soc",
  "inputs": {
    "chip_datasheet":    "path/to/datasheet.pdf",
    "memory_map":        "path/to/memory_map.md",
    "peripheral_list":   ["UART", "SPI", "I2C", "GPIO", "DMA", "Timer", "Ethernet"],
    "rtos":              "FreeRTOS | Zephyr | bare-metal",
    "toolchain":         "arm-none-eabi-gcc | custom_toolchain",
    "target_hw":         "FPGA_prototype | Silicon",
    "language":          "C | C++"
  },
  "stages": {
    "bsp_development":    { "status": "pending", "output": {} },
    "peripheral_drivers": { "status": "pending", "output": {} },
    "rtos_integration":   { "status": "pending", "output": {} },
    "driver_validation":  { "status": "pending", "output": {} },
    "system_integration": { "status": "pending", "output": {} },
    "firmware_signoff":   { "status": "pending", "output": {} }
  },
  "drivers_complete": [],
  "test_results": {},
  "flow_status": "not_started"
}
```

---

## 2. Stage Sequence

```text
bsp_development → peripheral_drivers → rtos_integration → driver_validation → system_integration → firmware_signoff
```

Loop-back rules — the target stage, the iteration cap, and which failures escalate
instead of looping — are in `## Loop-Back Rules` of [`firmware-orchestrator.md`](../plugins/firmware/agents/firmware-orchestrator.md). That file is
authoritative; this document does not restate them.

---

## 3. Skill File Specifications

### 3.1 `sv-fw-bsp/SKILL.md`

```markdown
# Skill: Firmware — Board Support Package (BSP) Development

## Purpose
Create the hardware abstraction layer that enables firmware to
boot and initialize the chip from reset.

## BSP Components
1. Startup code (crt0.S / startup.c):
   - Set stack pointer
   - Initialize .data section (copy from flash to RAM)
   - Zero .bss section
   - Call SystemInit()
   - Branch to main()

2. System initialization (SystemInit):
   - Configure PLLs / clock tree
   - Configure memory (flash wait states, DRAM init)
   - Disable watchdog if safe at startup
   - Enable caches (I-cache, D-cache) if present

3. Interrupt controller (NVIC / PLIC / custom):
   - Vector table definition
   - IRQ enable/disable primitives
   - Priority configuration API
   - ISR registration mechanism

4. Memory map header (memory_map.h):
   - All peripheral base addresses as #defines
   - Register offset definitions
   - Bit field definitions (prefer struct/union or masks)

5. Linker scripts:
   - Boot region, code region, data region, stack, heap

## Coding Standards for BSP
1. Volatile: all hardware register accesses must use volatile pointer
2. Atomic: read-modify-write on hardware registers: disable IRQ or use atomic ops
3. Barriers: use memory barriers (DMB/DSB) around hardware access sequences
4. No OS calls in BSP: BSP must be RTOS-agnostic

## QoR Metrics
- Boot: chip reaches main() within expected time
- Clock: all PLLs locked, peripherals clocked correctly
- Interrupts: vector table valid, default handler in place
- Memory: .data and .bss correctly initialized

## Output Required
- startup.S and system_init.c
- memory_map.h (complete register definitions)
- Linker scripts
- BSP build system (Makefile or CMakeLists.txt)
```

---

### 3.2 `sv-fw-drivers/SKILL.md`

```markdown
# Skill: Firmware — Peripheral Driver Development

## Purpose
Implement clean, tested, reusable device drivers for all chip peripherals.

## Driver Architecture Pattern (HAL-style)
```c
// Initialization
status_t UART_Init(UART_Type *base, const uart_config_t *config);

// Data transfer (polling)
status_t UART_WriteBlocking(UART_Type *base, const uint8_t *data, size_t len);
status_t UART_ReadBlocking(UART_Type *base, uint8_t *data, size_t len);

// Data transfer (interrupt-driven)
status_t UART_TransferSendNonBlocking(UART_Type *base, uart_handle_t *handle,
                                       uart_transfer_t *xfer);

// ISR (called from vector table)
void UART_TransferHandleIRQ(UART_Type *base, uart_handle_t *handle);
```

## Driver Development Rules
1. All register access: via memory_map.h definitions (no magic numbers)
2. Timeout: all polling loops have timeout; return error on timeout
3. Error handling: return status codes (not void); define status_t enum
4. Thread safety: document whether driver is thread-safe; if not, note lock requirement
5. DMA integration: provide DMA-based transfer variants for high-bandwidth peripherals
6. Power management: implement suspend/resume hooks for low-power modes
7. Callback pattern: use callbacks for async completion notification

## Driver Test Pattern (bare-metal)
- Loopback tests: UART TX→RX, SPI master→slave loopback
- DMA tests: verify buffer contents after DMA transfer
- Interrupt tests: verify callback fires on correct event
- Error injection: force error conditions, verify error handling

## Standard Peripheral Driver Checklist
- [ ] UART: init, send, receive, baud rate, parity, flow control
- [ ] SPI: master/slave, all modes (CPOL/CPHA), DMA
- [ ] I2C: master/slave, 7/10-bit addressing, repeated start
- [ ] GPIO: input/output, pull up/down, interrupt on edge
- [ ] Timer: periodic, one-shot, PWM output, input capture
- [ ] DMA: channel config, scatter-gather, completion callback
- [ ] Watchdog: init, refresh, triggered reset test
- [ ] Ethernet: MAC init, DMA descriptors, PHY init (MDIO)

## Output Required
- Driver source files (one .c/.h pair per peripheral)
- Driver test suite
- Driver API documentation (Doxygen-compatible)
```

---

### 3.3 `sv-fw-rtos/SKILL.md`

```markdown
# Skill: Firmware — RTOS Integration

## Purpose
Integrate an RTOS (FreeRTOS, Zephyr, or similar) with the BSP
and peripheral drivers for multi-tasking firmware.

## FreeRTOS Integration Steps
1. Port layer: implement portmacro.h for target architecture
2. Tick timer: configure hardware timer for RTOS tick (typ. 1ms)
3. Context switch: implement PendSV/SVC handlers (or equivalent)
4. Heap: select heap scheme (heap_4 for most embedded use cases)
5. Stack sizing: size each task stack (use uxTaskGetStackHighWaterMark)
6. Interrupt nesting: configure BASEPRI or equivalent for IRQ masking

## RTOS-Aware Driver Requirements
1. Blocking calls: use RTOS semaphore/queue instead of busy-wait
2. ISR-to-task notification: use xSemaphoreGiveFromISR() pattern
3. Mutual exclusion: use mutex for shared peripheral access
4. DMA + RTOS: use event flags for DMA completion notification
5. No FreeRTOS API calls from within ISR unless FromISR variant

## Common RTOS Integration Bugs
- Stack overflow: set configCHECK_FOR_STACK_OVERFLOW = 2
- Priority inversion: use mutex with priority inheritance
- ISR calling non-ISR API: linker/assert catch in debug builds
- Tick timer wrong frequency: verify with logic analyzer

## QoR Metrics
- RTOS boots: idle task runs, tick fires at correct rate
- Task creation: all application tasks created and running
- No stack overflow detected in stress test
- Driver + RTOS: no deadlocks under concurrent access

## Output Required
- RTOS port layer files (if custom target)
- FreeRTOSConfig.h / prj.conf (configured for target)
- RTOS integration test (multi-task producer-consumer)
```

---

### 3.4 `sv-fw-validation/SKILL.md`

```markdown
# Skill: Firmware — Validation and System Testing

## Purpose
Validate that firmware correctly controls all chip peripherals
and meets system-level functional requirements.

## Validation Strategy
| Level            | What it tests                              | Environment       |
|------------------|--------------------------------------------|-------------------|
| Unit (driver)    | Individual peripheral, loopback            | Bare-metal on HW  |
| Integration      | Multiple peripherals together              | RTOS on HW        |
| System           | Full application scenario                  | RTOS on HW        |
| Stress           | Long-run, high-throughput, corner cases    | Overnight on HW   |
| Power            | Verify low-power modes, wake-up            | HW + power meter  |

## Automated Testing Framework
1. Unity or CppUTest: C unit test framework for driver tests
2. Test runner: Python script controls target via UART/JTAG
3. Pass/fail: target sends PASS/FAIL over UART; host logs result
4. CI integration: run on every commit via FPGA farm or emulator

## Performance Validation
- UART: verify throughput at maximum baud rate
- SPI: verify throughput at maximum clock
- DMA: verify transfer rate matches theoretical (memcpy benchmark)
- Interrupt latency: measure IRQ-to-ISR entry time

## QoR Metrics
- All peripheral driver tests: 100% pass
- System integration tests: 100% pass
- Stress test: 24hr run with 0 failures
- Performance: within 10% of theoretical limits

## Output Required
- Test results report (per peripheral, per scenario)
- Performance measurements
- Any known limitations with workarounds
```

---

## 4. Orchestrator System Prompt

The orchestrator's system prompt is its agent definition, [`firmware-orchestrator.md`](../plugins/firmware/agents/firmware-orchestrator.md): stage
sequence, loop-back rules, stage gating and escalation. This document does not
restate it.
