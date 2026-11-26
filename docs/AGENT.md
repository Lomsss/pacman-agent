# Main agent (my_team.py)

`my_team.py` is a two-agent capture team: a `Raider` that collects food and a
`Sentinel` that guards our side. Both are the same class, `CapturePlayer`; the
only difference is the `guarding` flag, and either agent can raid or defend on
any turn. On the seven opponents that still take points from us on
defaultCapture it scores about 2.5 points a game, and against the
contest-team proxies it scored 2.83 points a game. Read sections 2.3 (roles)
and 2.4 (raid) first: most of the behaviour lives there. The defender's
main tool is a chase game solved once per map (sections 2.1 and 2.8).

## 1. How to run it

```bash
cd pacman-contest/src/contest/
python capture.py -r ../../../my_team.py -b baseline_team
# with team options
python capture.py -r ../../../my_team.py -b baseline_team --redOpts "lookahead=1"
```

`create_team` options:

| Option | Default | Effect |
|---|---|---|
| `prediction` | `"1"` | Track hidden enemies with `OpponentModel`. `0`, `false` or `off` uses only visible positions. |
| `lookahead` | `"0"` | `1`, `true` or `on` adds the one-turn reply forecast (`OpponentModel.replies`) to raid risk and interception. Off by default after a paired ablation (db2c5fd). |
| `first` | `"Raider"` | Class of the first agent (`Raider` or `Sentinel`; unknown names fall back to `Raider`). |
| `second` | `"Sentinel"` | Class of the second agent (unknown names fall back to `Sentinel`). |

## 2. Design

### 2.1 `Maze`: map analysis (built once in `register_initial_state`)

- **Canonical order.** `key` maps each square to itself for red and to its
  180-degree rotation for blue. `order()` sorts by `key`, the heap in
  `routes` breaks ties by `key`, and blue tries moves in `BLUE_STEPS`
  (the mirror of `STEPS`). Every tie therefore breaks the same way for both
  colours. Before this change blue played a differently tuned agent: it
  scored 0.70 points a game against an exact copy of itself.
- **Edges, home, doors.** `edges` lists each square's open neighbours in
  canonical order. `home` is our half. `doors` are home squares with a
  neighbour on the enemy side.
- **Distances.** `rows` holds a BFS distance row per source. On boards up to
  650 open squares every square is a source. On bigger boards only the first
  32 doors are, and `dist` falls back to Manhattan distance between two
  squares that both lack a row. Unreachable is 999.
- **`bank`.** Each square's distance to the nearest door.
- **Dead ends.** `peel(side)` repeatedly removes degree-1 squares on one side
  of the map. Each removed square maps to the first square outside its
  pocket, its mouth. `mouth` covers enemy-side pockets (the raider must pass
  the mouth again to get home). `home_mouth` covers our pockets whose mouth
  is on our side (an invader inside must come back out through it).
- **`routes(origin, legal, risk, home_only, parent)`.** One uniform-cost
  search that prices every goal at once. Step cost is `1 + risk[q]`. It
  stops after 850 expansions. It returns the cost and the first action for
  every reached square, and optionally a `parent` map that `trace` walks
  back into a path.
- **`descent(q, goal)`.** A shortest path built from the distance rows,
  taking the first closer neighbour in canonical order. Gives up after 200
  squares.
- **`chase(squares, target)`.** The squares a chasing ghost may hold after one
  move: from each possible square, every stay-or-step on its own side that
  gets closest to `target`. Ties are all kept (pessimistic). The set is
  capped at the 12 squares closest to the target.
- **`survive(path, ghosts, t, capsules, bank)`.** Walks the path one move at
  a time against ghosts given as (squares, scared timer). It returns `True`
  when the path reaches a capsule (or home, if `bank`), `False` when a ghost
  that is no longer scared at that time can be on our square (checked before
  and after the ghosts move), and `None` if the path ends with us still
  exposed.
- **`contain(capsules)` and `holds(d, i)`.** The defender's chase game,
  solved once at setup by working backwards over every pair of home squares
  (our ghost, one invader), with either side to move. The invader wins by
  stepping home, onto one of our capsules (even with our ghost on it: the
  engine eats the capsule before it checks the catch) or more than `SIGHT`
  (5) squares from our ghost, where we could no longer see it; or by forcing
  such a position. `holds(d, i)` lists the ghost's moves from `d`, staying
  included, after which an invader on `i` can never win: eating it, or a
  square the solution keeps. Capsules are the ones present at the start of
  the game. The solve takes under 0.2 s (jumboCapture, 301 home squares).
  `testing/check_contain.py` re-derives every position from the rules.

### 2.2 `OpponentModel`: tracking

One histogram filter per enemy, started at its spawn square.

- **Visible enemy.** The belief collapses to its square. If it was also
  visible on our previous turn, the step since then is returned as
  `direction`.
- **Hidden enemy.** The belief spreads one step (equal shares to staying and
  to each neighbour). Squares survive only if they are on the side that fits
  the enemy's pacman flag, more than 5 Manhattan squares from both our
  agents (otherwise we would see it), and possible under our own sonar
  reading. If nothing survives (for example after a respawn), every
  compatible square gets equal weight.
