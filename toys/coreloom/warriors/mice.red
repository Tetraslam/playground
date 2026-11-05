; mice (slot 4, replicator): Chip Wendell's 1986 paper.
; Copies itself 653 cells further on each pass and SPLs into the copy,
; so killing it means killing every copy before it breeds again.
DAT #0, #0          ; ptr: copy counter / source index
start: MOV #12, $-1 ; ptr = 12
MOV @-2, <5         ; copy ptr+n to --dest
DJN $-1, $-3        ; until ptr hits 0
SPL @3, $0          ; start the copy
ADD #653, $2        ; move dest along
JMZ $-5, $-6        ; and breed again
DAT #0, #833        ; dest
ORG start
