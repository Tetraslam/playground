// Headless sanity check: build a world, run some history, print stats. Proves
// the engine works without needing the TUI. `bun run src/smoke.ts [name]`.

import { World } from "./world";
import { History } from "./civ";
import { isRiver } from "./hydrology";
import { Biome, BIOME_NAMES } from "./biomes";

const name = process.argv[2] ?? "Qurwenya";
const t0 = performance.now();
const world = World.fromName(name);
const genMs = performance.now() - t0;

const g = world.grid;
let land = 0,
  river = 0,
  maxEl = -Infinity,
  minEl = Infinity;
const biomeCount: Record<number, number> = {};
for (let i = 0; i < g.n; i++) {
  if (g.elevation[i] > 0) land++;
  if (isRiver(g, i)) river++;
  maxEl = Math.max(maxEl, g.elevation[i]);
  minEl = Math.min(minEl, g.elevation[i]);
  biomeCount[g.biome[i]] = (biomeCount[g.biome[i]] ?? 0) + 1;
}

console.log(`world "${name}"  ${g.w}x${g.h}  gen ${genMs.toFixed(0)}ms`);
console.log(`  sea fraction : ${(world.seaFraction * 100).toFixed(1)}%`);
console.log(`  elevation    : ${minEl.toFixed(0)}..${maxEl.toFixed(0)} m`);
console.log(`  land cells   : ${land}   river cells: ${river}`);
console.log(
  "  biomes       : " +
    Object.entries(biomeCount)
      .sort((a, b) => b[1] - a[1])
      .map(([b, c]) => `${BIOME_NAMES[Number(b) as Biome]}=${c}`)
      .join(" "),
);

const hist = new History(g, world.rng);
hist.seed(6);
const steps = 40;
const ts = performance.now();
for (let i = 0; i < steps; i++) hist.step();
const simMs = performance.now() - ts;

console.log(`\nhistory: ${steps} centuries in ${simMs.toFixed(0)}ms`);
console.log(`  settlements  : ${hist.settlements.length}`);
console.log(`  cultures     : ${hist.cultures.map((c) => c.name).join(", ")}`);
console.log(`  total pop    : ${hist.totalPop().toFixed(0)}k`);
console.log(`  trade routes : ${hist.routes.length}`);
const biggest = [...hist.settlements].sort((a, b) => b.pop - a.pop).slice(0, 5);
console.log(
  "  metropolises : " +
    biggest.map((s) => `${s.name}(${s.pop.toFixed(0)}k)`).join(", "),
);
console.log("\nlast events:");
for (const l of hist.log.slice(-5)) console.log("  " + l);
