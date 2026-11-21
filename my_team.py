"""Behavioural proxy for "Alma Team", inferred from contest replay 150100.

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
"""

import itertools

from contest.game import Directions

# ---- Shared sparring helpers (inlined from testing/opponents/zoo_common.py) ----
import math
import random
import time
from collections import deque

from contest.capture_agents import CaptureAgent
from contest.game import Actions, Directions

INF = float("inf")


def ipos(pos):
    return None if pos is None else (int(round(pos[0])), int(round(pos[1])))


class ZooAgent(CaptureAgent):
    """Map facts, enemy tracking and the moves every style needs."""

    def __init__(self, index, time_for_computing=0.1, **kw):
        super().__init__(index, time_for_computing)
        self.opts = kw

    def register_initial_state(self, game_state):
        CaptureAgent.register_initial_state(self, game_state)
        self.start = ipos(game_state.get_agent_position(self.index))
        walls = game_state.get_walls()
        self.walls = walls
        self.width, self.height = walls.width, walls.height
        self.mid = walls.width // 2
        self.cells = [(x, y) for x in range(walls.width) for y in range(walls.height) if not walls[x][y]]
        self.nbrs = {}
        for x, y in self.cells:
            self.nbrs[(x, y)] = [(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                                 if not walls[x + dx][y + dy]]
        self.border = [c for c in self.cells if self.is_home(c) and any(not self.is_home(n) for n in self.nbrs[c])]
        self.enemy_spawn = {i: ipos(game_state.get_initial_agent_position(i)) for i in self.get_opponents(game_state)}
        self.belief = {i: {self.enemy_spawn[i]: 1.0} for i in self.get_opponents(game_state)}
        self.prev_defend = set(self.get_food_you_are_defending(game_state).as_list())
        self.last_eaten = None

    # ------------------------------------------------------------ geometry
    def is_home(self, pos):
        return pos[0] < self.mid if self.red else pos[0] >= self.mid

    def dist(self, a, b):
        return self.get_maze_distance(a, b)

    def home_dist(self, pos):
        if self.is_home(pos):
            return 0
        return min(self.dist(pos, b) for b in self.border)

    def step(self, pos, action):
        dx, dy = Actions.direction_to_vector(action)
        return int(pos[0] + dx), int(pos[1] + dy)

    def toward(self, game_state, target, avoid=()):
        """Legal action whose next square is closest to target."""
        pos = self.my_pos(game_state)
        best, best_d = Directions.STOP, INF
        for action in game_state.get_legal_actions(self.index):
            nxt = self.step(pos, action)
            if nxt in avoid:
                continue
            d = self.dist(nxt, target)
            if d < best_d or (d == best_d and action != Directions.STOP and best == Directions.STOP):
                best, best_d = action, d
        return best

    def my_pos(self, game_state):
        return ipos(game_state.get_agent_position(self.index))

    # ------------------------------------------------------------ tracking
    def track(self, game_state):
        """Sonar particle filter, the standard Bayes approach from CS188."""
        me = self.my_pos(game_state)
        noisy = game_state.get_agent_distances()
        defend = set(self.get_food_you_are_defending(game_state).as_list())
        eaten = self.prev_defend - defend
        self.prev_defend = defend
        if eaten:
            self.last_eaten = ipos(next(iter(eaten)))
        for i in self.get_opponents(game_state):
            seen = ipos(game_state.get_agent_position(i))
            if seen is not None:
                self.belief[i] = {seen: 1.0}
                continue
            spread = {}
            for cell, p in self.belief[i].items():
                opts = self.nbrs.get(cell, []) + [cell]
                for n in opts:
                    spread[n] = spread.get(n, 0) + p / len(opts)
            pac = game_state.get_agent_state(i).is_pacman
            reading = noisy[i] if noisy else None
            new = {}
            for cell, p in spread.items():
                if reading is not None and abs(util_manhattan(cell, me) - reading) > 6:
                    continue
                if pac != (self.is_home(cell)):
                    continue
                if util_manhattan(cell, me) <= 5:
                    continue
                new[cell] = p
            if not new:
                new = {c: 1.0 for c in self.cells
                       if (reading is None or abs(util_manhattan(c, me) - reading) <= 6)
                       and pac == self.is_home(c)} or {self.enemy_spawn[i]: 1.0}
            if eaten and pac:
                new = {ipos(next(iter(eaten))): 1.0}
            total = sum(new.values())
            self.belief[i] = {c: p / total for c, p in new.items()}

    def guess(self, i):
        return max(self.belief[i].items(), key=lambda kv: kv[1])[0]

    def ghosts(self, game_state, scared_ok=False):
        out = []
        for i in self.get_opponents(game_state):
            st = game_state.get_agent_state(i)
            pos = ipos(st.get_position())
            if pos is None or st.is_pacman:
                continue
            if st.scared_timer > 2 and not scared_ok:
                continue
            out.append((i, pos, st.scared_timer))
        return out

    def invaders(self, game_state):
        out = []
        for i in self.get_opponents(game_state):
            st = game_state.get_agent_state(i)
            if st.is_pacman:
                pos = ipos(st.get_position())
                out.append((i, pos if pos is not None else self.guess(i), st.num_carrying, pos is not None))
        return out

    # ------------------------------------------------------------ roles
    def defend(self, game_state):
        """Chase seen invaders, else the last bite, else guard the busiest door."""
        pos = self.my_pos(game_state)
        if not self.is_home(pos):
            return self.toward(game_state, min(self.border, key=lambda b: self.dist(pos, b)))
        scared = game_state.get_agent_state(self.index).scared_timer > 0
        inv = self.invaders(game_state)
        if inv:
            target = min(inv, key=lambda t: (not t[3], self.dist(pos, t[1])))[1]
            if scared:
                # Keep two squares away until the timer ends.
                best, key = Directions.STOP, None
                for a in game_state.get_legal_actions(self.index):
                    n = self.step(pos, a)
                    if not self.is_home(n):
                        continue
                    k = abs(self.dist(n, target) - 2)
                    if key is None or k < key:
                        best, key = a, k
                return best
            if self.is_home(target):
                return self.toward(game_state, target)
        if self.last_eaten is not None and self.is_home(self.last_eaten):
            if pos == self.last_eaten:
                self.last_eaten = None
            else:
                return self.toward(game_state, self.last_eaten)
        guesses = [self.guess(i) for i in self.get_opponents(game_state)]
        door = min(self.border, key=lambda b: min(self.dist(b, g) for g in guesses))
        return self.toward(game_state, door)

    def safe_food_step(self, game_state, carry_limit=4, flee=3, capsule_bonus=0.0):
        """Greedy offense: nearest food, flee close ghosts, bank at carry_limit."""
        pos = self.my_pos(game_state)
        st = game_state.get_agent_state(self.index)
        food = self.get_food(game_state).as_list()
        caps = self.get_capsules(game_state)
        ghosts = self.ghosts(game_state)
        time_left = game_state.data.timeleft / 4
        go_home = st.num_carrying >= carry_limit or len(food) <= 2 or \
            (st.num_carrying and self.home_dist(pos) + 3 >= time_left) or \
            (st.num_carrying and any(self.dist(pos, g[1]) <= flee for g in ghosts))
        best, best_v = Directions.STOP, -INF
        for a in game_state.get_legal_actions(self.index):
            n = self.step(pos, a)
            v = 0.0
            for _, g, _ in ghosts:
                d = self.dist(n, g)
                if d <= 1:
                    v -= 1000
                elif d <= flee:
                    v -= 40 / d
            if go_home:
                v -= 3 * self.home_dist(n)
            else:
                if food:
                    v -= min(self.dist(n, f) for f in food)
                if n in food:
                    v += 5
            if caps and (ghosts or capsule_bonus):
                v -= (0.8 + capsule_bonus) * min(self.dist(n, c) for c in caps)
                if n in caps:
                    v += 20
            if a == Directions.STOP:
                v -= 2
            v += random.random() * 0.01
            if v > best_v:
                best, best_v = a, v
        return best


def util_manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class ChaseModel:
    """Tiny model of one pacman against the ghosts it can see.

    Used by the search opponents. State: (me, ghosts, food eaten, carried,
    banked, dead). Ghosts stay on their own side, as real ghosts do.
    """

    def __init__(self, agent, game_state):
        self.a = agent
        self.food = set(ipos(f) for f in agent.get_food(game_state).as_list())
        self.caps = set(ipos(c) for c in agent.get_capsules(game_state))
        self.start = (agent.my_pos(game_state),
                      tuple(g[1] for g in agent.ghosts(game_state)),
                      frozenset(), game_state.get_agent_state(agent.index).num_carrying, 0, False)

    def my_moves(self, s):
        me = s[0]
        return self.a.nbrs[me] + [me]

    def ghost_moves(self, g):
        return [n for n in self.a.nbrs[g] if not self.a.is_home(n)] + [g]

    def move_me(self, s, n):
        me, ghosts, eaten, carry, banked, dead = s
        if n in ghosts:
            return (n, ghosts, eaten, 0, banked, True)
        if n in self.food and n not in eaten:
            eaten = eaten | {n}
            carry += 1
        if self.a.is_home(n) and carry:
            banked += carry
            carry = 0
        if n in self.caps:
            # Scared ghosts no longer threaten: drop them from the model.
            ghosts = ()
        return (n, ghosts, eaten, carry, banked, dead)

    def move_ghosts(self, s, moves):
        me, _, eaten, carry, banked, dead = s
        dead = dead or me in moves
        return (me, tuple(moves), eaten, 0 if dead else carry, banked, dead)

    def value(self, s):
        me, ghosts, eaten, carry, banked, dead = s
        if dead:
            return -500
        left = [f for f in self.food if f not in eaten]
        v = 12 * banked + 4 * carry + 3 * len(eaten)
        v -= 0.6 * min((self.a.dist(me, f) for f in left), default=0)
        v -= 0.4 * carry * self.a.home_dist(me)
        for g in ghosts:
            d = self.a.dist(me, g)
            if d <= 1:
                v -= 200
            elif d <= 3:
                v -= 15 / d
        return v
# ---- End of shared helpers ----

REVERSE = {Directions.NORTH: Directions.SOUTH, Directions.SOUTH: Directions.NORTH,
           Directions.EAST: Directions.WEST, Directions.WEST: Directions.EAST}

# Raider weights, fitted on the replay (292 of 300 moves on the true state).
EAT = 3.3          # value of a dot eaten during the look-ahead
HOME_PULL = 0.12   # per carried dot per step from home
REV_PEN = 1.5      # reversing the current heading
STOP_PEN = 5.0
STRAIGHT = 0.25    # per straight-line step away from the nearest ghost (capped at 6)
DEAD = 5000.0      # caught (ghost on or next to us)
NEAR = 500.0       # two squares from a ghost
HOVER = 1.0        # per square beyond three from a visible ghost (capped at eight)
FLEE = 4.0         # as a pacman: per square closer than FLEE_RANGE to a ghost
FLEE_RANGE = 7
HOME_FLEE = 2.0
HOME_FLEE_RANGE = 7
FAR_GHOST = 7      # ghosts further than this are not searched over


class AlmaBase(ZooAgent):
    def register_initial_state(self, game_state):
        super().register_initial_state(game_state)
        self.home_d = {}
        for c in self.cells:
            self.home_d[c] = 0 if self.is_home(c) else min(self.dist(c, b) for b in self.border)

    def heading(self, game_state):
        conf = game_state.get_agent_state(self.index).configuration
        return conf.direction if conf is not None else Directions.STOP

    def visible_ghosts(self, game_state):
        out = []
        for i in self.get_opponents(game_state):
            st = game_state.get_agent_state(i)
            pos = ipos(st.get_position())
            if pos is not None and not st.is_pacman and st.scared_timer == 0:
                out.append(pos)
        return out


class AlmaRaider(AlmaBase):
    def choose_action(self, game_state):
        legal = game_state.get_legal_actions(self.index)
        try:
            self.track(game_state)
            return self._choose(game_state, legal)
        except Exception:
            return legal[0] if legal else Directions.STOP

    def _choose(self, game_state, legal):
        pos = self.my_pos(game_state)
        st = game_state.get_agent_state(self.index)
        carry = st.num_carrying
        food = frozenset(ipos(f) for f in self.get_food(game_state).as_list())
        time_left = game_state.data.timeleft // 4
        # End of game, or nothing left worth taking: walk home.
        if carry and (len(food) <= 2 or time_left <= self.home_d[pos] + 2):
            return self._home_step(game_state, legal, pos)
        ghosts = tuple(self.visible_ghosts(game_state))
        # A guard that has not moved since our last turn is "parked": the raider
        # probes it from about three squares. One that moved (or just came into
        # view) is treated as approaching and the raider backs off at home too.
        prev = getattr(self, "prev_ghosts", ())
        self.prev_ghosts = ghosts
        self.parked = bool(ghosts) and all(g in prev for g in ghosts)
        self.food = food
        self.fd_cache = {}
        self.prune = sum(self.dist(pos, g) <= FAR_GHOST for g in ghosts) >= 2
        heading = self.heading(game_state)
        best, best_v = None, -INF
        for a in legal:
            n = self.step(pos, a)
            eaten, c = frozenset(), carry
            if n in food:
                eaten, c = frozenset([n]), carry + 1
            if self.is_home(n):
                c = 0
            if n in ghosts and not self.is_home(n):
                v = -DEAD
            else:
                v = self._ghost_reply(n, eaten, c, ghosts, 1)
            if a == Directions.STOP:
                v -= STOP_PEN
            elif a == REVERSE.get(heading):
                v -= REV_PEN
            if ghosts:
                v += STRAIGHT * min(min(util_manhattan(n, g) for g in ghosts), 6)
            if v > best_v + 1e-9:
                best, best_v = a, v
        return best

    # ---------------------------------------------------------- look-ahead
    def _ghost_moves(self, g, me):
        if self.dist(g, me) > FAR_GHOST:
            return [g]
        moves = [n for n in self.nbrs[g] + [g] if not self.is_home(n)]
        if self.prune:
            # Two ghosts close by: 5 x 5 replies per layer is too slow, so each
            # ghost only considers replies that do not take it further from us.
            d = self.dist(g, me)
            moves = [n for n in moves if self.dist(n, me) <= d]
        return moves or [g]

    def _ghost_reply(self, me, eaten, carry, ghosts, my_moves_left):
        if not ghosts:
            if my_moves_left:
                return self._my_move(me, eaten, carry, ghosts, my_moves_left - 1)
            return self._leaf(me, eaten, carry, ghosts)
        worst = INF
        for combo in itertools.product(*[self._ghost_moves(g, me) for g in ghosts]):
            if me in combo and not self.is_home(me):
                v = -DEAD
            elif my_moves_left:
                v = self._my_move(me, eaten, carry, combo, my_moves_left - 1)
            else:
                v = self._leaf(me, eaten, carry, combo)
            if v < worst:
                worst = v
        return worst

    def _my_move(self, me, eaten, carry, ghosts, my_moves_left):
        best = -INF
        for n in self.nbrs[me] + [me]:
            e, c = eaten, carry
            if n in self.food and n not in eaten:
                e, c = eaten | {n}, carry + 1
            if self.is_home(n):
                c = 0
            if n in ghosts and not self.is_home(n):
                v = -DEAD
            else:
                v = self._ghost_reply(n, e, c, ghosts, my_moves_left)
            if v > best:
                best = v
        return best

    def _food_dist(self, me, eaten):
        key = (me, eaten)
        d = self.fd_cache.get(key)
        if d is None:
            left = [f for f in self.food if f not in eaten]
            d = min((self.dist(me, f) for f in left), default=0)
            self.fd_cache[key] = d
        return d

    def _leaf(self, me, eaten, carry, ghosts):
        v = -self._food_dist(me, eaten) + EAT * len(eaten) - HOME_PULL * carry * self.home_d[me]
        if ghosts:
            g = min(self.dist(me, q) for q in ghosts)
            if g <= 1:
                v -= DEAD
            elif g == 2:
                v -= NEAR
            elif self.is_home(me) and self.parked:
                v -= HOVER * (min(g, 8) - 3)
            elif self.is_home(me):
                v -= HOME_FLEE * max(0, HOME_FLEE_RANGE - g)
            else:
                v -= FLEE * max(0, FLEE_RANGE - g)
        return v

    def _home_step(self, game_state, legal, pos):
        ghosts = self.visible_ghosts(game_state)
        best, key = legal[0], None
        for a in legal:
            n = self.step(pos, a)
            danger = any(self.dist(n, g) <= 1 for g in ghosts) and not self.is_home(n)
            k = (danger, self.home_d[n])
            if key is None or k < key:
                best, key = a, k
        return best


class AlmaGuard(AlmaBase):
    """Chases what it sees, keeps three squares off while scared, else holds a door."""

    def register_initial_state(self, game_state):
        super().register_initial_state(game_state)
        # Opening post: our square nearest the middle of the map.
        centre = (self.width // 2, self.height // 2)
        home = [c for c in self.cells if self.is_home(c)]
        self.post = min(home, key=lambda c: (util_manhattan(c, centre), c))
        self.opening = True

    def choose_action(self, game_state):
        legal = game_state.get_legal_actions(self.index)
        try:
            self.track(game_state)
            return self._choose(game_state, legal)
        except Exception:
            return legal[0] if legal else Directions.STOP

    def _toward(self, legal, pos, target, key=None):
        best, best_k = None, None
        for a in legal:
            n = self.step(pos, a)
            if not self.is_home(n):
                continue
            k = self.dist(n, target) if key is None else key(self.dist(n, target))
            if best_k is None or k < best_k:
                best, best_k = a, k
        return best if best is not None else Directions.STOP

    def _choose(self, game_state, legal):
        pos = self.my_pos(game_state)
        scared = game_state.get_agent_state(self.index).scared_timer > 1
        opp = self.get_opponents(game_state)
        seen, unseen = [], []
        for i in opp:
            st = game_state.get_agent_state(i)
            p = ipos(st.get_position())
            if st.is_pacman:
                (seen if p is not None else unseen).append(p if p is not None else self.guess(i))
        if seen or unseen or pos == self.post:
            self.opening = False
        if seen:
            target = min(seen, key=lambda q: self.dist(pos, q))
            if scared:
                return self._toward(legal, pos, target, key=lambda d: abs(d - 3))
            return self._toward(legal, pos, target)
        unseen = [q for q in unseen if self.is_home(q)]
        if unseen:
            # Invader out of sight: walk to where the sonar puts it.
            return self._toward(legal, pos, min(unseen, key=lambda q: self.dist(pos, q)))
        target = self.post
        if not self.opening:
            # Hold the door nearest the enemy closest to our side; scared
            # enemies are not treated as a threat.
            door = None
            for i in opp:
                if game_state.get_agent_state(i).scared_timer > 0:
                    continue
                g = self.guess(i)
                b = min(self.border, key=lambda b: (self.dist(g, b), b))
                k = (self.dist(g, b), b)
                if door is None or k < door[0]:
                    door = (k, b)
            if door is not None:
                target = door[1]
        if pos == target:
            return Directions.STOP
        return self._toward(legal, pos, target)


def create_team(first_index, second_index, is_red, first="AlmaRaider", second="AlmaGuard", **kwargs):
    return [AlmaRaider(first_index), AlmaGuard(second_index)]
