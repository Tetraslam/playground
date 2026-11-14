; app.s -- the application: tank controller + friends (owner: agent 7)
;
; Tasks (index = order in task_table, higher priority wins):
;   0 monitor    p5  kicks the watchdog only while the control task is alive
;   1 control    p4  every 10 ticks: read sensor, sanity-check it, Q8.8 PID,
;                    drive heater + fan, telemetry on queue 0 once a second
;   2 logger     p2  prints "T=41.25 S=45.00 H=180 F=0" + "!event" lines
;   3 shell      p2  UART commands (see app_s_help)
;   4 heartbeat  p1  blinks LED0
;
; LEDs: 0 heartbeat, 1 fan on, 2 sensor fault, 7 overheat (> 90 C, heater off).
;
; Safety logic lives in the control task: a sensor that returns the exact same
; Q8.8 reading 15 times in a row (real readings carry ~0.08 C of noise) or an
; implausible value is declared failed -> heater off until it recovers. Over
; 90 C latches an overheat alarm (heater off, fan on) until it cools below 85 C.
; The time-critical tasks (monitor, control) never print or take locks; they
; raise event bits that the logger reports.
;
; PID, all Q8.8 with FMUL. e = setpoint - temp. With a gain g held as a plain
; integer, FMUL(e, g) = e_degC * g, so gains are in duty units:
;   P  = kp * e                     kp: duty per degC          (default 64)
;   I += ki * e per 0.1 s step      ki: duty/16 per degC*step   (default 240)
;   D  = kd * dT per step           kd: duty per degC/step      (default 0)
;   heater = clamp(P + I/16 - D, 0, 255)
; Anti-windup: conditional integration (skip when saturated in the direction
; of the error) plus a clamp of I to [0, 255*16].

.equ APP_CTL_PERIOD, 10         ; ticks between control steps (0.1 s)
.equ APP_TELEM_EVERY, 10        ; control steps per telemetry message (1 s)
.equ APP_MON_PERIOD, 20         ; ticks between watchdog checks (0.2 s)
.equ APP_HB_PERIOD, 50          ; heartbeat toggle (0.5 s)
.equ APP_WDOG_TIMEOUT, 196      ; *256 cycles ~ 0.5 s
.equ APP_STUCK_LIMIT, 15        ; identical readings before the sensor is failed

.equ APP_Q_TELEM, 0
.equ APP_Q_UART, 7
.equ APP_T_LOGGER, 2            ; task index of the logger (task_table order)
.equ APP_NUM_TCBS, 9
.equ APP_NUM_STATES, 7

.equ APP_HOT_Q, 90 * 256
.equ APP_COOL_Q, 85 * 256
.equ APP_TMAX_Q, 120 * 256      ; plausible sensor range
.equ APP_TMIN_Q, -20 * 256
.equ APP_SP_MAX_Q, 95 * 256
.equ APP_FAN_ON_Q, 3 * 256      ; fan on above setpoint + 3 C
.equ APP_FAN_OFF_Q, 1 * 256     ; ...off again below setpoint + 1 C
.equ APP_I_SHIFT, 4
.equ APP_I_MAX, 255 * 16
.equ APP_TERM_MAX, 1024         ; clamp on |P|, |D|, |dI|
.equ APP_GAIN_MAX, 4000

.equ APP_KP_DEFAULT, 64
.equ APP_KI_DEFAULT, 240
.equ APP_KD_DEFAULT, 0

.equ APP_LED_HB, 0x01
.equ APP_LED_FAN, 0x02
.equ APP_LED_SENSOR, 0x04
.equ APP_LED_HOT, 0x80

.equ APP_F_HOT, 1               ; app_flags bits
.equ APP_F_SENSOR, 2

.equ APP_EV_HOT, 1              ; app_events bits (control -> logger)
.equ APP_EV_COOL, 2
.equ APP_EV_SENSOR, 4
.equ APP_EV_SENSOR_OK, 8

.equ APP_LINE_MAX, 24

; ---- task table (kernel ABI) -----------------------------------------------

task_table:
    .word app_monitor, 5, 32
    .word app_control, 4, 48
    .word app_logger, 2, 64
    .word app_shell, 2, 64
    .word app_heartbeat, 1, 32
    .word 0

