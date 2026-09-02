#!/usr/bin/env python3
"""hearsay — a spiking auditory cortex that learns to hear Qurwenyan.

    uv run python toys/hearsay/main.py live            # watch it learn, poke it
    uv run python toys/hearsay/main.py train           # full experiment -> examples/
    uv run python toys/hearsay/main.py say tho         # one word: raster PNG + decode

qurwen invents the vocabulary, phonotone speaks it (many speakers), a gammatone
cochlea turns it into auditory-nerve spikes, and a layer of LIF neurons with
STDP + lateral inhibition learns spectro-temporal receptive fields with no
labels. A population decoder reads the word back. Lesion it, drown it in noise,
and watch what the code does.
"""

from __future__ import annotations

import argparse
import pickle
import select
import shutil
import sys
import termios
import time
import tty
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cochlea as C  # noqa: E402
import cortex as X  # noqa: E402
import decode as D  # noqa: E402
import viz as V  # noqa: E402

HERE = Path(__file__).resolve().parent
RENDERS = HERE / "renders"
EXAMPLES = HERE / "examples"
N_BINS = 3  # temporal bins for the readout (early / middle / late)

DEFAULT_CFG = dict(
    n_in=C.N_CHANNELS * C.FIBERS_PER_CHANNEL,
    n_neurons=100,
    theta_jump=0.02,
    w_sum=12.0,
    w_inh=0.5,
    eta_post=0.005,
    eta_pre=0.003,
    w_max=0.3,
)


def binned(spikes: np.ndarray, nb: int = N_BINS) -> np.ndarray:
    """(N, T) spikes -> (N*nb,) counts in nb equal time bins."""
    T = spikes.shape[1]
    edges = np.linspace(0, T, nb + 1).astype(int)
    return np.concatenate([spikes[:, edges[i] : edges[i + 1]].sum(axis=1) for i in range(nb)])


def bin_mask(alive: np.ndarray, nb: int = N_BINS) -> np.ndarray:
    return np.tile(alive, nb)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class Split:
    x: list[np.ndarray]  # nerve spikes (n_in, T)
    y: np.ndarray
    coch: list[np.ndarray] = field(default_factory=list)  # cochleagrams (C, T)


@dataclass
class Data:
    words: list[str]
    train: Split
    test: dict[str, Split]  # condition name -> split


def build_data(
    seed: str, n_words: int, n_train: int, n_noisy: int, n_test: int, ear: C.Ear
) -> Data:
    words = C.make_vocabulary(seed, n_words)
    rng = np.random.default_rng(abs(hash(seed)) % (2**32))

    KEEP = "keep"  # use the speaker's own snr_db

    def hear_all(spk_fn, n_spk, cond_snr: list) -> dict[str, Split]:
        out = {str(s): Split([], []) for s in cond_snr}
        for wi, w in enumerate(words):
            for _ in range(n_spk):
                spk = spk_fn()
                for s in cond_snr:
                    snr = spk.snr_db if s == KEEP else s
                    a = C.synth_utterance(w, C.Speaker(spk.tract, spk.f0, spk.tempo, spk.seed, snr))
                    drive, sp = ear.hear(a)
                    out[str(s)].x.append(sp)
                    out[str(s)].y.append(wi)
                    out[str(s)].coch.append(drive)
        for sp_ in out.values():
            sp_.y = np.array(sp_.y)
        return out

    clean = hear_all(lambda: C.Speaker.random(rng), n_train, [KEEP])[KEEP]
    noisy = hear_all(
        lambda: C.Speaker.random(rng, snr_db=float(rng.uniform(5.0, 15.0))), n_noisy, [KEEP]
    )[KEEP]
    train = Split(clean.x + noisy.x, np.concatenate([clean.y, noisy.y]), clean.coch + noisy.coch)
    test = hear_all(lambda: C.Speaker.random(rng), n_test, [None, 10.0, 0.0])
    test = {{"None": "clean", "10.0": "snr10", "0.0": "snr0"}[k]: v for k, v in test.items()}
    return Data(words, train, test)


