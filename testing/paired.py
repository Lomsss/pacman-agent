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
import math
import sys

POINTS = {1: 3, 0: 1, -1: 0}


def load(path):
    return {g["seed"]: g for g in json.load(open(path)) if g.get("result") is not None}


def stat(values):
    mean = sum(values) / len(values)
    sd = math.sqrt(sum((x - mean) ** 2 for x in values) / max(1, len(values) - 1))
    return mean, sd / math.sqrt(len(values))


def main():
    ref, new = load(sys.argv[1]), load(sys.argv[2])
    common = [s for s in ref if s in new]
    if not common:
        sys.exit("no games in common: were both runs made with the same --game-seed?")
    per = collections.defaultdict(list)
    for s in common:
        per[ref[s]["opponent"].split("/")[-1]].append(POINTS[new[s]["result"]] - POINTS[ref[s]["result"]])
    for opponent, diffs in sorted(per.items()):
        mean, se = stat(diffs)
        print(f"{opponent:28} {mean:+.2f} +- {se:.2f}  (changed {sum(d != 0 for d in diffs)}/{len(diffs)})")
    mean, se = stat([d for diffs in per.values() for d in diffs])
    before = sum(POINTS[ref[s]["result"]] for s in common) / len(common)
    after = sum(POINTS[new[s]["result"]] for s in common) / len(common)
    print(f"{'ALL':28} {mean:+.3f} +- {se:.3f}  n={len(common)}  {before:.3f} -> {after:.3f} pts/game")


if __name__ == "__main__":
    main()
