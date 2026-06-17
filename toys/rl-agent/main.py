"""rl-agent — watch a Q-learning agent learn a grid world in real time."""

import argparse
import random
import sys
import time
from dataclasses import dataclass, field

UP, RIGHT, DOWN, LEFT = 0, 1, 2, 3
ACTIONS = [UP, RIGHT, DOWN, LEFT]
ACTION_NAMES = ["UP", "RIGHT", "DOWN", "LEFT"]
ACTION_DELTA = {UP: (-1, 0), RIGHT: (0, 1), DOWN: (1, 0), LEFT: (0, -1)}
ARROW_CHARS = {UP: "\u2191", RIGHT: "\u2192", DOWN: "\u2193", LEFT: "\u2190"}


@dataclass
class GridWorld:
    cols: int = 12
    rows: int = 8
    start: tuple[int, int] = (0, 0)
    goal: tuple[int, int] | None = None
    walls: set[tuple[int, int]] = field(default_factory=set)
    pits: set[tuple[int, int]] = field(default_factory=set)
    step_penalty: float = -0.05
    goal_reward: float = 10.0
    pit_reward: float = -10.0

    def __post_init__(self):
        if self.goal is None:
            self.goal = (self.rows - 1, self.cols - 1)

    def reset(self) -> tuple[int, int]:
        return self.start

    def step(self, s: tuple[int, int], action: int) -> tuple[tuple[int, int], float, bool]:
        dr, dc = ACTION_DELTA[action]
        nr, nc = s[0] + dr, s[1] + dc
        if 0 <= nr < self.rows and 0 <= nc < self.cols and (nr, nc) not in self.walls:
            s_next = (nr, nc)
        else:
            s_next = s
        if s_next == self.goal:
            return s_next, self.goal_reward, True
        if s_next in self.pits:
            return s_next, self.pit_reward, True
        return s_next, self.step_penalty, False

    def state_index(self, s: tuple[int, int]) -> int:
        return s[0] * self.cols + s[1]

    def state_count(self) -> int:
        return self.rows * self.cols


@dataclass
class QLearner:
    env: GridWorld
    alpha: float = 0.3
    gamma: float = 0.95
    epsilon: float = 1.0
    epsilon_decay: float = 0.997
    epsilon_min: float = 0.05
    q: list[list[float]] = field(init=False)

    def __post_init__(self):
        self.q = [[0.0] * 4 for _ in range(self.env.state_count())]

    def choose_action(self, s: tuple[int, int]) -> int:
        if random.random() < self.epsilon:
            return random.choice(ACTIONS)
        idx = self.env.state_index(s)
        return max(ACTIONS, key=lambda a: self.q[idx][a])

    def update(self, s: tuple[int, int], a: int, r: float, s_next: tuple[int, int]):
        idx, nidx = self.env.state_index(s), self.env.state_index(s_next)
        best_next = max(self.q[nidx])
        self.q[idx][a] += self.alpha * (r + self.gamma * best_next - self.q[idx][a])

    def decay_epsilon(self):
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    def best_action(self, s: tuple[int, int]) -> int:
        idx = self.env.state_index(s)
        return max(ACTIONS, key=lambda a: self.q[idx][a])

    def max_q(self, s: tuple[int, int]) -> float:
        idx = self.env.state_index(s)
        return max(self.q[idx])


def hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    h = h % 1.0
    i = int(h * 6)
    f = h * 6 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    i = i % 6
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return int(r * 255), int(g * 255), int(b * 255)


