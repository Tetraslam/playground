; impring (slot 4): three imps spaced 2667 apart, one step each in turn.
; 3 * 2667 = 8001 = 1 (mod 4000), so the trio closes into a ring:
; each imp writes the cell the next one is about to run, so one bombed
; cell doesn't stop it. Launch tree: leaves run in order 2, 5, 4, 6,
; which queues the imps as [A, B, C] back to back so the ring starts in step.
SPL $3, $0      ; 0 -> 3
SPL $4, $0      ; 1 -> 5
JMP $5, $0      ; 2 -> A at 7
SPL $3, $0      ; 3 -> 6
JMP $1337, $0   ; 4 -> C at 7 + 5334
JMP $2669, $0   ; 5 -> B at 7 + 2667
DAT #0, #0      ; 6 spare leaf, dies
MOV $0, $2667   ; 7 the imp
