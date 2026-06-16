// Color mapping for the render layers. Returns [r,g,b] 0..255.
// The view is the WINDOW onto the sim — these mappings just expose the fields.

import { Grid } from "./grid";
import { Biome } from "./biomes";
import { isRiver } from "./hydrology";

export type RGB = [number, number, number];
export type LayerMode =
  | "biome"
  | "elevation"
  | "temperature"
  | "rainfall"
  | "political";

const BIOME_COLORS: Record<Biome, RGB> = {
  [Biome.Ocean]: [20, 52, 96],
  [Biome.Lake]: [54, 110, 168],
  [Biome.Ice]: [232, 238, 246],
  [Biome.Tundra]: [150, 158, 140],
  [Biome.Taiga]: [62, 96, 78],
  [Biome.Grassland]: [128, 162, 78],
  [Biome.Shrubland]: [150, 150, 88],
  [Biome.TemperateForest]: [54, 118, 64],
  [Biome.Rainforest]: [28, 92, 52],
  [Biome.Savanna]: [176, 162, 90],
  [Biome.Desert]: [208, 188, 128],
  [Biome.Mountain]: [120, 110, 104],
  [Biome.Beach]: [214, 200, 150],
};

function lerp(a: RGB, b: RGB, t: number): RGB {
  return [
    Math.round(a[0] + (b[0] - a[0]) * t),
    Math.round(a[1] + (b[1] - a[1]) * t),
    Math.round(a[2] + (b[2] - a[2]) * t),
  ];
}

function hsl(h: number, s: number, l: number): RGB {
  h = ((h % 360) + 360) % 360;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let r = 0,
    g = 0,
    b = 0;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  return [
    Math.round((r + m) * 255),
    Math.round((g + m) * 255),
    Math.round((b + m) * 255),
  ];
}

export function cellColor(
  grid: Grid,
  i: number,
  mode: LayerMode,
  territory?: Int16Array,
  cultureHue?: (id: number) => number,
): RGB {
  const el = grid.elevation[i];
  const isOcean = el <= 0;

  if (mode === "elevation") {
    if (isOcean) {
      const t = Math.min(1, -el / 6000);
      return lerp([42, 78, 130], [8, 16, 44], t);
    }
    const t = Math.min(1, el / 5000);
    return lerp([72, 120, 70], [240, 240, 240], t);
  }

  if (mode === "temperature") {
    const tC = grid.temperature[i];
    const t = Math.min(1, Math.max(0, (tC + 25) / 60));
    return lerp([40, 70, 200], [220, 60, 40], t);
  }

  if (mode === "rainfall") {
    if (isOcean) return [16, 24, 48];
    const t = grid.rainfall[i];
    return lerp([180, 150, 90], [30, 90, 180], t);
  }

  if (mode === "political") {
    if (isOcean) return [16, 28, 52];
    const c = territory ? territory[i] : -1;
    if (c < 0 || !cultureHue) {
      // unclaimed land: muted biome
      const base = BIOME_COLORS[grid.biome[i] as Biome] ?? [60, 60, 60];
      return lerp(base, [40, 40, 44], 0.55);
    }
    const hue = cultureHue(c);
    const shade = 0.32 + 0.18 * grid.fertility[i];
    return hsl(hue, 0.6, shade);
  }

  // biome mode (default)
  let col = BIOME_COLORS[grid.biome[i] as Biome] ?? [80, 80, 80];
  // hillshade: brighten west-facing, darken east-facing slopes
  if (!isOcean) {
    const x = grid.xOf(i);
    const y = grid.yOf(i);
    const wEl = grid.elevation[grid.idx(x - 1, y)];
    const eEl = grid.elevation[grid.idx(x + 1, y)];
    const slope = (wEl - eEl) / 1200;
    const sh = Math.max(-0.25, Math.min(0.25, slope));
    col = [
      clamp(col[0] * (1 + sh)),
      clamp(col[1] * (1 + sh)),
      clamp(col[2] * (1 + sh)),
    ];
    if (isRiver(grid, i)) col = lerp(col, [70, 130, 200], 0.6);
  }
  return col;
}

function clamp(v: number): number {
  return Math.max(0, Math.min(255, Math.round(v)));
}
