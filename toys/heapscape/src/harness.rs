// The harness owns one workload and N allocator "lanes". Every op from the
// trace is applied to every lane; an alloc that fails in one lane simply
// never exists there (and its later free is skipped), so lanes stay
// comparable forever.

use std::collections::HashMap;

use crate::alloc::{self, Allocator, ARENA};
use crate::workload::{Kind, Op, Workload};

pub struct Lane {
    pub alloc: Box<dyn Allocator>,
    /// id -> (offset, requested size, birth op#)
    live: HashMap<u64, (u32, u32, u64)>,
    pub failures: u64,
    pub live_req: u64, // sum of requested bytes actually live in this lane
    pub reserved: u64, // sum of reserved_for() across live blocks
    pub alloc_calls: u64,
}

pub struct Metrics {
    pub util: f64,     // live requested bytes / arena
    pub overhead: f64, // (reserved - requested) / reserved
    pub ext_frag: f64, // 1 - largest_free / total_free
    pub largest_free: u32,
    pub failures: u64,
}

impl Lane {
    fn new(alloc: Box<dyn Allocator>) -> Self {
        Lane {
            alloc,
            live: HashMap::new(),
            failures: 0,
            live_req: 0,
            reserved: 0,
            alloc_calls: 0,
        }
    }

    fn apply(&mut self, op: Op, tick: u64) {
        match op {
            Op::Alloc { id, size } => {
                self.alloc_calls += 1;
                match self.alloc.alloc(size) {
                    Some(off) => {
                        self.live.insert(id, (off, size, tick));
                        self.live_req += size as u64;
                        self.reserved += self.alloc.reserved_for(size) as u64;
                    }
                    None => self.failures += 1,
                }
            }
            Op::Free { id } => {
                if let Some((off, size, _)) = self.live.remove(&id) {
                    self.alloc.free(off, size);
                    self.live_req -= size as u64;
                    self.reserved -= self.alloc.reserved_for(size) as u64;
                }
            }
        }
    }

    pub fn metrics(&self) -> Metrics {
        let (total_free, largest_free) = self.alloc.free_space();
        Metrics {
            util: self.live_req as f64 / ARENA as f64,
            overhead: if self.reserved == 0 {
                0.0
            } else {
                (self.reserved - self.live_req) as f64 / self.reserved as f64
            },
            ext_frag: alloc::ext_frag(total_free, largest_free),
            largest_free,
            failures: self.failures,
        }
    }

    /// Paint the arena into `cells`: for each cell, coverage in [0,1] and the
    /// dominant block's size class (log2 bucket, 0 = 16 B).
    pub fn paint(&self, cells: &mut [(f32, u8)]) {
        let n = cells.len() as u64;
        let bpc = ARENA as u64 / n; // bytes per cell
        let mut cover = vec![0u32; cells.len()];
        let mut class_bytes = vec![[0u32; 12]; cells.len()];
        for &(off, size, _) in self.live.values() {
            let reserved = self.alloc.reserved_for(size);
            let class = size_class(size);
            let (start, end) = (off as u64, off as u64 + reserved as u64);
            let (c0, c1) = ((start / bpc) as usize, ((end - 1) / bpc) as usize);
            for c in c0..=c1.min(cells.len() - 1) {
                let cell_lo = c as u64 * bpc;
                let cell_hi = cell_lo + bpc;
                let overlap = end.min(cell_hi).saturating_sub(start.max(cell_lo)) as u32;
                cover[c] += overlap;
                class_bytes[c][class as usize] += overlap;
            }
        }
        for (c, cell) in cells.iter_mut().enumerate() {
            let dominant = class_bytes[c]
                .iter()
                .enumerate()
                .max_by_key(|(_, &b)| b)
                .map(|(i, _)| i as u8)
                .unwrap_or(0);
            *cell = ((cover[c] as f32 / bpc as f32).min(1.0), dominant);
        }
    }
}

/// log2 size bucket: 16 B -> 0, 32 B -> 1, ... 32 KiB+ -> 11
pub fn size_class(size: u32) -> u8 {
    let bits = 32 - size.max(16).leading_zeros() - 1; // floor log2
    (bits - 4).min(11) as u8
}

pub struct Harness {
    pub lanes: Vec<Lane>,
    pub workload: Workload,
    pub ops: u64,
    seed: u64,
}

pub fn standard_lanes() -> Vec<Lane> {
    use crate::alloc::{
        buddy::Buddy,
        bump::Bump,
        freelist::{FreeList, Policy},
        segfit::SegFit,
    };
    vec![
        Lane::new(Box::new(Bump::new())),
        Lane::new(Box::new(FreeList::new(Policy::FirstFit))),
        Lane::new(Box::new(FreeList::new(Policy::BestFit))),
        Lane::new(Box::new(Buddy::new())),
        Lane::new(Box::new(SegFit::new())),
    ]
}

impl Harness {
    pub fn new(kind: Kind, seed: u64) -> Self {
        Harness {
            lanes: standard_lanes(),
            workload: Workload::new(kind, seed),
            ops: 0,
            seed,
        }
    }

    pub fn step(&mut self) {
        let op = self.workload.next_op();
        self.ops += 1;
        for lane in &mut self.lanes {
            lane.apply(op, self.ops);
        }
    }

    pub fn run(&mut self, n: u64) {
        for _ in 0..n {
            self.step();
        }
    }

    /// swap to a different workload, resetting every lane
    pub fn set_workload(&mut self, kind: Kind) {
        self.workload = Workload::new(kind, self.seed);
        self.ops = 0;
        for lane in &mut self.lanes {
            lane.alloc.reset();
            lane.live.clear();
            lane.failures = 0;
            lane.live_req = 0;
            lane.reserved = 0;
            lane.alloc_calls = 0;
        }
    }
}
