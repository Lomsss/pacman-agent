# Allrounder: what changed and how it was measured

`my_team.py` on this branch is the PR #5 agent plus three changes. On the
seven opponents that still take points from us on defaultCapture it scores
about **+0.33 points a game** more (1.99 → 2.40 and 2.10 → 2.35 on two
independent seed sets). Against the other ten it is unchanged.

## Method

- **Paired games.** `bench.py --game-seed` seeds every game, so two
  versions play exactly the same games, and `testing/paired.py` compares
  them game by game. Against deterministic opponents a seeded game replays
  move for move.
- **Hard suite.** The seven opponents that do not lose every game on
  defaultCapture: `astar`, `bfs`, `mdp`, `switcher`, the PR #5 agent
  (`git:main`), crowded-stalls and Cursor. That is 40 games each per seed set.
- **Keep rule.** A change is kept only if it gains on two seed sets and a
  run against all 17 opponents shows no other loss.
- **New opponents.** `mdp` (value iteration), `bfs` (plain BFS with a
  chasing defender) and `abfull` (full-state alpha-beta), to cover the
  styles the field is expected to use.

## Changes kept

| Change | Paired gain, seed set 1 / seed set 2 |
|---|---|
| Colour-symmetric tie-breaks | blue 2.15 → 2.33, red unchanged (unpaired, 420 games) |
| Route verification against a chasing ghost | +0.33 / +0.16 |
| Dead-end trap on our side | +0.10 / +0.19 |
| Verification and trap together | **+0.41 / +0.24** |

**Colour-symmetric tie-breaks.** Every tie (sorted squares, heap order,
the first move tried) used raw coordinates. On the 180° symmetric map,
blue therefore played a differently tuned agent from red. Against an exact
copy of itself, blue scored 0.70 points a game where it should score 1.5.
Blue now breaks ties as red would on the rotated map.

**Route verification.** Every defender in the field chases a pacman it can
see. When a visible, unscared ghost is within 7 squares, the raider
simulates the routes to its six best-priced targets, and then the route
home, against that ghost stepping toward it each turn (ties kept
pessimistically). It takes the best target whose route is not caught.
Deaths against the BFS team fell from about 2.7 to 1.2 a game in a
6-game check. Each move uses at most about 2 ms.

**Dead-end trap.** When a visible invader is in a dead end on our side and
we can reach its mouth first, the defender holds the mouth instead of
chasing. A mouth with our capsule below it is skipped.

## Tried and dropped

| Change | Paired result | Why it failed |
|---|---|---|
| Danger from every square a visible ghost reaches first | −0.87 | Walls off half the map, so the raider is too timid |
| Sentinel hangs back near our capsule | +0.03, but −0.25 vs A\* (its target) | Lets the A\* attacker through |
| Double defence to protect a late lead | −0.09 | Gives up points in close games |
| Runtime opponent identification | not built | See `docs/OPPONENT_ID_DESIGN.md` |

## Open issue

- A\* is slightly worse on all three seed sets (−0.17, −0.05, −0.40;
  pooled about −0.17 ± 0.13). It is not significant, but it is the next
  thing to look at.
