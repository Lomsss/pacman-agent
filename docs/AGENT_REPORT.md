# How our agents play

This report explains every technique in `my_team.py` and how the
techniques work together. The section numbers (§1 to §11) match the
`§` banners in the source, so you can jump from a heading here to the
code that implements it. Methods sit in the file in roughly this
order, but a few helpers live next to their callers, so a section can
appear in more than one place (for example, §6.2 sits after §8).

Both players are the same class, `ContestAgent`. One starts with the
`offense` role and the other with `defense`. Roles only set defaults:
on any turn either agent can attack, raid, patrol or hunt.

---

## §1 Configuration and team entry

| Constant | Value | Meaning |
|---|---|---|
| `_SIGHT` | 5 | Manhattan range at which the game reveals an enemy's exact position |
| `_NOISE` | 6 | Largest error of a sonar reading (the game adds noise of −6 to +6) |
| `_MIN_PROB` | 0.0008 | Belief cells below this probability are dropped |
| `_HORIZON` | 160 | Longest path any search will consider |
| `_INF` | 99 | "Never reachable" in safety maps |
| `_SCARED_RAID` | 12 | A scared ghost with more moves left than this goes raiding instead of shadowing |
| `_SEARCH_TIME` | 0.25 s | Time budget for the tactical look-ahead (the contest allows 1 s per move) |
| `_SEARCH_RANGE` | 6 | The look-ahead only runs when a visible ghost is this close |
| `_SHARE` | dict | Memory shared by the two teammates (see §4.6) |

`SEARCH_TIME` and `SEARCH_RANGE` can be overridden with environment
variables for testing. `PACMAN_DEBUG=1` prints per-agent stats at the
end of a game: deaths, kills, food returned and move times.

`create_team` returns one `ContestAgent` with the offense role and one
with the defense role.

## §2 Map analysis (`_Map`)

This runs once per game, in `register_initial_state`. Random maps
change every game, so nothing is cached between games. It builds:

- **Graph.** Every open square and its neighbours. All later searches are
  breadth-first searches over this graph.
- **Home / enemy split.** `on_home` returns true for our half. Red's half
  is `x < width/2`; blue's half is the rest.
- **`dist_home`**: for every square, the number of steps to reach our side
  (0 on our side). A multi-source BFS from all home squares. Used for
  return trips, carry decisions and estimating how fast an enemy can
  enter.
- **`dist_exit`**: the same thing, but for an invader getting back to its
  own side.
- **`border` / `border_set`**: our squares that touch the enemy side,
  i.e. the doors.
- **`tunnel`**: how deep a square sits inside a corridor. It is the
  distance to the nearest junction (3 or more exits) or to our side. 0
  means open ground; a high value is a dead end where a ghost can trap
  us. This is the main trap detector for the attacker.

## §3 Agent lifecycle and the per-turn pipeline

### §3.1 Setup and teardown
`register_initial_state` resets all per-game state. It builds the map,
seeds a belief for each enemy at its spawn square, and records our
starting food and capsules. The lower-index teammate also clears the
shared memory. `food_to_win` is counted from the food on the map. The
engine's own `TOTAL_FOOD` constant is wrong when `capture.py` runs as a
script, so it isn't used. `final` prints debug stats when
`PACMAN_DEBUG=1`.

### §3.2 The safety wrapper (`choose_action`)
`choose_action` wraps the real decision in `try/except` and checks that
the result is a legal action. If anything goes wrong, `_fallback` steps
toward home, so a bug can never crash or forfeit a game. It also times
every move for the debug stats.

### §3.3 The turn pipeline (`_choose`)
Every turn runs these steps in order:

1. **Read ourselves**: position, scared timer, carried food. Count a death
   if we jumped back to spawn.
2. **Track enemies** (§4). Update the beliefs, then turn them into
   `reports`.
3. **Pick a mode** (§5): `hunt`, `patrol`, `raid` or `attack`. A `flee`
   branch exists but `_mode` no longer returns it.
4. **Run the mode's planner**:

   | Mode | Planner |
   |---|---|
   | `attack` | `_attack` (§6) |
   | `raid` | `_attack(raid=True)` (§6) |
   | `hunt` | `_hunt` (§9) |
   | `patrol` | `_patrol` (§9) |
   | `flee` | `_flee` (§9) |

5. **Anti-stall override** (§8.2). If the last 8 squares show a two-square
   wobble, or we sat still on their side, `_barge` commits to a
   direction instead.
6. **Border-pacing override** (§8.3). If we are attacking with nothing
   carried and the plan keeps us on our side, `_cross` forces a crossing.
7. **Tactical veto** (§7). In `attack` or `raid`, if a visible ghost is
   close, the alpha-beta search may replace the move with a safer one.
8. **Bookkeeping.** Record our position history and the food and capsules
   we are defending, for next turn's comparisons.