- **Eaten food.** For an invader, squares where our food or capsule just
  disappeared get 9 times the weight. Both invaders get the boost, since
  either could be responsible.
- The 40 likeliest squares are kept and normalised. `update` returns the top
  4 as (square, weight) for the planners.
- **`replies`** (only with `lookahead=1`). Forecasts the enemy's next square:
  its 3 nearest goals are weighted by closeness, a step that gains on a goal
  weighs 4.0, no change 1.0, losing 0.35 (reversed for a fleeing ghost,
  scared timer above 1), and a step that repeats the visible motion is
  multiplied by 1.6. Goals in `observe`: doors for an invader carrying 2 or more,
  otherwise our food and capsules; for a ghost, whichever of our agents is
  on the enemy side, otherwise the doors.

Our agents do not share memory. Each keeps its own models.

### 2.3 `choose_action`: turn pipeline and roles

Setup and helpers: `register_initial_state` builds the `Maze`, one
`OpponentModel` per enemy (only with `prediction`), `quota` and the memories
below. `resources` is the set of food and capsules we defend. `observe`
updates the models (or, with `prediction=0`, returns only visible enemies)
and builds the `replies` forecast. `get_maze_distance` keeps the
`CaptureAgent` distance API working on top of `Maze.dist`. `manhattan` is the
plain grid distance.

Each turn: start the timer, return the only legal action if there is one,
record our square in `recent` (last 12), detect missing food or capsules
(`bite` is the nearest one, `bite_age` counts turns since), update the
models, then pick a role. `moves` is `(timeleft + 3) // 4`, our own moves
left (300 at the start).

| Flag | Rule |
|---|---|
| `double_cover` | Two invaders, we are scared for 15 or less, and we are the sentinel, or we are a ghost while our mate is on the enemy side. A raider already across (a pacman) does not count, so it finishes its trip. |
| `emergency` | `double_cover`, or we lead with fewer than 24 moves left. |
| `visible_near` | A visible invader within 2 squares. |
| `assist` | No invaders and (we are scared for more than 8, we trail, or fewer than 150 moves left and we do not lead); or scared for more than 15, whatever is invading. A long-scared ghost can neither eat nor block, and with both enemies on our side their half is empty. |
| defend | `(guarding and not assist) or emergency or visible_near`, and only while we are a ghost. |
| `recall` | Passed to `raid` for a sentinel out raiding when an invader appears and we are scared for less than 5, unless a `sortie` runs. `emergency` also recalls. |
| `sortie` | A frozen board (score, our dots and their dots unchanged for 50 turns while an invader is on our side or our mate is across) is a tie at best. A sentinel that is level or behind with more than 100 moves left then raids for 100 turns; only `emergency` brings it back. It ends early once we lead. |

So the sentinel defends unless `assist` holds, and the raider defends only
in emergencies or when a visible invader is within 2. A pacman never runs
`defend`; under `emergency` or `recall` it heads home instead.
Any action not in `legal` is replaced by `legal[0]`.

### 2.4 `raid`: the attacker

**Risk map.** For each enemy ghost with scared timer 5 or less and each of
its likely squares, every enemy-side square within distance 4 (not a
capsule) gets `weight * (60, 38, 10, 2.8, 0.8)[d]`. These are twice the
original crowded-stalls weights; the raider was dying 3 times a game against
a door-holding guard on defaultCapture. Food inside an enemy dead end gets
`danger` of `weight * min(16, 3 + 2 * depth)` when the ghost could reach the
mouth no more than one move after we get back out. With `lookahead`, forecast
squares add `18 * probability`. Each repeat visit in `recent` adds 0.65.

**When to bank.** `limit` is 5 when level or ahead, 7 when behind, and 99
(no cap) while both enemies are pacmen: their half then has no defender, so
only the trip checks below end a trip. With food carried, `cash` is true if any of these hold:

- what we returned plus what we carry reaches `quota` (half the total dots,
  minus 2);
- `moves <= bank[p] + 8` (the clock is running out);
- `full_load`: `carried >= limit` and the nearest dot is more than 1 away,
  or `carried >= limit + 2`;
- the cheapest door costs 2 or less;
- the nearest dot is at least `bank[p] + 3` away.

**Exit pricing.** While we are a pacman and a ghost with scared timer 3 or
less is visible, each door costs `costs[b] + 3 * max(0, 2 - lead)`, where
`lead` is how many moves sooner we reach it than the nearest such ghost.
If we carry food and the lead at the chosen door is 0 or 1, we
bank now. A pacman that must bank (`cash`, `recall` or no food left) heads
for that door through `safe_step`.

**Target price.** Candidates are all food and capsules reached by `routes`.

```
price(q) = costs[q] + 0.36 * bank[q] + extra(q) - 1.5 * (q == goal)
extra(q) = danger[q] + 12 if within 3 of a taboo square
           - capsule_bonus if q is a capsule
           + 4 if our mate is on the enemy side and more than 1 move closer
```

