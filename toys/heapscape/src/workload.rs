// Workload generators: deterministic streams of alloc/free ops. The
// generator tracks its own canonical live set (assuming every alloc
// succeeds) so the SAME trace can be fed to every allocator and the heaps
// diverge only by policy, never by luck.

use crate::alloc::ARENA;
use crate::rng::Pcg32;

#[derive(Clone, Copy, Debug)]
pub enum Op {
    Alloc { id: u64, size: u32 },
    Free { id: u64 },
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    Churn,   // steady-state alloc/free around a target occupancy
    Spike,   // churn + periodic bursts of large, long-ish-lived blocks
    Ramp,    // sawtooth: fill toward capacity, drain, repeat
    Stripes, // fill uniform, free every other, then ask for 4x blocks
    Shift,   // churn whose size regime flips small<->large; strands blocks
}

pub const KINDS: [Kind; 5] = [
    Kind::Churn,
    Kind::Spike,
    Kind::Ramp,
    Kind::Stripes,
    Kind::Shift,
];

impl Kind {
    pub fn name(self) -> &'static str {
        match self {
            Kind::Churn => "churn",
            Kind::Spike => "spike",
            Kind::Ramp => "ramp",
            Kind::Stripes => "stripes",
            Kind::Shift => "shift",
        }
    }
}

#[derive(Clone, Copy, PartialEq)]
enum Phase {
    Fill,
    Drain,
    StripeFree,
    StripeProbe(u32), // remaining probe ops
    StripeClear,
}

pub struct Workload {
    pub kind: Kind,
    rng: Pcg32,
    next_id: u64,
    /// canonical live set: (id, size). Order = allocation order.
    live: Vec<(u64, u32)>,
    live_bytes: u64,
    tick: u64,
    phase: Phase,
    stripe_cycle: usize,
    /// spike blocks waiting to expire: (expiry_tick, id)
    pending_frees: Vec<(u64, u64)>,
    pub spikes_queued: u32,
}

const STRIPE_SIZES: [u32; 3] = [48, 160, 640];

impl Workload {
    pub fn new(kind: Kind, seed: u64) -> Self {
        Workload {
            kind,
            rng: Pcg32::new(seed ^ (kind as u64) << 32),
            next_id: 0,
            live: Vec::new(),
            live_bytes: 0,
            tick: 0,
            phase: Phase::Fill,
            stripe_cycle: 0,
            pending_frees: Vec::new(),
            spikes_queued: 0,
        }
    }

    /// canonical live bytes (assuming every alloc succeeded)
    pub fn live_bytes(&self) -> u64 {
        self.live_bytes
    }

    /// Ask for a burst of large allocations on the next ticks (the TUI's `f`).
    pub fn inject_spike(&mut self) {
        self.spikes_queued += 24;
    }

    fn fresh_id(&mut self) -> u64 {
        self.next_id += 1;
        self.next_id
    }

    fn do_alloc(&mut self, size: u32) -> Op {
        let id = self.fresh_id();
        self.live.push((id, size));
        self.live_bytes += size as u64;
        Op::Alloc { id, size }
    }

    fn free_at(&mut self, idx: usize) -> Op {
        let (id, size) = self.live.swap_remove(idx);
        self.live_bytes -= size as u64;
        Op::Free { id }
    }

    fn free_random(&mut self) -> Option<Op> {
        if self.live.is_empty() {
            return None;
        }
        let idx = self.rng.below(self.live.len() as u32) as usize;
        Some(self.free_at(idx))
    }

    /// size skewed small: exponent geometric-ish over [2^lo, 2^hi)
    fn skewed_size(&mut self, lo: u32, hi: u32) -> u32 {
        let mut e = lo;
        while e < hi && self.rng.f32() < 0.55 {
            e += 1;
        }
        let base = 1u32 << e;
        base + self.rng.below(base)
    }

