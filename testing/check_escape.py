#!/usr/bin/env python3
"""Check that Maze.escape in my_team.py solves the raider's duel exactly.

    python testing/check_escape.py                      # three fixed maps, both colours
    python testing/check_escape.py jumboCapture RANDOM5

Re-solves our pacman against one enemy ghost on its side by plain sweeps over
every position until nothing changes, starting from "nothing is safe", and
compares each position with the solver. Us to move: safe if a step reaches
home or a capsule, or reaches a free square where the ghost to move is held.
Ghost to move: held if it is not on or next to us and every reply (staying
included) leaves us safe.
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pacman-contest", "src"))
spec = importlib.util.spec_from_file_location("my_team", os.path.join(ROOT, "my_team.py"))
team = importlib.util.module_from_spec(spec)
spec.loader.exec_module(team)
from contest.capture import random_layout  # noqa: E402
from contest.layout import Layout, get_layout  # noqa: E402


def check(name, red):
    if name.startswith("RANDOM"):
        lay = Layout(layout_name=name, layout_text=random_layout(int(name[6:]))[1].split("\n"))
    else:
        lay = get_layout(name)
    maze = team.Maze(lay.walls, red)
    caps = {c for c in lay.capsules if c not in maze.home}
    ix, held = maze.escape(caps)
    away = list(ix)
    moves = {p: [q for q, _ in maze.edges[p]] + [p] for p in away}
    safe, hold = set(), set()
    changed = True
    while changed:
        changed = False
        for q in away:
            for g in away:
                if g == q:
                    continue
                if (q, g) not in safe and any(r in maze.home or r in caps or (r != g and (r, g) in hold)
                                              for r in moves[q]):
                    safe.add((q, g))
                    changed = True
                if (q, g) not in hold and q not in moves[g] and all(
                        h in maze.home or (q, h) in safe for h in moves[g]):
                    hold.add((q, g))
                    changed = True
    n = len(away)
    for q in away:
        for g in away:
            if g != q:
                assert bool(held[ix[q] * n + ix[g]]) == ((q, g) in hold), (name, red, q, g)
    return n * (n - 1)


def main():
    os.chdir(os.path.join(ROOT, "pacman-contest", "src", "contest"))
    for name in sys.argv[1:] or ["defaultCapture", "mediumCapture", "officeCapture"]:
        for red in (True, False):
            print(f"{name} {'red' if red else 'blue'}: {check(name, red)} positions ok")


if __name__ == "__main__":
    main()
