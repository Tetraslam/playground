; paperimp (slot 4): mice and impring in one body. The paper breeds while
; the ring circles the core, so a bomber has to beat both to win.
; The ring sits last because its imps march forward over whatever follows.
; Foreign processes in the queue don't break the ring: only the relative
; order of its three imps matters, and FIFO preserves that.
SPL $10, $0         ; ring gets its own process
JMP $2, $0          ; -> mice
DAT #0, #0          ; mice ptr
MOV #12, $-1
MOV @-2, <5
DJN $-1, $-3
SPL @3, $0
ADD #653, $2
JMZ $-5, $-6
DAT #0, #833        ; mice dest
SPL $3, $0          ; impring launcher, offsets as in impring.red
SPL $4, $0
JMP $5, $0
SPL $3, $0
JMP $1337, $0
JMP $2669, $0
DAT #0, #0
MOV $0, $2667
