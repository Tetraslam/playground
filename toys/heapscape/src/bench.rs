// Bench mode: run every workload through every allocator (same trace),
// print a comparison table, and write PNGs — final arena snapshots and a
// largest-free-block-over-time chart per workload.

use std::path::Path;

use crate::alloc::ARENA;
use crate::harness::Harness;
use crate::viz::{cell_color, Canvas};
use crate::workload::KINDS;

pub const LANE_COLORS: [(u8, u8, u8); 5] = [
    (150, 150, 150), // bump
    (245, 150, 60),  // freelist/first-fit
    (235, 215, 80),  // freelist/best-fit
    (90, 200, 235),  // buddy
    (235, 105, 205), // segfit
];

pub fn run(ops: u64, seed: u64, out_dir: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(out_dir)?;
    let sample_every = (ops / 400).max(1);

    for kind in KINDS {
        let mut h = Harness::new(kind, seed);
        let mut series: Vec<Vec<f32>> = vec![Vec::new(); h.lanes.len()];
        // snapshot the arena at the trace's busiest moment, not wherever the
        // run happens to stop (workloads are cyclic; the end can be empty)
        let mut best_live = 0u64;
        let mut best_cells: Vec<Vec<(f32, u8)>> =
            vec![vec![(0.0, 0); SNAP_W * SNAP_ROWS]; h.lanes.len()];

        let mut done = 0;
        while done < ops {
            h.run(sample_every);
            done += sample_every;
            for (i, lane) in h.lanes.iter().enumerate() {
                let (_, largest) = lane.alloc.free_space();
                series[i].push(largest as f32 / ARENA as f32);
            }
            if h.workload.live_bytes() > best_live {
                best_live = h.workload.live_bytes();
                for (i, lane) in h.lanes.iter().enumerate() {
                    lane.paint(&mut best_cells[i]);
                }
            }
        }

        // ---- table ----
        println!("\n## {} ({} ops, seed {})", kind.name(), ops, seed);
        println!(
            "{:<20} {:>7} {:>7} {:>7} {:>9} {:>10}",
            "allocator", "util%", "ovh%", "frag%", "big-free", "failures"
        );
        for lane in &h.lanes {
            let m = lane.metrics();
            println!(
                "{:<20} {:>7.1} {:>7.1} {:>7.1} {:>8}K {:>10}",
                lane.alloc.name(),
                m.util * 100.0,
                m.overhead * 100.0,
                m.ext_frag * 100.0,
                m.largest_free >> 10,
                m.failures
            );
        }

        snapshot(
            &best_cells,
            &out_dir.join(format!("arena-{}.png", kind.name())),
        )?;
        chart(&series, &out_dir.join(format!("frag-{}.png", kind.name())))?;
    }
    println!("\nimages written to {}", out_dir.display());
    Ok(())
}

const SNAP_W: usize = 256;
const SNAP_ROWS: usize = 8;

/// all five lanes as stacked pixel strips (256 cells wide × 8 rows, 4 px cells)
fn snapshot(lanes_cells: &[Vec<(f32, u8)>], path: &Path) -> std::io::Result<()> {
    const SCALE: usize = 4;
    const GAP: usize = 6;
    let lane_h = SNAP_ROWS * SCALE;
    let canvas_h = lanes_cells.len() * (lane_h + GAP) - GAP;
    let mut cv = Canvas::new(SNAP_W * SCALE, canvas_h, (12, 12, 16));

    for (li, cells) in lanes_cells.iter().enumerate() {
        let y0 = li * (lane_h + GAP);
        for row in 0..SNAP_ROWS {
            for x in 0..SNAP_W {
                let (cov, class) = cells[row * SNAP_W + x];
                cv.fill_rect(
                    x * SCALE,
                    y0 + row * SCALE,
                    SCALE,
                    SCALE,
                    cell_color(cov, class),
                );
            }
        }
    }
    cv.save(path)
}

/// largest free block over time, one line per allocator
fn chart(series: &[Vec<f32>], path: &Path) -> std::io::Result<()> {
    const W: usize = 960;
    const H: usize = 320;
    const M: usize = 12; // margin
    let mut cv = Canvas::new(W, H, (16, 16, 20));

    for frac in [0.25, 0.5, 0.75] {
        let y = M + ((1.0 - frac) * (H - 2 * M) as f64) as usize;
        for x in (M..W - M).step_by(4) {
            cv.set(x, y, (52, 52, 60));
        }
    }
    for (i, s) in series.iter().enumerate() {
        if s.is_empty() {
            continue;
        }
        let color = LANE_COLORS[i % LANE_COLORS.len()];
        let px = |j: usize| M + j * (W - 2 * M) / s.len().max(1);
        let py = |v: f32| M + ((1.0 - v as f64) * (H - 2 * M) as f64) as usize;
        for j in 1..s.len() {
            cv.line(px(j - 1), py(s[j - 1]), px(j), py(s[j]), color);
        }
    }
    cv.save(path)
}
