// Binary buddy allocator: every block is a power of two, blocks split in
// halves ("buddies") on demand, and a freed block merges with its buddy —
// found by XOR-ing the offset with the block size — whenever the buddy is
// also free. O(log n) alloc/free, bounded external fragmentation, but pays
// for it in internal fragmentation (a 1025-byte request burns 2048).

use std::collections::BTreeSet;

use super::{Allocator, ARENA};

const MIN_ORDER: u32 = 5; // 32 B smallest block
const MAX_ORDER: u32 = 20; // 1 MiB = whole arena
const ORDERS: usize = (MAX_ORDER - MIN_ORDER + 1) as usize;

pub struct Buddy {
    /// free_lists[k] holds offsets of free blocks of size 1 << (MIN_ORDER + k)
    free_lists: Vec<BTreeSet<u32>>,
}

fn order_for(size: u32) -> u32 {
    let bits = 32 - size.max(1).next_power_of_two().leading_zeros() - 1;
    bits.max(MIN_ORDER)
}

impl Buddy {
    pub fn new() -> Self {
        let mut free_lists = vec![BTreeSet::new(); ORDERS];
        free_lists[ORDERS - 1].insert(0u32); // one maximal block
        Buddy { free_lists }
    }
}

impl Allocator for Buddy {
    fn name(&self) -> &'static str {
        "buddy"
    }

    fn alloc(&mut self, size: u32) -> Option<u32> {
        if size > ARENA {
            return None;
        }
        let want = order_for(size);
        // find the smallest free block big enough...
        let from =
            (want..=MAX_ORDER).find(|&k| !self.free_lists[(k - MIN_ORDER) as usize].is_empty())?;
        let off = *self.free_lists[(from - MIN_ORDER) as usize].iter().next()?;
        self.free_lists[(from - MIN_ORDER) as usize].remove(&off);
        // ...then split down, shedding the upper half at each level
        for k in (want..from).rev() {
            self.free_lists[(k - MIN_ORDER) as usize].insert(off + (1 << k));
        }
        Some(off)
    }

    fn free(&mut self, offset: u32, size: u32) {
        let mut off = offset;
        let mut order = order_for(size);
        // merge with buddy as long as the buddy is also free
        while order < MAX_ORDER {
            let buddy = off ^ (1 << order);
            let list = &mut self.free_lists[(order - MIN_ORDER) as usize];
            if !list.remove(&buddy) {
                break;
            }
            off = off.min(buddy);
            order += 1;
        }
        self.free_lists[(order - MIN_ORDER) as usize].insert(off);
    }

    fn reserved_for(&self, size: u32) -> u32 {
        1 << order_for(size)
    }

    fn free_space(&self) -> (u64, u32) {
        let mut total = 0u64;
        let mut largest = 0u32;
        for (i, list) in self.free_lists.iter().enumerate() {
            let sz = 1u32 << (MIN_ORDER as usize + i);
            total += list.len() as u64 * sz as u64;
            if !list.is_empty() {
                largest = sz;
            }
        }
        (total, largest)
    }

    fn reset(&mut self) {
        for l in &mut self.free_lists {
            l.clear();
        }
        self.free_lists[ORDERS - 1].insert(0);
    }
}
