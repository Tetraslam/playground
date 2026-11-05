; scout (slot 3, scanner): skip empty core, bomb anything with a nonzero B.
; Step 5 keeps the scan off its own code (offsets -4..1 from the pointer).
; A bombed cell gets B=0, so it is never rescanned.
ADD #5, $4      ; ptr += 5
JMZ $-1, @3     ; target B == 0: keep scanning
MOV $3, @2      ; found something: drop the bomb on it
JMP $-3, $0
DAT #0, #0      ; ptr (B = offset from here)
DAT #0, #0      ; bomb