def render(
    env: GridWorld,
    agent: QLearner,
    episode: int,
    total_episodes: int,
    episode_steps: int,
    episode_reward: float,
    window_rewards: list[float],
    frames_per_second: float,
    s: tuple[int, int] | None = None,
    paused: bool = False,
):
    buf: list[str] = []
    buf.append("\033[2J\033[H")
    buf.append("\033[1m Q-LEARNING AGENT \033[0m")
    buf.append(
        f"  episode {episode}/{total_episodes}  "
        f"\u03b5={agent.epsilon:.3f}  "
        f"steps={episode_steps}  "
        f"reward={episode_reward:+.2f}"
    )
    if paused:
        buf.append("  \033[1;33m[PAUSED]\033[0m")
    buf.append("")

    vmax = max(0.0, max(agent.max_q((r, c)) for r in range(env.rows) for c in range(env.cols)))
    vmin = min(0.0, min(agent.max_q((r, c)) for r in range(env.rows) for c in range(env.cols)))
    vrange = vmax - vmin if vmax != vmin else 1.0

    def value_color(cell_v: float) -> tuple[int, int, int]:
        t = (cell_v - vmin) / vrange
        return hsv_to_rgb(0.58 * (1 - t), 0.9, 0.15 + 0.18 * t)

    def best_arrow(r: int, c: int) -> str:
        idx = env.state_index((r, c))
        vals = agent.q[idx]
        best_val = max(vals)
        if best_val == 0 or all(v == 0 for v in vals):
            return " "
        best_actions = [a for a in ACTIONS if vals[a] == best_val]
        if len(best_actions) == 4:
            return "\u25c9"
        if len(best_actions) == 3:
            chosen = best_actions[0]
            if UP in best_actions and DOWN in best_actions:
                chosen = UP if LEFT not in best_actions else LEFT
            return ARROW_CHARS[chosen]
        if len(best_actions) == 2:
            if {UP, DOWN} == set(best_actions):
                return "\u2195"
            if {LEFT, RIGHT} == set(best_actions):
                return "\u2194"
            chosen = best_actions[0]
            return ARROW_CHARS[chosen]
        return ARROW_CHARS[best_actions[0]]

    top_line = "\u250c" + "\u252c".join("\u2500\u2500\u2500" for _ in range(env.cols)) + "\u2510"
    buf.append("  " + top_line)
    for r in range(env.rows):
        row_str = "  \u2502"
        for c in range(env.cols):
            cell = (r, c)
            rcol, gcol, bcol = value_color(agent.max_q(cell))
            arrow = best_arrow(r, c)
            bg = f"\033[48;2;{rcol};{gcol};{bcol}m"
            if cell == env.start and cell == (s or (-1, -1)):
                prefix = "\033[1;37m"
                suffix = "\033[0m"
            else:
                prefix, suffix = "", ""
            cell_display = f" {prefix}{arrow}{suffix} "
            if cell == env.goal:
                row_str += f"\033[1;32m{cell_display}\033[0m"
            elif cell in env.pits:
                row_str += f"\033[1;31m{cell_display}\033[0m"
            elif cell in env.walls:
                row_str += f"\033[47m{cell_display}\033[0m"
            elif cell == s:
                row_str += f"{bg}\033[1;97m{cell_display}\033[0m\033[0m"
            else:
                row_str += f"{bg}\033[30m{cell_display}\033[0m\033[0m"
            row_str += "\u2502"
        buf.append(row_str)
        if r < env.rows - 1:
            buf.append(
                "  "
                + "\u251c"
                + "\u253c".join("\u2500\u2500\u2500" for _ in range(env.cols))
                + "\u2524"
            )
    buf.append(
        "  " + "\u2514" + "\u2534".join("\u2500\u2500\u2500" for _ in range(env.cols)) + "\u2518"
    )

    buf.append("")
    buf.append(
        "  \033[0;32m\u25a0 goal\033[0m  \033[0;31m\u25a0 pit\033[0m  \033[47m  \033[0m wall  \033[1;97m\u263a agent\033[0m  arrow = best action"
    )
    buf.append(f"  fps={frames_per_second:.0f}  |  [space] pause/resume  [q] quit  [+/-] speed")

    avg_r = sum(window_rewards[-100:]) / max(1, len(window_rewards[-100:])) if window_rewards else 0
    buf.append(f"  avg reward (last 100 eps): {avg_r:+.2f}")
    if window_rewards:
        chart_w = 40
        max_abs = max(
            abs(max(window_rewards[-100:], default=0)),
            abs(min(window_rewards[-100:], default=0)),
            1,
        )
        buf.append("  reward trend:")
        recent = window_rewards[-chart_w:]
        line = "  "
        for val in recent:
            if val >= 0:
                bar_h = int(val / (max_abs + 0.01) * 8)
                line += f"\033[38;2;0;200;100m{' \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588'[bar_h]}\033[0m"
            else:
                bar_h = int(abs(val) / (max_abs + 0.01) * 8)
                line += f"\033[38;2;220;60;60m{' \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588'[bar_h]}\033[0m"
        buf.append(line)

    sys.stdout.write("\n".join(buf))
    sys.stdout.flush()


