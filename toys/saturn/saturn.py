"""CDCL SAT solver, built from scratch.

Watched literals, unit propagation, 1-UIP conflict analysis with clause
learning, VSIDS branching with exponential decay, and Luby-restart schedule.

No external deps. The algorithm is the toy.
"""

from __future__ import annotations

from dataclasses import dataclass

# A literal is a signed int: +v means "v is true", -v means "v is false".
# Variable v in 1..n. Literal 0 is never used (sentinel for "unassigned").


@dataclass
class Clause:
    """A disjunction of literals. The first two slots are the watched literals."""

    lits: list[int]
    learned: bool = False

    def __len__(self) -> int:
        return len(self.lits)


@dataclass
class Stats:
    decisions: int = 0
    propagations: int = 0
    conflicts: int = 0
    learned_clauses: int = 0
    restarts: int = 0
    max_depth: int = 0

    def __repr__(self) -> str:
        return (
            f"decisions={self.decisions} propagations={self.propagations} "
            f"conflicts={self.conflicts} learned={self.learned_clauses} "
            f"restarts={self.restarts} max_depth={self.max_depth}"
        )


class Solver:
    """A conflict-driven clause-learning SAT solver."""

    def __init__(self, num_vars: int, clauses: list[list[int]], *, verbose: bool = False):
        self.n = num_vars
        self.verbose = verbose

        self.stats = Stats()
        self.unsat = False

        # Assignment state.
        # value: 1 -> true, -1 -> false, 0 -> unassigned (indexed by var).
        self.value: list[int] = [0] * (self.n + 1)
        # level[v]: decision level at which v was assigned.
        self.level: list[int] = [0] * (self.n + 1)
        # reason[v]: index of the clause that propagated v, or -1 for a decision.
        self.reason: list[int] = [-1] * (self.n + 1)
        # The trail: literals in assignment order, with level markers.
        self.trail: list[int] = []
        self.trail_lim: list[int] = []  # index into trail where each level starts
        # Persistent propagation head: literals on the trail up to here have
        # already had their consequences propagated. Never reset to len(trail),
        # or newly-enqueued decisions/units never get propagated.
        self.qhead: int = 0

        # Clauses & watches.
        self.clauses: list[Clause] = []
        # watches[l] -> list of clause indices watching literal l.
        # Indexed by literal offset: lit_to_idx(l) = 2*v + (1 if l<0 else 0).
        self.watches: dict[int, list[int]] = {}
        for cls in clauses:
            self._add_clause(cls, learned=False)

        # VSIDS activity scores.
        self.activity: list[float] = [0.0] * (self.n + 1)
        self.var_inc = 1.0
        self.var_decay = 0.95

        # Conflict counter for restart schedule (Luby).
        self.conflict_count = 0
        self.restart_base = 100  # conflicts before first restart unit

    # --- literal helpers -------------------------------------------------

    @staticmethod
    def _lidx(lit: int) -> int:
        v = lit if lit > 0 else -lit
        return 2 * v + (1 if lit < 0 else 0)

    def _lit_val(self, lit: int) -> int:
        v = lit if lit > 0 else -lit
        sign = 1 if lit > 0 else -1
        return self.value[v] * sign

    def _watches(self, lit: int) -> list[int]:
        idx = self._lidx(lit)
        return self.watches.setdefault(idx, [])

    # --- clause construction --------------------------------------------

    def _add_clause(self, lits: list[int], *, learned: bool) -> int:
        # Deduplicate while PRESERVING ORDER (critical for learned clauses:
        # lits[0] is the asserting UIP, lits[1] is the highest-level watch).
        seen: set[int] = set()
        dedup: list[int] = []
        for lit in lits:
            if -lit in seen:
                return -1  # tautology; drop silently
            if lit not in seen:
                seen.add(lit)
                dedup.append(lit)
        ci = len(self.clauses)
        clause = Clause(lits=dedup, learned=learned)
        self.clauses.append(clause)
        if len(dedup) >= 2:
            a, b = dedup[0], dedup[1]
            self._watches(a).append(ci)
            self._watches(b).append(ci)
        elif len(dedup) == 1:
            # Unit clause at level 0: enqueue immediately.
            if not self._enqueue(dedup[0], reason=-1 if not learned else ci):
                # Conflicts with an existing assignment -> unsat (or, for a
                # learned clause asserted after backjump, a genuine bug; either
                # way the instance is unsatisfiable at this level).
                self.unsat = True
        # Empty clause => immediately unsat.
        return ci

    # --- propagation -----------------------------------------------------

    def _enqueue(self, lit: int, reason: int) -> bool:
        v = lit if lit > 0 else -lit
        cur = self.value[v]
        sign = 1 if lit > 0 else -1
        if cur != 0:
            return cur == sign  # consistent?
        self.value[v] = sign
        self.level[v] = self._cur_level()
        self.reason[v] = reason
        self.trail.append(lit)
        self.stats.propagations += 1
        return True

    def _cur_level(self) -> int:
        return len(self.trail_lim)

    def propagate(self) -> int:
        """Unit propagation. Returns the index of a conflicting clause, or -1."""
        while self.qhead < len(self.trail):
            lit = self.trail[self.qhead]
            self.qhead += 1
            # The negation of lit just became false: clauses watching -lit
            # need their watches fixed.
            neg = -lit
            wl = self._watches(neg)
            i = 0
            new_wl: list[int] = []
            conflict = -1
            while i < len(wl):
                ci = wl[i]
                clause = self.clauses[ci]
                # Ensure neg is in slot 1 (the "blocked" watch).
                if clause.lits[0] == neg:
                    clause.lits[0], clause.lits[1] = clause.lits[1], clause.lits[0]
                # clause.lits[1] == neg now.
                first = clause.lits[0]
                # If first is already true, this clause is satisfied; keep watch.
                if self._lit_val(first) == 1:
                    new_wl.append(ci)
                    i += 1
                    continue
                # Look for a new literal to watch (beyond slot 1).
                found = False
                for k in range(2, len(clause.lits)):
                    cand = clause.lits[k]
                    if self._lit_val(cand) != -1:  # not false
                        # Move cand into slot 1; watch cand instead of neg.
                        clause.lits[1] = cand
                        clause.lits[k] = neg
                        self._watches(cand).append(ci)
                        found = True
                        i += 1
                        break
                if found:
                    continue
                # No new watch: clause is unit or conflicting under `neg`.
                new_wl.append(ci)  # keep watching neg
                i += 1
                if self._lit_val(first) == -1:
                    # Both watched literals false -> conflict.
                    # Finish copying remaining watches first.
                    new_wl.extend(wl[i:])
                    conflict = ci
                    break
                # Unit: enqueue first.
                if not self._enqueue(first, reason=ci):
                    new_wl.extend(wl[i:])
                    conflict = ci
                    break
            self.watches[self._lidx(neg)] = new_wl
            if conflict != -1:
                return conflict
        return -1

    # --- conflict analysis (1-UIP) --------------------------------------

    def _analyze(self, conflict: int) -> tuple[list[int], int]:
        """Return (learned clause as lits, backjump level). 1-UIP cut."""
        learnt: list[int] = []
        seen: list[bool] = [False] * (self.n + 1)
        counter = 0  # literals at current level not yet resolved
        p = 0  # the asserting literal (negation of the UIP)
        cur_level = self._cur_level()
        ci = conflict
        trail_idx = len(self.trail) - 1

        while True:
            clause = self.clauses[ci]
            # Bump VSIDS for every literal in the conflict clause.
            for lit in clause.lits:
                v = lit if lit > 0 else -lit
                if not seen[v] and self.level[v] > 0:
                    self._bump(v)
                    seen[v] = True
                    if self.level[v] >= cur_level:
                        counter += 1
                    else:
                        learnt.append(lit)
            # Find the next literal on the trail that we've seen.
            while trail_idx >= 0:
                v = self.trail[trail_idx] if self.trail[trail_idx] > 0 else -self.trail[trail_idx]
                trail_idx -= 1
                if seen[v]:
                    break
            else:
                # Shouldn't happen on a real conflict.
                break
            v = self.trail[trail_idx + 1]
            vv = v if v > 0 else -v
            counter -= 1
            if counter == 0:
                p = -v  # this is the 1-UIP
                break
            # Otherwise resolve: reason of vv becomes the next clause.
            ci = self.reason[vv]
            assert ci != -1, "decision literal reached during analysis"
        # The UIP's negation is the asserting literal: it MUST sit at
        # learnt[0] (the watch + enqueue target). The loop above collected the
        # lower-level literals into `learnt`, so prepend p.
        learnt.insert(0, p)
        if len(learnt) == 1:
            back_level = 0
        else:
            # Find the literal with the highest level among learnt[1:].
            max_i = 1
            max_lvl = self.level[learnt[1] if learnt[1] > 0 else -learnt[1]]
            for k in range(2, len(learnt)):
                lv = self.level[learnt[k] if learnt[k] > 0 else -learnt[k]]
                if lv > max_lvl:
                    max_lvl = lv
                    max_i = k
            # Swap so learnt[1] is the highest-level literal (keeps watch sane).
            learnt[1], learnt[max_i] = learnt[max_i], learnt[1]
            back_level = max_lvl
        return learnt, back_level

    def _bump(self, v: int) -> None:
        self.activity[v] += self.var_inc
        if self.activity[v] > 1e100:
            # Rescale everything down.
            for i in range(1, self.n + 1):
                self.activity[i] *= 1e-100
            self.var_inc *= 1e-100

    def _decay(self) -> None:
        self.var_inc /= self.var_decay

    # --- backtracking ----------------------------------------------------

    def _backtrack(self, target_level: int) -> None:
        if target_level >= self._cur_level():
            return
        # Pop the trail down to the start of target_level+1.
        limit = (
            self.trail_lim[target_level] if target_level < len(self.trail_lim) else len(self.trail)
        )
        for i in range(len(self.trail) - 1, limit - 1, -1):
            lit = self.trail[i]
            v = lit if lit > 0 else -lit
            self.value[v] = 0
            self.reason[v] = -1
            self.level[v] = 0
        del self.trail[limit:]
        del self.trail_lim[target_level:]
        # Don't repropagate literals that survived the backtrack; they're
        # already on the trail and were propagated earlier. The next enqueue
        # (the asserting unit) will advance past qhead naturally.
        if self.qhead > len(self.trail):
            self.qhead = len(self.trail)

    # --- branching -------------------------------------------------------

    def _pick(self) -> int:
        # VSIDS: highest-activity unassigned variable. Linear scan is fine
        # for the instance sizes this toy is meant for.
        best = 0
        best_act = -1.0
        for v in range(1, self.n + 1):
            if self.value[v] == 0 and self.activity[v] > best_act:
                best_act = self.activity[v]
                best = v
        # Phase: default to true (a common heuristic; could track per-var phase).
        return best

    # --- restarts (Luby) -------------------------------------------------

    @staticmethod
    def _luby(i: int) -> int:
        # Luby(1) sequence: 1,1,2,1,1,2,4,...
        k = 1
        while (1 << k) - 1 < i + 1:
            k += 1
        if (1 << k) - 1 == i + 1:
            return 1 << (k - 1)
        return Solver._luby(i - (1 << (k - 1)) + 1)

    # --- main loop -------------------------------------------------------

    def solve(self) -> bool:
        if self.unsat:
            return False
        # Initial propagation of top-level units.
        if self.propagate() != -1:
            self.unsat = True
            return False
        luby_i = 0
        next_restart = self.restart_base * self._luby(luby_i)
        while True:
            conflict = self.propagate()
            if conflict != -1:
                self.stats.conflicts += 1
                self.conflict_count += 1
                if self._cur_level() == 0:
                    self.unsat = True
                    return False
                learnt, back_level = self._analyze(conflict)
                ci = self._add_clause(learnt, learned=True)
                self.stats.learned_clauses += 1
                if self.verbose:
                    print(
                        f"  conflict @ lvl {self._cur_level()} "
                        f"-> learnt {len(learnt)} lits, backjump to {back_level}"
                    )
                self._backtrack(back_level)
                if ci != -1:
                    # The new clause is unit at back_level; assert it.
                    self._enqueue(learnt[0], reason=ci)
                self._decay()
                # Restart?
                if self.conflict_count >= next_restart:
                    self._backtrack(0)
                    self.stats.restarts += 1
                    self.conflict_count = 0
                    luby_i += 1
                    next_restart = self.restart_base * self._luby(luby_i)
            else:
                # No conflict: pick a decision variable.
                lit = self._pick()
                if lit == 0:
                    return True  # all assigned, SAT
                self.stats.decisions += 1
                self.trail_lim.append(len(self.trail))
                self.stats.max_depth = max(self.stats.max_depth, self._cur_level())
                if self.verbose:
                    print(f"  decide lvl {self._cur_level()}: +{lit}")
                self._enqueue(lit, reason=-1)

    # --- model extraction ------------------------------------------------

    def model(self) -> dict[int, bool]:
        m = {}
        for v in range(1, self.n + 1):
            m[v] = self.value[v] == 1
        return m
