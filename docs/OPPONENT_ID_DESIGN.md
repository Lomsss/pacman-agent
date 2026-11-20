# Opponent identification: decision

**Verdict: no runtime identification by default.** An adversarial review
(three lenses plus a critic, reading every suite opponent's source) cut the
first draft. When nearly the whole field shares a behaviour, the default
play should handle it, and a label adds only false-positive risk.

## What was cut, and why

| Element | Reason |
|---|---|
| Attacker ghost clearance `r` | About 2 for every field attacker (`astar_team.py` cost INF at d<=1, `zoo_common.py` -1000 at d<=1, BFS and MDP block it too). Our own chasing drives the observed values down, so it measures us, not them. |
| Defender leash `L` | A maximum over sightings near our agents is a lower bound, but the use needed an upper bound: the raider would have treated unexplored squares as safe. No field defender has a leash. |
| Capsule greed (2 of 2 events) | defaultCapture has one capsule per side. It could never fire before the capsule is gone. |
| Greedy / Cautious / Chaser / Holder labels | Their only consumer, the reply forecast, is off by default (`lookahead="0"`, disabled in db2c5fd). Holder misfires on the camper, which chases within 6. Chaser describes every field defender, so it belongs in the default risk model, not in a label. |

Evidence errors found in the draft, kept here for any future detector:

- Both our agents see every enemy move between their turns, so a
  per-agent store double-counts. Read one store only.
- The observed state already contains the effects of the enemy's move
  (food or capsule eaten, a kill, its side flag and load). Judge
  evidence on the pre-move state.
- "Visible before and after" keeps approaches and drops retreats.
  Treat a move that leaves sight as censored, not as evidence.
- Opponents act on their own partial view, ties and jitter. Spread
  probability over ties.
- Agents persist across games in a multi-game run: reset every store in
  `register_initial_state`.

## What may survive

1. Benchmark an unconditional sentinel hang-back near our capsule (no
   identification). Keep it if A* and Cursor each improve by >= 0.2 points
   per game over >= 40 paired games and no other opponent drops by > 0.1.
2. Only if step 1 helps A* and Cursor but costs points elsewhere: one
   per-enemy capsule-seeker detector, a CUSUM test fixed in advance
   (match +ln(0.85/0.40), miss ln(0.15/0.60), declare at ln 49 after at
   least 6 net matches). It counts only moves where the shortest step to
   the capsule differs from the steps toward food and home. Ground truth
   for each opponent is written down from its source before a passive
   false-positive run, and the thresholds are never tuned on the suite.
