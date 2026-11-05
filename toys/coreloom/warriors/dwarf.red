; dwarf (slot 3, bomber): classic A.K. Dewdney bomber.
; Drops a DAT every 4 cells. Its own code sits at -3..-1 from the bomb,
; never a multiple of 4, so it never hits itself.
ADD #4, $3      ; bump the bomb's B-field (the aim)
MOV $2, @2      ; copy the bomb to bomb + B
JMP $-2, $0
DAT #0, #0      ; bomb and pointer