def cached_data(args, ear: C.Ear) -> Data:
    RENDERS.mkdir(exist_ok=True)
    key = f"data_{args.seed}_{args.words}_{args.speakers}_{args.noisy_speakers}_{args.test_speakers}.pkl"
    path = RENDERS / key
    if path.exists() and not args.fresh:
        with path.open("rb") as f:
            return pickle.load(f)
    t0 = time.time()
    print(f"synthesising {args.words} words x speakers ...", file=sys.stderr, flush=True)
    data = build_data(
        args.seed, args.words, args.speakers, args.noisy_speakers, args.test_speakers, ear
    )
    with path.open("wb") as f:
        pickle.dump(data, f)
    print(f"  {len(data.train.x)} train utterances, {time.time() - t0:.1f}s", file=sys.stderr)
    return data


# ---------------------------------------------------------------------------
# Training / evaluation
# ---------------------------------------------------------------------------


def train_cortex(ctx: X.Cortex, split: Split, epochs: int, rng: np.random.Generator, log=None):
    order = np.arange(len(split.x))
    for ep in range(epochs):
        rng.shuffle(order)
        spikes = 0.0
        for i in order:
            spikes += ctx.present(split.x[i]).counts.sum()
        if log:
            log(
                f"epoch {ep + 1}/{epochs}  spikes/word {spikes / len(order):.0f}  theta {ctx.theta.mean():.2f}"
            )
    ctx.plastic = False


def responses(ctx: X.Cortex, split: Split) -> np.ndarray:
    return np.stack([binned(ctx.present(x, learn=False).spikes) for x in split.x])


def nerve_features(split: Split) -> np.ndarray:
    return np.stack([binned(x) for x in split.x])


def evaluate(data: Data, ctx: X.Cortex, ctx0: X.Cortex, log) -> dict:
    """Trained cortex vs untrained cortex vs raw nerve, all decoders, all conditions."""
    K = len(data.words)
    systems = {
        "cortex (stdp)": (lambda s: responses(ctx, s)),
        "cortex (untrained)": (lambda s: responses(ctx0, s)),
        "nerve (no cortex)": nerve_features,
    }
    results: dict = {"acc": {}, "confusion": None, "decoders": {}, "feats": {}}
    for name, fn in systems.items():
        ftr = fn(data.train)
        dec = D.PopulationDecoder(K).fit(ftr, data.train.y)
        results["decoders"][name] = dec
        for cond, split in data.test.items():
            fte = fn(split)
            results["feats"][(name, cond)] = fte
            for m in ("vote", "template", "poisson"):
                pred = dec.decode(m, fte)
                results["acc"][(name, cond, m)] = D.accuracy(pred, split.y)
                if name == "cortex (stdp)" and cond == "snr10" and m == "poisson":
                    results["confusion"] = D.confusion(pred, split.y, K)
        log(
            f"{name:20s} "
            + "  ".join(
                f"{cond}: "
                + "/".join(
                    f"{results['acc'][(name, cond, m)]:.2f}"
                    for m in ("vote", "template", "poisson")
                )
                for cond in data.test
            )
        )
    return results


def lesion_sweep(
    data: Data,
    ctx: X.Cortex,
    dec: D.PopulationDecoder,
    cond: str,
    fracs: np.ndarray,
    trials: int = 5,
) -> dict[str, np.ndarray]:
    """Accuracy vs fraction of cortex neurons killed (decoder is NOT refit)."""
    rng = np.random.default_rng(123)
    split = data.test[cond]
    fte = responses(ctx, split)
    out = {m: np.zeros(len(fracs)) for m in ("template", "poisson")}
    for i, f in enumerate(fracs):
        for _ in range(trials):
            alive = np.ones(ctx.cfg.n_neurons, dtype=bool)
            k = int(round(f * ctx.cfg.n_neurons))
            if k:
                alive[rng.choice(ctx.cfg.n_neurons, size=k, replace=False)] = False
            mask = bin_mask(alive)
            for m in out:
                out[m][i] += D.accuracy(dec.decode(m, fte, mask), split.y) / trials
    return out


def nerve_lesion_sweep(
    data: Data, dec: D.PopulationDecoder, cond: str, fracs: np.ndarray, trials: int = 5
) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(123)
    split = data.test[cond]
    fte = nerve_features(split)
    n = split.x[0].shape[0]
    out = {m: np.zeros(len(fracs)) for m in ("template", "poisson")}
    for i, f in enumerate(fracs):
        for _ in range(trials):
            alive = np.ones(n, dtype=bool)
            k = int(round(f * n))
            if k:
                alive[rng.choice(n, size=k, replace=False)] = False
            mask = bin_mask(alive)
            for m in out:
                out[m][i] += D.accuracy(dec.decode(m, fte, mask), split.y) / trials
    return out