; ---- init (interrupts off, kernel stack) -----------------------------------

app_init:
    PUSH r1
    PUSH r2
    CALL lib_init
    LDI r1, app_vars
    LDI r2, 0
app_init_zero:
    ST [r1], r2
    ADDI r1, 1
    CMPI r1, app_vars_end
    JNZ app_init_zero
    LDI r1, APP_KP_DEFAULT
    ST [app_kp], r1
    LDI r1, APP_KI_DEFAULT
    ST [app_ki], r1
    LDI r1, APP_KD_DEFAULT
    ST [app_kd], r1
    ST [MMIO_PWM_HEATER], r2
    ST [MMIO_PWM_FAN], r2
    ST [MMIO_GPIO_OUT], r2
    LDI r1, APP_WDOG_TIMEOUT
    ST [MMIO_WDOG_TIMEOUT], r1
    ST [MMIO_WDOG_KICK], r1
    POP r2
    POP r1
    RET

; ---- small shared helpers (preserve r1..r6, arg in r3) ---------------------

app_ev:                         ; app_events |= r3
    DI
    LD r0, [app_events]
    OR r0, r3
    ST [app_events], r0
    EI
    RET

app_flag_set:                   ; app_flags |= r3
    LD r0, [app_flags]
    OR r0, r3
    ST [app_flags], r0
    RET

app_flag_clr:                   ; app_flags &= ~r3
    PUSH r3
    NOT r3
    LD r0, [app_flags]
    AND r0, r3
    ST [app_flags], r0
    POP r3
    RET

app_led_on:                     ; LEDs |= r3 (atomic RMW)
    DI
    LD r0, [MMIO_GPIO_OUT]
    OR r0, r3
    ST [MMIO_GPIO_OUT], r0
    EI
    RET

app_led_off:                    ; LEDs &= ~r3
    PUSH r3
    NOT r3
    DI
    LD r0, [MMIO_GPIO_OUT]
    AND r0, r3
    ST [MMIO_GPIO_OUT], r0
    EI
    POP r3
    RET

app_clamp_term:                 ; r0 = clamp(r0, -APP_TERM_MAX, APP_TERM_MAX)
    PUSH r1
    PUSH r2
    PUSH r3
    MOV r1, r0
    LDI r2, -APP_TERM_MAX
    LDI r3, APP_TERM_MAX
    CALL lib_clamp
    POP r3
    POP r2
    POP r1
    RET

; ---- monitor: watchdog kicker ----------------------------------------------

app_monitor:
    LD r6, [app_beat]
app_mon_loop:
    LDI r1, APP_MON_PERIOD
    CALL lib_sleep
    LD r1, [app_beat]
    CMP r1, r6
    JZ app_mon_loop             ; control went quiet: let the watchdog bite
    MOV r6, r1
    ST [MMIO_WDOG_KICK], r1
    JMP app_mon_loop

; ---- control ---------------------------------------------------------------

app_control:
    CALL lib_ticks
    MOV r6, r0                  ; r6 = next wake tick (absolute: no drift)
app_ctl_loop:
    ADDI r6, APP_CTL_PERIOD
    CALL lib_ticks
    MOV r1, r6
    SUB r1, r0
    CMPI r1, 0
    JGT app_ctl_sleep
    MOV r6, r0                  ; fell behind: resync and run now
    JMP app_ctl_run
app_ctl_sleep:
    CALL lib_sleep
app_ctl_run:
    CALL app_ctl_step
    JMP app_ctl_loop

; One control step. Preserves r6. r1 = temp, r2 = setpoint, r4 = heater, r5 = fan.
app_ctl_step:
    LD r1, [app_beat]
    ADDI r1, 1
    ST [app_beat], r1

    LD r2, [MMIO_ADC_SETPOINT]
    MOV r1, r2
    LDI r2, 0
    LDI r3, APP_SP_MAX_Q
    CALL lib_clamp
    MOV r2, r0
    ST [app_sp], r2
    LD r1, [MMIO_ADC_TEMP]
    ST [app_temp], r1

    ; -- sensor health (skipped when app_cfg_safety = 0; the 90 C latch stays)
    LD r3, [app_cfg_safety]
    CMPI r3, 0
    JZ app_ctl_hot
    LD r3, [app_last_raw]
    ST [app_last_raw], r1
    CMP r1, r3
    JNZ app_ctl_fresh
    LD r3, [app_stuck_n]
    ADDI r3, 1
    ST [app_stuck_n], r3
    CMPI r3, APP_STUCK_LIMIT
    JGE app_ctl_badsensor
    JMP app_ctl_range
