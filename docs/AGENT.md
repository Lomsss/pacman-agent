# Agent branch `agent/ghostclaniol`

**Proxy of the contest team GhostClaniol, reverse-engineered from a replay.**

This branch holds a behavioural proxy of a real contest team, rebuilt from
contest replays. It is not that team's code: it reproduces the decision rules
seen in the replays. The main agent and the test tools are on `main`.

`my_team.py` is self-contained (shared helpers inlined), so it can be played
directly or from `main` with `python testing/bench.py -o ghostclaniol`.

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team
```

## What it does (from the module docstring)

Proxy of the student team "GhostClaniol" (replay 150085, red).

Reverse-engineered from one contest replay. Both agents are one-step
reflex agents: each legal move is scored on simple features of the square
it leads to; remaining ties go to the move the engine lists last.

Attacker (first index): walks the shortest path to the nearest dot. Squares
within 3 steps of a visible unscared ghost are walls for that path, and a
dead-end pocket is not entered while a ghost could reach its mouth before
we got back out. It banks once it carries 5, or as soon as home is nearer
than the next dot; on the way home it still takes one dot a step away. It
ignores invaders and never hunts scared ghosts on purpose (it eats them
only when they stand on its path). Near the end it enters a pocket anyway
if the ghost could not reach it before time runs out.

Defender (second index): patrols the map centre (width // 2, height // 2).
On the red side that square is the first enemy column, so the defender
shuttles across the border every turn. It chases a visible invader by maze
distance (crossing the border if that is shorter), runs from it while
scared, and as a pacman keeps more than 4 steps from an unscared ghost.
Staying home wins ties. It never reacts to dots vanishing out of sight.

## Reverse-engineered behaviour

### Pure attacker: a greedy dot-eater that avoids ghosts, never defends and never deliberately hunts scared ghosts. It banked all 20 points over 5 trips (3, 5, 1, 6, 5).

Replay agent: 0

- Opening: takes the shortest maze path to the nearest enemy dot, (20,16) at distance 63. The capsule at (19,16) happened to lie on that path; every off-path step in plies 0-248 is an eating step.
- Target: the nearest dot by maze distance. When a visible ghost is near, the path routes around the squares within 3 of that ghost. Examples: at 904-936 it detoured from (16,1) through (14,1)-(14,5) and (16,5) instead of going through the ghost on row 1; at 928 it chose E over S, which tie on plain distance and differ on the ghost-aware path.
- Ghost avoidance: it never steps to a square within maze distance 3 of a visible ghost that is not scared (scared timer 5 or less still counts as dangerous). Distance 4 is allowed. At 860 it retreated from (24,4) with the ghost at 4, because N would have put it at 3. At 956/960 it advanced with the ghost at distance 4. Moving the threshold to 4 drops junction agreement from 0.946 to 0.849, and 2 gives 0.946.
- Dead-end pockets: it does not enter a pocket while a ghost could reach the pocket mouth before it got back out. At 1036, 1084 and 1132 it was at (27,3) with the ghost at (26,5), distance 3, and refused the food square (27,2) at the mouth of a 4-square pocket. It looped the same 12-step cycle around a block 3 times instead. Removing this rule costs 6 junction plies.
- Endgame: at 1180, in the same state with only 5 own moves left, it dived into the pocket and ate 4 more dots, ending with 7 carried. It ignores the pocket danger when the game ends before the ghost could follow it in.
- Banking: it heads home when carrying 5 or more, or as soon as it carries anything and home is strictly closer than the next dot. Cases: 268 (carry 3, home 4 vs dot 15), 480 (carry 1, home 2 vs dot 5), 408/764 (carry 5). On the way home it still takes a dot one step away: at 592 it ate (24,16) while carrying 5. A limit of 5 fits best: 4 gives 0.914, 6 gives 0.925, no limit gives 0.882. Dropping the home-closer-than-dot rule costs 6 plies.
- Scared ghosts: it ignores them. At 600-660 it walked home carrying 6 with a scared ghost at distance 2 and did not hunt it. It eats one only when it stands on its path: at 388 it moved onto e3 (scared 5) at the food square (22,13).
- Invaders: it ignores them. It only Stopped twice, at 704 and 708 on (16,1), while an invader carrying 4 was visible about 18 away. That trigger is unexplained.
- Ties: among a0's equal moves, 3 went to the later move in engine order (692, 696 and 1188, which was E over W) and 2 to the earlier one (300 S over E, 524 N over E). This looks like random tie-breaking. The proxy sends ties to the move listed last.

### Defender posted at the map centre (width//2, height//2) = (17,9). On the red side that square is the first enemy column, so the defender crosses the border every turn: (16,9) E then (17,9) W, more than 200 times. It ate no dots.

Replay agent: 2

- Post: the map centre square (W//2, H//2). The opening is the exact shortest path from (1,1) to (17,9), distance 64, with no off-path step before ply 258. After fleeing it walks the same path back (342-382, 582-606).
- At (16,9) going E reaches the post. At (17,9) it is a pacman and N, S and W all tie at distance 1. W, the move back home, wins every time (23 such ties, 0 exceptions), and it never Stops on the post. Home preference also explains the ties at 490 (N over E) and 798 (S over E). This is a one-step reflex with an on-defense or home bonus smaller than one step of post distance, plus a Stop penalty.
- Visible invader and not scared: it moves to minimise the maze distance to the invader and crosses the border when that is shorter. At 418-446 it went (16,10), (17,10), (17,11), (17,12), (16,12), then west along row 12 behind e1 at distance 4. It does not cut off routes or predict the invader.
- Scared with an invader visible: it runs away to maximise distance from the invader on our own side, from as far as 10 away (486). At 286-338 it fled from (16,9) all the way to (7,6). At 518-574 it fled from (16,9) to (14,4). When the invader goes out of sight it walks back to the post.
- As a pacman it avoids an unscared ghost within 4: at 714/718, with e1 just turned ghost at (18,12)/(19,12), it stayed home and stepped N/S instead of E. It treats a ghost with 5 or less scared time as dangerous: at 670, with e3 scared 5 at (17,7), it went S rather than E. A scared ghost on the next square gets eaten: at 678 it killed e3 (scared 3) on (17,9).
- It ignores dots vanishing out of sight. From ply 746 to 1198 the invader e1 grazed the top-left (7..16,12..16) out of sight and banked several times. a2 kept shuttling at the centre.
- Unexplained deviations, about 10 plies (786-798, 914/918, 938 Stop, 942/946, 974/978, 1198 Stop, 706 Stop): small N/S/Stop moves near the post while an invader was out of sight. They are probably sonar-driven and cannot be reproduced, because the harness noise is not the game's noise.

## Likely algorithm

A hand-written two-role team with no adversarial search.
- Attacker: each turn it runs a BFS (shortest path) to the nearest enemy dot, or to the home border once it carries 5 or home is strictly closer than the next dot. Squares within maze distance 3 of a visible unscared ghost count as walls. It has a dead-end check that is dropped in the last few moves. It never stops voluntarily, and its ties look random. It has no capsule or scared-ghost logic and no defensive role.
- Defender: a one-step reflex agent of the baseline DefensiveReflexAgent kind. It heads for a fixed post at (width//2, height//2). It gets a small bonus for standing on its own side, which produces the perfect (16,9)/(17,9) shuttle on red, and a Stop penalty. It closes in on visible invaders by maze distance, flees them while scared without leaving its side, and as a pacman avoids unscared ghosts within 4. It may use sonar faintly, given about 6 unexplained small moves toward out-of-sight invaders.
- Unexplained: the simultaneous team Stops at 704-708.

## Exploitable weaknesses (verified against the replays)

- The defender reacts only to invaders it can see. It ignores dots disappearing and invaders out of sight, apart from rare small steps. From 746 to 1198 M&M farmed the top-left and banked 4 times while a2 shuttled at the centre. Attack through lanes far from (W//2, H//2).
- On red, the post is the first enemy column, so the defender is a pacman one step over the border every other turn and covers no other door.
- Once their team is scared, the defender flees to maximise distance from any visible invader (it fled to (7,6) at 286-338 and to (14,4) at 518-574). Eating their capsule (the one on our side) therefore opens their side for about 40 moves. M&M banked 6 and 5 right after its two capsules.
- The chase is pure maze distance with no interception. It trailed an invader at exactly 4 for 30 plies without gaining. An invader moving away is never caught. It crosses the border when the shortest path does, but not always (it Stopped at 706).
- The attacker can be herded. A ghost holding 4 away drove it home with 0 food (860-900). A ghost holding 3 from a pocket mouth kept it looping a 12-move cycle for about 150 plies carrying 3; it never banked, and those 3 dots plus 4 more were lost at the end.
- The attacker refuses dead-end pockets while a ghost could reach the mouth. Food in pockets is safe from it while a defender sits nearby, except in the last few moves, when it dives in.
- Banking is predictable: home at 5 carried (6 if a dot is adjacent at 5), or as soon as home is strictly closer than the next dot. It walks the shortest ghost-free path, so a defender waiting on the border near its return route intercepts it.
- The attacker never defends and ignores invaders. It never hunts scared ghosts (it walked past one with 17 scared moves left at 620) and takes capsules only when they lie on its food path. Our scared ghosts are safe from it unless they stand on its path.
- M&M lost no ghost to a deliberate hunt: both blue respawns came from a blue ghost walking into a0 (387) or a2 walking to its post (678). Do not expect scared-ghost kills from this team.

## How faithful the proxy is

After the fix, match_150085.replay, ghostclaniol_team.py as red: all 0.970 (582/600), junctions 0.950 (285/300). Agent 0: 0.973, junctions 0.946 (88/93). Agent 2: 0.967, junctions 0.952 (197/207). This is identical to before the fix and identical with --seed 3. As blue on the same replay, against M&M (for interest only): junctions 0.714. a2's junction count is inflated by about 110 trivial shuttle plies at (16,9), which the harness counts as junctions because 3 non-Stop moves are legal there. On the 98 non-shuttle a2 plies after the opening it is about 90%. Sensitivity checks: SCARED_SAFE 0-3 gives 0.947 overall junctions (a2 196/207), SCARED_SAFE 10 gives 0.947, removing the endgame pocket clause gives 0.947 (a0 87/93), no home bonus gives 0.923 (a2 189/207), and random ties give 0.903-0.933.

Medium. The rules are map-general and fit the replay very well: 0.950 junction agreement, independent of seed, with both agents' trajectories reproduced almost move for move. But they come from one game on one map, playing only as red, so several parts rest on very few plies:
- the post rule (W//2, H//2), which only this one red game supports (any rule that lands on (17,9) here would fit), so its behaviour on blue and on other maps is extrapolated;
- the endgame pocket dive (1 ply);
- the 'one extra dot at the limit' rule (1 ply);
- the defender's scared-5 danger threshold (1 ply).

The attacker's core rules (BFS around a radius-3 ghost block, carry 5 or home closer than the next dot, pocket refusal, ignoring invaders and scared ghosts) were each seen many times and should carry over well. The defender's sonar-like deviations and the team Stops are not modelled. Ties are broken by engine order, not at random, which is a colour asymmetry. In sparring games its statistics look like the replay on defaultCapture as red: attacker a pacman about 70% of moves with small banks, defender a pacman about a third of moves through the shuttle.

Claims from the first analysis that a reviewer refuted:

- The claim 'at 388 a0 moved onto e3 (scared 5) at the food square (22,13)' is wrong. The respawn event for agent 3 is at ply 387, on blue's own move: a3, scared 5, stepped West from (22,13) onto pacman a0 at (21,13) and died. At 388 a0 only ate the food at (22,13). So a0 never ate a scared ghost on its own move in this game. The kill was a scared M&M ghost walking into a0. At 384, the move that put a0 next to that ghost was forced: N, S and Stop all ended within 3 of it, so food decided.
- The claim that a0 treats a ghost with 5 or fewer scared moves as dangerous has no support in a0's moves. No a0 ply tells the thresholds apart: SCARED_SAFE = 0, 2 or 3 leaves a0 at 88/93 junctions. The only evidence for the value 5 is one defender ply, 670: a2 went S rather than E with e3 (scared 5) at distance 2. That ply could just as well be driven by sonar.
- 'It crosses for real only when the shortest chase path runs through enemy squares (418-430, 466-482)' is half wrong. During 466-482 a2 was scared (36 to 33) and the invader was out of sight. It was walking back to the post through (17,12), (17,11), (17,10), because (16,11) is a wall. It was not chasing. Also at 706, with the invader visible at (16,12) at distance 4, it Stopped instead of crossing E, which would have cut the distance to 3. So 'crosses whenever that is shorter' does not always hold.
- 'At (17,9) W wins in 23 such ties' undercounts. a2 played W from (17,9) all 73 times: 69 with an invader known to be a pacman but out of sight, 4 with none. The direction of the claim is right.
- The analyst calls both agents one-step reflex agents with no search. That is not right for a0. The detour at 904-936 and the retreat at 860-900 need a path search in which squares near the ghost count as walls, which is BFS-style planning every turn. A per-step feature cannot produce them. The proxy itself uses BFS (path_dist). The no-search description fits only the defender.
