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

## Why a game was won or lost (`match_stats.py`)

`match_stats.py` replays every game's moves and counts what happened inside
it, per team: dots banked, deaths as pacman, dots lost by dying, scared
ghosts eaten, capsules eaten, moves on the enemy side, the largest load,
who scored first, lead changes and the score after each quarter.

```bash
python testing/match_stats.py -a my_team.py -b testing/opponents/astar_team.py -f "$D" -r 0
```
