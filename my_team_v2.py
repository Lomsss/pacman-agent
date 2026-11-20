# my_team_v2.py
# -------------
# Licensing Information: Please do not distribute or publish solutions to this
# project. You are free to use and extend these projects for educational
# purposes. The Pacman AI projects were developed at UC Berkeley, primarily by
# John DeNero and Dan Klein. See http://ai.berkeley.edu.
"""Second-generation capture team, designed from our test results.

Sections (numbered banners below, explained in docs/AGENT_V2_DESIGN.md):
  1. Configuration and team entry
  2. Map analysis
  3. Opponent tracking, with teammate sonar fusion
  4. Turn pipeline and role selection
  5. Raider: risk-priced route planning
  6. Raider: last-step safety check
  7. Sentinel: interception and patrol
  8. Sentinel: time-guarded capture search
  9. Roles

Every input comes from this agent's own observation, the previous
observation and the teammate's notes. Nothing reads or changes the
opponents' objects or the game engine.
"""
import time
from collections import Counter, deque
from heapq import heappop, heappush

from contest.capture_agents import CaptureAgent
from contest.game import Directions
from contest.util import nearest_point


# ============================================================================
# 1. Configuration and team entry
# ============================================================================
INF = float("inf")
STEPS = ((1, 0, Directions.EAST), (-1, 0, Directions.WEST),
         (0, 1, Directions.NORTH), (0, -1, Directions.SOUTH))

# Path cost added near a likely enemy ghost, by maze distance 0..4. Twice
# crowded-stalls' weights: lower made the raider die 3 times a game
# against a door-holding guard on defaultCapture; 1.5x and 3x scored less.
RISK = (60, 38, 10, 2.8, 0.8)
REVISIT = 0.65          # extra cost per repeat visit in the last 12 squares
CARRY = 3               # bank at this load when level or ahead
CARRY_BEHIND = 5        # and at this load when behind
TABOO_MOVES = 20        # how long a target a guard keeps blocking is avoided
LOCK_MOVES = 8          # how long the raider commits when its target flips

# Spare think time. A move may take 1 s before a warning. The capture
# search stops at HUNT_BUDGET and only runs with an invader in sight.
HUNT_RANGE = 7          # search when a visible invader is this close
HUNT_BUDGET = 0.3       # seconds per move for the search
HUNT_MAX_ROUNDS = 12    # 0 turns the search off
FUSE_SONAR = True       # use the teammate's last sonar reading as well

# Team notes shared by our two agents, one entry per colour so a game
# against a copy of ourselves keeps the teams apart.
_NOTES = {}


def create_team(first_index, second_index, is_red, first="Raider", second="Sentinel",
                num_training=0, **kwargs):
    """Tournament entry: one raider and one sentinel."""
    classes = {"Raider": Raider, "Sentinel": Sentinel}
    return [classes.get(first, Raider)(first_index), classes.get(second, Sentinel)(second_index)]


