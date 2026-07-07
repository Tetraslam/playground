// Segregated-fit allocator (the jemalloc/tcmalloc small-object picture):
// requests are rounded up to one of a fixed ladder of size classes, each
// class is served from 4 KiB "runs" carved into equal slots tracked by a
// bitmap, and runs themselves come from a page-level free list. Large
// requests (> 2048 B) bypass the classes and take whole pages. Small-object
// churn can never fragment the page level — an emptied run is returned as a
// whole page — which is the entire trick.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use super::{Allocator, ARENA};

const PAGE: u32 = 4096;
const CLASSES: [u32; 14] = [
    16, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 1536, 2048,
];
const LARGE_CUTOFF: u32 = 2048;

struct Run {
    class: usize,
    used: u16,
    bitmap: [u64; 4], // enough for 4096/16 = 256 slots
}

pub struct SegFit {
    /// page-level free list: offset -> length (both page-multiples)
    pages: BTreeMap<u32, u32>,
    /// per class: run bases that still have a free slot
    partial: Vec<BTreeSet<u32>>,
    runs: HashMap<u32, Run>,
}

fn class_for(size: u32) -> Option<usize> {
    CLASSES.iter().position(|&c| c >= size.max(1))
}

fn pages_for(size: u32) -> u32 {
    (size + PAGE - 1) & !(PAGE - 1)
}

impl SegFit {
    pub fn new() -> Self {
        let mut pages = BTreeMap::new();
        pages.insert(0, ARENA);
        SegFit {
            pages,
            partial: vec![BTreeSet::new(); CLASSES.len()],
            runs: HashMap::new(),
        }
    }

    fn alloc_pages(&mut self, len: u32) -> Option<u32> {
        // first-fit over page ranges
        let (&off, &plen) = self.pages.iter().find(|(_, &l)| l >= len)?;
        self.pages.remove(&off);
        if plen > len {
            self.pages.insert(off + len, plen - len);
        }
        Some(off)
    }

    fn free_pages(&mut self, offset: u32, len: u32) {
        let mut start = offset;
        let mut l = len;
        if let Some((&poff, &plen)) = self.pages.range(..offset).next_back() {
            if poff + plen == start {
                self.pages.remove(&poff);
                start = poff;
                l += plen;
            }
        }
        if let Some(&slen) = self.pages.get(&(start + l)) {
            self.pages.remove(&(start + l));
            l += slen;
        }
        self.pages.insert(start, l);
    }
}

impl Allocator for SegFit {
    fn name(&self) -> &'static str {
        "segfit"
    }

    fn alloc(&mut self, size: u32) -> Option<u32> {
        let Some(class) = class_for(size).filter(|_| size <= LARGE_CUTOFF) else {
            return self.alloc_pages(pages_for(size)); // large path
        };
        let slot_size = CLASSES[class];
        let slots = (PAGE / slot_size) as u16;

        let base = match self.partial[class].iter().next().copied() {
            Some(b) => b,
            None => {
                // no partial run: carve a fresh page into a new run
                let b = self.alloc_pages(PAGE)?;
                self.runs.insert(
                    b,
                    Run {
                        class,
                        used: 0,
                        bitmap: [0; 4],
                    },
                );
                self.partial[class].insert(b);
                b
            }
        };

        let run = self.runs.get_mut(&base).unwrap();
        // find the first zero bit among the first `slots` bits
        let mut slot = None;
        for (w, word) in run.bitmap.iter_mut().enumerate() {
            if *word != u64::MAX {
                let bit = word.trailing_ones() as usize;
                let idx = w * 64 + bit;
                if idx < slots as usize {
                    *word |= 1 << bit;
                    slot = Some(idx);
                    break;
                }
            }
        }
        let slot = slot?; // can't happen: run was in `partial`
        run.used += 1;
        if run.used == slots {
            self.partial[class].remove(&base);
        }
        Some(base + slot as u32 * slot_size)
    }

    fn free(&mut self, offset: u32, size: u32) {
        if size > LARGE_CUTOFF {
            self.free_pages(offset, pages_for(size));
            return;
        }
        let base = offset & !(PAGE - 1);
        let run = self.runs.get_mut(&base).expect("free of unknown run");
        let class = run.class;
        let slot_size = CLASSES[class];
        let slots = (PAGE / slot_size) as u16;
        let idx = ((offset - base) / slot_size) as usize;
        run.bitmap[idx / 64] &= !(1 << (idx % 64));
        let was_full = run.used == slots;
        run.used -= 1;
        if run.used == 0 {
            // run emptied: hand the whole page back — no small-object confetti
            self.runs.remove(&base);
            self.partial[class].remove(&base);
            self.free_pages(base, PAGE);
        } else if was_full {
            self.partial[class].insert(base);
        }
    }

    fn reserved_for(&self, size: u32) -> u32 {
        match class_for(size).filter(|_| size <= LARGE_CUTOFF) {
            Some(c) => CLASSES[c],
            None => pages_for(size),
        }
    }

    fn free_space(&self) -> (u64, u32) {
        let page_free: u64 = self.pages.values().map(|&l| l as u64).sum();
        let largest = self.pages.values().copied().max().unwrap_or(0);
        // slack inside partial runs counts as free-for-small, so include it in
        // the total; it can never serve a large request, so not in `largest`.
        let run_free: u64 = self
            .runs
            .values()
            .map(|r| {
                let slots = (PAGE / CLASSES[r.class]) as u64;
                (slots - r.used as u64) * CLASSES[r.class] as u64
            })
            .sum();
        (page_free + run_free, largest)
    }

    fn reset(&mut self) {
        self.pages.clear();
        self.pages.insert(0, ARENA);
        for p in &mut self.partial {
            p.clear();
        }
        self.runs.clear();
    }
}
