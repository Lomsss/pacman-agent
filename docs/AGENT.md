# Agent branch `agent/abfull`

**Full-state alpha-beta with iterative deepening.**

This branch holds one of the sparring opponents we used to test the main agent.
It is not a contest entry. The main agent and the test tools are on `main`;
see `docs/AGENT.md` there.

`my_team.py` is self-contained (shared helpers inlined), so it can be played
directly or from `main` with `python testing/bench.py -o abfull`.

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team
```

## What it does (from the module docstring)

Full-state alpha-beta team, the CS188 multi-agent project adapted to capture.

Both agents search the real game state with generate_successor over
themselves and every enemy they can see, deepening one ply at a time until
the time budget runs out. The evaluation is the usual weighted features,
with an offence and a defence version.