`capsule_bonus` is 4 when fewer than 5 dots are left or some tracked enemy
has scared timer below 7 (in practice almost always), otherwise 1. The 1.5
bonus keeps the current goal unless another is clearly better.

**Stand-off breaking.** `cycling` means the last five squares alternate
A-B-A-B-A. When cycling, with a goal and the score level or behind:

- if the last 4 goals were all the same (a guard keeps turning us back),
  that goal becomes `taboo` for 20 raid turns (targets within 3 of it pay
  +12; it is a price penalty, not a ban);
- otherwise (the target keeps flipping), `lock` commits to the current goal
  for 8 turns.

When ahead we keep the stand-off, because it runs the clock for us. With the
double risk weights this was the PR #5 change: 2.52 to 2.80 points a game on
defaultCapture.

A longer loop (the last 3 to 20 squares of `trail`, the last 40, repeated
twice with at least 3 distinct squares) means a ghost mirrors us along the
border. When level or behind, empty-handed and with the goal flipping, `lock`
commits to the current goal for its distance plus 2 turns.

**Sortie.** `stall` counts raid turns spent empty-handed, with nothing
eaten, while a visible ghost with scared timer 5 or less is within 6. At
`STALL` (8), and unless recalled, `foray` looks for a one-dot out-and-back
trip (one of the 20 nearest dots, home through one of its 3 nearest doors)
that no enemy can cut off whatever it does: at every away square, at our
arrival time, no enemy could already stand there (a ghost walks its own
side, an invader may use ours; unseen enemies get 2 moves of slack, scared
ghosts count only once their timer runs out). The plan is re-checked every
move and dropped the moment the check fails or we are recalled.

**Hunting.** A visible enemy ghost on its side within `HUNT` (2) steps,
scared for more than `2 * distance + 1` moves, is eaten, unless the clock
is down to `bank[p] + 12` moves. An eaten guard respawns at its start
instead of waking up next to us when the fright ends.

**Choosing.** If a lock is active, keep the locked goal. Otherwise take the
cheapest price, then, while we are a pacman or within 1 of a door, ask
`trips` for a better first stop. If `trips` returns nothing and a visible,
unscared ghost is within 7, `verified` picks the target. A pacman's step
always goes through `safe_step`. A ghost that has spent 10 of its last 12
turns within 2 of a door keeps its new target while the route to it keeps
shortening (`commit`), so a guard's wiggle cannot flip it back from a long
open crossing to the short blocked one.

### 2.5 `trips`: multi-dot trip planner

Plans ordered trips of up to `TRIP_DEPTH` (3) stops from the `TRIP_POOL` (8)
best-priced candidates and returns the first stop of the best one. A trip
scores

```
rate = stops / max(1, moves + TRIP_HOME * home + cost)
```

where `moves` is the first leg's route cost plus the plain distances of later
legs, `cost` sums `extra` over the stops (minus the 1.5 goal bonus on the
first), and `home` is the distance back. `TRIP_HOME` is 0.36, the home weight
in `price`, so a one-stop trip home through the nearest door ranks as
`price` does.

Safety checks replay `survive` along the trip:

- `watch` replays the visible ghosts. It is on when a visible ghost with
  scared timer 5 or less is within 10 (`threat`). A trip whose leg is caught
  is cut.
- `alarm` replays every defender, hidden ones at their likeliest squares. It
  only matters for trips that would carry more than `limit`; such a trip
  scores only if every tracked replay survives. With no belief for some
  hidden defender (`blind`, e.g. `prediction=0`), trips over the limit are
  dropped (neither scored nor extended).
  With both enemies on our side (`limit` 99) it never applies: an invader
  must first cross back before it can defend again, and `watch` still sees it.
- `back` tries the `TRIP_DOORS` (3) nearest doors and uses the first one all
  active replays survive. If none does, the trip does not score. With no
  active replay it uses `bank[q]`.

Work is capped by counters, not the clock, so seeded games replay exactly:
at most `TRIP_EVALS` (600) trip evaluations and `TRIP_STEPS` (60000) replayed
ghost-square moves. A 0.45 s clock check is a backstop only; if it ever
fired, that game would no longer replay exactly. The slowest move measured
was about 0.1 s.

Measured: +0.08 +- 0.09 and +0.24 +- 0.08 on two seed sets of the hard
suite; A\* +0.45 / +0.55, which reversed the A\* dip from verification.

### 2.6 `verified`: route check against a chasing ghost

Used when `trips` finds no trip and a visible ghost with scared timer 0 is
within 7. The
six best-priced targets are tried in price order. For each, the route
(`trace`) is replayed against the visible ghosts with `chase`. If the route
ends still exposed, `escape` tries the six nearest doors with `descent`. The
first target that is not caught wins. If none is safe and we carry food, it
banks along the first door route (cheapest first) that survives. Otherwise
the plain cheapest target stands. A 0.45 s check returns early.

Measured: +0.33 / +0.16 alone on the hard suite; deaths against the BFS
team fell from about 2.7 to 1.2 a game in a 6-game check. Each move uses at
most about 2 ms.

