# Agent branch `agent/astar`

**A* path planner around visible ghosts.**

This branch holds one of the sparring opponents we used to test the main agent.
It is not a contest entry. The main agent and the test tools are on `main`;
see `docs/AGENT.md` there.

`my_team.py` is self-contained (shared helpers inlined), so it can be played
directly or from `main` with `python testing/bench.py -o astar`.

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team
```

## What it does (from the module docstring)

A* attacker that plans whole paths around the ghosts it can see, plus a defender.

This is the heuristic-search style many teams adapt from the CS188 search
project: A* to the best dot with squares next to a ghost blocked and squares
near one made expensive, then A* back home once loaded or threatened.
