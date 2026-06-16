// Headless snapshot: build a world, run N centuries of history, and write a PNG
// of any layer — no terminal/window needed. Doubles as the example-frame
// generator for the README. Uses the SAME cellColor mapping as the live TUI, so
// a snapshot is exactly a frame of the running system.
//
//   bun run src/snapshot.ts <name> <years> <layer> <outfile> [scale]
//   bun run src/snapshot.ts Qurwenya 2500 biome examples/qurwenya-biome.png 4

import { World } from "./world";
import { History } from "./civ";
import { cellColor, LayerMode } from "./palette";
import { seedFromString } from "./rng";

const name = process.argv[2] ?? "Qurwenya";
const years = Number(process.argv[3] ?? 2500);
const layer = (process.argv[4] ?? "biome") as LayerMode;
const out = process.argv[5] ?? `examples/${name.toLowerCase()}-${layer}.png`;
const scale = Number(process.argv[6] ?? 4);

const W = 160;
const H = 96;
const world = new World({ w: W, h: H, plates: 11, seed: seedFromString(name) });
const hist = new History(world.grid, world.rng);
hist.seed(7);
const steps = Math.round(years / 100);
for (let i = 0; i < steps; i++) hist.step();

const g = world.grid;
const cultureHue = (id: number) => hist.cultures[id]?.hue ?? 0;

// build RGB buffer at native resolution
const pix = new Uint8Array(W * H * 3);
for (let y = 0; y < H; y++) {
  for (let x = 0; x < W; x++) {
    const [r, gg, b] = cellColor(
      g,
      y * W + x,
      layer,
      hist.territory,
      cultureHue,
    );
    const o = (y * W + x) * 3;
    pix[o] = r;
    pix[o + 1] = gg;
    pix[o + 2] = b;
  }
}

// overlay routes + settlements directly into the pixel buffer for political/biome
function blend(
  x: number,
  y: number,
  r: number,
  gg: number,
  b: number,
  a: number,
) {
  if (x < 0 || x >= W || y < 0 || y >= H) return;
  const o = (y * W + x) * 3;
  pix[o] = Math.round(pix[o] * (1 - a) + r * a);
  pix[o + 1] = Math.round(pix[o + 1] * (1 - a) + gg * a);
  pix[o + 2] = Math.round(pix[o + 2] * (1 - a) + b * a);
}
for (const route of hist.routes) {
  const intensity = Math.min(1, route.volume / 80);
  for (const ci of route.path)
    blend(g.xOf(ci), g.yOf(ci), 248, 232, 150, 0.35 + 0.4 * intensity);
}
for (const s of hist.settlements) {
  const big = s.pop > 12;
  blend(s.x, s.y, 255, 255, 255, big ? 0.95 : 0.7);
  if (big) {
    blend(s.x - 1, s.y, 255, 255, 255, 0.5);
    blend(s.x + 1, s.y, 255, 255, 255, 0.5);
    blend(s.x, s.y - 1, 255, 255, 255, 0.5);
    blend(s.x, s.y + 1, 255, 255, 255, 0.5);
  }
}

// nearest-neighbour upscale, write a binary PPM (P6), pipe to magick for PNG
const SW = W * scale;
const SH = H * scale;
const header = `P6\n${SW} ${SH}\n255\n`;
const body = new Uint8Array(SW * SH * 3);
for (let y = 0; y < SH; y++) {
  const sy = Math.floor(y / scale);
  for (let x = 0; x < SW; x++) {
    const sx = Math.floor(x / scale);
    const src = (sy * W + sx) * 3;
    const dst = (y * SW + x) * 3;
    body[dst] = pix[src];
    body[dst + 1] = pix[src + 1];
    body[dst + 2] = pix[src + 2];
  }
}

const ppm = new Uint8Array(header.length + body.length);
ppm.set(new TextEncoder().encode(header), 0);
ppm.set(body, header.length);

// convert PPM -> PNG via magick (installed in the playground)
const proc = Bun.spawn(["magick", "ppm:-", "-strip", out], { stdin: "pipe" });
proc.stdin.write(ppm);
proc.stdin.end();
await proc.exited;

console.log(
  `${out}  ${SW}x${SH}  "${name}" @ ${years}y  layer=${layer}  ` +
    `${hist.settlements.length} towns, ${hist.cultures.length} cultures, ${hist.routes.length} routes`,
);
