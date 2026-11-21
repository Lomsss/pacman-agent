#!/usr/bin/env python3
"""Stress-test our team against many opponent styles, maps and both colours.

Examples (run from the repository root):
    python testing/bench.py                        # every opponent, 10 fixed + 20 random maps
    python testing/bench.py -o rusher,mcts -r 40   # two opponents (branches agent/rusher, agent/mcts), 40 random maps
    python testing/bench.py -o git:551e486         # against an older version of our agent
    python testing/bench.py -a /tmp/candidate.py --json out.json

Each map is played twice, once with us as red and once as blue.
Points use the usual tournament scheme: win 3, tie 1, loss 0.
"""
import argparse
import contextlib
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTEST_SRC = os.path.join(ROOT, "pacman-contest", "src")
CONTEST = os.path.join(CONTEST_SRC, "contest")
# Every opponent lives on its own branch, agent/<name>, as a self-contained
# my_team.py. A name below is played from that branch (local or origin).
OPPONENTS = {
    "double-baseline": "the staff baseline with both agents attacking",
    "rusher": "two greedy attackers",
    "turtle": "two sonar-tracking defenders",
    "capsule": "capsule first, feast while ghosts are scared",
    "switcher": "roles flip with the score",
    "approxq": "linear Q-function features",
    "minimax": "alpha-beta attacker",
    "mcts": "Monte Carlo tree search attacker",
    "astar": "A* path planner around visible ghosts",
    "camper": "greedy attacker plus a border-mirroring camper",
    "mdp": "value iteration over a reward grid, both roles",
    "bfs": "plain BFS, squares next to ghosts treated as walls",
    "abfull": "full-state alpha-beta with iterative deepening",
    "mirror-attack": "our own code, both on offense",
    "mm": "proxy of the contest team M&M",
    "alma": "proxy of the contest team Alma Team",
    "ghostclaniol": "proxy of the contest team GhostClaniol",
}
DEFAULT = ["baseline"] + list(OPPONENTS)
FIXED = ["defaultCapture", "alleyCapture", "bloxCapture", "crowdedCapture", "distantCapture",
         "fastCapture", "jumboCapture", "mediumCapture", "officeCapture", "strategicCapture"]


def show(refs, tmp, label):
    """Write my_team.py from the first ref that has it and return the path."""
    for ref in refs:
        out = subprocess.run(["git", "-C", ROOT, "show", f"{ref}:my_team.py"], capture_output=True, text=True)
        if out.returncode == 0:
            path = os.path.join(tmp, f"past_{re.sub(r'[^A-Za-z0-9]', '_', label)}_team.py")
            with open(path, "w") as fh:
                fh.write(out.stdout)
            return path
    sys.exit(f"no my_team.py at {' or '.join(refs)}; try: git fetch origin")


def resolve(name, tmp):
    if name.startswith("git:"):
        return show([name[4:]], tmp, name[4:])
    if name == "baseline":
        return "baseline_team"
    branch = "agent/" + name.replace("_", "-")
    if name.replace("_", "-") in OPPONENTS:
        return show([branch, "origin/" + branch], tmp, branch)
    if not os.path.isfile(name):
        sys.exit(f"unknown opponent {name!r}: use a name from OPPONENTS, git:<ref> or a file path")
    return os.path.abspath(name)


def layout_file(layout, tmp):
    """Write RANDOM<n> maps to a file so the engine never regenerates them.

    capture.py builds RANDOM<n> layouts with maze_generator, which calls
    random.seed(n) after --setRandomSeed was applied. That overwrites the game
    seed, so every game on that map, both colours included, would share one
    random stream. Loading the same map from a file keeps the game seed.
    """
    if not layout.startswith("RANDOM"):
        return layout
    path = os.path.join(tmp, f"{layout}Capture.lay")
    if not os.path.exists(path):
        sys.path.insert(0, CONTEST_SRC)
        import contest.maze_generator as maze_generator
        state = random.getstate()
        with open(path, "w") as fh, contextlib.redirect_stdout(io.StringIO()):
            fh.write(maze_generator.generate_maze(int(layout[6:])))
        random.setstate(state)
    return path


