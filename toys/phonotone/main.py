#!/usr/bin/env python3
"""phonotone — formant synthesis for Qurwenyan words.

Takes a romanized word (or raw IPA), synthesizes speech-like audio from
scratch (no recorded phonemes — pulses + noise through cascaded 2-pole
resonators, Klatt-style), and renders a spectrogram SVG you can read while
listening. Same word -> same wav. Composes with qurwen (upstream):
    uv run python toys/qurwen/main.py --seed ember --ipa \\
        | xargs -I{} uv run python toys/phonotone/main.py --ipa {}
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FS = 22050  # mono, plenty for speech-ish formants out to ~8 kHz
F0_BASE = 120.0  # Hz; F0 contour is built per word
DEFAULT_AMP = 0.55  # master output ceiling


# ---------------------------------------------------------------------------
# Phoneme spec
#
# Each phoneme is described uniformly: how much voiced source, how much noise
# source, which formants the source is filtered through during its lifetime,
# and how long it lives. Plosives carry a closure sub-segment.
# ---------------------------------------------------------------------------


@dataclass
class Phoneme:
    ipa: str  # canonical symbol, e.g. "a", "θ", "q"
    kind: str  # vowel | plosive | fricative | nasal | liquid | glide | silence
    voiced_amp: float = 0.0  # glottal-pulse-train amplitude during the open phase
    noise_amp: float = 0.0  # white-noise amplitude during the open phase
    closure_voiced: float = 0.0  # voiced hum during the silent closure (plosives)
    forms: tuple[tuple[float, float], ...] = ()  # (freq_hz, bandwidth_hz)
    dur_ms: float = 110.0
    closure_ms: float = 0.0  # for plosives: silence-then-burst split
    burst_ms: float = 0.0  # rest of dur_ms after the closure
    amp: float = 0.7  # phoneme-level amplitude (relative)
    stressed: bool = False  # marks the syllable bearing primary stress


VOWELS: dict[str, tuple[tuple[float, float], ...]] = {
    # F1, F2, F3 in Hz, with reasonable bandwidths. Standard Klatt-ish values.
    "a": ((700, 130), (1200, 150), (2500, 200)),
    "ɑ": ((700, 130), (1100, 150), (2500, 200)),
    "æ": ((800, 130), (1700, 150), (2500, 200)),
    "e": ((480, 110), (2000, 150), (2600, 200)),
    "ɛ": ((600, 110), (1800, 150), (2500, 200)),
    "ɪ": ((400, 110), (1900, 150), (2550, 200)),
    "ə": ((520, 110), (1500, 150), (2500, 200)),
    "ʌ": ((600, 110), (1200, 150), (2400, 200)),
    "i": ((300, 90), (2200, 150), (2900, 200)),
    "ɨ": ((320, 90), (1500, 150), (2500, 200)),
    "u": ((300, 90), (870, 150), (2200, 220)),
    "ʊ": ((400, 90), (1000, 150), (2300, 220)),
    "o": ((500, 100), (800, 150), (2400, 220)),
    "ɔ": ((570, 110), (840, 150), (2400, 220)),
    "ɶ": ((820, 130), (1500, 150), (2600, 200)),
}

DIPHTHONGS: dict[str, tuple[str, str, float]] = {
    # IPA -> (start, target, glide_ms). The synthesized diphthong ramps the
    # three formants from start-target to finish-target across its duration.
    "aɪ": ("a", "ɪ", 110),
    "aʊ": ("a", "ʊ", 130),
    "eɪ": ("e", "ɪ", 110),
    "oʊ": ("o", "ʊ", 130),
    "ɔɪ": ("ɔ", "ɪ", 110),
    "əʊ": ("ə", "ʊ", 130),
}

# Consonants: (kind, voiced_amp, noise_amp, closure_voiced, forms, dur_ms, closure_ms, burst_ms, amp)
CONSONANTS: dict[str, dict] = {
    # plosives — short closure (silence or voiced hum for VOICED stops), then a brief noisy burst
    "p": dict(
        kind="plosive",
        voiced_amp=0.0,
        noise_amp=1.0,
        closure_voiced=0.0,
        forms=((500, 150), (1500, 200), (2500, 250)),
        dur_ms=80,
        closure_ms=55,
        burst_ms=25,
        amp=0.55,
    ),
    "b": dict(
        kind="plosive",
        voiced_amp=0.0,
        noise_amp=0.9,
        closure_voiced=0.5,
        forms=((500, 150), (1500, 200), (2500, 250)),
        dur_ms=80,
        closure_ms=60,
        burst_ms=20,
        amp=0.55,
    ),
    "t": dict(
        kind="plosive",
        voiced_amp=0.0,
        noise_amp=1.0,
        closure_voiced=0.0,
        forms=((1500, 200), (3500, 300), (5000, 400)),
        dur_ms=70,
        closure_ms=50,
        burst_ms=20,
        amp=0.55,
    ),
    "d": dict(
        kind="plosive",
        voiced_amp=0.0,
        noise_amp=0.9,
        closure_voiced=0.6,
        forms=((300, 150), (1500, 250), (2700, 250)),
        dur_ms=70,
        closure_ms=55,
        burst_ms=15,
        amp=0.55,
    ),
    "k": dict(
        kind="plosive",
        voiced_amp=0.0,
        noise_amp=1.0,
        closure_voiced=0.0,
        forms=((1200, 200), (2500, 300), (4000, 400)),
        dur_ms=75,
        closure_ms=55,
        burst_ms=20,
        amp=0.55,
    ),
    "g": dict(
        kind="plosive",
        voiced_amp=0.0,
        noise_amp=0.9,
        closure_voiced=0.6,
        forms=((300, 150), (1200, 250), (2400, 250)),
        dur_ms=75,
        closure_ms=60,
        burst_ms=15,
        amp=0.55,
    ),
    "q": dict(
        kind="plosive",
        voiced_amp=0.0,
        noise_amp=1.0,
        closure_voiced=0.0,
        forms=((900, 200), (1800, 300), (3000, 400)),
        dur_ms=80,
        closure_ms=60,
        burst_ms=20,
        amp=0.50,
    ),
    "ʔ": dict(
        kind="plosive",
        voiced_amp=0.0,
        noise_amp=0.6,
        closure_voiced=0.0,
        forms=((1000, 200), (2000, 300), (3000, 400)),
        dur_ms=60,
        closure_ms=45,
        burst_ms=15,
        amp=0.40,
    ),
    # fricatives — sustained noise source, with voicing added if voiced
    "f": dict(
        kind="fricative",
        voiced_amp=0.0,
        noise_amp=1.0,
        forms=((2000, 400), (4500, 500), (6500, 600)),
        dur_ms=110,
        amp=0.40,
    ),
    "v": dict(
        kind="fricative",
        voiced_amp=0.35,
        noise_amp=0.65,
        forms=((300, 150), (1200, 200), (2400, 250)),
        dur_ms=100,
        amp=0.45,
    ),
    "θ": dict(
        kind="fricative",
        voiced_amp=0.0,
        noise_amp=1.0,
        forms=((2500, 500), (5500, 600), (7500, 700)),
        dur_ms=110,
        amp=0.30,
    ),
    "ð": dict(
        kind="fricative",
        voiced_amp=0.35,
        noise_amp=0.65,
        forms=((400, 150), (1400, 200), (2400, 250)),
        dur_ms=100,
        amp=0.40,
    ),
    "s": dict(
        kind="fricative",
        voiced_amp=0.0,
        noise_amp=1.0,
        forms=((3000, 400), (4500, 300), (6500, 400)),
        dur_ms=120,
        amp=0.50,
    ),
    "z": dict(
        kind="fricative",
        voiced_amp=0.35,
        noise_amp=0.65,
        forms=((300, 150), (1600, 250), (4000, 400)),
        dur_ms=120,
        amp=0.50,
    ),
    "ʃ": dict(
        kind="fricative",
        voiced_amp=0.0,
        noise_amp=1.0,
        forms=((2600, 250), (3500, 200), (5500, 400)),
        dur_ms=120,
        amp=0.45,
    ),
    "ʒ": dict(
        kind="fricative",
        voiced_amp=0.35,
        noise_amp=0.65,
        forms=((300, 150), (1500, 250), (2500, 300)),
        dur_ms=120,
        amp=0.45,
    ),
    "h": dict(
        kind="fricative",
        voiced_amp=0.0,
        noise_amp=1.0,
        forms=((500, 300), (1500, 300), (2500, 300)),
        dur_ms=90,
        amp=0.30,
    ),
    "x": dict(
        kind="fricative",
        voiced_amp=0.0,
        noise_amp=1.0,
        forms=((1500, 250), (2500, 300), (4000, 400)),
        dur_ms=110,
        amp=0.45,
    ),
    "ɣ": dict(
        kind="fricative",
        voiced_amp=0.35,
        noise_amp=0.65,
        forms=((300, 150), (1500, 250), (2400, 300)),
        dur_ms=110,
        amp=0.45,
    ),
    "χ": dict(
        kind="fricative",
        voiced_amp=0.0,
        noise_amp=1.0,
        forms=((800, 250), (1800, 300), (3000, 400)),
        dur_ms=110,
        amp=0.40,
    ),
    "ʁ": dict(
        kind="fricative",
        voiced_amp=0.35,
        noise_amp=0.65,
        forms=((250, 150), (1100, 250), (2400, 300)),
        dur_ms=110,
        amp=0.40,
    ),
    # nasals — voiced, low-pass formant chain (the nasal murmur)
    "m": dict(
        kind="nasal",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=((250, 100), (1100, 200), (2250, 300)),
        dur_ms=80,
        amp=0.65,
    ),
    "n": dict(
        kind="nasal",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=((280, 100), (1700, 200), (2400, 300)),
        dur_ms=80,
        amp=0.65,
    ),
    "ɲ": dict(
        kind="nasal",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=((280, 100), (2200, 200), (2750, 300)),
        dur_ms=80,
        amp=0.65,
    ),
    "ŋ": dict(
        kind="nasal",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=((250, 100), (220, 200), (2400, 300)),
        dur_ms=80,
        amp=0.65,
    ),
    "ɴ": dict(
        kind="nasal",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=((250, 100), (800, 200), (2500, 300)),
        dur_ms=80,
        amp=0.65,
    ),
    # liquids — voiced, distinctive formant structure
    "l": dict(
        kind="liquid",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=((350, 120), (1200, 200), (2600, 300)),
        dur_ms=90,
        amp=0.70,
    ),
    "ɫ": dict(
        kind="liquid",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=((450, 120), (1000, 200), (2500, 300)),
        dur_ms=90,
        amp=0.70,
    ),
    "r": dict(
        kind="liquid",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=((330, 120), (1800, 200), (2500, 300)),
        dur_ms=90,
        amp=0.70,
    ),
    "ɾ": dict(
        kind="liquid",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=((300, 120), (1700, 200), (2500, 300)),
        dur_ms=60,
        amp=0.70,
    ),
    "ɻ": dict(
        kind="liquid",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=((330, 120), (1500, 200), (2400, 300)),
        dur_ms=90,
        amp=0.70,
    ),
    # glides — short vowels
    "j": dict(
        kind="glide",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=((300, 90), (2200, 200), (2700, 300)),
        dur_ms=70,
        amp=0.65,
    ),
    "w": dict(
        kind="glide",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=((300, 90), (870, 200), (2200, 300)),
        dur_ms=70,
        amp=0.65,
    ),
}


def _vowel_phoneme(ipa: str, stressed: bool, length_factor: float = 1.0) -> Phoneme:
    return Phoneme(
        ipa=ipa,
        kind="vowel",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=VOWELS[ipa],
        dur_ms=160.0 * length_factor,
        amp=0.85,
        stressed=stressed,
    )


def _diphthong_phoneme(ipa: str, stressed: bool) -> Phoneme:
    start, target, _glide_ms = DIPHTHONGS[ipa]
    start_f = VOWELS[start]
    target_f = VOWELS[target]
    # Average the two endpoints as the "publish" formant set; the synthesizer
    # ramps from start via target during the glide using these two stacks.
    avg = tuple(
        ((s[0] + t[0]) / 2, (s[1] + t[1]) / 2) for s, t in zip(start_f, target_f, strict=True)
    )
    return Phoneme(
        ipa=ipa,
        kind="diphthong",
        voiced_amp=1.0,
        noise_amp=0.0,
        forms=avg,
        dur_ms=200.0,
        amp=0.85,
        stressed=stressed,
    )


def _consonant_phoneme(ipa: str) -> Phoneme:
    c = CONSONANTS[ipa]
    return Phoneme(
        ipa=ipa,
        kind=c["kind"],
        voiced_amp=c.get("voiced_amp", 0.0),
        noise_amp=c.get("noise_amp", 0.0),
        closure_voiced=c.get("closure_voiced", 0.0),
        forms=tuple(c.get("forms", ())),
        dur_ms=c.get("dur_ms", 100.0),
        closure_ms=c.get("closure_ms", 0.0),
        burst_ms=c.get("burst_ms", 0.0),
        amp=c.get("amp", 0.6),
    )


# ---------------------------------------------------------------------------
# IPA parser
#
# Walks an IPA string left-to-right, preferentially matching 2-char
# diphthongs and length-modified vowels, falling back to 1-char tokens.
# Skips stress / syllable markers; lengthens the previous vowel on ː.
# ---------------------------------------------------------------------------


STRESS = "ˈ"
SEC_STRESS = "ˌ"
SYL_BOUNDARY = "."
LENGTH = "ː"
PRIMARY_MARKER = "̚"  # not used here, just declared for clarity

VOWEL_KEYS = set(VOWELS.keys())
DIPHTHONG_KEYS = set(DIPHTHONGS.keys())
CONSONANT_KEYS = set(CONSONANTS.keys())


def parse_ipa(ipa: str) -> list[Phoneme]:
    out: list[Phoneme] = []
    i = 0
    stressed_next = False
    while i < len(ipa):
        ch = ipa[i]
        if ch in (STRESS, SEC_STRESS):
            stressed_next = True
            i += 1
            continue
        if ch in (SYL_BOUNDARY, " ", "/", "ˑ"):
            # ˑ is half-length; treat as ordinary segment boundary
            i += 1
            continue
        if ch == LENGTH:
            # Apply length to the previous vowel if last thing was a vowel
            if out and out[-1].kind == "vowel":
                out[-1].dur_ms *= 1.8
            i += 1
            continue
        # try diphthong (2-char) first
        two = ipa[i : i + 2]
        if two in DIPHTHONG_KEYS:
            out.append(_diphthong_phoneme(two, stressed_next))
            stressed_next = False
            i += 2
            continue
        # try vowel (1-char)
        if ch in VOWEL_KEYS:
            out.append(_vowel_phoneme(ch, stressed_next))
            stressed_next = False
            i += 1
            continue
        # try consonant
        if ch in CONSONANT_KEYS:
            out.append(_consonant_phoneme(ch))
            i += 1
            continue
        # unknown: log but keep walking
        sys.stderr.write(f"phonotone: skipping unknown IPA symbol {ch!r}\n")
        i += 1
    if not out:
        raise ValueError(f"no recognized phonemes in IPA: {ipa!r}")
    return out


# ---------------------------------------------------------------------------
# Romanization -> IPA
#
# A small Bible of substitutions matching qurwen's inventory, applied
# longest-first so 'kh' beats 'k' and 'ae' beats 'a'. Deterministic.
# ---------------------------------------------------------------------------


ROMAN_TO_IPA: list[tuple[str, str]] = [
    ("kh", "x"),
    ("th", "θ"),
    ("sh", "ʃ"),
    ("ae", "ɛ"),
    ("ei", "eɪ"),
    ("au", "aʊ"),
    ("ii", "iː"),
    ("uu", "uː"),
    ("q", "q"),
    ("k", "k"),
    ("t", "t"),
    ("d", "d"),
    ("g", "g"),
    ("p", "p"),
    ("b", "b"),
    ("v", "v"),
    ("s", "s"),
    ("z", "z"),
    ("h", "h"),
    ("n", "n"),
    ("m", "m"),
    ("r", "r"),
    ("l", "l"),
    ("w", "w"),
    ("y", "j"),
    ("a", "a"),
    ("e", "e"),
    ("i", "i"),
    ("o", "o"),
    ("u", "u"),
]


def romanize_to_ipa(word: str) -> str:
    """Apply the romanization table to a Qurwenyan word, longest tokens first.

    Inserts a primary-stress marker at the start (Qurwenyan stress is initial)
    and syllable boundaries at vowel-consonant transitions where ambiguous.
    """
    w = word.strip().lower()
    ipa = ""
    i = 0
    while i < len(w):
        matched = False
        for rom, ip in ROMAN_TO_IPA:
            if w.startswith(rom, i):
                ipa += ip
                i += len(rom)
                matched = True
                break
        if not matched:
            sys.stderr.write(f"phonotone: skipping unknown roman char {w[i]!r}\n")
            i += 1
        # we deliberately don't insert syllable boundaries here — they're only
        # used by parse_ipa to skip char; stress is inserted at the head below
    return STRESS + ipa


# ---------------------------------------------------------------------------
# Determinism
#
# Source noise is the one stochastic piece. We seed numpy from the input
# string so the same word produces the same audio (matches qurwen / glyphgen).
# ---------------------------------------------------------------------------


def _seed_from(s: str) -> int:
    h = hashlib.sha256(s.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big", signed=False)


# ---------------------------------------------------------------------------
# Source generators
# ---------------------------------------------------------------------------


def rosenberg_pulse_train(n: int, f0: float, fs: int) -> np.ndarray:
    """A pulse train with a 50%% open quotient. Energy-per-pulse is normalized
    so amplitude is roughly independent of F0."""
    period = int(round(fs / f0))
    if period < 4:
        period = 4
    open_n = period // 2
    pulse = np.zeros(period, dtype=np.float64)
    if open_n > 1:
        pulse[:open_n] = np.sin(np.pi * np.arange(open_n) / (open_n - 1))
    energy = pulse.sum()
    if energy > 0:
        pulse /= energy
    reps = (n // period) + 2
    train = np.tile(pulse, reps)
    return train[:n].copy()


def white_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    return rng.standard_normal(n)


# ---------------------------------------------------------------------------
# Formant filter (2-pole resonator) via closed-form impulse response.
# ---------------------------------------------------------------------------


def resonator_ir(freq: float, bw: float, fs: int, length: int | None = None) -> np.ndarray:
    """Closed-form 2-pole resonator impulse response:
        h[n] = R^n * sin(theta * n) * u[n]
    where R = exp(-pi * bw / fs) and theta = 2*pi*freq/fs. Truncated when the
    envelope falls below -60 dB (so length scales with fs/bw)."""
    if freq <= 0 or bw <= 0:
        return np.array([1.0])
    R = np.exp(-np.pi * bw / fs)
    theta = 2 * np.pi * freq / fs
    if length is None:
        # tau = 1 / (pi * bw / fs); 5 tau -> -91 dB
        length = max(8, int(np.ceil(5 * fs / (np.pi * bw))))
    n = np.arange(length)
    ir = (R**n) * np.sin(theta * n)
    # normalize so peak amplitude is ~1 (so cascade doesn't blow up at single freq)
    peak = np.max(np.abs(ir))
    if peak > 0:
        ir /= peak
    return ir


def _filt(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Causal convolution truncated to len(x). np.convolve(mode="same") returns
    max(len(x), len(h)) samples, which blows up when a segment is shorter than
    the resonator IR (fast tempo, short bursts) — this never does."""
    return np.convolve(x, h)[: len(x)]


