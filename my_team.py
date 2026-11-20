# my_team.py
# ---------------
# Licensing Information: Please do not distribute or publish solutions to this
# project. You are free to use and extend these projects for educational
# purposes. The Pacman AI projects were developed at UC Berkeley, primarily by
# John DeNero and Dan Klein. See http://ai.berkeley.edu.

"""Capture team for the defaultCapture contest.

The raider treats a ghost as extra path cost, grabs the shallow pellets
(most food on this map is a dead end just inside a door) and banks two or
three before a defender can reach that door. The guard holds the door an
invader is actually using, and stays on it for a step after they retreat.
A belief cloud never becomes a wall, and a reply search never overrides
the plan: both of those freeze an attacker against a careful opponent.
"""

from collections import Counter, deque
from heapq import heappop, heappush

from contest.capture_agents import CaptureAgent
from contest.game import Directions
from contest.util import nearest_point

_INF = 10 ** 9
_STEPS = ((1, 0, Directions.EAST), (-1, 0, Directions.WEST),
          (0, 1, Directions.NORTH), (0, -1, Directions.SOUTH))
# Teammates share one process. The lower index clears this each game.
_SHARE = {"sonar": {}, "token": None}


def create_team(first_index, second_index, is_red,
                first="Raider", second="Guard", num_training=0, **kwargs):
    """Tournament entry. No extra options are passed in."""
    return [Raider(first_index), Guard(second_index)]


def _at(pos):
    if pos is None:
        return None
    x, y = nearest_point(pos)
    return int(x), int(y)


