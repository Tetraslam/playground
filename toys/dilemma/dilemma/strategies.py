"""Classic IPD strategies."""

from random import Random as _Random


class Strategy:
    name = "base"

    def move(self, my_history: list[str], their_history: list[str]) -> str:
        raise NotImplementedError


class AlwaysCooperate(Strategy):
    name = "all_c"

    def move(self, my_history, their_history):
        return "C"


class AlwaysDefect(Strategy):
    name = "all_d"

    def move(self, my_history, their_history):
        return "D"


class TitForTat(Strategy):
    name = "tft"

    def move(self, my_history, their_history):
        return "C" if not their_history else their_history[-1]


class SuspiciousTitForTat(Strategy):
    name = "suspicious_tft"

    def move(self, my_history, their_history):
        return "D" if not their_history else their_history[-1]


class Grudger(Strategy):
    name = "grudger"

    def move(self, my_history, their_history):
        return "D" if "D" in their_history else "C"


class Joss(Strategy):
    """TFT but sneaks in a random defection 10% of the time."""

    name = "joss"

    def __init__(self):
        self.rng = _Random(0)

    def move(self, my_history, their_history):
        if self.rng.random() < 0.10:
            return "D"
        return "C" if not their_history else their_history[-1]


class Tester(Strategy):
    """Defects once, then plays TFT if punished; otherwise exploits."""

    name = "tester"

    def move(self, my_history, their_history):
        if not my_history:
            return "D"
        if len(my_history) == 1:
            return "C" if their_history[0] == "D" else "D"
        return their_history[-1]


class SoftMajority(Strategy):
    """Cooperates if opponent mostly cooperated; tie goes to cooperation."""

    name = "soft_majo"

    def move(self, my_history, their_history):
        if not their_history:
            return "C"
        return "C" if their_history.count("C") >= their_history.count("D") else "D"


class RandomStrategy(Strategy):
    name = "random"

    def __init__(self):
        self.rng = _Random(0)

    def move(self, my_history, their_history):
        return "C" if self.rng.random() < 0.5 else "D"


class Pavlov(Strategy):
    """Win-stay, lose-shift."""

    name = "pavlov"

    def move(self, my_history, their_history):
        if not my_history:
            return "C"
        last_payoff = (my_history[-1], their_history[-1])
        if last_payoff in (("C", "C"), ("D", "C")):
            return my_history[-1]
        return "D" if my_history[-1] == "C" else "C"


BUILTIN_STRATEGIES: list[type[Strategy]] = [
    TitForTat,
    AlwaysCooperate,
    AlwaysDefect,
    SuspiciousTitForTat,
    Grudger,
    Joss,
    Tester,
    SoftMajority,
    RandomStrategy,
    Pavlov,
]

NAME_TO_STRATEGY = {s.name: s for s in BUILTIN_STRATEGIES}
