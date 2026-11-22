#!/usr/bin/env python3
"""Check that Maze.contain in my_team.py solves the defender's chase game exactly.

    python testing/check_contain.py                      # five fixed maps, both colours
    python testing/check_contain.py jumboCapture RANDOM5

For every pair of squares on our side it re-derives, from the rules of the
game, who wins and compares that with the solver. Invader to move: it wins if
a step takes it home, onto one of our capsules or out of our ghost's sight, or
if some step leaves the ghost with only losing replies. Ghost to move: it holds
if it can eat the invader or reach a position the invader does not win.
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
    caps = {c for c in lay.capsules if c in maze.home}
    maze.contain(caps)
    ix, n, lost = maze.cix, len(maze.cix), maze.lost
    moves = lambda p: [q for q, _ in maze.edges[p] if q in maze.home] + [p]
    won = lambda d, i: lost[ix[d] * n + ix[i]]
    home = maze.order(maze.home)
    for d in home:
        for i in home:
            if d == i:
                continue
            holds = any(e == i or not won(e, i) for e in moves(d))
            assert bool(maze.holds(d, i)) == holds, (name, red, d, i)
            escape = any(q not in maze.home or q in caps for q, _ in maze.edges[i]) or \
                any(team.manhattan(d, j) > team.SIGHT for j in moves(i))
            beats = escape or any(j != d and not any(e == j or not won(e, j) for e in moves(d)) for j in moves(i))
            assert bool(won(d, i)) == beats, (name, red, d, i)
    return n * (n - 1)


def main():
    os.chdir(os.path.join(ROOT, "pacman-contest", "src", "contest"))
    for name in sys.argv[1:] or ["defaultCapture", "mediumCapture", "bloxCapture", "strategicCapture", "officeCapture"]:
        for red in (True, False):
            print(f"{name} {'red' if red else 'blue'}: {check(name, red)} positions ok")


if __name__ == "__main__":
    main()
