// The world substrate: a W×H cylindrical grid (wraps E–W, hard poles N–S).
// Every simulation layer (tectonics, climate, hydrology, biomes, settlement)
// reads and writes typed arrays on this grid. Keeping it flat + typed makes the
// per-tick passes cheap enough to animate.

export class Grid {
  readonly w: number;
  readonly h: number;
  readonly n: number;

  // Geophysical fields, all length w*h.
  elevation: Float32Array; // metres, roughly [-8000, 6000]
  plateId: Int16Array; // which tectonic plate owns this cell
  temperature: Float32Array; // °C, annual mean
  rainfall: Float32Array; // arbitrary 0..1 moisture supply
  flow: Float32Array; // accumulated water flux (river strength)
  waterLevel: Float32Array; // standing water depth (lakes/sea fill)
  biome: Uint8Array; // biome enum index
  fertility: Float32Array; // 0..1 habitability for settlement

  constructor(w: number, h: number) {
    this.w = w;
    this.h = h;
    this.n = w * h;
    this.elevation = new Float32Array(this.n);
    this.plateId = new Int16Array(this.n);
    this.temperature = new Float32Array(this.n);
    this.rainfall = new Float32Array(this.n);
    this.flow = new Float32Array(this.n);
    this.waterLevel = new Float32Array(this.n);
    this.biome = new Uint8Array(this.n);
    this.fertility = new Float32Array(this.n);
  }

  idx(x: number, y: number): number {
    // wrap x (cylinder), clamp y (poles)
    const xx = ((x % this.w) + this.w) % this.w;
    const yy = y < 0 ? 0 : y >= this.h ? this.h - 1 : y;
    return yy * this.w + xx;
  }

  // 4-neighbourhood (N,E,S,W) with E–W wrap, as indices. North/south past the
  // pole are clamped (returns same row), callers filter self-references.
  neighbors4(x: number, y: number): number[] {
    return [
      this.idx(x, y - 1),
      this.idx(x + 1, y),
      this.idx(x, y + 1),
      this.idx(x - 1, y),
    ];
  }

  neighbors8(x: number, y: number): number[] {
    const out: number[] = [];
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        if (dx === 0 && dy === 0) continue;
        out.push(this.idx(x + dx, y + dy));
      }
    }
    return out;
  }

  // latitude in [-1 (south pole), +1 (north pole)] for a row.
  lat(y: number): number {
    return 1 - (2 * y) / (this.h - 1);
  }

  xOf(i: number): number {
    return i % this.w;
  }
  yOf(i: number): number {
    return Math.floor(i / this.w);
  }
}

export const SEA_LEVEL = 0; // elevation 0 = coastline