def composite_ir(forms: tuple[tuple[float, float], ...], fs: int) -> np.ndarray:
    """Compose the impulse responses of cascaded 2-pole resonators into one IR."""
    out = np.array([1.0])
    for f, bw in forms:
        h = resonator_ir(f, bw, fs)
        out = np.convolve(out, h)
    return out


def _envelope(n: int, fs: int, attack_ms: float = 8.0, release_ms: float = 12.0) -> np.ndarray:
    a = int(fs * attack_ms / 1000)
    r = int(fs * release_ms / 1000)
    env = np.ones(n)
    if a > 0 and a < n:
        env[:a] = np.linspace(0.0, 1.0, a, endpoint=False)
    if r > 0 and r < n:
        env[-r:] = np.linspace(1.0, 0.0, r, endpoint=True)
    return env


def synth_phoneme(ph: Phoneme, f0: float, fs: int, rng: np.random.Generator) -> np.ndarray:
    """Render one phoneme to a 1-D numpy array at sample rate `fs`.

    Plosives split their lifetime into [closure | burst]; closures are silent
    (or a low-amp voiced hum for voiced stops), bursts are a short noisy
    feature. Other phonemes produce a sustained source shaped by an envelope.
    """
    n_total = int(fs * ph.dur_ms / 1000)
    if ph.kind == "plosive":
        n_closure = int(fs * ph.closure_ms / 1000)
        n_burst = max(8, n_total - n_closure)
        out = np.zeros(n_total)
        if ph.closure_voiced > 0 and n_closure > 0:
            closure = rosenberg_pulse_train(n_closure, f0, fs) * ph.closure_voiced * 0.25
            h = composite_ir(((250, 100), (800, 200), (1800, 250)), fs)
            closure = _filt(closure, h)
            out[:n_closure] = closure
        burst_noise = white_noise(n_burst, rng) * ph.noise_amp
        burst = burst_noise
        h = composite_ir(ph.forms, fs)
        burst = _filt(burst, h)
        # very fast rise (1ms), slower decay (~30ms) so the burst "pops"
        env = _envelope(n_burst, fs, attack_ms=1.0, release_ms=30.0)
        out[n_closure:] = burst * env
    elif ph.kind == "diphthong":
        # Build two formant composite IRs (start, target) and cross-fade between
        # them. Pre-compute both segment signals and ramp from one to the other.
        start, target, _ = DIPHTHONGS[ph.ipa]
        h_start = composite_ir(VOWELS[start], fs)
        h_target = composite_ir(VOWELS[target], fs)
        src = rosenberg_pulse_train(n_total, f0, fs) * ph.voiced_amp
        if ph.noise_amp > 0:
            src = src + white_noise(n_total, rng) * ph.noise_amp * 0.3
        seg_start = _filt(src, h_start)
        seg_target = _filt(src, h_target)
        ramp = np.linspace(0.0, 1.0, n_total)
        out = seg_start * (1 - ramp) + seg_target * ramp
        env = _envelope(n_total, fs, attack_ms=15.0, release_ms=25.0)
        out *= env
    else:
        # vowel, fricative, nasal, liquid, glide — uniform LTI path
        voiced = rosenberg_pulse_train(n_total, f0, fs) * ph.voiced_amp
        noise = white_noise(n_total, rng) * ph.noise_amp
        src = voiced + noise
        h = composite_ir(ph.forms, fs)
        out = _filt(src, h)
        env = _envelope(
            n_total,
            fs,
            attack_ms=10.0 if ph.kind in ("fricative", "vowel") else 15.0,
            release_ms=20.0 if ph.kind == "fricative" else 40.0,
        )
        out *= env
    # Normalize each phoneme per-spec to keep relative amplitudes meaningful.
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 1e-6:
        out = out * (ph.amp / peak)
    return out