    pub fn next_op(&mut self) -> Op {
        self.tick += 1;

        // expiring spike blocks take priority
        if let Some(pos) = self
            .pending_frees
            .iter()
            .position(|&(exp, _)| exp <= self.tick)
        {
            let (_, id) = self.pending_frees.swap_remove(pos);
            if let Some(idx) = self.live.iter().position(|&(i, _)| i == id) {
                return self.free_at(idx);
            }
        }

        // injected spikes (from the TUI) fire on any workload
        if self.spikes_queued > 0 {
            self.spikes_queued -= 1;
            let size = 8192 + self.rng.below(24576);
            let op = self.do_alloc(size);
            if let Op::Alloc { id, .. } = op {
                self.pending_frees.push((self.tick + 1500, id));
            }
            return op;
        }

        match self.kind {
            Kind::Churn => self.step_churn(0.60, 4, 11),
            Kind::Spike => {
                if self.tick % 4000 == 0 {
                    self.spikes_queued += 24;
                }
                self.step_churn(0.45, 4, 11)
            }
            Kind::Ramp => self.step_ramp(),
            Kind::Stripes => self.step_stripes(),
            Kind::Shift => {
                let large = (self.tick / 6000) % 2 == 1;
                if large {
                    self.step_churn(0.55, 9, 13)
                } else {
                    self.step_churn(0.55, 4, 9)
                }
            }
        }
    }

    fn step_churn(&mut self, target: f64, lo: u32, hi: u32) -> Op {
        let occupancy = self.live_bytes as f64 / ARENA as f64;
        let p_alloc = if occupancy < target { 0.75 } else { 0.25 };
        if self.rng.f32() < p_alloc as f32 || self.live.is_empty() {
            let size = self.skewed_size(lo, hi);
            self.do_alloc(size)
        } else {
            self.free_random().unwrap()
        }
    }

    fn step_ramp(&mut self) -> Op {
        let occupancy = self.live_bytes as f64 / ARENA as f64;
        match self.phase {
            Phase::Fill if occupancy >= 0.85 => {
                self.phase = Phase::Drain;
                self.free_random().unwrap()
            }
            Phase::Fill => {
                let size = self.skewed_size(4, 11);
                self.do_alloc(size)
            }
            _ if occupancy <= 0.20 || self.live.is_empty() => {
                self.phase = Phase::Fill;
                let size = self.skewed_size(4, 11);
                self.do_alloc(size)
            }
            _ => self.free_random().unwrap(),
        }
    }

    fn step_stripes(&mut self) -> Op {
        let s = STRIPE_SIZES[self.stripe_cycle % STRIPE_SIZES.len()];
        let occupancy = self.live_bytes as f64 / ARENA as f64;
        match self.phase {
            Phase::Fill | Phase::Drain => {
                if occupancy < 0.80 {
                    self.do_alloc(s)
                } else {
                    self.phase = Phase::StripeFree;
                    self.step_stripes()
                }
            }
            Phase::StripeFree => {
                // free every other block by allocation order — classic checkerboard
                if self.live.len() >= 2 {
                    // find the lowest-id block at an even position of the sorted order:
                    // cheap approximation: free every other element of the Vec
                    let idx = (self.tick as usize * 2 + 1) % self.live.len();
                    let op = self.free_at(idx);
                    if self.live_bytes as f64 / ARENA as f64 <= 0.42 {
                        self.phase = Phase::StripeProbe(400);
                    }
                    op
                } else {
                    self.phase = Phase::StripeProbe(400);
                    self.step_stripes()
                }
            }
            Phase::StripeProbe(n) => {
                // now ask for blocks 4x the stripe size: they only fit if the
                // allocator kept (or rebuilt) contiguity
                self.phase = if n > 1 {
                    Phase::StripeProbe(n - 1)
                } else {
                    Phase::StripeClear
                };
                if self.rng.f32() < 0.6 {
                    let jitter = self.rng.below(s);
                    self.do_alloc(s * 4 + jitter)
                } else {
                    self.free_random().unwrap_or_else(|| self.do_alloc(s * 4))
                }
            }
            Phase::StripeClear => {
                if self.live.is_empty() {
                    self.phase = Phase::Fill;
                    self.stripe_cycle += 1;
                    self.step_stripes()
                } else {
                    self.free_random().unwrap()
                }
            }
        }
    }
}
