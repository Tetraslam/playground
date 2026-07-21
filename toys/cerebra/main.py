"""cerebra — gradient brains for the Drift.

Self-play REINFORCE predators AND prey in the same toroidal world. Both species
have a tiny 2-layer MLP policy whose parameters are updated by applied policy
gradient (hand-derived, no autograd). The opponent species is whoever else
happens to be in the env this iteration — so training is genuinely coupled:
prey get better at fleeing predators that get better at chasing them, with no
extra machinery.

top-level modes:
    uv run python toys/cerebra/main.py train --iters 400
    uv run python toys/cerebra/main.py live
    uv run python toys/cerebra/main.py eval --out examples/iter400.png

Run `uv sync` first to register the package in the workspace.
"""

from __future__ import annotations

import argparse
import os
import select
import sys
import termios
import time
import tty
from dataclasses import dataclass, field

import numpy as np

# absolute imports: the script's own dir is on sys.path[0] when run directly.
from brain import N_ACT, Adam, Policy
from viz import (
    compose_strip,
    render_curve_png,
    render_terminal,
    render_world_rgb,
    write_png,
)
from world import (
    N_PRED_IN,
    N_PREY_IN,
    World,
    discounted_returns,
)

EPISODE_LEN = 180
DEFAULT_ENVS = 16
DEFAULT_N_PREY = 24
DEFAULT_N_PRED = 6
DEFAULT_ITERS = 400
GAMMA = 0.99
LR = 3e-3
ENTROPY = 0.008     # gentle exploration bonus — prevents collapse to deterministic loops
OPPONENT_POOL_EVERY = 25   # snapshot cadence

# iteration checkpoints we render a behavior frame for
STRIP_ITERS_DEFAULT = [0, 30, 120, 400]


# ---------------------------------------------------------------------------
# trainer
# ---------------------------------------------------------------------------

@dataclass
class Rollout:
    obs: np.ndarray            # (T, B, S)
    actions: np.ndarray        # (T, B)
    h: np.ndarray               # (T, B, H)
    p: np.ndarray               # (T, B, A)
    rewards: np.ndarray         # (T, B)
    alive: np.ndarray           # (T, B)


