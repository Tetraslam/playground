// Biomes via a Whittaker-style classification: temperature × moisture decides
// the biome, with effective moisture boosted near rivers/lakes. Fertility (the
// habitability field that drives settlement) falls out of biome + water access
// + slope: people settle warm, watered, flattish, non-frozen, non-desert land,
// and they love coasts and riverbanks.

import { Grid } from "./grid";
import { isRiver } from "./hydrology";

export enum Biome {
  Ocean = 0,
  Lake,
  Ice,
  Tundra,
  Taiga,
  Grassland,
  Shrubland,
  TemperateForest,
  Rainforest,
  Savanna,
  Desert,
  Mountain,
  Beach,
}

export const BIOME_NAMES: Record<Biome, string> = {
  [Biome.Ocean]: "ocean",
  [Biome.Lake]: "lake",
  [Biome.Ice]: "ice",
  [Biome.Tundra]: "tundra",
  [Biome.Taiga]: "taiga",
  [Biome.Grassland]: "grassland",
  [Biome.Shrubland]: "shrubland",
  [Biome.TemperateForest]: "forest",
  [Biome.Rainforest]: "rainforest",
  [Biome.Savanna]: "savanna",
  [Biome.Desert]: "desert",
  [Biome.Mountain]: "mountain",
  [Biome.Beach]: "coast",
};

export function classifyBiomes(grid: Grid) {
  const { w, h } = grid;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const el = grid.elevation[i];
      const t = grid.temperature[i];

      if (el <= 0) {
        grid.biome[i] = Biome.Ocean;
        continue;
      }
      if (grid.waterLevel[i] > 4) {
        grid.biome[i] = Biome.Lake;
        continue;
      }
      // coastal beach: low land next to ocean
      let coastal = false;
      for (const j of grid.neighbors8(x, y)) {
        if (grid.elevation[j] <= 0) {
          coastal = true;
          break;
        }
      }
      if (coastal && el < 120) {
        grid.biome[i] = Biome.Beach;
        continue;
      }
      // high, cold peaks are rock/ice; the line scales with temperature so
      // tropical mountains can be bare rock while only truly cold ones glaciate
      if (el > 4000) {
        grid.biome[i] = t < -6 ? Biome.Ice : Biome.Mountain;
        continue;
      }

      // effective moisture: rainfall + river bonus
      let m = grid.rainfall[i];
      if (isRiver(grid, i)) m = Math.min(1, m + 0.3);

      if (t < -8) grid.biome[i] = Biome.Ice;
      else if (t < -2) grid.biome[i] = Biome.Tundra;
      else if (t < 6) grid.biome[i] = m > 0.3 ? Biome.Taiga : Biome.Tundra;
      else if (t < 21) {
        if (m > 0.45) grid.biome[i] = Biome.TemperateForest;
        else if (m > 0.18) grid.biome[i] = Biome.Grassland;
        else grid.biome[i] = Biome.Shrubland;
      } else {
        if (m > 0.5) grid.biome[i] = Biome.Rainforest;
        else if (m > 0.2) grid.biome[i] = Biome.Savanna;
        else grid.biome[i] = Biome.Desert;
      }
    }
  }
  computeFertility(grid);
}

function computeFertility(grid: Grid) {
  const { w, h } = grid;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const b = grid.biome[i];
      if (grid.elevation[i] <= 0 || b === Biome.Lake) {
        grid.fertility[i] = 0;
        continue;
      }
      // base habitability by biome
      const base: Partial<Record<Biome, number>> = {
        [Biome.Grassland]: 0.85,
        [Biome.TemperateForest]: 0.8,
        [Biome.Savanna]: 0.7,
        [Biome.Shrubland]: 0.55,
        [Biome.Rainforest]: 0.6,
        [Biome.Taiga]: 0.4,
        [Biome.Beach]: 0.75,
        [Biome.Tundra]: 0.2,
        [Biome.Desert]: 0.12,
        [Biome.Mountain]: 0.1,
        [Biome.Ice]: 0.02,
      };
      let f = base[b as Biome] ?? 0.3;

      // slope penalty
      let maxd = 0;
      for (const j of grid.neighbors8(x, y)) {
        const d = Math.abs(grid.elevation[i] - grid.elevation[j]);
        if (d > maxd) maxd = d;
      }
      f *= Math.max(0.3, 1 - maxd / 1800);

      // water access bonus: rivers, lakes, coasts within reach
      let water = 0;
      for (const j of grid.neighbors8(x, y)) {
        if (grid.elevation[j] <= 0 || grid.waterLevel[j] > 2)
          water = Math.max(water, 0.25);
        if (grid.flow[j] > 6) water = Math.max(water, 0.3);
      }
      f += water;

      grid.fertility[i] = Math.max(0, Math.min(1, f));
    }
  }
}