class _Maze:
    """Static facts for one layout. defaultCapture is small enough to cache."""

    def __init__(self, walls, red):
        cells = []
        for x in range(walls.width):
            for y in range(walls.height):
                if not walls[x][y]:
                    cells.append((x, y))
        self.cells = set(cells)
        self.edges = {}
        for x, y in cells:
            nbs = []
            for dx, dy, action in _STEPS:
                nxt = (x + dx, y + dy)
                if nxt in self.cells:
                    nbs.append((nxt, action))
            self.edges[(x, y)] = nbs
        self.home = {p for p in self.cells if (p[0] < walls.width // 2) == red}
        self.doors = sorted(
            p for p in self.home if any(q not in self.home for q, _ in self.edges[p])
        )
        self.rows = {}
        for source in self.cells:
            row = {source: 0}
            queue = deque([source])
            while queue:
                pos = queue.popleft()
                for nxt, _ in self.edges[pos]:
                    if nxt not in row:
                        row[nxt] = row[pos] + 1
                        queue.append(nxt)
            self.rows[source] = row
        self.bank = {
            p: min((self.dist(p, door) for door in self.doors), default=99)
            for p in self.cells
        }
        # Peel enemy-side dead ends. The mouth is the last square you must
        # recross to get home, which is what a ghost camps.
        degree = {p: len(nbs) for p, nbs in self.edges.items()}
        leaves = deque(p for p in self.edges if p not in self.home and degree[p] == 1)
        parents = []
        while leaves:
            pos = leaves.popleft()
            for nxt, _ in self.edges[pos]:
                if degree[nxt] <= 0:
                    continue
                parents.append((pos, nxt))
                degree[nxt] -= 1
                if degree[nxt] == 1 and nxt not in self.home:
                    leaves.append(nxt)
                break
            degree[pos] = 0
        self.mouth = {}
        for pos, nxt in reversed(parents):
            self.mouth[pos] = self.mouth.get(nxt, nxt)

    def dist(self, a, b):
        if a == b:
            return 0
        row = self.rows.get(a)
        if row is None:
            return abs(a[0] - b[0]) + abs(a[1] - b[1])
        return row.get(b, 99)

    def routes(self, origin, legal, risk, home_only=False):
        """One search prices every goal. Cost is steps plus danger."""
        cost = {origin: 0}
        first = {origin: Directions.STOP}
        queue = [(0, origin)]
        while queue:
            spent, pos = heappop(queue)
            if spent != cost[pos]:
                continue
            for nxt, action in self.edges[pos]:
                if home_only and nxt not in self.home:
                    continue
                if pos == origin and action not in legal:
                    continue
                new = spent + 1 + risk.get(nxt, 0)
                if new < cost.get(nxt, _INF):
                    cost[nxt] = new
                    first[nxt] = action if pos == origin else first[pos]
                    heappush(queue, (new, nxt))
        return cost, first


class _Track:
    """Where one enemy can be. Position only; no reply forecast."""

    def __init__(self, maze, spawn):
        self.maze = maze
        self.spawn = spawn
        self.belief = {spawn: 1.0}
        self.pac = False
        self.carry = 0
        self.returned = 0

    def update(self, state, index, me, mate, moves, noisy, missing):
        agent = state.get_agent_state(index)
        pac = bool(agent.is_pacman)
        carry = int(agent.num_carrying)
        returned = int(agent.num_returned)
        died = self.pac and (not pac) and self.carry > 0 and returned == self.returned
        self.pac, self.carry, self.returned = pac, carry, returned
        seen = _at(state.get_agent_position(index))
        if seen is not None:
            self.belief = {seen: 1.0}
            return
        if died and self.spawn in self.maze.cells:
            self.belief = {self.spawn: 1.0}
            return
        for _ in range(max(0, moves)):
            self.belief = self._spread(self.belief)
        kept = {}
        for pos, mass in self.belief.items():
            if not self._fits(pos, me, mate, pac, noisy):
                continue
            if pos in missing and pac:
                mass *= 8
            kept[pos] = mass
        if not kept:
            kept = {
                pos: 1.0 for pos in self.maze.cells
                if self._fits(pos, me, mate, pac, noisy)
            }
        if not kept:
            kept = {self.spawn: 1.0}
        # A single hidden pacman standing on the only missing pellet is there.
        if pac and len(missing) == 1:
            food = next(iter(missing))
            if self._fits(food, me, mate, True, noisy):
                self.belief = {food: 1.0}
                return
        ranked = sorted(kept.items(), key=lambda item: item[1], reverse=True)[:48]
        total = sum(mass for _, mass in ranked) or 1.0
        self.belief = {pos: mass / total for pos, mass in ranked}

    def _spread(self, belief):
        spread = Counter()
        for pos, mass in belief.items():
            nbs = self.maze.edges.get(pos, [])
            share = mass / float(1 + len(nbs))
            spread[pos] += share
            for nxt, _ in nbs:
                spread[nxt] += share
        return spread

    def _fits(self, pos, me, mate, pac, noisy):
        if (pos in self.maze.home) != pac:
            return False
        if abs(pos[0] - me[0]) + abs(pos[1] - me[1]) <= 5:
            return False
        if abs(pos[0] - mate[0]) + abs(pos[1] - mate[1]) <= 5:
            return False
        if noisy is None:
            return True
        return abs((abs(pos[0] - me[0]) + abs(pos[1] - me[1])) - noisy) <= 6

    def top(self, k=4):
        return sorted(self.belief.items(), key=lambda item: item[1], reverse=True)[:k]


class _Player(CaptureAgent):
    """Shared planner. Subclasses only set whether they start on defense."""

    guard = False

    def register_initial_state(self, game_state):
        CaptureAgent.register_initial_state(self, game_state)
        self.maze = _Maze(game_state.get_walls(), self.red)
        self.dist = self.maze.dist
        self.enemies = list(self.get_opponents(game_state))
        self.mate_index = next(i for i in self.get_team(game_state) if i != self.index)
        self.tracks = {
            i: _Track(self.maze, _at(game_state.get_initial_agent_position(i)))
            for i in self.enemies
        }
        foods = self.get_food(game_state).as_list()
        defended = self.get_food_you_are_defending(game_state).as_list()
        self.quota = (len(foods) + len(defended)) / 2 - 2
        self.goal = None
        self.recent = deque(maxlen=10)
        self.last_time = int(game_state.data.timeleft or 1200)
        self.watch = self._opening_door(game_state)
        self.held_door = None
        self.held_for = 0
        self._defended = set(map(_at, self.get_food_you_are_defending(game_state).as_list()))
        walls = game_state.get_walls()
        token = (self.red, walls.width, walls.height, len(self.maze.cells), self.quota)
        if self.index == min(self.get_team(game_state)) or _SHARE["token"] != token:
            _SHARE["token"] = token
            _SHARE["sonar"] = {}

    def choose_action(self, game_state):
        legal = game_state.get_legal_actions(self.index)
        try:
            action = self._choose(game_state, legal)
        except Exception:
            action = None
        if action not in legal:
            action = self._toward_home(game_state, legal)
        return action

    def _choose(self, game_state, legal):
        me = game_state.get_agent_state(self.index)
        pos = _at(me.get_position())
        mate = _at(game_state.get_agent_position(self.mate_index))
        self.recent.append(pos)
        missing = self._missing(game_state)
        estimates = self._observe(game_state, pos, mate, missing)
        invaders = [i for i in self.enemies if game_state.get_agent_state(i).is_pacman]
        moves = (int(game_state.data.timeleft) + 3) // 4
        score = self.get_score(game_state)
        feast = self._feast(game_state)
        emergency = (len(invaders) >= 2 and (self.guard or not me.is_pacman)) or (
            score > 0 and moves < 28
        )
        # A second attacker is safe only while nobody is near our doors.
        # The moment an invader exists, the guard is already on the way home.
        border_clear = not invaders and not self._border_threat(estimates)
        assist = self.guard and moves > 45 and not emergency and (feast or border_clear)
        visible_near = (not me.is_pacman) and any(
            self.dist(pos, _at(game_state.get_agent_position(i))) <= 2
            for i in invaders if game_state.get_agent_position(i) is not None
        )
        defend = ((self.guard and not assist) or emergency or visible_near) and not me.is_pacman
        if defend:
            return self._defend(game_state, pos, mate, invaders, estimates, legal)
        recall = self.guard and not feast and (bool(invaders) or self._border_threat(estimates))
        return self._raid(game_state, pos, mate, estimates, legal, moves, recall or emergency)

    def _observe(self, game_state, pos, mate, missing):
        now = int(game_state.data.timeleft)
        passed = max(0, self.last_time - now)
        self.last_time = now
        distances = game_state.get_agent_distances() or []
        noisy = {}
        estimates = {}
        for index in self.enemies:
            moved = Counter()
            cursor = self.index
            for _ in range(passed):
                cursor = (cursor - 1) % 4
                moved[cursor] += 1
            moves = moved[index]
            reading = int(distances[index]) if distances else None
            noisy[index] = reading
            self.tracks[index].update(game_state, index, pos, mate, moves, reading, missing)
            estimates[index] = self.tracks[index].top()
        _SHARE["sonar"][self.index] = {"at": now, "pos": pos, "noisy": noisy}
        self._fuse(now, estimates)
        return estimates

    def _fuse(self, now, estimates):
        """Drop particles the teammate's sonar already rules out."""
        pack = None
        mate_index = None
        for key, value in _SHARE["sonar"].items():
            if key != self.index:
                pack, mate_index = value, key
        if not pack or now - pack["at"] <= 0 or now - pack["at"] > 3:
            return
        moved = set()
        cursor = mate_index
        while cursor != self.index:
            moved.add(cursor)
            cursor = (cursor + 1) % 4
        for index, particles in list(estimates.items()):
            reading = pack["noisy"].get(index)
            if reading is None:
                continue
            tol = 7 if index in moved else 6
            mx, my = pack["pos"]
            kept = [
                (pos, mass) for pos, mass in particles
                if abs(abs(pos[0] - mx) + abs(pos[1] - my) - reading) <= tol
            ]
            if kept:
                estimates[index] = kept

    def _missing(self, game_state):
        current = set(map(_at, self.get_food_you_are_defending(game_state).as_list()))
        previous = getattr(self, "_defended", current)
        self._defended = current
        return previous - current

    def _feast(self, game_state):
        timers = []
        for index in self.enemies:
            agent = game_state.get_agent_state(index)
            if agent.is_pacman:
                return False
            timers.append(int(agent.scared_timer))
        return bool(timers) and min(timers) > 8

    def _raid(self, game_state, pos, mate, estimates, legal, moves, recall):
        me = game_state.get_agent_state(self.index)
        carried = int(me.num_carrying)
        food = [_at(bit) for bit in self.get_food(game_state).as_list()]
        capsules = {_at(cap) for cap in self.get_capsules(game_state)}
        feast = self._feast(game_state)
        risk, danger, ghosts = self._pressure(game_state, pos, estimates, food, capsules, feast)
        for square, count in Counter(self.recent).items():
            risk[square] += 0.7 * max(0, count - 1)
        cost, action = self.maze.routes(pos, legal, risk)
        doors = [door for door in self.maze.doors if door in cost]
        if not doors:
            return legal[0]
        active = self._visible_ghosts(game_state, scared_max=4)
        bank = min(doors, key=lambda door: self._exit_cost(pos, door, cost, active))
        returned = sum(game_state.get_agent_state(i).num_returned for i in self.agentsOnTeam)
        limit = 2 if self.guard else (8 if feast else (4 if self.get_score(game_state) < 0 else 3))
        near = min((self.dist(pos, bit) for bit in food), default=99)
        home = self.maze.bank[pos]
        cash = carried > 0 and (
            returned + carried >= self.quota
            or moves <= home + 6
            or carried >= limit
            or (not feast and self._exit_threatened(pos, bank, estimates, game_state))
            or (feast and self._scare_left(game_state) <= home + 2)
            or near >= home + 4
        )
        if me.is_pacman and (cash or recall or not food):
            self.goal = bank
            return self._safe(pos, action[bank], active, capsules, legal)
        goals = [bit for bit in food if bit in cost] + [cap for cap in capsules if cap in cost]
        if feast:
            for index in self.enemies:
                seen = _at(game_state.get_agent_position(index))
                timer = int(game_state.get_agent_state(index).scared_timer)
                if seen in cost and 1 < timer and self.dist(pos, seen) < timer:
                    goals.append(seen)
        if not goals:
            return self._safe(pos, action[bank], active, capsules, legal)
        bonus = 6 if (len(food) <= 6 or self._blocked_border(estimates, game_state)) else 2

        def price(goal):
            value = cost[goal] + 0.8 * self.maze.bank.get(goal, 8) + danger.get(goal, 0)
            if goal in capsules:
                value -= bonus
            elif goal not in food:
                value -= 7  # a scared ghost, removed for the rest of the feast
            if self.guard:
                # Take a different door from the raider. Eight doors, one each.
                value -= 0.4 * min(14, self.dist(mate, goal))
            elif mate not in self.maze.home and self.dist(mate, goal) + 1 < self.dist(pos, goal):
                value += 5
            if goal == self.goal:
                value -= 1.4
            return value

        self.goal = min(goals, key=price)
        step = action.get(self.goal, Directions.STOP)
        if me.is_pacman or pos not in self.maze.home:
            return self._safe(pos, step, active, capsules, legal)
        return step if step in legal else legal[0]

    def _pressure(self, game_state, pos, estimates, food, capsules, feast):
        risk = Counter()
        danger = {}
        ghosts = []
        if feast:
            return risk, danger, ghosts
        for index, particles in estimates.items():
            agent = game_state.get_agent_state(index)
            if agent.is_pacman or int(agent.scared_timer) > 5 or not particles:
                continue
            seen = _at(game_state.get_agent_position(index))
            use = [(seen, 1.0)] if seen is not None else particles
            if seen is None and particles[0][1] < 0.2:
                use = particles[:1]
            for ghost, weight in use:
                ghosts.append(ghost)
                for square in self.maze.cells:
                    if square in self.maze.home or square in capsules:
                        continue
                    gap = self.dist(ghost, square)
                    if gap < 5:
                        risk[square] += weight * (28, 16, 5, 1.5, 0.35)[gap]
                for bit in food:
                    mouth = self.maze.mouth.get(bit)
                    if mouth is None:
                        continue
                    slack = self.dist(ghost, mouth) - self.dist(pos, bit) - self.dist(bit, mouth)
                    if slack <= 1:
                        danger[bit] = danger.get(bit, 0) + weight * min(14, 2 + 2 * self.dist(bit, mouth))
        return risk, danger, ghosts

    def _border_threat(self, estimates):
        for particles in estimates.values():
            if not particles or particles[0][1] < 0.15:
                continue
            ghost = particles[0][0]
            if any(self.dist(ghost, door) <= 10 for door in self.maze.doors):
                return True
        return False

    def _exit_threatened(self, pos, door, estimates, game_state):
        away = self.dist(pos, door)
        for index, particles in estimates.items():
            agent = game_state.get_agent_state(index)
            if agent.is_pacman or int(agent.scared_timer) > 4 or not particles:
                continue
            seen = _at(game_state.get_agent_position(index))
            if seen is None and particles[0][1] < 0.34:
                continue
            ghost = seen or particles[0][0]
            if self.dist(ghost, door) <= away + 1:
                return True
        return False

    def _blocked_border(self, estimates, game_state):
        """A defender sitting on a door is why we spend the trip on a capsule."""
        near = 0
        for index, particles in estimates.items():
            agent = game_state.get_agent_state(index)
            if agent.is_pacman or int(agent.scared_timer) > 0 or not particles:
                continue
            ghost = _at(game_state.get_agent_position(index)) or particles[0][0]
            if any(self.dist(ghost, door) <= 2 for door in self.maze.doors):
                near += 1
        return near > 0

    def _scare_left(self, game_state):
        return min(int(game_state.get_agent_state(i).scared_timer) for i in self.enemies)

    def _visible_ghosts(self, game_state, scared_max):
        found = []
        for index in self.enemies:
            agent = game_state.get_agent_state(index)
            seen = _at(game_state.get_agent_position(index))
            if seen is None or agent.is_pacman or int(agent.scared_timer) > scared_max:
                continue
            found.append(seen)
        return found

    def _exit_cost(self, pos, door, cost, ghosts):
        if not ghosts:
            return cost[door]
        lead = min(self.dist(ghost, door) for ghost in ghosts) - self.dist(pos, door)
        return cost[door] + 4 * max(0, 2 - lead)

    def _safe(self, pos, planned, ghosts, capsules, legal):
        """A ghost we can see gets one move before we do. Don't step into it."""
        if not ghosts or planned not in legal:
            return planned if planned in legal else legal[0]

        def slack(square):
            if square in self.maze.home or square in capsules:
                return 8
            return min(self.dist(ghost, square) for ghost in ghosts)

        options = [(pos, Directions.STOP)] + self.maze.edges[pos]
        options = [(square, action) for square, action in options if action in legal]
        dest = next((square for square, action in options if action == planned), pos)
        if slack(dest) > 1:
            return planned
        safe = [(square, action) for square, action in options if slack(square) > 1]
        if not safe:
            return planned
        return min(safe, key=lambda item: (self.recent.count(item[0]), -slack(item[0])))[1]

    def _defend(self, game_state, pos, mate, invaders, estimates, legal):
        me = game_state.get_agent_state(self.index)
        cost, action = self.maze.routes(pos, legal, {}, home_only=True)
        doors = [door for door in self.maze.doors if door in cost]
        if not doors:
            return legal[0]
        if int(me.scared_timer) > 0 and invaders:
            return self._shadow(pos, invaders, estimates, cost, legal)
        caught = self._retreat_door(game_state, doors)
        if caught is not None and caught in action:
            self.held_door, self.held_for = caught, 8
            return action[caught]
        sightings = []
        for index in invaders:
            for square, weight in estimates.get(index, []):
                if square in self.maze.home:
                    sightings.append((index, square, weight))
        if sightings:
            return self._intercept(game_state, pos, mate, sightings, cost, action, doors)
        if self.held_door in doors and self.held_for > 0:
            self.held_for -= 1
            return action[self.held_door]
        target = self._patrol_door(estimates, doors)
        self.held_door, self.held_for = target, 0
        return action[target]

    def _shadow(self, pos, invaders, estimates, cost, legal):
        threats = []
        for index in invaders:
            for square, _ in estimates.get(index, []):
                if square in self.maze.home:
                    threats.append(square)
        if not threats:
            return Directions.STOP if Directions.STOP in legal else legal[0]

        def rank(square):
            gap = min(self.dist(square, threat) for threat in threats)
            return (max(0, 3 - gap), abs(gap - 3))

        options = [(pos, Directions.STOP)] + self.maze.edges[pos]
        options = [(square, action) for square, action in options if action in legal and square in cost]
        return min(options, key=lambda item: rank(item[0]))[1]

    def _retreat_door(self, game_state, doors):
        """They stepped off our door. The next move is usually back through it."""
        previous = self.get_previous_observation()
        if previous is None:
            return None
        for index in self.enemies:
            if game_state.get_agent_state(index).is_pacman:
                continue
            if not previous.get_agent_state(index).is_pacman:
                continue
            was = _at(previous.get_agent_position(index))
            now = _at(game_state.get_agent_position(index))
            if was in doors and now is not None and self.dist(was, now) <= 2:
                return was
        return None

    def _intercept(self, game_state, pos, mate, sightings, cost, action, doors):
        def rank(item):
            index, square, weight = item
            carried = int(game_state.get_agent_state(index).num_carrying)
            closer = self.dist(mate, square) + 1 < cost.get(square, 99)
            return (cost.get(square, 99) + (4 if closer else 0) - 3 * min(carried, 4), -weight)

        index, where, _ = min(sightings, key=rank)
        if cost.get(where, 99) <= 1 and game_state.get_agent_position(index) is not None:
            self.held_door = where if where in doors else self._door_of(where)
            self.held_for = 6
            return action.get(where, Directions.STOP)
        carried = int(game_state.get_agent_state(index).num_carrying)
        foods = [_at(bit) for bit in self.get_food_you_are_defending(game_state).as_list()]
        if carried >= 2 or not foods:
            goal = min(doors, key=lambda door: self.dist(where, door))
        else:
            goal = min(foods, key=lambda bit: self.dist(where, bit))
        span = self.dist(where, goal)
        meet = [
            square for square in cost
            if cost[square] <= self.dist(where, square)
            and self.dist(where, square) + self.dist(square, goal) <= span + 1
        ]
        target = min(meet, key=lambda square: (self.dist(where, square), cost[square])) if meet else where
        if target in doors:
            self.held_door, self.held_for = target, 6
        return action.get(target, action.get(min(doors, key=cost.get), Directions.STOP))

    def _patrol_door(self, estimates, doors):
        foods = list(self._defended)
        best_door = self.watch if self.watch in doors else doors[len(doors) // 2]
        best_eta = 99
        for index, particles in estimates.items():
            if not particles:
                continue
            anchor = particles[0][0]
            if anchor in self.maze.home or not foods:
                continue
            food = min(foods, key=lambda bit: self.dist(anchor, bit))
            door = self._door_of(food)
            eta = self.dist(anchor, door)
            if eta < best_eta and door in doors:
                best_eta = eta
                best_door = door
        return best_door

    def _door_of(self, goal):
        return min(self.maze.doors, key=lambda door: self.dist(goal, door))

    def _opening_door(self, game_state):
        """Door on the shortest path from their nearest spawn to our nearest food."""
        foods = [_at(bit) for bit in self.get_food_you_are_defending(game_state).as_list()]
        spawns = [_at(game_state.get_initial_agent_position(i)) for i in self.enemies]
        if not foods or not self.maze.doors:
            return None
        spawn = min(spawns, key=lambda spot: min(self.dist(spot, bit) for bit in foods))
        food = min(foods, key=lambda bit: self.dist(spawn, bit))
        return self._door_of(food)

    def _toward_home(self, game_state, legal):
        pos = _at(game_state.get_agent_state(self.index).get_position())
        if pos is None:
            return legal[0]
        best, best_dist = legal[0], 99
        for action in legal:
            if action == Directions.STOP:
                continue
            dx, dy = {Directions.NORTH: (0, 1), Directions.SOUTH: (0, -1),
                      Directions.EAST: (1, 0), Directions.WEST: (-1, 0)}[action]
            nxt = (pos[0] + dx, pos[1] + dy)
            if self.maze.bank.get(nxt, 99) < best_dist:
                best, best_dist = action, self.maze.bank[nxt]
        return best


class Raider(_Player):
    """Brings food home. Starts on offense."""


class Guard(_Player):
    """Holds our doors. Joins the raid only while every enemy ghost is scared."""

    guard = True
