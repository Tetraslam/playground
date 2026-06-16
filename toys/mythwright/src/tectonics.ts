// Plate tectonics — hard part #1.
//
// We seed N plates as Voronoi cells over the cylinder, give each a drift vector
// and a crustal type (oceanic = dense/low, continental = buoyant/high), then
// build elevation from plate interactions:
//   - base height from crustal type + per-plate bias
//   - at plate BOUNDARIES, the relative motion of the two plates decides the
//     tectonic regime: convergent -> uplift (mountains) or subduction (trench),
//     divergent -> rifting (low), transform -> mild.
// The uplift is then diffused inland so ranges have foothills, not a 1px wall.
//
// This is a steady-state approximation of millions of years of drift, not a
// frame-by-frame plate animation — but the resulting topography is emergent
// from the plate layout + motions, and changes completely with the seed.

import { Grid, SEA_LEVEL } from "./grid";
import { RNG } from "./rng";

interface Plate {
  cx: number; // seed cell (centroid-ish) in grid coords
  cy: number;
  vx: number; // drift vector
  vy: number;
  oceanic: boolean;
  bias: number; // per-plate elevation offset
}

export function runTectonics(grid: Grid, rng: RNG, nPlates: number): Plate[] {
  const { w, h } = grid;
  const plates: Plate[] = [];

  for (let p = 0; p < nPlates; p++) {
    const oceanic = rng.next() < 0.55;
    plates.push({
      cx: rng.int(0, w - 1),
      cy: rng.int(0, h - 1),
      vx: rng.normal(0, 1),
      vy: rng.normal(0, 0.6),
      oceanic,
      bias: oceanic ? rng.range(-3500, -1500) : rng.range(300, 1800),
    });
  }

  // Assign each cell to nearest plate seed (cylindrical distance in x).
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let best = 0;
      let bestD = Infinity;
      for (let p = 0; p < nPlates; p++) {
        const pl = plates[p];
        let dx = Math.abs(x - pl.cx);
        dx = Math.min(dx, w - dx); // wrap
        const dy = y - pl.cy;
        const d = dx * dx + dy * dy;
        if (d < bestD) {
          bestD = d;
          best = p;
        }
      }
      const i = y * w + x;
      grid.plateId[i] = best;
      grid.elevation[i] = plates[best].bias;
    }
  }

  // Boundary interactions: where neighbouring cells belong to different plates,
  // compute relative motion along the boundary normal. Closing => uplift.
  const uplift = new Float32Array(grid.n);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const a = grid.plateId[i];
      for (const j of grid.neighbors4(x, y)) {
        const b = grid.plateId[j];
        if (b === a) continue;
        const pa = plates[a];
        const pb = plates[b];
        // boundary normal ~ direction from a's centroid to b's
        let nx = x - pa.cx;
        let ny = y - pa.cy;
        const nlen = Math.hypot(nx, ny) || 1;
        nx /= nlen;
        ny /= nlen;
        // relative closing speed (positive = converging)
        const rel = (pa.vx - pb.vx) * nx + (pa.vy - pb.vy) * ny;
        if (rel > 0) {
          // convergent: continent-continent -> big mountains; with ocean -> trench+arc
          if (!pa.oceanic && !pb.oceanic) uplift[i] += rel * 2600;
          else if (pa.oceanic && pb.oceanic) uplift[i] += rel * 700;
          else if (!pa.oceanic)
            uplift[i] += rel * 2000; // overriding continent
          else uplift[i] -= rel * 1500; // subducting ocean -> trench
        } else {
          uplift[i] += rel * 600; // divergent -> rift valley (rel<0 lowers)
        }
      }
    }
  }

  // Diffuse uplift inland: spread the boundary uplift into foothills while
  // keeping the ridge crest tall (max with original, not pure average).
  let buf = uplift;
  for (let pass = 0; pass < 5; pass++) {
    const next = new Float32Array(grid.n);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = y * w + x;
        let s = buf[i];
        let c = 1;
        for (const j of grid.neighbors8(x, y)) {
          s += buf[j] * 0.5;
          c += 0.5;
        }
        // blend the smoothed value with the crest so peaks survive
        next[i] = Math.max(buf[i] * 0.82, (s / c) * 0.99);
      }
    }
    buf = next;
  }
  for (let i = 0; i < grid.n; i++) grid.elevation[i] += buf[i];

  // Add fractal roughness (value-noise octaves) so coasts/interiors aren't flat.
  addFractalNoise(grid, rng, 1700);

  // Gentle pole-ward continental shelf bias + clamp.
  for (let i = 0; i < grid.n; i++) {
    grid.elevation[i] = Math.max(-9000, Math.min(7000, grid.elevation[i]));
  }

  void SEA_LEVEL;
  return plates;
}

// Cheap tileable value noise summed over octaves, added to elevation.
function addFractalNoise(grid: Grid, rng: RNG, amp: number) {
  const { w, h } = grid;
  for (let oct = 0; oct < 4; oct++) {
    const cells = 4 << oct;
    const gw = cells;
    const gh = Math.max(2, Math.round((cells * h) / w));
    const lattice = new Float32Array(gw * gh);
    for (let k = 0; k < lattice.length; k++) lattice[k] = rng.range(-1, 1);
    const a = amp / (oct + 1);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const fx = (x / w) * gw;
        const fy = (y / h) * gh;
        const x0 = Math.floor(fx) % gw;
        const y0 = Math.min(gh - 1, Math.floor(fy));
        const x1 = (x0 + 1) % gw;
        const y1 = Math.min(gh - 1, y0 + 1);
        const tx = fx - Math.floor(fx);
        const ty = fy - Math.floor(fy);
        const v00 = lattice[y0 * gw + x0];
        const v10 = lattice[y0 * gw + x1];
        const v01 = lattice[y1 * gw + x0];
        const v11 = lattice[y1 * gw + x1];
        const sx = tx * tx * (3 - 2 * tx);
        const sy = ty * ty * (3 - 2 * ty);
        const top = v00 + (v10 - v00) * sx;
        const bot = v01 + (v11 - v01) * sx;
        grid.elevation[y * w + x] += (top + (bot - top) * sy) * a;
      }
    }
  }
}
