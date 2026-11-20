"""A* attacker that plans whole paths around the ghosts it can see, plus a defender.

This is the heuristic-search style many teams adapt from the CS188 search
project: A* to the best dot with squares next to a ghost blocked and squares
near one made expensive, then A* back home once loaded or threatened.
"""
import heapq

from zoo_common import ZooAgent, INF
from contest.game import Directions


class AStarAttacker(ZooAgent):
    CARRY = 5

    def choose_action(self, game_state):
        self.track(game_state)
        pos = self.my_pos(game_state)
        st = game_state.get_agent_state(self.index)
        ghosts = [g[1] for g in self.ghosts(game_state)]
        food = self.get_food(game_state).as_list()
        caps = self.get_capsules(game_state)
        time_left = game_state.data.timeleft / 4
        near = min((self.dist(pos, g) for g in ghosts), default=INF)
        home = self.home_dist(pos)
        go_home = (st.num_carrying >= self.CARRY or len(food) <= 2 or
                   (st.num_carrying and home + 4 >= time_left) or
                   (st.num_carrying and near <= 4))
        if near <= 4 and caps:
            cap = min(caps, key=lambda c: self.dist(pos, c))
            if self.dist(pos, cap) < home or not st.num_carrying:
                path = self.astar(pos, {cap}, ghosts)
                if path:
                    return path
        if go_home:
            goals = set(self.border)
        else:
            # Rank dots by the round trip, the usual A* agent heuristic.
            ranked = sorted(food, key=lambda f: self.dist(pos, f) + 0.5 * self.home_dist(f))
            goals = set(ranked[:3])
        return self.astar(pos, goals, ghosts) or self.toward(game_state, min(self.border, key=lambda b: self.dist(pos, b)))

    def astar(self, start, goals, ghosts):
        if not goals:
            return None

        def h(p):
            return min(self.dist(p, g) for g in goals)

        def cost(p):
            if self.is_home(p):
                return 1
            d = min((self.dist(p, g) for g in ghosts), default=INF)
            if d <= 1:
                return INF
            return 1 + (12 if d == 2 else 4 if d == 3 else 0)

        frontier = [(h(start), 0, start, None)]
        best = {start: 0}
        first = {}
        while frontier:
            _, g, p, act = heapq.heappop(frontier)
            if p in goals and p != start:
                return act
            if g > best.get(p, INF):
                continue
            for n in self.nbrs[p]:
                c = cost(n)
                if c == INF:
                    continue
                ng = g + c
                if ng < best.get(n, INF):
                    best[n] = ng
                    a = act if act is not None else self.action_to(start, n)
                    heapq.heappush(frontier, (ng + h(n), ng, n, a))
        return None

    def action_to(self, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        return {(1, 0): Directions.EAST, (-1, 0): Directions.WEST,
                (0, 1): Directions.NORTH, (0, -1): Directions.SOUTH}[(dx, dy)]


class Guard(ZooAgent):
    def choose_action(self, game_state):
        self.track(game_state)
        return self.defend(game_state)


def create_team(first_index, second_index, is_red, **kw):
    return [AStarAttacker(first_index), Guard(second_index)]