def cmd_train(args) -> int:
    ear = C.Ear(0)
    data = cached_data(args, ear)
    log = lambda s: print(s, flush=True)  # noqa: E731
    K = len(data.words)
    log(f"vocabulary ({K}): {' '.join(data.words)}")

    cfg = X.CortexConfig(**{**DEFAULT_CFG, "n_neurons": args.neurons, "seed": 0})
    ctx = X.Cortex(cfg)
    ctx0 = X.Cortex(cfg)  # same initial weights, never trained
    ctx0.plastic = False
    t0 = time.time()
    train_cortex(ctx, data.train, args.epochs, np.random.default_rng(0), log)
    log(f"trained in {time.time() - t0:.1f}s")

    log("accuracy  (vote/template/poisson)")
    res = evaluate(data, ctx, ctx0, log)

    out = EXAMPLES if args.examples else RENDERS
    out.mkdir(exist_ok=True)

    # receptive fields, sorted by the word each neuron votes for
    dec = res["decoders"]["cortex (stdp)"]
    rfs = ctx.receptive_fields()
    order = np.argsort(dec.labels[: cfg.n_neurons])
    V.write_png(out / "rfs.png", V.rf_gallery(rfs, cols=20, cell=6, order=order))
    V.write_png(out / "rfs_untrained.png", V.rf_gallery(ctx0.receptive_fields(), cols=20, cell=6))

    # a raster for one noisy test utterance
    split = data.test["snr10"]
    i = int(np.flatnonzero(split.y == 0)[0])
    st = ctx.present(split.x[i], learn=False)
    coch = split.coch[i][:, : split.x[i].shape[1]]
    V.write_png(out / "raster.png", V.raster_image(split.x[i], st.spikes, coch, scale=2))

    # confusion at 10 dB
    V.write_png(out / "confusion.png", V.matrix_image(res["confusion"], cell=16))

    # lesion sweeps
    fracs = np.linspace(0.0, 0.9, 10)
    les = lesion_sweep(data, ctx, dec, "snr10", fracs)
    les_n = nerve_lesion_sweep(data, res["decoders"]["nerve (no cortex)"], "snr10", fracs)
    V.write_png(
        out / "lesion.png",
        V.curve_image(
            fracs,
            {
                "cortex poisson": les["poisson"],
                "cortex template": les["template"],
                "nerve poisson": les_n["poisson"],
                "nerve template": les_n["template"],
            },
        ),
    )
    log(
        "lesion (10 dB, poisson): "
        + " ".join(f"{f:.1f}:{a:.2f}" for f, a in zip(fracs, les["poisson"], strict=True))
    )
    log(
        "lesion (10 dB, nerve  ): "
        + " ".join(f"{f:.1f}:{a:.2f}" for f, a in zip(fracs, les_n["poisson"], strict=True))
    )

    # results table (markdown)
    lines = ["| system | decoder | clean | 10 dB | 0 dB |", "|---|---|---|---|---|"]
    for name in ("cortex (stdp)", "cortex (untrained)", "nerve (no cortex)"):
        for m in ("vote", "template", "poisson"):
            row = [f"{res['acc'][(name, cond, m)]:.2f}" for cond in ("clean", "snr10", "snr0")]
            lines.append(f"| {name} | {m} | " + " | ".join(row) + " |")
    lines += ["", "lesion (10 dB test, decoder not refit), fraction killed -> accuracy:", ""]
    lines += [
        "| killed | cortex poisson | cortex template | nerve poisson | nerve template |",
        "|---|---|---|---|---|",
    ]
    for i, f in enumerate(fracs):
        lines.append(
            f"| {f:.1f} | {les['poisson'][i]:.2f} | {les['template'][i]:.2f} | {les_n['poisson'][i]:.2f} | {les_n['template'][i]:.2f} |"
        )
    (out / "results.md").write_text("\n".join(lines) + "\n")
    with (RENDERS / "model.pkl").open("wb") as f:
        pickle.dump({"cfg": cfg, "W": ctx.W, "theta": ctx.theta, "words": data.words}, f)
    log(f"wrote {out}/{{rfs,rfs_untrained,raster,confusion,lesion}}.png + results.md")
    return 0


