# Agent branch `agent/bfs`

**Plain BFS; squares next to ghosts treated as walls.**

This branch holds one of the sparring opponents we used to test the main agent.
It is not a contest entry. The main agent and the test tools are on `main`;
see `docs/AGENT.md` there.

`my_team.py` is self-contained (shared helpers inlined), so it can be played
directly or from `main` with `python testing/bench.py -o bfs`.

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team
```

## What it does (from the module docstring)

Plain BFS team: the first search most students write.

The attacker runs BFS to the nearest dot, treating squares next to a
visible ghost as walls, and BFS home once it carries 4 or a ghost is near.
The defender runs BFS to the invader it sees, else the last eaten dot,
else the door nearest our food.
