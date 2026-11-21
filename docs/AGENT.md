# Agent branch `agent/mm-replay-proxy`

**Earlier, rougher M&M proxy inferred from match_150100.**

This branch holds a behavioural proxy of a real contest team, rebuilt from
contest replays. It is not that team's code: it reproduces the decision rules
seen in the replays. The main agent and the test tools are on `main`.

`my_team.py` is self-contained (shared helpers inlined), so it can be played
directly or from `main` with `python testing/bench.py -o mm-replay-proxy`.

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team
```

## What it does (from the module docstring)

Behavioral proxy for M&M, inferred from match_150100.replay.

This is not M&M's source. It reproduces the observed policy family:
one capsule-aware, risk-averse raider and one sentinel that owns its
nearest door, tracks active invaders, and returns to that post.