## §4 Opponent tracking

Enemies are only visible within 5 squares of us or our teammate.
Otherwise each agent gets a noisy distance (true distance ±6) to every
enemy. The agent keeps a probability map (a **grid Bayes filter**) for
each enemy.

### §4.1 Prediction (`_motion`)
Each enemy move spreads every cell's probability evenly over its
neighbours and itself, the classic random-walk motion model.
`_moves_between` uses the fixed turn order (agents 0, 1, 2, 3, …) to
count exactly how many moves each enemy has made since our last update.
This is usually 1, but more after we respawn.

### §4.2 Correction (`_observe`, `_sensor_ok`)
Cells are kept only if they agree with all of these:

- **The sonar ring.** The cell's Manhattan distance to us must be within
  ±6 of the reading.
- **Negative sight.** The enemy is not within 5 of us or our teammate,
  because if it were we would see it.
- **Pacman state.** If the game says the enemy is a pacman, it must be on
  our side; if it is a ghost, it must be on its own side.

If nothing survives, `_reseed` rebuilds the belief from every square that
satisfies the constraints.

### §4.3 Pruning (`_trim`)
Cells below `_MIN_PROB` are dropped and the rest renormalised. This
keeps the belief local and the computations cheap.

### §4.4 Hard evidence
- **Exact sight** replaces the belief with a single square.
- **Eaten food or capsules** (`_snap_eaten`). A dot that vanished from
  our side is exactly where an invader just stood. Each missing dot is
  matched to the invader whose sonar and belief fit it best, at most one
  dot per invader, and that invader's belief collapses to that square.
  The latest bite is also kept in `last_bite` for the hunters.
- **Kills.** An enemy that was a pacman carrying food, and is now a ghost
  without having scored, was eaten. Its belief resets to its spawn
  square.

### §4.5 Teammate sonar fusion (`_fuse`)
Each agent publishes its own sonar readings in `_SHARE["sonar"]`. When
the teammate's reading is at most 3 moves old, our belief is
intersected with the teammate's ring as well. Two rings around two
different squares pin an enemy down far more tightly than one.
`_enemy_moved` adds one step of tolerance if the enemy moved between
the two readings. If the intersection is empty, the fusion is skipped.

### §4.6 Shared team memory (`_SHARE`)
This is a module-level dict. Both teammates are created from the same
loaded module, so they share it.

| Key | Contents |
|---|---|
| `sonar` | Each agent's last readings and position (§4.5) |
| `cover` | The door each agent last decided to guard, so the other covers a different one (§9.3) |
| `hunt` | The last invader position each agent targeted. Written but not currently read; it is ready for future coordination |

### §4.7 Reports (`_reports`)
Every turn, each enemy's belief is summarised into a report with these
fields:

| Field | Meaning |
|---|---|
| `visible` | The exact square, if we can see the enemy |
| `pos` | The exact square, or the belief if it is a single certain cell |
| `map_pos` | The most likely square |
| `peak`, `eff` | How concentrated the belief is (`eff` is the effective number of cells) |
| `diffuse` | True when the belief is too spread out to treat as a wall |
| `lower` | A lower bound on the enemy's distance from us, from sight and sonar |
| state fields | Pacman/ghost, scared timer, carried food, spawn square |

All planners work from reports, never from raw beliefs.

## §5 Role selection (`_mode`)

The decision follows a fixed priority order:

1. **Scared ghost at home.**
   - No invader: `patrol`.
   - More than `_SCARED_RAID` moves of scare left and more than 120
     moves of game left: `attack`. A scared ghost can't stop the
     invader, so it scores on their side instead.
   - Otherwise: `hunt`, which shadows the invader from 2 squares until
     the timer runs out.
2. **Invaders present.**
   - `hunt` if we are closing out a lead (below) or `_should_hunt` says so.
   - Otherwise `attack`.
3. **Closing out a lead** with no invaders: `patrol`. Closing out means
   we are ahead with little time left: more than 0 points with under 170
   moves left, 4 or more with under 300, or 8 or more with under 480.
4. **Defense role**: `raid` only if `_should_raid` says so, otherwise
   `patrol`.
5. **Offense role**: `attack`.

`_should_hunt` works like this:
- The defense role always hunts.
- The offense role hunts if it is at least 2 steps closer to the invader
  than its teammate. It also hunts if an invader carries 4 or more dots
  and we are no farther than the teammate, unless we are about to bank 4
  or more dots ourselves.

`_should_raid` lets the defender cross only when all enemy ghosts are
scared for more than 10 more moves, there are no invaders, and the game
is not nearly over. Raiding the rest of the time was tested and lost
points to double-attack teams.

## §6 Offense planner (`_attack`)

### §6.1 When to go home (carry limit)
The carry limit depends on the situation:

