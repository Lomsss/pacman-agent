#!/usr/bin/env python3
"""Round-robin tournament between agents, scored the way the contest is.

Every pair of entrants plays every map twice, once with each colour.
A win is 3 points, a tie 1, a loss 0. Entrants are ranked by points per
game with every map weighted equally (bench.map_weighted), then by wins.

Examples (from the repository root):
    python testing/tournament.py                          # every agent, 10 fixed + 6 random maps
    python testing/tournament.py -t main=my_team.py,v2=git:agent/v2,astar -f defaultCapture -r 4
    python testing/tournament.py --json t1.json --game-seed t1
    python testing/tournament.py --resume t1.json -t new=cand.py,... --json t2.json   # only play new pairs

An entrant is name=spec or just spec, where spec is anything bench.py
accepts: an opponent name (its agent/<name> branch), git:<ref> or a file.
With --resume, games already in the given file (same entrants, map and
seed) are reused, so adding one entrant only plays its own pairs. Only use
it when the other entrants have not changed.
"""
import argparse
import itertools
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench  # noqa: E402
from bench import FIXED, OPPONENTS, POINTS, map_weighted  # noqa: E402

DEFAULT = (["allrounder=my_team.py", "v2=git:agent/v2", "contest-agent=git:agent/contest-agent", "baseline"]
           + [n for n in OPPONENTS])


def parse(entrants):
    out = {}
    for e in entrants:
        name, _, spec = e.partition("=")
        if not spec:
            name, spec = e, e
        if name in out:
            sys.exit(f"entrant {name!r} given twice")
        out[name] = spec
    return out


def standings(games, names):
    rows = []
    for n in names:
        mine = [(g["layout"], POINTS[g["result"]] if g["red"] == n else POINTS[-g["result"]])
                for g in games if n in (g["red"], g["blue"])]
        w = sum(p == 3 for _, p in mine); t = sum(p == 1 for _, p in mine); l = sum(p == 0 for _, p in mine)
        mean, se = map_weighted(mine)
        issues = sum(len(g["red_issues"] if g["red"] == n else g["blue_issues"]) > 0
                     for g in games if n in (g["red"], g["blue"]))
        rows.append((mean, w, n, se, t, l, len(mine), issues))
    rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
    return rows


def head_to_head(games, a, b):
    """Map-weighted points per game of a against b."""
    vals = [(g["layout"], POINTS[g["result"]] if g["red"] == a else POINTS[-g["result"]])
            for g in games if {g["red"], g["blue"]} == {a, b}]
    return map_weighted(vals)[0] if vals else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-t", "--teams", default=",".join(DEFAULT), help="comma list of name=spec or spec")
    ap.add_argument("-f", "--fixed", default=",".join(FIXED), help="fixed layouts (empty for none)")
    ap.add_argument("-r", "--random", type=int, default=6, help="number of random maps")
    ap.add_argument("-s", "--seed", type=int, default=1000, help="first random map seed")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("-i", "--length", type=int, default=1200)
    ap.add_argument("--game-seed", default="tournament", help="seeds every game so runs can be compared")
    ap.add_argument("--resume", help="reuse finished games from an earlier --json file")
    ap.add_argument("--json")
    args = ap.parse_args()

    teams = parse([t for t in args.teams.split(",") if t])
    names = list(teams)
    layouts = [l for l in args.fixed.split(",") if l] + [f"RANDOM{args.seed + k}" for k in range(args.random)]
    tmp = tempfile.mkdtemp(prefix="tournament_")
    bench.TMP = tmp
    for l in layouts:
        bench.layout_file(l, tmp)
    paths = {n: bench.resolve(spec, tmp) for n, spec in teams.items()}

    done = {}
    if args.resume:
        for g in json.load(open(args.resume)):
            if g["result"] is not None and g["red"] in teams and g["blue"] in teams:
                done[g["seed"]] = g
    jobs = []
    for a, b in itertools.combinations(names, 2):
        pair = "|".join(sorted((a, b)))
        for k, l in enumerate(layouts):
            for red, blue in ((a, b), (b, a)):
                seed = f"{args.game_seed}:{pair}:{l}:{k}:{red}"
                jobs.append((red, blue, l, seed))
    todo = [j for j in jobs if j[3] not in done]
    print(f"{len(names)} entrants, {len(layouts)} maps, {len(jobs)} games ({len(jobs) - len(todo)} reused), "
          f"{args.jobs} at a time", flush=True)

    def run(job):
        red, blue, layout, seed = job
        r = bench.play(paths[red], paths[blue], layout, "red", args.length, seed)
        return {"red": red, "blue": blue, "layout": layout, "seed": seed, "result": r["result"],
                "margin": r.get("margin"), "early": r.get("early"), "red_issues": r.get("issues", []),
                "blue_issues": r.get("opp_issues", []), "note": r.get("note")}

    with ThreadPoolExecutor(args.jobs) as ex:
        fresh = list(ex.map(run, todo))
    games = [done[j[3]] if j[3] in done else None for j in jobs]
    it = iter(fresh)
    games = [g if g is not None else next(it) for g in games]
    failed = [g for g in games if g["result"] is None]
    ok = [g for g in games if g["result"] is not None]

    rows = standings(ok, names)
    print(f"\n{'rank':>4s}  {'entrant':16s} {'pts/game':>13s}  {'W':>4s} {'T':>4s} {'L':>4s}  games  issues")
    for i, (mean, w, n, se, t, l, ng, issues) in enumerate(rows, 1):
        print(f"{i:4d}  {n:16s} {mean:5.2f} ± {se:4.2f}  {w:4d} {t:4d} {l:4d}  {ng:5d}  {issues}")
    top = [r[2] for r in rows]
    width = max(6, max(len(n) for n in top))
    print(f"\nHead to head (row's points per game against column, maps weighted equally):")
    print(" " * (width + 1) + " ".join(f"{n[:6]:>6s}" for n in top))
    for a in top:
        cells = [head_to_head(ok, a, b) for b in top]
        print(f"{a:{width}s} " + " ".join("     -" if a == b or c is None else f"{c:6.2f}" for b, c in zip(top, cells)))
    for g in failed[:20]:
        print("  unfinished:", g["red"], "vs", g["blue"], g["layout"], (g.get("note") or "")[:150])
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(games, fh, indent=1)


if __name__ == "__main__":
    main()
