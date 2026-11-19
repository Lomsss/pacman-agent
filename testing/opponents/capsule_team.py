"""Capsule-first attacker that feasts while ghosts are scared, plus a defender."""
from zoo_common import ZooAgent


class CapsuleRaider(ZooAgent):
    def choose_action(self, game_state):
        self.track(game_state)
        scared = [g for g in self.ghosts(game_state, scared_ok=True) if g[2] > 5]
        enemies_scared = all(game_state.get_agent_state(i).scared_timer > 5 for i in self.get_opponents(game_state))
        if enemies_scared:
            return self.safe_food_step(game_state, carry_limit=14, flee=0)
        return self.safe_food_step(game_state, carry_limit=5, flee=3, capsule_bonus=3.0)


class Guard(ZooAgent):
    def choose_action(self, game_state):
        self.track(game_state)
        return self.defend(game_state)


def create_team(first_index, second_index, is_red, **kw):
    return [CapsuleRaider(first_index), Guard(second_index)]
