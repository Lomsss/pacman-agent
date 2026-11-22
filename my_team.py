# Licensing Information: Please do not distribute or publish solutions to this
# project. You are free to use and extend these projects for educational
# purposes. The Pacman AI projects were developed at UC Berkeley, primarily by
# John DeNero and Dan Klein. See http://ai.berkeley.edu.
"""UPF capture pair. All live inputs come from this agent's observation."""
import time
from collections import Counter, deque
from heapq import heappop, heappush

from contest.capture_agents import CaptureAgent
from contest.distance_calculator import get_grids_2D
from contest.game import Directions
from contest.util import nearest_point

INF = float("inf")
SIGHT = 5  # the engine shows an enemy within this Manhattan distance of either of us
STEPS = ((1, 0, Directions.EAST), (-1, 0, Directions.WEST),
         (0, 1, Directions.NORTH), (0, -1, Directions.SOUTH))
# Blue sees the map rotated by 180 degrees, so its first step to try is the
# mirror image of red's. Every tie then breaks the same way for both colours.
BLUE_STEPS = ((-1, 0, Directions.WEST), (1, 0, Directions.EAST),
              (0, -1, Directions.SOUTH), (0, 1, Directions.NORTH))
# Trip planning is capped by work, never by the clock, so seeded games replay
# exactly: targets drawn, stops per trip, exits tried, trips scored, ghost squares moved.
TRIP_POOL, TRIP_DEPTH, TRIP_DOORS = 8, 3, 3
TRIP_EVALS, TRIP_STEPS = 600, 60000
# The raider rarely banks right after a trip, so the return leg weighs what
# the single-target price gives it; a one-stop trip then ranks as that price.
TRIP_HOME = 0.36


