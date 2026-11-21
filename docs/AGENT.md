# Agent branch `agent/mdp`

**Value iteration over a reward grid, both roles.**

This branch holds one of the sparring opponents we used to test the main agent.
It is not a contest entry. The main agent and the test tools are on `main`;
see `docs/AGENT.md` there.

`my_team.py` is self-contained (shared helpers inlined), so it can be played
directly or from `main` with `python testing/bench.py -o mdp`.

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team
```

## What it does (from the module docstring)

Value-iteration (MDP) attacker and defender.

The usual student MDP: every turn, put rewards on the grid (food, capsules,
home once loaded, invaders for the defender), penalise squares near visible
ghosts, run value iteration with a discount, then step to the best neighbour.
