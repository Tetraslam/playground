// mythwright — the animated terminal window onto a living world.
//
// The engine (world.ts + civ.ts) is the toy; this file is the WINDOW. It paints
// the W×H world grid into a half-block framebuffer (two map rows per character
// cell, so the map is crisp), overlays settlements + trade routes, and runs the
// history simulation forward in real time. You poke it mid-flight:
//
//   space   play / pause history
//   . (>)   single-step one century
//   1..5    switch map layer (biome/elevation/temp/rainfall/political)
//   n       new random world (re-seeds everything)
//   r       replay this world's history from year 0
//   + / -   faster / slower
//   q / esc quit
//
// Nothing is pre-rendered: every frame recolors the grid from live fields and
// the civ layer advances, so which cultures dominate and where trade flows is
// emergent and different every run.

import {
  createCliRenderer,
  FrameBufferRenderable,
  TextRenderable,
  BoxRenderable,
  RGBA,
} from "@opentui/core";
import { World } from "./world";
import { History } from "./civ";
import { cellColor, LayerMode } from "./palette";
import { seedFromString } from "./rng";

const LAYERS: LayerMode[] = [
  "biome",
  "elevation",
  "temperature",
  "rainfall",
  "political",
];
const LAYER_KEYS: Record<string, number> = {
  "1": 0,
  "2": 1,
  "3": 2,
  "4": 3,
  "5": 4,
};

const WORLD_W = 160;
const WORLD_H = 96; // even -> clean half-block pairing

function randomName(): string {
  const a = [
    "aur",
    "vel",
    "kor",
    "tha",
    "ysk",
    "mor",
    "eld",
    "quor",
    "sev",
    "nim",
    "bel",
    "dra",
    "ith",
    "oss",
  ];
  const b = [
    "enya",
    "wen",
    "oth",
    "mar",
    "dor",
    "ix",
    "and",
    "ul",
    "een",
    "or",
    "ara",
    "is",
    "eth",
  ];
  return (
    a[Math.floor(Math.random() * a.length)] +
    b[Math.floor(Math.random() * b.length)]
  );
}

