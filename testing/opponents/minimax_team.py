"""Alpha-beta attacker against the ghosts it can see, plus a sonar defender."""
import time

from zoo_common import ZooAgent, ChaseModel, INF


class AlphaBetaAttacker(ZooAgent):
    DEPTH = 3

    def choose_action(self, game_state):
        self.track(game_state)
        pos = self.my_pos(game_state)
        ghosts = self.ghosts(game_state)
        if not ghosts or min(self.dist(pos, g[1]) for g in ghosts) > 6:
            return self.safe_food_step(game_state, carry_limit=5, flee=2)
        model = ChaseModel(self, game_state)
        self.deadline = time.time() + 0.5
        best, best_v = None, -INF
        for a in game_state.get_legal_actions(self.index):
            n = self.step(pos, a)
            v = self.ghost_turn(model, model.move_me(model.start, n), 0, 1, best_v, INF)
            if v > best_v:
                best, best_v = a, v
        return best

    def me_turn(self, model, s, depth, alpha, beta):
        if s[5] or depth >= self.DEPTH or time.time() > self.deadline:
            return model.value(s)
        v = -INF
        for n in model.my_moves(s):
            v = max(v, self.ghost_turn(model, model.move_me(s, n), depth, 1, alpha, beta))
            if v >= beta:
                return v
            alpha = max(alpha, v)
        return v

    def ghost_turn(self, model, s, depth, _, alpha, beta):
        if s[5]:
            return model.value(s)
        ghosts = s[1]
        if not ghosts:
            return self.me_turn(model, s, depth + 1, alpha, beta)
        combos = [[]]
        for g in ghosts:
            combos = [c + [m] for c in combos for m in model.ghost_moves(g)]
        v = INF
        for c in combos:
            v = min(v, self.me_turn(model, model.move_ghosts(s, c), depth + 1, alpha, beta))
            if v <= alpha:
                return v
            beta = min(beta, v)
        return v


class Guard(ZooAgent):
    def choose_action(self, game_state):
        self.track(game_state)
        return self.defend(game_state)


def create_team(first_index, second_index, is_red, **kw):
    return [AlphaBetaAttacker(first_index), Guard(second_index)]
