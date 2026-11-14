; lib.s -- syscall wrappers, print helpers, parsers, print lock (owner: agent 7)
;
; Calling convention for every lib_* routine: arguments in r1..r3, result in
; r0. All routines preserve r1..r6 (r0 is scratch). Stack use is small (< 20
; words including nested calls), so a 32-word task stack is plenty.

.equ LIB_SYS_YIELD, 0
.equ LIB_SYS_SLEEP, 1
.equ LIB_SYS_TICKS, 2
.equ LIB_SYS_PUTC, 3
.equ LIB_SYS_SEND, 4
.equ LIB_SYS_RECV, 5
.equ LIB_SYS_EXIT, 6
.equ LIB_SYS_TASKID, 7

.equ LIB_TCB_WORDS, 6
.equ LIB_ST_FREE, 0
.equ LIB_ST_DEAD, 6
.equ LIB_PARSE_ERR, 0x8000     ; parse failure sentinel (-32768)

; ---- syscall wrappers ---------------------------------------------------

lib_yield:
    LDI r0, LIB_SYS_YIELD
    TRAP 0
    RET

lib_sleep:                      ; r1 = ticks
    LDI r0, LIB_SYS_SLEEP
    TRAP 0
    RET

lib_ticks:                      ; -> r0 = kernel tick count
    LDI r0, LIB_SYS_TICKS
    TRAP 0
    RET

lib_putc:                       ; r1 = char
    LDI r0, LIB_SYS_PUTC
    TRAP 0
    RET

lib_send:                       ; r1 = queue, r2 = value (blocks while full)
    LDI r0, LIB_SYS_SEND
    TRAP 0
    RET

lib_recv:                       ; r1 = queue -> r0 = value (blocks while empty)
    LDI r0, LIB_SYS_RECV
    TRAP 0
    RET

lib_exit:
    LDI r0, LIB_SYS_EXIT
    TRAP 0
    RET

lib_task_id:                    ; -> r0 = own task index
    LDI r0, LIB_SYS_TASKID
    TRAP 0
    RET

; ---- init / print lock --------------------------------------------------
; A cooperative mutex so lines from different tasks don't interleave. The
; owner is stored as task_id + 1. A waiter steals the lock if the owner is
; dead or freed (a task that faults mid-line must not wedge the console).
; Only use it from tasks of EQUAL priority (yield-spin would livelock a
; higher-priority waiter); time-critical tasks should never print.

lib_init:                       ; call from app_init (RAM is not re-zeroed on reset)
    LDI r0, 0
    ST [lib_lock_owner], r0
    RET

lib_lock:
    PUSH r1
    PUSH r2
    PUSH r3
    CALL lib_task_id
    MOV r3, r0
    ADDI r3, 1                  ; r3 = my owner tag
lib_lock_retry:
    DI
    LD r1, [lib_lock_owner]
    CMPI r1, 0
    JZ lib_lock_take
    CMP r1, r3
    JZ lib_lock_take            ; re-entrant
    ADDI r1, -1
    LDI r2, LIB_TCB_WORDS
    MUL r1, r2
    LD r2, [r1+k_tcb]           ; owner's state
    CMPI r2, LIB_ST_DEAD
    JZ lib_lock_take
    CMPI r2, LIB_ST_FREE
    JZ lib_lock_take
    EI
    CALL lib_yield
    JMP lib_lock_retry
lib_lock_take:
    ST [lib_lock_owner], r3
    EI
    POP r3
    POP r2
    POP r1
    RET

lib_unlock:
    LDI r0, 0
    ST [lib_lock_owner], r0
    RET

lib_lock_owner:
    .word 0

; ---- printing -----------------------------------------------------------

lib_puts:                       ; r1 = address of 0-terminated string
    PUSH r1
    PUSH r2
    MOV r2, r1
lib_puts_loop:
    LD r1, [r2]
    CMPI r1, 0
    JZ lib_puts_done
    CALL lib_putc
    ADDI r2, 1
    JMP lib_puts_loop
lib_puts_done:
    POP r2
    POP r1
    RET