async function main() {
  const renderer = await createCliRenderer({ targetFps: 30 });
  renderer.setBackgroundColor("#0a0d16");

  // map framebuffer: one char cell holds two vertical map pixels via "▀"
  const mapCols = WORLD_W;
  const mapRows = WORLD_H / 2;

  const map = new FrameBufferRenderable(renderer, {
    id: "map",
    width: mapCols,
    height: mapRows,
    position: "absolute",
    left: 1,
    top: 1,
  });
  renderer.root.add(map);

  const panel = new BoxRenderable(renderer, {
    id: "panel",
    width: 40,
    height: mapRows + 2,
    position: "absolute",
    left: mapCols + 2,
    top: 0,
    borderStyle: "rounded",
    borderColor: "#3a4566",
    title: " mythwright ",
    titleAlignment: "center",
  });
  renderer.root.add(panel);

  const info = new TextRenderable(renderer, {
    id: "info",
    content: "",
    position: "absolute",
    left: mapCols + 4,
    top: 1,
    fg: "#c8d2e8",
  });
  renderer.root.add(info);

  const help = new TextRenderable(renderer, {
    id: "help",
    content:
      "space play/pause   . step   1-5 layer\n" +
      "n new world   r replay   +/- speed   q quit",
    position: "absolute",
    left: 1,
    top: mapRows + 1,
    fg: "#5b678a",
  });
  renderer.root.add(help);

  // --- simulation state ---
  let worldName = "Qurwenya";
  let world: World;
  let hist: History;
  let layer = 0;
  let playing = true;
  let stepEveryFrames = 6; // history step cadence (lower = faster)
  let frame = 0;

  function rebuild(name: string, seed?: number) {
    worldName = name;
    world = new World({
      w: WORLD_W,
      h: WORLD_H,
      plates: 11,
      seed: seed ?? seedFromString(name),
    });
    hist = new History(world.grid, world.rng);
    hist.seed(7);
    frame = 0;
  }

  rebuild(worldName);

  const cultureHue = (id: number) => hist.cultures[id]?.hue ?? 0;

  function paint() {
    const fb = map.frameBuffer;
    const g = world.grid;
    const mode = LAYERS[layer];
    const territory = hist.territory;

    // two map rows -> one char row (top=fg via ▀, bottom=bg)
    for (let cy = 0; cy < mapRows; cy++) {
      const yTop = cy * 2;
      const yBot = yTop + 1;
      for (let x = 0; x < mapCols; x++) {
        const top = cellColor(g, yTop * g.w + x, mode, territory, cultureHue);
        const bot = cellColor(g, yBot * g.w + x, mode, territory, cultureHue);
        fb.setCell(
          x,
          cy,
          "\u2580", // ▀ upper half block
          RGBA.fromInts(top[0], top[1], top[2], 255),
          RGBA.fromInts(bot[0], bot[1], bot[2], 255),
        );
      }
    }

    // trade routes: blend a warm thread over whatever's underneath, opacity
    // scaled by route volume so the busy arteries glow brighter.
    for (const route of hist.routes) {
      const intensity = Math.min(1, route.volume / 80);
      const alpha = Math.round(120 + 110 * intensity);
      const col = RGBA.fromInts(248, 232, 150, alpha);
      for (const ci of route.path) {
        const cy = Math.floor(g.yOf(ci) / 2);
        fb.setCellWithAlphaBlending(g.xOf(ci), cy, "\u2580", col, col, 0);
      }
    }

    // settlements: size glyph by population
    for (const s of hist.settlements) {
      const cy = Math.floor(s.y / 2);
      const glyph = s.pop > 12 ? "\u25C9" : s.pop > 6 ? "\u25CF" : "\u00B7"; // ◉ ● ·
      const hue = cultureHue(s.cultureId);
      const c = hueToRGBA(hue, 0.7, 0.72);
      fb.setCell(s.x, cy, glyph, c, RGBA.fromInts(10, 13, 22, 255));
    }
  }

  function updateInfo() {
    const big = [...hist.settlements].sort((a, b) => b.pop - a.pop).slice(0, 7);
    const lines: string[] = [];
    lines.push(`world   ${worldName}`);
    lines.push(`year    ${hist.tick * 100}`);
    lines.push(`layer   ${LAYERS[layer]}  ${playing ? "▶" : "⏸"}`);
    lines.push(`sea     ${(world.seaFraction * 100).toFixed(0)}%`);
    lines.push("");
    lines.push(
      `cultures ${hist.cultures.length}   towns ${hist.settlements.length}`,
    );
    lines.push(
      `pop      ${hist.totalPop().toFixed(0)}k   routes ${hist.routes.length}`,
    );
    lines.push("");
    lines.push("largest settlements");
    for (const s of big) {
      const cult = hist.cultures[s.cultureId]?.name ?? "?";
      lines.push(
        `  ${s.name.padEnd(11)} ${s.pop.toFixed(0).padStart(3)}k ${cult}`,
      );
    }
    lines.push("");
    lines.push("recent history");
    for (const l of hist.log.slice(-4)) lines.push("  " + l.slice(0, 34));
    info.content = lines.join("\n");
  }

  // continuous render loop: advance history on cadence, repaint every frame
  renderer.setFrameCallback(async () => {
    frame++;
    if (playing && frame % stepEveryFrames === 0) hist.step();
    paint();
    updateInfo();
  });
  renderer.start();

  const keys = renderer.keyInput as unknown as {
    on(
      ev: "keypress",
      cb: (key: { name?: string; sequence?: string }) => void,
    ): void;
  };
  keys.on("keypress", (key) => {
    const k = key.name ?? key.sequence ?? "";
    if (k === "q" || k === "escape") {
      renderer.stop();
      renderer.destroy?.();
      process.exit(0);
    } else if (k === "space") {
      playing = !playing;
    } else if (k === "." || k === ">") {
      hist.step();
    } else if (k === "n") {
      rebuild(randomName(), (Math.random() * 0xffffffff) >>> 0);
    } else if (k === "r") {
      rebuild(worldName, world.config.seed);
    } else if (k === "+" || k === "=") {
      stepEveryFrames = Math.max(1, stepEveryFrames - 1);
    } else if (k === "-" || k === "_") {
      stepEveryFrames = Math.min(30, stepEveryFrames + 1);
    } else if (k in LAYER_KEYS) {
      layer = LAYER_KEYS[k];
    }
  });
}

function hueToRGBA(h: number, s: number, l: number): RGBA {
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
  return RGBA.fromInts(
    Math.round((r + m) * 255),
    Math.round((g + m) * 255),
    Math.round((b + m) * 255),
    255,
  );
}

main();
