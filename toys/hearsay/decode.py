"""hearsay.decode — reading a word back out of a population of spike counts.

Three decoders, all fit on the *training* responses of the frozen cortex:

  label-vote   each neuron is labelled with the word it fires most for (relative
               to its mean); a test count vector votes by summed rate per label.
               Diehl & Cook's readout. Cheap, and it's what "population code"
               usually means in a textbook.
  template     nearest class centroid by cosine on the count vector.
  poisson-ml   each neuron's count is Poisson with a class-specific mean;
               pick the class maximising the total log-likelihood.

Plus two *baselines* that skip the cortex entirely (nearest centroid on the
cochleagram's mean spectrum, and on raw nerve counts), so we can tell whether
the spiking layer earned anything.

Lesions are applied by masking neurons in the count vectors; decoders never see
the mask, which is the point — a population code should not need to be told
who died.
"""

from __future__ import annotations

import numpy as np


class PopulationDecoder:
    def __init__(self, n_classes: int):
        self.k = n_classes
        self.labels: np.ndarray | None = None  # (N,) neuron -> class
        self.centroids: np.ndarray | None = None  # (k, N)
        self.means: np.ndarray | None = None  # (k, N) Poisson means

    def fit(self, counts: np.ndarray, y: np.ndarray) -> PopulationDecoder:
        """counts (M, N) training responses, y (M,) class ids."""
        k, N = self.k, counts.shape[1]
        rates = np.zeros((k, N))
        for c in range(k):
            m = y == c
            if m.any():
                rates[c] = counts[m].mean(axis=0)
        self.means = rates + 1e-3
        self.centroids = rates
        # label a neuron by its most selective class (rate relative to its own mean)
        rel = rates / (rates.mean(axis=0, keepdims=True) + 1e-9)
        self.labels = rel.argmax(axis=0)
        return self

    def _masked(self, counts: np.ndarray, alive: np.ndarray | None) -> np.ndarray:
        if alive is None:
            return counts
        return counts * alive[None, :]

    def vote(self, counts: np.ndarray, alive: np.ndarray | None = None) -> np.ndarray:
        assert self.labels is not None
        c = self._masked(np.atleast_2d(counts), alive)
        scores = np.zeros((c.shape[0], self.k))
        for cls in range(self.k):
            m = self.labels == cls
            if alive is not None:
                m = m & alive
            n = max(1, int(m.sum()))
            scores[:, cls] = c[:, m].sum(axis=1) / n
        return scores.argmax(axis=1)

    def template(self, counts: np.ndarray, alive: np.ndarray | None = None) -> np.ndarray:
        assert self.centroids is not None
        c = self._masked(np.atleast_2d(counts), alive)
        cen = self._masked(self.centroids, alive)
        num = c @ cen.T
        den = np.linalg.norm(c, axis=1)[:, None] * np.linalg.norm(cen, axis=1)[None, :] + 1e-9
        return (num / den).argmax(axis=1)

    def poisson(self, counts: np.ndarray, alive: np.ndarray | None = None) -> np.ndarray:
        assert self.means is not None
        c = np.atleast_2d(counts)
        mu = self.means
        # log P(n | mu) summed over alive neurons, dropping the n! term (class-independent)
        ll = c @ np.log(mu).T - mu.sum(axis=1)[None, :] if alive is None else None
        if alive is not None:
            ll = (c * alive) @ (np.log(mu) * alive).T - (mu * alive).sum(axis=1)[None, :]
        return ll.argmax(axis=1)

    def decode(self, method: str, counts: np.ndarray, alive: np.ndarray | None = None):
        return {"vote": self.vote, "template": self.template, "poisson": self.poisson}[method](
            counts, alive
        )


def accuracy(pred: np.ndarray, y: np.ndarray) -> float:
    return float((pred == y).mean()) if len(y) else float("nan")


def confusion(pred: np.ndarray, y: np.ndarray, k: int) -> np.ndarray:
    m = np.zeros((k, k), dtype=int)
    for p, t in zip(pred, y, strict=True):
        m[t, p] += 1
    return m


class CentroidBaseline:
    """Nearest centroid (cosine) on any fixed feature vector — no cortex involved."""

    def fit(self, feats: np.ndarray, y: np.ndarray, k: int) -> CentroidBaseline:
        self.c = np.stack([feats[y == i].mean(axis=0) for i in range(k)])
        return self

    def predict(self, feats: np.ndarray) -> np.ndarray:
        num = feats @ self.c.T
        den = np.linalg.norm(feats, axis=1)[:, None] * np.linalg.norm(self.c, axis=1)[None, :]
        return (num / (den + 1e-9)).argmax(axis=1)