# ---------------------------------------------------------------------------
# say: one word, end to end
# ---------------------------------------------------------------------------


def cmd_say(args) -> int:
    ear = C.Ear(0)
    rng = np.random.default_rng(args.speaker_seed)
    spk = C.Speaker.random(rng, snr_db=args.snr)
    audio = C.synth_utterance(args.word, spk)
    coch, nerve = ear.hear(audio)
    model_path = RENDERS / "model.pkl"
    if model_path.exists():
        with model_path.open("rb") as f:
            m = pickle.load(f)
        ctx = X.Cortex(m["cfg"])
        ctx.W = m["W"]
        ctx.theta = m["theta"]
        ctx.plastic = False
    else:
        ctx = X.Cortex(X.CortexConfig(**DEFAULT_CFG))
        ctx.plastic = False
        print("(no trained model in renders/ — using an untrained cortex; run `train` first)")
    st = ctx.present(nerve)
    out = Path(args.out) if args.out else RENDERS / f"say_{args.word}.png"
    V.write_png(out, V.raster_image(nerve, st.spikes, coch[:, : nerve.shape[1]], scale=2))
    print(
        f"{args.word!r} as speaker(tract={spk.tract:.2f}, f0={spk.f0:.0f}Hz, tempo={spk.tempo:.2f})"
        f"  {audio.size / C.FS:.2f}s  nerve {int(nerve.sum())} spikes  cortex {int(st.counts.sum())} spikes"
        f"  active neurons {int((st.counts > 0).sum())}/{ctx.cfg.n_neurons}\n-> {out}"
    )
    return 0


# ---------------------------------------------------------------------------
# live: an online learner you can poke
# ---------------------------------------------------------------------------


class OnlineDecoder:
    """Class-conditional running means of the binned response; decodes by
    Poisson log-likelihood and by cosine template. Updated after every word,
    so it tracks a cortex whose weights are still moving."""

    def __init__(self, k: int, dim: int, tau: float = 20.0):
        self.k, self.dim, self.tau = k, dim, tau
        self.means = np.ones((k, dim)) * 0.5
        self.n = np.zeros(k)

    def update(self, feat: np.ndarray, y: int) -> None:
        self.n[y] += 1
        a = 1.0 / min(self.n[y], self.tau)
        self.means[y] = (1 - a) * self.means[y] + a * feat

    def predict(self, feat: np.ndarray, alive: np.ndarray) -> tuple[int, int]:
        mask = bin_mask(alive)
        mu = self.means * mask + 1e-3
        ll = (feat * mask) @ np.log(mu).T - mu.sum(axis=1)
        cen = self.means * mask
        cos = (cen @ (feat * mask)) / (
            np.linalg.norm(cen, axis=1) * np.linalg.norm(feat * mask) + 1e-9
        )
        return int(ll.argmax()), int(cos.argmax())


class RawKeys:
    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    def poll(self) -> str | None:
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None


def _downsample_cols(a: np.ndarray, width: int) -> np.ndarray:
    """(R, T) -> (R, width) by max-pooling along time."""
    T = a.shape[1]
    edges = np.linspace(0, T, width + 1).astype(int)
    return np.stack(
        [a[:, edges[i] : max(edges[i] + 1, edges[i + 1])].max(axis=1) for i in range(width)], axis=1
    )


