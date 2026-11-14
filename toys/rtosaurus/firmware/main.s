; rtosaurus firmware image. Assemble with: uv run python -m rtosaurus asm
.include "kernel.s"   ; .org 0: vector table, then kernel code/data (agent 6)
.include "lib.s"      ; print helpers (agent 7)
.include "app.s"      ; app_init, task_table, tasks (agent 7)
