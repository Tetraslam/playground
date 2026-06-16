// Civilization — hard part #4, and the part that runs OVER TIME and surprises
// its author. The geophysical world is fixed; history is not.
//
// Each tick (a "century"):
//   - every settlement grows toward the local carrying capacity (logistic),
//     capacity = sum of fertility in its claimed hinterland.
//   - settlements claim nearby unclaimed fertile cells into their territory.
//   - when a settlement is large + crowded, it sends out a COLONIST that walks
//     down a fertility gradient to found a new town (founding a daughter of the
//     same culture).
//   - cultures are colours; territory is contested at borders by relative pop.
//   - trade routes are least-cost paths (Dijkstra over terrain movement cost)
//     between the largest nearby settlements; route volume scales with the
//     product of populations / distance (a gravity model).
//
// Nothing here is scripted: which sites become metropolises, which cultures
// dominate, and where the trade arteries run all emerge from the terrain + the
// dynamics. Re-run a seed's history and poke it; it diverges in interesting ways.

import { Grid } from "./grid";
import { RNG } from "./rng";

export interface Settlement {
  id: number;
  x: number;
  y: number;
  cultureId: number;
  pop: number; // thousands
  founded: number; // tick founded
  name: string;
}

export interface Culture {
  id: number;
  name: string;
  hue: number; // 0..360 for rendering territory
  originSettlement: number;
}

export interface TradeRoute {
  a: number; // settlement id
  b: number;
  path: number[]; // cell indices
  volume: number;
}

export class History {
  grid: Grid;
  rng: RNG;
  tick = 0;
  settlements: Settlement[] = [];
  cultures: Culture[] = [];
  routes: TradeRoute[] = [];
  territory: Int16Array; // cultureId per cell, -1 = unclaimed
  owner: Int32Array; // settlement id controlling the cell, -1 = none
  private nextSettlement = 0;
  private nextCulture = 0;
  log: string[] = [];

  constructor(grid: Grid, rng: RNG) {
    this.grid = grid;
    this.rng = rng;
    this.territory = new Int16Array(grid.n).fill(-1);
    this.owner = new Int32Array(grid.n).fill(-1);
  }

  // seed initial city-states at the most fertile, well-separated sites
  seed(nCultures: number) {
    const candidates: number[] = [];
    for (let i = 0; i < this.grid.n; i++) {
      if (this.grid.fertility[i] > 0.6) candidates.push(i);
    }
    candidates.sort((a, b) => this.grid.fertility[b] - this.grid.fertility[a]);

    const minSep = Math.max(6, Math.floor(this.grid.w / (nCultures + 2)));
    for (const i of candidates) {
      if (this.cultures.length >= nCultures) break;
      const x = this.grid.xOf(i);
      const y = this.grid.yOf(i);
      let ok = true;
      for (const s of this.settlements) {
        let dx = Math.abs(s.x - x);
        dx = Math.min(dx, this.grid.w - dx);
        if (Math.hypot(dx, s.y - y) < minSep) {
          ok = false;
          break;
        }
      }
      if (!ok) continue;
      const cult: Culture = {
        id: this.nextCulture++,
        name: this.cultureName(),
        hue: (this.cultures.length * 360) / nCultures + this.rng.range(-12, 12),
        originSettlement: this.nextSettlement,
      };
      this.cultures.push(cult);
      this.found(x, y, cult.id);
    }
    this.log.push(`founded ${this.cultures.length} city-states`);
  }

  private found(x: number, y: number, cultureId: number): Settlement {
    const s: Settlement = {
      id: this.nextSettlement++,
      x,
      y,
      cultureId,
      pop: 2 + this.rng.range(0, 3),
      founded: this.tick,
      name: this.settlementName(),
    };
    this.settlements.push(s);
    const i = this.grid.idx(x, y);
    this.territory[i] = cultureId;
    this.owner[i] = s.id;
    return s;
  }

