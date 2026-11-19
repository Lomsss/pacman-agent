"""Score-driven roles: both attack when behind, both defend when ahead late."""
from zoo_common import ZooAgent


class Switcher(ZooAgent):
    def choose_action(self, game_state):
        self.track(game_state)
        score = self.get_score(game_state)
        time_left = game_state.data.timeleft
        first = self.index == min(self.get_team(game_state))
        if score > 0 and time_left < 600:
            return self.defend(game_state)
        if score < 0 or (first and not self.invaders(game_state)):
            return self.safe_food_step(game_state, carry_limit=5, flee=3)
        if first:
            return self.safe_food_step(game_state, carry_limit=4, flee=3)
        return self.defend(game_state)


def create_team(first_index, second_index, is_red, **kw):
    return [Switcher(first_index), Switcher(second_index)]
