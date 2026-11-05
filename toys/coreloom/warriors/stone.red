; stone (slot 3, bomber): dwarf with a scattered step.
; 3044 = 4*761 and gcd(761, 1000) = 1, so it visits every multiple of 4
; but jumps around the core instead of walking, hitting far enemies early.
ADD #3044, $3
MOV $2, @2
JMP $-2, $0
DAT #0, #0
