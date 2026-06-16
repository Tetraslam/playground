// Orchestrator: builds a complete world from a seed by running the geophysical
// pipeline in order (each layer depends on the previous), then hands back a
// World you can attach a History to and simulate forward.

import { Grid } from "./grid";
import { RNG, seedFromString } from "./rng";
import { runTectonics } from "./tectonics";
import { runClimate } from "./climate";
import { runHydrology } from "./hydrology";
import { classifyBiomes } from "./biomes";

export interface WorldConfig {
  w: number;
  h: number;
  plates: number;
  seed: number;
}

export class World {
  grid: Grid;
  rng: RNG;
  config: WorldConfig;
  seaFraction = 0;

  constructor(config: WorldConfig) {
    this.config = config;
    this.grid = new Grid(config.w, config.h);
    this.rng = new RNG(config.seed);
    this.generate();
  }

  static fromName(name: string, w = 200, h = 96, plates = 11): World {
    return new World({ w, h, plates, seed: seedFromString(name) });
  }

  generate() {
    const g = this.grid;
    runTectonics(g, this.rng, this.config.plates);
    this.calibrateSeaLevel();
    runClimate(g);
    runHydrology(g);
    classifyBiomes(g);
    let sea = 0;
    for (let i = 0; i < g.n; i++) if (g.elevation[i] <= 0) sea++;
    this.seaFraction = sea / g.n;
  }

  // Shift elevations so a target fraction (~62%) of the world is ocean — keeps
  // every seed looking like a planet rather than all-land or all-sea.
  private calibrateSeaLevel(target = 0.62) {
    const g = this.grid;
    const sorted = Float32Array.from(g.elevation).sort();
    const cut = sorted[Math.floor(target * sorted.length)];
    for (let i = 0; i < g.n; i++) g.elevation[i] -= cut;
  }
}
