# Agent branch `agent/mm`

**Proxy of the contest team M&M, reverse-engineered from two replays.**

This branch holds a behavioural proxy of a real contest team, rebuilt from
contest replays. It is not that team's code: it reproduces the decision rules
seen in the replays. The main agent and the test tools are on `main`.

`my_team.py` is self-contained (shared helpers inlined), so it can be played
directly or from `main` with `python testing/bench.py -o mm`.

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team
```

## What it does (from the module docstring)

Behavioural proxy of the student team "M&M", rebuilt from two contest replays.

Not their source: a reconstruction of the decision rules seen in the replays
(every rule below is checked against both games, see the notes per rule).
Both agents are greedy one-step planners over BFS distances. Every choice is
the first best move in the engine's action order (North, South, East, West,
Stop), so the team is fully deterministic.

Attacker (first index)
  * Heads for the nearest dot by BFS. The square of the nearest visible ghost
    and the squares next to it count as walls, so it detours to another door
    rather than walk past a guard. Other ghosts are ignored.
  * Banks when it carries at least a quarter of the dots still out
    (carry >= food_left // 4): 6 of 24, 5 of 19, 4 of 15, 3 of 12, 2 of 10,
    1 of 7 in the replays. It also banks with any dot as soon as a ghost is
    within 5 steps, or when time runs short.
  * Under threat the way home may end in a capsule instead, so it eats the
    capsule when that is closer than a door. It ignores scared ghosts and never
    hunts them; it just keeps eating while they are scared.
Defender (second index)
  * Never crosses the border, and plans its paths inside its own half.
  * Chases the nearest visible invader. Without one, it walks to the last alert
    (a dot that just vanished or the last place an invader was seen), clears
    the alert there, then walks to its post: the door with the smallest total
    maze distance to the dots it defends. At the post it Stops until something
    happens. This is why it Stopped 178 times in 150100.
  * While scared it keeps exactly two steps from the invader. It closes in from
    farther away, Stops at two and backs off at one.

## Reverse-engineered behaviour

### Attacker: greedy BFS raider, never defends

Replay agent: 150100: agent 0 (red); 150085: agent 1 (blue). The first index is always the attacker.

- Food mode: one step along the BFS shortest path to the nearest dot. With no ghost visible this matches 189/189 plies in 150085 and 85/85 in 150100. On ties it takes the first move in the engine's order N,S,E,W,Stop. That held for every tie, for example 87 times N over E/W in 150100.
- Ghost avoidance: only the NEAREST visible non-scared ghost (scared timer <= 2) counts. Its square and the 4 squares next to it become walls for the BFS, and other ghosts are ignored. Blocking all visible ghosts drops 150100 a0 from 0.996 to 0.624 junction agreement, and blocking only ghosts within 5 steps scores 0.991. The rule produces the detours to another door at 150100 plies 212-268 (retreat at (17,5), walk home along row 6, re-enter at (17,1)) and 150085 plies 669-709 (returns via (16,12) to avoid ghosts at (16,5)/(16,9)).
- Banking rule: go home when carry >= food_left // 4. Return points (carry, food left): 150085 345 (6,24), 497 (5,19), 637 (4,15), 781 (3,12), 869 (2,10), 989 (2,8), 1125 (1,7); 150100 420 (6,23). Every 'one dot earlier' ply kept eating: 341 (5,25), 493 (4,20), 633 (3,16), 777 (2,13), 865 (1,11), 985 (1,9), 150100 416 (5,24). Ghosts, score and time explain none of these returns.
- Threat banking: with carry > 0 and a ghost within 5 maze steps, it heads home at once. 150100 ply 188: c1, ghost at 5, turns back and banks 1 at 204. Ply 184: ghost at 7, keeps going.
- Under threat the home goals include capsules, so it takes a capsule that is closer than a door. 150100 ply 344: ghost adjacent, takes the capsule (20,2) over the dot (19,1) even though S comes first in tie order. 150085 ply 449: ghost 3 behind, takes the capsule (11,9) over the dot (12,10).
- Scared ghosts are ignored and never hunted. 150100 plies 348-460: the scared Alma defender trails it at distance 3 for 40 moves while it eats 5 dots and banks 6 exactly as the timer runs out.
- Ignores invaders on its own side (150085 plies 385-393, invader visible 13 away).

### Defender: door sentinel with an alert memory; never crosses the border

Replay agent: 150100: agent 2 (red); 150085: agent 3 (blue). The second index is always the defender.

- Post = the border square with the smallest total maze distance to the dots it still defends, recomputed every turn. 150100: (16,6), total 393, the unique minimum. 150085: (17,7), total 464, at the start, then (17,1) after the north-east dots went. Its opening walk is a shortest path with N,S,E,W tie-breaks (150100 plies 70-150).
- Target priority: (1) the nearest visible invader; (2) the alert square, which is the latest of 'a defended dot just vanished' and 'invader last seen here', cleared on arrival; (3) the post. 150100 ply 182: walks to the eaten dot (14,11) with nothing visible. Plies 214-230: walks to the last sighting (16,12), clears it, returns to the post. Ply 278: walks to the eaten dot (14,15).
- All paths are BFS restricted to its own half. 150085 ply 939: goes E round inside its half instead of W through enemy ground. Plies 299-311: the long home-side route to post (17,1). These rules fixed 5 plies that full-maze distances got wrong.
- Stop = its target is its own square: at the post with no alert and no visible invader. Enemy ghosts hovering across the border are not invaders and do not move it.
- Scared: picks the move minimising |distance to invader - 2|. It closes in from far, Stops at exactly 2 and backs off at 1. Evidence: 150085 plies 251-279 shuttle (17,7)/(17,8), ply 335 Stop at distance 2, plies 599-659; 150100 plies 398-402.
- Deterministic, with the same N,S,E,W,Stop tie order. No sonar use: fidelity is identical for sonar seeds 0, 1 and 2.

## Likely algorithm

A hand-written greedy goal planner with BFS distance maps and no lookahead, using first-best tie-breaking in the engine's action order (N,S,E,W,Stop). Attacker: BFS to the nearest dot, with the nearest non-scared ghost (scared timer <= 2) and its 4 neighbours as walls. It switches to goal = home border (plus capsules when threatened) when carry >= food_left//4 or a ghost is within 5-6 with carry > 0. It never hunts and never defends. Defender: a state machine with a target chosen in this order: nearest visible invader, else an alert square (the latest vanished dot or invader sighting, cleared on arrival), else a fixed post (the border square with the minimum total maze distance to the remaining defended dots). Paths stay inside its own half, and it Stops when the target is its own square. When scared it keeps the invader at distance 2. No sonar, no particle filter, no minimax. Evidence: independent trace re-simulation reproduces 599/600 for each team colour; it does no lookahead (172 moves adjacent to a ghost, walking into a dead end); every move with nothing in view is an exact shortest-path step. The proxy's time-up rule and no-path fallback are not tested by either replay.

## Exploitable weaknesses (verified against the replays)

- Attacker walls only the nearest non-scared ghost (its square and the 4 next to it). A ghost that mirrors it at distance 1 makes it shuttle between two squares indefinitely without banking (150100 plies 504-1196, 172 moves carrying 1). It does not flee an adjacent ghost properly, so a ghost that stays next to it can simply eat it. A ghost standing opposite it at the border makes it dither between doors (150100 plies 212-304; crowdedCapture sanity game).
- A second ghost is ignored when walls are built (walling all ghosts fits only 214/300), so two defenders should be able to pinch it. This is inferred from the rule and was not observed in a replay.
- It banks only when carry >= food_left//4 or a ghost comes within 5-6 steps. Late trips carry 1-2 dots over 50-70 plies (150085 banks 6,5,4,3,2,2,1), so its scoring is slow late in the game.
- It never hunts scared ghosts. A capsule only buys it free eating (150100 plies 348-460).
- The attacker never defends and never Stops; the defender never crosses the border. No role switching even when losing (175 idle Stops while 5 down).
- The defender has no sonar and guards one post (the border square closest in total to its dots). An unseen invader at a far door is free until the first dot vanishes (150100 plies 170-182). Enemy ghosts hovering at the border never move it.
- Capsule exploit: while scared it keeps a distance of 2 and in practice trails far behind. Alma ate 7 dots and banked 9 during one scare (150100 plies 290-389).
- Scared defender death traps: it backs away from an adjacent pacman with no dead-end awareness, gets cornered and dies (150085 plies 343-387). With no invader visible it walks to its alert square next to an enemy ghost at the border, which steps across and eats it (150085 plies 675-678).
- The defender is kitable: a pure equal-speed follower that never closes a gap of 3-4 (150085 plies 959-1199, invader reached carry 7; 150100 plies 450-494, invader banked 2).
- Deterministic, with N,S,E,W,Stop tie order. The same situation gives the same move (the lock repeated identical responses for 172 moves).

## How faithful the proxy is

match_150100.replay mm_team.py as red: all 0.998 (599/600), junctions 0.998 (469/470); agent 0: 0.997, junctions 0.996 (228/229); agent 2: 1.000, junctions 1.000 (241/241). Only miss: ply 504, a0 at (20,9) recorded East, proxy South (two ghosts in view). match_150085.replay mm_team.py as blue: all 0.998 (599/600), junctions 1.000 (147/147); agent 1: 1.000, junctions 1.000 (78/78); agent 3: 0.997, junctions 1.000 (69/69). Only miss: ply 387, scared defender cornered in the dead end (22,13), recorded West (onto the pacman), proxy Stop. Same for sonar seeds 0, 1 and 3. References this beats at junctions: mm_replay_proxy 0.477 / 0.816, baseline 0.230 / 0.721, my_team 0.357 / 0.673.

High that the proxy reproduces the real team's decision rules in situations the replays cover: two different maps, both colours, near-perfect independent re-simulation, and every sub-rule shown necessary by ablation. Medium on other maps, for four reasons. (1) The banking rule food_left//4 was only seen with 30 dots per side; on maps with more food it banks 12-13 at once, and the real team might have had a cap the replays cannot show. (2) The threat distance could be 5 or 6. (3) The time-up rule and the no-path fallback (which I changed) are guesses that neither replay exercises. (4) Behaviour with two ghosts in view is barely sampled (the one miss, ply 504). Deterministic tie-breaking is the best fit, though only a few plies separate the tie orders.

Claims from the first analysis that a reviewer refuted:

- 'The shuttle lock cost the game (-5)': refuted. The score was already -5 at ply 496, before the lock began. Alma's 9-dot bank at 389 and a 2-dot bank at 493 had settled it. The lock only froze the score for about 700 plies. It also needed Alma's ghost to mirror the attacker at distance 1 without eating it, which it could have done on any turn.
- 'In 150100 Alma came in through (16,10)-(16,12) while M&M guarded (16,6), and banked 9 (ply 390)': half wrong as an explanation. The door choice did let Alma in unseen: plies 170-178, Alma is a pacman at (16,12)->(14,12) while the defender Stops at (16,6). But the 9-dot trip happened under capsule scare. Alma ate capsule (13,15) at ply 289, and M&M's defender was scared from 290 to about 449. During that time its 'keep 2' rule kept it 5 to 11 squares away, and Alma ate 7 dots (plies 298-366) before banking 9 at 389.
- 'Thresholds are crisp: a ghost within 5': overstated. Threat distances of 5 and 6 fit both traces equally well (300/300 and 299/300). 7 breaks ply 184 and 4 or lower breaks plies 188-204. The trace only pins the threshold to 5 or 6.
- 'Tie order N,S,E,W held for every tie' is true but weakly identified: NSEW scores 1198/1200 in my own re-simulation, against 1194 for NSWE and 1193 for SNEW. Few plies discriminate.
