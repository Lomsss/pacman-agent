"""Value-iteration (MDP) attacker and defender.

The usual student MDP: every turn, put rewards on the grid (food, capsules,
home once loaded, invaders for the defender), penalise squares near visible
ghosts, run value iteration with a discount, then step to the best neighbour.
"""
from zoo_common import ZooAgent, INF
from contest.game import Directions

GAMMA = 0.9
SWEEPS = 40


class MDPAgent(ZooAgent):
    def rewards(self, game_state):
        raise NotImplementedError

    def choose_action(self, game_state):
        self.track(game_state)
        reward, blocked = self.rewards(game_state)
        cells = [c for c in self.cells if c not in blocked]
        value = {c: reward.get(c, 0.0) for c in cells}
        for _ in range(SWEEPS):
            new = {}
            for c in cells:
                if c in reward and reward[c] > 0:
                    new[c] = reward[c]  # terminal: collect the reward there
                    continue
                best = max((value.get(n, -INF) for n in self.nbrs[c]), default=0.0)
                new[c] = reward.get(c, 0.0) - 0.04 + GAMMA * best
            value = new
        pos = self.my_pos(game_state)
        best, best_v = Directions.STOP, -INF
        for a in game_state.get_legal_actions(self.index):
            if a == Directions.STOP:
                continue
            v = value.get(self.step(pos, a), -INF)
            if v > best_v:
                best, best_v = a, v
        return best


class MDPAttacker(MDPAgent):
    CARRY = 5

    def rewards(self, game_state):
        pos = self.my_pos(game_state)
        st = game_state.get_agent_state(self.index)
        ghosts = [g[1] for g in self.ghosts(game_state)]
        food = self.get_food(game_state).as_list()
        time_left = game_state.data.timeleft / 4
        reward, blocked = {}, set()
        loaded = st.num_carrying >= self.CARRY or len(food) <= 2 or \
            (st.num_carrying and self.home_dist(pos) + 5 >= time_left) or \
            (st.num_carrying and any(self.dist(pos, g) <= 5 for g in ghosts))
        if loaded:
            for b in self.border:
                reward[b] = 10.0 + st.num_carrying
        for f in food:
            reward[f] = 2.0 if loaded else 10.0
        for c in self.get_capsules(game_state):
            reward[c] = 25.0 if ghosts else 6.0
        for g in ghosts:
            for c in self.cells:
                d = self.dist(c, g)
                if d <= 1:
                    blocked.add(c)
                elif d == 2:
                    reward[c] = -30.0
                elif d == 3:
                    reward[c] = min(reward.get(c, 0.0), 0.0) - 8.0
        return reward, blocked


class MDPDefender(MDPAgent):
    def rewards(self, game_state):
        reward = {}
        blocked = {c for c in self.cells if not self.is_home(c)}
        scared = game_state.get_agent_state(self.index).scared_timer > 0
        invaders = self.invaders(game_state)
        for _, pos, carry, seen in invaders:
            if pos is not None and self.is_home(pos):
                reward[pos] = -20.0 if scared else 30.0 + carry
        if not invaders:
            if self.last_eaten is not None and self.is_home(self.last_eaten):
                reward[self.last_eaten] = 15.0
            guesses = [self.guess(i) for i in self.get_opponents(game_state)]
            door = min(self.border, key=lambda b: min(self.dist(b, g) for g in guesses))
            reward[door] = 10.0
        return reward, blocked


def create_team(first_index, second_index, is_red, **kw):
    return [MDPAttacker(first_index), MDPDefender(second_index)]