class Trainer:
    def __init__(
        self,
        n_envs: int = DEFAULT_ENVS,
        n_prey: int = DEFAULT_N_PREY,
        n_pred: int = DEFAULT_N_PRED,
        episode_len: int = EPISODE_LEN,
        n_hid: int = 32,
        lr: float = LR,
        seed: int | None = None,
    ) -> None:
        self.world = World(n_envs, n_prey, n_pred, seed=seed)
        self.episode_len = episode_len
        self.n_hid = n_hid
        self.prey_policy = Policy(N_PREY_IN, n_hid, N_ACT, seed=(seed + 1 if seed else None))
        self.pred_policy = Policy(N_PRED_IN, n_hid, N_ACT, seed=(seed + 2 if seed else None))
        self.opt_prey = Adam(lr=lr)
        self.opt_pred = Adam(lr=lr)
        self.iter = 0

    # ---- rollout ----------------------------------------------------------

    def rollout(self) -> tuple[Rollout, Rollout, dict]:
        self.world.reset()
        T = self.episode_len
        E = self.world.E
        Np = self.world.Np
        Nq = self.world.Nq
        Bp = E * Np
        Bq = E * Nq

        obs_p = np.empty((T, Bp, N_PREY_IN), dtype=np.float32)
        a_p = np.empty((T, Bp), dtype=np.int64)
        h_p = np.empty((T, Bp, self.n_hid), dtype=np.float32)
        p_p = np.empty((T, Bp, N_ACT), dtype=np.float32)
        r_p = np.empty((T, Bp), dtype=np.float32)
        alive_p = np.empty((T, Bp), dtype=bool)

        obs_q = np.empty((T, Bq, N_PRED_IN), dtype=np.float32)
        a_q = np.empty((T, Bq), dtype=np.int64)
        h_q = np.empty((T, Bq, self.n_hid), dtype=np.float32)
        p_q = np.empty((T, Bq, N_ACT), dtype=np.float32)
        r_q = np.empty((T, Bq), dtype=np.float32)
        alive_q = np.empty((T, Bq), dtype=bool)

        for t in range(T):
            op = self.world.sense_prey().astype(np.float32)
            oq = self.world.sense_pred().astype(np.float32)
            # forward + sample
            pp, cp = self.prey_policy.forward(op)
            ap, logp_ap, _ = self.prey_policy.sample(op, cache=cp)
            pq, cq = self.pred_policy.forward(oq)
            aq, logp_aq, _ = self.pred_policy.sample(oq, cache=cq)
            # store
            obs_p[t] = op
            a_p[t] = ap
            h_p[t] = cp["h"]
            p_p[t] = cp["p"]
            alive_p[t] = self.world.palive.reshape(-1)
            obs_q[t] = oq
            a_q[t] = aq
            h_q[t] = cq["h"]
            p_q[t] = cq["p"]
            alive_q[t] = self.qalive_flat = self.world.qalive.reshape(-1)
            # advance the world
            rp, rq = self.world.step(ap, aq)
            r_p[t] = rp
            r_q[t] = rq

        ro_p = Rollout(obs_p, a_p, h_p, p_p, r_p, alive_p)
        ro_q = Rollout(obs_q, a_q, h_q, p_q, r_q, alive_q)
        info = {"last_alive_prey": int(self.world.palive.sum()),
                "last_alive_pred": int(self.world.qalive.sum())}
        return ro_p, ro_q, info

    # ---- one training step ------------------------------------------------

    def train_step(self) -> dict:
        ro_p, ro_q, info = self.rollout()

        G_p = discounted_returns(ro_p.rewards, GAMMA)         # (T, Bp)
        G_q = discounted_returns(ro_q.rewards, GAMMA)
        # NOTE: dead-agent rewards are already 0 (we masked them) — but their
        # returns G_t are still nonzero (carried forward from when they were
        # alive), so masking advantages by alive is clean.
        b_p = G_p[ro_p.alive].mean() if ro_p.alive.any() else 0.0
        b_q = G_q[ro_q.alive].mean() if ro_q.alive.any() else 0.0
        adv_p_raw = (G_p - b_p)
        adv_q_raw = (G_q - b_q)
        # mask dead agents from gradient
        adv_p = (adv_p_raw * ro_p.alive).astype(np.float32)
        adv_q = (adv_q_raw * ro_q.alive).astype(np.float32)
        # normalise advantages per-species (helps Adam's adaptive scale)
        if adv_p.std() > 1e-6:
            adv_p = (adv_p - adv_p.mean()) / (adv_p.std() + 1e-6)
        if adv_q.std() > 1e-6:
            adv_q = (adv_q - adv_q.mean()) / (adv_q.std() + 1e-6)
        adv_p = adv_p * ro_p.alive   # re-mask (norm may have moved zero)
        adv_q = adv_q * ro_q.alive

        # collapse time*env*agent into one big batch
        T, Bp = G_p.shape
        Bq = G_q.shape[1]
        cache_p = {
            "obs": ro_p.obs.reshape(T * Bp, -1),
            "h": ro_p.h.reshape(T * Bp, -1),
            "p": ro_p.p.reshape(T * Bp, -1),
        }
        cache_q = {
            "obs": ro_q.obs.reshape(T * Bq, -1),
            "h": ro_q.h.reshape(T * Bq, -1),
            "p": ro_q.p.reshape(T * Bq, -1),
        }
        grads_p = self.prey_policy.backward(cache_p, ro_p.actions.reshape(-1),
                                             adv_p.reshape(-1), entropy_coef=ENTROPY)
        grads_q = self.pred_policy.backward(cache_q, ro_q.actions.reshape(-1),
                                              adv_q.reshape(-1), entropy_coef=ENTROPY)

        self.opt_prey.ensure(self.prey_policy)
        self.opt_pred.ensure(self.pred_policy)
        self.prey_policy.grads_apply(grads_p, self.opt_prey)
        self.pred_policy.grads_apply(grads_q, self.opt_pred)

        # stats: per-agent episode return
        ep_p = (ro_p.rewards * ro_p.alive).sum(axis=0)
        ep_q = (ro_q.rewards * ro_q.alive).sum(axis=0)
        stats = {
            "rp_mean": float(ep_p.mean()), "rp_max": float(ep_p.max()),
            "rq_mean": float(ep_q.mean()), "rq_max": float(ep_q.max()),
            "alive_prey_end": info["last_alive_prey"],
            "alive_pred_end": info["last_alive_pred"],
            "adv_p_std": float(adv_p[ro_p.alive].std()) if ro_p.alive.any() else 0.0,
            "adv_q_std": float(adv_q[ro_q.alive].std()) if ro_q.alive.any() else 0.0,
        }
        self.iter += 1
        return stats

    # ---- demo rollout: snapshot one env's visual frame --------------------

    def demo_frame_rgb(self, steps: int = 60) -> np.ndarray:
        """Spin up a single-env world with the current policies, run for
        `steps` ticks, and return an RGB frame of env 0 at the end.

        Uses a dense demo (18 prey, 5 preds on a 64×40 world) so behaviour
        differences are visible. Seeded so the same layout underlies every
        snapshot — only the policy changes between frames."""
        demo = World(1, 18, 5, seed=12345)
        demo.reset()
        for _ in range(steps):
            op = demo.sense_prey().astype(np.float32)
            oq = demo.sense_pred().astype(np.float32)
            _, cp = self.prey_policy.forward(op)
            ap, _, _ = self.prey_policy.sample(op, cache=cp)
            _, cq = self.pred_policy.forward(oq)
            aq, _, _ = self.pred_policy.sample(oq, cache=cq)
            demo.step(ap, aq)
        return render_world_rgb(demo, env_idx=0)


# ---------------------------------------------------------------------------
# training loop with optional live tty + behavior snapshots
# ---------------------------------------------------------------------------

@dataclass
class TrainLogger:
    history: dict = field(default_factory=lambda: {
        "iter": [], "rp_mean": [], "rq_mean": [], "rp_max": [], "rq_max": [],
    })

    def log(self, it: int, stats: dict) -> None:
        self.history["iter"].append(it)
        self.history["rp_mean"].append(stats["rp_mean"])
        self.history["rq_mean"].append(stats["rq_mean"])
        self.history["rp_max"].append(stats["rp_max"])
        self.history["rq_max"].append(stats["rq_max"])


class TermRaw:
    def __enter__(self):
        try:
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setraw(self.fd)
        except termios.error:
            self.old = None
        return self

    def __exit__(self, *a):
        if getattr(self, "old", None) is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)


def read_key() -> str | None:
    try:
        r, _, _ = select.select([sys.stdin], [], [], 0)
        if r:
            return sys.stdin.read(1)
    except (OSError, ValueError):
        pass
    return None


def cmd_train(args) -> None:
    strip_iters = [int(s) for s in args.strip_iters.split(",")] if args.strip_iters \
        else STRIP_ITERS_DEFAULT
    trainer = Trainer(
        n_envs=args.envs, n_prey=args.n_prey, n_pred=args.n_pred,
        episode_len=args.episode, n_hid=args.n_hid, lr=args.lr, seed=args.seed,
    )
    logger = TrainLogger()
    strip_frames: list[tuple[int, np.ndarray]] = []
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    live = (not args.no_tty) and sys.stdout.isatty() and not args.quiet

    # capture initial random-policy frame
    if 0 in strip_iters:
        rgb = trainer.demo_frame_rgb(steps=args.demo_steps)
        strip_frames.append((0, rgb))
        write_png(os.path.join(out_dir, "iter_0000.png"), rgb)
    t0 = time.time()
    speed = 1
    with TermRaw() if live else _null_ctx():
        for it in range(args.iters):
            stats = trainer.train_step()
            logger.log(it, stats)
            if live:
                # render once for every speed iters
                rgb = trainer.demo_frame_rgb(steps=10)
                # turn into a downsample ascii terminal view
                print("\x1b[H\x1b[J", end="")
                demo = World(1, 12, 4, seed=it % 1000)
                demo.reset()
                for _ in range(15):
                    op = demo.sense_prey().astype(np.float32)
                    oq = demo.sense_pred().astype(np.float32)
                    _, cp = trainer.prey_policy.forward(op)
                    ap, _, _ = trainer.prey_policy.sample(op, cache=cp)
                    _, cq = trainer.pred_policy.forward(oq)
                    aq, _, _ = trainer.pred_policy.sample(oq, cache=cq)
                    demo.step(ap, aq)
                term = render_terminal(demo, env_idx=0, stats={
                    "iter": it, "rp": stats["rp_mean"], "rq": stats["rq_mean"]
                })
                print(term)
                print(f"[q]uit  [+/-]speed  [s]napshot  speed={speed}")
                key = read_key()
                if key == "q":
                    break
                elif key == "+":
                    speed = min(speed + 1, 8)
                elif key == "-":
                    speed = max(speed - 1, 1)
                elif key == "s":
                    rgb = trainer.demo_frame_rgb(steps=args.demo_steps)
                    strip_frames.append((it, rgb))
                # advance speed-1 extra train steps before the next render
                for _ in range(speed - 1):
                    s2 = trainer.train_step()
                    logger.log(trainer.iter - 1, s2)
            else:
                if it % 5 == 0:
                    elapsed = time.time() - t0
                    print(
                        f"it {it:4d}/{args.iters}  "
                        f"rp {stats['rp_mean']:6.2f} (max {stats['rp_max']:6.2f})  "
                        f"rq {stats['rq_mean']:6.2f} (max {stats['rq_max']:6.2f})  "
                        f"alive_end prey {stats['alive_prey_end']:3d}/{args.n_prey*args.envs:3d} "
                        f"pred {stats['alive_pred_end']:2d}/{args.n_pred*args.envs:2d}  "
                        f"({elapsed:5.1f}s)",
                        file=sys.stderr,
                    )
            if (it + 1) in strip_iters:
                rgb = trainer.demo_frame_rgb(steps=args.demo_steps)
                strip_frames.append((it + 1, rgb))
                write_png(os.path.join(out_dir, f"iter_{it+1:04d}.png"), rgb)
            # when speed>1 in live mode, we already advanced above; in headless that's nothing

    # save learning curve
    render_curve_png(
        logger.history,
        os.path.join(out_dir, "learning_curve.png"),
        title=f"cerebra self-play — {args.iters} iters",
    )
    # save behavior strip
    if strip_frames:
        compose_strip(strip_frames, os.path.join(out_dir, "behavior_strip.png"),
                      label=f"cerebra — iter {' → '.join(str(i) for i, _ in strip_frames)}")
    print(f"\nDone. {args.iters} iters in {time.time()-t0:.1f}s. "
          f"Outputs in {out_dir}/", file=sys.stderr)


