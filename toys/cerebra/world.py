"""cerebra.world — a batched-for-RL toroidal Drift-world.

One instance holds E parallel "worlds" so REINFORCE gets a fat batch a tick.
Per env: fixed N_pre prey and N_pr predators. Critters die (energ→0) within
an episode but don't reproduce — that's deliberate, so the rollout tensor shape
stays stable for backprop. Energy is the only player-state; what you train on
is energy-derived reward.

Layout convention: the leading axis is the env index E; subscripts _p for prey,
_q for predators.
"""

from __future__ import annotations

import math

import numpy as np

# world constants — tuned close to primordia but tightened for short episodes
WORLD = 64.0
WORLD_H = 40.0
SENSE_R = 14.0
EAT_R = 1.5
PLANT_E = 8.0           # plant cell cap
PLANT_REGROW = 0.06     # logistic-rate per tick

# critter dynamics (per-tick)
PREY_META = 0.014       # base metabolism
PRED_META = 0.150       # predators burn hot — they MUST hunt regularly
MOVE_COST = 0.014       # per unit speed
AGE_COST = 0.0004
PRED_BITE = 22.0        # energy gained per kill — kills weaker prey in 1-2 bites
PREY_MAX_SPEED = 2.3
PRED_MAX_SPEED = 1.8     # slightly faster so they can close
TURN_RATE = 0.8
EAT_R = 1.5
PREY_START_E = (32, 48)
PRED_START_E = (28, 38)  # hungry at start — must eat within ~150 ticks

# sensing: 4 angular quadrants per signal
QUAD_COUNT = 4
N_PREY_IN = 4 + 4 + 4 + 1 + 1     # food, conspecific, threat, energy, bias  = 14
N_PRED_IN = 4 + 4 + 1 + 1         # prey-as-food, conspecific, energy, bias = 10

# reward shaping (kept tiny — the dynamics do the heavy lifting)
R_PREY_SURVIVE = 0.01
R_PREY_FOOD_SCALE = 0.02          # multiply energy gained from plants
R_PREY_DEATH = -0.6
R_PREY_THREAT_NEAR = -0.02         # -0.02 per predator within sense range

R_PRED_KILL = 0.08                # multiply bite energy
R_PRED_IDLE = -0.004              # tiny per-tick idle penalty
R_PRED_HUNGRY = -0.002             # extra penalty if no prey in sense range
R_PRED_STARVE = -0.6              # dead-of-starvation penalty


