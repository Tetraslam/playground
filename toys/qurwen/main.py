"""qurwen — a phonotactic word generator for the Qurwenyan conlang.

Most playground toys take a word and *render* it (glyphgen -> SVG, phloraflora ->
plant, phonoscape -> landscape). This one is the upstream primitive: it *invents*
the words, from a phonotactic grammar. Feed it nothing and it samples the
Qurwenyan sound system; feed it a seed and the same seed always yields the same
word, so you can pipe its output straight into the other toys.

What "phonotactic" means here: words are built from syllables, syllables from
weighted onset / nucleus / coda slots, and consonant clusters are filtered by a
sonority hierarchy (so you get plausible `kr-` and `-lt` but never `-tk` mid-
cluster). The result *sounds* like one language instead of random letters.

    # one word
    uv run python toys/qurwen/main.py
    uv run python toys/qurwen/main.py --seed velthar

    # a themed mini-lexicon with English glosses
    uv run python toys/qurwen/main.py --lexicon 12

    # tune the shape: longer words, heavier clusters, an IPA column
    uv run python toys/qurwen/main.py -n 8 --syllables 2-4 --ipa

    # hand a generated word to a sister toy
    uv run python toys/qurwen/main.py --seed dawn \
      | xargs -I{} go run ./toys/glyphgen --word {} --out scratch/{}.svg

Stdlib only. Deterministic given --seed.
"""

from __future__ import annotations

import argparse
import hashlib

# --- the Qurwenyan sound system ---------------------------------------------
# Each phoneme is (romanization, IPA, weight). Weight biases sampling so the
# language has characteristic frequent sounds rather than a flat distribution.
# Sonority rank (below) drives which clusters are legal.

ONSET_CONS: list[tuple[str, str, float]] = [
    ("q", "q", 3.0),
    ("kh", "x", 2.5),
    ("th", "θ", 2.0),
    ("v", "v", 2.5),
    ("r", "r", 3.0),
    ("l", "l", 2.5),
    ("n", "n", 2.5),
    ("m", "m", 2.0),
    ("s", "s", 2.0),
    ("sh", "ʃ", 1.5),
    ("t", "t", 2.0),
    ("k", "k", 2.0),
    ("w", "w", 1.5),
    ("y", "j", 1.5),
    ("d", "d", 1.2),
    ("g", "g", 1.0),
    ("z", "z", 1.0),
    ("p", "p", 0.8),
    ("b", "b", 0.8),
    ("h", "h", 0.6),
]

# Codas: a tighter, more sonorant-leaning set (Qurwenyan likes liquid/nasal ends).
CODA_CONS: list[tuple[str, str, float]] = [
    ("r", "r", 3.0),
    ("l", "l", 2.5),
    ("n", "n", 3.0),
    ("th", "θ", 2.0),
    ("kh", "x", 1.5),
    ("s", "s", 1.5),
    ("m", "m", 1.5),
    ("q", "q", 1.0),
    ("t", "t", 1.0),
    ("sh", "ʃ", 0.8),
]

VOWELS: list[tuple[str, str, float]] = [
    ("a", "a", 3.0),
    ("e", "e", 2.5),
    ("i", "i", 2.5),
    ("u", "u", 2.0),
    ("o", "o", 1.8),
    ("ae", "ɛ", 1.2),
    ("ei", "eɪ", 1.0),
    ("au", "aʊ", 0.8),
    ("ii", "iː", 0.7),
    ("uu", "uː", 0.6),
]

# Sonority hierarchy: higher = more vowel-like. Onset clusters must *rise* toward
# the nucleus; coda clusters must *fall* away from it. This is what stops a toy
# language from emitting "tkbr".
SONORITY: dict[str, int] = {
    "stop": 1,
    "fric": 2,
    "nasal": 3,
    "liquid": 4,
    "glide": 5,
}
_CLASS = {
    "q": "stop",
    "k": "stop",
    "t": "stop",
    "d": "stop",
    "g": "stop",
    "p": "stop",
    "b": "stop",
    "kh": "fric",
    "th": "fric",
    "v": "fric",
    "s": "fric",
    "sh": "fric",
    "z": "fric",
    "h": "fric",
    "n": "nasal",
    "m": "nasal",
    "r": "liquid",
    "l": "liquid",
    "w": "glide",
    "y": "glide",
}