app_ctl_fresh:
    LDI r3, 0
    ST [app_stuck_n], r3
app_ctl_range:
    CMPI r1, APP_TMAX_Q
    JGT app_ctl_badsensor
    CMPI r1, APP_TMIN_Q
    JLT app_ctl_badsensor
    LD r3, [app_flags]
    LDI r0, APP_F_SENSOR
    AND r3, r0
    JZ app_ctl_hot
    LDI r3, APP_F_SENSOR        ; sensor recovered
    CALL app_flag_clr
    LDI r3, APP_LED_SENSOR
    CALL app_led_off
    LDI r3, APP_EV_SENSOR_OK
    CALL app_ev
    JMP app_ctl_hot

app_ctl_badsensor:
    LD r3, [app_flags]
    LDI r0, APP_F_SENSOR
    AND r3, r0
    JNZ app_ctl_failsafe
    LDI r3, APP_F_SENSOR
    CALL app_flag_set
    LDI r3, APP_LED_SENSOR
    CALL app_led_on
    LDI r3, APP_EV_SENSOR
    CALL app_ev
app_ctl_failsafe:
    LDI r4, 0                   ; blind: heater off, fan off, forget history
    LDI r5, 0
    LDI r0, 0
    ST [app_integ], r0
    ST [app_have_prev], r0
    JMP app_ctl_out

    ; -- overheat latch
app_ctl_hot:
    LD r3, [app_flags]
    LDI r0, APP_F_HOT
    AND r3, r0
    JNZ app_ctl_hot_latched
    CMPI r1, APP_HOT_Q
    JLE app_ctl_pid
    LDI r3, APP_F_HOT
    CALL app_flag_set
    LDI r3, APP_LED_HOT
    CALL app_led_on
    LDI r3, APP_EV_HOT
    CALL app_ev
    JMP app_ctl_hot_out
app_ctl_hot_latched:
    CMPI r1, APP_COOL_Q
    JGE app_ctl_hot_out
    LDI r3, APP_F_HOT
    CALL app_flag_clr
    LDI r3, APP_LED_HOT
    CALL app_led_off
    LDI r3, APP_EV_COOL
    CALL app_ev
    JMP app_ctl_pid
app_ctl_hot_out:
    LDI r4, 0
    LDI r5, 255
    LDI r0, 0
    ST [app_integ], r0
    JMP app_ctl_out

    ; -- PID
app_ctl_pid:
    MOV r3, r2
    SUB r3, r1                  ; r3 = e (Q8.8)
    MOV r0, r3
    LD r4, [app_kp]
    FMUL r0, r4
    CALL app_clamp_term
    MOV r4, r0                  ; r4 = P
    LD r0, [app_have_prev]
    CMPI r0, 0
    JZ app_ctl_nod
    MOV r0, r1
    LD r5, [app_prev_temp]
    SUB r0, r5                  ; dT this step
    LD r5, [app_kd]
    FMUL r0, r5
    CALL app_clamp_term
    SUB r4, r0                  ; r4 = P - D
app_ctl_nod:
    ST [app_prev_temp], r1
    LDI r0, 1
    ST [app_have_prev], r0

    LD r5, [app_integ]
    MOV r0, r5
    PUSH r1
    LDI r1, APP_I_SHIFT
    SAR r0, r1
    POP r1
    ADD r0, r4                  ; r0 = u before integrating
    CMPI r0, 255
    JLT app_ctl_chk_lo
    CMPI r3, 0
    JGT app_ctl_i_done          ; saturated high, error still positive
app_ctl_chk_lo:
    CMPI r0, 0
    JGT app_ctl_i_do
    CMPI r3, 0
    JLT app_ctl_i_done          ; saturated low, error still negative
app_ctl_i_do:
    MOV r0, r3
    PUSH r1
    LD r1, [app_ki]
    FMUL r0, r1
    POP r1
    CALL app_clamp_term
    ADD r5, r0
    PUSH r1
    PUSH r2
    PUSH r3
    MOV r1, r5
    LDI r2, 0
    LDI r3, APP_I_MAX
    CALL lib_clamp
    POP r3
    POP r2
    POP r1
    MOV r5, r0
    ST [app_integ], r5