  // advance one century
  step() {
    this.tick++;
    this.claimTerritory();
    this.growPopulations();
    this.colonize();
    if (this.tick % 2 === 0) this.computeTrade();
  }

  // settlements expand their borders into adjacent fertile, unclaimed/weaker land
  private claimTerritory() {
    const { grid } = this;
    // pressure each settlement can project ~ sqrt(pop)
    const frontier: Array<[number, number]> = []; // [cellIndex, settlementId]
    for (const s of this.settlements) {
      const reach = 1 + Math.floor(Math.sqrt(s.pop) / 2.2);
      for (let dy = -reach; dy <= reach; dy++) {
        for (let dx = -reach; dx <= reach; dx++) {
          const i = grid.idx(s.x + dx, s.y + dy);
          if (grid.fertility[i] <= 0.05) continue;
          if (Math.hypot(dx, dy) > reach) continue;
          frontier.push([i, s.id]);
        }
      }
    }
    // claim: stronger settlement (by pop, nearer) wins contested cells
    for (const [i, sid] of frontier) {
      const s = this.settlements[sid];
      const cur = this.owner[i];
      if (cur === -1) {
        this.owner[i] = sid;
        this.territory[i] = s.cultureId;
      } else if (cur !== sid) {
        const other = this.settlements[cur];
        if (s.pop > other.pop * 1.25) {
          this.owner[i] = sid;
          this.territory[i] = s.cultureId;
        }
      }
    }
  }

  // logistic growth toward hinterland carrying capacity
  private growPopulations() {
    const cap = new Float32Array(this.settlements.length);
    for (let i = 0; i < this.grid.n; i++) {
      const o = this.owner[i];
      if (o >= 0) cap[o] += this.grid.fertility[i];
    }
    for (const s of this.settlements) {
      const K = Math.max(4, cap[s.id] * 1.6);
      const r = 0.28; // growth rate per century
      s.pop = s.pop + r * s.pop * (1 - s.pop / K);
      // small noise + decline if over capacity
      s.pop = Math.max(0.5, s.pop + this.rng.normal(0, 0.15));
    }
  }

  // large, crowded settlements spawn colonists that found daughter towns
  private colonize() {
    const newcomers: Array<[number, number, number]> = []; // x,y,culture
    for (const s of this.settlements) {
      if (s.pop < 9) continue;
      if (this.rng.next() > 0.6) continue;
      // walk outward following fertility, away from existing claims
      let bx = s.x;
      let by = s.y;
      let best = -1;
      let bestScore = -1;
      const R = 4 + Math.floor(this.rng.range(0, 5));
      for (let a = 0; a < 12; a++) {
        const ang = this.rng.range(0, Math.PI * 2);
        const x = Math.round(s.x + Math.cos(ang) * R);
        const y = Math.round(s.y + Math.sin(ang) * R);
        const i = this.grid.idx(x, y);
        if (this.owner[i] !== -1) continue;
        const score = this.grid.fertility[i];
        if (score > bestScore) {
          bestScore = score;
          best = i;
          bx = this.grid.xOf(i);
          by = this.grid.yOf(i);
        }
      }
      if (best >= 0 && bestScore > 0.4) {
        newcomers.push([bx, by, s.cultureId]);
        s.pop *= 0.78; // emigration relieves pressure
      }
    }
    for (const [x, y, c] of newcomers) {
      const s = this.found(x, y, c);
      this.log.push(
        `${this.tick * 100}y: ${s.name} founded (${this.cultures[c].name})`,
      );
    }
  }