def play(agent, opp, layout, side, length, seed=None):
    red, blue = (agent, opp) if side == "red" else (opp, agent)
    env = dict(os.environ, PYTHONPATH=CONTEST_SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    cmd = [sys.executable, "capture.py", "-r", red, "-b", blue, "-l", layout_file(layout, TMP), "-Q", "-c",
           "--delay-step", "0", "-i", str(length)]
    if seed is not None:
        cmd += ["--setRandomSeed", seed]
    try:
        out = subprocess.run(cmd, cwd=CONTEST, env=env, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return {"result": None, "note": "harness timeout"}
    text = out.stdout + out.stderr
    ours = (0, 2) if side == "red" else (1, 3)
    issues = []
    for idx in ours:
        if re.search(rf"Agent {idx} (timed out|took too long|exceeded|ran out of time)", text):
            issues.append(f"agent {idx} time")
    if re.search(rf"{side.capitalize()} agent crashed", text) or "Traceback" in text:
        issues.append("crash/traceback")
    early = re.search(r"The (Red|Blue) team has returned at least", text)
    won = re.search(r"The (Red|Blue) team wins by (\d+) points", text)
    if early:
        margin = None
        result = 1 if early.group(1).lower() == side else -1
        early_flag = True
    elif won:
        margin = int(won.group(2)) * (1 if won.group(1).lower() == side else -1)
        result = (margin > 0) - (margin < 0)
        early_flag = False
    elif "Tie game" in text:
        margin, result, early_flag = 0, 0, False
    else:
        return {"result": None, "note": text[-300:]}
    return {"result": result, "margin": margin, "early": early_flag, "issues": issues}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-a", "--agent", default=os.path.join(ROOT, "my_team.py"))
    ap.add_argument("-o", "--opponents", default=",".join(DEFAULT), help="comma list; names (agent/<name> branches), git:<ref> or paths")
    ap.add_argument("-f", "--fixed", default=",".join(FIXED), help="fixed layouts (empty for none)")
    ap.add_argument("-r", "--random", type=int, default=20, help="number of random maps")
    ap.add_argument("-s", "--seed", type=int, default=1000, help="first random map seed")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("-i", "--length", type=int, default=1200)
    ap.add_argument("--json")
    ap.add_argument("--game-seed", help="seed every game (who starts, sonar noise) so two agents can be compared on the same games")
    args = ap.parse_args()

    layouts = [l for l in args.fixed.split(",") if l] + [f"RANDOM{args.seed + k}" for k in range(args.random)]
    agent = os.path.abspath(args.agent)
    tmp = tempfile.mkdtemp(prefix="bench_")
    global TMP
    TMP = tmp
    for l in layouts:
        layout_file(l, tmp)  # build every map once, before the worker threads start
    opps = [o for o in args.opponents.split(",") if o]
    paths = {o: resolve(o, tmp) for o in opps}
    jobs = [(o, l, side, k) for o in opps for k, l in enumerate(layouts) for side in ("red", "blue")]
    print(f"{len(jobs)} games: {len(opps)} opponents x {len(layouts)} maps x 2 colours, {args.jobs} at a time", flush=True)

    def run(job):
        o, l, side, k = job
        seed = None if args.game_seed is None else f"{args.game_seed}:{o}:{l}:{k}:{side}"
        return dict(play(agent, paths[o], l, side, args.length, seed), opponent=o, layout=l, side=side, seed=seed,
                    map_file=l.startswith("RANDOM"))

    with ThreadPoolExecutor(args.jobs) as ex:
        results = list(ex.map(run, jobs))

    print(f"\n{'opponent':16s} {'W':>4s} {'T':>4s} {'L':>4s}  {'win%':>5s} {'tie%':>5s}  {'pts/g':>5s}  {'margin':>6s}  {'early W/L':>9s}  issues")
    total = {"w": 0, "t": 0, "l": 0, "n": 0}
    for o in opps:
        rs = [r for r in results if r["opponent"] == o]
        ok = [r for r in rs if r["result"] is not None]
        w = sum(r["result"] > 0 for r in ok); t = sum(r["result"] == 0 for r in ok); l = sum(r["result"] < 0 for r in ok)
        margins = [r["margin"] for r in ok if r["margin"] is not None]
        ew = sum(r["early"] and r["result"] > 0 for r in ok); el = sum(r["early"] and r["result"] < 0 for r in ok)
        issues = sum(bool(r.get("issues")) for r in rs) + (len(rs) - len(ok))
        n = max(1, len(rs))
        print(f"{o:16s} {w:4d} {t:4d} {l:4d}  {100*w/n:5.1f} {100*t/n:5.1f}  {(3*w+t)/n:5.2f}  "
              f"{(sum(margins)/max(1,len(margins))):+6.1f}  {ew:4d}/{el:<4d}  {issues}")
        total["w"] += w; total["t"] += t; total["l"] += l; total["n"] += len(rs)
    n = max(1, total["n"])
    print(f"{'ALL':16s} {total['w']:4d} {total['t']:4d} {total['l']:4d}  {100*total['w']/n:5.1f} {100*total['t']/n:5.1f}  {(3*total['w']+total['t'])/n:5.2f}")
    bad = [r for r in results if r["result"] is None or r.get("issues")]
    for r in bad[:20]:
        print("  issue:", r["opponent"], r["layout"], r["side"], r.get("issues") or r.get("note", "")[:200])
    losses = [r for r in results if r["result"] is not None and r["result"] < 0]
    if losses:
        print("losses:", ", ".join(f"{r['opponent']}@{r['layout']}/{r['side']}" for r in losses[:40]))
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(results, fh, indent=1)


if __name__ == "__main__":
    main()