app_ctl_i_done:
    MOV r0, r5
    PUSH r1
    PUSH r2
    PUSH r3
    LDI r1, APP_I_SHIFT
    SAR r0, r1
    ADD r0, r4
    MOV r1, r0
    LDI r2, 0
    LDI r3, 255
    CALL lib_clamp
    POP r3
    POP r2
    POP r1
    MOV r4, r0                  ; r4 = heater duty

    ; -- fan with hysteresis
    LD r5, [app_fan]
    MOV r3, r1
    SUB r3, r2                  ; temp - setpoint
    CMPI r3, APP_FAN_ON_Q
    JLE app_ctl_fan_low
    LDI r5, 255
    JMP app_ctl_out
app_ctl_fan_low:
    CMPI r3, APP_FAN_OFF_Q
    JGE app_ctl_out
    LDI r5, 0

app_ctl_out:
    ST [MMIO_PWM_HEATER], r4
    ST [app_heat], r4
    ST [MMIO_PWM_FAN], r5
    ST [app_fan], r5
    LDI r3, APP_LED_FAN
    CMPI r5, 0
    JZ app_ctl_fan_led_off
    CALL app_led_on
    JMP app_ctl_telem
app_ctl_fan_led_off:
    CALL app_led_off

    ; -- telemetry: the temperature on queue 0 once a second, if the logger lives
app_ctl_telem:
    LD r3, [app_telem_n]
    ADDI r3, 1
    ST [app_telem_n], r3
    CMPI r3, APP_TELEM_EVERY
    JLT app_ctl_done
    LDI r3, 0
    ST [app_telem_n], r3
    LD r0, [k_tcb + APP_T_LOGGER * LIB_TCB_WORDS]
    CMPI r0, LIB_ST_DEAD
    JZ app_ctl_done
    CMPI r0, LIB_ST_FREE
    JZ app_ctl_done
    MOV r2, r1
    LDI r1, APP_Q_TELEM
    CALL lib_send
app_ctl_done:
    RET

; ---- logger ----------------------------------------------------------------

app_logger:
    CALL lib_lock
    LDI r1, app_s_banner
    CALL lib_puts
    CALL lib_unlock
app_log_loop:
    LDI r1, APP_Q_TELEM
    CALL lib_recv
    MOV r6, r0                  ; r6 = temperature sample
    CALL lib_lock
    DI
    LD r5, [app_events]
    LDI r0, 0
    ST [app_events], r0
    EI
    LDI r2, APP_EV_HOT
    LDI r1, app_s_ev_hot
    CALL app_log_ev
    LDI r2, APP_EV_COOL
    LDI r1, app_s_ev_cool
    CALL app_log_ev
    LDI r2, APP_EV_SENSOR
    LDI r1, app_s_ev_sensor
    CALL app_log_ev
    LDI r2, APP_EV_SENSOR_OK
    LDI r1, app_s_ev_sensor_ok
    CALL app_log_ev

    LDI r1, app_s_T
    CALL lib_puts
    MOV r1, r6
    CALL lib_put_q88
    LDI r1, app_s_S
    CALL lib_puts
    LD r1, [app_sp]
    CALL lib_put_q88
    LDI r1, app_s_H
    CALL lib_puts
    LD r1, [app_heat]
    CALL lib_put_u16
    LDI r1, app_s_F
    CALL lib_puts
    LD r1, [app_fan]
    CALL lib_put_u16
    LD r5, [app_flags]
    LDI r2, APP_F_SENSOR
    LDI r1, app_s_tag_sensor
    CALL app_log_tag
    LDI r2, APP_F_HOT
    LDI r1, app_s_tag_hot
    CALL app_log_tag
    CALL lib_newline
    CALL lib_unlock
    JMP app_log_loop

app_log_ev:                     ; if r5 & r2: puts(r1) + newline
    MOV r0, r5
    AND r0, r2
    JZ app_log_ev_no
    CALL lib_puts
    CALL lib_newline
app_log_ev_no:
    RET

