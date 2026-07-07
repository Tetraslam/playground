// Bump allocator: a single pointer that only moves forward. free() is a
// no-op unless you free the *entire* live set (tracked by a counter), in
// which case the pointer snaps back to zero. Blazing fast, hilariously bad
// under churn — included as the control group.

use super::{Allocator, ARENA};

const ALIGN: u32 = 16;

pub struct Bump {
    head: u32,
    live: u32,
}

impl Bump {
    pub fn new() -> Self {
        Bump { head: 0, live: 0 }
    }
}

fn align_up(n: u32) -> u32 {
    (n + ALIGN - 1) & !(ALIGN - 1)
}

impl Allocator for Bump {
    fn name(&self) -> &'static str {
        "bump"
    }

    fn alloc(&mut self, size: u32) -> Option<u32> {
        let need = align_up(size.max(1));
        if self.head + need > ARENA {
            return None;
        }
        let off = self.head;
        self.head += need;
        self.live += 1;
        Some(off)
    }

    fn free(&mut self, _offset: u32, _size: u32) {
        self.live -= 1;
        if self.live == 0 {
            self.head = 0; // the only reclamation a bump allocator knows
        }
    }

    fn reserved_for(&self, size: u32) -> u32 {
        align_up(size.max(1))
    }

    fn free_space(&self) -> (u64, u32) {
        let rest = ARENA - self.head;
        (rest as u64, rest)
    }

    fn reset(&mut self) {
        self.head = 0;
        self.live = 0;
    }
}
