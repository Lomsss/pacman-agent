# Agent branch `agent/alma`

**Proxy of the contest team Alma Team, reverse-engineered from a replay.**

This branch holds a behavioural proxy of a real contest team, rebuilt from
contest replays. It is not that team's code: it reproduces the decision rules
seen in the replays. The main agent and the test tools are on `main`.

`my_team.py` is self-contained (shared helpers inlined), so it can be played
directly or from `main` with `python testing/bench.py -o alma`.

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team
```

## What it does (from the module docstring)

Behavioural proxy for "Alma Team", inferred from contest replay 150100.

This is not their source. It reproduces the decision rules the replay shows:

Raider (first agent)
  * Shortest path to the nearest dot; equal moves go to the first legal
    action in engine order (North, South, East, West, Stop).
  * Against visible, non-scared ghosts it looks two moves ahead: it moves,
    the ghosts answer (they stay on their own half), it moves again, the
    ghosts answer again. Ending within two squares of a ghost is ruled out.
    On its own half it stays about three squares from a guard that is
    parked (same square as on its previous turn): in the replay it hovered
    next to a camped door for the last 175 moves instead of trying another
    door. A guard that moved or just came into view is backed away from
    instead (replay: it retreated from 4 to 5 and from 6 to 7 squares while
    a guard walked along the border, and came back once it was out of
    sight). As a pacman it backs off from any ghost closer than seven
    squares. With two ghosts close, ghost replies are limited to moves that
    do not increase their distance, to keep the search fast.
  * Small penalties for reversing (read from its own heading, which the
    observation contains) and for stopping, and a small preference for
    squares that are further from the ghost by straight-line distance.
    These produce the replay's three-square shuttle in front of a guarded
    door.
  * Banking: the pull home grows with carry times distance home (it banked
    9 dots in one trip while the ghosts were scared and turned home after
    one dot when a ghost came into view). Scared ghosts are ignored.
    Capsules count for nothing except being on the way.

Guard (second agent)
  * Never crosses the border.
  * Visible invader: step to the square that is closest to it by maze
    distance. Ties go to the first legal action. While scared (timer > 1)
    it keeps exactly three squares away instead.
  * Invader out of sight: walks to where the sonar belief puts it.
  * Otherwise it opens at our square nearest the map centre, then holds
    the door nearest the non-scared enemy that is closest to our side
    (sonar belief) and stops there.

## Reverse-engineered behaviour

### Raider (pure attacker; pacman for 69 of 300 moves, banked 1+9+2, never died, 0 Stops)

Replay agent: 1

- Opening: takes the shortest maze path to the nearest enemy dot, and equal moves go to the first legal action in engine order N,S,E,W. Evidence: N over W at plies 65-85 (6 times), N over S at 129, S over W at 145, N over W at 161. It crosses at (16,12) on ply 173 and eats (14,11) at 181.
- Determinism: the game ends in a loop with a 16-ply period that lasts 700 plies (497-1200). So there is no random tie-breaking, but the choice depends on its own heading. At (19,5) the observation is identical every time, yet it goes South when it arrived moving East (plies 509, 525, 541...) and West when it arrived moving North (517, 533...). This is a reverse penalty read from configuration.direction, which is part of the observation. It never picks North there.
- Against a visible, non-scared ghost it behaves like a depth-2 look-ahead: it moves, the ghost replies while staying on its own half, then a second round. It never ends within 2 squares of the ghost. At ply 497 it picks S (17,5) over N (17,7) even though N is 2 squares closer to food, because (17,7) is a pocket with one exit.
- On its own half facing a door guard, it hovers about 3 squares from the ghost. For the last 175 moves (497-1200) it shuttles (18,5)->(19,5)->(19,4)->(19,5)->(18,5) in front of M&M a2, which Stops on the door at (16,6), and it never tries another door. Fitted penalty: 0 at distance 3, +1 per extra square up to 8.
- As a pacman it backs off from a ghost as soon as it sees one. Ply 189: carrying 1 at (14,10), ghost visible at maze distance 6, it steps away from food 1 square off (N instead of W), shuttles (14,10)/(14,11) at 189-201, then banks 1 at 213. After banking it keeps retreating on its own half while that ghost is visible (217-241, at distance 4-6) and goes back in when the ghost is out of sight (245-261).
- Banking: the pull home grows with carry x distance home (fitted weight 0.12) plus the threat. With both ghosts scared (capsule at (13,15) eaten on ply 289) it went deep and turned home at carry 9 on ply 369, with 15+ scared turns left, banking at 389. It banked 2 at 493 once the ghost was no longer scared (ply 461, unscared ghost at 2).
- Scared ghosts are ignored: it never hunts them. Scared a2 was 1-2 squares away for plies 397-445 and was never eaten. Capsules have no value of their own and are only eaten when on the path (13,15).
- Ignores visible invaders while at home: M&M a0 sat on our side carrying 1, 7-9 squares away, for 175 moves.

### Guard (pure defender; never becomes pacman; 4 Stops at 235, 239, 259, 295)

Replay agent: 3

- Opening: follows the same corridor as the raider toward our square nearest the map centre ((17,9)/(17,10)). A fixed target there explains 43 of 44 opening moves.
- Visible invader and not scared: steps to the home square with the smallest maze distance to it, ties to the first legal action. This explains 184 of 184 chase moves (e.g. 507 S over E, 511 N over E).
- Scared (timer > 1) with a visible invader: picks the move that leaves it exactly 3 squares away (38 of 39; the miss is at ply 503, where timer 1 already means chase). Seen at 347-499 after M&M took our capsule at 344.
- Invader not visible: walks toward the sonar or eaten-food estimate (171-207 toward (19,6), where a0 had eaten).
- No invader: holds the door nearest the non-scared enemy that is closest to our side, and Stops when on it ((17,5) at 235/239/259, (17,1) at 295). When both enemies were scared (299-327) it walked back toward the centre and left the (17,1) door.
- Never crosses the border to chase: 0 pacman moves in 300.

## Likely algorithm

Raider: a deterministic evaluation agent with a shallow adversarial look-ahead.

What the evaluation contains:
- Distance to the nearest dot, dots eaten, a carry x distance-home pull that turns it home at about 9 dots with no threat.
- A heavy penalty for ending 2 or fewer squares from a visible unscared ghost.
- A reverse penalty that reads its own heading.
- First-legal argmax (ties go to N, S, E, W in order).
- Scared ghosts are not threats and not targets.

What is confirmed and what is not:
- Confirmed: the look-ahead is deeper than one move (the ply-497 pocket avoidance), it never ends within 2 squares of a ghost, and it is deterministic and heading-dependent.
- Not identified: the exact depth (2 fits well), the weights, and the at-home reaction to ghosts. The data shows retreating from a moving ghost and probing about 3 squares from a stationary one. The proxy models this with a 'parked guard' flag, but the real code may use the ghost's direction or a prediction instead.

Guard: a baseline DefensiveReflexAgent-like chaser. This part is strongly supported (185 of 185 chase moves, 38 of 38 scared moves):
- Minimise maze distance to the visible invader, never cross, ties to the first legal action.
- While scared, keep exactly 3 squares away.
- Walk toward the believed invader position when it is out of sight.
- Open toward our square nearest the map centre (43 of 43).

The guard's idle door choice and its Stops are unexplained: the stated rule fails 9 of 24 idle moves even on the true state.

## Exploitable weaknesses (verified against the replays)

- A raider stalled by a parked door guard (confirmed): it hovered 3-5 squares from a ghost Stopped at (16,6) for 175 moves and never tried the other doors at (17,1), (17,10) or (17,12). Parking a ghost on the door that leads to their nearest food shuts down their offence. Their target is the nearest dot, so the door to guard is the one on the shortest path to our closest food.
- A raider that backs off from moving ghosts (confirmed): as a pacman carrying 1 it retreated from a ghost 6 squares away and banked only 1. At home it moved from 4 to 5 squares away from a ghost walking the border, and came back only once the ghost was out of view. A defender patrolling the border cuts their income a lot.
- A raider that never defends (confirmed): it ignored an invader carrying 1 that stayed 7-9 squares away for 175 moves.
- A guard that can be kited without being caught (confirmed): it chases by greedy maze distance with first-legal ties and never crosses. M&M a0 shuttled 2 squares from it around a 2x2 block for 175 moves. Waiting just across the border is safe from it (inferred from 0 crossings).
- Taking their capsule neutralises the guard (confirmed): while scared it keeps exactly 3 squares away (38 of 38), so the invader can eat freely. M&M took 6 dots at 344-416 and banked 6.
- The guard abandons doors when both our agents are scared (confirmed): after their raider's capsule it left (17,1) for the centre, and a0 came in there on ply 331.
- No capsule plan and no hunting of scared ghosts (confirmed, weak evidence): the capsule was eaten only on the way, and no scared ghost was ever chased.
- A 2-move horizon (confirmed in kind): it ate (9,7) at ply 457 with an unscared ghost 2 squares behind, because a 2-step search called it safe. A trap that needs 3 or more moves, or two ghosts, should catch it. This is inferred, not observed: it never died.
- Fully deterministic with fixed N, S, E, W tie-breaks and a no-reverse preference (confirmed by the identical-state test at 517/525), so its loops can be predicted and induced.
- Removed as unverified: 'the guard holds the door nearest the enemy closest to our side'. Its idle positioning is not identified, so do not plan around a specific door choice. It does stay near the door where it last saw an enemy and Stops there sometimes.

## How faithful the proxy is

After the fixes:
- match_150100 as blue (Alma): all 0.972 (583/600), junctions 0.966 (370/383). Agent 1: 0.977, junctions 0.953 (143/150). Agent 3: 0.967, junctions 0.974 (227/233). Before the fixes: junctions 0.963, agent 1 0.947.
- Remaining raider misses: 205, 217, 221, 297, 369, 437, 493. Remaining guard misses: 171, 227, 235, 239, 251, 255, 259, 291, 295, 463.
- About 58% of all moves are the end loop, which repeats about 3 distinct decisions, so these numbers overstate how much behaviour is identified. Before the loop, raider junction agreement is about 0.87 (analyst's split; I did not re-split after the fixes).
- Off-target checks: match_150085 as blue (M&M), junctions 0.810. match_150085 as red (GhostClaniol), junctions 0.563. match_150100 as red (M&M), junctions 0.219. The proxy is a fairly generic raider-plus-chaser, so it partly fits M&M too.

Medium for the guard on other maps; medium-low for the raider. Main risks:

- The guard's chase and scared rules are simple, map-general and fit every applicable move, so its behaviour with an invader in view should carry over. Its idle behaviour is a guess: the proxy camps and Stops far more than the real guard did (median 200 Stops vs 4).
- For the raider, the model family is well supported: greedy nearest dot, a 2-step max-min against ghosts that stay on their own half, never within 2 squares, no reversing, deterministic ties. But all the numbers come from one game, about 58% of which is a loop repeating 3 decisions. The at-home ghost reaction is the least certain part, and it decides how often the proxy stalls at the border. On defaultCapture it stalls completely against baseline and turtle (0-0), which is plausible given the replay but unverified.
- Banking extrapolates a linear carry x distance pull: it banked 20-31 on food-dense maps with no ghost in view, a regime the replay never showed.
- The proxy is fast (0.007 s max), never crashed, and uses no map-specific constants.

Claims from the first analysis that a reviewer refuted:

- Guard idle rule ('hold the door nearest the non-scared enemy that is closest to our side, and Stop on it'): refuted. I tested it on the TRUE positions in the trace (re/review_alma/door.py, door2.py). It misses 9 of 24 idle guard moves after ply 210 (227, 235, 239, 251, 255, 259, 291, 295, 463), which includes all 4 recorded Stops. At 235 and 239 the enemy closest to our side is a2 at (14,12)/(14,11), so the rule targets (17,12), yet the guard Stopped at (17,5). At 295 both enemies were scared (a0 timer 39, a2 timer 38), so the rule says go to the centre post, yet it Stopped at (17,1). Eleven variants (maze or Manhattan door metric, enemy nearest to me or nearest to the border, with or without skipping scared enemies) top out at 17 of 24. The idle/door behaviour is not identified.
- The analyst blamed the guard misses at 227-263 and 291-295 on sonar the harness cannot reproduce. Refuted: the harness gives the same guard result for --seed 0, 1 and 2, and the stated rule fails on those plies even with perfect information.
- 'Stops when on the door' is overstated as a persistent habit. The real guard Stopped 4 times in about 34 idle moves (12%) and wandered E-E-W-W around (17,5) between Stops. The proxy guard Stops a median of 200 of 300 moves in sanity games (real: 4 of 300, though the real guard was chasing an invader most of the game).
- 'On its own half it hovers about 3 squares from the ghost' as a general rule: contradicted before the loop. At 213-229 it stepped from 4 to 5 squares away from a ghost walking along the border, four times in a row. At 241 it went from 6 to 7. At 233-237, once the ghost was out of view, it walked back toward food (re/review_alma/hometrace.py). Hovering at 3 squares occurs only in the end loop, where the guard a2 is Stopped at (16,6). Fixed in the proxy (see changes).
- Timing claim 'max per move 0.0122 s': refuted. With the original file I measured a 0.114 s move in a sanity game with two enemy ghosts within 7 squares: the depth-2 search over 5x5 joint ghost replies gives about 78k leaves. Fixed: the max is now 0.007 s.
- 'The game ends in a loop that lasts 700 plies (497-1200)': minor correction. The exact 16-ply period starts at ply 512 (re/review_alma/loop.py). Plies 497-511 lead into it.