app_log_tag:                    ; if r5 & r2: puts(r1)
    MOV r0, r5
    AND r0, r2
    JZ app_log_tag_no
    CALL lib_puts
app_log_tag_no:
    RET

; ---- shell -----------------------------------------------------------------

app_shell:
    LDI r6, 0                   ; r6 = line length
app_sh_loop:
    LDI r1, APP_Q_UART
    CALL lib_recv
    CMPI r0, 10
    JZ app_sh_eol
    CMPI r0, 13
    JZ app_sh_eol
    CMPI r6, APP_LINE_MAX - 1
    JGE app_sh_loop             ; overlong: drop the tail
    ST [r6+app_line], r0
    ADDI r6, 1
    JMP app_sh_loop
app_sh_eol:
    LDI r0, 0
    ST [r6+app_line], r0
    CMPI r6, 0
    JZ app_sh_loop              ; blank line (or the \n of \r\n)
    CALL lib_lock
    CALL app_sh_exec
    CALL lib_unlock
    LDI r6, 0
    JMP app_sh_loop

app_sh_exec:                    ; run the command in app_line. Preserves r6.
    LD r1, [app_line]
    CMPI r1, 's'
    JZ app_sh_set
    CMPI r1, 'p'
    JZ app_sh_ps
    CMPI r1, 'g'
    JZ app_sh_gains
    CMPI r1, 'k'
    JZ app_sh_tune
    CMPI r1, '?'
    JZ app_sh_help
    CMPI r1, 'h'
    JZ app_sh_help
app_sh_err:
    LDI r1, app_s_err
    CALL lib_puts
    RET

app_sh_help:
    LDI r1, app_s_help
    CALL lib_puts
    RET

app_sh_set:                     ; s<degC>  e.g. s45, s52.5
    LDI r1, app_line + 1
    CALL lib_parse_q88
    LDI r1, LIB_PARSE_ERR
    CMP r0, r1
    JZ app_sh_err
    MOV r1, r0
    LDI r2, 0
    LDI r3, APP_SP_MAX_Q
    CALL lib_clamp
    ST [MMIO_ADC_SETPOINT], r0
    MOV r5, r0
    LDI r1, app_s_ok_s
    CALL lib_puts
    MOV r1, r5
    CALL lib_put_q88
    CALL lib_newline
    RET

app_sh_tune:                    ; kp<n> ki<n> kd<n>
    LD r1, [app_line + 1]
    LDI r5, app_kp
    CMPI r1, 'p'
    JZ app_sh_tune_val
    LDI r5, app_ki
    CMPI r1, 'i'
    JZ app_sh_tune_val
    LDI r5, app_kd
    CMPI r1, 'd'
    JNZ app_sh_err
app_sh_tune_val:
    LDI r1, app_line + 2
    CALL lib_parse_int
    CMPI r0, 0
    JLT app_sh_err              ; also catches LIB_PARSE_ERR
    CMPI r0, APP_GAIN_MAX
    JGT app_sh_err
    ST [r5], r0
    ; fall through: show the gains
app_sh_gains:
    LDI r1, app_s_kp
    CALL lib_puts
    LD r1, [app_kp]
    CALL lib_put_i16
    LDI r1, app_s_ki
    CALL lib_puts
    LD r1, [app_ki]
    CALL lib_put_i16
    LDI r1, app_s_kd
    CALL lib_puts
    LD r1, [app_kd]
    CALL lib_put_i16
    CALL lib_newline
    RET

app_sh_ps:                      ; task table straight out of kernel memory
    LDI r1, app_s_ticks
    CALL lib_puts
    LD r1, [k_ticks]
    CALL lib_put_u16
    CALL lib_newline
    LDI r5, 0                   ; r5 = task index
app_sh_ps_loop:
    MOV r4, r5
    LDI r0, LIB_TCB_WORDS
    MUL r4, r0                  ; r4 = TCB offset
    LD r3, [r4+k_tcb]           ; state
    CMPI r3, LIB_ST_FREE
    JZ app_sh_ps_next
    LDI r1, ' '
    LD r0, [k_current]
    CMP r0, r5
    JNZ app_sh_ps_mark
    LDI r1, '*'