# Syllable templates with weights. C = consonant slot, V = nucleus, optional via
# lowercase. We keep it readable: onset/coda complexity comes from cluster rules.
TEMPLATES: list[tuple[str, float]] = [
    ("CV", 4.0),
    ("CVC", 3.5),
    ("CCV", 1.5),
    ("CVCC", 1.0),
    ("V", 1.0),
    ("VC", 1.2),
    ("CCVC", 0.8),
]

# A small inventory of derivational suffixes so --lexicon can attach meaning.
# (gloss-tag, romanization, IPA)
SUFFIXES: list[tuple[str, str, str]] = [
    ("place", "-en", "en"),
    ("agent", "-ar", "ar"),
    ("abstract", "-eth", "eθ"),
    ("plural", "-i", "i"),
    ("dimin", "-el", "el"),
    ("of", "-as", "as"),
]

# Seed glosses for the lexicon mode — evocative, worldbuilder-friendly roots.
GLOSS_POOL = [
    "river",
    "stone",
    "ember",
    "frost",
    "wind",
    "shadow",
    "dawn",
    "star",
    "root",
    "tide",
    "ash",
    "bloom",
    "hollow",
    "spire",
    "mire",
    "glow",
    "thorn",
    "veil",
    "echo",
    "drift",
    "rune",
    "moth",
    "loom",
    "vow",
]


