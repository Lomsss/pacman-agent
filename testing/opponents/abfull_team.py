"""Full-state alpha-beta team, the CS188 multi-agent project adapted to capture.

Both agents search the real game state with generate_successor over
themselves and every enemy they can see, deepening one ply at a time until
the time budget runs out. The evaluation is the usual weighted features,
with an offence and a defence version.
"""
import time

from zoo_common import ZooAgent, INF, ipos
from contest.game import Directions

BUDGET = 0.25  # seconds per move; real teams use up to ~0.9


class Timeout(Exception):
    pass


class ABAgent(ZooAgent):
    OFFENSE = True

    def choose_action(self, game_state):
        self.track(game_state)
        self.deadline = time.time() + BUDGET
        enemies = [i for i in self.get_opponents(game_state)
                   if game_state.get_agent_position(i) is not None and
                   self.dist(self.my_pos(game_state), ipos(game_state.get_agent_position(i))) <= 6]
        order = [self.index] + enemies
        actions = [a for a in game_state.get_legal_actions(self.index) if a != Directions.STOP] or [Directions.STOP]
        best = actions[0]
        depth = 1
        try:
            while depth <= 8:
                value, choice = -INF, best
                for a in actions:
                    v = self.search(game_state.generate_successor(self.index, a), order, 1, depth, value, INF)
                    if v > value:
                        value, choice = v, a
                best = choice
                depth += 1
        except Timeout:
            pass
        return best

    def search(self, state, order, turn, depth, alpha, beta):
        if time.time() > self.deadline:
            raise Timeout
        if turn == len(order):
            turn, depth = 0, depth - 1
        if depth == 0 or state.is_over():
            return self.evaluate(state)
        agent = order[turn]
        maximise = agent == self.index
        v = -INF if maximise else INF
        for a in state.get_legal_actions(agent):
            child = self.search(state.generate_successor(agent, a), order, turn + 1, depth, alpha, beta)
            if maximise:
                v = max(v, child)
                alpha = max(alpha, v)
            else:
                v = min(v, child)
                beta = min(beta, v)
            if alpha >= beta:
                break
        return v

    def evaluate(self, state):
        me = state.get_agent_state(self.index)
        pos = ipos(me.get_position())
        v = 100 * self.get_score(state)
        enemies = [state.get_agent_state(i) for i in self.get_opponents(state)]
        if self.OFFENSE:
            food = self.get_food(state).as_list()
            v -= 20 * len(food)
            v -= 1.5 * min((self.dist(pos, f) for f in food), default=0)
            v += 8 * me.num_carrying
            v -= me.num_carrying * 0.6 * self.home_dist(pos)
            for e in enemies:
                epos = ipos(e.get_position())
                if epos is None or e.is_pacman:
                    continue
                d = self.dist(pos, epos)
                if e.scared_timer > 2:
                    v += 10 / (d + 1)
                elif me.is_pacman and d <= 2:
                    v -= 300 / (d + 1)
            if pos == self.start:
                v -= 200
        else:
            v -= 60 * sum(1 for e in enemies if e.is_pacman)
            seen = [ipos(e.get_position()) for e in enemies if e.is_pacman and e.get_position() is not None]
            if seen:
                v -= 4 * min(self.dist(pos, s) for s in seen)
            else:
                guesses = [self.guess(i) for i in self.get_opponents(state)]
                v -= 0.5 * min(self.dist(pos, b) for b in self.border) + \
                    0.3 * min(self.dist(pos, g) for g in guesses)
            if me.is_pacman:
                v -= 100
            v += 2 * len(self.get_food_you_are_defending(state).as_list())
        return v


class ABAttacker(ABAgent):
    OFFENSE = True


class ABDefender(ABAgent):
    OFFENSE = False


def create_team(first_index, second_index, is_red, **kw):
    return [ABAttacker(first_index), ABDefender(second_index)]