def crossfade_concat(segments: list[np.ndarray], fs: int, ms: float = 8.0) -> np.ndarray:
    """Crossfade adjacent segments with a short overlap so consecutive phonemes
    don't click. The overlap region linearly blends the tail of one segment
    into the head of the next."""
    if len(segments) == 1:
        return segments[0]
    n = int(fs * ms / 1000)
    total = sum(len(s) for s in segments) - n * (len(segments) - 1)
    out = np.zeros(max(0, total))
    pos = 0
    for i, seg in enumerate(segments):
        if i == 0:
            out[pos : pos + len(seg)] = seg
            pos += len(seg) - n
        elif i == len(segments) - 1:
            tail = out[pos : pos + n]
            head = seg[:n]
            out[pos : pos + n] = tail + head  # additive in the overlap, then linear bleed
            out[pos + n : pos + n + len(seg) - n] = seg[n:]
            pos += len(seg)
        else:
            tail = out[pos : pos + n]
            head = seg[:n]
            w = np.linspace(0.0, 1.0, n)
            out[pos : pos + n] = tail * (1 - w) + head * w
            out[pos + n : pos + n + len(seg) - n] = seg[n:]
            pos += len(seg) - n
    return out


# ---------------------------------------------------------------------------
# F0 contour — small downward drift with a bump on stressed syllables.
# ---------------------------------------------------------------------------


