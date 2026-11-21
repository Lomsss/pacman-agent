"""Plain BFS team: the first search most students write.

The attacker runs BFS to the nearest dot, treating squares next to a
visible ghost as walls, and BFS home once it carries 4 or a ghost is near.
The defender runs BFS to the invader it sees, else the last eaten dot,
else the door nearest our food.
"""
from collections import deque

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
from contest.game import Directions


class BFSAgent(ZooAgent):
    def bfs(self, game_state, goals, walls=frozenset(), home_only=False):
        start = self.my_pos(game_state)
        goals = set(goals)
        if not goals:
            return None
        first = {start: None}
        queue = deque([start])
        while queue:
            p = queue.popleft()
            if p in goals and p != start:
                return first[p]
            for n in self.nbrs[p]:
                if n in first or n in walls or (home_only and not self.is_home(n)):
                    continue
                first[n] = first[p] or self.action_between(start, n)
                queue.append(n)
        return None

    def action_between(self, a, b):
        return {(1, 0): Directions.EAST, (-1, 0): Directions.WEST,
                (0, 1): Directions.NORTH, (0, -1): Directions.SOUTH}[(b[0] - a[0], b[1] - a[1])]


class BFSAttacker(BFSAgent):
    def choose_action(self, game_state):
        self.track(game_state)
        pos = self.my_pos(game_state)
        st = game_state.get_agent_state(self.index)
        ghosts = [g[1] for g in self.ghosts(game_state)]
        walls = {n for g in ghosts for n in self.nbrs[g] + [g]}
        food = self.get_food(game_state).as_list()
        near = min((self.dist(pos, g) for g in ghosts), default=99)
        if st.num_carrying >= 4 or len(food) <= 2 or (st.num_carrying and near <= 5) or \
                (st.num_carrying and self.home_dist(pos) + 4 >= game_state.data.timeleft / 4):
            act = self.bfs(game_state, self.border, walls)
        else:
            act = self.bfs(game_state, food, walls)
        return act or self.bfs(game_state, self.border) or Directions.STOP


class BFSDefender(BFSAgent):
    def choose_action(self, game_state):
        self.track(game_state)
        pos = self.my_pos(game_state)
        seen = [t[1] for t in self.invaders(game_state) if t[3]]
        if game_state.get_agent_state(self.index).scared_timer:
            return self.defend(game_state)
        if seen:
            return self.bfs(game_state, seen, home_only=True) or self.defend(game_state)
        if self.last_eaten is not None and self.is_home(self.last_eaten) and pos != self.last_eaten:
            return self.bfs(game_state, [self.last_eaten], home_only=True) or Directions.STOP
        self.last_eaten = None
        food = self.get_food_you_are_defending(game_state).as_list()
        door = min(self.border, key=lambda b: sum(self.dist(b, f) for f in food))
        if pos == door:
            return Directions.STOP
        return self.bfs(game_state, [door], home_only=True) or Directions.STOP


def create_team(first_index, second_index, is_red, **kw):
    return [BFSAttacker(first_index), BFSDefender(second_index)]