class _null_ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


# ---------------------------------------------------------------------------
# eval mode — render a single high-res snapshot using saved weights?
# We'll skip a full weight save/load for now and just offer a longer demo rollout.
# ---------------------------------------------------------------------------

def cmd_eval(args) -> None:
    """Quick: train briefly + save a high-quality demo frame, no logging."""
    trainer = Trainer(n_envs=args.envs, n_prey=args.n_prey, n_pred=args.n_pred,
                      seed=args.seed)
    for it in range(args.iters):
        trainer.train_step()
        if it % 20 == 0:
            print(f"it {it} rp={trainer if False else ''}", file=sys.stderr)
    rgb = trainer.demo_frame_rgb(steps=80)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    write_png(args.out, rgb)
    print(f"wrote {args.out}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    # shared args
    def add_common(p):
        p.add_argument("--envs", type=int, default=DEFAULT_ENVS)
        p.add_argument("--n-prey", type=int, default=DEFAULT_N_PREY)
        p.add_argument("--n-pred", type=int, default=DEFAULT_N_PRED)
        p.add_argument("--n-hid", type=int, default=32)
        p.add_argument("--lr", type=float, default=LR)
        p.add_argument("--seed", type=int, default=None)

    p = sub.add_parser("train", help="train policies, save learning curve + behavior strip")
    add_common(p)
    p.add_argument("--iters", type=int, default=DEFAULT_ITERS)
    p.add_argument("--episode", type=int, default=EPISODE_LEN)
    p.add_argument("--out-dir", type=str, default="examples")
    p.add_argument("--no-tty", action="store_true", help="don't try to draw a live view")
    p.add_argument("--quiet", action="store_true", help="just print periodic stats")
    p.add_argument("--strip-iters", type=str, default="",
                   help="comma-separated iterations to snapshot for the strip (default 0,30,120,400)")
    p.add_argument("--demo-steps", type=int, default=50,
                   help="how many steps a demo rollout should run before capturing a frame")
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("eval", help="train briefly + save one high-quality frame")
    add_common(p)
    p.add_argument("--out", type=str, default="examples/iter_eval.png")
    p.add_argument("--iters", type=int, default=120)
    p.set_defaults(func=cmd_eval)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