class Rng:
    """Deterministic splitmix64 PRNG seeded from a string (matches house style)."""

    def __init__(self, seed: str):
        self.s = int.from_bytes(hashlib.blake2b(seed.encode(), digest_size=8).digest(), "little")

    def _next(self) -> int:
        self.s = (self.s + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return z ^ (z >> 31)

    def rand(self) -> float:
        return (self._next() >> 11) / float(1 << 53)

    def pick(self, weighted: list[tuple]) -> tuple:
        """Weighted choice. Items are tuples whose LAST element is the weight."""
        total = sum(item[-1] for item in weighted)
        r = self.rand() * total
        acc = 0.0
        for item in weighted:
            acc += item[-1]
            if r <= acc:
                return item
        return weighted[-1]


def _onset_cluster(rng: Rng, n: int) -> tuple[str, str]:
    """Build an n-consonant onset whose sonority rises toward the nucleus."""
    if n == 1:
        rom, ipa, _ = rng.pick(ONSET_CONS)
        return rom, ipa
    # two consonants: pick a first that is strictly less sonorous than a liquid/
    # glide second, so e.g. kr-, thl-, vr- but never rk-.
    firsts = [c for c in ONSET_CONS if SONORITY[_CLASS[c[0]]] <= 2]
    seconds = [c for c in ONSET_CONS if SONORITY[_CLASS[c[0]]] >= 4]
    f = rng.pick(firsts)
    s = rng.pick(seconds)
    return f[0] + s[0], f[1] + s[1]


def _coda_cluster(rng: Rng, n: int) -> tuple[str, str]:
    """Build an n-consonant coda whose sonority falls away from the nucleus."""
    if n == 1:
        rom, ipa, _ = rng.pick(CODA_CONS)
        return rom, ipa
    firsts = [c for c in CODA_CONS if SONORITY[_CLASS[c[0]]] >= 3]
    seconds = [c for c in CODA_CONS if SONORITY[_CLASS[c[0]]] <= 2]
    f = rng.pick(firsts)
    s = rng.pick(seconds)
    return f[0] + s[0], f[1] + s[1]


# vowels with a single mora — "simple" nuclei that may carry a heavy cluster.
_SIMPLE_VOWELS = [v for v in VOWELS if len(v[0]) == 1]


def _syllable(rng: Rng) -> tuple[str, str]:
    template = rng.pick(TEMPLATES)[0]
    # Pick the nucleus up front so the onset/coda can react to its weight: a
    # diphthong nucleus already makes the syllable heavy, so we forbid stacking a
    # consonant cluster around it (keeps roots pronounceable — no "vlei...twimsh").
    has_cluster = "CC" in template
    nucleus = rng.pick(_SIMPLE_VOWELS if has_cluster else VOWELS)

    rom_parts: list[str] = []
    ipa_parts: list[str] = []
    i = 0
    pre_v = True  # are we still in the onset (before the vowel)?
    while i < len(template):
        ch = template[i]
        if ch == "V":
            rom_parts.append(nucleus[0])
            ipa_parts.append(nucleus[1])
            pre_v = False
            i += 1
        else:  # a run of consonants
            run = 0
            while i < len(template) and template[i] == "C":
                run += 1
                i += 1
            if pre_v:
                rom, ipa = _onset_cluster(rng, run)
            else:
                rom, ipa = _coda_cluster(rng, run)
            rom_parts.append(rom)
            ipa_parts.append(ipa)
    return "".join(rom_parts), "".join(ipa_parts)


def generate(rng: Rng, min_syl: int, max_syl: int) -> tuple[str, str]:
    n = min_syl + int(rng.rand() * (max_syl - min_syl + 1))
    n = max(1, n)
    roms: list[str] = []
    ipas: list[str] = []
    for _ in range(n):
        r, p = _syllable(rng)
        roms.append(r)
        ipas.append(p)
    word = "".join(roms)
    ipa = "ˈ" + ".".join(ipas)  # primary stress on first syllable
    return word, ipa


def _capitalize(word: str) -> str:
    return word[:1].upper() + word[1:] if word else word


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate plausible Qurwenyan words from a phonotactic grammar."
    )
    ap.add_argument("--seed", default="", help="deterministic seed (omit = random-ish)")
    ap.add_argument("-n", "--count", type=int, default=1, help="how many words")
    ap.add_argument("--syllables", default="1-3", help="syllable range, e.g. '2-4'")
    ap.add_argument("--ipa", action="store_true", help="show IPA transcription")
    ap.add_argument(
        "--lexicon",
        type=int,
        default=0,
        help="emit N glossed root+suffix entries instead of bare words",
    )
    ap.add_argument("--cap", action="store_true", help="capitalize (proper nouns)")
    args = ap.parse_args()

    lo, _, hi = args.syllables.partition("-")
    min_syl = int(lo)
    max_syl = int(hi) if hi else min_syl

    base_seed = (
        args.seed
        or hashlib.blake2b(repr((args.count, args.syllables)).encode(), digest_size=6).hexdigest()
    )

    if args.lexicon:
        # build a small dictionary: each root gets a gloss + a derived form.
        rng = Rng(base_seed + "/lex")
        width = 0
        rows: list[tuple[str, str, str, str]] = []
        for k in range(args.lexicon):
            r = Rng(f"{base_seed}/{k}")
            # roots read best at 2-3 syllables; clamp the lexicon to that range.
            word, ipa = generate(r, 2, min(3, max(2, max_syl)))
            gloss = GLOSS_POOL[int(rng.rand() * len(GLOSS_POOL))]
            tag, sfx_rom, sfx_ipa = SUFFIXES[int(rng.rand() * len(SUFFIXES))]
            derived = word + sfx_rom.lstrip("-")
            rows.append((word, ipa, gloss, f"{derived} ({tag})"))
            width = max(width, len(word))
        print(f"# Qurwenyan lexicon  (seed: {base_seed})")
        for word, ipa, gloss, derived in rows:
            ipa_col = f"  /{ipa}/" if args.ipa else ""
            print(f"{word:<{width}}{ipa_col}  — {gloss:<8}  ~ {derived}")
        return

    for k in range(args.count):
        seed_k = base_seed if args.count == 1 else f"{base_seed}/{k}"
        rng = Rng(seed_k)
        word, ipa = generate(rng, min_syl, max_syl)
        if args.cap:
            word = _capitalize(word)
        print(f"{word}  /{ipa}/" if args.ipa else word)


if __name__ == "__main__":
    main()