class World:
    def __init__(
        self,
        n_envs: int = 16,
        n_prey: int = 24,
        n_pred: int = 6,
        cell: float = 4.0,
        seed: int | None = None,
    ) -> None:
        self.E = n_envs
        self.Np = n_prey
        self.Nq = n_pred
        self.rng = np.random.default_rng(seed)
        # state — all (E, N, ...)
        self.ppos = np.empty((n_envs, n_prey, 2))
        self.phead = np.empty((n_envs, n_prey))
        self.pene = np.empty((n_envs, n_prey))
        self.page = np.empty((n_envs, n_prey))
        self.palive = np.empty((n_envs, n_prey), dtype=bool)
        self.qpos = np.empty((n_envs, n_pred, 2))
        self.qhead = np.empty((n_envs, n_pred))
        self.qene = np.empty((n_envs, n_pred))
        self.qage = np.empty((n_envs, n_pred))
        self.qalive = np.empty((n_envs, n_pred), dtype=bool)
        # plants — per-env grid
        self.cell = cell
        self.gw = int(WORLD / cell)
        self.gh = int(WORLD_H / cell)
        self.plants = np.zeros((n_envs, self.gh, self.gw))
        self.step_count = 0

    def reset(self) -> None:
        # randomized positions, headings, energies, plant field
        self.ppos = self.rng.uniform(0, WORLD, self.ppos.shape)
        self.ppos[..., 1] = self.rng.uniform(0, WORLD_H, self.ppos[..., 1].shape)
        self.phead = self.rng.uniform(0, 2 * math.pi, self.phead.shape)
        self.pene = self.rng.uniform(*PREY_START_E, self.pene.shape)
        self.page = np.zeros_like(self.pene)
        self.palive = np.ones(self.palive.shape, dtype=bool)
        self.qpos = self.rng.uniform(0, WORLD, self.qpos.shape)
        self.qpos[..., 1] = self.rng.uniform(0, WORLD_H, self.qpos[..., 1].shape)
        self.qhead = self.rng.uniform(0, 2 * math.pi, self.qhead.shape)
        self.qene = self.rng.uniform(*PRED_START_E, self.qene.shape)
        self.qage = np.zeros_like(self.qene)
        self.qalive = np.ones(self.qalive.shape, dtype=bool)
        self.plants = np.full(self.plants.shape, PLANT_E * 0.6)
        self.step_count = 0

    # ---- sensing -----------------------------------------------------------

    def sense_prey(self) -> np.ndarray:
        """Observations for all prey across all envs: (E*Np, N_PREY_IN)."""
        return self._sense_one(self.ppos, self.phead, self.pene,
                               food_pos=self.ppos, food_sig=None,
                               con_pos=self.ppos, con_alive=self.palive,
                               threat_pos=self.qpos, threat_alive=self.qalive)

    def sense_pred(self) -> np.ndarray:
        return self._sense_one(self.qpos, self.qhead, self.qene,
                               food_pos=self.ppos, food_sig=self.palive.astype(np.float32),
                               con_pos=self.qpos, con_alive=self.qalive,
                               threat_pos=None, threat_alive=None)

    def _sense_one(self, my_pos, my_head, my_e, food_pos, food_sig,
                   con_pos, con_alive, threat_pos, threat_alive):
        # my_pos: (E, N, 2), my_head: (E, N). Returns (E, N, 14 or 10).
        E, N = my_pos.shape[:2]
        has_food = food_pos is not None
        has_threat = threat_pos is not None
        mfood = self._pairwise_quads(my_pos, my_head, food_pos, food_sig) if has_food else None
        mcon = self._pairwise_quads(my_pos, my_head, con_pos, con_alive.astype(np.float32))
        mthreat = self._pairwise_quads(my_pos, my_head, threat_pos, threat_alive) if has_threat else None
        parts = []
        if mfood is not None:
            parts.append(mfood)
        parts.append(mcon)
        if mthreat is not None:
            parts.append(mthreat)
        e_col = (my_e / 100.0)[..., None]
        parts.append(e_col)
        bias = np.ones((E, N, 1))
        parts.append(bias)
        obs = np.concatenate(parts, axis=2)  # (E, N, S)
        return obs.reshape(E * N, -1)

    def _pairwise_quads(self, my_pos, my_head, their_pos, signal):
        """All pairwise, vectorised over (E, N, M). Returns (E, N, 4) inverse-distance-weighted sums per quad.

        signal: if None, weight is uniform (1.0); else shape (E, M).
        """
        E, N, _ = my_pos.shape
        M = their_pos.shape[1]
        # centred delta on torus
        dx = their_pos[:, None, :, 0] - my_pos[:, :, None, 0]
        dy = their_pos[:, None, :, 1] - my_pos[:, :, None, 1]
        dx = (dx + WORLD / 2) % WORLD - WORLD / 2
        dy = (dy + WORLD_H / 2) % WORLD_H - WORLD_H / 2
        dist2 = dx * dx + dy * dy
        mask = dist2 < (SENSE_R * SENSE_R)
        dist = np.sqrt(dist2 + 1e-3)
        # NOT self — zero out diagonal when my_pos is their_pos
        if signal is None:
            # uniform weight = 1; but skip self pairs only if shapes match
            w = np.ones((E, N, M), dtype=np.float32)
        else:
            w = signal[:, None, :].astype(np.float32)
        w = w / (1.0 + dist) * mask
        # zero-out diagonal pairs (self-detection)?
        if M == N:
            eye = np.eye(N, dtype=bool)[None, :, :]
            w = np.where(eye, 0.0, w)
        ang = np.arctan2(dy, dx) - my_head[:, :, None]
        ang = (ang + math.pi) % (2 * math.pi) - math.pi
        q = ((ang + math.pi) / (math.pi / 2)).astype(np.int64)
        q = np.clip(q, 0, 3)
        out = np.zeros((E, N, 4), dtype=np.float32)
        for qi in range(4):
            m = (q == qi)
            out[:, :, qi] = np.where(m.any(axis=2), np.sum(w * m, axis=2), 0.0)
        return out

    # ---- step -------------------------------------------------------------

    def step(self, a_p: np.ndarray, a_q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Apply actions to both species for one tick. Returns (r_prey, r_pred) shaped (E*Np,) (E*Nq)."""
        self.step_count += 1
        E, Np = self.E, self.Np
        Nq = self.Nq
        # decode actions and reshape to per-env layout
        t_p, s_p = _decode_batch(a_p, Np_pre=E * Np)
        t_q, s_q = _decode_batch(a_q, Np_pre=E * Nq)
        t_p = t_p.reshape(E, Np)
        s_p = s_p.reshape(E, Np)
        t_q = t_q.reshape(E, Nq)
        s_q = s_q.reshape(E, Nq)
        speed_p = s_p * PREY_MAX_SPEED
        speed_q = s_q * PRED_MAX_SPEED

        # move — only the alive ones actually move (mask)
        p_alive = self.palive
        q_alive = self.qalive
        self.phead = (self.phead + t_p * TURN_RATE * p_alive) % (2 * math.pi)
        self.ppos[..., 0] = (self.ppos[..., 0] + np.cos(self.phead) * speed_p * p_alive) % WORLD
        self.ppos[..., 1] = (self.ppos[..., 1] + np.sin(self.phead) * speed_p * p_alive) % WORLD_H
        self.qhead = (self.qhead + t_q * TURN_RATE * q_alive) % (2 * math.pi)
        self.qpos[..., 0] = (self.qpos[..., 0] + np.cos(self.qhead) * speed_q * q_alive) % WORLD
        self.qpos[..., 1] = (self.qpos[..., 1] + np.sin(self.qhead) * speed_q * q_alive) % WORLD_H

        # eat plants — prey graze their cell
        gained_p = self._graze(self.ppos, p_alive)
        self.pene += gained_p * p_alive

        # predation — pred eats prey in contact; each prey to nearest contacting pred
        bite_p_energy, bite_q_energy = self._predation()
        self.pene -= bite_p_energy * p_alive
        self.qene += bite_q_energy * q_alive

        # metabolism / aging — only pay if alive
        meta_p_cost = (PREY_META + MOVE_COST * speed_p + AGE_COST * self.page) * p_alive
        meta_q_cost = (PRED_META + MOVE_COST * speed_q + AGE_COST * self.qage) * q_alive
        self.pene -= meta_p_cost
        self.qene -= meta_q_cost
        self.page += 1.0 * p_alive
        self.qage += 1.0 * q_alive

        # deaths
        new_p_dead = (self.pene <= 0) | (self.page > 4000)
        new_p_dead = new_p_dead & p_alive  # only newly-dead this tick
        new_q_dead = (self.qene <= 0) | (self.qage > 5000)
        new_q_dead = new_q_dead & q_alive
        self.palive = self.palive & ~new_p_dead
        self.qalive = self.qalive & ~new_q_dead

        # ---- rewards ----
        r_prey = np.zeros(E * Np, dtype=np.float32)
        r_pred = np.zeros(E * Nq, dtype=np.float32)
        r_prey += (R_PREY_SURVIVE * p_alive).reshape(-1)
        r_prey += (R_PREY_FOOD_SCALE * gained_p).reshape(-1)
        r_prey += (R_PREY_DEATH * new_p_dead).reshape(-1)
        # threat proximity shaping — count predators within sense range
        thr_near = self._threats_near_prey(p_alive=p_alive)
        r_prey += (R_PREY_THREAT_NEAR * thr_near).reshape(-1)

        r_pred += (R_PRED_KILL * bite_q_energy).reshape(-1)
        r_pred += (R_PRED_IDLE * q_alive).reshape(-1)
        r_pred += (R_PRED_HUNGRY * self._pred_no_prey_in_sight(q_alive) * q_alive).reshape(-1)
        # punish predators that die of starvation
        r_pred += (R_PRED_STARVE * new_q_dead).reshape(-1)

        # plant regrow
        self.plants += PLANT_REGROW * (PLANT_E - self.plants) + PLANT_REGROW * 0.3
        self.plants = np.minimum(self.plants, PLANT_E)

        return r_prey, r_pred

    # ---- sub-routines -------------------------------------------------------

    def _graze(self, pos: np.ndarray, alive: np.ndarray) -> np.ndarray:
        """Each prey bites plants in its cell. Returns (E, Np) energy gained."""
        E, N = pos.shape[:2]
        gx = np.clip((pos[..., 0] / self.cell).astype(int), 0, self.gw - 1)
        gy = np.clip((pos[..., 1] / self.cell).astype(int), 0, self.gh - 1)
        # gather across envs
        envs = np.arange(E)[:, None].repeat(N, axis=1)
        avail = self.plants[envs, gy, gx]    # (E, N)
        bite = np.minimum(avail, 3.0) * alive
        self.plants[envs, gy, gx] -= bite
        return bite

    def _predation(self) -> tuple[np.ndarray, np.ndarray]:
        """Returns prey_energy_lost (E, Np), predator_energy_gained (E, Nq)."""
        # pairwise distances predator×prey per env
        dx = self.qpos[:, :, None, 0] - self.ppos[:, None, :, 0]
        dy = self.qpos[:, :, None, 1] - self.ppos[:, None, :, 1]
        dx = (dx + WORLD / 2) % WORLD - WORLD / 2
        dy = (dy + WORLD_H / 2) % WORLD_H - WORLD_H / 2
        d = np.sqrt(dx * dx + dy * dy)
        # contact: pred-prey within EAT_R, both alive
        contact = (d < EAT_R) & self.palive[:, None, :] & self.qalive[:, :, None]
        # each prey to nearest contacting predator
        dmasked = np.where(contact, d, np.inf)
        nearest_pred = np.argmin(dmasked, axis=1)   # (E, Np): for each prey
        prey_caught = np.isfinite(dmasked[np.arange(self.E)[:, None], nearest_pred,
                                          np.arange(self.Np)[None, :]])
        prey_caught = prey_caught & self.palive
        # bite energy from each caught prey
        bite_each = np.minimum(self.pene * 0.8, PRED_BITE)
        # zero-out not-caught
        bite_for_prey = np.where(prey_caught, bite_each, 0.0)   # (E, Np)
        # sum to each predator using np.add.at per env
        pred_energy_gained = np.zeros((self.E, self.Nq))
        e_idx = np.arange(self.E)[:, None].repeat(self.Np, axis=1)
        prey_idx = np.arange(self.Np)[None, :].repeat(self.E, axis=0)
        # only count caught prey
        mask = prey_caught
        ee = e_idx[mask]
        pp_idx = prey_idx[mask]
        pred_idx_for_caught = nearest_pred[mask]
        np.add.at(pred_energy_gained, (ee, pred_idx_for_caught), bite_for_prey[ee, pp_idx])
        return bite_for_prey, pred_energy_gained

    def _threats_near_prey(self, p_alive) -> np.ndarray:
        """Count predators within SENSE_R per prey. Returns (E, Np)."""
        dx = self.qpos[:, :, None, 0] - self.ppos[:, None, :, 0]
        dy = self.qpos[:, :, None, 1] - self.ppos[:, None, :, 1]
        dx = (dx + WORLD / 2) % WORLD - WORLD / 2
        dy = (dy + WORLD_H / 2) % WORLD_H - WORLD_H / 2
        d = np.sqrt(dx * dx + dy * dy)
        near = (d < SENSE_R) & self.qalive[:, :, None]
        return near.sum(axis=1).astype(np.float32) * p_alive

    def _pred_no_prey_in_sight(self, q_alive) -> np.ndarray:
        """True where no prey is in sense range, per predator. Returns (E, Nq)."""
        dx = self.ppos[:, None, :, 0] - self.qpos[:, :, None, 0]
        dy = self.ppos[:, None, :, 1] - self.qpos[:, :, None, 1]
        dx = (dx + WORLD / 2) % WORLD - WORLD / 2
        dy = (dy + WORLD_H / 2) % WORLD_H - WORLD_H / 2
        d = np.sqrt(dx * dx + dy * dy)
        near_prey = (d < SENSE_R) & self.palive[:, None, :]   # (E, Nq, Np)
        any_in_sight = near_prey.any(axis=2)
        no_sight = (~any_in_sight).astype(np.float32) * q_alive.astype(np.float32)
        return no_sight


def _decode_batch(a: np.ndarray, Np_pre: int) -> tuple[np.ndarray, np.ndarray]:
    """Decode the 9-action integer encoding to (turn_dir, speed_frac)."""
    from brain import decode_actions
    t, s = decode_actions(a)
    return t, s


def discounted_returns(rewards: np.ndarray, gamma: float = 0.99) -> np.ndarray:
    """rewards (T, B) -> rewards-to-go G_t (T, B)."""
    T, B = rewards.shape
    G = np.zeros_like(rewards)
    running = np.zeros(B, dtype=np.float32)
    for t in range(T - 1, -1, -1):
        running = rewards[t] + gamma * running
        G[t] = running
    return G
