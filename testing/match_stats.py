#!/usr/bin/env python3
"""Play matches and measure what happened inside them, not only who won.

For every game it replays the move history and records, per team:
points banked, deaths as pacman, dots lost by dying, scared ghosts eaten,
capsules eaten, moves spent on the enemy side, the largest load carried,
when the team first scored, how many times the lead changed, and the score
after a quarter, half and three quarters of the game.

Examples (from the repository root):
    python testing/match_stats.py -a my_team.py -b rusher -r 20
    python testing/match_stats.py -a my_team.py -b other.py -f crowdedCapture,jumboCapture -r 0 --json out.json

Each map is played twice, with A as red and then as blue.
"""
import argparse
import json
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor

from bench import resolve

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTEST_SRC = os.path.join(ROOT, "pacman-contest", "src")
CONTEST = os.path.join(CONTEST_SRC, "contest")


def _play(job):
    red, blue, layout, length = job
    sys.path[:0] = [CONTEST_SRC]
    os.chdir(CONTEST)
    import io
    import contextlib
    import contest.capture as capture

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        options = capture.read_command(["-r", red, "-b", blue, "-l", layout, "-Q", "-c",
                                        "--delay-step", "0", "-i", str(length)])
        games = capture.run_games(**options)
    game = games[0]
    lay = options["layouts"][0]
    import contest.text_display as text_display
    # A fresh game on the same layout gives the exact starting state; its
    # agents are never asked to move.
    with contextlib.redirect_stdout(io.StringIO()):
        state = capture.CaptureRules().new_game(lay, game.agents, text_display.NullGraphics(),
                                                length, False, False).state
    starts = [tuple(map(int, state.get_agent_position(i))) for i in range(4)]
    teams = {"red": [0, 2], "blue": [1, 3]}
    stats = {side: {"deaths": 0, "dots_lost": 0, "ghost_kills": 0, "capsules": 0,
                    "enemy_side_moves": 0, "max_carry": 0, "first_score_move": None}
             for side in teams}
    side_of = {0: "red", 2: "red", 1: "blue", 3: "blue"}
    lead_changes = 0
    leader = 0
    checkpoints = {length // 4: None, length // 2: None, 3 * length // 4: None}
    caps_before = {"red": len(state.get_blue_capsules()), "blue": len(state.get_red_capsules())}
    for move, (agent, action) in enumerate(game.move_history):
        before = [(state.get_agent_state(i).is_pacman, state.get_agent_state(i).num_carrying,
                   tuple(map(int, state.get_agent_position(i)))) for i in range(4)]
        state = state.generate_successor(agent, action)
        for i in range(4):
            was_pac, carry, pos = before[i]
            now = tuple(map(int, state.get_agent_position(i)))
            jumped = now == starts[i] and abs(now[0] - pos[0]) + abs(now[1] - pos[1]) > 1
            if jumped:
                if was_pac:
                    stats[side_of[i]]["deaths"] += 1
                    stats[side_of[i]]["dots_lost"] += carry
                else:
                    # A ghost sent home was eaten while scared.
                    stats["blue" if side_of[i] == "red" else "red"]["ghost_kills"] += 1
            st = state.get_agent_state(i)
            if i == agent and st.is_pacman:
                stats[side_of[i]]["enemy_side_moves"] += 1
            stats[side_of[i]]["max_carry"] = max(stats[side_of[i]]["max_carry"], st.num_carrying)
        caps_now = {"red": len(state.get_blue_capsules()), "blue": len(state.get_red_capsules())}
        for side in teams:
            stats[side]["capsules"] += caps_before[side] - caps_now[side]
        caps_before = caps_now
        score = state.data.score
        if move + 1 in checkpoints:
            checkpoints[move + 1] = score
        for side, sign in (("red", 1), ("blue", -1)):
            returned = sum(state.get_agent_state(i).num_returned for i in teams[side])
            if returned and stats[side]["first_score_move"] is None:
                stats[side]["first_score_move"] = move
        new_leader = (score > 0) - (score < 0)
        if new_leader and leader and new_leader != leader:
            lead_changes += 1
        if new_leader:
            leader = new_leader
    for side in teams:
        stats[side]["returned"] = sum(state.get_agent_state(i).num_returned for i in teams[side])
    final = game.state.data.score
    # A game that ended early keeps its final score at the later checkpoints.
    checkpoints = {k: (final if v is None else v) for k, v in checkpoints.items()}
    return {"layout": layout, "score": final, "moves": len(game.move_history), "score_at": checkpoints,
            "lead_changes": lead_changes, "red": stats["red"], "blue": stats["blue"],
            "crashed": bool(getattr(game, "agent_crashed", False)),
            "timeout": bool(getattr(game, "agent_timeout", False))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-a", required=True, help="team A file")
    ap.add_argument("-b", required=True, help="team B: a file, or a bench.py name / git:<ref>")
    ap.add_argument("-f", "--fixed", default="", help="comma list of fixed layouts")
    ap.add_argument("-r", "--random", type=int, default=10)
    ap.add_argument("-s", "--seed", type=int, default=5000)
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("-i", "--length", type=int, default=1200)
    ap.add_argument("--json")
    args = ap.parse_args()
    a = os.path.abspath(args.a)
    b = os.path.abspath(args.b) if os.path.exists(args.b) else resolve(args.b, tempfile.mkdtemp(prefix="stats_"))
    layouts = [l for l in args.fixed.split(",") if l] + [f"RANDOM{args.seed + k}" for k in range(args.random)]
    jobs, sides = [], []
    for lay in layouts:
        jobs.append((a, b, lay, args.length)); sides.append("red")
        jobs.append((b, a, lay, args.length)); sides.append("blue")
    with ProcessPoolExecutor(args.jobs) as ex:
        results = list(ex.map(_play, jobs))
    rows = []
    for res, a_side in zip(results, sides):
        b_side = "blue" if a_side == "red" else "red"
        sign = 1 if a_side == "red" else -1
        rows.append({"layout": res["layout"], "a_side": a_side, "margin": sign * res["score"],
                     "moves": res["moves"], "lead_changes": res["lead_changes"],
                     "score_at": {k: sign * v for k, v in res["score_at"].items()},
                     "a": res[a_side], "b": res[b_side], "crashed": res["crashed"], "timeout": res["timeout"]})
    keys = ["returned", "deaths", "dots_lost", "ghost_kills", "capsules", "enemy_side_moves", "max_carry"]
    n = len(rows)
    print(f"{n} games. Averages per game (A = {os.path.basename(a)}, B = {os.path.basename(b)}):")
    print(f"{'metric':18s} {'A':>8s} {'B':>8s}")
    for k in keys:
        print(f"{k:18s} {sum(r['a'][k] for r in rows)/n:8.2f} {sum(r['b'][k] for r in rows)/n:8.2f}")
    firsts = [r for r in rows if r["a"]["first_score_move"] is not None or r["b"]["first_score_move"] is not None]
    a_first = sum(1 for r in firsts if r["b"]["first_score_move"] is None or
                  (r["a"]["first_score_move"] is not None and r["a"]["first_score_move"] < r["b"]["first_score_move"]))
    print(f"A scored first in {a_first}/{len(firsts)} games that had any score")
    w = sum(r["margin"] > 0 for r in rows); t = sum(r["margin"] == 0 for r in rows)
    print(f"A: W {w} T {t} L {n - w - t}, avg margin {sum(r['margin'] for r in rows)/n:+.2f}, "
          f"early finishes {sum(r['moves'] < args.length for r in rows)}, lead changes/game {sum(r['lead_changes'] for r in rows)/n:.2f}")
    for k in sorted(rows[0]["score_at"]):
        ahead = sum(r["score_at"][k] > 0 for r in rows); behind = sum(r["score_at"][k] < 0 for r in rows)
        print(f"after {k:4d} moves: A ahead in {ahead}, behind in {behind}, "
              f"avg margin {sum(r['score_at'][k] for r in rows)/n:+.2f}")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(rows, fh, indent=1)


if __name__ == "__main__":
    main()
