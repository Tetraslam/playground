"""hearsay.cochlea — from sound to auditory-nerve spikes.

Pipeline (all numpy, nothing borrowed from an audio library):

    word ──phonotone──> waveform ──gammatone bank──> 32 basilar-membrane channels
         ──hair cell (rectify, compress, low-pass)──> per-channel drive
         ──adapting LIF fibers──> auditory-nerve spike trains @ 1 ms

Speakers: the same word is uttered by many "speakers" (formant scaling for
vocal-tract length, F0 shift, tempo, source-noise seed, optional background
noise at a given SNR). That variation is what the cortex has to learn to
ignore.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    """Import a sibling toy's main.py by path (both are named main.py)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


phonotone = _load("phonotone_main", _HERE.parent / "phonotone" / "main.py")
qurwen = _load("qurwen_main", _HERE.parent / "qurwen" / "main.py")

FS = phonotone.FS  # 22050
DT_MS = 1.0  # simulation step for the spiking stages
N_CHANNELS = 32
F_LO, F_HI = 120.0, 7000.0
FIBERS_PER_CHANNEL = 2


# ---------------------------------------------------------------------------
# Vocabulary (qurwen) and utterances (phonotone + speaker variation)
# ---------------------------------------------------------------------------


def make_vocabulary(seed: str, n_words: int, syllables: tuple[int, int] = (1, 3)) -> list[str]:
    """n distinct Qurwenyan words (romanized) from qurwen's phonotactics."""
    rng = qurwen.Rng(f"hearsay:{seed}")
    words: list[str] = []
    seen: set[str] = set()
    while len(words) < n_words:
        w, _ipa = qurwen.generate(rng, syllables[0], syllables[1])
        if w not in seen and len(w) >= 2:
            seen.add(w)
            words.append(w)
    return words


@dataclass(frozen=True)
class Speaker:
    tract: float = 1.0  # formant frequency multiplier (vocal tract length)
    f0: float = 120.0  # base pitch (Hz)
    tempo: float = 1.0  # duration multiplier
    seed: int = 0  # source-noise seed
    snr_db: float | None = None  # additive white noise; None = clean

    @staticmethod
    def random(rng: np.random.Generator, snr_db: float | None = None) -> Speaker:
        return Speaker(
            tract=float(rng.uniform(0.86, 1.16)),
            f0=float(rng.uniform(85.0, 210.0)),
            tempo=float(rng.uniform(0.8, 1.25)),
            seed=int(rng.integers(0, 2**31 - 1)),
            snr_db=snr_db,
        )


def synth_utterance(word: str, spk: Speaker, pad_ms: float = 60.0) -> np.ndarray:
    """Speak `word` as `spk`. Returns float waveform at FS with silence padding."""
    ipa = phonotone.romanize_to_ipa(word)
    phs = phonotone.parse_ipa(ipa)
    phs = [
        replace(
            ph,
            forms=tuple((f * spk.tract, bw) for f, bw in ph.forms),
            dur_ms=ph.dur_ms * spk.tempo,
            closure_ms=ph.closure_ms * spk.tempo,
            burst_ms=ph.burst_ms * spk.tempo,
        )
        for ph in phs
    ]
    old_f0 = phonotone.F0_BASE
    phonotone.F0_BASE = spk.f0
    try:
        audio = phonotone.synth_word(phs, FS, spk.seed)
    finally:
        phonotone.F0_BASE = old_f0
    pad = np.zeros(int(FS * pad_ms / 1000))
    audio = np.concatenate([pad, audio, pad])
    if spk.snr_db is not None:
        rng = np.random.default_rng(spk.seed ^ 0xA5A5)
        sig_p = float(np.mean(audio**2)) + 1e-12
        noise_p = sig_p / (10 ** (spk.snr_db / 10))
        audio = audio + rng.normal(0.0, np.sqrt(noise_p), size=audio.shape)
    return audio


# ---------------------------------------------------------------------------
# Gammatone filterbank
# ---------------------------------------------------------------------------


def erb(f: np.ndarray | float) -> np.ndarray | float:
    return 24.7 * (4.37 * np.asarray(f) / 1000.0 + 1.0)


def erb_space(lo: float, hi: float, n: int) -> np.ndarray:
    """n centre frequencies equally spaced on the ERB-rate scale."""
    ear_q, min_bw = 9.26449, 24.7
    lo_e = np.log(lo + ear_q * min_bw)
    hi_e = np.log(hi + ear_q * min_bw)
    return -ear_q * min_bw + np.exp(np.linspace(hi_e, lo_e, n)) * 1.0


