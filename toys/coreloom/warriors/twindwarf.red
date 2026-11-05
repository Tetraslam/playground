; twindwarf (slot 3, bomber): dwarf run by two processes.
; Same bombing rate (one insn per warrior per cycle), but a stray hit on
; one loop cell can leave the other process alive.
SPL $1, $0
ADD #4, $3
MOV $2, @2
JMP $-2, $0
DAT #0, #0