def make_classic_env(env_type: str) -> GridWorld:
    if env_type == "open":
        return GridWorld(rows=6, cols=10, walls=set())
    if env_type == "maze":
        walls = {(r, 2) for r in range(5)} | {(2, c) for c in range(4, 9)}
        walls -= {(2, 2), (4, 2)}
        return GridWorld(rows=6, cols=10, walls=walls)
    if env_type == "cliff":
        walls = {(5, c) for c in range(1, 9)}
        pits = {(5, c) for c in range(9)}
        return GridWorld(
            rows=6,
            cols=10,
            start=(5, 0),
            goal=(5, 9),
            walls=walls,
            pits=pits,
            goal_reward=5.0,
            step_penalty=-0.1,
        )
    raise ValueError(f"unknown env type: {env_type}")


def getch_unix() -> str:
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.buffer.read(1)
        if ch == b"\x1b":
            extra = sys.stdin.buffer.read(2)
            return "\x1b" + extra.decode("utf-8", errors="replace")
        return ch.decode("utf-8", errors="replace")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main():
    parser = argparse.ArgumentParser(description="watch a Q-learning agent learn a grid world")
    parser.add_argument(
        "--env", default="maze", choices=["open", "maze", "cliff"], help="environment type"
    )
    parser.add_argument("--episodes", type=int, default=500, help="training episodes")
    parser.add_argument("--alpha", type=float, default=0.3, help="learning rate")
    parser.add_argument("--gamma", type=float, default=0.95, help="discount factor")
    parser.add_argument("--epsilon", type=float, default=1.0, help="starting exploration rate")
    parser.add_argument(
        "--epsilon-decay", type=float, default=0.997, help="epsilon decay per episode"
    )
    parser.add_argument(
        "--fps", type=int, default=30, help="target frames per second for rendering"
    )
    args = parser.parse_args()

    env = make_classic_env(args.env)
    agent = QLearner(
        env=env,
        alpha=args.alpha,
        gamma=args.gamma,
        epsilon=args.epsilon,
        epsilon_decay=args.epsilon_decay,
    )

    window_rewards: list[float] = []
    fps = args.fps
    period = 1.0 / max(1, fps)
    paused = False
    frames = 0
    last_render = 0.0

    render(env, agent, 0, args.episodes, 0, 0.0, window_rewards, float(fps), paused=paused)

    for ep in range(1, args.episodes + 1):
        s = env.reset()
        episode_reward = 0.0
        episode_steps = 0
        done = False

        while not done:
            now = time.monotonic()
            if now - last_render >= period or not frames:
                render(
                    env,
                    agent,
                    ep,
                    args.episodes,
                    episode_steps,
                    episode_reward,
                    window_rewards,
                    1.0 / max(period, 0.001) if period > 0 else 999,
                    s,
                    paused,
                )
                last_render = now
                frames += 1

            ch = None
            try:
                ch = getch_unix()
            except Exception:
                pass
            if ch is not None:
                if ch in (" ",):
                    paused = not paused
                elif ch in ("q", "\x03"):
                    print("\033[2J\033[Hquitting.")
                    return
                elif ch == "+":
                    fps = min(120, fps * 2)
                    period = 1.0 / fps
                elif ch == "-":
                    fps = max(2, fps // 2)
                    period = 1.0 / fps

            while paused:
                render(
                    env,
                    agent,
                    ep,
                    args.episodes,
                    episode_steps,
                    episode_reward,
                    window_rewards,
                    0.0,
                    s,
                    paused,
                )
                try:
                    ch = getch_unix()
                except Exception:
                    continue
                if ch in (" ",):
                    paused = not paused
                elif ch in ("q", "\x03"):
                    print("\033[2J\033[Hquitting.")
                    return
                elif ch == "+":
                    fps = min(120, fps * 2)
                    period = 1.0 / fps
                elif ch == "-":
                    fps = max(2, fps // 2)
                    period = 1.0 / fps

            a = agent.choose_action(s)
            s_next, r, done = env.step(s, a)
            agent.update(s, a, r, s_next)
            s = s_next
            episode_reward += r
            episode_steps += 1

        agent.decay_epsilon()
        window_rewards.append(episode_reward)

        if not paused:
            render(
                env,
                agent,
                ep,
                args.episodes,
                episode_steps,
                episode_reward,
                window_rewards,
                1.0 / max(period, 0.001),
                s,
                paused,
            )

    render(env, agent, args.episodes, args.episodes, 0, 0.0, window_rewards, 0, paused=True)
    print()
    print("training complete. press q to quit.")
    while True:
        try:
            ch = getch_unix()
            if ch in ("q", "\x03"):
                break
        except Exception:
            pass
    print("\033[2J\033[H")


if __name__ == "__main__":
    main()
