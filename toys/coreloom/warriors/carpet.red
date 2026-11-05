; carpet (slot 3, anti-paper): stun first, then clear.
; Phase 1 lays two-cell stun bombs (SPL $0 / JMP $-1) every 3044 cells.
; A paper process that lands on either cell is trapped forking in place,
; eating the 64-process budget its copies need to breed.
; 520 bombs is the most 3044 allows before one would land on this code.
; Phase 2 is a backward DAT clear from ptr, two cells per loop, that turns
; every trapped cell into a death cell, stops just short of its own code,
; and starts over.
ptr:    DAT #0, #0
start:  ADD #3045, ptr      ; +3044, plus the 1 that <ptr takes back
        MOV jb, @ptr
        MOV sb, <ptr
        DJN start, #520
reset:  MOV #0, ptr
clear:  MOV db, <ptr
        MOV db, <ptr
        DJN clear, #1993
        MOV #1993, clear+2
        JMP reset
sb:     SPL $0, $0
jb:     JMP $-1, $0
db:     DAT #0, #0
ORG start
