# Agent branch `agent/cursor`

**The Cursor team (Cursor agent V1.2, commit a50df4b).**

This branch holds the team that was on the `Cursor` branch, built from the
`ContestAgent` of `1aef08f`. It is a separate team, not a contest entry; the
main agent and the test tools are on `main` (see `docs/AGENT.md` there).
It is one of the strongest sparring opponents in the hard suite.

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team
```

From `main`, `python testing/bench.py -o cursor` plays this branch.

## What it does (from the module docstring)

The raider treats a ghost as extra path cost, grabs the shallow pellets
(most food on defaultCapture is a dead end just inside a door) and banks two
or three before a defender can reach that door. The guard holds the door an
invader is actually using, and stays on it for a step after they retreat.
A belief cloud never becomes a wall, and a reply search never overrides
the plan: both of those freeze an attacker against a careful opponent.

The earlier version, Cursor agent V1 (c8ef302), is in the history of the
old `Cursor` branch only.
