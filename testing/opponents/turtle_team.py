"""Two defenders with sonar tracking. Tests whether we can break a wall."""
from zoo_common import ZooAgent


class Turtle(ZooAgent):
    def choose_action(self, game_state):
        self.track(game_state)
        mates = [i for i in self.get_team(game_state) if i != self.index]
        inv = self.invaders(game_state)
        if not inv and mates and self.index > mates[0]:
            # Second turtle sits on the door farthest from its partner.
            mate = game_state.get_agent_position(mates[0])
            if mate is not None:
                door = max(self.border, key=lambda b: self.dist(b, (int(mate[0]), int(mate[1]))))
                return self.toward(game_state, door)
        return self.defend(game_state)


def create_team(first_index, second_index, is_red, **kw):
    return [Turtle(first_index), Turtle(second_index)]