class Gammatone:
    """4th-order gammatone bank applied by FFT convolution (exact FIR, ~40 ms IRs)."""

    def __init__(self, fs: int = FS, n: int = N_CHANNELS, lo: float = F_LO, hi: float = F_HI):
        self.fs = fs
        self.cf = np.sort(erb_space(lo, hi, n))  # ascending
        ir_len = int(0.040 * fs)
        t = np.arange(ir_len) / fs
        b = 1.019 * erb(self.cf)  # (n,)
        env = t[None, :] ** 3 * np.exp(-2 * np.pi * b[:, None] * t[None, :])
        self.ir = env * np.cos(2 * np.pi * self.cf[:, None] * t[None, :])
        # unity peak gain per channel
        gains = np.abs(np.fft.rfft(self.ir, n=8192, axis=1)).max(axis=1)
        self.ir /= gains[:, None]

    def __call__(self, x: np.ndarray) -> np.ndarray:
        n_fft = 1 << int(np.ceil(np.log2(len(x) + self.ir.shape[1])))
        X = np.fft.rfft(x, n=n_fft)
        H = np.fft.rfft(self.ir, n=n_fft, axis=1)
        y = np.fft.irfft(X[None, :] * H, n=n_fft, axis=1)[:, : len(x)]
        return y  # (n_channels, samples)


def hair_cell(bm: np.ndarray, fs: int = FS, dt_ms: float = DT_MS) -> np.ndarray:
    """Inner hair cell: half-wave rectify, cube-root compress, low-pass, frame to dt.

    Returns drive (n_channels, n_frames) in roughly [0, 1] after a soft AGC.
    """
    r = np.maximum(bm, 0.0) ** (1.0 / 3.0)
    # leaky integrator (~1 kHz cutoff) as the hair-cell membrane
    alpha = np.exp(-2 * np.pi * 1000.0 / fs)
    out = np.empty_like(r)
    acc = np.zeros(r.shape[0])
    for i in range(r.shape[1]):
        acc = alpha * acc + (1 - alpha) * r[:, i]
        out[:, i] = acc
    hop = int(fs * dt_ms / 1000)
    n_frames = out.shape[1] // hop
    frames = out[:, : n_frames * hop].reshape(out.shape[0], n_frames, hop).mean(axis=2)
    # slow adaptation: each channel forgets its own steady floor (background
    # noise, hum) — only departures from it count
    floor = np.percentile(frames, 30, axis=1, keepdims=True)
    frames = np.maximum(frames - floor, 0.0)
    # soft AGC: normalise to the loud part of the utterance, not the peak
    scale = np.percentile(frames, 98) + 1e-9
    return np.clip(frames / scale, 0.0, 1.5)


def nerve_spikes(
    drive: np.ndarray,
    fibers: int = FIBERS_PER_CHANNEL,
    rng: np.random.Generator | None = None,
    gain: float = 8.0,
    tau_m: float = 8.0,
    tau_adapt: float = 60.0,
    adapt_jump: float = 0.35,
    noise: float = 0.05,
) -> np.ndarray:
    """Adapting LIF auditory-nerve fibers. drive (C, T) -> bool spikes (C*fibers, T).

    Spike-rate adaptation makes fibers onset-sensitive: sustained drive fades,
    changes stand out, which is what gives downstream STDP its temporal grip.
    """
    rng = rng or np.random.default_rng(0)
    C, T = drive.shape
    N = C * fibers
    d = np.repeat(drive, fibers, axis=0)  # (N, T)
    # each fiber gets its own sensitivity so a channel isn't 2 identical copies
    sens = rng.uniform(0.8, 1.25, size=(N, 1))
    d = d * sens * gain
    v = np.zeros(N)
    a = np.zeros(N)
    refr = np.zeros(N, dtype=int)
    out = np.zeros((N, T), dtype=bool)
    dv = DT_MS / tau_m
    da = DT_MS / tau_adapt
    for t in range(T):
        i_in = d[:, t] - a + noise * rng.standard_normal(N)
        v += dv * (-v + i_in)
        a -= da * a
        v[refr > 0] = 0.0
        refr -= 1
        s = v >= 1.0
        if s.any():
            out[s, t] = True
            v[s] = 0.0
            a[s] += adapt_jump
            refr[s] = 2
    return out


class Ear:
    """Sound -> nerve spikes, with a cached filterbank."""

    def __init__(self, seed: int = 0):
        self.bank = Gammatone()
        self.rng = np.random.default_rng(seed)

    @property
    def cf(self) -> np.ndarray:
        return self.bank.cf

    def hear(self, audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Returns (cochleagram (C,T) in [0,1.5], nerve spikes (C*fibers, T))."""
        # pre-emphasis flattens the glottal source's ~-6 dB/oct tilt so the
        # upper channels (fricatives, F3) aren't drowned by F1
        x = np.concatenate([audio[:1], audio[1:] - 0.95 * audio[:-1]])
        bm = self.bank(x)
        drive = hair_cell(bm)
        spikes = nerve_spikes(drive, rng=self.rng)
        return drive, spikes