lib_newline:
    PUSH r1
    LDI r1, '\n'
    CALL lib_putc
    POP r1
    RET

lib_put_u16:                    ; r1 = unsigned value, printed in decimal
    PUSH r1
    PUSH r2
    PUSH r3
    PUSH r4
    MOV r2, r1                  ; r2 = remaining value
    LDI r4, 0                   ; r4 = digits pushed
lib_put_u16_div:
    MOV r3, r2
    LDI r0, 1
    SHR r3, r0                  ; v >> 1 is < 0x8000, so signed DIV is safe
    LDI r0, 5
    DIV r3, r0                  ; r3 = v / 10
    MOV r1, r3
    LDI r0, 10
    MUL r1, r0
    MOV r0, r2
    SUB r0, r1                  ; r0 = v % 10
    ADDI r0, '0'
    PUSH r0
    ADDI r4, 1
    MOV r2, r3
    CMPI r2, 0
    JNZ lib_put_u16_div
lib_put_u16_out:
    POP r1
    CALL lib_putc
    ADDI r4, -1
    JNZ lib_put_u16_out
    POP r4
    POP r3
    POP r2
    POP r1
    RET

lib_put_i16:                    ; r1 = signed value
    PUSH r1
    CMPI r1, 0
    JGE lib_put_i16_pos
    PUSH r1
    LDI r1, '-'
    CALL lib_putc
    POP r1
    NEG r1
lib_put_i16_pos:
    CALL lib_put_u16
    POP r1
    RET

lib_put_q88:                    ; r1 = signed Q8.8, printed as [-]I.FF (rounded)
    PUSH r1
    PUSH r2
    PUSH r3
    CMPI r1, 0
    JGE lib_put_q88_pos
    PUSH r1
    LDI r1, '-'
    CALL lib_putc
    POP r1
    NEG r1
lib_put_q88_pos:
    MOV r2, r1
    LDI r0, 8
    SHR r2, r0                  ; r2 = integer part
    LDI r0, 0xFF
    AND r1, r0
    LDI r0, 100
    MUL r1, r0
    ADDI r1, 128
    LDI r0, 8
    SHR r1, r0                  ; r1 = hundredths, 0..100
    CMPI r1, 100
    JNZ lib_put_q88_frac
    LDI r1, 0
    ADDI r2, 1
lib_put_q88_frac:
    MOV r3, r1
    MOV r1, r2
    CALL lib_put_u16
    LDI r1, '.'
    CALL lib_putc
    MOV r1, r3
    LDI r0, 10
    DIV r1, r0                  ; tens digit
    MOV r2, r1
    ADDI r1, '0'
    CALL lib_putc
    LDI r0, 10
    MUL r2, r0
    MOV r1, r3
    SUB r1, r2                  ; units digit
    ADDI r1, '0'
    CALL lib_putc
    POP r3
    POP r2
    POP r1
    RET

lib_put_hex4:                   ; r1 = value, printed as 4 lowercase hex digits
    PUSH r1
    PUSH r2
    PUSH r3
    MOV r2, r1
    LDI r3, 4
lib_put_hex4_loop:
    MOV r1, r2
    LDI r0, 12
    SHR r1, r0
    LDI r0, 4
    SHL r2, r0
    CMPI r1, 10
    JLT lib_put_hex4_dec
    ADDI r1, 'a' - 10
    JMP lib_put_hex4_emit
lib_put_hex4_dec:
    ADDI r1, '0'
lib_put_hex4_emit:
    CALL lib_putc
    ADDI r3, -1
    JNZ lib_put_hex4_loop
    POP r3
    POP r2
    POP r1
    RET

; ---- parsing ------------------------------------------------------------

lib_parse_int:                  ; r1 = string -> r0 = [-]digits, or LIB_PARSE_ERR
    PUSH r1                     ; whole string must be consumed; |value| <= 9999
    PUSH r2
    PUSH r3
    PUSH r4
    LDI r4, 0                   ; r4 = negative?
    LD r2, [r1]
    CMPI r2, '-'
    JNZ lib_parse_int_digits
    LDI r4, 1
    ADDI r1, 1