### 2.7 `safe_step`: last-step check

With a visible active ghost (scared timer 3 or less), if the planned step
lands within 1 of it, take another legal step (or stop) that does not. Home
squares and capsules count as safe. Among safe steps, prefer the least
visited in `recent`, then the farthest from the ghost. If no step is safe,
keep the plan.

### 2.8 `defend`: the guard

Routes stay on our side (`routes(..., home_only=True)`, no risk).

1. **Scared shadowing.** While scared and an invader is tracked, stay about
   3 squares from it: score `max(0, 3 - near) * 10 + abs(near - 3)`, then
   prefer squares near the door closest to the nearest invader, then near
   any door.
2. **Dead-end trap.** For each visible invader inside one of our pockets, if
   we reach its `home_mouth` no later than it does, hold the mouth (stop on
   it). Mouths with our capsule below them are skipped, since the capsule
   would scare us there. With two invaders, the raider leaves a mouth to an
   unscared sentinel at home that gets there no later; never the other way
   round. An invader 1 step away is eaten first. Measured +0.10 / +0.19.
3. **Choice.** Pick the invader with the lowest
   `costs[q] + 6 * partner_closer - 2 * min(4, carrying) - 3 * weight`. Eat
   it if visible and adjacent.
4. **Containment.** If that invader is visible and `holds(p, invader)` is
   not empty, play the holding move nearest to it. Food only scores once it
   is brought home, so an invader that can never get home gains nothing,
   and staying as close as the solution allows keeps the pressure on. A
   chase from behind never closes; this is what lost mediumCapture to
   crowded-stalls (a 13-dot trip with our ghost 1 to 3 squares behind).
   Paired gains over the agent without it, on four seed sets: +0.69, +0.25,
   +0.14, +0.33 points a game. Head to head (320 games, 16 maps):
   crowded-stalls 1.51 to 1.85, v2 1.65 to 2.02. defaultCapture is
   unchanged (0 of 144 games changed): there the holds the solver finds
   while keeping the invader in sight are rare.
5. **Seal.** If that invader is visible and carries 2 or more, take a
   square from which it reaches no door strictly before us (`pen`), and
   from which every reply it makes still leaves us a next square that seals
   it. Prefer squares that keep it in sight, then those that leave it the
   fewest squares, then the closest. A ghost trailing a loaded invader
   round a loop in our half never closes; this lost crowdedCapture by up to
   40. Capsules are not exits in `pen`, so a sealed invader can still eat
   our capsule (see "Tried and dropped").
6. **Interception.** Otherwise assume its goal is the nearest door
   when it carries 2 or more, else our nearest food or capsule. With
   `lookahead`, the goal among these that best fits the forecast replies
   is used instead of the nearest. Go to the square on its shortest
   path to that goal, nearest to the invader, that we reach no later than it.
7. **Door re-cover.** With no invaders and not scared: if an enemy was a
   pacman on one of our doors on our previous turn and is now visible one
   step from that door, go back to that door.
8. **Bite chase.** With invaders, go to the last eaten square until 6 turns
   after it vanished (`bite_age <= 6`).
9. **Patrol.** Choose the door minimising mean distance to the 4 nearest
   defended items, plus `0.8 *` the smallest `distance + 4 * (1 - w)` over
   enemy estimates on their side, plus `0.1 *` our route cost, plus `0.25 *`
   mean distance to all doors.

## 3. Constants

