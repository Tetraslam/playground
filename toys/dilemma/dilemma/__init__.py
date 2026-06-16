"""dilemma package."""

from .engine import play_match, play_round
from .strategies import BUILTIN_STRATEGIES, NAME_TO_STRATEGY, Strategy
from .tournament import run_tournament, standings

__all__ = [
    "BUILTIN_STRATEGIES",
    "NAME_TO_STRATEGY",
    "Strategy",
    "play_match",
    "play_round",
    "run_tournament",
    "standings",
]
