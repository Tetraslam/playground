; lurker (slot 3, anti-paper scanner): look before you bomb.
; Each pass CMPs a pair of adjacent cells 762 further on. Empty core is
; all DAT #0, #0, so a mismatch means something lives there, and the pair
; gets a stun trap (SPL $0 / JMP $-1) laid exactly over it.
; 1780 passes is the most 762 allows (starting 16 out) before the probe
; would land on this code. Then a backward DAT clear from the gate turns
; every trap into a death cell, stopping short of its own code, forever.
gate:   DAT #0, #0
scan:   ADD inc, cmpp
cmpp:   CMP $16, $17
        JMP attack          ; mismatch
next:   DJN scan, #1780
reset:  MOV #0, gate
clear:  MOV db, <gate
        MOV db, <gate
        DJN clear, #1990
        MOV #1990, clear+2
        JMP reset
attack: MOV jb, @cmpp       ; JMP $-1 on the B cell
        MOV sb, <cmpp       ; SPL $0 on the A cell (B - 1)
        ADD #1, cmpp        ; undo the predecrement
        JMP next
inc:    DAT #762, #762
sb:     SPL $0, $0
jb:     JMP $-1, $0
db:     DAT #0, #0
ORG scan