def f0_contour(phonemes: list[Phoneme], total_samples: int, fs: int) -> np.ndarray:
    """Per-sample F0 (Hz). Starts at F0+8, drifts to F0-8 by end;
    any stressed syllable adds +25 Hz with a smooth bell across its span."""
    base = F0_BASE + np.linspace(8.0, -8.0, max(1, total_samples))
    bumps = np.zeros(max(1, total_samples))
    pos = 0
    for ph in phonemes:
        n = int(fs * ph.dur_ms / 1000)
        if ph.stressed:
            local_t = np.arange(n) / fs
            bell = np.exp(-((local_t - local_t.max() / 2) ** 2) / (2 * (n / fs * 0.3 + 1) ** 2))
            bumps[pos : pos + n] += 25.0 * bell
        pos += n
    return base + bumps


# ---------------------------------------------------------------------------
# Master synth
# ---------------------------------------------------------------------------


def synth_word(phonemes: list[Phoneme], fs: int, seed_int: int) -> np.ndarray:
    rng = np.random.default_rng(seed_int)
    f0_track = f0_contour(phonemes, sum(int(fs * ph.dur_ms / 1000) for ph in phonemes), fs)
    segments: list[np.ndarray] = []
    pos = 0
    for ph in phonemes:
        n = int(fs * ph.dur_ms / 1000)
        f0_mid = float(f0_track[pos + n // 2]) if (pos + n // 2) < len(f0_track) else F0_BASE
        seg = synth_phoneme(ph, f0_mid, fs, rng)
        segments.append(seg)
        pos += n
    audio = crossfade_concat(segments, fs, ms=8.0)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 1e-6:
        audio = audio * (DEFAULT_AMP / peak)
    return audio


# ---------------------------------------------------------------------------
# WAV writer (stdlib only)
# ---------------------------------------------------------------------------


def write_wav(path: Path, samples: np.ndarray, fs: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scaled = np.clip(samples, -1.0, 1.0)
    pcm = (scaled * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(pcm)


# ---------------------------------------------------------------------------
# Spectrogram -> SVG. STFT via numpy, log-magnitude, vmin/vmax scaled to the
# loudest bin in the word. Formant-track overlay is computed from the phoneme
# specs so it shows what the synth is actually doing.
# ---------------------------------------------------------------------------


def _jetish(t: float) -> str:
    """A small warm-to-cool map. t in [0,1]. Returns an SVG hex color."""
    t = max(0.0, min(1.0, t))
    if t < 0.25:
        # dark navy -> cyan
        f = t / 0.25
        r, g, b = 0.05, 0.10 + 0.40 * f, 0.20 + 0.30 * f
    elif t < 0.50:
        # cyan -> green-yellow
        f = (t - 0.25) / 0.25
        r, g, b = 0.05 + 0.30 * f, 0.50 + 0.40 * f, 0.50 - 0.30 * f
    elif t < 0.75:
        # yellow -> orange
        f = (t - 0.50) / 0.25
        r, g, b = 0.35 + 0.55 * f, 0.90 - 0.30 * f, 0.20 - 0.20 * f
    else:
        # orange -> near-white
        f = (t - 0.75) / 0.25
        r, g, b = 0.90 + 0.10 * f, 0.60 + 0.30 * f, 0.0 + 0.85 * f
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def spectrogram_svg(
    samples: np.ndarray,
    fs: int,
    phonemes: list[Phoneme],
    title: str,
    out_path: Path,
    *,
    width: int = 980,
    height: int = 360,
    max_freq: float = 8000.0,
    n_time: int = 240,
    n_freq: int = 96,
) -> None:
    """Render a heatmap SVG with overlaid F1/F2/F3 tracks and phoneme labels."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    samples = samples.astype(np.float64)

    # --- STFT ---
    win_len = 2 * round(2 ** int(np.log2(len(samples) / n_time)))
    hop = max(1, (len(samples) - win_len) // n_time)
    n_actual = max(1, (len(samples) - win_len) // hop + 1)
    window = np.hanning(win_len)
    frame = np.zeros((n_actual, win_len // 2 + 1))
    for k in range(n_actual):
        seg = samples[k * hop : k * hop + win_len] * window
        spec = np.fft.rfft(seg)
        frame[k] = np.abs(spec)
    mag = np.log1p(frame)
    # frequency bins to display
    freqs = np.fft.rfftfreq(win_len, 1 / fs)
    f_mask = freqs <= max_freq
    f_idx = np.where(f_mask)[0]
    # compress n_freq display-bins
    coarse = np.zeros((n_actual, n_freq))
    for j in range(n_freq):
        lo = j * len(f_idx) // n_freq
        hi = (j + 1) * len(f_idx) // n_freq
        if hi <= lo:
            hi = lo + 1
        coarse[:, j] = mag[:, f_idx][lo:hi].max(axis=1)

    vmax = coarse.max() if coarse.max() > 0 else 1.0
    vmin = vmax - 6.0  # 6 dB dynamic range floor
    coarse = (coarse - vmin) / (vmax - vmin)
    coarse = np.clip(coarse, 0.0, 1.0)

    # --- formant track: x in [0, n_actual), y in [0, max_freq] ---
    margin_l, margin_r = 60, 16
    margin_t, margin_b = 28, 40
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b

    def time_to_x(sample_idx: int) -> float:
        t = sample_idx / fs
        total = (len(samples) - 1) / fs
        return margin_l + (t / total) * plot_w if total > 0 else margin_l

    def freq_to_y(freq: float) -> float:
        return margin_t + (1 - freq / max_freq) * plot_h

    # Formant segment boundaries — phoneme positions in samples (pre crossfade)
    ph_boundaries = [0]
    for ph in phonemes:
        ph_boundaries.append(ph_boundaries[-1] + int(fs * ph.dur_ms / 1000))

    def formant_track(formant_index: int) -> tuple[list[float], list[float]]:
        xs, ys = [], []
        for i, ph in enumerate(phonemes):
            mid = (ph_boundaries[i] + ph_boundaries[i + 1]) / 2
            if ph.kind in ("vowel", "diphthong", "nasal", "liquid", "glide"):
                f = ph.forms[formant_index][0]
                xs.append(time_to_x(mid))
                ys.append(freq_to_y(f))
            elif ph.kind == "plosive":
                # trace a brief trajectory: closure (low), burst (mid), release (back to neighbor)
                burst_mid = ph_boundaries[i] + int(fs * (ph.closure_ms + ph.burst_ms / 2) / 1000)
                f = ph.forms[formant_index][0]
                xs.append(time_to_x(burst_mid))
                ys.append(freq_to_y(f))
            elif ph.kind == "fricative":
                mid = (ph_boundaries[i] + ph_boundaries[i + 1]) / 2
                # fricatives don't have a "formant" in the same sense, but use the
                # peak of their noise filter as a stylized indicator.
                f = ph.forms[formant_index][0]
                xs.append(time_to_x(mid))
                ys.append(freq_to_y(f))
        return xs, ys

    # --- SVG ---
    parts: list[str] = []
    parts.append(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
        f' viewBox="0 0 {width} {height}" font-family="ui-monospace, SF Mono, Menlo, Consolas, monospace">'
    )
    parts.append(f'<rect width="{width}" height="{height}" fill="#0c1018"/>')
    parts.append(f'<text x="{margin_l}" y="20" fill="#d8dee9" font-size="12">{title}</text>')

    # heatmap cells
    cell_w = plot_w / n_actual
    cell_h = plot_h / n_freq
    for k in range(n_actual):
        for j in range(n_freq):
            v = coarse[k, j]
            if v < 0.04:
                continue
            x = margin_l + k * cell_w
            y = margin_t + plot_h - (j + 1) * cell_h
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{cell_w + 0.6:.2f}" height="{cell_h + 0.6:.2f}" fill="{_jetish(v)}"/>'
            )

    # freq axis labels (0, 2k, 4k, 6k, 8k)
    for f in (0, 2000, 4000, 6000, 8000):
        y = freq_to_y(f)
        parts.append(
            f'<line x1="{margin_l - 4}" y1="{y:.1f}" x2="{margin_l}" y2="{y:.1f}" stroke="#4c566a"/>'
        )
        label = f"{f // 1000}k" if f > 0 else "0"
        parts.append(
            f'<text x="{margin_l - 8}" y="{y + 3:.1f}" fill="#8f9aab" font-size="9" text-anchor="end">{label}</text>'
        )

    # phoneme labels along the bottom (boundary ticks)
    for i, ph in enumerate(phonemes):
        x = time_to_x(ph_boundaries[i + 1])
        parts.append(
            f'<line x1="{x:.1f}" y1="{margin_t}" x2="{x:.1f}" y2="{margin_t + plot_h}" stroke="#2e3440" stroke-width="0.5"/>'
        )
        # tick above the phoneme span
        mid = time_to_x((ph_boundaries[i] + ph_boundaries[i + 1]) / 2)
        col = "#f0a070" if ph.stressed else "#8f9aab"
        parts.append(
            f'<text x="{mid:.1f}" y="{height - 22}" fill="{col}" font-size="11" text-anchor="middle">{ph.ipa}</text>'
        )

    # formant track overlays: F1 (red), F2 (lime), F3 (sky)
    for fi, color, _name in [(0, "#ff5577", "F1"), (1, "#88dd6a", "F2"), (2, "#66bbff", "F3")]:
        xs, ys = formant_track(fi)
        if len(xs) < 2:
            continue
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
        parts.append(
            f'<polyline points="{pts}" stroke="{color}" stroke-width="1.6" fill="none" stroke-opacity="0.9"/>'
        )
        parts.append(f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="2.2" fill="{color}"/>')

    # small legend
    legend_x = width - margin_r - 90
    for i, (color, name) in enumerate([("#ff5577", "F1"), ("#88dd6a", "F2"), ("#66bbff", "F3")]):
        parts.append(f'<circle cx="{legend_x}" cy="{22 + i * 14}" r="3" fill="{color}"/>')
        parts.append(
            f'<text x="{legend_x + 8}" y="{22 + i * 14 + 3}" fill="#d8dee9" font-size="9">{name}</text>'
        )

    parts.append("</svg>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _generate_from_qurwen(seed: str | None) -> tuple[str, str]:
    """Use qurwen to produce a word; returns (romanization, ipa)."""
    cmd = ["uv", "run", "python", str(Path(__file__).parent.parent / "qurwen" / "main.py")]
    if seed:
        cmd += ["--seed", seed]
    cmd += ["--ipa"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    out = res.stdout.strip()
    # qurwen prints "<rom>  /<ipa>/"  — parse the two halves
    m = re.match(r"(\S+)\s+/([^/]+)/", out)
    if not m:
        raise RuntimeError(f"could not parse qurwen output: {out!r}")
    return m.group(1), m.group(2)


def main() -> int:
    p = argparse.ArgumentParser(description="phonotone — speak a Qurwenyan word.")
    p.add_argument("word", nargs="?", help="romanization, e.g. vrakh (auto-IPA-encoded)")
    p.add_argument("--ipa", help="raw IPA string, e.g. 'ˈdut.xa.veɪθ'")
    p.add_argument("--seed", help="delegate to qurwen with this string seed")
    p.add_argument("--out", default="scratch/phonotone/out", help="prefix for .wav/.svg outputs")
    p.add_argument("--fs", type=int, default=FS, help="sample rate (Hz)")
    args = p.parse_args()

    # resolve the input
    if args.ipa:
        ipa = args.ipa
        roman = args.ipa
    elif args.seed is not None:
        roman, ipa = _generate_from_qurwen(args.seed)
    elif args.word:
        ipa = romanize_to_ipa(args.word)
        roman = args.word
    else:
        p.error("pass a romanization, --ipa, or --seed")

    phonemes = parse_ipa(ipa)
    seed_int = _seed_from(ipa)
    audio = synth_word(phonemes, args.fs, seed_int)

    out = Path(args.out)
    wav_path = out.with_suffix(".wav")
    svg_path = out.with_suffix(".svg")
    write_wav(wav_path, audio, args.fs)
    spectrogram_svg(audio, args.fs, phonemes, f"phonotone  {roman}  /{ipa}/", svg_path)

    dur = len(audio) / args.fs
    print(f"phonotone: {roman}  /{ipa}/")
    print(f"  {len(phonemes):2d} phonemes  {dur:.2f}s  ->  {wav_path}")
    print(f"  spectrogram ->  {svg_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
