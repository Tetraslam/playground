// The Allocator trait every heap strategy implements, over a simulated arena
// of ARENA bytes. Allocators hand out byte offsets; no user data is stored.

pub mod buddy;
pub mod bump;
pub mod freelist;
pub mod segfit;

pub const ARENA: u32 = 1 << 20; // 1 MiB

pub trait Allocator {
    fn name(&self) -> &'static str;

    /// Try to allocate `size` bytes; returns the offset on success.
    fn alloc(&mut self, size: u32) -> Option<u32>;

    /// Free a block previously returned by `alloc` with the same requested size.
    fn free(&mut self, offset: u32, size: u32);

    /// Bytes this allocator actually consumes to satisfy a request of `size`
    /// (rounding + headers). Used for internal-fragmentation accounting.
    fn reserved_for(&self, size: u32) -> u32;

    /// (total free bytes, largest contiguous free block)
    fn free_space(&self) -> (u64, u32);

    fn reset(&mut self);
}

/// External fragmentation: how much of the free space is unreachable to a
/// large request. 0 = one contiguous free block, ->1 = shattered.
pub fn ext_frag(total_free: u64, largest: u32) -> f64 {
    if total_free == 0 {
        0.0
    } else {
        1.0 - largest as f64 / total_free as f64
    }
}