lib_parse_int_digits:
    CALL lib_parse_digits       ; r0 = value, r1 advanced, r2 = digit count
    CMPI r2, 0
    JZ lib_parse_int_err
    CMPI r0, 0
    JLT lib_parse_int_err       ; overflowed
    LD r3, [r1]
    CMPI r3, 0
    JNZ lib_parse_int_err       ; trailing junk
    CMPI r4, 0
    JZ lib_parse_int_done
    NEG r0
    JMP lib_parse_int_done
lib_parse_int_err:
    LDI r0, LIB_PARSE_ERR
lib_parse_int_done:
    POP r4
    POP r3
    POP r2
    POP r1
    RET

; internal: r1 = string. -> r0 = value of leading decimal digits (max 4
; digits, else r0 = -1), r1 advanced past them, r2 = digit count. Clobbers r3.
lib_parse_digits:
    LDI r0, 0
    LDI r2, 0
lib_parse_digits_loop:
    LD r3, [r1]
    CMPI r3, '0'
    JLT lib_parse_digits_end
    CMPI r3, '9'
    JGT lib_parse_digits_end
    CMPI r2, 4
    JGE lib_parse_digits_long
    ADDI r3, -48                ; - '0'
    PUSH r3
    LDI r3, 10
    MUL r0, r3
    POP r3
    ADD r0, r3
    ADDI r2, 1
    ADDI r1, 1
    JMP lib_parse_digits_loop
lib_parse_digits_long:
    LDI r0, -1
lib_parse_digits_end:
    RET

lib_parse_q88:                  ; r1 = "[-]I[.F[F]]" -> r0 = Q8.8, or LIB_PARSE_ERR
    PUSH r1                     ; integer part must be 0..127
    PUSH r2
    PUSH r3
    PUSH r4
    PUSH r5
    LDI r4, 0                   ; r4 = negative?
    LD r2, [r1]
    CMPI r2, '-'
    JNZ lib_parse_q88_int
    LDI r4, 1
    ADDI r1, 1
lib_parse_q88_int:
    CALL lib_parse_digits
    CMPI r2, 0
    JZ lib_parse_q88_err
    CMPI r0, 0
    JLT lib_parse_q88_err
    CMPI r0, 127
    JGT lib_parse_q88_err
    LDI r3, 8
    SHL r0, r3
    MOV r5, r0                  ; r5 = integer part in Q8.8
    LD r3, [r1]
    CMPI r3, 0
    JZ lib_parse_q88_sign
    CMPI r3, '.'
    JNZ lib_parse_q88_err
    ADDI r1, 1
    CALL lib_parse_digits       ; fraction digits
    CMPI r2, 1
    JLT lib_parse_q88_err
    CMPI r2, 2
    JGT lib_parse_q88_err
    JZ lib_parse_q88_hund
    LDI r3, 10                  ; one digit: tenths -> hundredths
    MUL r0, r3
lib_parse_q88_hund:
    LD r3, [r1]
    CMPI r3, 0
    JNZ lib_parse_q88_err
    LDI r3, 256
    MUL r0, r3                  ; <= 99*256, fits
    ADDI r0, 50
    LDI r3, 100
    DIV r0, r3                  ; round(hundredths * 256 / 100)
    ADD r5, r0
lib_parse_q88_sign:
    MOV r0, r5
    CMPI r4, 0
    JZ lib_parse_q88_done
    NEG r0
    JMP lib_parse_q88_done
lib_parse_q88_err:
    LDI r0, LIB_PARSE_ERR
lib_parse_q88_done:
    POP r5
    POP r4
    POP r3
    POP r2
    POP r1
    RET

; ---- misc ---------------------------------------------------------------

lib_clamp:                      ; r0 = clamp(r1, r2, r3)  (signed)
    MOV r0, r1
    CMP r0, r2
    JGE lib_clamp_hi
    MOV r0, r2
    RET
lib_clamp_hi:
    CMP r0, r3
    JLE lib_clamp_done
    MOV r0, r3
lib_clamp_done:
    RET
