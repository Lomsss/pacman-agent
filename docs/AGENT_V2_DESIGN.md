# Agent v2 design (`my_team_v2.py`)

`my_team_v2.py` is a second-generation team built from what our tests
showed. It keeps every technique the data supports, adds two that target
open weaknesses, and leaves out the ideas that cost points when we tried
them. `my_team.py` is unchanged. The section numbers below (§1 to §9)
match the numbered banners in the source.

All tests were run on `defaultCapture`, the contest map, unless a line
says otherwise. Points use 3 per win and 1 per tie, per game.

## What the data told us

| Idea | Evidence | In v2? |
|---|---|---|
| Bold raider with risk-priced routes (crowded-stalls) | Beat the previous main agent 59–1–0. Main banked 6.6 dots a game against 10.9, because it was too careful. | Yes (§5) |
| Ghost risk weights ×2 | Against Cursor, 1.25 → 2.21. ×1.5 and ×3 scored less. | Yes (§1, §5) |
| Breaking stand-offs when not ahead | Part of the PR #5 gain (2.52 → 2.78 overall). Only when level or behind, because a stand-off runs the clock for the side that leads. | Yes (§5) |
| Interception on the invader's path, door re-cover, bite chase | Crowded-stalls' defence. No defensive change we tried did better. | Yes (§7) |
| Teammate sonar fusion | Tracking error falls from 5.03 to 4.54 squares against Cursor, and from 5.58 to 4.19 against the A* attacker (10 games each, measured against the true positions). No points change we can measure. | Yes (§3) |
| Forced-capture search for the sentinel | Never worse in screening (2.31 against 2.29 without it, 160 games each). It rarely fires: about 1 in 50 searches finds a capture we can force. | Yes (§8) |
| Deep escape search for the raider (worst-case replies of both ghosts, up to 8 rounds) | 1.98 against 2.29 without it. Like main's look-ahead, planning for a perfect guard makes the raider too careful. | No |
| Short escape search (2 rounds) | Cursor 2.40 → 2.55 but A* 2.17 → 1.70. | No |
| Scared ghost walks into the invader to respawn unscared | 2.00 and 1.95 against 2.31. The scared sentinel scores more by counter-raiding. | No |
| Guarding our capsule during interception | A* matchup 1.95 → 1.57 (tested for PR #5). | No |

Two facts shaped the defence. Both the A\* attacker and Cursor eat our
capsule in every game we measured (40 of 40 each). The A\* attacker banks
5.0 of its 7.9 dots a game while our ghosts are scared. Every attempt to
deny the capsule or shorten the scare lost more than it saved, so v2
keeps crowded-stalls' answer: while scared, the sentinel joins the raid.

## §1 Configuration and team entry

The risk weights, carry limits, stand-off timers and the capture search's
range, time budget and depth live at the top of the file. `create_team`
returns a `Raider` and a `Sentinel`, the same pairing as `my_team.py`.

`_NOTES` is the only memory the two agents share: each agent's latest
sonar reading. It is keyed by team colour, so a game against a copy of
ourselves keeps the teams apart, and it is cleared at the start of every
game.

## §2 Map analysis (`Maze`)

Built once at startup, in about 0.03 s on defaultCapture:

- exact maze distances from every square (all-pairs BFS);
- our home squares and the doors on the border;
- `bank`: each square's distance to the nearest door;
- `mouth`: for every square inside a dead end on the enemy side, the
  square the raider must pass again to get out;
- `routes`: one uniform-cost search that prices every goal at once,
  with ghost risk added to the step cost.

## §3 Opponent tracking (`OpponentModel`)

A histogram filter per enemy. Each turn the belief spreads one step, then
keeps only squares that fit everything we know:

- the enemy's side (pacman or ghost);
- that neither of us can see it (so it is more than 5 squares away);
- our own sonar reading;
- **new:** our teammate's reading from its last turn, with one extra
  square of slack for the move the enemy made since.

Squares where a dot just vanished get 9 times the weight. The 40 likeliest
squares are kept.

An enemy is reset to its start square when it dies. v2 detects that from
two signs: it was carrying and turned back into a ghost without banking,
or we last saw it next to one of our ghosts.

## §4 Turn pipeline and role selection

`choose_action` times the turn and wraps it in a guard: if anything
raises, the agent takes a safe-looking step (towards home when it is a
pacman) instead of crashing the game.

Roles follow crowded-stalls. The sentinel defends, but raids when
nobody is invading and it is scared, we are behind, or the game is late
and not won. It also raids while scared for more than 15 moves with a
single invader. The raider defends only in emergencies: two invaders
while the sentinel is away, a lead to protect in the last 24 moves, or a
visible invader within two squares.

## §5 Raider: risk-priced route planning

The raider prices routes with a step cost plus risk near every likely
ghost square (weights 60, 38, 10, 2.8, 0.8 by distance 0 to 4). Dots in
dead ends get extra danger when a ghost could reach the mouth before we
get out. It banks at 3 dots when level or ahead and at 5 when behind, and
earlier when the trip home is short, the game is ending or a visible
ghost is closing in. It leaves through the door where it has the biggest
lead over the ghosts it can see.

When it cycles between two squares and we are not ahead, it either
commits to one target for 8 moves or avoids a blocked target for 20.

## §6 Raider: last-step safety check

If the planned step lands next to a visible ghost and another step does
not, take the other step. This is the same check as crowded-stalls. The
deeper search we tried here is listed in the table above.

## §7 Sentinel: interception and patrol

- **Scared:** shadow the invader from 3 squares, out of reach.
- **Invader in sight:** go to the earliest square on its shortest path to
  its likely goal that we reach first. Its goal is the nearest door once it
  carries 2 dots, otherwise our nearest food.
- **Invader just stepped back out:** cover that door, since it usually
  comes straight back.
- **Dot just eaten:** go to where it vanished.
- **Otherwise:** patrol the door that best covers our food and the
  likeliest entry.

## §8 Sentinel: time-guarded capture search

This section uses the spare think time. When an invader is visible within
7 squares, the sentinel searches our moves against every reply of the
invader. The invader escapes if it crosses back to its side or eats one
of our capsules. The search deepens one round at a time, up to 12 rounds,
so the first capture it proves is the quickest. If it proves one, the
sentinel takes that step. If not, §7 decides.

The search stops at 0.3 s. In practice it finishes in under 0.2 s even
with the range and depth turned up to 99 squares and 60 rounds. A run
with a 0.5 ms budget hit the time guard 41 times in one game and still
finished cleanly.

## §9 Roles

`Raider` and `Sentinel` only set the `guarding` flag.

## Results

RESULTS_PLACEHOLDER

## Rules and timing

- Uses only the agent's own observation and the teammate's notes. It
  never reads or changes the opponents' objects or the game engine.
- The shared notes are a module-level dictionary that our two agents
  write to. The contest runs both agents in one process, and the previous
  main agent shared memory the same way. Flagging it in case the
  organisers' rules say otherwise.
- On Python 3.8: startup about 0.03 s, typical move 1 ms, slowest move
  16 ms. With the capture search's range and depth turned up to 99 squares
  and 60 rounds, the slowest move was 0.18 s, far below the 1 s warning.

## Reproducing

```bash
# full suite on defaultCapture: 13 opponents, 320 games
D=$(python3 -c "print(','.join(['defaultCapture'] * 10))")
python testing/bench.py -a my_team_v2.py -f "$D" -r 0 \
  -o baseline,double_baseline,rusher,turtle,capsule,switcher,approxq,minimax,mcts,astar,camper
# head to head with the current agent
python testing/bench.py -a my_team_v2.py -o git:main -f "$D" -r 0
```
