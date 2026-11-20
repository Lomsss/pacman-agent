"""Plain BFS team: the first search most students write.

The attacker runs BFS to the nearest dot, treating squares next to a
visible ghost as walls, and BFS home once it carries 4 or a ghost is near.
The defender runs BFS to the invader it sees, else the last eaten dot,
else the door nearest our food.
"""
from collections import deque

from zoo_common import ZooAgent
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