| Situation | Limit |
|---|---|
| Enemy side has no ghost | 10 |
| Raid | 3 |
| Feast (all ghosts scared for more than 8 moves) | 12 |
| Losing late | 8 |
| Under 180 moves left | 2 |
| Otherwise | 3 |

We also go home early when any of these is true:
- returning now would win the game (`returned + carrying >= food_to_win`)
- the clock is about to run out
- the scare is ending before we can get back
- we are 2 steps from home with 2 or more dots
- a ghost we can see clearly is as close to us as home is

### §6.2 Safety maps (`_safety`, `_threat_cells`, `_enter`, `_bfs`)
The core idea is a **safety map**. For every enemy-side square it holds
the latest step at which we can stand there before a ghost could reach
it: the ghost's maze distance minus one, plus its scared time.

- **Ghost cells.** A seen ghost uses its exact cell.
- **Belief cells.** For an unseen ghost, only its likely cells count, or
  just its most likely cell when the cloud is wide.
- **Slack.** Unseen ghosts get a few steps of extra allowance, so a vague
  cloud doesn't freeze the attacker.

`_bfs` is then a breadth-first search that may only enter a square if
it arrives before that deadline. The result is the set of food reachable
safely, with paths. Two maps are built: a `loose` one when carrying
nothing, and a `strict` one when carrying food.

### §6.3 Choosing a target
Each reachable dot is scored by:
- **Base cost**: path length plus 1.15 × the distance from that dot back
  home. Round trips matter, not just reaching the dot.
- **Tunnel limit.** When an unseen ghost is around, dots deeper in a dead
  end than half the sonar gap are skipped.
- **Escape check** (`_can_escape`). With nothing carried, a dot only
  counts if a safe path home still exists after eating it.
- **Teammate spread.** The non-primary agent gets +4 for dots its
  teammate is closer to, so the two don't chase the same dot.
- **Defender awareness.** +7 for dots whose nearest exit has a known
  defender next to it, and a small bonus for dots far from defenders.

Two other kinds of target compete with food:
- **Capsules**, when no dot is safe or a ghost is within 10 squares.
- **Scared ghosts**, which we chase down when we can reach them before
  their timer ends. Eating one sends it back to spawn for the rest of
  our feast.

### §6.4 Going home
`_travel_home` tries the strict safety map, then the loose one. If
neither has a path, `_hold_home` takes the step that keeps us closest
to home without moving next to a ghost.

## §7 Tactical look-ahead (alpha-beta veto)

This is where the spare thinking time goes (§3.3 step 7). It runs when
a ghost we can see is within `_SEARCH_RANGE` squares and we are on
their side or at the door.

- **The model**: our square, the visible ghosts, the dots and capsules
  eaten along the way, what we carry and what we have banked. Ghosts
  move after us and must stay on their side. Eating a capsule removes the
  ghosts from the model; reaching home banks what we carry.
- **The search** is minimax with alpha-beta pruning. Our moves maximise
  and the ghosts' joint moves minimise; each ghost tries its 4 moves
  closest to us first. Iterative deepening adds one round at a time until
  `_SEARCH_TIME` is spent, so a quiet position costs nothing and a fight
  goes as deep as the clock allows.
- **The evaluation** (`_tac_value`):
  - Points: 12 per banked dot, 3 per carried dot.
  - Penalties: distance home while carrying, distance to the next dot,
    being near a ghost (400 when adjacent, 30 at distance 2), and
    standing in a corridor deeper than half the ghost's distance.
  - Being caught scores −1000.
- **Veto, not steer.** We keep the planned move from §6 unless the search
  proves it walks into a forced catch and another move avoids one. A
  version that let the search choose every move made the attacker timid:
  ties rose from 16% to 27% and it scored fewer points.

## §8 Offense fallbacks, anti-stall and border crossing

### §8.1 When the safe plan finds nothing
- **`_commit`**. Take the food anyway and refuse only the squares a ghost
  could step onto next turn. This prefers shallow dots and grabs a
  capsule when stuck. If we carry food, it heads home with no safety
  limit.
- **`_least_danger_step`**. The last resort: the step with the least
  danger that still heads toward food (or home when carrying).

### §8.2 Anti-stall (`_stalled`, `_barge`, `_blocked`)
Two patterns count as stalling:
- two squares alternating over the last 8 moves;
- sitting still on their side.

Either way, `_barge` picks a direction by pure progress: toward food or
home on their side, toward an invader or the border on ours. It refuses
only a square with a ghost on it. After 5 stalled turns in a row, even
that refusal is dropped. `_blocked` stops path-followers from stepping
straight back into a wobble.

### §8.3 Border crossing (`_cross`)
When the planner would keep an empty-handed attacker pacing our own
border, usually because a wide belief cloud covers the doors, `_cross`
picks food reachable without stepping next to a visible ghost. Dots
behind a guarded door are penalised and capsules get a bonus.

