// Hydrology — hard part #3: real flow accumulation, not painted squiggles.
//
// Pipeline (the standard terrain-analysis chain):
//   1. Priority-flood depression filling: raise pits to their spill level so
//      every land cell has a downhill path to the sea. Where the fill is deeper
//      than the terrain, that's a LAKE (standing water).
//   2. D8 flow directions: each land cell points to its steepest-descent
//      neighbour on the filled surface.
//   3. Flow accumulation: process cells from high to low, pushing each cell's
//      (rainfall-weighted) water into its downstream neighbour. Cells that many
//      others drain through accumulate large flux -> those are rivers.
//
// Rivers therefore EMERGE from topology + rainfall; they always run downhill,
// merge into trunk streams, and end at the sea or a lake. That's the payoff of
// doing the real algorithm.

import { Grid } from "./grid";

// Binary min-heap keyed by elevation, storing cell indices.
class MinHeap {
  private keys: number[] = [];
  private vals: number[] = [];
  get size() {
    return this.vals.length;
  }
  push(val: number, key: number) {
    this.keys.push(key);
    this.vals.push(val);
    let i = this.vals.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (this.keys[p] <= this.keys[i]) break;
      this.swap(i, p);
      i = p;
    }
  }
  pop(): number {
    const top = this.vals[0];
    const lastV = this.vals.pop()!;
    const lastK = this.keys.pop()!;
    if (this.vals.length > 0) {
      this.vals[0] = lastV;
      this.keys[0] = lastK;
      let i = 0;
      const n = this.vals.length;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < n && this.keys[l] < this.keys[m]) m = l;
        if (r < n && this.keys[r] < this.keys[m]) m = r;
        if (m === i) break;
        this.swap(i, m);
        i = m;
      }
    }
    return top;
  }
  private swap(a: number, b: number) {
    [this.keys[a], this.keys[b]] = [this.keys[b], this.keys[a]];
    [this.vals[a], this.vals[b]] = [this.vals[b], this.vals[a]];
  }
}

export function runHydrology(grid: Grid) {
  const { w, h, n } = grid;
  const el = grid.elevation;

  // --- 1. priority-flood fill from ocean cells ---
  const filled = new Float32Array(n);
  const closed = new Uint8Array(n);
  const heap = new MinHeap();

  for (let i = 0; i < n; i++) {
    if (el[i] <= 0) {
      // ocean: fixed at its own level, seeds the flood
      filled[i] = el[i];
      closed[i] = 1;
      heap.push(i, el[i]);
    } else {
      filled[i] = Infinity;
    }
  }

  while (heap.size > 0) {
    const i = heap.pop();
    const x = grid.xOf(i);
    const y = grid.yOf(i);
    for (const j of grid.neighbors8(x, y)) {
      if (closed[j]) continue;
      // spill level: can't be lower than current cell's filled height
      const lvl = Math.max(el[j], filled[i] + 1e-3);
      if (lvl < filled[j]) {
        filled[j] = lvl;
        closed[j] = 1;
        heap.push(j, lvl);
      }
    }
  }

  // standing water = how much the fill exceeds the bare terrain (lakes)
  for (let i = 0; i < n; i++) {
    grid.waterLevel[i] = el[i] > 0 ? Math.max(0, filled[i] - el[i]) : 0;
  }

  // --- 2. D8 steepest descent on the filled surface ---
  const downstream = new Int32Array(n).fill(-1);
  const order: number[] = [];
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      if (el[i] <= 0) continue; // ocean drains out
      order.push(i);
      let best = -1;
      let bestDrop = 0;
      for (const j of grid.neighbors8(x, y)) {
        const drop = filled[i] - filled[j];
        if (drop > bestDrop) {
          bestDrop = drop;
          best = j;
        }
      }
      downstream[i] = best; // -1 if it's a sink/already at sea boundary
    }
  }

  // --- 3. accumulate flux high -> low ---
  order.sort((a, b) => filled[b] - filled[a]);
  const flow = grid.flow;
  flow.fill(0);
  for (const i of order) {
    // each land cell contributes its local rainfall
    flow[i] += 0.05 + grid.rainfall[i];
    const d = downstream[i];
    if (d >= 0 && el[d] > 0) flow[d] += flow[i];
  }
}

// Is this cell a river channel? (enough accumulated flux, above sea, not a big lake)
export function isRiver(grid: Grid, i: number, threshold = 6): boolean {
  return (
    grid.elevation[i] > 0 && grid.waterLevel[i] < 4 && grid.flow[i] > threshold
  );
}
