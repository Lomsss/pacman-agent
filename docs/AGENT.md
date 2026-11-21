# Agent branch `agent/camper`

**Greedy attacker plus a border-mirroring camper.**

This branch holds one of the sparring opponents we used to test the main agent.
It is not a contest entry. The main agent and the test tools are on `main`;
see `docs/AGENT.md` there.

`my_team.py` is self-contained (shared helpers inlined), so it can be played
directly or from `main` with `python testing/bench.py -o camper`.

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team
```

## What it does (from the module docstring)

A greedy attacker plus a border camper that mirrors the nearest enemy.

The camper never crosses. It stands on the border square level with the
enemy it believes is closest, so any crossing runs straight into it, and it
only leaves the line to eat an invader it can see.
