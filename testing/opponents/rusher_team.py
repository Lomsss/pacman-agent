"""Two greedy attackers that rush food and only flee ghosts that get close."""
from zoo_common import ZooAgent


class Rusher(ZooAgent):
    def choose_action(self, game_state):
        self.track(game_state)
        return self.safe_food_step(game_state, carry_limit=6, flee=2)


def create_team(first_index, second_index, is_red, **kw):
    return [Rusher(first_index), Rusher(second_index)]
