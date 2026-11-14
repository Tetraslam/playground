; =============================================================================
; rtosaurus kernel (agent 6): vectors, preemptive priority scheduler, syscalls,
; message queues, fault + watchdog handling. T16 assembly, see rtosaurus/isa.py.
;
; Context frame on a task's stack (saved_sp points at r6):
;   +0 r6  +1 r5  +2 r4  +3 r3  +4 r2  +5 r1  +6 r0  +7 flags  +8 pc
; (the CPU pushes pc then flags on exception entry; ISRs push r0..r6.)
; After saving the frame, every handler switches to the private kernel stack,
; so a task only needs ~10 words of headroom for interrupts (K_HEADROOM is
; added to each task's stack_words automatically).
;
; Kernel labels are all k_* (plus `reset`). The app provides app_init and
; task_table (see PLAN.md).
; =============================================================================

.equ K_STACK_TOP,   RAM_TOP + 1      ; first PUSH lands on RAM_TOP
.equ K_STACK_WORDS, 64
.equ K_HEADROOM,    12
.equ K_IDLE_WORDS,  4
.equ K_NTASKS,      9                ; 8 app + idle
.equ K_IDLE,        8
.equ K_TCB_WORDS,   6
.equ K_QWORDS,      10               ; head, count, buf[8]
.equ K_QDEPTH,      8
.equ K_TICK_CYCLES, 1000             ; 100 Hz at CLOCK_HZ = 100 kHz

; TCB fields
.equ T_STATE, 0
.equ T_PRIO,  1
.equ T_SP,    2
.equ T_WAKE,  3                      ; wake tick when sleeping, queue id when blocked
.equ T_ENTRY, 4
.equ T_FAULTS, 5

; task states
.equ S_FREE,  0
.equ S_READY, 1
.equ S_RUN,   2
.equ S_SLEEP, 3
.equ S_BSEND, 4
.equ S_BRECV, 5
.equ S_DEAD,  6

; frame offsets from saved_sp
.equ F_R0, 6
.equ F_PC, 8

; ---- vector table -------------------------------------------------------------
.org 0
.word reset          ; 0 reset
.word k_trap         ; 1 TRAP (syscalls)
.word k_timer        ; 2 timer tick
.word k_uart         ; 3 uart rx
.word k_ignore       ; 4 gpio (unused by the kernel; poll MMIO_GPIO_IN)
.word k_fault        ; 5 fault
.word k_wdog         ; 6 watchdog
.word k_ignore, k_ignore, k_ignore, k_ignore, k_ignore, k_ignore, k_ignore, k_ignore, k_ignore

.org CODE_BASE

; ---- reset ----------------------------------------------------------------------
reset:
        DI
        LDI sp, K_STACK_TOP
        LDI r0, 0
        ST [MMIO_TIMER_CTRL], r0
        ST [MMIO_UART_CTRL], r0
        ST [MMIO_GPIO_IRQEN], r0
        ST [MMIO_PWM_HEATER], r0        ; fail safe: heater off until the app decides
        ST [MMIO_WDOG_KICK], r0         ; restart any running watchdog countdown

        ; zero all kernel data (matters after a watchdog restart)
        LDI r1, k_data
k_zero_loop:
        ST [r1], r0
        ADDI r1, 1
        CMPI r1, k_data_end
        JNZ k_zero_loop
        LDI r0, K_IDLE
        ST [k_current], r0
        LDI r0, 1
        ST [k_in_kernel], r0
        LD r0, [k_boots]
        ADDI r0, 1
        ST [k_boots], r0

        LDI r1, k_msg_boot
        CALL k_puts

        CALL app_init

        ; build TCBs from task_table: entry, priority, stack_words; 0-terminated
        LDI r1, task_table
        LDI r2, 0
        LDI r3, K_STACK_TOP - K_STACK_WORDS
k_build:
        LD r4, [r1]
        CMPI r4, 0
        JZ k_build_idle
        CMPI r2, K_IDLE
        JGE k_build_idle
        LD r5, [r1+1]
        LD r6, [r1+2]
        CALL k_mktask
        ADDI r1, 3
        ADDI r2, 1
        JMP k_build
k_build_idle:
        LDI r2, K_IDLE
        LDI r4, k_idle
        LDI r5, 0
        LDI r6, K_IDLE_WORDS
        CALL k_mktask
        ST [k_stack_low], r3

        LDI r0, K_TICK_CYCLES
        ST [MMIO_TIMER_PERIOD], r0
        LDI r0, 1
        ST [MMIO_TIMER_CTRL], r0
        ST [MMIO_UART_CTRL], r0

        LDI r1, 0
        CALL k_pick
        JMP k_switch                    ; IRET into the first task sets I

; k_mktask: r2 = index, r3 = stack top, r4 = entry, r5 = priority, r6 = stack words
; returns r3 = next stack top. clobbers r0.
k_mktask:
        PUSH r1
        LDI r1, K_TCB_WORDS
        MUL r1, r2
        ADDI r1, k_tcb
        LDI r0, S_READY
        ST [r1+T_STATE], r0
        ST [r1+T_PRIO], r5
        ST [r1+T_ENTRY], r4
        LDI r0, 0
        ST [r1+T_WAKE], r0
        ST [r1+T_FAULTS], r0
        ; initial frame: returning from entry lands in k_task_exit
        LDI r0, k_task_exit
        ST [r3-1], r0
        ST [r3-2], r4                   ; pc
        LDI r0, FLAG_I
        ST [r3-3], r0                   ; flags
        LDI r0, 0
        ST [r3-4], r0                   ; r0
        ST [r3-5], r0
        ST [r3-6], r0
        ST [r3-7], r0
        ST [r3-8], r0
        ST [r3-9], r0
        ST [r3-10], r0                  ; r6
        MOV r0, r3
        ADDI r0, -10
        ST [r1+T_SP], r0
        SUB r3, r6
        ADDI r3, -K_HEADROOM
        POP r1
        RET

; ---- idle + task exit -------------------------------------------------------------
k_idle:
        NOP
        JMP k_idle

k_task_exit:
        LDI r0, 6
        TRAP 0
        JMP k_task_exit

; ---- common entry / exit ---------------------------------------------------------
; Every handler: PUSH r0..r6, MOV r6, sp, CALL k_enter.
; k_enter saves r6 (the frame) into the current TCB, returns r5 = TCB pointer,
; and moves onto the kernel stack. Clobbers r0, r4.
k_enter:
        POP r4                          ; our return address (sp == frame again)
        LD r5, [k_current]
        CMPI r5, K_NTASKS
        JNC k_panic                     ; corrupted k_current
        LDI r0, K_TCB_WORDS
        MUL r5, r0
        ADDI r5, k_tcb
        ST [r5+T_SP], r6
        LDI r0, 1
        ST [k_in_kernel], r0
        LDI sp, K_STACK_TOP
        JR r4, 0

; round robin: pick starting after the current task (equal priority rotates)
k_resched_rr:
        LD r1, [k_current]
        ADDI r1, 1
        CMPI r1, K_NTASKS
        JLT k_rr_ok
        LDI r1, 0
k_rr_ok:
        CALL k_pick
        JMP k_switch

; keep: the current task wins ties (only a strictly higher priority preempts)
k_resched_keep:
        LD r1, [k_current]
        CALL k_pick
        ; fall through

; k_resume: return to the current task untouched (no scheduling decision needed).
k_resume:
        LD r1, [k_current]
        LDI r0, K_TCB_WORDS
        MUL r1, r0
        ADDI r1, k_tcb
        LDI r0, 0
        ST [k_in_kernel], r0
        LD sp, [r1+T_SP]
        POP r6
        POP r5
        POP r4
        POP r3
        POP r2
        POP r1
        POP r0
        IRET

; k_resched_woke: resume directly unless k_wake just readied someone.
k_resched_woke:
        LD r0, [k_woke]
        CMPI r0, 0
        JZ k_resume
        JMP k_resched_keep

; k_switch: r0 = task to run. Demotes the old task, restores the new frame, IRETs.
k_switch:
        LD r1, [k_current]
        CMPI r1, K_NTASKS
        JNC k_panic                     ; corrupted k_current
        LDI r2, K_TCB_WORDS
        MUL r1, r2
        ADDI r1, k_tcb
        LD r3, [r1+T_STATE]
        CMPI r3, S_RUN
        JNZ k_sw_new
        LDI r3, S_READY
        ST [r1+T_STATE], r3
k_sw_new:
        ST [k_current], r0
        LDI r1, K_TCB_WORDS
        MUL r1, r0
        ADDI r1, k_tcb
        LDI r3, S_RUN
        ST [r1+T_STATE], r3
        LD r3, [k_switches]
        ADDI r3, 1
        ST [k_switches], r3
        LDI r3, 0
        ST [k_in_kernel], r3
        LD sp, [r1+T_SP]
        POP r6
        POP r5
        POP r4
        POP r3
        POP r2
        POP r1
        POP r0
        IRET

; k_pick: r1 = start index. Returns r0 = highest-priority ready/running task,
; first in rotation order from r1 on ties. Idle (always ready) is the fallback.
; clobbers r1..r5.
k_pick:
        LDI r0, K_IDLE
        LDI r2, -32768                  ; best priority so far
        LDI r3, K_NTASKS
k_pick_loop:
        LDI r4, K_TCB_WORDS
        MUL r4, r1
        ADDI r4, k_tcb
        LD r5, [r4+T_STATE]
        CMPI r5, S_READY
        JZ k_pick_cand
        CMPI r5, S_RUN
        JNZ k_pick_next
k_pick_cand:
        LD r5, [r4+T_PRIO]
        CMP r5, r2
        JLE k_pick_next
        MOV r2, r5
        MOV r0, r1
k_pick_next:
        ADDI r1, 1
        CMPI r1, K_NTASKS
        JLT k_pick_wrap
        LDI r1, 0
k_pick_wrap:
        ADDI r3, -1
        JNZ k_pick_loop
        RET

; k_wake: r1 = queue, r2 = blocked state. Every task blocked on that queue in
; that state becomes ready (it re-executes its TRAP); k_woke = 1 if any did.
; clobbers r0, r3, r4.
k_wake:
        LDI r3, 0
        ST [k_woke], r3
        LDI r3, k_tcb
        LDI r4, K_NTASKS
k_wake_loop:
        LD r0, [r3+T_STATE]
        CMP r0, r2
        JNZ k_wake_next
        LD r0, [r3+T_WAKE]
        CMP r0, r1
        JNZ k_wake_next
        LDI r0, S_READY
        ST [r3+T_STATE], r0
        ST [k_woke], r0
k_wake_next:
        ADDI r3, K_TCB_WORDS
        ADDI r4, -1
        JNZ k_wake_loop
        RET

; ---- timer tick --------------------------------------------------------------------
k_timer:
        PUSH r0
        PUSH r1
        PUSH r2
        PUSH r3
        PUSH r4
        PUSH r5
        PUSH r6
        MOV r6, sp
        CALL k_enter
        LD r1, [k_ticks]
        ADDI r1, 1
        ST [k_ticks], r1
        ; wake sleepers whose wake tick has passed (wraparound-safe)
        LDI r3, k_tcb
        LDI r4, K_NTASKS
k_tm_loop:
        LD r0, [r3+T_STATE]
        CMPI r0, S_SLEEP
        JNZ k_tm_next
        MOV r2, r1
        LD r0, [r3+T_WAKE]
        SUB r2, r0
        CMPI r2, 0
        JLT k_tm_next
        LDI r0, S_READY
        ST [r3+T_STATE], r0
k_tm_next:
        ADDI r3, K_TCB_WORDS
        ADDI r4, -1
        JNZ k_tm_loop
        JMP k_resched_rr

; ---- uart rx: move bytes from the bus fifo into queue 7 ---------------------------
; Bytes are never dropped: when queue 7 is full the rx irq is masked (it is
; level-triggered, so leaving it on would re-enter forever) and the rest wait in
; the bus fifo. recv(7) refills the queue from the fifo and unmasks the irq.
k_uart:
        PUSH r0
        PUSH r1
        PUSH r2
        PUSH r3
        PUSH r4
        PUSH r5
        PUSH r6
        MOV r6, sp
        CALL k_enter
        CALL k_ua_fill
        LDI r1, 7
        LDI r2, S_BRECV
        CALL k_wake
        JMP k_resched_woke

; k_ua_fill: fifo -> queue 7 until one is full/empty; sets the rx irq mask.
; clobbers r0..r4.
k_ua_fill:
        LDI r3, k_queues + 7 * K_QWORDS
k_uf_loop:
        LD r4, [r3+1]
        CMPI r4, K_QDEPTH
        JNC k_uf_full
        LD r0, [MMIO_UART_STATUS]
        LDI r1, 1
        AND r0, r1
        JZ k_uf_on
        LD r2, [MMIO_UART_RX]
        LD r0, [r3]
        ADD r0, r4
        LDI r1, K_QDEPTH - 1
        AND r0, r1
        ADD r0, r3
        ST [r0+2], r2
        ADDI r4, 1
        ST [r3+1], r4
        JMP k_uf_loop
k_uf_full:
        LDI r0, 0
        ST [MMIO_UART_CTRL], r0
        RET
k_uf_on:
        LDI r0, 1
        ST [MMIO_UART_CTRL], r0
        RET

; ---- spurious / unused vectors ---------------------------------------------------------
k_ignore:
        IRET

; ---- syscalls -----------------------------------------------------------------------------
; r0 = number, r1/r2 = args. Result is written into the frame's r0 slot.
k_trap:
        PUSH r0
        PUSH r1
        PUSH r2
        PUSH r3
        PUSH r4
        PUSH r5
        PUSH r6
        MOV r6, sp
        CALL k_enter                    ; r5 = tcb, r6 = frame; r1, r2 untouched
        LD r0, [r6+F_R0]
        CMPI r0, 8
        JNC k_sys_bad
        LD r3, [r0+k_sys_table]
        JR r3, 0

k_sys_table:
        .word k_sys_yield, k_sys_sleep, k_sys_ticks, k_sys_putc
        .word k_sys_send, k_sys_recv, k_sys_exit, k_sys_task_id

k_sys_bad:
        LDI r0, 0xFFFF
        ST [r6+F_R0], r0
        JMP k_resume

k_sys_yield:
        JMP k_resched_rr

k_sys_sleep:
        CMPI r1, 0
        JZ k_resched_rr
        LD r0, [k_ticks]
        ADD r0, r1
        ST [r5+T_WAKE], r0
        LDI r0, S_SLEEP
        ST [r5+T_STATE], r0
        JMP k_resched_rr

k_sys_ticks:
        LD r0, [k_ticks]
        ST [r6+F_R0], r0
        JMP k_resume

k_sys_putc:
        ST [MMIO_UART_TX], r1
        JMP k_resume

k_sys_task_id:
        LD r0, [k_current]
        ST [r6+F_R0], r0
        JMP k_resume

k_sys_exit:
        LDI r0, S_DEAD
        ST [r5+T_STATE], r0
        JMP k_resched_rr

k_sys_send:
        CMPI r1, 8
        JNC k_sys_bad
        LDI r3, K_QWORDS
        MUL r3, r1
        ADDI r3, k_queues
        LD r4, [r3+1]
        CMPI r4, K_QDEPTH
        JNC k_block_send
        LD r0, [r3]
        ADD r0, r4
        LDI r4, K_QDEPTH - 1
        AND r0, r4
        ADD r0, r3
        ST [r0+2], r2
        LD r4, [r3+1]
        ADDI r4, 1
        ST [r3+1], r4
        LDI r0, 0
        ST [r6+F_R0], r0
        LDI r2, S_BRECV
        CALL k_wake
        JMP k_resched_woke
k_block_send:
        LDI r0, S_BSEND
        JMP k_block

k_sys_recv:
        CMPI r1, 8
        JNC k_sys_bad
        LDI r3, K_QWORDS
        MUL r3, r1
        ADDI r3, k_queues
        LD r4, [r3+1]
        CMPI r4, 0
        JZ k_block_recv
        LD r0, [r3]
        ADD r0, r3
        LD r0, [r0+2]
        ST [r6+F_R0], r0
        LD r0, [r3]
        ADDI r0, 1
        LDI r2, K_QDEPTH - 1
        AND r0, r2
        ST [r3], r0
        ADDI r4, -1
        ST [r3+1], r4
        CMPI r1, 7
        JNZ k_recv_wake
        CALL k_ua_fill                  ; room again: pull waiting uart bytes
        LDI r1, 7
k_recv_wake:
        LDI r2, S_BSEND
        CALL k_wake
        JMP k_resched_woke
k_block_recv:
        LDI r0, S_BRECV
        ; fall through

; k_block: r0 = blocked state, r1 = queue. Rewind pc onto the TRAP so the task
; retries the syscall when woken.
k_block:
        ST [r5+T_STATE], r0
        ST [r5+T_WAKE], r1
        LD r0, [r6+F_PC]
        ADDI r0, -2
        ST [r6+F_PC], r0
        JMP k_resched_rr

; ---- faults -------------------------------------------------------------------------------
; A faulting task is killed; its context is discarded. A fault inside the kernel
; or the idle task is unrecoverable: report and HALT.
k_fault:
        LDI sp, K_STACK_TOP
        LD r0, [k_in_kernel]
        CMPI r0, 0
        JNZ k_panic
        LD r1, [k_current]
        CMPI r1, K_IDLE
        JNC k_panic
        LDI r0, 1
        ST [k_in_kernel], r0
        LDI r5, K_TCB_WORDS
        MUL r5, r1
        ADDI r5, k_tcb
        LDI r0, S_DEAD
        ST [r5+T_STATE], r0
        LD r0, [r5+T_FAULTS]
        ADDI r0, 1
        ST [r5+T_FAULTS], r0
        LD r0, [k_faults]
        ADDI r0, 1
        ST [k_faults], r0
        CALL k_print_fault
        JMP k_resched_rr

k_panic:
        LDI sp, K_STACK_TOP
        LD r1, [k_current]
        CALL k_print_fault
        LDI r1, k_msg_panic
        CALL k_puts
        HALT
        JMP k_panic

; prints "!fault t<id> c<cause> pc<faultpc>\n"  (r1 = task id, hex fields)
k_print_fault:
        PUSH r1
        LDI r1, k_msg_fault
        CALL k_puts
        POP r1
        LDI r2, 1
        CALL k_puthex
        LDI r1, k_msg_c
        CALL k_puts
        LD r1, [MMIO_CAUSE]
        LDI r2, 2
        CALL k_puthex
        LDI r1, k_msg_pc
        CALL k_puts
        LD r1, [MMIO_FAULTPC]
        LDI r2, 4
        CALL k_puthex
        LDI r1, 10
        ST [MMIO_UART_TX], r1
        RET

; ---- watchdog: report and restart the whole firmware -------------------------------------------
k_wdog:
        LDI sp, K_STACK_TOP
        LDI r1, k_msg_wdog
        CALL k_puts
        JMP reset

; ---- kernel print helpers (direct UART, kernel context only) ------------------------------------
; k_puts: r1 = 0-terminated string. clobbers r0, r1.
k_puts:
        LD r0, [r1]
        CMPI r0, 0
        JZ k_puts_end
        ST [MMIO_UART_TX], r0
        ADDI r1, 1
        JMP k_puts
k_puts_end:
        RET

; k_puthex: r1 = value, r2 = digits (1..4). clobbers r0..r3.
k_puthex:
        MOV r3, r2
        ADDI r3, -1
        LDI r0, 2
        SHL r3, r0                      ; shift = (digits-1)*4
k_ph_loop:
        MOV r0, r1
        SHR r0, r3
        LDI r2, 15
        AND r0, r2
        LD r0, [r0+k_hexdigits]
        ST [MMIO_UART_TX], r0
        ADDI r3, -4
        JGE k_ph_loop
        RET

k_hexdigits: .string "0123456789abcdef"
k_msg_boot:  .string "!boot\n"
k_msg_fault: .string "!fault t"
k_msg_c:     .string " c"
k_msg_pc:    .string " pc"
k_msg_wdog:  .string "!wdog\n"
k_msg_panic: .string "!panic\n"

; ---- kernel data -----------------------------------------------------------------------------
k_boots:      .word 0                   ; survives watchdog restarts (not in k_data)
k_data:
k_current:    .word 0
k_ticks:      .word 0
k_in_kernel:  .word 0
k_switches:   .word 0
k_faults:     .word 0
k_uart_drops: .word 0                   ; kept for compatibility; rx no longer drops
k_woke:       .word 0
k_stack_low:  .word 0                   ; lowest task stack address handed out
k_tcb:        .zero K_NTASKS * K_TCB_WORDS
k_queues:     .zero 8 * K_QWORDS
k_data_end:
