// Climate — hard part #2: orographic rainfall + temperature.
//
// Temperature: a latitude profile (hot equator, cold poles) minus an elevation
// lapse rate (~6.5°C/km), plus a small continentality penalty inland.
//
// Rainfall: we model prevailing winds as zonal bands (tropical easterlies,
// mid-latitude westerlies, polar easterlies) and march moisture parcels ALONG
// the wind. A parcel picks up humidity over water and drops it as rain when the
// air is forced up over rising terrain (orographic lift). The leeward side gets
// the leftover — that's how rain shadows (deserts behind mountains) emerge for
// free instead of being hand-painted.

import { Grid } from "./grid";

export function runClimate(grid: Grid) {
  const { w, h } = grid;

  // --- temperature ---
  for (let y = 0; y < h; y++) {
    const lat = grid.lat(y); // -1..1
    // base: ~31°C at equator down to ~-12°C at poles. cos^2 keeps the
    // temperate mid-latitudes genuinely temperate; the gentler pole gradient
    // widens the habitable band so worlds aren't dominated by ice sheets.
    const c = Math.cos((lat * Math.PI) / 2);
    const base = 31 - 43 * (1 - c * c);
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const el = grid.elevation[i];
      const lapse = el > 0 ? (el / 1000) * 6.5 : 0;
      grid.temperature[i] = base - lapse;
    }
  }

  // --- prevailing wind direction per latitude band (dx, dy) ---
  // returns horizontal wind sign; +1 blows east, -1 blows west.
  function windDir(lat: number): number {
    const a = Math.abs(lat);
    if (a < 0.33) return -1; // tropical easterlies (blow toward west)
    if (a < 0.66) return +1; // mid-lat westerlies
    return -1; // polar easterlies
  }

  // --- orographic rainfall march ---
  const rain = grid.rainfall;
  rain.fill(0);
  for (let y = 0; y < h; y++) {
    const dir = windDir(grid.lat(y));
    let humidity = 0.75; // start each band with some baseline moisture
    // march across the full width (+wrap) ~1.5 laps so wind equilibrates
    const start = dir > 0 ? 0 : w - 1;
    const steps = Math.round(w * 1.6);
    let x = start;
    let prevEl = grid.elevation[y * w + (((x % w) + w) % w)];
    for (let s = 0; s < steps; s++) {
      const xi = ((x % w) + w) % w;
      const i = y * w + xi;
      const el = grid.elevation[i];
      // warmer air over warm water holds more moisture
      if (el <= 0) {
        const evap = 0.04 * Math.max(0.2, (grid.temperature[i] + 10) / 40);
        humidity = Math.min(1.2, humidity + evap);
      } else {
        // rising terrain forces precipitation (orographic)
        const rise = Math.max(0, el - prevEl);
        const orographic = Math.min(humidity, rise / 1400);
        // plus baseline convective rain scaled by humidity & warmth
        const convective =
          humidity * 0.02 * Math.max(0, (grid.temperature[i] + 5) / 35);
        const precip = orographic + convective;
        rain[i] += precip;
        // lose the precipitated moisture, but only partially — terrestrial
        // transpiration recycles a lot of rain, so interiors stay watered
        // instead of becoming a single giant rain shadow.
        humidity = Math.max(0, humidity - precip * 0.6 - 0.002);
      }
      prevEl = el;
      x += dir;
    }
  }

  // light smoothing so rainfall isn't streaky along the wind rows
  smooth(grid, rain, 1);

  // normalize rainfall to 0..1 for downstream use
  let max = 1e-6;
  for (let i = 0; i < grid.n; i++) if (rain[i] > max) max = rain[i];
  for (let i = 0; i < grid.n; i++) rain[i] = Math.min(1, rain[i] / max);
}

function smooth(grid: Grid, field: Float32Array, passes: number) {
  const { w, h } = grid;
  for (let p = 0; p < passes; p++) {
    const next = new Float32Array(grid.n);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = y * w + x;
        let s = field[i];
        let c = 1;
        for (const j of grid.neighbors8(x, y)) {
          s += field[j];
          c++;
        }
        next[i] = s / c;
      }
    }
    field.set(next);
  }
}
