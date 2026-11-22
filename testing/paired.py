#!/usr/bin/env python3
"""Compare two seeded bench runs game by game.

Both runs must use the same --game-seed, so game k of one run and game k of
the other start identically (who moves first, sonar noise). Only games whose
result changed carry information, which makes small effects measurable.

    python testing/bench.py -a my_team.py -o astar,bfs -f "$D" -r 0 --game-seed s1 --json ref.json
    python testing/bench.py -a candidate.py -o astar,bfs -f "$D" -r 0 --game-seed s1 --json new.json
    python testing/paired.py ref.json new.json
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench import POINTS, map_weighted  # noqa: E402


def load(path):
    return {g["seed"]: g for g in json.load(open(path)) if g.get("result") is not None}


def main():
    ref, new = load(sys.argv[1]), load(sys.argv[2])
    common = [s for s in ref if s in new]
    if not common:
        sys.exit("no games in common: were both runs made with the same --game-seed?")
    # Every map weighs the same: differences are averaged per layout first.
    per = collections.defaultdict(list)
    for s in common:
        per[ref[s]["opponent"].split("/")[-1]].append(
            (ref[s]["layout"], POINTS[new[s]["result"]] - POINTS[ref[s]["result"]]))
    for opponent, diffs in sorted(per.items()):
        mean, se = map_weighted(diffs)
        print(f"{opponent:28} {mean:+.2f} +- {se:.2f}  (changed {sum(d != 0 for _, d in diffs)}/{len(diffs)})")
    mean, se = map_weighted([d for diffs in per.values() for d in diffs])
    before, _ = map_weighted([(ref[s]["layout"], POINTS[ref[s]["result"]]) for s in common])
    after, _ = map_weighted([(new[s]["layout"], POINTS[new[s]["result"]]) for s in common])
    print(f"{'ALL':28} {mean:+.3f} +- {se:.3f}  n={len(common)}  {before:.3f} -> {after:.3f} pts/game, maps weighted equally")


if __name__ == "__main__":
    main()
