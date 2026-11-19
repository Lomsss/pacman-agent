"""Monte Carlo tree search attacker (UCT with rollouts), plus a sonar defender."""
import math
import random
import time

from zoo_common import ZooAgent, ChaseModel


class Node:
    __slots__ = ("state", "kids", "n", "w", "move")

    def __init__(self, state, move=None):
        self.state, self.move, self.kids, self.n, self.w = state, move, None, 0, 0.0


class MCTSAttacker(ZooAgent):
    BUDGET = 0.15
    ROLLOUT = 12

    def choose_action(self, game_state):
        self.track(game_state)
        pos = self.my_pos(game_state)
        ghosts = self.ghosts(game_state)
        if not ghosts or min(self.dist(pos, g[1]) for g in ghosts) > 7:
            return self.safe_food_step(game_state, carry_limit=6, flee=2)
        model = ChaseModel(self, game_state)
        root = Node(model.start)
        end = time.time() + self.BUDGET
        while time.time() < end:
            self.iterate(model, root)
        if not root.kids:
            return self.safe_food_step(game_state)
        best = max(root.kids, key=lambda k: k.n)
        for a in game_state.get_legal_actions(self.index):
            if self.step(pos, a) == best.move:
                return a
        return self.safe_food_step(game_state)

    def ghost_reply(self, model, s):
        moves = []
        for g in s[1]:
            opts = model.ghost_moves(g)
            if random.random() < 0.8:
                moves.append(min(opts, key=lambda o: self.dist(o, s[0])))
            else:
                moves.append(random.choice(opts))
        return model.move_ghosts(s, moves)

    def iterate(self, model, root):
        path, node = [root], root
        while node.kids:
            log_n = math.log(node.n + 1)
            node = max(node.kids, key=lambda k: (k.w / (k.n + 1e-9)) + 1.2 * math.sqrt(log_n / (k.n + 1e-9)) * 30
                       if k.n else float("inf"))
            path.append(node)
        if not node.state[5]:
            node.kids = [Node(self.ghost_reply(model, model.move_me(node.state, m)), m) for m in model.my_moves(node.state)]
        s = node.state
        for _ in range(self.ROLLOUT):
            if s[5]:
                break
            moves = model.my_moves(s)
            if s[3] >= 3:
                m = min(moves, key=lambda x: self.home_dist(x)) if random.random() < 0.7 else random.choice(moves)
            else:
                m = random.choice(moves)
            s = self.ghost_reply(model, model.move_me(s, m))
        value = model.value(s)
        for p in path:
            p.n += 1
            p.w += value


class Guard(ZooAgent):
    def choose_action(self, game_state):
        self.track(game_state)
        return self.defend(game_state)


def create_team(first_index, second_index, is_red, **kw):
    return [MCTSAttacker(first_index), Guard(second_index)]
