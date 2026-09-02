"""hearsay.cortex — a layer of spiking neurons that learns, unsupervised, what
the ear keeps saying.

    nerve spikes (N_in, T)
      -> delay lines: D shifted copies (so a synapse can prefer "channel c,
         d ms ago"; the learned weights are spectro-temporal receptive fields)
      -> N leaky integrate-and-fire neurons, all-to-all lateral inhibition
         (soft winner-take-all), adaptive thresholds (homeostasis)
      -> trace-based STDP with weight-dependent updates + per-neuron
         input normalisation

The recipe is Diehl & Cook (2015) with delay lines bolted on. No gradients, no
labels: the only teaching signal is "spikes that arrive just before I fire were
probably my fault".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DT = 1.0  # ms


@dataclass
class CortexConfig:
    n_in: int = 64  # auditory-nerve fibers
    n_neurons: int = 100
    delays_ms: tuple[int, ...] = (0, 12, 24, 36, 48)
    tau_m: float = 20.0  # membrane (ms)
    tau_e: float = 4.0  # excitatory synaptic current (ms)
    tau_i: float = 6.0  # inhibitory synaptic current (ms)
    v_th: float = 1.0
    refractory_ms: int = 4
    w_inh: float = 0.9  # lateral inhibition kick on a peer's spike
    w_max: float = 1.0
    w_sum: float = 6.0  # per-neuron total input weight (normalised after each word)
    tau_pre: float = 15.0  # STDP traces (ms)
    tau_post: float = 25.0
    eta_pre: float = 0.004  # depression rate (pre after post)
    eta_post: float = 0.02  # potentiation rate (pre before post)
    mu: float = 0.6  # weight dependence exponent
    theta_jump: float = 0.08  # threshold adaptation per spike
    tau_theta: float = 4000.0  # threshold decay (ms) — slow homeostasis
    seed: int = 0

    @property
    def n_syn(self) -> int:
        return self.n_in * len(self.delays_ms)


@dataclass
class CortexState:
    """What one presentation left behind — for the raster and the decoder."""

    spikes: np.ndarray  # (N, T) bool
    counts: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.counts = self.spikes.sum(axis=1).astype(np.float64)


class Cortex:
    def __init__(self, cfg: CortexConfig):
        self.cfg = cfg
        rng = np.random.default_rng(cfg.seed)
        S, N = cfg.n_syn, cfg.n_neurons
        self.W = rng.uniform(0.0, 0.3, size=(S, N))
        self._normalise()
        self.theta = np.zeros(N)  # adaptive threshold offsets
        self.alive = np.ones(N, dtype=bool)  # lesion mask
        self.plastic = True
        self.presentations = 0
        self.rng = rng

    # -- housekeeping -------------------------------------------------------

    def _normalise(self) -> None:
        col = self.W.sum(axis=0, keepdims=True) + 1e-9
        self.W *= self.cfg.w_sum / col
        np.clip(self.W, 0.0, self.cfg.w_max, out=self.W)

    def lesion(self, fraction: float) -> int:
        """Kill a random `fraction` of the currently-alive neurons. Returns #killed."""
        idx = np.flatnonzero(self.alive)
        k = int(round(fraction * len(idx)))
        if k <= 0:
            return 0
        kill = self.rng.choice(idx, size=k, replace=False)
        self.alive[kill] = False
        return k

    def heal(self) -> None:
        self.alive[:] = True

    def receptive_fields(self) -> np.ndarray:
        """(N, D, n_in) weights — per neuron, a delay x fiber spectro-temporal patch."""
        D = len(self.cfg.delays_ms)
        return self.W.T.reshape(self.cfg.n_neurons, D, self.cfg.n_in)

    # -- the simulation -----------------------------------------------------

    def _delayed_input(self, nerve: np.ndarray) -> np.ndarray:
        """Stack delayed copies of the nerve: (n_in*D, T)."""
        n_in, T = nerve.shape
        out = np.zeros((self.cfg.n_syn, T), dtype=bool)
        for k, d in enumerate(self.cfg.delays_ms):
            steps = int(d / DT)
            if steps < T:
                out[k * n_in : (k + 1) * n_in, steps:] = nerve[:, : T - steps]
        return out

    def present(self, nerve: np.ndarray, learn: bool | None = None) -> CortexState:
        """Run one utterance's nerve spikes (n_in, T) through the layer."""
        cfg = self.cfg
        learn = self.plastic if learn is None else learn
        x = self._delayed_input(nerve)
        S, T = x.shape
        N = cfg.n_neurons
        W = self.W

        v = np.zeros(N)
        g_e = np.zeros(N)
        g_i = np.zeros(N)
        refr = np.zeros(N, dtype=int)
        x_pre = np.zeros(S)
        x_post = np.zeros(N)
        out = np.zeros((N, T), dtype=bool)

        d_m = DT / cfg.tau_m
        dec_e = np.exp(-DT / cfg.tau_e)
        dec_i = np.exp(-DT / cfg.tau_i)
        dec_pre = np.exp(-DT / cfg.tau_pre)
        dec_post = np.exp(-DT / cfg.tau_post)
        dec_theta = np.exp(-DT / cfg.tau_theta)
        dead = ~self.alive

        for t in range(T):
            s_in = x[:, t]
            rows = np.flatnonzero(s_in)
            if rows.size:
                g_e += W[rows].sum(axis=0)
            v += d_m * (-v) + g_e * d_m * 2.0 - g_i * d_m * 2.0
            g_e *= dec_e
            g_i *= dec_i
            v[refr > 0] = 0.0
            refr -= 1
            fired = (v >= cfg.v_th + self.theta) & ~dead
            cols = np.flatnonzero(fired)
            if cols.size:
                out[cols, t] = True
                v[cols] = 0.0
                refr[cols] = cfg.refractory_ms
                # lateral inhibition: everyone else gets a kick
                g_i += cfg.w_inh * cols.size
                g_i[cols] -= cfg.w_inh
                if learn:
                    self.theta[cols] += cfg.theta_jump
            if learn:
                x_pre *= dec_pre
                x_pre[rows] += 1.0
                x_post *= dec_post
                x_post[cols] += 1.0
                if cols.size:
                    # potentiation: pre trace at post spike (only the columns that fired)
                    Wc = W[:, cols]
                    Wc += cfg.eta_post * x_pre[:, None] * (cfg.w_max - Wc) ** cfg.mu
                    np.minimum(Wc, cfg.w_max, out=Wc)
                    W[:, cols] = Wc
                if rows.size:
                    # depression: post trace at pre spike (only the rows that spiked)
                    Wr = W[rows]
                    Wr -= cfg.eta_pre * x_post[None, :] * Wr**cfg.mu
                    np.maximum(Wr, 0.0, out=Wr)
                    W[rows] = Wr
                self.theta *= dec_theta

        if learn:
            np.clip(W, 0.0, cfg.w_max, out=W)
            self._normalise()
        self.presentations += 1
        return CortexState(out)