| Name / place | Value | Meaning |
|---|---|---|
| `STEPS`, `BLUE_STEPS` | E W N S / W E S N | Move order per colour |
| `TRIP_POOL` | 8 | Targets a trip may draw from |
| `TRIP_DEPTH` | 3 | Stops per trip |
| `TRIP_DOORS` | 3 | Exits tried per trip |
| `TRIP_EVALS` | 600 | Trip evaluations per move |
| `TRIP_STEPS` | 60000 | Replayed ghost-square moves per move |
| `TRIP_HOME` | 0.36 | Weight of the return leg in a trip |
| `INF` | `float("inf")` | Unreached cost |
| `Maze`: BFS cut-off | 650 squares, 32 doors | Above this, rows only from doors |
| `routes` cap | 850 expansions | Search bound |
| `chase` cap | 12 squares | Ghost set size |
| `descent` cap | 200 squares | Path length bound |
| Tracking | 5 sight, x9 bite, top 40, 4 returned | `OpponentModel.update` |
| Replies | 3 goals, 4.0 / 1.0 / 0.35, x1.6, flee if scared > 1 | `OpponentModel.replies` |
| Unreachable | 999 | `dist`, `bank` |
| `SIGHT` | 5 | Engine sight range; `contain` counts an invader beyond it as escaped |
| `recent`, `goal_hist` | 12, 4 | Memory lengths |
| `quota` | total dots / 2 - 2 | Bank everything at this point |
| Roles | 24, 2, 8, 150, 15, 5 | `emergency`, `visible_near`, `assist`, `recall` |
| Frozen board | 50 turns, raid for 100, more than 100 moves left | `sortie` |
| Risk weights | 60, 38, 10, 2.8, 0.8 | Ghost at distance 0..4; ghosts scared > 5 ignored |
| Dead-end danger | slack <= 1, `min(16, 3 + 2d)` | Food in enemy pockets |
| Forecast risk | 18 | Per unit reply probability |
| Revisit cost | 0.65 | Per repeat in `recent` |
| `limit` | 5 / 7 / 99 | Carry limit when level or ahead / behind / both enemies are pacmen |
| Cash rules | +8, 2, +3, `limit + 2` | Clock, door cost, far food, full load |
| Exit pricing | ghosts scared <= 3, `3 * max(0, 2 - lead)`, window 0..1 | Door choice and early bank |
| `capsule_bonus` | 4 / 1 | Fewer than 5 dots or an enemy scared < 7 |
| Price | 0.36 home, 1.5 goal, +4 mate, +12 taboo (radius 3) | `price`, `extra` |
| Stand-off | taboo 20, lock 8; loops of 3-20 in a 40-square `trail`, lock distance + 2; `commit` after 10 of 12 turns within 2 of a door | Raid turns |
| `STALL` | 8 | Stalled turns before a `foray` |
| `foray` | 20 dots, 3 doors, 2 moves slack for unseen enemies | Uncatchable one-dot trip |
| `HUNT` | 2, timer > 2d + 1, clock > `bank[p] + 12` | Eat a scared guard |
| Seal | carry >= 2, two-ply | `defend` step 5, `pen` |
| Trip threat | scared <= 5 within 10 | Turns on `watch` |
| Trip gate | pacman or `bank[p] <= 1` | When `trips` runs |
| Verification | unscared within 7, 6 targets, 6 doors | `verified` |
| Clock backstop | 0.45 s | `trips`, `verified` |
| `safe_step` | slack > 1, home/capsule = 8 | Last-step check |
| Shadow | 3 squares | Scared guard distance |
| Interception | 6, 2 x min(4, carrying), 3, carry >= 2 | Priority and invader goal |
| Bite chase | 6 turns | `bite_age` |
| Patrol | 4 items, 0.8, 4, 0.1, 0.25 | `coverage` |

## 4. Rules and timing

- All live inputs come from the agent's own observation: its state, visible
  positions, noisy sonar, food and capsule grids, score and time left. It
  never reads or changes the opponents' objects or the engine.
- No threads, no files, no shared module state between our two agents.
- Deterministic: ties follow the canonical order, and search is capped by
  work counters, so a seeded game against a deterministic opponent replays
  move for move (unless a 0.45 s clock check fires).
- Time: measured on all 16 test maps in both colours, 4 games at a time:
  slowest move 70 ms, setup at most 0.2 s (jumboCapture), at most 1.3 s of
  thinking per game for both agents together. The engine's limits are 15 s
  for setup, a warning for a move over 1 s (the third warning loses), 3 s
  for an instant forfeit and 900 s per agent per game. The 0.45 s clock
  checks are a backstop. Setup is the BFS distance table and the
  containment solve.
- Python: the file uses only the Python 3.8 grammar and library. Played on
  3.9.6 and 3.12. Not yet run on the UPF cluster.

## 5. Results

Points are 3 per win and 1 per tie, per game. The "hard suite" is the seven
opponents that do not lose every game on defaultCapture: `astar`, `bfs`,
`mdp`, `switcher`, the PR #5 agent, crowded-stalls and Cursor.

### Lineage