  // gravity-model trade over least-cost terrain paths
  private computeTrade() {
    this.routes = [];
    const big = [...this.settlements]
      .filter((s) => s.pop > 8)
      .sort((a, b) => b.pop - a.pop);
    const top = big.slice(0, Math.min(14, big.length));
    for (let a = 0; a < top.length; a++) {
      // connect each major settlement to its 2 nearest major neighbours
      const others = top
        .filter((_, b) => b !== a)
        .map((s) => {
          let dx = Math.abs(s.x - top[a].x);
          dx = Math.min(dx, this.grid.w - dx);
          return { s, d: Math.hypot(dx, s.y - top[a].y) };
        })
        .sort((u, v) => u.d - v.d)
        .slice(0, 2);
      for (const { s } of others) {
        if (s.id < top[a].id) continue; // dedupe
        const path = this.leastCostPath(top[a], s);
        if (path.length === 0) continue;
        const dist = Math.max(1, path.length);
        const volume = (top[a].pop * s.pop) / dist;
        this.routes.push({ a: top[a].id, b: s.id, path, volume });
      }
    }
  }

  // Dijkstra over movement cost: flat fertile land is cheap, mountains/water dear.
  private leastCostPath(a: Settlement, b: Settlement): number[] {
    const { grid } = this;
    const src = grid.idx(a.x, a.y);
    const dst = grid.idx(b.x, b.y);
    const dist = new Float32Array(grid.n).fill(Infinity);
    const prev = new Int32Array(grid.n).fill(-1);
    dist[src] = 0;
    // simple array-based PQ (worlds are small enough)
    const visited = new Uint8Array(grid.n);
    const heap: Array<[number, number]> = [[0, src]];
    const moveCost = (i: number): number => {
      if (grid.elevation[i] <= 0) return 8; // crossing water is expensive
      let c = 1 + grid.elevation[i] / 800; // climbing costs
      if (grid.waterLevel[i] > 2) c += 6; // lakes
      c += (1 - grid.fertility[i]) * 1.5; // harsh land slows travel
      if (grid.flow[i] > 6) c *= 0.7; // rivers are highways
      return c;
    };
    let guard = 0;
    while (heap.length && guard++ < grid.n * 12) {
      // pop min (linear scan; fine for these sizes)
      let mi = 0;
      for (let k = 1; k < heap.length; k++)
        if (heap[k][0] < heap[mi][0]) mi = k;
      const [d, i] = heap.splice(mi, 1)[0];
      if (visited[i]) continue;
      visited[i] = 1;
      if (i === dst) break;
      const x = grid.xOf(i);
      const y = grid.yOf(i);
      for (const j of grid.neighbors8(x, y)) {
        if (visited[j]) continue;
        const nd = d + moveCost(j);
        if (nd < dist[j]) {
          dist[j] = nd;
          prev[j] = i;
          heap.push([nd, j]);
        }
      }
    }
    if (!isFinite(dist[dst])) return [];
    const path: number[] = [];
    let cur = dst;
    while (cur !== -1) {
      path.push(cur);
      cur = prev[cur];
    }
    return path.reverse();
  }

  totalPop(): number {
    return this.settlements.reduce((s, x) => s + x.pop, 0);
  }

  // --- name generators (simple syllable stitching; deterministic per RNG) ---
  private settlementName(): string {
    const a = [
      "bel",
      "kar",
      "thal",
      "mor",
      "ael",
      "dun",
      "vor",
      "ysh",
      "len",
      "gra",
      "sol",
      "neth",
    ];
    const b = [
      "mar",
      "dor",
      "wyn",
      "stad",
      "heim",
      "gard",
      "fell",
      "mere",
      "ford",
      "hollow",
      "reach",
      "spire",
    ];
    return cap(this.rng.pick(a) + this.rng.pick(b));
  }
  private cultureName(): string {
    const a = [
      "Aur",
      "Vel",
      "Kor",
      "Tha",
      "Ysk",
      "Mor",
      "Eld",
      "Quor",
      "Sev",
      "Nim",
    ];
    const b = [
      "ian",
      "esh",
      "ar",
      "oth",
      "wen",
      "ix",
      "and",
      "ul",
      "een",
      "or",
    ];
    return cap(this.rng.pick(a) + this.rng.pick(b));
  }
}

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
