# Stress testing

`bench.py` plays our team against a set of opponents that copy the styles
other teams are likely to use. Every map is played twice, once with us as
red and once as blue. It reports wins, ties, losses, tournament points
(3 for a win, 1 for a tie), average margin, early finishes (all but two
dots returned) and any timeouts or crashes by our agents.

```bash
# from the repository root, with the contest submodule checked out
python testing/bench.py                           # all opponents, 10 fixed + 20 random maps
python testing/bench.py -o rusher,capsule -r 60   # focus on two styles, 60 random maps
python testing/bench.py -o git:main               # play against the version on main
python testing/bench.py -a path/to/candidate.py   # test a candidate file instead of my_team.py
python testing/bench.py -f "" -r 40 -s 2000       # 40 random maps only, seeds 2000-2039
```

A full run is several hundred games. With 4 cores it takes roughly 5 to 10
minutes. Results vary between runs because the agents and the sonar are
random, so compare two versions on the same maps (`-s`) and treat a
difference under about 0.1 points per game as noise.

## Opponents (`testing/opponents/`)

| name | style |
|---|---|
| `baseline` | the staff baseline team |
| `double_baseline` | the baseline with both agents attacking |
| `rusher` | two greedy attackers that carry 6 dots and only flee ghosts within 2 squares |
| `turtle` | two defenders with sonar tracking that split the doors |
| `capsule` | an attacker that goes for the capsule first and feasts while ghosts are scared, plus a defender |
| `switcher` | roles follow the score: both attack when behind, both defend when ahead late |
| `approxq` | a linear Q-function over hand-tuned features (what approximate Q-learning produces), plus a defender |
| `minimax` | an alpha-beta attacker against the ghosts it can see, plus a defender |
| `mcts` | a Monte Carlo tree search attacker (UCT with rollouts), plus a defender |
| `astar` | an A* attacker that plans whole paths around the ghosts it can see, plus a defender |
| `camper` | a greedy attacker plus a defender that camps on the border level with the nearest enemy |
| `mdp` | value iteration over a reward grid (food, capsules, home when loaded, ghost penalties), both roles |
| `bfs` | plain BFS: nearest dot with squares next to a ghost treated as walls, and a chasing defender |
| `abfull` | full-state alpha-beta with iterative deepening over `generate_successor`, 0.25 s per move |
| `mirror_attack` | our own code with both agents attacking |
| `git:<ref>` | any past version of `my_team.py` |

All opponents only use what the game gives every agent (their own
observation, maze distances and noisy sonar), so results reflect what a
real opponent could do.

## The contest map

The tournament is played on `defaultCapture` only, so test there first.
Repeating a layout in `-f` plays it again with fresh random sonar:

```bash
D=$(python3 -c "print(','.join(['defaultCapture'] * 20))")
python testing/bench.py -f "$D" -r 0 -o astar,capsule,git:main   # 40 games per opponent
```

Treat the other maps as a robustness check. On one map, a difference needs
roughly 40 games per opponent before it stands out from the noise.

## Comparing two versions (`--game-seed`, `paired.py`)

`--game-seed` seeds every game (which team moves first, the sonar noise),
so two agents can play exactly the same games. Against deterministic
opponents a seeded game replays move for move. `paired.py` then compares
the runs game by game; only games whose result changed carry information,
so effects of about 0.1 points per game show up in a few hundred games.

```bash
D=$(python3 -c "print(','.join(['defaultCapture'] * 20))")
OPP=astar,bfs,mdp,switcher,git:main,git:origin/codex/crowded-stalls,git:origin/Cursor
python testing/bench.py -a my_team.py   -o $OPP -f "$D" -r 0 --game-seed s1 --json ref.json
python testing/bench.py -a candidate.py -o $OPP -f "$D" -r 0 --game-seed s1 --json new.json
python testing/paired.py ref.json new.json
```

These seven opponents are the "hard suite": the ones that do not lose every
game on defaultCapture, so they separate two versions. Confirm a gain on a
second seed (`s2`) before keeping it, and run the full opponent list once to
check nothing else got worse. Opponents that stop searching on a clock
(`abfull`, `minimax`, `mcts`) do not replay exactly.

The contest framework needs `frozendict`; if your Python lacks it, run
`pip install frozendict==2.3.4`.

## Why a game was won or lost (`match_stats.py`)

`match_stats.py` replays every game's moves and counts what happened inside
it, per team: dots banked, deaths as pacman, dots lost by dying, scared
ghosts eaten, capsules eaten, moves on the enemy side, the largest load,
who scored first, lead changes and the score after each quarter.

```bash
python testing/match_stats.py -a my_team.py -b testing/opponents/astar_team.py -f "$D" -r 0
```
