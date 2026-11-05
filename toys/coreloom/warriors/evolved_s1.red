;name evolved_s1
;author evolve.py
; bred from noise: seed 1, 100 generations, pop 64, coevolve 10
; final generation: 1.60 pts/round vs the hill
; points per opponent: carpet 0/12, dwarf 12/12, imp 12/12, impring 12/12, mice 3/12, paperimp 4/12, scout 12/12, stone 12/12, twindwarf 12/12, gen10 4/12, gen20 4/12, gen30 4/12, gen40 4/12, gen50 4/12, gen60 4/12, gen70 4/12, gen80 4/12, gen90 4/12
ORG 2
CMP #2, #2825
DAT $3992, #11
ADD @62, #3
DJN #10, <0
SPL @67, $7
DJN #17, <7
DJN #170, <8
DJN #170, <0
ADD @67, #3870
JMP #162, <0
DJN @5, <3
DJN @5, <3
DJN #170, <0
SPL @67, @3996
DJN #170, <0
ADD #3900, $3599
ADD @73, #2
JMP #162, <0
DJN @5, <3
