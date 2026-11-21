# Agent branch `agent/crowded-stalls`

**The crowded-stalls team (commit 79c5379), the direct ancestor of the main agent.**

This branch holds the team that was on `codex/crowded-stalls`. It was merged
into `main` at `e74870e` as the starting point of the current agent, which
then added stand-off breaking and doubled ghost risk (PR #5), colour-symmetric
tie-breaks, route verification, the dead-end trap and multi-dot trips (see
`docs/AGENT.md` on `main` for the measured gains). It stays useful as a
sparring opponent: mirror-style matches against it separate close versions.

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team
```

From `main`, `python testing/bench.py -o crowded-stalls` plays this branch.

## What it does

A `Raider` and a `Sentinel` sharing one class. The raider plans risk-priced
routes (ghost danger added to path cost) and banks small loads; the sentinel
intercepts invaders on their path to our food or the exit, re-covers a door
right after an invader steps back over the line, and chases the square where
a dot just vanished. Against the previous `ContestAgent` it won 59-1-0 on
defaultCapture, because it carried more food per raid.
