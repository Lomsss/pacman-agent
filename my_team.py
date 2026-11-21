"""Behavioural proxy of the student team "M&M", rebuilt from two contest replays.

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
"""

from collections import deque

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

GHOST_NEAR = 5      # carry home with any dot once a ghost is this close (150100 ply 188)
SCARED_SAFE = 2     # a ghost scared for at most this many more moves is a threat again


class MMAgent(ZooAgent):
    def register_initial_state(self, game_state):
        super().register_initial_state(game_state)
        self.home_cells = [c for c in self.cells if self.is_home(c)]

    def bfs_from(self, sources, blocked=frozenset(), home_only=False):
        """Maze distance from the nearest source, never entering blocked."""
        dist = {}
        queue = deque()
        for s in sources:
            if s not in blocked and s not in dist:
                dist[s] = 0
                queue.append(s)
        while queue:
            p = queue.popleft()
            for n in self.nbrs[p]:
                if n in dist or n in blocked or (home_only and not self.is_home(n)):
                    continue
                dist[n] = dist[p] + 1
                queue.append(n)
        return dist

    def pick(self, game_state, score, allowed=None):
        """First legal action with the lowest score (engine order breaks ties)."""
        pos = self.my_pos(game_state)
        best, best_v = Directions.STOP, INF
        for action in game_state.get_legal_actions(self.index):
            nxt = self.step(pos, action)
            if allowed is not None and not allowed(nxt):
                continue
            v = score(nxt)
            if v < best_v:
                best, best_v = action, v
        return best


class MMAttacker(MMAgent):
    def choose_action(self, game_state):
        try:
            return self._choose(game_state)
        except Exception:
            return self.toward(game_state, min(self.border, key=lambda b: self.dist(self.my_pos(game_state), b)))

    def _choose(self, game_state):
        pos = self.my_pos(game_state)
        carry = game_state.get_agent_state(self.index).num_carrying
        food = [tuple(f) for f in self.get_food(game_state).as_list()]
        caps = [tuple(c) for c in self.get_capsules(game_state)]
        ghosts = [g[1] for g in self.ghosts(game_state) if g[2] <= SCARED_SAFE]
        # Only the nearest visible ghost is avoided: its square and the squares
        # next to it become walls. Avoiding every ghost does not reproduce
        # 150100 (it would leave the stalemate at ply 516 the other way).
        nearest = sorted(ghosts, key=lambda g: self.dist(pos, g))[:1]
        blocked = set(nearest)
        for g in nearest:
            blocked.update(self.nbrs[g])
        near = min((self.dist(pos, g) for g in ghosts), default=INF)
        moves_left = game_state.data.timeleft // 4
        going_home = carry > 0 and (
            carry >= len(food) // 4 or len(food) <= 2 or near <= GHOST_NEAR or
            self.home_dist(pos) + 2 >= moves_left)
        if going_home:
            goals = list(self.border) + (caps if near <= GHOST_NEAR else [])
        else:
            goals = food
        legal = game_state.get_legal_actions(self.index)
        # The replays never box it in, and it never Stops as attacker (0 of
        # 600 moves, even 172 moves next to a ghost). So when the walls cut
        # every path, relax them (ghost square only, then none) rather than
        # wait in a pocket.
        for walls in (blocked, set(nearest), set()):
            dist = self.bfs_from(goals, walls)
            if any(self.step(pos, a) in dist for a in legal):
                return self.pick(game_state, lambda n: dist.get(n, INF))
        return self.pick(game_state, lambda n: -min((self.dist(n, g) for g in ghosts), default=0))


class MMDefender(MMAgent):
    def register_initial_state(self, game_state):
        super().register_initial_state(game_state)
        self.alert = None

    def choose_action(self, game_state):
        try:
            return self._choose(game_state)
        except Exception:
            return Directions.STOP

    def _choose(self, game_state):
        pos = self.my_pos(game_state)
        defend = set(tuple(f) for f in self.get_food_you_are_defending(game_state).as_list())
        eaten = self.prev_defend - defend
        self.prev_defend = defend
        if eaten:
            self.alert = min(eaten, key=lambda f: self.dist(pos, f))
        seen = [p for _, p, _, vis in self.invaders(game_state) if vis]
        home = self.is_home
        if seen:
            target = min(seen, key=lambda p: self.dist(pos, p))
            self.alert = target
            if game_state.get_agent_state(self.index).scared_timer > 0:
                return self.pick(game_state, lambda n: abs(self.dist(n, target) - 2), home)
        else:
            if self.alert is not None and pos == self.alert:
                self.alert = None
            if self.alert is not None:
                target = self.alert
            else:
                target = min(self.border, key=lambda b: sum(self.dist(b, f) for f in defend))
        # Paths stay on our side (150085 ply 939: it walks the long way round
        # inside its half rather than the short way through enemy ground).
        dist = self.bfs_from([target], home_only=True)
        if pos not in dist:
            self.alert = None
            return self.pick(game_state, lambda n: self.dist(n, target), home)
        return self.pick(game_state, lambda n: dist.get(n, INF), home)


def create_team(first_index, second_index, is_red, **kwargs):
    return [MMAttacker(first_index), MMDefender(second_index)]
