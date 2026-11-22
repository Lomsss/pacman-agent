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
python testing/bench.py -o git:7655999            # play against a past version of our agent
python testing/bench.py -a path/to/candidate.py   # test a candidate file instead of my_team.py
python testing/bench.py -f "" -r 40 -s 2000       # 40 random maps only, seeds 2000-2039
```

`pts/map` weights every map equally: the games on one layout (repeats and
both colours) are averaged first, then the maps are averaged. So repeating
`defaultCapture` 20 times in `-f` gives it more games, which narrows its
error bar, but not more weight. `pts/g` is the plain per-game mean.
`paired.py` and `tournament.py` weight maps the same way.

A full run is several hundred games. With 4 cores it takes roughly 5 to 10
minutes. Results vary between runs because the agents and the sonar are
random, so compare two versions on the same maps (`-s`) and treat a
difference under about 0.1 points per game as noise.

## Opponents (one branch each)

Every opponent lives on its own branch, `agent/<name>`, where `my_team.py`
is that agent as one self-contained file. `bench.py` reads it with
`git show`, from the local branch or `origin/agent/<name>`, so run
`git fetch origin` once after cloning. Nothing needs to be checked out.

| name | branch | style |
|---|---|---|
| `baseline` | (in the contest) | the staff baseline team |
| `double-baseline` | `agent/double-baseline` | the baseline with both agents attacking |
| `rusher` | `agent/rusher` | two greedy attackers that carry 6 dots and only flee ghosts within 2 squares |
| `turtle` | `agent/turtle` | two defenders with sonar tracking that split the doors |
| `capsule` | `agent/capsule` | an attacker that goes for the capsule first and feasts while ghosts are scared, plus a defender |
| `switcher` | `agent/switcher` | roles follow the score: both attack when behind, both defend when ahead late |
| `approxq` | `agent/approxq` | a linear Q-function over hand-tuned features (what approximate Q-learning produces), plus a defender |
| `minimax` | `agent/minimax` | an alpha-beta attacker against the ghosts it can see, plus a defender |
| `mcts` | `agent/mcts` | a Monte Carlo tree search attacker (UCT with rollouts), plus a defender |
| `astar` | `agent/astar` | an A* attacker that plans whole paths around the ghosts it can see, plus a defender |
| `camper` | `agent/camper` | a greedy attacker plus a defender that camps on the border level with the nearest enemy |
| `mdp` | `agent/mdp` | value iteration over a reward grid (food, capsules, home when loaded, ghost penalties), both roles |
| `bfs` | `agent/bfs` | plain BFS: nearest dot with squares next to a ghost treated as walls, and a chasing defender |
| `abfull` | `agent/abfull` | full-state alpha-beta with iterative deepening over `generate_successor`, 0.25 s per move |
| `mirror-attack` | `agent/mirror-attack` | our main agent as of the split, with both agents attacking |
| `mm` | `agent/mm` | proxy of the contest team M&M (reproduces 599/600 replay moves) |
| `alma` | `agent/alma` | proxy of the contest team Alma Team (97% of replay moves) |
| `ghostclaniol` | `agent/ghostclaniol` | proxy of the contest team GhostClaniol (97% of replay moves) |
| `cursor` | `agent/cursor` | the Cursor team (Cursor agent V1.2) |
| `crowded-stalls` | `agent/crowded-stalls` | the crowded-stalls team, which the main agent grew from |
| `git:<ref>` | any | `my_team.py` at any commit or branch, e.g. `git:agent/v2`, `git:7655999` |

The proxies were rebuilt from contest replays; their branch docs list the
inferred rules, the likely algorithm and the weaknesses seen in the games.
`agent/v2` and `agent/contest-agent` are not in the default list; play
them with `git:agent/v2` and `git:agent/contest-agent`. To change an opponent,
commit to its branch; `bench.py` always plays the branch tip.

All opponents only use what the game gives every agent (their own
observation, maze distances and noisy sonar), so results reflect what a
real opponent could do.

## The contest map

The tournament is played on `defaultCapture` only, so test there first.
Repeating a layout in `-f` plays it again with fresh random sonar:

```bash
D=$(python3 -c "print(','.join(['defaultCapture'] * 20))")
python testing/bench.py -f "$D" -r 0 -o astar,capsule,git:7655999   # 40 games per opponent
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
OPP=astar,bfs,mdp,switcher,git:7655999,crowded-stalls,cursor
python testing/bench.py -a my_team.py   -o $OPP -f "$D" -r 0 --game-seed s1 --json ref.json
python testing/bench.py -a candidate.py -o $OPP -f "$D" -r 0 --game-seed s1 --json new.json
python testing/paired.py ref.json new.json
```

These seven opponents are the "hard suite": the ones that do not lose every
game on defaultCapture, so they separate two versions. `git:7655999` is the
PR #5 agent; pin past versions by commit, because `git:main` moves whenever
a PR is merged and then plays the agent against itself. For other maps and
the contest-team styles, add `mm,alma,ghostclaniol` and maps to `-f`. Confirm a gain on a
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
python testing/match_stats.py -a my_team.py -b astar -f "$D" -r 0
```

## Replaying one game (`why.py`)

`why.py` replays one seeded game and prints the score every 100 moves and
every death, bank, capsule and scared-ghost kill, so a lost game can be
inspected move by move:

```bash
python testing/why.py --from-json ref.json --index 17        # game 17 of a bench run
python testing/why.py -r my_team.py -b astar -l defaultCapture --seed "s1:astar:defaultCapture:3:red"
```

## Round-robin tournament (`tournament.py`)

`tournament.py` plays every pair of entrants on every map, once with each
colour, and ranks them the way the contest does: 3 points for a win, 1 for
a tie, points per game with every map weighted equally. It also prints a
head-to-head table.

```bash
python testing/tournament.py --json t1.json             # every agent branch plus main, 10 fixed + 6 random maps
python testing/tournament.py -t main=my_team.py,v2=git:agent/v2,astar,mm -f defaultCapture -r 4
python testing/tournament.py --resume t1.json -t "$(cat teams.txt),new=cand.py" --json t2.json
```

With `--resume`, games already played between the same entrants on the
same map and seed are reused, so adding one entrant only plays its pairs.
Every agent is played on 16 maps x 2 colours against each other agent, so
the full default field (23 entrants) is about 8,000 games; abfull, mcts and
the contest agent think on a clock, so those pairs take most of the time.
