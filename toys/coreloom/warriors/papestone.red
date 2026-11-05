; papestone (slot 4): mice with a stone stapled on. Every copy starts its
; own bomber, so the paper spreads a field of stones instead of just ties.
; The stone steps by 1180 = 20 * 59: it hits only multiples of 20 from its
; bomb, which never land on the 12-cell body behind it. Re-breeding jumps to
; brd, past the SPL, so each copy starts exactly one stone.
DAT #0, #0          ; 0 ptr
start: SPL $8, $0   ; 1 -> stone
MOV #12, $-2        ; 2 brd: copy cells 12..1
MOV @-3, <5         ; 3
DJN $-1, $-4        ; 4
SPL @3, $0          ; 5 start the copy at its SPL
ADD #653, $2        ; 6
JMZ $-5, $-7        ; 7 -> brd
DAT #0, #833        ; 8 dest
ADD #1180, $3       ; 9 stone
MOV $2, @2          ; 10
JMP $-2, $0         ; 11
DAT #0, #0          ; 12 bomb
ORG start