def create_team(first_index, second_index, is_red, first="Raider", second="Sentinel",
                num_training=0, prediction="1", lookahead="0", **kwargs):
    """Default to position tracking. Set prediction=0 or test one-turn replies with lookahead=1."""
    classes = {"Raider": Raider, "Sentinel": Sentinel}
    use_prediction = str(prediction).lower() not in ("0", "false", "off")
    use_replies = str(lookahead).lower() in ("1", "true", "on")
    return [classes.get(first, Raider)(first_index, use_prediction, use_replies),
            classes.get(second, Sentinel)(second_index, use_prediction, use_replies)]


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class Maze:
    def __init__(self, walls, red):
        cells = set(walls.as_list(False))
        # Tie-breaks follow each team's own view of the map: blue's key is
        # red's after a 180-degree rotation, so both colours play the same game.
        self.key = {p: p if red else (walls.width - 1 - p[0], walls.height - 1 - p[1]) for p in cells}
        steps = STEPS if red else BLUE_STEPS
        self.edges = {p: [((p[0] + dx, p[1] + dy), action) for dx, dy, action in steps
                          if (p[0] + dx, p[1] + dy) in cells] for p in self.order(cells)}
        self.home = {p for p in cells if (p[0] < walls.width // 2) == red}
        self.doors = self.order(p for p in self.home if any(q not in self.home for q, _ in self.edges[p]))
        # Breadth-first search (BFS) gives shortest path lengths on unit-cost edges.
        # Repeat from each source and cache its distance row for move decisions.
        # On oversized boards keep only crossing rows and use Manhattan elsewhere.
        sources = self.edges if len(cells) <= 650 else self.doors[:32]
        self.rows = {}
        for source in sources:
            row = {source: 0}
            queue = deque([source])
            while queue:
                p = queue.popleft()
                for q, _ in self.edges[p]:
                    if q not in row:
                        row[q] = row[p] + 1
                        queue.append(q)
            self.rows[source] = row
        self.bank = {p: min((self.dist(p, b) for b in self.doors), default=999) for p in cells}
        # Graph pruning by degree identifies dead ends and their escape mouths.
        # Peel leaves on the enemy side. A raider below a peeled cell must
        # revisit its mouth before it can bank, even in a branching cul-de-sac.
        self.mouth = self.peel(lambda p: p not in self.home)
        # Our own pockets trap invaders the same way: whoever holds the mouth
        # first keeps an invader below it from getting home.
        self.home_mouth = {p: m for p, m in self.peel(lambda p: p in self.home).items() if m in self.home}

    def peel(self, side):
        degree = {p: len(edges) for p, edges in self.edges.items()}
        leaves = deque(p for p in self.edges if side(p) and degree[p] == 1)
        parents = []
        while leaves:
            p = leaves.popleft()
            for q, _ in self.edges[p]:
                if degree[q] > 0:
                    parents.append((p, q))
                    degree[q] -= 1
                    if degree[q] == 1 and side(q):
                        leaves.append(q)
                    break
            degree[p] = 0
        mouth = {}
        for p, q in reversed(parents):
            mouth[p] = mouth.get(q, q)
        return mouth

    def contain(self, capsules):
        """Solve our ghost against one invader on our side as a two-player game.
        lost[d * n + i] is set when, with the invader to move from i and our ghost
        on d, the invader can force its way home, onto a capsule or out of our
        ghost's sight (where we could no longer follow the solution) whatever we do."""
        home = self.order(self.home)
        self.cix = ix = {p: k for k, p in enumerate(home)}
        n = len(home)
        nbr = [[ix[q] for q, _ in self.edges[p] if q in ix] + [ix[p]] for p in home]
        # A capsule is a goal even under our ghost: the engine eats it before checking the catch.
        out = [any(q not in self.home for q, _ in self.edges[p]) for p in home]
        caps = [[ix[q] for q, _ in self.edges[p] if q in capsules] for p in home]
        lost = bytearray(n * n)
        beaten = bytearray(n * n)
        # Ghost replies not yet known to lose; a ghost that can step onto the invader never loses.
        left = [n * n if i in nbr[d] else len(nbr[d]) for d in range(n) for i in range(n)]
        queue = deque((0, d, i) for d in range(n) for i in range(n)
                      if i != d and (out[i] or caps[i] or
                                     any(manhattan(home[d], home[j]) > SIGHT for j in nbr[i])))
        for _, d, i in queue:
            lost[d * n + i] = 1
        while queue:
            ghost_turn, d, i = queue.popleft()
            if not ghost_turn:
                for e in nbr[d]:
                    k = e * n + i
                    if e != i and not beaten[k]:
                        left[k] -= 1
                        if not left[k]:
                            beaten[k] = 1
                            queue.append((1, e, i))
            else:
                for j in nbr[i]:
                    k = d * n + j
                    if j != d and not lost[k]:
                        lost[k] = 1
                        queue.append((0, d, j))
        self.lost = lost

    def holds(self, d, i):
        """Our ghost's moves from d (staying included) after which an invader on i
        can never get home: eating it, or any square the solved game keeps."""
        ix, n = self.cix, len(self.cix)
        if d not in ix or i not in ix:
            return []
        return [q for q in [q for q, _ in self.edges[d]] + [d]
                if q in ix and (q == i or not self.lost[ix[q] * n + ix[i]])]

    def order(self, squares):
        return sorted(squares, key=self.key.__getitem__)

    def dist(self, p, q):
        if p in self.rows:
            return self.rows[p].get(q, 999)
        if q in self.rows:
            return self.rows[q].get(p, 999)
        return manhattan(p, q)

    # Uniform-cost search (Dijkstra) expands the lowest cumulative cost first.
    # The expansion cap bounds work, and first actions are shared across goals.
    def routes(self, origin, legal, risk, home_only=False, parent=None):
        """Multi-goal UCS. Path cost is moves plus nonnegative danger in move units.
        First actions let us price all food and all exits with one search.
        A parent dict, if given, records each square's predecessor."""
        cost = {origin: 0}
        action = {origin: Directions.STOP}
        queue = [(0, self.key[origin], origin)]
        expanded = 0
        while queue and expanded < 850:
            g, _, p = heappop(queue)
            if g != cost[p]:
                continue
            expanded += 1
            for q, step in self.edges[p]:
                if (home_only and q not in self.home) or (p == origin and step not in legal):
                    continue
                new = g + 1 + risk.get(q, 0)
                if new < cost.get(q, INF):
                    cost[q] = new
                    action[q] = step if p == origin else action[p]
                    if parent is not None:
                        parent[q] = p
                    heappush(queue, (new, self.key[q], q))
        return cost, action

    @staticmethod
    def trace(parent, q):
        # Walk predecessors back to the search origin, which has none.
        path = [q]
        while path[-1] in parent:
            path.append(parent[path[-1]])
        return path[::-1]

    def descent(self, q, goal):
        # Shortest path by distance rows; the first closer edge keeps ties canonical.
        path = [q]
        while path[-1] != goal:
            here = self.dist(path[-1], goal)
            step = next((n for n, _ in self.edges[path[-1]] if self.dist(n, goal) == here - 1), None)
            if step is None or len(path) > 200:
                return None
            path.append(step)
        return path

    def chase(self, squares, target):
        """Squares a chasing ghost may occupy after one move: from each possible
        square, every stay-or-step on its own side that closes on target most."""
        reach = set()
        for g in squares:
            options = [g] + [n for n, _ in self.edges[g] if n not in self.home]
            best = min(self.dist(n, target) for n in options)
            reach.update(n for n in options if self.dist(n, target) == best)
        if len(reach) > 12:
            # Keep the set small; the closest squares are the ones that catch us.
            reach = set(sorted(reach, key=lambda n: (self.dist(n, target), self.key[n]))[:12])
        return reach

    def survive(self, path, ghosts, t, capsules, bank):
        """Walk path[1:] against chasing ghosts given as (squares, scared_timer).
        Returns (verdict, ghosts, t): True once a capsule (or home, if bank) is
        reached, False if caught, None if the path ends with us still exposed."""
        for q in path[1:]:
            t += 1
            if q in capsules or (bank and q in self.home):
                return True, ghosts, t
            # A ghost still scared at this time cannot catch us.
            if any(q in squares for squares, scared in ghosts if scared <= t):
                return False, ghosts, t
            ghosts = [(self.chase(squares, q), scared) for squares, scared in ghosts]
            if any(q in squares for squares, scared in ghosts if scared <= t):
                return False, ghosts, t
        return None, ghosts, t


class OpponentModel:
    """Bounded histogram filter with a one-turn, goal-directed reply model."""

    def __init__(self, maze, spawn):
        self.maze = maze
        self.belief = {spawn: 1.0}
        self.last_visible = spawn

    def update(self, state, index, me, mate, missing):
        visible = state.get_agent_position(index)
        invader = state.get_agent_state(index).is_pacman
        direction = None
        if visible is not None:
            q = nearest_point(visible)
            if self.last_visible is not None:
                direction = (q[0] - self.last_visible[0], q[1] - self.last_visible[1])
            self.last_visible = q
            self.belief = {q: 1.0}
            return [(q, 1.0)], direction
        self.last_visible = None
        reading = state.get_agent_distances()

        def compatible(q):
            return ((q in self.maze.home) == invader and manhattan(me, q) > 5 and
                    manhattan(mate, q) > 5 and (not reading or
                    state.get_distance_prob(manhattan(me, q), reading[index]) > 0))
        # Approximate Bayes filtering predicts a distribution over hidden tiles.
        # Then use visibility and sonar compatibility, weight missing food, and
        # normalize the most likely tiles to get the next belief state.
        # Between consecutive grid turns each opponent normally had one move.
        # Standing still also covers an opponent yet to move on the first turn.
        spread = Counter()
        for source, mass in self.belief.items():
            neighbors = self.maze.edges[source]
            share = mass / (1 + len(neighbors))
            spread[source] += share
            for q, _ in neighbors:
                spread[q] += share
        posterior = Counter({q: w for q, w in spread.items() if compatible(q)})
        if not posterior:  # e.g. respawn or pruning eliminated the true branch
            posterior.update(q for q in self.maze.edges if compatible(q))
        if invader:
            # Either invader could be responsible. A bite raises likelihood
            # at a feasible cell while retaining both prior distributions.
            for q in missing:
                if q in posterior:
                    posterior[q] *= 9
        top = posterior.most_common(40)
        total = sum(w for _, w in top)
        self.belief = {q: w / total for q, w in top}
        # Preserve unrepresented mass as uncertainty in the action evaluation.
        return list(self.belief.items())[:4], direction

    def replies(self, sources, direction, goals, flee):
        # Optional one-step lookahead weights opponent replies by probability.
        # A bounded forecast uses up to 4 sources, 5 replies and 3 goals.
        # A nearer goal has greater prior weight. A legal step that reduces
        # distance to it is more likely; matching visible motion breaks ties.
        forecast = Counter()
        dist = self.maze.dist
        for q, mass in sources:
            likely = sorted(goals, key=lambda g: dist(q, g))[:3]
            if not likely:
                continue
            weights = [1.0 / (1 + dist(q, g) - dist(q, likely[0])) for g in likely]
            options = [(q, Directions.STOP)] + self.maze.edges[q]
            scores = []
            for n, _ in options:
                value = 0.0
                for g, w in zip(likely, weights):
                    gain = dist(q, g) - dist(n, g)
                    if flee:
                        gain = -gain
                    step_weight = {1: 4.0, 0: 1.0, -1: 0.35}.get(gain, 1.0)
                    value += w * step_weight
                if direction == (n[0] - q[0], n[1] - q[1]):
                    value *= 1.6
                scores.append(value)
            total = sum(scores)
            for (n, _), value in zip(options, scores):
                forecast[n] += mass * value / total
        return forecast


class CapturePlayer(CaptureAgent):
    guarding = False

    def __init__(self, index, prediction=True, lookahead=False):
        super().__init__(index)
        self.prediction = prediction
        self.lookahead = lookahead

    def register_initial_state(self, state):
        # Replace the base class's eager Dijkstra distancer with unit-edge BFS.
        self.red = state.is_on_red_team(self.index)
        self.register_team(self.get_team(state))
        self.mate = next(i for i in self.agentsOnTeam if i != self.index)
        self.enemies = self.get_opponents(state)
        self.maze = Maze(state.get_walls(), self.red)
        self.dist = self.maze.dist
        # shortcut: capsules eaten later still count as invader goals, which only makes holding stricter.
        self.maze.contain(set(self.get_capsules_you_are_defending(state)))
        self.defended = self.resources(state)
        self.quota = (len(self.get_food(state).as_list()) +
                      len(self.get_food_you_are_defending(state).as_list())) / 2 - 2
        self.recent = deque(maxlen=12)
        self.goal = None
        self.goal_hist = deque(maxlen=4)
        self.taboo = {}
        self.lock_goal, self.lock = None, 0
        self.bite = None
        self.bite_age = 99
        self.models = {i: OpponentModel(self.maze, state.get_initial_agent_position(i))
                       for i in self.enemies} if self.prediction else {}
        self.forecast = {}

    def get_maze_distance(self, pos1, pos2):
        # Keep the CaptureAgent distance API available, including half steps.
        return min((self.dist(a, b) + da + db
                    for a, da in get_grids_2D(pos1) if a in self.maze.edges
                    for b, db in get_grids_2D(pos2) if b in self.maze.edges), default=INF)

    def resources(self, state):
        return set(self.get_food_you_are_defending(state).as_list()) | set(self.get_capsules_you_are_defending(state))

    def observe(self, state, p, mate, missing):
        if not self.prediction:
            return {i: [(nearest_point(state.get_agent_position(i)), 1.0)]
                    if state.get_agent_position(i) is not None else [] for i in self.enemies}
        estimates = {}
        for i in self.enemies:
            enemy = state.get_agent_state(i)
            sources, direction = self.models[i].update(state, i, p, mate, missing)
            estimates[i] = sources
            if not self.lookahead:
                continue
            if enemy.is_pacman:
                goals = (self.maze.doors if enemy.num_carrying >= 2 else
                         self.maze.order(self.defended) or self.maze.doors)
            else:
                goals = [q for q in (p, mate) if q not in self.maze.home] or self.maze.doors
            self.forecast[i] = self.models[i].replies(sources, direction, goals,
                                                     not enemy.is_pacman and enemy.scared_timer > 1)
        return estimates

    def choose_action(self, state):
        self.started = time.perf_counter()
        legal = state.get_legal_actions(self.index)
        # CaptureAgent.get_action already continues straight at fractional positions.
        if len(legal) == 1:
            return legal[0]
        me = state.get_agent_state(self.index)
        p = nearest_point(me.get_position())
        mate = nearest_point(state.get_agent_position(self.mate))
        self.recent.append(p)
        defended = self.resources(state)
        missing = self.defended - defended
        self.defended = defended
        self.bite_age += 1
        if missing:
            self.bite = min(self.maze.order(missing), key=lambda q: self.dist(p, q))
            self.bite_age = 0
        estimates = self.observe(state, p, mate, missing)
        invaders = [i for i in self.enemies if state.get_agent_state(i).is_pacman]
        score = self.get_score(state)
        moves = (state.data.timeleft + 3) // 4
        # Two invaders leave the far side open. Let a raider already across
        # finish the trip if our sentinel is home; otherwise double-cover.
        # A long-scared ghost can neither eat nor block, so it never covers.
        # A rule-based policy switches between raiding and defending.
        double_cover = len(invaders) == 2 and me.scared_timer <= 15 and (self.guarding or
                       (not me.is_pacman and mate not in self.maze.home))
        emergency = double_cover or score > 0 and moves < 24
        visible_near = any(state.get_agent_position(i) is not None and
                           self.dist(p, nearest_point(state.get_agent_position(i))) <= 2 for i in invaders)
        # The raider backs up a busy guard. An idle guard can raid while
        # scared, while trailing, or when both opposing ghosts stay home.
        # Long scared, it raids whatever is invading: their half is emptier.
        assist = (not invaders and (me.scared_timer > 8 or score < 0 or
                  (moves < 245 and score <= 0))) or me.scared_timer > 15
        defend = (self.guarding and not assist or emergency or visible_near) and not me.is_pacman
        if defend:
            action = self.defend(state, p, mate, invaders, estimates, legal)
        else:
            recall = self.guarding and bool(invaders) and me.scared_timer < 5
            action = self.raid(state, p, mate, estimates, legal, moves, recall or emergency)
        return action if action in legal else legal[0]

    def raid(self, state, p, mate, estimates, legal, moves, recall):
        maze = self.maze
        me = state.get_agent_state(self.index)
        carried = me.num_carrying
        food = maze.order(self.get_food(state).as_list())
        capsules = set(self.get_capsules(state))
        # A visible defender contests adjacent squares on its next turn.
        # A capsule is consumed before collision testing, so it is a safe step.
        risk = Counter()
        danger = {}
        for i, possible in estimates.items():
            enemy = state.get_agent_state(i)
            if enemy.is_pacman or enemy.scared_timer > 5:
                continue
            for g, weight in possible:
                for q in maze.edges:
                    if q in maze.home or q in capsules:
                        continue
                    d = self.dist(g, q)
                    if d < 5:
                        # Twice the original weights: on defaultCapture the
                        # raider died 3 times a game against a door-holding guard.
                        risk[q] += weight * (60, 38, 10, 2.8, 0.8)[d]
                for q in food:
                    mouth = maze.mouth.get(q)
                    if mouth:
                        slack = self.dist(g, mouth) - self.dist(p, q) - self.dist(q, mouth)
                        if slack <= 1:
                            danger[q] = danger.get(q, 0) + weight * min(16, 3 + self.dist(q, mouth) * 2)
            # Projected reply occupancy changes the cost of stepping into a
            # defender's path even when two food routes are equally short.
            for q, probability in self.forecast.get(i, {}).items():
                if q not in maze.home and q not in capsules:
                    risk[q] += 18 * probability
        for q, count in Counter(self.recent).items():
            risk[q] += 0.65 * max(0, count - 1)
        parent = {}
        costs, actions = maze.routes(p, legal, risk, parent=parent)
        doors = [q for q in maze.doors if q in costs]
        if not doors:
            return legal[0]
        bank = min(doors, key=costs.get)
        score = self.get_score(state)
        returned = sum(state.get_agent_state(i).num_returned for i in self.agentsOnTeam)
        limit = 3 if score >= 0 else 5
        near_food = min((self.dist(p, q) for q in food), default=999)
        full_load = carried >= limit and (near_food > 1 or carried >= limit + 2)
        cash = carried and (
            returned + carried >= self.quota
            or moves <= maze.bank[p] + 8
            or full_load
            or costs[bank] <= 2
            or near_food >= maze.bank[p] + 3
        )
        # On cramped maps a small load is worth banking while an exit is
        # still open. Compare both arrivals; the closest door may be guarded.
        active = [nearest_point(state.get_agent_position(i)) for i in self.enemies
                  if not state.get_agent_state(i).is_pacman and
                  state.get_agent_state(i).scared_timer <= 3 and state.get_agent_position(i) is not None]
        if active and me.is_pacman:
            def exit_price(b):
                lead = min(self.dist(g, b) for g in active) - self.dist(p, b)
                return costs[b] + 3 * max(0, 2 - lead)
            bank = min(doors, key=exit_price)
            window = min(self.dist(g, bank) for g in active) - self.dist(p, bank)
            if carried and - 1 <= window <= 3:
                cash = True
        if me.is_pacman and (cash or recall or not food):
            self.goal = bank
            return self.safe_step(p, actions[bank], active, capsules, legal)
        candidates = [q for q in food + maze.order(capsules) if q in costs]
        if not candidates:
            return actions[bank]
        capsule_bonus = 4 if (len(food) < 5 or any(
            estimates[i] and state.get_agent_state(i).scared_timer < 7 for i in self.enemies
        )) else 1

        # A two-step cycle means the target keeps flipping, or a guard keeps
        # turning us back from the same target. Unless we lead, commit to one
        # target in the first case and steer away from the blocked one in the second.
        recent = list(self.recent)
        cycling = (len(recent) >= 6 and recent[-1] == recent[-3] == recent[-5]
                   and recent[-2] == recent[-4] and recent[-1] != recent[-2])
        for q in list(self.taboo):
            self.taboo[q] -= 1
            if self.taboo[q] <= 0:
                del self.taboo[q]
        # A stand-off only helps the side that is ahead, so keep it then.
        if cycling and self.goal is not None and score <= 0:
            if len(set(self.goal_hist)) <= 1:
                self.taboo[self.goal] = 20
                self.lock = 0
            else:
                self.lock_goal, self.lock = self.goal, 8

        # Greedy evaluation ranks reachable goals by path cost and weighted features.
        def extra(q):
            # Per-target terms a trip pays at every stop; the home-distance
            # term stays out because a trip prices its own return leg.
            preference = danger.get(q, 0)
            if any(self.dist(q, t) <= 3 for t in self.taboo):
                preference += 12
            if q in capsules:
                preference -= capsule_bonus
            if mate not in maze.home and self.dist(mate, q) + 1 < self.dist(p, q):
                preference += 4
            return preference

        def price(q):
            return costs[q] + 0.36 * maze.bank[q] + extra(q) - 1.5 * (q == self.goal)
        if self.lock > 0 and self.lock_goal in candidates:
            self.lock -= 1
            self.goal = self.lock_goal
        else:
            self.lock = 0
            choice = min(candidates, key=price)
            ghosts = [(nearest_point(state.get_agent_position(i)), state.get_agent_state(i).scared_timer)
                      for i in self.enemies if state.get_agent_position(i) is not None
                      and not state.get_agent_state(i).is_pacman]
            # A ghost whose fright ends within the risk horizon is already a threat.
            threat = any(scared <= 5 and self.dist(p, g) <= 10 for g, scared in ghosts)
            if me.is_pacman or maze.bank[p] <= 1:
                # Hidden defenders enter the replay at their likeliest squares,
                # and only to vet a trip that carries more than the limit.
                hidden = [(set(q for q, _ in estimates[i]), state.get_agent_state(i).scared_timer)
                          for i in self.enemies if state.get_agent_position(i) is None
                          and not state.get_agent_state(i).is_pacman]
                trip = self.trips(p, sorted(candidates, key=price), costs, parent, extra, capsules,
                                  ghosts, hidden, carried, limit, threat)
                if trip is not None:
                    choice = trip
                # Otherwise today's choice: with a chasing ghost nearby, replay
                # single targets and prefer the cheapest we can bring home.
                elif any(scared == 0 and self.dist(p, g) <= 7 for g, scared in ghosts):
                    choice = self.verified(candidates, price, parent, costs, doors, capsules,
                                           [({g}, scared) for g, scared in ghosts], carried, choice)
            self.goal = choice
        self.goal_hist.append(self.goal)
        if me.is_pacman:
            return self.safe_step(p, actions[self.goal], active, capsules, legal)
        return actions[self.goal]

    def trips(self, p, ranked, costs, parent, extra, capsules, ghosts, hidden, carried, limit, threatened):
        """Best first stop of a short multi-dot trip, or None. A trip visits up
        to TRIP_DEPTH of the best-priced targets in order, then banks; it scores
        stops per move. Work is counted, not timed, so games replay exactly."""
        maze = self.maze
        pool = ranked[:TRIP_POOL]
        seen = [({g}, scared) for g, scared in ghosts]
        every = seen + [h for h in hidden if h[0]]
        # Without a belief for some defender a long trip cannot be vetted.
        blind = any(not squares for squares, _ in hidden)
        work = Counter()
        legs = {}
        best = [None, None]

        def leg(a, b):
            if (a, b) not in legs:
                legs[a, b] = maze.descent(a, b)
            return legs[a, b]

        def replay(state, path, bank):
            # A settled verdict sticks: a capsule keeps us safe, a catch stays fatal.
            if state is None or state[0] is not None:
                return state
            if path is None:
                return False, state[1], state[2]
            # A replayed move costs one chase step per square a ghost may hold.
            work["steps"] += (len(path) - 1) * sum(len(squares) for squares, _ in state[1])
            return maze.survive(path, state[1], state[2], capsules, bank)

        def back(q, states):
            # Moves home through the nearest door every tracked replay survives.
            if not states:
                return maze.bank[q]
            for b in sorted(maze.doors, key=lambda b: (self.dist(q, b), maze.key[b]))[:TRIP_DOORS]:
                path = leg(q, b)
                if all(replay(s, path, True)[0] for s in states):
                    return self.dist(q, b)
            return None

        def grow(trip, moves, cost, value, dots, watch, alarm):
            # watch replays the visible ghosts, alarm every defender we track.
            if (work["evals"] >= TRIP_EVALS or work["steps"] >= TRIP_STEPS or
                    time.perf_counter() - self.started > 0.45):
                return
            work["evals"] += 1
            q = trip[-1]
            over = carried + dots > limit
            if over and blind:
                return
            states = [s for s in (watch, alarm if over else None) if s is not None]
            home = back(q, states)
            if home is not None:
                rate = value / max(1, moves + TRIP_HOME * home + cost)
                if best[0] is None or rate > best[0]:
                    best[:] = rate, trip[0]
            if len(trip) >= TRIP_DEPTH:
                return
            for n in pool:
                if n in trip:
                    continue
                path = leg(q, n) if watch or alarm else None
                step = replay(watch, path, False)
                if step is not None and step[0] is False:
                    continue
                grow(trip + [n], moves + self.dist(q, n), cost + extra(n), value + 1,
                     dots + (n not in capsules), step, replay(alarm, path, False))

        # Replay the visible ghosts only when one is close and soon awake; replay
        # everyone only if some trip could carry more than the limit.
        watch = (None, seen, 0) if threatened else None
        alarm = (None, every, 0) if every and carried + TRIP_DEPTH > limit else None
        for q in pool:
            path = maze.trace(parent, q) if watch or alarm else None
            step = replay(watch, path, False)
            if step is not None and step[0] is False:
                continue
            grow([q], costs[q], extra(q) - 1.5 * (q == self.goal), 1, int(q not in capsules),
                 step, replay(alarm, path, False))
        return best[1]

    def verified(self, candidates, price, parent, costs, doors, capsules, ghosts, carried, choice):
        maze = self.maze

        def hurry():
            # Backstop only; the bounded loops below finish well before it.
            return time.perf_counter() - self.started > 0.45

        def escape(q, chasers, t):
            # Nearest doors first; the first exit the chasers cannot cut off wins.
            for b in sorted(maze.doors, key=lambda b: self.dist(q, b))[:6]:
                if hurry():
                    return None
                path = maze.descent(q, b)
                if path and maze.survive(path, chasers, t, capsules, True)[0]:
                    return True
            return False

        # sorted() is stable, so equal prices keep the canonical candidate order.
        for q in sorted(candidates, key=price)[:6]:
            if hurry():
                return q  # out of time: unverified targets keep today's ranking
            verdict, chasers, t = maze.survive(maze.trace(parent, q), ghosts, 0, capsules, False)
            if verdict is None:
                verdict = escape(q, chasers, t)
            if verdict is not False:
                return q
        if carried:
            # Nothing is safe to collect, so bank along the first exit route that holds.
            for b in sorted(doors, key=costs.get):
                if hurry():
                    break
                if maze.survive(maze.trace(parent, b), ghosts, 0, capsules, True)[0]:
                    return b
        return choice

    def safe_step(self, p, planned, ghosts, capsules, legal):
        # One-step threat check avoids a direct capture when a safer move exists.
        # The defender has a turn before we move again. Avoid exposure to
        # one-step capture when a safe neighboring square or wait exists.
        if not ghosts:
            return planned

        def slack(q):
            if q in self.maze.home or q in capsules:
                return 8
            return min(self.dist(g, q) for g in ghosts)
        options = [(q, a) for q, a in self.maze.edges[p] + [(p, Directions.STOP)] if a in legal]
        dest = next((q for q, a in options if a == planned), p)
        if slack(dest) > 1:
            return planned
        safe = [(q, a) for q, a in options if slack(q) > 1]
        if not safe:
            return planned
        return min(safe, key=lambda pair: (self.recent.count(pair[0]), -slack(pair[0])))[1]

    def defend(self, state, p, mate, invaders, estimates, legal):
        maze = self.maze
        costs, actions = maze.routes(p, legal, {}, home_only=True)
        doors = [b for b in maze.doors if b in costs]
        if not doors:
            return legal[0]
        me = state.get_agent_state(self.index)
        sightings = [(i, q, w) for i in invaders for q, w in estimates[i] if q in costs]
        if me.scared_timer and sightings:
            # Shadow outside one-reply capture range until the timer expires,
            # on the side of the nearest invader's way home.
            _, seen, _ = min(sightings, key=lambda s: costs[s[1]])
            exit_ = min(maze.order(maze.doors), key=lambda b: self.dist(seen, b))

            def shadow(q):
                near = min(self.dist(q, s) for _, s, _ in sightings)
                return (max(0, 3 - near) * 10 + abs(near - 3), self.dist(q, exit_), maze.bank[q])
            choices = [(p, Directions.STOP)] + maze.edges[p]
            return min(((q, a) for q, a in choices if q in costs and a in legal),
                       key=lambda item: shadow(item[0]))[1]
        if sightings:
            # An invader seen inside one of our dead ends must come back out
            # through its mouth. Reach the mouth first and hold it; only step
            # off to eat the invader once it comes adjacent.
            seen = [nearest_point(state.get_agent_position(i)) for i in invaders
                    if state.get_agent_position(i) is not None]
            # A capsule below the mouth would scare us while we wait there.
            baited = {maze.home_mouth.get(c) for c in self.get_capsules_you_are_defending(state)}
            traps = []
            for q in seen:
                m = maze.home_mouth.get(q)
                if m not in costs or m in baited or costs[m] > self.dist(q, m):
                    continue
                # With a second invader loose, a raider leaves this mouth to
                # an unscared sentinel that gets there no later. Never the
                # other way round: a raider at home may still be raiding.
                if (len(invaders) > 1 and not self.guarding and mate in maze.home and
                        not state.get_agent_state(self.mate).scared_timer and self.dist(mate, m) <= costs[m]):
                    continue
                traps.append((costs[m], maze.key[m], maze.key[q], m))
            if traps:
                # Any invader next to us is worth the step, trapped or not.
                bites = [q for q in maze.order(seen) if costs.get(q, INF) <= 1]
                if bites:
                    return actions[bites[0]]
                m = min(traps)[-1]
                return Directions.STOP if p == m else actions[m]

            def priority(report):
                i, q, weight = report
                partner_closer = len(invaders) > 1 and self.dist(mate, q) < costs[q]
                return costs[q] + 6 * partner_closer - 2 * min(4, state.get_agent_state(i).num_carrying) - 3 * weight
            i, inv, _ = min(sightings, key=priority)
            if costs[inv] <= 1 and state.get_agent_position(i) is not None:
                return actions[inv]
            seen = state.get_agent_position(i)
            if seen is not None:
                # Where the solved chase says it can never get home, stay there,
                # as close to it as that allows; chasing from behind never closes.
                at = nearest_point(seen)
                hold = [q for q in maze.holds(p, at) if q in costs]
                if hold:
                    return actions[min(hold, key=lambda q: (self.dist(q, at), maze.key[q]))]
            # Shortest-path interception compares both agents' arrival times.
            # Intercept on a shortest corridor to likely loot or the exit.
            # Select the earliest square we reach no later than the invader.
            goals = doors if state.get_agent_state(i).num_carrying >= 2 else self.defended or doors
            likely_steps = self.forecast.get(i, {})
            if likely_steps:
                # Choose the route best aligned with the mass of projected
                # replies. Retain its current origin for the arrival-time race.
                def goal_cost(g):
                    progress = sum(w * (self.dist(inv, g) - self.dist(q, g))
                                   for q, w in likely_steps.items() if self.dist(inv, q) <= 1)
                    return self.dist(inv, g) - 3 * progress
                goal = min(maze.order(goals), key=goal_cost)
            else:
                goal = min(maze.order(goals), key=lambda q: self.dist(inv, q))
            length = self.dist(inv, goal)
            reachable = [q for q in costs if costs[q] <= self.dist(inv, q) and
                         self.dist(inv, q) + self.dist(q, goal) == length]
            target = min(reachable, key=lambda q: (self.dist(inv, q), costs[q])) if reachable else inv
            return actions[target]
        # An invader can dip back over the line and re-enter next turn.
        # Finish covering that door while it is still one step away.
        previous = self.get_previous_observation()
        if previous and not invaders and not me.scared_timer:
            for i in self.enemies:
                door = previous.get_agent_position(i)
                enemy = state.get_agent_position(i)
                if (door in doors and previous.get_agent_state(i).is_pacman
                        and enemy is not None and self.dist(door, enemy) == 1):
                    return actions[door]
        if invaders and self.bite_age <= 6 and self.bite in costs:
            return actions[self.bite]
        # Patrol crossings close to protected resources. Shift toward an
        # approaching visible ghost before it becomes an invader.
        approaches = [(q, w) for i in self.enemies for q, w in estimates[i] if q not in maze.home]

        def coverage(b):
            loot = sorted(self.dist(b, f) for f in self.defended)[:4]
            entry = min((self.dist(b, q) + 4 * (1 - w) for q, w in approaches), default=0)
            return (sum(loot) / max(1, len(loot)) + 0.8 * entry + 0.1 * costs[b] +
                    0.25 * sum(self.dist(b, gate) for gate in doors) / len(doors))
        return actions[min(doors, key=coverage)]


class Raider(CapturePlayer):
    """Primary food carrier."""


class Sentinel(CapturePlayer):
    """Primary home-side interceptor."""
    guarding = True