| Commit | Change | Measured gain |
|---|---|---|
| e74870e | crowded-stalls replaces the previous `ContestAgent` | Head to head 104-12-24; suite 2.12 to 2.62 (40 random maps); 59-1-0 on defaultCapture |
| dc189ef / 7655999 (PR #5) | Stand-off breaking, ghost risk x2 | defaultCapture, 13 opponents, 320 games: 2.52 to 2.80. Cursor 1.25 to 2.35, A\* 1.95 to 2.25, capsule 2.25 to 3.00. Other maps flat (2.59 to 2.58). x1.5 and x3 scored less. |
| 0b8e9be | Colour-symmetric tie-breaks | Hard suite, 420 games: blue 2.15 to 2.33 (red 2.57 to 2.44, code unchanged, noise). Blue vs exact copy 0.70 to 1.23; blue vs A\* 1.57 to 2.73. |
| b655d2a | Route verification + dead-end trap | Paired, hard suite: +0.41 / +0.24 (verification alone +0.33 / +0.16, trap alone +0.10 / +0.19). Full suite +0.02 +- 0.06. A\* about -0.17 +- 0.13. |
| 3188c01 | Multi-dot trips | +0.08 +- 0.09 / +0.24 +- 0.08; A\* +0.45 / +0.55; full suite +0.06 +- 0.05 |
| PR #16 | No carry cap while both enemies are pacmen | PR #15 suite against the PR #15 agent, paired: rivals (crowded-stalls, v2; 240 games per seed set) +0.09 / +0.00 / +0.04 / +0.16 on four seed sets; win rate vs crowded-stalls 76.9% to 78.8%, v2 79.8% to 82.1% (mean of four sets). 12 other opponents (1,440 games) +0.02 +- 0.02, none lower; Out of Scope proxy +0.10. Head to head vs the PR #15 agent level (50-4-66 either way, as for a mirror). defaultCapture (360 games, 2 seed sets) -0.01 / +0.00. Earlier screen: +0.02 / +0.04 / +0.04 on three 1,298-game sets (11 opponents, 59 maps). |
| PR #15 | Seal against looping loaded invaders, sortie and loop lock against stand-offs, frozen-board sentinel raid, hunting scared guards, carry limit 5 / 7, assist under 150 moves, exit window 0..1 | Four ideas built and screened in parallel, each about +0.1 alone; together they add up. vs crowded-stalls and v2, 120 games each per seed set (30 fixed + 30 random maps, both colours), win rate against the PR #14 agent on three held-out seed sets: crowded-stalls 75.8 / 67.5 / 70.8% to 75.8 / 84.2 / 85.8% (mean 81.9%), v2 67.5 / 66.7 / 74.2% to 75.8 / 83.3 / 81.7% (mean 80.3%); training set 82.5% / 80.8%. Head to head vs PR #14 78-4-38 (120 games). mirror-attack 64% to 85%; astar, approxq, mm up; baseline, alma, ghostclaniol level. defaultCapture (40 games per opponent, 2 seed sets): bfs, Cursor and mirror-attack up by 0.65 to 1.1 points, v2 +0.40 / +0.20, crowded-stalls +0.15 / -0.23, the PR #5 agent -0.30 / +0.30, mdp -0.18 / -0.10. |
| PR #14 | Long-scared guard raids even with invaders on our side; scared shadowing leans to the invader's exit | Paired, 120 games per opponent on 2 seed sets (30 fixed + 30 random maps, both colours): crowded-stalls +0.07 +- 0.08 and +0.24 +- 0.10 (win rate 63.8% to 69.2%), v2 +0.09 +- 0.09 and +0.13 +- 0.07 (61.3% to 64.2%), head to head vs the PR #13 agent +0.07 / +0.09, mirror-attack -0.07 / +0.00. baseline, mm, alma, ghostclaniol, approxq and astar unchanged (at most +0.01, 240 games each). The raid change carries the gain; the shadow tie-break alone was +0.00 to +0.03. |
| PR #13 | Defender chase solver (`contain`, `holds`) | +0.69 (300 games vs crowded-stalls, 6 maps), +0.25 and +0.14 (8 rivals, 16 maps, 2 seed sets), +0.33 (320 fresh games vs crowded-stalls, 16 maps). Head to head vs crowded-stalls 1.51 to 1.85, vs v2 1.65 to 2.02. defaultCapture unchanged. |

### Latest numbers

- Hard suite, PR #5 agent to this agent: 1.99 to 2.48 and 2.10 to 2.59 on
  two seed sets (about +0.5 a game). The other ten opponents are unchanged.
- Wider reference suite (10 opponents, 16 maps, 2 seed sets, 640 games):
  2.40 points a game.
- Round robin before the chase solver (`testing/tournament.py`, 23 agents,
  16 maps, both colours, maps weighted equally, 8,096 games): this agent
  2.54, v2 2.49, crowded-stalls 2.44, Cursor 2.02, every other agent 1.93
  or less.

- PR #15 agent, three held-out seed sets (360 games per rival): 81.9% wins
  vs crowded-stalls and 80.3% vs v2; per set 75.8 to 85.8%. On
  defaultCapture alone: crowded-stalls 60.0 / 67.5% and v2 67.5 / 65.0%
  (40 games each), so the contest map is still the hardest.
- Against the PR #14 agent on 240 games each (both seed sets above):
  crowded-stalls 69.2% wins, v2 64.2%, mirror-attack 64.2%, baseline 99.2%,
  mm 88.8%, alma 98.8%, ghostclaniol 91.7%, approxq 92.1%, astar 81.7%.
  Food lost per game to crowded-stalls and v2 is about 14 either way.

### Contest-team study

Two real contest replays were reverse-engineered into proxy teams:
match_150085 (GhostClaniol vs M&M) and match_150100 (M&M vs Alma Team). The
M&M proxy reproduces 599 of 600 recorded moves in each game; the Alma and
GhostClaniol proxies 97%. All three are deterministic BFS, reflex or shallow
max-min agents, and none predicts our moves.

Our five best agents each played these three proxies and an earlier, rougher
M&M proxy (since removed): 28 games per pairing on 14 maps. This
agent scored best overall: 2.83 points a game (105-2-5 over 112 games), and
31-1-0 on defaultCapture.

### Head to head

| Match | Games | W-T-L | Points |
|---|---|---|---|
| crowded-stalls vs previous `ContestAgent` | 140 | 104-12-24 | 2.31 |
| crowded-stalls vs previous `ContestAgent` (defaultCapture) | 60 | 59-1-0 | 2.97 |
| PR #5 agent vs v2 (defaultCapture) | 120 | 59-8-53 | 1.54 |
| 0b8e9be agent as blue vs an exact copy of itself (was 0.70 before the tie-break fix) | not recorded | not recorded | 1.23 (even is 1.5) |
| This agent vs crowded-stalls (16 maps, 10 seeds, both colours) | 320 | 191-18-111 | 1.85 (1.51 before the chase solver) |
| This agent vs v2 (16 maps, 10 seeds, both colours) | 320 | 208-23-89 | 2.02 (1.65 before the chase solver) |

## 6. Tried and dropped

| Idea | Result | Why it failed |
|---|---|---|
| Runtime opponent identification | Not built | An adversarial review cut it. Nearly every field opponent shares the behaviours a label would detect, so the default play already handles them; a label only adds false-positive risk. Its main consumer, the reply forecast, is off. Agents also persist across games and both see every enemy move, which made the evidence easy to miscount. |
| Danger from every square a visible ghost reaches first | -0.87 | Walls off half the map; the raider is too timid |
| Sentinel hangs back near our capsule | +0.03, but -0.25 vs A\* | Lets the A\* attacker through |
| Guard our capsule during interception | A\* 1.95 to 1.57 | Same: lets the attacker through |
| Double defence to protect a late lead | -0.09 | Gives up points in close games |
| Wider verification (all targets, all doors, 10 squares) | -0.04 / +0.09 | More of the same check does not pay |
| Defender search against the field's attacker pattern | -0.03 / -0.02 alone; -0.41 / -0.39 with trips | Wins vs A\* and BFS, loses mirror matches once the raider is away on long trips |
| Risk weights x1.5 or x3 | Lower than x2 | x2 kept |
| Deep escape search (both ghosts, up to 8 rounds) | 1.98 vs 2.29 (screening) | Planning for a perfect guard makes the raider too careful |
| Short escape search (2 rounds) | Cursor 2.40 to 2.55, A\* 2.17 to 1.70 | Net loss |
| Scared ghost walks into the invader to respawn | 2.00 / 1.95 vs 2.31 | We bank 1.4 dots a game less; the scared sentinel stops counter-raiding |
| Teammate sonar fusion (v2) | Tracking error 5.03 to 4.54 and 5.58 to 4.19 squares; no points change | Not adopted |
| Forced-capture search for the sentinel (v2) | 2.31 vs 2.29 | Rarely fires; a lone invader can usually step back |
| v2 as a whole | 2.77 vs 2.75 suite; 53-8-59 head to head | Level, not better |
| Feast (carry more while enemy ghosts are scared) | +0.01 +- 0.03; defaultCapture -0.16 +- 0.10 | Loses on the contest map |
| Capsule break-out from stand-offs | +0.02 +- 0.03; defaultCapture -0.06 +- 0.07 | No gain |
| Map-scaled carry limit | +0.01 +- 0.02; defaultCapture unchanged | No gain |
| Hunt cornered scared ghosts | +0.01 +- 0.02 | No gain |
| Loss fix: keeper | +0.00 +- 0.04 | No gain (defaultCapture hard suite) |
| Loss fix: escape | -0.08 | Lower; not kept |
| Loss fix: walk-in | -0.09 | Lower; not kept |
| Loss fix: clock | -0.03 | Lower; not kept |
| Loss fix: scare | -0.06 | Lower; not kept |
| Reset tracking to the spawn after a kill, plus a bigger load when both enemies are deep in our half | +0.07 / +0.10 on two 300-game sets, then -0.03 +- 0.02 replayed on 703 round-robin games | Noise |
| Pin a hidden invader to a vanished dot; capsule exits; scared shadow on the exit path | -0.05 to +0.05, sign flips between seed sets | Noise |
| Double cover near the enemy's quota | -0.11; mirror-attack -0.59 | Gives up too much attack |
| Hold the nearest door we reach first when trailing a loaded invader | +0.07 +- 0.10 vs crowded-stalls; bloxCapture -0.60 / -0.96 | The raider eats freely while we hold a door it does not need |
| Sentinel crosses in mid-game when our raider is held at the line (pincer) | +0.11 on training, -0.16 to -0.30 on two held-out sets | Changes 40-55 of 120 games; leaving home costs as much as the second attacker gains |
| Commit to a target the raider reaches before the guard (outrun lock) | +0.09 / +0.24 training, -0.16 / -0.23 held-out | Far more aggressive; fastCapture +1.0, office and distant collapse |
| Raider blocks the exit a chased invader heads for (strict and loose) | -0.03 / +0.03; -0.01 / +0.03 | Harmless but rarely decisive |
| Seal treats our capsules as exits | -0.04 vs both rivals on 8 comparisons | Fixes a capsule leak vs the baseline (1 game in 120) but gives up seals that hold vs the rivals |
| Counter-raid: both agents raid when two invaders come (always, only while they carry 4 or less, only when not behind) | -0.15 to -0.27 | Leaves our half open; the raider's points are worth more than a second defender |
| Guard-lock fixes: release a long hold when the other invader carries 5 more, deprioritise an empty-handed invader, raider covers a loaded second invader | -0.01 to +0.01 | Rarely fires |
| Bait or pincer against a two-defender wall while behind (target spreading, risk x0.25 or x0) | +0.00 on 2,600 games; x0 worse vs a wall | Behind-mode already sends both agents |
| Guard raids while all enemy ghosts are scared; both raid the first 30 / 60 moves | -0.01 to +0.01; -0.02 to +0.01 | Neutral |
| Extra carry (+4) with one invader | +0.03 / -0.04 / +0.02 over carry +12 with two | Sign flips |
| Hunt reach 3 or 4; capsule hold; capsule break-out | Within noise or negative | Chasing fleeing ghosts wastes attack time |
| Carry limit 4 / 6, assist under 290 moves | +0.07 / +0.12; noisy (36-48 games changed) | 5 / 7 and 150 kept |
| Raider comes back to defend against a loaded invader (carry >= 5 within 8; with or without leaving a raid; with or without splitting exits) | -0.17 to -0.30 vs crowded-stalls, v2 and mirror-attack | A held, loaded invader keeps the raider home for hundreds of moves; any defending by the raider costs more attack than it saves |
| Both ghosts squeeze a lone invader (joint step minimising the squares it reaches first) | -0.21 vs crowded-stalls, -0.27 head to head | Same: the raider's attack is worth more |
| Wait at the invader's likeliest goal instead of trailing it | -0.44 to -0.52 vs every rival | Trailing keeps pressure on the invader |
| Walk into a capsule-free dead end to eat a trapped invader | -0.03 to +0.00 | Works in replays, but a trapped invader also ties up one of theirs |
| Re-solve the chase game after a capsule is eaten | -0.03 to +0.03 | Rarely changes a hold |
| Patrol weighted toward our capsules | +0.01 +- 0.06 (500 games vs crowded-stalls) | Near-border capsules are lost to the first approach anyway |
| Stall breaker (shun food near a ghost that blocked us for 20 moves) | +0.09 / -0.01 on two seed sets | Breaks 0-0 deadlocks, but the opened game goes either way |
| Capsule break-out while cashing, bank before a fright ends | +0.12 / -0.18; +0.04 / -0.05 | Sign flips between opponents |
| Raider keeps raiding against two invaders; idle guard joins a feast | Within +-0.02 of PR #14 | Rarely fires |
| Chase solver without the sight rule | +0.13 to +0.66, but defaultCapture -1.3 vs crowded-stalls and v2 | Holds from chokepoints out of sight, where the solution can no longer be followed |
| Chase solver, holding only from squares within 4 of the invader | defaultCapture fixed vs crowded-stalls and v2, -1.0 vs Cursor and mirror-attack | The plan could still need an out-of-sight square later; the sight rule inside the solver replaced it |

The four variants from the contest-team data were each paired over 640 games
(10 opponents, 16 maps, 2 seed sets; reference 2.40). The open weakness
from the v2 study (measured on the PR #5 agent and v2): the A\* attacker and
Cursor ate our capsule in 40 of 40 games each, and the A\* attacker banked
5.0 of its 7.9 dots a game during the scare. None of the counters tried
(capsule guard, scare reset, two escape searches) paid.

## 7. Other agents

Only this agent lives on `main`. Every other team has its own branch named
`agent/<name>`:

| Branch | Agent |
|---|---|
| `agent/v2` | the second-generation team (formerly `my_team_v2.py`) |
| `agent/contest-agent` | the earlier `ContestAgent` team |
| `agent/abfull`, `agent/approxq`, `agent/astar`, `agent/bfs`, `agent/camper`, `agent/capsule`, `agent/double-baseline`, `agent/mcts`, `agent/mdp`, `agent/minimax`, `agent/mirror-attack`, `agent/rusher`, `agent/switcher`, `agent/turtle` | sparring opponents (styles in `testing/README.md`) |
| `agent/cursor` | the Cursor team (Cursor agent V1.2) |
| `agent/crowded-stalls` | the crowded-stalls team, which this agent grew from |
| `agent/mm`, `agent/alma`, `agent/ghostclaniol` | contest-team proxies |

On every agent branch `my_team.py` is that agent, self-contained, with a
`docs/AGENT.md` describing it. `testing/bench.py -o astar` plays the branch
`agent/astar` (local or `origin/`); `-o git:<branch>` plays any branch,
for example `-o git:agent/v2` or `-o git:7655999` (the PR #5 agent).

## 8. Testing

See `testing/README.md`. In short:

- `bench.py --game-seed` seeds every game, so two versions play the same
  games, and against deterministic opponents a seeded game replays move for
  move. `paired.py` compares two runs game by game.
- Test on defaultCapture first (the contest map), with about 40 games per
  opponent; other maps are a robustness check.
- Keep rule: a change is kept only if it gains on two independent seed sets
  of the hard suite and a run against the full opponent list shows no other
  loss. Treat differences under about 0.1 points a game as noise.
- `match_stats.py` and `why.py` explain why a game was won or lost.
- `check_contain.py` re-derives the defender's solved chase game from the
  rules on chosen maps (`RANDOM<n>` works too). Run it after changing
  `Maze.contain`.