## §9 Defense

### §9.1 Hunting (`_hunt`)
1. If we are on their side, go home first.
2. If an invader is next to us and we are not scared, eat it.
3. Pick the target: the invader carrying the most, then the nearest.
   Its position comes from sight, then the belief, then the last bite if
   the bite is under 12 moves old.
4. Hand the target to `_pursue`.

### §9.2 Region pursuit (`_pursue`)
For each of our legal moves, `_pursue` computes the **invader's
region**: every square the invader reaches strictly before every
hunter.

- **Hunters.** Our teammate counts as a second hunter if it is an
  unscared ghost on our side, so the two of us close different doors.
- **Ghost limits.** A hunter's distances stop at the border, because a
  ghost can't eat on the far side.
- **Scored contents.** Inside the region:

  | Content | Weight |
  |---|---|
  | An exit (a border square), scaled up by how much the invader carries | 10 + 3 per dot |
  | A capsule | 25 |
  | A dot | 1.5 |
  | Any other square | 0.2 |

  We take the move with the lowest score, then the one closest to the
  invader.
- **While scared.** We may not touch the invader. Our distances are
  raised to at least the scare time, and we keep 2 squares away. This
  shadows the invader until the timer ends.

### §9.3 Patrol (`_patrol`, `_cover`, `_crossing`, `_claimed_cover`)
With no invader, the defender predicts where each enemy would cross: the
first home square on its shortest path to our nearest food. `_cover`
picks the waiting spot whose slowest response to any of those doors is
fastest. If the teammate has just claimed a door in `_SHARE["cover"]`,
we cover a different one. With no prediction at all, it waits at the
middle of the border.

### §9.4 Scared fallback (`_flee`)
If we are scared and have no position for any invader, we stay on our
side and keep as far as possible from the invaders' likely squares.

### §9.5 Movement on our side (`_step_home`, `_home_distances`)
`_step_home` follows the shortest path that never leaves our side. If no
such path exists, it takes a greedy step that stays home.

### §9.6 Legacy exit cut-off (`_cut_off`, `_invader_goal`, `_intercept`)
This is the older "wait at the invader's exit" logic. Nothing calls it
since region pursuit replaced it. It is kept for reference and can be
deleted.

## §10 Utilities
| Function | Purpose |
|---|---|
| `_path` | BFS path, optionally restricted to our side |
| `_first` | First step toward a goal on a BFS parent tree |
| `_dir` | Convert a pair of squares into an action |
| `_nxt` | Square reached by an action |
| `_md` | Maze distance from the engine's precomputed table, falling back to Manhattan |
| `_fallback` | The crash-proof step home used by §3.2 |

## §11 How the techniques combine

```
               ┌──────────── every turn ────────────┐
 sonar, sight, │ §4 Bayes filter + teammate fusion  │
 eaten food ──►│    + eaten-food snaps + kill resets│──► reports
               └──────────────────┬─────────────────┘
                                  ▼
                       §5 mode (priority rules)
     ┌───────────────┬────────────┴───────┬──────────────────┐
  attack/raid      hunt               patrol              (scared)
     │               │                    │                  │
 §6 safety maps   §9.1 target pick    §9.3 door cover    raid (§6) or
  + food scoring   §9.2 region         with teammate     shadow (§9.2)
  + carry rules     squeeze with        split
     │              teammate
 §8 fallbacks,
  anti-stall,
  border cross
     │
 §7 alpha-beta veto (only when a seen ghost is near)
     ▼
  action ──► §3.2 legality check + crash-proof fallback
```

The main interactions:

- **Tracking feeds everything.** Better beliefs (fusion, food snaps)
  mean tighter safety maps for the attacker and accurate targets for
  hunters. Region pursuit only works when it knows roughly where the
  invader is, so `last_bite` fills gaps when the belief is wide.
- **Safety maps plan; search checks.** The safety-map planner looks far
  ahead cheaply but approximately. The alpha-beta search looks a few
  moves ahead exactly, so it only vetoes moves where the approximation
  could get us killed.
- **Teammates coordinate without messages.** The shared sonar, the door
  claims, and counting the teammate as a second hunter let the two
  agents split work. Neither needs to know the other's plan.
- **Anti-stall rules backstop the careful logic.** Safety-first planners
  can freeze when a defender mirrors them. The stall detector and
  `_cross` make sure a cautious agent still acts.
- **Roles bend with the situation.** The offense player hunts when it is
  closest; scared ghosts go raiding; leads get closed out by patrolling.

## Testing

`testing/bench.py` plays this file against nine opponent styles and
past versions of itself, on fixed and random maps, as both colours. See
`testing/README.md`. Results for each change are in the merged pull
requests.