def cmd_live(args) -> int:
    ear = C.Ear(0)
    words = C.make_vocabulary(args.seed, args.words)
    K = len(words)
    cfg = X.CortexConfig(**{**DEFAULT_CFG, "n_neurons": args.neurons, "seed": 0})
    ctx = X.Cortex(cfg)
    dec = OnlineDecoder(K, cfg.n_neurons * N_BINS)
    rng = np.random.default_rng(int(time.time()) if args.seed == "live" else 1)
    snr: float | None = None
    history: list[bool] = []
    history_t: list[bool] = []
    paused = False
    n_heard = 0
    width = max(40, min(120, shutil.get_terminal_size((100, 40)).columns - 4))
    last_msg = ""
    hi = V.ansi_rgb

    def frame(word, spk, coch, nerve, st, guess, guess_t) -> str:
        lines = []
        acc = np.mean(history[-40:]) if history else 0.0
        acc_t = np.mean(history_t[-40:]) if history_t else 0.0
        alive = int(ctx.alive.sum())
        snr_s = "clean" if snr is None else f"{snr:+.0f} dB"
        lines.append(
            hi("hearsay", (255, 200, 90))
            + f"  heard {n_heard:4d}  stdp {'ON ' if ctx.plastic else 'off'}  noise {snr_s:6s}"
            f"  alive {alive:3d}/{cfg.n_neurons}  acc/40: poisson {acc:.2f} template {acc_t:.2f}"
        )
        ok = words[guess] == word
        lines.append(
            f"  said {hi(word, (120, 220, 255))}  (tract {spk.tract:.2f} f0 {spk.f0:.0f} tempo {spk.tempo:.2f})"
            f"  heard {hi(words[guess], (140, 255, 140) if ok else (255, 110, 90))}"
            f"  template: {words[guess_t]}"
        )
        lines.append("")
        # cochleagram: 32 channels -> 8 rows (4 channels each), time -> width
        ds = _downsample_cols(coch, width)
        ds = ds.reshape(8, 4, width).max(axis=1)[::-1]
        lines.append("  cochlea  " + hi("7 kHz", (120, 120, 120)))
        for r in range(8):
            lines.append("  " + V.ansi_heat_row(ds[r] / (ds.max() + 1e-9), "magma"))
        lines.append("  " + hi("120 Hz", (120, 120, 120)))
        # cortex raster: neurons -> rows of 10, time -> width; brightness = spikes in cell
        sp = _downsample_cols(st.spikes.astype(np.float64), width)
        rows = int(np.ceil(cfg.n_neurons / 10))
        grid = np.zeros((rows, 10, width))
        grid.reshape(-1, width)[: cfg.n_neurons] = sp
        lines.append(
            "  cortex   " + hi("(each row = 10 neurons; colour = which one fired)", (120, 120, 120))
        )
        for r in range(rows):
            row = ""
            for tcol in range(width):
                who = np.flatnonzero(grid[r, :, tcol])
                if who.size == 0:
                    row += "\x1b[48;2;14;14;14m "
                else:
                    n = int(who[0])
                    if not ctx.alive[r * 10 + n]:
                        row += "\x1b[48;2;80;30;30m "
                    else:
                        hue = V.cmap(np.array((n + 0.5) / 10.0), "viridis")
                        row += f"\x1b[48;2;{hue[0]};{hue[1]};{hue[2]}m "
            lines.append("  " + row + "\x1b[0m")
        # receptive fields of the 10 most active neurons this word: spectral profile as a heat row
        rfs = ctx.receptive_fields().sum(axis=1)  # (N, n_in) summed over delays
        top = np.argsort(-st.counts)[:6]
        lines.append("")
        lines.append("  6 loudest neurons: receptive field (120 Hz -> 7 kHz), word it votes for")
        for n in top:
            prof = rfs[n].reshape(C.N_CHANNELS, C.FIBERS_PER_CHANNEL).mean(axis=1)
            lab = (
                words[int(dec.means[:, n :: cfg.n_neurons].sum(axis=1).argmax())]
                if dec.n.sum()
                else "?"
            )
            lines.append(
                f"  #{n:3d} {int(st.counts[n]):3d} spk  "
                + V.ansi_heat_row(prof / (prof.max() + 1e-9), "viridis")
                + f"  {lab}"
            )
        lines.append("")
        lines.append(
            hi("  keys: ", (120, 120, 120))
            + "[n/N] noise +/-  [l]esion 10%  [h]eal  [p]lasticity  [space] pause  [q]uit  "
            + hi(last_msg, (255, 200, 90))
        )
        return "\n".join(lines)

    if args.shot:
        # headless: hear N words (with one lesion + some noise for drama), dump the last frame
        shot_words = args.shot_words
        for i in range(shot_words):
            if i == int(shot_words * 0.7):
                ctx.lesion(0.2)
                last_msg = "lesioned 20 neurons (20 dead)"
            if i == int(shot_words * 0.85):
                snr = 15.0
            wi = int(rng.integers(K))
            spk = C.Speaker.random(rng, snr_db=snr)
            coch, nerve = ear.hear(C.synth_utterance(words[wi], spk))
            st = ctx.present(nerve)
            feat = binned(st.spikes)
            guess, guess_t = dec.predict(feat, ctx.alive)
            if dec.n.sum() >= K:
                history.append(guess == wi)
                history_t.append(guess_t == wi)
            dec.update(feat, wi)
            n_heard += 1
        text = frame(words[wi], spk, coch, nerve, st, guess, guess_t)
        html_path = RENDERS / "live.html"
        RENDERS.mkdir(exist_ok=True)
        html_path.write_text(V.ansi_to_html(text))
        ok = V.html_screenshot(html_path, Path(args.shot), width=width * 9 + 40, height=560)
        print(f"{'wrote' if ok else 'no chromium; html only at'} {args.shot if ok else html_path}")
        return 0

    sys.stdout.write("\x1b[?25l\x1b[2J")
    try:
        with RawKeys() as keys:
            while True:
                k = keys.poll()
                if k == "q":
                    break
                elif k == " ":
                    paused = not paused
                elif k == "n":
                    snr = 20.0 if snr is None else max(-10.0, snr - 5.0)
                    last_msg = f"noise -> {snr:+.0f} dB SNR"
                elif k == "N":
                    snr = None if snr is None or snr >= 20.0 else snr + 5.0
                    last_msg = "clean" if snr is None else f"noise -> {snr:+.0f} dB SNR"
                elif k == "l":
                    killed = ctx.lesion(0.10)
                    last_msg = f"lesioned {killed} neurons ({int((~ctx.alive).sum())} dead)"
                elif k == "h":
                    ctx.heal()
                    last_msg = "healed"
                elif k == "p":
                    ctx.plastic = not ctx.plastic
                    last_msg = f"plasticity {'on' if ctx.plastic else 'off'}"
                if paused:
                    time.sleep(0.05)
                    continue
                wi = int(rng.integers(K))
                word = words[wi]
                spk = C.Speaker.random(rng, snr_db=snr)
                audio = C.synth_utterance(word, spk)
                coch, nerve = ear.hear(audio)
                st = ctx.present(nerve)
                feat = binned(st.spikes)
                guess, guess_t = dec.predict(feat, ctx.alive)
                if dec.n.sum() >= K:  # don't score until every word has been heard once
                    history.append(guess == wi)
                    history_t.append(guess_t == wi)
                dec.update(feat, wi)
                n_heard += 1
                sys.stdout.write(
                    "\x1b[H" + frame(word, spk, coch, nerve, st, guess, guess_t) + "\x1b[J"
                )
                sys.stdout.flush()
                time.sleep(args.delay)
    finally:
        sys.stdout.write("\x1b[?25h\n")
    return 0


# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description="hearsay — a spiking cortex that learns to hear Qurwenyan"
    )
    p.add_argument("--seed", default="ember", help="vocabulary seed (qurwen)")
    p.add_argument("--words", type=int, default=20)
    p.add_argument("--neurons", type=int, default=100)
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("train", help="full experiment: train, evaluate, lesion sweep, PNGs")
    t.add_argument("--epochs", type=int, default=4)
    t.add_argument("--speakers", type=int, default=8, help="clean training speakers per word")
    t.add_argument(
        "--noisy-speakers", type=int, default=4, help="noisy (5-15 dB) training speakers per word"
    )
    t.add_argument("--test-speakers", type=int, default=4)
    t.add_argument("--fresh", action="store_true", help="ignore the cached dataset")
    t.add_argument(
        "--examples", action="store_true", help="write PNGs into examples/ instead of renders/"
    )
    t.set_defaults(fn=cmd_train)

    s = sub.add_parser("say", help="speak one word through the trained cortex -> raster PNG")
    s.add_argument("word")
    s.add_argument("--snr", type=float, default=None)
    s.add_argument("--speaker-seed", type=int, default=0)
    s.add_argument("--out", default=None)
    s.set_defaults(fn=cmd_say)

    lv = sub.add_parser("live", help="online learning you can watch and poke")
    lv.add_argument("--delay", type=float, default=0.15, help="pause between words (s)")
    lv.add_argument(
        "--shot",
        default=None,
        help="headless: run --shot-words words, screenshot the frame to this PNG",
    )
    lv.add_argument("--shot-words", type=int, default=150)
    lv.set_defaults(fn=cmd_live)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
