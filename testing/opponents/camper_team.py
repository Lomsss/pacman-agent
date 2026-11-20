"""A greedy attacker plus a border camper that mirrors the nearest enemy.

The camper never crosses. It stands on the border square level with the
enemy it believes is closest, so any crossing runs straight into it, and it
only leaves the line to eat an invader it can see.
"""
from zoo_common import ZooAgent


class Attacker(ZooAgent):
    def choose_action(self, game_state):
        self.track(game_state)
        return self.safe_food_step(game_state, carry_limit=4, flee=3)


class Camper(ZooAgent):
    def choose_action(self, game_state):
        self.track(game_state)
        pos = self.my_pos(game_state)
        scared = game_state.get_agent_state(self.index).scared_timer > 0
        seen = [t for t in self.invaders(game_state) if t[3]]
        if seen and not scared:
            target = min(seen, key=lambda t: self.dist(pos, t[1]))[1]
            if self.dist(pos, target) <= 6:
                return self.toward(game_state, target)
        if seen or any(t for t in self.invaders(game_state)):
            if scared:
                return self.defend(game_state)
            if self.last_eaten is not None and self.is_home(self.last_eaten):
                return self.defend(game_state)
        guesses = [self.guess(i) for i in self.get_opponents(game_state)]
        threat = min(guesses, key=lambda g: min(self.dist(g, b) for b in self.border))
        spot = min(self.border, key=lambda b: (abs(b[1] - threat[1]), self.dist(b, threat)))
        return self.toward(game_state, spot)


def create_team(first_index, second_index, is_red, **kw):
    return [Attacker(first_index), Camper(second_index)]