# ============================================================================
# 2. Map analysis
# ============================================================================
def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class Maze:
    """Static facts about one layout, computed once at the start."""

    def __init__(self, walls, red):
        cells = set(walls.as_list(False))
        self.edges = {p: [((p[0] + dx, p[1] + dy), action) for dx, dy, action in STEPS
                          if (p[0] + dx, p[1] + dy) in cells] for p in sorted(cells)}
        self.home = {p for p in cells if (p[0] < walls.width // 2) == red}
        self.doors = sorted(p for p in self.home if any(q not in self.home for q, _ in self.edges[p]))
        # Exact maze distances from every square (all-pairs BFS). On very
        # large boards keep only rows from the doors and fall back to
        # Manhattan distance elsewhere, to stay inside the startup time.
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
        # Dead ends on the enemy side, found by peeling leaves. For a square
        # inside one, `mouth` is the square we must pass again to get home.
        degree = {p: len(edges) for p, edges in self.edges.items()}
        leaves = deque(p for p in self.edges if p not in self.home and degree[p] == 1)
        parents = []
        while leaves:
            p = leaves.popleft()
            for q, _ in self.edges[p]:
                if degree[q] > 0:
                    parents.append((p, q))
                    degree[q] -= 1
                    if degree[q] == 1 and q not in self.home:
                        leaves.append(q)
                    break
            degree[p] = 0
        self.mouth = {}
        for p, q in reversed(parents):
            self.mouth[p] = self.mouth.get(q, q)

    def dist(self, p, q):
        if p in self.rows:
            return self.rows[p].get(q, 999)
        if q in self.rows:
            return self.rows[q].get(p, 999)
        return manhattan(p, q)

    def routes(self, origin, legal, risk, home_only=False):
        """Uniform-cost search from `origin` to every square at once.

        Cost is steps plus `risk`. Returns the cost of each square and the
        first action on its cheapest path, so one search prices every goal.
        """
        cost = {origin: 0}
        action = {origin: Directions.STOP}
        queue = [(0, origin)]
        expanded = 0
        while queue and expanded < 850:
            g, p = heappop(queue)
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
                    heappush(queue, (new, q))
        return cost, action


# ============================================================================
# 3. Opponent tracking, with teammate sonar fusion
# ============================================================================
class OpponentModel:
    """Histogram filter over one enemy's square.

    Each turn the belief spreads one step (the enemy moved once since our
    last turn), then keeps only squares that fit what we know: which side
    the enemy is on, that we and our teammate can't see it, our sonar
    reading and, when shared, our teammate's reading from its last turn.
    """

    def __init__(self, maze, spawn):
        self.maze = maze
        self.spawn = spawn
        self.belief = {spawn: 1.0}
        self.seen = None        # exact square when last visible
        self.was_pacman = False
        self.carry = 0
        self.returned = 0

    def update(self, state, index, me, mate, missing, mate_sonar, threats):
        enemy = state.get_agent_state(index)
        visible = state.get_agent_position(index)
        invader = enemy.is_pacman
        # Sent home: it was carrying and is a ghost again without banking,
        # or we saw it as a pacman next to one of our ghosts and lost it.
        died = (self.was_pacman and not invader and
                ((self.carry > 0 and enemy.num_returned == self.returned) or
                 (self.seen is not None and any(manhattan(self.seen, g) <= 1 for g in threats))))
        self.was_pacman, self.carry, self.returned = invader, enemy.num_carrying, enemy.num_returned
        if visible is not None:
            self.seen = nearest_point(visible)
            self.belief = {self.seen: 1.0}
            return [(self.seen, 1.0)]
        self.seen = None
        if died:
            self.belief = {self.spawn: 1.0}
            return [(self.spawn, 1.0)]
        reading = state.get_agent_distances()

        def fits(q):
            if (q in self.maze.home) != invader or manhattan(me, q) <= 5 or manhattan(mate, q) <= 5:
                return False
            if reading and state.get_distance_prob(manhattan(me, q), reading[index]) <= 0:
                return False
            if mate_sonar is not None:
                # The teammate read this one or two moves ago; allow one step.
                where, noisy = mate_sonar
                if abs(manhattan(where, q) - noisy) > 7:
                    return False
            return True

        spread = Counter()
        for source, mass in self.belief.items():
            neighbors = self.maze.edges[source]
            share = mass / (1 + len(neighbors))
            spread[source] += share
            for q, _ in neighbors:
                spread[q] += share
        posterior = Counter({q: w for q, w in spread.items() if fits(q)})
        if not posterior:
            # The true branch was pruned (a respawn, say): restart wide.
            posterior.update(q for q in self.maze.edges if fits(q))
            if not posterior and mate_sonar is not None:
                posterior.update(q for q in self.maze.edges
                                 if (q in self.maze.home) == invader and manhattan(me, q) > 5)
        if invader:
            # A dot vanished: an invader is very likely standing there.
            for q in missing:
                if q in posterior:
                    posterior[q] *= 9
        top = posterior.most_common(40) or [(self.spawn, 1.0)]
        total = sum(w for _, w in top)
        self.belief = {q: w / total for q, w in top}
        return list(self.belief.items())[:4]


# ============================================================================
# 4. Turn pipeline and role selection
# ============================================================================
class CapturePlayer(CaptureAgent):
    guarding = False

    def register_initial_state(self, state):
        # Our own unit-step BFS replaces the base class's distancer.
        self.red = state.is_on_red_team(self.index)
        self.register_team(self.get_team(state))
        self.mate = next(i for i in self.agentsOnTeam if i != self.index)
        self.enemies = self.get_opponents(state)
        self.maze = Maze(state.get_walls(), self.red)
        self.dist = self.maze.dist
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
                       for i in self.enemies}
        notes = _NOTES.setdefault(self.red, {})
        if state.data.timeleft >= 1199 or notes.get("game") is None:
            notes.clear()
        notes["game"] = True
        self.notes = notes

    def get_maze_distance(self, pos1, pos2):
        return self.dist(nearest_point(pos1), nearest_point(pos2))

    def resources(self, state):
        return set(self.get_food_you_are_defending(state).as_list()) | set(self.get_capsules_you_are_defending(state))

    def choose_action(self, state):
        legal = state.get_legal_actions(self.index)
        if len(legal) == 1:
            return legal[0]
        self.started = time.time()
        try:
            action = self.turn(state, legal)
        except Exception:
            # Never forfeit a game over a bug: take the safest-looking step.
            action = None
        if action not in legal:
            action = self.fallback(state, legal)
        return action

    def observe(self, state, p, mate, missing):
        distances = state.get_agent_distances()
        sonar = self.notes.setdefault("sonar", {})
        mine = {}
        threats = [q for q in (p, mate) if q in self.maze.home]
        estimates = {}
        for i in self.enemies:
            shared = sonar.get(i) if FUSE_SONAR else None
            estimates[i] = self.models[i].update(state, i, p, mate, missing, shared, threats)
            if distances:
                mine[i] = (p, distances[i])
        sonar.update(mine)
        return estimates

    def turn(self, state, legal):
        me = state.get_agent_state(self.index)
        p = nearest_point(me.get_position())
        mate = nearest_point(state.get_agent_position(self.mate))
        self.recent.append(p)
        defended = self.resources(state)
        missing = self.defended - defended
        self.defended = defended
        self.bite_age += 1
        if missing:
            self.bite = min(missing, key=lambda q: self.dist(p, q))
            self.bite_age = 0
        estimates = self.observe(state, p, mate, missing)
        invaders = [i for i in self.enemies if state.get_agent_state(i).is_pacman]
        score = self.get_score(state)
        moves = (state.data.timeleft + 3) // 4
        # Two invaders: the sentinel always covers; the raider helps if it is
        # home and the sentinel is not.
        double_cover = len(invaders) == 2 and (self.guarding or
                       (not me.is_pacman and mate not in self.maze.home))
        emergency = double_cover or score > 0 and moves < 24
        visible_near = any(state.get_agent_position(i) is not None and
                           self.dist(p, nearest_point(state.get_agent_position(i))) <= 2 for i in invaders)
        # An idle sentinel raids while scared, while trailing, or late in a
        # level game.
        assist = (not invaders and (me.scared_timer > 8 or score < 0 or
                  (moves < 245 and score <= 0))) or (me.scared_timer > 15 and len(invaders) == 1)
        defend = (self.guarding and not assist or emergency or visible_near) and not me.is_pacman
        if defend:
            return self.defend(state, p, mate, invaders, estimates, legal)
        recall = self.guarding and bool(invaders) and me.scared_timer < 5
        return self.raid(state, p, mate, estimates, legal, moves, recall or emergency)

    def fallback(self, state, legal):
        me = state.get_agent_state(self.index)
        p = nearest_point(me.get_position())
        options = [(q, a) for q, a in self.maze.edges.get(p, []) if a in legal]
        if me.is_pacman and options:
            return min(options, key=lambda item: self.maze.bank.get(item[0], 999))[1]
        return Directions.STOP if Directions.STOP in legal else legal[0]


# ============================================================================
# 5. Raider: risk-priced route planning
# ============================================================================
    def raid(self, state, p, mate, estimates, legal, moves, recall):
        maze = self.maze
        me = state.get_agent_state(self.index)
        carried = me.num_carrying
        food = self.get_food(state).as_list()
        capsules = set(self.get_capsules(state))
        # Path cost near likely ghosts, and the danger of dead ends whose
        # mouth a ghost reaches before we can get out again.
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
                        risk[q] += weight * RISK[d]
                for q in food:
                    mouth = maze.mouth.get(q)
                    if mouth:
                        slack = self.dist(g, mouth) - self.dist(p, q) - self.dist(q, mouth)
                        if slack <= 1:
                            danger[q] = danger.get(q, 0) + weight * min(16, 3 + self.dist(q, mouth) * 2)
        for q, count in Counter(self.recent).items():
            risk[q] += REVISIT * max(0, count - 1)
        costs, actions = maze.routes(p, legal, risk)
        doors = [q for q in maze.doors if q in costs]
        if not doors:
            return legal[0]
        bank = min(doors, key=costs.get)
        score = self.get_score(state)
        returned = sum(state.get_agent_state(i).num_returned for i in self.agentsOnTeam)
        limit = CARRY if score >= 0 else CARRY_BEHIND
        near_food = min((self.dist(p, q) for q in food), default=999)
        full_load = carried >= limit and (near_food > 1 or carried >= limit + 2)
        cash = carried and (
            returned + carried >= self.quota
            or moves <= maze.bank[p] + 8
            or full_load
            or costs[bank] <= 2
            or near_food >= maze.bank[p] + 3
        )
        # Ghosts we can see that can still eat us.
        active = [nearest_point(state.get_agent_position(i)) for i in self.enemies
                  if not state.get_agent_state(i).is_pacman and
                  state.get_agent_state(i).scared_timer <= 3 and state.get_agent_position(i) is not None]
        if active and me.is_pacman:
            # Bank through the door we reach with the biggest lead.
            def exit_price(b):
                lead = min(self.dist(g, b) for g in active) - self.dist(p, b)
                return costs[b] + 3 * max(0, 2 - lead)
            bank = min(doors, key=exit_price)
            window = min(self.dist(g, bank) for g in active) - self.dist(p, bank)
            if carried and -1 <= window <= 3:
                cash = True
        if me.is_pacman and (cash or recall or not food):
            self.goal = bank
            return self.safe(state, p, actions[bank], capsules, legal)
        candidates = [q for q in food + sorted(capsules) if q in costs]
        if not candidates:
            return actions[bank]
        capsule_bonus = 4 if (len(food) < 5 or any(
            estimates[i] and state.get_agent_state(i).scared_timer < 7 for i in self.enemies
        )) else 1

        # Stand-offs: a two-square cycle means the target keeps flipping, or
        # a guard keeps turning us back from one target. Unless we lead
        # (then the stand-off runs the clock for us), commit to one target
        # in the first case and avoid the blocked target in the second.
        recent = list(self.recent)
        cycling = (len(recent) >= 6 and recent[-1] == recent[-3] == recent[-5]
                   and recent[-2] == recent[-4] and recent[-1] != recent[-2])
        for q in list(self.taboo):
            self.taboo[q] -= 1
            if self.taboo[q] <= 0:
                del self.taboo[q]
        if cycling and self.goal is not None and score <= 0:
            if len(set(self.goal_hist)) <= 1:
                self.taboo[self.goal] = TABOO_MOVES
                self.lock = 0
            else:
                self.lock_goal, self.lock = self.goal, LOCK_MOVES

        def price(q):
            preference = 0.36 * maze.bank[q] + danger.get(q, 0)
            if any(self.dist(q, t) <= 3 for t in self.taboo):
                preference += 12
            if q in capsules:
                preference -= capsule_bonus
            if mate not in maze.home and self.dist(mate, q) + 1 < self.dist(p, q):
                preference += 4     # leave it to the teammate
            if q == self.goal:
                preference -= 1.5
            return costs[q] + preference

        if self.lock > 0 and self.lock_goal in candidates:
            self.lock -= 1
            self.goal = self.lock_goal
        else:
            self.lock = 0
            self.goal = min(candidates, key=price)
        self.goal_hist.append(self.goal)
        if me.is_pacman or p not in maze.home:
            return self.safe(state, p, actions[self.goal], capsules, legal)
        return actions[self.goal]


# ============================================================================
# 6. Raider: last-step safety check
# ============================================================================
    def safe(self, state, p, planned, capsules, legal):
        """Don't step next to a visible ghost when another step avoids it.

        The route costs of section 5 already keep the raider away from
        likely ghosts; this only catches the last step. A deeper search
        over the ghosts' replies was tried and cost points (see the design
        doc): the worst case it plans for is far more careful than the
        guards we meet.
        """
        ghosts = [nearest_point(state.get_agent_position(i)) for i in self.enemies
                  if not state.get_agent_state(i).is_pacman and
                  state.get_agent_state(i).scared_timer <= 3 and state.get_agent_position(i) is not None]
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


# ============================================================================
# 7. Sentinel: interception and patrol
# ============================================================================
    def defend(self, state, p, mate, invaders, estimates, legal):
        maze = self.maze
        costs, actions = maze.routes(p, legal, {}, home_only=True)
        doors = [b for b in maze.doors if b in costs]
        if not doors:
            return legal[0]
        me = state.get_agent_state(self.index)
        sightings = [(i, q, w) for i in invaders for q, w in estimates[i] if q in costs]
        if me.scared_timer and sightings:
            # Scared: shadow from 3 squares, out of reach, until it wears off.
            def shadow(q):
                near = min(self.dist(q, s) for _, s, _ in sightings)
                return (max(0, 3 - near) * 10 + abs(near - 3), maze.bank[q])
            choices = [(p, Directions.STOP)] + maze.edges[p]
            return min(((q, a) for q, a in choices if q in costs and a in legal),
                       key=lambda item: shadow(item[0]))[1]
        if sightings:
            def priority(report):
                i, q, weight = report
                partner_closer = len(invaders) > 1 and self.dist(mate, q) < costs[q]
                return costs[q] + 6 * partner_closer - 2 * min(4, state.get_agent_state(i).num_carrying) - 3 * weight
            i, inv, _ = min(sightings, key=priority)
            if costs[inv] <= 1 and state.get_agent_position(i) is not None:
                return actions[inv]
            if state.get_agent_position(i) is not None:
                # A capture we can force beats any heuristic (section 8).
                trap = self.hunt(state, p, inv, legal)
                if trap is not None:
                    return trap
            # Intercept: the earliest square on the invader's shortest path
            # to its likely goal (loot, or the exit once it carries 2) that
            # we reach no later than it does.
            goals = doors if state.get_agent_state(i).num_carrying >= 2 else self.defended or doors
            goal = min(sorted(goals), key=lambda q: self.dist(inv, q))
            length = self.dist(inv, goal)
            reachable = [q for q in costs if costs[q] <= self.dist(inv, q) and
                         self.dist(inv, q) + self.dist(q, goal) == length]
            target = min(reachable, key=lambda q: (self.dist(inv, q), costs[q])) if reachable else inv
            return actions[target]
        # An invader that just stepped back over the line usually comes
        # straight back: cover that door while it is one step away.
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
        # Patrol the door that best covers our food and the likeliest entry.
        approaches = [(q, w) for i in self.enemies for q, w in estimates[i] if q not in maze.home]

        def coverage(b):
            loot = sorted(self.dist(b, f) for f in self.defended)[:4]
            entry = min((self.dist(b, q) + 4 * (1 - w) for q, w in approaches), default=0)
            return (sum(loot) / max(1, len(loot)) + 0.8 * entry + 0.1 * costs[b] +
                    0.25 * sum(self.dist(b, gate) for gate in doors) / len(doors))
        return actions[min(doors, key=coverage)]


# ============================================================================
# 8. Sentinel: time-guarded capture search
# ============================================================================
    def hunt(self, state, p, prey, legal):
        """A first step that catches a visible invader whatever it does.

        Pursuit search: we move, the invader replies, for up to R rounds.
        The invader gets away by crossing back to its side or by eating one
        of our capsules. R grows until the time budget runs out, so the
        quickest forced capture wins; None means no capture can be forced
        and section 7's interception decides.
        """
        if not HUNT_MAX_ROUNDS or self.dist(p, prey) > HUNT_RANGE:
            return None
        maze = self.maze
        home = maze.home
        exits = set(self.get_capsules_you_are_defending(state))
        deadline = self.started + HUNT_BUDGET
        memo = {}
        clock = [0]

        def chaser_moves(m):
            return [q for q, _ in maze.edges[m] if q in home] + [m]

        def caught(m, e, r):
            # We just moved to m; the invader at e moves next; r rounds left.
            if m == e:
                return True
            if r == 0:
                return False
            key = (m, e, r)
            if key in memo:
                return memo[key]
            clock[0] += 1
            if clock[0] & 255 == 0 and time.time() > deadline:
                raise TimeoutError
            result = True
            for n, _ in maze.edges[e] + [(e, None)]:
                if n == m:
                    continue    # walking into us is no escape
                if n not in home or n in exits or not any(
                        caught(m2, n, r - 1) for m2 in chaser_moves(m)):
                    result = False
                    break
            memo[key] = result
            return result

        options = [(q, a) for q, a in maze.edges[p] if q in home and a in legal]
        if Directions.STOP in legal:
            options.append((p, Directions.STOP))
        try:
            for rounds in range(1, HUNT_MAX_ROUNDS + 1):
                for q, a in options:
                    if caught(q, prey, rounds):
                        return a
        except TimeoutError:
            pass
        return None


# ============================================================================
# 9. Roles
# ============================================================================
class Raider(CapturePlayer):
    """Brings food home; defends only in emergencies."""


class Sentinel(CapturePlayer):
    """Guards home; raids when idle, scared or trailing."""
    guarding = True