app_sh_ps_mark:
    CALL lib_putc
    LDI r1, 't'
    CALL lib_putc
    MOV r1, r5
    CALL lib_put_u16
    LDI r1, ' '
    CALL lib_putc
    LD r1, [r5+app_task_names]
    CALL lib_puts
    LDI r1, ' '
    CALL lib_putc
    LDI r1, app_s_st_unknown
    CMPI r3, APP_NUM_STATES
    JC app_sh_ps_state          ; unsigned < 7: known state
    JMP app_sh_ps_state_out
app_sh_ps_state:
    LD r1, [r3+app_state_names]
app_sh_ps_state_out:
    CALL lib_puts
    LDI r1, app_s_prio
    CALL lib_puts
    LD r1, [r4+k_tcb+1]
    CALL lib_put_u16
    LDI r1, app_s_faults
    CALL lib_puts
    LD r1, [r4+k_tcb+5]
    CALL lib_put_u16
    CALL lib_newline
app_sh_ps_next:
    ADDI r5, 1
    CMPI r5, APP_NUM_TCBS
    JLT app_sh_ps_loop
    RET

; ---- heartbeat -------------------------------------------------------------

app_heartbeat:
    LDI r1, APP_HB_PERIOD
    CALL lib_sleep
    DI
    LD r2, [MMIO_GPIO_OUT]
    LDI r0, APP_LED_HB
    XOR r2, r0
    ST [MMIO_GPIO_OUT], r2
    EI
    JMP app_heartbeat

; ---- strings ---------------------------------------------------------------

app_s_banner:       .string "rtosaurus app up (? for help)\n"
app_s_T:            .string "T="
app_s_S:            .string " S="
app_s_H:            .string " H="
app_s_F:            .string " F="
app_s_tag_sensor:   .string " SENSOR"
app_s_tag_hot:      .string " HOT"
app_s_ev_hot:       .string "!overheat: heater off, fan on"
app_s_ev_cool:      .string "!overheat cleared"
app_s_ev_sensor:    .string "!sensor failed: heater off"
app_s_ev_sensor_ok: .string "!sensor ok"
app_s_err:          .string "err (? for help)\n"
app_s_ok_s:         .string "ok S="
app_s_kp:           .string "kp="
app_s_ki:           .string " ki="
app_s_kd:           .string " kd="
app_s_ticks:        .string "ticks="
app_s_prio:         .string " p"
app_s_faults:       .string " f"
app_s_help:         .string "s<C> setpoint (s52.5) | p tasks | g gains | kp<n> ki<n> kd<n> tune | ? help\n"

app_n_monitor:      .string "monitor"
app_n_control:      .string "control"
app_n_logger:       .string "logger"
app_n_shell:        .string "shell"
app_n_heartbeat:    .string "heartbeat"
app_n_idle:         .string "idle"
app_n_unknown:      .string "?"

app_task_names:
    .word app_n_monitor, app_n_control, app_n_logger, app_n_shell, app_n_heartbeat
    .word app_n_unknown, app_n_unknown, app_n_unknown, app_n_idle

app_s_st_free:      .string "free"
app_s_st_ready:     .string "ready"
app_s_st_running:   .string "running"
app_s_st_sleeping:  .string "sleeping"
app_s_st_blk_send:  .string "blk-send"
app_s_st_blk_recv:  .string "blk-recv"
app_s_st_dead:      .string "dead"
app_s_st_unknown:   .string "?"

app_state_names:
    .word app_s_st_free, app_s_st_ready, app_s_st_running, app_s_st_sleeping
    .word app_s_st_blk_send, app_s_st_blk_recv, app_s_st_dead

; ---- config (NOT touched by app_init: the host may poke it before/while running)

app_cfg_safety: .word 1         ; 0 = trust the sensor blindly (no stuck/range checks)

; ---- state (zeroed by app_init, so a watchdog reset starts clean) ----------

app_vars:
app_kp:         .word 0
app_ki:         .word 0
app_kd:         .word 0
app_integ:      .word 0
app_prev_temp:  .word 0
app_have_prev:  .word 0
app_temp:       .word 0
app_sp:         .word 0
app_heat:       .word 0
app_fan:        .word 0
app_beat:       .word 0
app_flags:      .word 0
app_events:     .word 0
app_stuck_n:    .word 0
app_last_raw:   .word 0
app_telem_n:    .word 0
app_line:       .zero APP_LINE_MAX
app_vars_end:
