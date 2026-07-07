// Classic free-list allocator (the malloc textbook picture): free ranges kept
// in an ordered map, allocation splits a range, free coalesces with both
// neighbors. Two placement policies share the implementation:
//   first-fit — take the lowest-address range that fits
//   best-fit  — take the tightest range that fits
// Each block pays a 16-byte header and is 16-byte aligned, like a real malloc.

use std::collections::BTreeMap;

use super::{Allocator, ARENA};

const HEADER: u32 = 16;
const ALIGN: u32 = 16;

#[derive(Clone, Copy, PartialEq)]
pub enum Policy {
    FirstFit,
    BestFit,
}

pub struct FreeList {
    policy: Policy,
    /// offset -> length of each free range, ordered by offset
    free: BTreeMap<u32, u32>,
}

fn block_size(req: u32) -> u32 {
    (req.max(1) + HEADER + ALIGN - 1) & !(ALIGN - 1)
}

impl FreeList {
    pub fn new(policy: Policy) -> Self {
        let mut free = BTreeMap::new();
        free.insert(0, ARENA);
        FreeList { policy, free }
    }
}

impl Allocator for FreeList {
    fn name(&self) -> &'static str {
        match self.policy {
            Policy::FirstFit => "freelist/first-fit",
            Policy::BestFit => "freelist/best-fit",
        }
    }

    fn alloc(&mut self, size: u32) -> Option<u32> {
        let need = block_size(size);
        let pick = match self.policy {
            Policy::FirstFit => self
                .free
                .iter()
                .find(|(_, &len)| len >= need)
                .map(|(&off, &len)| (off, len)),
            Policy::BestFit => self
                .free
                .iter()
                .filter(|(_, &len)| len >= need)
                .min_by_key(|(_, &len)| len)
                .map(|(&off, &len)| (off, len)),
        }?;
        let (off, len) = pick;
        self.free.remove(&off);
        if len > need {
            self.free.insert(off + need, len - need); // split: remainder stays free
        }
        Some(off)
    }

    fn free(&mut self, offset: u32, size: u32) {
        let mut start = offset;
        let mut len = block_size(size);
        // coalesce with predecessor if adjacent
        if let Some((&poff, &plen)) = self.free.range(..offset).next_back() {
            if poff + plen == start {
                self.free.remove(&poff);
                start = poff;
                len += plen;
            }
        }
        // coalesce with successor if adjacent
        if let Some(&slen) = self.free.get(&(start + len)) {
            self.free.remove(&(start + len));
            len += slen;
        }
        self.free.insert(start, len);
    }

    fn reserved_for(&self, size: u32) -> u32 {
        block_size(size)
    }

    fn free_space(&self) -> (u64, u32) {
        let total: u64 = self.free.values().map(|&l| l as u64).sum();
        let largest = self.free.values().copied().max().unwrap_or(0);
        (total, largest)
    }

    fn reset(&mut self) {
        self.free.clear();
        self.free.insert(0, ARENA);
    }
}
