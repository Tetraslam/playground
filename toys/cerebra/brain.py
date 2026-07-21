"""cerebra.brain — the policy net, by hand.

A 2-layer MLP with a softmax over 9 discrete actions (3 turn × 3 speed).
REINFORCE gives the gradient; Adam steps it. No autograd — the backward pass
is written out by hand so the policy-gradient math stays visible.

The agent "remembers" one forward pass's intermediates so a later backward pass
can re-use them; this keeps the training loop one forward -> one backward, no
tape.
"""

from __future__ import annotations

import numpy as np

# action space: 3 turn × 3 speed
ACTIONS_TURN = np.array([-1.0, 0.0, 1.0])
ACTIONS_SPEED = np.array([0.0, 0.5, 1.0])
N_ACT = 9  # turn index in [0,3), speed index in [0,3); a = turn_idx * 3 + speed_idx


def decode_action(a: int) -> tuple[float, float]:
    """action int -> (turn_dir, speed_frac)."""
    t_idx, s_idx = divmod(a, 3)
    return float(ACTIONS_TURN[t_idx]), float(ACTIONS_SPEED[s_idx])


def decode_actions(a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """vectorized: (B,) ints -> turn_dir (B,), speed_frac (B,)."""
    t_idx, s_idx = np.divmod(a, 3)
    return ACTIONS_TURN[t_idx], ACTIONS_SPEED[s_idx]


class Policy:
    def __init__(
        self, n_in: int, n_hid: int, n_act: int = N_ACT, seed: int | None = None
    ) -> None:
        self.n_in, self.n_hid, self.n_act = n_in, n_hid, n_act
        rng = np.random.default_rng(seed)
        # small init so logits start near-uniform (plenty of exploration early)
        self.W1 = rng.normal(0, 0.6, (n_in, n_hid))
        self.b1 = np.zeros(n_hid)
        self.W2 = rng.normal(0, 0.6, (n_hid, n_act))
        self.b2 = np.zeros(n_act)
        self.rng = rng

    # ---- forward ------------------------------------------------------------

    def forward(self, obs: np.ndarray) -> tuple[np.ndarray, dict]:
        """obs (B, n_in) -> probs (B, n_act), cache for backward."""
        z1 = obs @ self.W1 + self.b1            # (B, H)
        h = np.tanh(z1)                          # (B, H)
        logits = h @ self.W2 + self.b2           # (B, A)
        # numerically stable softmax
        m = logits.max(axis=1, keepdims=True)
        ex = np.exp(logits - m)
        p = ex / ex.sum(axis=1, keepdims=True)   # (B, A)
        cache = {"obs": obs, "h": h, "p": p}
        return p, cache

    def sample(self, obs: np.ndarray, cache: dict | None = None):
        """forward + sample actions; returns (a (B,), logp_a (B,), cache)."""
        p, c = self.forward(obs)
        if cache is not None:
            c.update(cache)
        B = obs.shape[0]
        # sample per row via cumulative + uniform
        u = self.rng.random(B)
        cdf = np.cumsum(p, axis=1)
        a = (u[:, None] < cdf).argmax(axis=1).astype(np.int64)
        logp_a = np.log(p[np.arange(B), a] + 1e-30)
        return a, logp_a, c

    # ---- backward (REINFORCE) ----------------------------------------------
    # We maximise J = E[ sum_t logpi(a_t|s_t) * A_t ], A_t = (G_t - b).
#    ∂J/∂logits[b, k] = A_t[b] * (1[k == a_b] - p[b, k]).
# Adam MINIMIZES, so backward() returns negative-gradient (== loss-grad) and
# grads_apply -> Adam steps in the direction that RAISES the expected return.

    def backward(
        self,
        cache: dict,
        actions: np.ndarray,
        advantages: np.ndarray,
        entropy_coef: float = 0.0,
    ) -> dict[str, np.ndarray]:
        obs = cache["obs"]
        h = cache["h"]
        p = cache["p"]
        B, A = p.shape
        adv = advantages[:, None]
        # softmax jacobian applied: 1[a=k] - p
        onehot = np.zeros((B, A))
        onehot[np.arange(B), actions] = 1.0
        dlogits = adv * (onehot - p)    # (B, A) — this is ∂J/∂logits (per-sample)
        # ENTROPY bonus: H = -sum p log p maximized alongside J.
        # exact dH/dlogits_k = -p_k * (logp_k + 1) ; we add entropy_coef * that.
        if entropy_coef > 0:
            logp = np.log(p + 1e-30)
            dlogits += entropy_coef * (-p * (logp + 1.0))
        # average over batch (Adam handles scale, but per-sample normalisation keeps it stable)
        dlogits /= B
        # NOTE: we MAXIMIZE J, but Adam MINIMIZES — so flip sign before backprop.
        dlogits = -dlogits

        # backprop through logits = h @ W2 + b2
        dW2 = h.T @ dlogits                  # (H, A)
        db2 = dlogits.sum(axis=0)            # (A,)
        dh = dlogits @ self.W2.T             # (B, H)
        dz1 = dh * (1.0 - h * h)             # tanh'
        dW1 = obs.T @ dz1                    # (S, H)
        db1 = dz1.sum(axis=0)               # (H,)
        return {"W1": dW1, "b1": db1, "W2": dW2, "b2": db2}

    # ---- weight ops ---------------------------------------------------------

    def params(self) -> dict[str, np.ndarray]:
        return {"W1": self.W1, "b1": self.b1, "W2": self.W2, "b2": self.b2}

    def grads_apply(self, grads: dict[str, np.ndarray], opt: Adam) -> None:
        for k, g in grads.items():
            new_w, opt.m[k], opt.v[k], opt.t[k] = adam_step(
                self.params()[k], g, opt.m[k], opt.v[k], opt.t[k], opt.lr,
                beta1=opt.beta1, beta2=opt.beta2, eps=opt.eps,
            )
            setattr(self, k, new_w)

    # ---- snapshot / load ----------------------------------------------------

    def state_dict(self) -> dict[str, np.ndarray]:
        return {k: v.copy() for k, v in self.params().items()}

    def load_state_dict(self, sd: dict[str, np.ndarray]) -> None:
        self.W1 = sd["W1"].copy()
        self.b1 = sd["b1"].copy()
        self.W2 = sd["W2"].copy()
        self.b2 = sd["b2"].copy()

    def perturb(self, sigma: float = 0.1) -> Policy:
        """return a perturbed copy — used for random-opponent self-play."""
        clone = Policy(self.n_in, self.n_hid, self.n_act, seed=None)
        clone.load_state_dict(self.state_dict())
        clone.W1 += self.rng.normal(0, sigma, clone.W1.shape)
        clone.b1 += self.rng.normal(0, sigma, clone.b1.shape)
        clone.W2 += self.rng.normal(0, sigma, clone.W2.shape)
        clone.b2 += self.rng.normal(0, sigma, clone.b2.shape)
        return clone


# ---------------------------------------------------------------------------
# Adam (one set of moments per parameter)
# ---------------------------------------------------------------------------


def adam_step(
    w: np.ndarray, g: np.ndarray, m: np.ndarray, v: np.ndarray,
    t: int, lr: float, beta1: float = 0.9, beta2: float = 0.999, eps: float = 1e-8,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    m = beta1 * m + (1 - beta1) * g
    v = beta2 * v + (1 - beta2) * (g * g)
    t += 1
    mhat = m / (1 - beta1**t)
    vhat = v / (1 - beta2**t)
    w = w - lr * mhat / (np.sqrt(vhat) + eps)
    return w, m, v, t


class Adam:
    def __init__(self, lr: float = 3e-3) -> None:
        self.lr = lr
        self.beta1, self.beta2, self.eps = 0.9, 0.999, 1e-8
        self.m: dict[str, np.ndarray] = {}
        self.v: dict[str, np.ndarray] = {}
        self.t: dict[str, int] = {}

    def ensure(self, p: Policy) -> None:
        for k, w in p.params().items():
            if k not in self.m:
                self.m[k] = np.zeros_like(w)
                self.v[k] = np.zeros_like(w)
                self.t[k] = 0
