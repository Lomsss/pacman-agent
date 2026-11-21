# Agent branch `agent/double-baseline`

**Two baseline offensive reflex agents.**

This branch holds one of the sparring opponents we used to test the main agent.
It is not a contest entry. The main agent and the test tools are on `main`;
see `docs/AGENT.md` there.

`my_team.py` is self-contained (shared helpers inlined), so it can be played
directly or from `main` with `python testing/bench.py -o double-baseline`.

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team
```

## What it does (from the module docstring)

The staff baseline with both agents on offense.
