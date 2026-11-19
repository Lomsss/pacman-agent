"""Linear Q-function agents with hand-tuned weights, like a trained approximate Q-learner."""
from zoo_common import ZooAgent, INF
from contest.game import Directions


class QAttacker(ZooAgent):
    W = {"food": -1.5, "eat": 12, "carry_home": -0.35, "ghost1": -400, "ghost2": -25,
         "cap": -0.9, "eat_cap": 30, "stop": -5, "reverse": -1.5, "deposit": 25, "scared_hunt": -2}

    def features(self, game_state, action):
        pos = self.my_pos(game_state)
        n = self.step(pos, action)
        st = game_state.get_agent_state(self.index)
        food = self.get_food(game_state).as_list()
        caps = self.get_capsules(game_state)
        f = {}
        f["food"] = min((self.dist(n, x) for x in food), default=0) / 10.0
        f["eat"] = 1.0 if n in food else 0.0
        f["carry_home"] = st.num_carrying * self.home_dist(n) / 10.0
        f["deposit"] = st.num_carrying if self.is_home(n) and not self.is_home(pos) else 0
        g = self.ghosts(game_state)
        f["ghost1"] = sum(1 for _, gp, _ in g if self.dist(n, gp) <= 1)
        f["ghost2"] = sum(1 for _, gp, _ in g if self.dist(n, gp) == 2)
        f["cap"] = (min((self.dist(n, c) for c in caps), default=0) / 10.0) if g else 0
        f["eat_cap"] = 1.0 if n in caps else 0.0
        sg = [gp for _, gp, t in self.ghosts(game_state, scared_ok=True) if t > 3]
        f["scared_hunt"] = min((self.dist(n, gp) for gp in sg), default=0) / 10.0
        f["stop"] = 1.0 if action == Directions.STOP else 0.0
        rev = Directions.REVERSE[game_state.get_agent_state(self.index).configuration.direction]
        f["reverse"] = 1.0 if action == rev else 0.0
        return f

    def choose_action(self, game_state):
        self.track(game_state)
        best, best_q = Directions.STOP, -INF
        for a in game_state.get_legal_actions(self.index):
            f = self.features(game_state, a)
            q = sum(self.W[k] * v for k, v in f.items())
            if q > best_q:
                best, best_q = a, q
        return best


class QDefender(ZooAgent):
    def choose_action(self, game_state):
        self.track(game_state)
        return self.defend(game_state)


def create_team(first_index, second_index, is_red, **kw):
    return [QAttacker(first_index), QDefender(second_index)]
