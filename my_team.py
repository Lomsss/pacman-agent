# my_team.py
# ---------------
# Licensing Information: Please do not distribute or publish solutions to this
# project. You are free to use and extend these projects for educational
# purposes. The Pacman AI projects were developed at UC Berkeley, primarily by
# John DeNero (denero@cs.berkeley.edu) and Dan Klein (klein@cs.berkeley.edu).
# For more info, see http://inst.eecs.berkeley.edu/~cs188/sp09/pacman.html

"""Contest capture team.

Offense paths to food it can still carry home, and crosses a defended
border instead of pacing it. Defense holds the corridor an invader must
use, and both agents read carried food, scared timers and pacman state
even when a position is hidden. Teammates also share sonar.
"""

import os
from collections import deque

from contest.capture_agents import CaptureAgent
from contest.game import Actions, Directions

_DEBUG = os.environ.get("PACMAN_DEBUG") == "1"
_INF = 99
# Particles below this probability are dropped so the cloud stays local.
# Keep the reachable set. Dropping low-probability cells deletes the true square
# once a random walk has spread out, and then food snaps can no longer land.
_MIN_PROB = 0.0008
_SIGHT = 5
_NOISE = 6
# Random maps can hide the nearest food 90 steps away. A short horizon
# makes the search pretend the food does not exist, and the agent wanders.
_HORIZON = 160
# Teammates share one module. The lower index clears this at each new game.
_SHARE = {"sonar": {}, "cover": {}, "hunt": {}}
# Scared longer than this, a ghost raids instead of shadowing the invader.
_SCARED_RAID = 12
# Seconds the attacker may spend searching a close fight. The limit is 1 s.
_SEARCH_TIME = float(os.environ.get("SEARCH_TIME", "0.25"))
_SEARCH_RANGE = int(os.environ.get("SEARCH_RANGE", "6"))


def create_team(first_index, second_index, is_red,
                first="ContestAgent", second="ContestAgent", num_training=0, **kwargs):
    """Return the pair that plays in the tournament (no extra options are passed)."""
    return [
        ContestAgent(first_index, role="offense"),
        ContestAgent(second_index, role="defense"),
    ]


def _ipos(pos):
    """Grid coordinate. AgentState positions can be floats such as 26.0."""
    if pos is None:
        return None
    return int(round(pos[0])), int(round(pos[1]))


def _manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class _Map:
    """Static layout facts. Rebuilt every game; random maps change."""

    def __init__(self, agent, game_state):
        walls = game_state.get_walls()
        self.width = walls.width
        self.height = walls.height
        self.mid = walls.width // 2
        self.red = agent.red
        self.neighbors = {}
        self.positions = []
        for x in range(walls.width):
            for y in range(walls.height):
                if walls[x][y]:
                    continue
                pos = (x, y)
                self.positions.append(pos)
        for pos in self.positions:
            nbs = []
            x, y = pos
            for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0)):
                nxt = (x + dx, y + dy)
                if nxt[0] < 0 or nxt[1] < 0 or nxt[0] >= walls.width or nxt[1] >= walls.height:
                    continue
                if not walls[nxt[0]][nxt[1]]:
                    nbs.append(nxt)
            self.neighbors[pos] = nbs

        self.home = set()
        self.enemy_squares = []
        for pos in self.positions:
            if self.on_home(pos):
                self.home.add(pos)
            else:
                self.enemy_squares.append(pos)

        # Steps to step off the enemy side. 0 on our side.
        self.dist_home = {pos: 0 for pos in self.home}
        queue = deque(self.home)
        while queue:
            pos = queue.popleft()
            for nxt in self.neighbors[pos]:
                if nxt in self.dist_home:
                    continue
                self.dist_home[nxt] = self.dist_home[pos] + 1
                queue.append(nxt)

        # Steps for an invader to reach their own side. 0 already on their side.
        self.dist_exit = {pos: 0 for pos in self.enemy_squares}
        queue = deque(self.enemy_squares)
        while queue:
            pos = queue.popleft()
            for nxt in self.neighbors[pos]:
                if nxt in self.dist_exit:
                    continue
                self.dist_exit[nxt] = self.dist_exit[pos] + 1
                queue.append(nxt)

        self.border = [
            pos for pos in self.home
            if any(not self.on_home(nxt) for nxt in self.neighbors[pos])
        ]
        if not self.border:
            self.border = list(self.home)
        self.border_set = set(self.border)

        # Distance back out of a corridor. Junctions and our side are 0.
        # Used when a defender's position cloud is too wide to treat as a wall.
        # Degree 1 is a dead end, not an exit. Only junctions and our side are safe mouths.
        exits = [
            pos for pos in self.positions
            if self.on_home(pos) or len(self.neighbors[pos]) >= 3
        ]
        self.tunnel = {pos: 0 for pos in exits}
        queue = deque(exits)
        while queue:
            pos = queue.popleft()
            for nxt in self.neighbors[pos]:
                if nxt in self.tunnel:
                    continue
                self.tunnel[nxt] = self.tunnel[pos] + 1
                queue.append(nxt)
        for pos in self.positions:
            self.tunnel.setdefault(pos, 30)

    def on_home(self, pos):
        if self.red:
            return pos[0] < self.mid
        return pos[0] >= self.mid


class ContestAgent(CaptureAgent):
    """One agent class, two roles. Roles swap when an invader has to be caught."""

    def __init__(self, index, role="offense", time_for_computing=0.1):
        super().__init__(index, time_for_computing)
        self.role = role
        self.start = None
        self.map = None
        self.belief = {}
        self.prev_enemy = {}
        self.spawns = {}
        self.prev_food = set()
        self.prev_caps = set()
        self.last_completed = 0
        self.initial_time = 1200
        self.food_to_win = 28
        self.hist = []
        self.opponents = []
        self.team = []
        self.my_scared = 0
        self.deaths = 0
        self.kills = 0
        self.last_bite = None
        self._last_me = None
        self._move_times = []
        self._stall_time = 0

    def register_initial_state(self, game_state):
        CaptureAgent.register_initial_state(self, game_state)
        self.start = _ipos(game_state.get_agent_position(self.index))
        self.map = _Map(self, game_state)
        self.opponents = list(self.get_opponents(game_state))
        self.team = list(self.get_team(game_state))
        self.initial_time = game_state.data.timeleft or 1200
        self.last_completed = 0
        self.hist = []
        self.deaths = 0
        self.kills = 0
        self.last_bite = None
        self._move_times = []
        self.my_scared = 0
        self._stall_time = 0
        total = len(self.get_food(game_state).as_list()) + len(self.get_food_you_are_defending(game_state).as_list())
        self.food_to_win = max(1, int(total / 2 - 2))

        self.belief = {}
        self.prev_enemy = {}
        self.spawns = {}
        for index in self.opponents:
            pos = _ipos(game_state.get_agent_position(index))
            if pos is None:
                pos = _ipos(game_state.get_initial_agent_position(index))
            self.spawns[index] = pos
            self.belief[index] = {pos: 1.0} if pos is not None else {}
            state = game_state.get_agent_state(index)
            self.prev_enemy[index] = {
                "pac": state.is_pacman,
                "carry": state.num_carrying,
                "returned": state.num_returned,
            }
        self.prev_food = set(map(_ipos, self.get_food_you_are_defending(game_state).as_list()))
        self.prev_caps = set(map(_ipos, self.get_capsules_you_are_defending(game_state)))
        # Lower index registers first, so this never wipes a teammate's fresh data.
        if self.index == min(self.team):
            _SHARE["sonar"].clear()
            _SHARE["cover"].clear()
            _SHARE["hunt"].clear()

    def final(self, game_state):
        if _DEBUG:
            avg = (sum(self._move_times) / len(self._move_times)) if self._move_times else 0
            returned = sum(game_state.get_agent_state(index).num_returned for index in self.team)
            line = (
                f"agent {self.index} role {self.role} deaths {self.deaths} kills {self.kills} "
                f"returned {returned} avg_ms {avg * 1000:.1f} "
                f"max_ms {max(self._move_times, default=0) * 1000:.1f}"
            )
            print(line)
        CaptureAgent.final(self, game_state)

    def choose_action(self, game_state):
        import time
        started = time.perf_counter()
        try:
            action = self._choose(game_state)
            legal = game_state.get_legal_actions(self.index)
            if action not in legal:
                action = self._fallback(game_state)
        except Exception:
            if _DEBUG:
                import traceback
                traceback.print_exc()
            action = self._fallback(game_state)
        elapsed = time.perf_counter() - started
        self._move_times.append(elapsed)
        return action

    # ----------------------------------------------------------------- state

    def _choose(self, game_state):
        me = self._self_pack(game_state)
        self.my_scared = me["scared"]
        if self.hist and self.hist[-1] != self.start and me["pos"] == self.start and not self.map.on_home(self.hist[-1]):
            self.deaths += 1
        self._update_beliefs(game_state, me)
        reports = self._reports(game_state, me)
        mode = self._mode(game_state, me, reports)
        if mode == "hunt":
            action = self._hunt(game_state, me, reports)
        elif mode == "flee":
            action = self._flee(game_state, me, reports)
        elif mode == "patrol":
            action = self._patrol(game_state, me, reports)
        elif mode == "raid":
            action = self._attack(game_state, me, reports, raid=True)
        else:
            action = self._attack(game_state, me, reports, raid=False)
        if self._stalled(me["pos"]):
            # A two-step wobble or a sit-in on their side never deposits food.
            self._stall_time += 1
            action = self._barge(game_state, me, reports, suicide=self._stall_time >= 5)
        else:
            self._stall_time = 0
        stepped = self._nxt(me["pos"], action)
        # The safe planner will pace our border forever if a belief cloud covers
        # the entry. While we are carrying nothing, take the food anyway and
        # only refuse the squares next to a ghost we can see.
        if (
            mode == "attack"
            and me["carrying"] == 0
            and self.map.on_home(me["pos"])
            and self.map.on_home(stepped)
        ):
            action = self._cross(game_state, me, reports)
        if mode in ("attack", "raid") and _SEARCH_TIME > 0:
            searched = self._tactics(game_state, me, reports, action)
            if searched is not None:
                action = searched
        self.hist.append(me["pos"])
        if len(self.hist) > 12:
            self.hist.pop(0)
        self.prev_food = set(map(_ipos, self.get_food_you_are_defending(game_state).as_list()))
        self.prev_caps = set(map(_ipos, self.get_capsules_you_are_defending(game_state)))
        return action

    def _self_pack(self, game_state):
        state = game_state.get_agent_state(self.index)
        return {
            "pos": _ipos(state.get_position()),
            "scared": int(state.scared_timer),
            "carrying": int(state.num_carrying),
            "pac": state.is_pacman,
        }

    def _completed(self, game_state):
        return self.initial_time - int(game_state.data.timeleft)

    def _team_positions(self, game_state):
        positions = []
        for index in self.team:
            pos = _ipos(game_state.get_agent_position(index))
            if pos is not None:
                positions.append(pos)
        return positions

    def _update_beliefs(self, game_state, me):
        completed = self._completed(game_state)
        start_index = (self.index - completed) % 4
        distances = game_state.get_agent_distances() or []
        team_positions = self._team_positions(game_state)
        self._last_me = me["pos"]
        missing = self.prev_food - set(map(_ipos, self.get_food_you_are_defending(game_state).as_list()))
        missing_caps = self.prev_caps - set(map(_ipos, self.get_capsules_you_are_defending(game_state)))
        # A capsule eat is also an exact square, same as a food eat.
        eaten = list(missing) + [cap for cap in missing_caps if cap not in missing]
        if eaten:
            self.last_bite = (eaten[-1], completed)

        snapshots = {}
        for index in self.opponents:
            state = game_state.get_agent_state(index)
            snapshots[index] = {
                "pos": _ipos(game_state.get_agent_position(index)),
                "pac": bool(state.is_pacman),
                "scared": int(state.scared_timer),
                "carry": int(state.num_carrying),
                "returned": int(state.num_returned),
                "noisy": int(distances[index]) if distances else 0,
            }

        moves = {
            index: self._moves_between(start_index, index, self.last_completed, completed)
            for index in self.opponents
        }

        # Death is a teleport. Returning home is not: carried food is scored.
        for index in self.opponents:
            prev = self.prev_enemy[index]
            cur = snapshots[index]
            if prev["pac"] and not cur["pac"] and prev["carry"] > 0 and cur["returned"] == prev["returned"]:
                spawn = self.spawns.get(index)
                self.belief[index] = {spawn: 1.0} if spawn is not None else {}
                moves[index] = 0
                self.kills += 1

        for index in self.opponents:
            for _ in range(moves[index]):
                self.belief[index] = self._motion(self.belief[index])
            cur = snapshots[index]
            if cur["pos"] is not None:
                self.belief[index] = {cur["pos"]: 1.0}
            else:
                observed = self._observe(
                    self.belief[index], me["pos"], cur["noisy"], team_positions, cur["pac"]
                )
                if observed:
                    self.belief[index] = observed
                else:
                    self.belief[index] = self._reseed(
                        me["pos"], cur["noisy"], team_positions, cur["pac"]
                    )
                self.belief[index] = self._fuse(index, self.belief[index], completed)

        self._snap_eaten(snapshots, eaten)
        _SHARE["sonar"][self.index] = {
            "completed": completed,
            "pos": me["pos"],
            "noisy": {index: snapshots[index]["noisy"] for index in self.opponents},
        }
        for index in self.opponents:
            cur = snapshots[index]
            self.prev_enemy[index] = {
                "pac": cur["pac"],
                "carry": cur["carry"],
                "returned": cur["returned"],
            }
        self.last_completed = completed

    def _fuse(self, index, belief, completed):
        """Drop particles the teammate's sonar already rules out.

        Their reading is from their own square, so the two annuli intersect.
        One opponent moves between the two observations; allow one extra step
        for that opponent and keep the old cloud if the filter would erase it.
        """
        if not belief:
            return belief
        mate = None
        mate_index = None
        for key, pack in _SHARE["sonar"].items():
            if key != self.index:
                mate = pack
                mate_index = key
        if not mate or mate.get("pos") is None:
            return belief
        age = completed - int(mate.get("completed", -999))
        if age <= 0 or age > 3:
            return belief
        mate_noisy = mate.get("noisy", {}).get(index)
        if mate_noisy is None:
            return belief
        tol = _NOISE + (1 if self._enemy_moved(index, mate_index) else 0)
        updated = {}
        for pos, prob in belief.items():
            if abs(_manhattan(pos, mate["pos"]) - mate_noisy) > tol:
                continue
            updated[pos] = prob
        if not updated:
            return belief
        return self._trim(updated)

    def _enemy_moved(self, enemy, mate_index):
        cursor = mate_index
        while cursor != self.index:
            if cursor == enemy:
                return True
            cursor = (cursor + 1) % 4
        return False

    def _moves_between(self, start_index, enemy, begin, end):
        count = 0
        for step in range(begin, end):
            if (start_index + step) % 4 == enemy:
                count += 1
        return count

    def _motion(self, belief):
        if not belief:
            return {}
        updated = {}
        for pos, prob in belief.items():
            options = self.map.neighbors.get(pos, [])
            if not options:
                updated[pos] = updated.get(pos, 0.0) + prob
                continue
            # Stay is legal, but real agents rarely camp a single square forever.
            options = options + [pos]
            share = prob / float(len(options))
            for nxt in options:
                updated[nxt] = updated.get(nxt, 0.0) + share
        return self._trim(updated)

    def _observe(self, belief, my_pos, noisy, team_positions, is_pacman):
        if not belief:
            return {}
        updated = {}
        for pos, prob in belief.items():
            if not self._sensor_ok(pos, my_pos, noisy, team_positions, is_pacman):
                continue
            updated[pos] = prob
        return self._trim(updated)

    def _sensor_ok(self, pos, my_pos, noisy, team_positions, is_pacman):
        if abs(_manhattan(pos, my_pos) - noisy) > _NOISE:
            return False
        for teammate in team_positions:
            if _manhattan(pos, teammate) <= _SIGHT:
                return False
        on_home = self.map.on_home(pos)
        if is_pacman and not on_home:
            return False
        if (not is_pacman) and on_home:
            return False
        return True

    def _reseed(self, my_pos, noisy, team_positions, is_pacman):
        cells = [
            pos for pos in self.map.positions
            if self._sensor_ok(pos, my_pos, noisy, team_positions, is_pacman)
        ]
        if not cells:
            # Keep the side constraint even if the sonar reading is inconsistent.
            cells = [
                pos for pos in self.map.positions
                if self.map.on_home(pos) == is_pacman
            ]
        if not cells:
            cells = list(self.map.positions)
        share = 1.0 / float(len(cells))
        return {pos: share for pos in cells}

    def _trim(self, belief):
        if not belief:
            return {}
        total = sum(belief.values())
        if total <= 0:
            return {}
        kept = {pos: prob / total for pos, prob in belief.items() if prob / total >= _MIN_PROB}
        if not kept:
            top = max(belief.items(), key=lambda item: item[1])
            return {top[0]: 1.0}
        total = sum(kept.values())
        return {pos: prob / total for pos, prob in kept.items()}

    def _snap_eaten(self, snapshots, eaten):
        """An eaten dot is the square that pacman just landed on.

        The cloud often does not contain that square (a long random walk gets
        trimmed, or the ghost crossed the map). The bite itself is enough.
        """
        if not eaten:
            return
        remaining = list(eaten)
        pacmen = [
            index for index in self.opponents
            if snapshots[index]["pac"] and snapshots[index]["pos"] is None
        ]
        if not pacmen:
            return

        def score(index, food):
            noisy = snapshots[index]["noisy"]
            sonar = abs(_manhattan(food, self._last_me) - noisy)
            cloud = self.belief.get(index, {})
            if cloud:
                cloud_dist = min(_manhattan(food, pos) for pos in cloud)
            else:
                cloud_dist = 0
            return (0 if sonar <= _NOISE else 1, sonar, cloud_dist)

        # One pacman can eat one dot per move. Assign uniquely, closest first.
        pairs = []
        for index in pacmen:
            for food in remaining:
                pairs.append((score(index, food), index, food))
        pairs.sort(key=lambda item: item[0])
        used_agents = set()
        used_food = set()
        for _, index, food in pairs:
            if index in used_agents or food in used_food:
                continue
            self.belief[index] = {food: 1.0}
            used_agents.add(index)
            used_food.add(food)

    def _reports(self, game_state, me):
        reports = []
        for index in self.opponents:
            state = game_state.get_agent_state(index)
            belief = self.belief.get(index, {})
            visible = _ipos(game_state.get_agent_position(index))
            exact = visible
            if exact is None and belief:
                top_pos, top_prob = max(belief.items(), key=lambda item: item[1])
                if top_prob >= 0.85 and len(belief) == 1:
                    exact = top_pos
            probs = list(belief.values())
            if probs:
                peak = max(probs)
                eff = 1.0 / sum(prob * prob for prob in probs)
            else:
                peak = 0.0
                eff = 999.0
            map_pos = None
            if belief:
                map_pos = max(belief.items(), key=lambda item: item[1])[0]
            noisy = 0
            distances = game_state.get_agent_distances()
            if distances:
                noisy = int(distances[index])
            if visible is not None:
                lower = _manhattan(me["pos"], visible)
            else:
                lower = max(_SIGHT + 1, noisy - _NOISE, 0)
            reports.append({
                "index": index,
                "pos": exact,
                "visible": visible,
                "is_pacman": bool(state.is_pacman),
                "scared": int(state.scared_timer),
                "carrying": int(state.num_carrying),
                "belief": belief,
                "map_pos": map_pos,
                "peak": peak,
                "eff": eff,
                "diffuse": len(belief) > 12 or (peak < 0.25 and eff > 12),
                "lower": lower,
                "spawn": self.spawns.get(index),
            })
        return reports

    # ----------------------------------------------------------------- roles

    def _mode(self, game_state, me, reports):
        invaders = [report for report in reports if report["is_pacman"]]
        time_left = int(game_state.data.timeleft)
        score = self.get_score(game_state)
        close_out = (
            (score > 0 and time_left < 170)
            or (score >= 4 and time_left < 300)
            or (score >= 8 and time_left < 480)
        )
        if self.my_scared > 0 and self.map.on_home(me["pos"]):
            if not invaders:
                return "patrol"
            # A scared ghost cannot stop the invader. Score on their side
            # while the timer runs, and come back to shadow it near the end.
            if self.my_scared > _SCARED_RAID and time_left > 120:
                return "attack"
            return "hunt"
        if invaders:
            if close_out or self._should_hunt(game_state, me, invaders):
                return "hunt"
            return "attack"
        if close_out:
            return "patrol"
        if self.role == "defense" and not self._should_raid(game_state, me, reports, score, time_left):
            return "patrol"
        if self.role == "defense":
            return "raid"
        return "attack"

    def _should_hunt(self, game_state, me, invaders):
        my_dist = self._invader_dist(me["pos"], invaders)
        teammate = self._teammate_pos(game_state)
        mate_dist = self._invader_dist(teammate, invaders) if teammate else 999
        loaded = max(report["carrying"] for report in invaders)
        # A fat payload on our side is worth more than another food run.
        if loaded >= 4 and my_dist <= mate_dist + (0 if self.role == "defense" else 2):
            if me["carrying"] >= 4 and self.map.dist_home[me["pos"]] <= 3 and mate_dist <= my_dist + 4:
                return False
            return True
        if self.role == "defense":
            return True
        return my_dist + 2 < mate_dist

    def _should_raid(self, game_state, me, reports, score, time_left):
        # An empty home is a free score for them. Only cross while they are scared.
        if time_left < 160 or any(report["is_pacman"] for report in reports):
            return False
        ghosts = [report for report in reports if not report["is_pacman"]]
        return bool(ghosts) and all(report["scared"] > 10 for report in ghosts)

    def _invader_dist(self, origin, invaders):
        if origin is None:
            return 999
        best = 999
        for report in invaders:
            anchor = report["pos"] or report["map_pos"]
            if anchor is None:
                best = min(best, report["lower"] + 4)
            else:
                best = min(best, self._md(origin, anchor))
        return best

    def _teammate_pos(self, game_state):
        for index in self.team:
            if index == self.index:
                continue
            return _ipos(game_state.get_agent_position(index))
        return None

    # -------------------------------------------------------------- offense

    def _attack(self, game_state, me, reports, raid=False, force_home=False):
        pos = me["pos"]
        carrying = me["carrying"]
        time_left = int(game_state.data.timeleft)
        dist_home = self.map.dist_home[pos]
        ghosts = [report for report in reports if not report["is_pacman"]]
        min_scared = min((report["scared"] for report in ghosts), default=0)
        any_unscared = any(report["scared"] == 0 for report in ghosts)
        feast = (not any_unscared) and ghosts and min_scared > 8
        returned = sum(game_state.get_agent_state(index).num_returned for index in self.team)
        must_deposit = carrying > 0 and returned + carrying >= self.food_to_win
        moves_left = time_left / 4.0
        if not ghosts:
            # Their side is empty. Sweep, then bank.
            carry_limit = 10
        elif raid:
            carry_limit = 3
        elif feast:
            carry_limit = 12
        elif self.get_score(game_state) < 0 and time_left < 450:
            carry_limit = 8
        elif time_left < 180:
            carry_limit = 2
        elif any(report["scared"] == 0 and report["lower"] <= 8 for report in ghosts):
            carry_limit = 3
        else:
            # Short trips survive a defender who reaches the only gate.
            carry_limit = 3

        go_home = must_deposit or (
            carrying > 0 and (
                carrying >= carry_limit
                or dist_home + 1 >= moves_left
                or (feast and min_scared <= dist_home + 2)
                or (not feast and dist_home <= 2 and carrying >= 2 and not raid)
            )
        )
        if feast and dist_home >= max(1, min_scared - 2):
            go_home = True
        if raid and carrying >= 1 and (any_unscared and min(report["lower"] for report in ghosts) <= dist_home + 2):
            go_home = True
        # A known defender as close as the border will eat a loaded pacman.
        # Bank first; the food is still there next trip.
        if carrying >= 1 and not feast:
            for report in ghosts:
                if report["scared"] == 0 and not report["diffuse"] and report["lower"] <= max(3, dist_home):
                    go_home = True
                    break

        unknown = any(report["diffuse"] and report["scared"] == 0 for report in ghosts)
        lowers = [report["lower"] for report in ghosts if report["scared"] == 0]
        lower = min(lowers) if lowers else 99

        loose_cut = 0.22 if carrying == 0 else 0.1
        strict_cut = 0.08
        loose = self._safety(ghosts, loose_cut, pos, slack=4)
        strict = self._safety(ghosts, strict_cut, pos, slack=1 if carrying else 3)
        forward_safety = strict if carrying > 0 else loose

        if force_home and not self.map.on_home(pos):
            for safety in (strict, loose, None):
                action = self._travel_home(pos, safety)
                if action is not None:
                    return action
            return self._hold_home(game_state, me, ghosts)

        if go_home and not self.map.on_home(pos):
            action = self._travel_home(pos, strict if not feast else None)
            if action is not None:
                return action
            action = self._travel_home(pos, loose)
            if action is not None:
                return action
            # Stepping back to the square we just left is how a run freezes
            # one step from home. Hold the frontier instead of wobbling.
            return self._hold_home(game_state, me, ghosts)

        # Wide clouds are not walls. Alleys are the actual trap, so limit those
        # and keep taking food that has a junction nearby.
        # Most pellets sit in dead ends. The sonar gap is how deep a round trip can be.
        if unknown:
            max_tunnel = max(2, (lower - 1) // 2)
            max_tunnel = min(max_tunnel, 8)
        else:
            max_tunnel = 99
        home_cap = 6 if raid else 99

        foods = self._foods(game_state)
        capsules = [_ipos(cap) for cap in self.get_capsules(game_state)]
        teammate = self._teammate_pos(game_state)
        primary = min(self.team) == self.index

        dist, parent = self._bfs(pos, forward_safety)
        best = None
        best_cost = 10 ** 9
        for food in foods:
            if food not in dist:
                continue
            if self.map.dist_home.get(food, 99) > home_cap:
                continue
            if self.map.tunnel.get(food, 0) > max_tunnel:
                continue
            depth = dist[food]
            if carrying == 0 and not self._can_escape(food, depth, strict if not feast else None):
                continue
            cost = depth + 1.15 * self.map.dist_home[food]
            if teammate is not None and not primary:
                if self._md(teammate, food) + 1 < depth:
                    cost += 4
            # Break ties toward food far from a known defender.
            exit_sq = min(self.map.border, key=lambda border: self._md(food, border))
            for report in ghosts:
                if report["scared"] > depth + 2:
                    continue
                anchor = report["pos"] or (None if report["diffuse"] else report["map_pos"])
                if anchor is None:
                    continue
                # Food behind a door the defender is sitting on is a death, not a score.
                if self._md(anchor, exit_sq) <= 2:
                    cost += 7
                else:
                    cost -= min(5.0, self._md(food, anchor) * 0.15)
            if cost < best_cost:
                best_cost = cost
                best = food

        # Capsule only when it changes a blocked or scary position.
        capsule_useful = (best is None) or any(
            report["scared"] == 0 and report["lower"] <= 10 for report in ghosts
        )
        if capsule_useful:
            for capsule in capsules:
                if capsule not in dist:
                    continue
                cost = dist[capsule] - (10 if best is None else 4)
                if cost < best_cost:
                    best_cost = cost
                    best = capsule

        # Removing a scared defender sends them to spawn for the rest of the feast.
        if feast or any(report["scared"] > 0 for report in ghosts):
            for report in ghosts:
                anchor = report["visible"] or report["pos"]
                if anchor is None or report["scared"] <= 1:
                    continue
                if anchor not in dist:
                    continue
                if dist[anchor] >= report["scared"]:
                    continue
                if dist[anchor] > 8 and best is not None:
                    continue
                cost = dist[anchor] - 8
                if cost < best_cost:
                    best_cost = cost
                    best = anchor

        if best is None:
            return self._commit(game_state, me, ghosts, foods)

        nxt = self._first(parent, pos, best)
        action = self._dir(pos, nxt)
        if self._blocked(nxt):
            return self._commit(game_state, me, ghosts, foods)
        return action

    # ------------------------------------------------------------ tactics

    def _tactics(self, game_state, me, reports, planned):
        """Alpha-beta look-ahead when a ghost we can see is close.

        The model holds our square, the visible ghosts, the dots we eat on
        the way, what we carry and what we bank. Ghosts move after us and
        stay on their side. Depth grows one round at a time until the time
        budget is spent, so a quiet position costs nothing and a fight gets
        as deep as the clock allows.
        """
        import time
        pos = me["pos"]
        ghosts = []
        for report in reports:
            if report["is_pacman"] or report["visible"] is None:
                continue
            if report["scared"] > 2:
                continue
            if self._md(pos, report["visible"]) <= _SEARCH_RANGE:
                ghosts.append(report["visible"])
        if not ghosts:
            return None
        if self.map.on_home(pos) and me["carrying"] == 0:
            # Only worth it at the door: about to cross with a guard nearby.
            if self.map.dist_home.get(pos, 0) == 0 and pos not in self.map.border_set:
                return None
        self._tac_food = set(self._foods(game_state))
        self._tac_caps = set(_ipos(cap) for cap in self.get_capsules(game_state))
        self._tac_deadline = time.perf_counter() + _SEARCH_TIME
        self._tac_planned = self._nxt(pos, planned)
        start = (pos, tuple(ghosts), frozenset(), me["carrying"], 0)
        legal = game_state.get_legal_actions(self.index)
        moves = [(action, self._nxt(pos, action)) for action in legal]
        ordered = sorted(moves, key=lambda item: 0 if item[1] == self._tac_planned else 1)
        done = None
        depth = 1
        while depth <= 12:
            scores = {}
            alpha = -1e9
            try:
                for action, nxt in ordered:
                    value = self._tac_after_me(self._tac_step(start, nxt), depth, alpha, 1e9)
                    if action == Directions.STOP:
                        value -= 0.5
                    scores[action] = value
                    alpha = max(alpha, value)
            except TimeoutError:
                break
            done = scores
            if max(scores.values()) <= -900:
                break
            depth += 1
        # Keep the strategic plan unless the search proves it walks into a
        # catch that another move avoids. The plan is searched first, so its
        # value is exact; the others are bounds, but the best one is exact.
        if not done or planned not in done:
            return None
        best_action = max(done, key=done.get)
        if done[planned] > -900 or done[best_action] <= -900:
            return planned
        return best_action

    def _tac_step(self, state, nxt):
        me, ghosts, eaten, carry, banked = state
        if nxt in ghosts:
            return None
        if nxt in self._tac_food and nxt not in eaten:
            eaten = eaten | {nxt}
            carry += 1
        if nxt in self._tac_caps and nxt not in eaten:
            eaten = eaten | {nxt}
            return (nxt, (), eaten, carry, banked + 0.5)
        if self.map.on_home(nxt) and carry:
            banked += carry
            carry = 0
        return (nxt, ghosts, eaten, carry, banked)

    def _tac_after_me(self, state, depth, alpha, beta):
        """Ghosts' turn: each ghost picks its move, minimising our value."""
        import time
        if state is None:
            return -1000
        if time.perf_counter() > self._tac_deadline:
            raise TimeoutError
        me, ghosts, eaten, carry, banked = state
        if not ghosts or self.map.on_home(me):
            return self._tac_value(state, depth)
        options = []
        for ghost in ghosts:
            moves = [cell for cell in self.map.neighbors[ghost] if not self.map.on_home(cell)] + [ghost]
            moves.sort(key=lambda cell: _manhattan(cell, me))
            options.append(moves[:4])
        combos = [()]
        for moves in options:
            combos = [combo + (cell,) for combo in combos for cell in moves]
        value = 1e9
        for combo in combos:
            if me in combo:
                result = -1000 - 5 * carry
            else:
                result = self._tac_me((me, combo, eaten, carry, banked), depth - 1, alpha, beta)
            if result < value:
                value = result
            if value <= alpha:
                return value
            if value < beta:
                beta = value
        return value

    def _tac_me(self, state, depth, alpha, beta):
        if depth <= 0:
            return self._tac_value(state, depth)
        me = state[0]
        value = -1e9
        for nxt in self.map.neighbors[me] + [me]:
            result = self._tac_after_me(self._tac_step(state, nxt), depth, alpha, beta)
            if result > value:
                value = result
            if value >= beta:
                return value
            if value > alpha:
                alpha = value
        return value

    def _tac_value(self, state, depth):
        me, ghosts, eaten, carry, banked = state
        value = 12.0 * banked + 3.0 * carry
        # Sooner is better: rounds left unused add a little.
        value += 0.05 * max(depth, 0)
        home = self.map.dist_home.get(me, 0)
        value -= 0.25 * carry * home
        left = [food for food in self._tac_food if food not in eaten]
        if left and carry < 6:
            value -= 0.4 * min(_manhattan(me, food) for food in left)
        if not self.map.on_home(me):
            for ghost in ghosts:
                gap = self._md(me, ghost)
                if gap <= 1:
                    value -= 400
                elif gap == 2:
                    value -= 30
                elif gap <= 4:
                    value -= 6.0 / gap
                # A corridor deeper than the ghost's lead is a trap.
                if self.map.tunnel.get(me, 0) * 2 >= gap:
                    value -= 15
        return value

    def _commit(self, game_state, me, ghosts, foods):
        """Take food when the safe plan has nothing. Only refuse a square a ghost can step onto."""
        pos = me["pos"]
        if me["carrying"] > 0 and not self.map.on_home(pos):
            action = self._travel_home(pos, None)
            if action is not None:
                return action
        threats = []
        for report in ghosts:
            if report["scared"] > 4:
                continue
            anchor = report["visible"] or report["map_pos"]
            if anchor is not None:
                threats.append(anchor)
        blocked = set()
        for anchor in threats:
            for square in self.map.enemy_squares:
                if self._md(anchor, square) <= 1:
                    blocked.add(square)
        safety = None
        if blocked:
            safety = {square: (-1 if square in blocked else _INF) for square in self.map.enemy_squares}
        dist, parent = self._bfs(pos, safety)
        capsules = [_ipos(cap) for cap in self.get_capsules(game_state)]
        goal = None
        best_cost = 10 ** 9
        for food in foods:
            if food not in dist:
                continue
            cost = dist[food] + 0.35 * self.map.dist_home.get(food, 20) + 0.7 * self.map.tunnel.get(food, 0)
            if cost < best_cost:
                best_cost = cost
                goal = food
        for capsule in capsules:
            if capsule not in dist:
                continue
            # A stuck offense should take the capsule and then ignore the defender.
            cost = dist[capsule] - 2
            if goal is None:
                cost -= 6
            if cost < best_cost:
                best_cost = cost
                goal = capsule
        if goal is None:
            return self._least_danger_step(game_state, me, ghosts, foods)
        return self._dir(pos, self._first(parent, pos, goal))

    def _can_escape(self, origin, depth, safety):
        if self.map.on_home(origin):
            return True
        if safety is None:
            return True
        seen = {origin}
        queue = deque([(origin, depth)])
        while queue:
            pos, dist = queue.popleft()
            for nxt in self.map.neighbors[pos]:
                if nxt in seen:
                    continue
                nd = dist + 1
                if nd > _HORIZON:
                    continue
                if not self._enter(nxt, nd, safety):
                    continue
                if self.map.on_home(nxt):
                    return True
                seen.add(nxt)
                queue.append((nxt, nd))
        return False

    def _travel_home(self, pos, safety):
        if self.map.on_home(pos):
            return Directions.STOP
        dist, parent = self._bfs(pos, safety)
        homes = [cell for cell in dist if self.map.on_home(cell)]
        if not homes:
            return None
        goal = min(homes, key=lambda cell: dist[cell])
        nxt = self._first(parent, pos, goal)
        if self._blocked(nxt):
            return None
        return self._dir(pos, nxt)

    def _foods(self, game_state):
        return [_ipos(food) for food in self.get_food(game_state).as_list()]

    def _stalled(self, pos):
        if len(self.hist) < 8:
            return False
        recent = self.hist[-8:]
        kinds = len(set(recent))
        if kinds == 2:
            return True
        # Camping our border is defense. Sitting on their side is a wasted trip.
        return kinds == 1 and not self.map.on_home(pos)

    def _hold_home(self, game_state, me, ghosts):
        """Step toward home, or wait. Never step back into the square we fled."""
        pos = me["pos"]
        legal = game_state.get_legal_actions(self.index)
        here = self.map.dist_home.get(pos, 99)
        likely = self._likely_ghosts(ghosts, 0.08)
        best = Directions.STOP if Directions.STOP in legal else legal[0]
        best_key = None
        for action in legal:
            nxt = self._nxt(pos, action)
            dist = self.map.dist_home.get(nxt, 99)
            if dist > here:
                continue
            worst = 0
            if not (self.map.on_home(nxt) and self.my_scared <= 0):
                for ghost_pos, scared in likely:
                    if scared > 1:
                        continue
                    gap = self._md(ghost_pos, nxt)
                    if gap <= 1:
                        worst += 5
                    elif gap == 2:
                        worst += 2
            key = (1 if worst >= 5 else 0, dist, 1 if action == Directions.STOP else 0)
            if best_key is None or key < best_key:
                best_key = key
                best = action
        return best

    def _barge(self, game_state, me, reports, suicide=False):
        """Commit to a direction after the agent has been pacing the same squares."""
        pos = me["pos"]
        legal = game_state.get_legal_actions(self.index)
        visible = [
            report["visible"]
            for report in reports
            if (not report["is_pacman"]) and report["scared"] == 0 and report["visible"] is not None
        ]
        if me["carrying"] or not self.map.on_home(pos):
            goals = None
            if not me["carrying"]:
                goals = self._foods(game_state) + [_ipos(cap) for cap in self.get_capsules(game_state)]

            def progress(nxt):
                if me["carrying"] or not goals:
                    return self.map.dist_home.get(nxt, 99)
                return min(self._md(nxt, goal) for goal in goals)
        else:
            anchors = []
            for report in reports:
                if not report["is_pacman"]:
                    continue
                anchor = report["visible"] or report["pos"] or report["map_pos"]
                if anchor is not None:
                    anchors.append(anchor)
            if not anchors and self.map.border:
                anchors = list(self.map.border)

            def progress(nxt):
                if not self.map.on_home(nxt):
                    return 80
                if not anchors:
                    return 0
                return min(self._md(nxt, anchor) for anchor in anchors)

        best = legal[0]
        best_key = None
        for action in legal:
            nxt = self._nxt(pos, action)
            # Only the square a ghost is standing on is death this turn.
            # Treating "nearby" as a wall is what freezes a loaded pacman in an alley.
            on_ghost = 0 if suicide else (1 if nxt in visible else 0)
            key = (on_ghost, progress(nxt), 1 if action == Directions.STOP else 0, self.map.tunnel.get(nxt, 0))
            if best_key is None or key < best_key:
                best_key = key
                best = action
        return best

    def _cross(self, game_state, me, reports):
        """Step onto their side when pacing our border has gone on too long."""
        pos = me["pos"]
        visible = {
            report["visible"]
            for report in reports
            if (not report["is_pacman"]) and report["scared"] == 0 and report["visible"] is not None
        }
        blocked = set(visible)
        for ghost in visible:
            for square in self.map.enemy_squares:
                if self._md(ghost, square) <= 1:
                    blocked.add(square)
        safety = None
        if blocked:
            safety = {square: (-1 if square in blocked else _INF) for square in self.map.enemy_squares}
        dist, parent = self._bfs(pos, safety)
        foods = self._foods(game_state)
        capsules = [_ipos(cap) for cap in self.get_capsules(game_state)]
        goal = None
        best_cost = 10 ** 9
        for food in list(foods) + capsules:
            if food not in dist:
                continue
            cost = dist[food] + 0.35 * self.map.dist_home.get(food, 20)
            if self.map.border:
                exit_sq = min(self.map.border, key=lambda border: self._md(food, border))
                for ghost in visible:
                    if self._md(ghost, exit_sq) <= 2:
                        cost += 12
                        break
            if food in capsules:
                cost -= 4
            if cost < best_cost:
                best_cost = cost
                goal = food
        if goal is not None:
            return self._dir(pos, self._first(parent, pos, goal))
        legal = game_state.get_legal_actions(self.index)
        target = min(foods, key=lambda food: self._md(pos, food)) if foods else None
        best = legal[0]
        best_key = None
        for action in legal:
            nxt = self._nxt(pos, action)
            if nxt in visible:
                continue
            if target is None:
                key = (0 if not self.map.on_home(nxt) else 1, 1 if action == Directions.STOP else 0)
            else:
                key = (self._md(nxt, target), 1 if action == Directions.STOP else 0)
            if best_key is None or key < best_key:
                best_key = key
                best = action
        return best

    def _least_danger_step(self, game_state, me, ghosts, foods):
        pos = me["pos"]
        legal = game_state.get_legal_actions(self.index)
        likely = self._likely_ghosts(ghosts, 0.08)
        uncertain = any(report["diffuse"] and report["scared"] == 0 for report in ghosts)

        def danger(nxt):
            if self.map.on_home(nxt) and self.my_scared <= 0:
                return 0
            worst = 0
            for ghost_pos, scared in likely:
                if scared > 1:
                    continue
                dist = self._md(ghost_pos, nxt)
                if dist <= 1:
                    worst += 5
                elif dist == 2:
                    worst += 2
            if uncertain and not self.map.on_home(nxt):
                worst += self.map.tunnel.get(nxt, 0)
            return worst

        best_action = legal[0]
        best_key = None
        target = None
        if foods and not me["carrying"]:
            target = min(
                foods,
                key=lambda food: self._md(pos, food) + self.map.dist_home[food] + 2 * self.map.tunnel.get(food, 0),
            )
        for action in legal:
            nxt = self._nxt(pos, action)
            if nxt not in self.map.neighbors and nxt != pos and action != Directions.STOP:
                continue
            key = (
                1 if danger(nxt) >= 5 else 0,
                self.map.dist_home.get(nxt, 99) if me["carrying"] else (0 if target is None else self._md(nxt, target)),
                danger(nxt),
                1 if action == Directions.STOP else 0,
            )
            if best_key is None or key < best_key:
                best_key = key
                best_action = action
        return best_action

    def _likely_ghosts(self, ghosts, cutoff):
        found = []
        for report in ghosts:
            if report["diffuse"]:
                continue
            for pos, prob in report["belief"].items():
                if prob >= cutoff:
                    found.append((pos, report["scared"]))
            if report["visible"] is not None:
                found.append((report["visible"], report["scared"]))
        return found

    def _threat_cells(self, report, cutoff, origin):
        """Cells we actually route around.

        A wide cloud is a weak guess. Treat it as one estimated square, unless
        part of the cloud is already close enough to trap us this trip.
        """
        if report["visible"] is not None:
            return [report["visible"]]
        belief = report["belief"]
        if not belief:
            return []
        likely = [cell for cell, prob in belief.items() if prob >= cutoff]
        if not likely:
            likely = [report["map_pos"]] if report["map_pos"] is not None else []
        near = [cell for cell in likely if self._md(origin, cell) <= 7]
        if near:
            return near
        if report["map_pos"] is not None:
            return [report["map_pos"]]
        return likely[:1]

    def _safety(self, ghosts, cutoff, origin, slack=0):
        """Max arrival step still safe from the ghosts we are willing to believe.

        slack is extra steps granted against an unseen estimate. A ghost we can
        see is never given slack, so we still refuse to step next to them.
        """
        packs = []
        for report in ghosts:
            cells = self._threat_cells(report, cutoff, origin)
            if cells:
                packs.append((cells, report["scared"], report["visible"] is not None))
        if not packs:
            return None
        safety = {}
        for square in self.map.enemy_squares:
            worst = _INF
            for cells, scared, seen in packs:
                local = _INF
                extra = 0 if seen else slack
                for cell in cells:
                    local = min(local, max(scared - 1, self._md(cell, square) + extra - 1))
                worst = min(worst, local)
            safety[square] = worst
        return safety

    def _bfs(self, start, safety):
        dist = {start: 0}
        parent = {start: None}
        queue = deque([start])
        while queue:
            pos = queue.popleft()
            depth = dist[pos]
            if depth >= _HORIZON:
                continue
            for nxt in self.map.neighbors[pos]:
                if nxt in dist:
                    continue
                if not self._enter(nxt, depth + 1, safety):
                    continue
                dist[nxt] = depth + 1
                parent[nxt] = pos
                queue.append(nxt)
        return dist, parent

    def _enter(self, square, depth, safety):
        if self.map.on_home(square):
            if self.my_scared <= 0 or depth >= self.my_scared:
                return True
            # Still scared on arrival: do not step onto a square an invader can reach.
            return True
        if safety is None:
            return True
        return depth <= safety.get(square, -1)

    # -------------------------------------------------------------- defense

    def _hunt(self, game_state, me, reports):
        if not self.map.on_home(me["pos"]):
            return self._attack(game_state, me, reports, force_home=True)
        invaders = [report for report in reports if report["is_pacman"]]
        if not invaders:
            return self._patrol(game_state, me, reports)
        # Standing next to an invader ends the raid this turn. Do that before any plan.
        for report in invaders:
            anchor = report["visible"] or report["pos"]
            if anchor is None or not self.map.on_home(anchor):
                continue
            if anchor in self.map.neighbors[me["pos"]] and self.my_scared == 0:
                return self._dir(me["pos"], anchor)
        if self.my_scared > 0 and not any(report["pos"] or report["map_pos"] for report in invaders):
            return self._flee(game_state, me, reports)
        # Highest payload, then the one we can reach sooner.
        invaders.sort(key=lambda report: (
            -report["carrying"],
            self._invader_dist(me["pos"], [report]),
        ))
        target = invaders[0]
        anchor = target["pos"] or target["map_pos"]
        if (anchor is None or not self.map.on_home(anchor)) and self.last_bite is not None:
            bite, when = self.last_bite
            if self._completed(game_state) - when <= 12:
                anchor = bite
        if anchor is None or not self.map.on_home(anchor):
            return self._patrol(game_state, me, reports)
        _SHARE["hunt"][self.index] = (anchor, self._completed(game_state))
        return self._pursue(game_state, me, target, anchor)

    def _pursue(self, game_state, me, target, anchor):
        """Pick the step that leaves the invader the smallest safe region.

        A cell is the invader's if it reaches it strictly before every
        hunter. Hunters are ghosts only on our side, so their distances stop
        at the border, and any border exit the invader owns is an escape.
        A teammate that is a ghost on our side counts as a second hunter, so
        two hunters close different doors instead of trailing each other.
        """
        pos = me["pos"]
        inv_dist = self._dist_from(anchor)
        mate = self._teammate_pos(game_state)
        mate_dist = None
        if mate is not None and self.map.on_home(mate):
            mate_state = game_state.get_agent_state(self._teammate_index())
            if int(mate_state.scared_timer) == 0:
                mate_dist = self._home_distances(mate)
        foods = set(_ipos(food) for food in self.get_food_you_are_defending(game_state).as_list())
        caps = set(_ipos(cap) for cap in self.get_capsules_you_are_defending(game_state))
        carrying = target["carrying"]
        scared = self.my_scared
        legal = game_state.get_legal_actions(self.index)
        best = None
        best_key = None
        for action in legal:
            nxt = self._nxt(pos, action)
            if not self.map.on_home(nxt):
                continue
            gap = inv_dist.get(nxt, 99)
            if scared > 0 and gap <= 1 and scared > 1:
                # Touching them while scared sends us home.
                continue
            mine = self._home_distances(nxt)
            region = 0
            food_in = 0
            cap_in = 0
            escape = 0
            for cell, d_inv in inv_dist.items():
                if d_inv > 40:
                    continue
                d_h = mine.get(cell, 999)
                if mate_dist is not None:
                    d_h = min(d_h, mate_dist.get(cell, 999))
                if scared > 0:
                    # We only bite once the timer runs out.
                    d_h = max(d_h, scared)
                if d_inv < d_h:
                    if self.map.on_home(cell):
                        region += 1
                        if cell in foods:
                            food_in += 1
                        if cell in caps:
                            cap_in += 1
                        if cell in self.map.border_set:
                            escape = 1
            key = (
                escape * (10 + 3 * carrying) + cap_in * 25 + food_in * 1.5 + region * 0.2,
                gap if scared == 0 else abs(gap - 2),
                1 if action == Directions.STOP else 0,
            )
            if best_key is None or key < best_key:
                best_key = key
                best = action
        if best is None:
            return self._flee(game_state, me, self._reports(game_state, me)) if scared else self._step_home(game_state, pos, anchor)
        return best

    def _teammate_index(self):
        for index in self.team:
            if index != self.index:
                return index
        return self.index

    def _dist_from(self, origin):
        dist = {origin: 0}
        queue = deque([origin])
        while queue:
            cur = queue.popleft()
            for nxt in self.map.neighbors.get(cur, []):
                if nxt in dist:
                    continue
                dist[nxt] = dist[cur] + 1
                queue.append(nxt)
        return dist

    def _cut_off(self, game_state, my_pos, anchor, report):
        """Chase the bite while they are still eating. Hold the exit only once they turn for home."""
        goal = self._invader_goal(game_state, report, anchor)
        # A pacman that is still biting is not heading home. Chase it.
        eating = self.last_bite is not None and self._completed(game_state) - self.last_bite[1] <= 8
        if goal in self.map.border and not eating:
            mine = self._home_distances(my_pos)
            their_exit = self.map.dist_exit.get(anchor, 99)
            my_exit = mine.get(goal, self._md(my_pos, goal))
            if my_exit <= their_exit + 1:
                return goal
        return self._intercept(my_pos, anchor, goal)

    def _invader_goal(self, game_state, report, anchor):
        foods = [_ipos(food) for food in self.get_food_you_are_defending(game_state).as_list()]
        capsules = [_ipos(cap) for cap in self.get_capsules_you_are_defending(game_state)]
        exit_dist = self.map.dist_exit.get(anchor, 99)
        food_dist = min((self._md(anchor, food) for food in foods), default=99)
        cap_dist = min((self._md(anchor, cap) for cap in capsules), default=99)
        if report["carrying"] >= 4 or (report["carrying"] >= 1 and exit_dist <= food_dist):
            return min(self.map.border, key=lambda border: self._md(anchor, border))
        if capsules and cap_dist <= food_dist + 1:
            return min(capsules, key=lambda cap: self._md(anchor, cap))
        if foods:
            return min(foods, key=lambda food: self._md(anchor, food))
        return anchor

    def _intercept(self, my_pos, inv_pos, goal):
        path = self._path(inv_pos, goal, home_only=True)
        if not path:
            return inv_pos
        # Maze distance can cut through their side and look faster than we are.
        mine = self._home_distances(my_pos)
        best = path[0]
        best_key = None
        for step, square in enumerate(path):
            my_dist = mine.get(square)
            if my_dist is None:
                continue
            late = my_dist - step
            # Meet them on the earliest square we can reach in time.
            # If we're always late, lose the least time.
            if late <= 0:
                key = (0, step, my_dist)
            else:
                key = (1, late, my_dist)
            if best_key is None or key < best_key:
                best_key = key
                best = square
        return best

    def _home_distances(self, origin):
        dist = {origin: 0}
        if origin is None or not self.map.on_home(origin):
            return dist
        queue = deque([origin])
        while queue:
            pos = queue.popleft()
            for nxt in self.map.neighbors[pos]:
                if nxt in dist or not self.map.on_home(nxt):
                    continue
                dist[nxt] = dist[pos] + 1
                queue.append(nxt)
        return dist

    def _patrol(self, game_state, me, reports):
        if not self.map.on_home(me["pos"]):
            return self._attack(game_state, me, reports, force_home=True)
        foods = [_ipos(food) for food in self.get_food_you_are_defending(game_state).as_list()]
        threats = []
        for report in reports:
            anchor = self._offside(report)
            if anchor is None or not foods:
                continue
            food = min(foods, key=lambda cell: self._md(anchor, cell))
            cross = self._crossing(anchor, food)
            threats.append((cross, self._md(anchor, cross)))
        # The teammate who moved earlier already claimed a door. Cover the other one.
        claimed = self._claimed_cover(game_state)
        if claimed is not None and len(threats) > 1:
            others = [item for item in threats if self._md(item[0], claimed) > 3]
            if others:
                threats = others
        if threats:
            spot = self._cover(me["pos"], threats)
        elif self.map.border:
            spot = min(
                self.map.border,
                key=lambda border: sum(self._md(border, other) for other in self.map.border),
            )
        else:
            spot = me["pos"]
        _SHARE["cover"][self.index] = (spot, self._completed(game_state))
        return self._step_home(game_state, me["pos"], spot)

    def _claimed_cover(self, game_state):
        now = self._completed(game_state)
        for index, pack in _SHARE["cover"].items():
            if index == self.index or not pack:
                continue
            spot, when = pack
            if spot is not None and 0 <= now - when <= 3:
                return spot
        return None

    def _offside(self, report):
        for cand in (report["visible"], report["pos"], report["map_pos"], report["spawn"]):
            if cand is not None and not self.map.on_home(cand):
                return cand
        return None

    def _crossing(self, origin, goal):
        """First square on our side of the shortest path from origin to goal."""
        path = self._path(origin, goal, home_only=False)
        if path:
            for square in path:
                if self.map.on_home(square):
                    return square
        if self.map.border:
            return min(self.map.border, key=lambda border: self._md(border, goal))
        return goal

    def _cover(self, origin, threats):
        """Wait where the slowest answer to any likely entry is as fast as possible.

        Squares on the way to a single entry all tie, and the last key stands
        on that entry so a ghost who does not dodge walks into us. Two entries
        pull the wait back to a square that still reaches both.
        """
        unique = {}
        for cross, eta in threats:
            if cross is None or not self.map.on_home(cross):
                continue
            if cross not in unique or eta < unique[cross]:
                unique[cross] = eta
        if not unique:
            return origin
        from_cross = {cross: self._home_distances(cross) for cross in unique}
        mine = self._home_distances(origin)
        soonest = min(unique, key=lambda cross: unique[cross])
        best = origin
        best_key = None
        for spot in mine:
            worst = None
            total = 0
            feasible = True
            for cross, eta in unique.items():
                gap = from_cross[cross].get(spot)
                if gap is None:
                    feasible = False
                    break
                late = mine[spot] + gap - eta
                total += late
                if worst is None or late > worst:
                    worst = late
            if not feasible or worst is None:
                continue
            key = (worst, total, from_cross[soonest].get(spot, 99))
            if best_key is None or key < best_key:
                best_key = key
                best = spot
        return best

    def _flee(self, game_state, me, reports):
        threats = []
        for report in reports:
            if not report["is_pacman"]:
                continue
            anchor = report["pos"] or report["map_pos"]
            if anchor is not None:
                threats.append(anchor)
        legal = game_state.get_legal_actions(self.index)
        best_action = legal[0]
        best_key = None
        for action in legal:
            nxt = self._nxt(me["pos"], action)
            if not self.map.on_home(nxt) and action != Directions.STOP:
                # Leaving while scared is right only when every enemy is already over here,
                # which means their side has no ghost. _mode sends us to attack in that case.
                continue
            if threats:
                gap = min(self._md(nxt, threat) for threat in threats)
            else:
                gap = 0
            key = (-gap, 1 if action == Directions.STOP else 0)
            if best_key is None or key < best_key:
                best_key = key
                best_action = action
        return best_action

    def _step_home(self, game_state, src, dst):
        if src == dst:
            legal = game_state.get_legal_actions(self.index)
            return Directions.STOP if Directions.STOP in legal else legal[0]
        path = self._path(src, dst, home_only=True)
        if path and len(path) >= 2:
            nxt = path[1]
            if not self._blocked(nxt):
                return self._dir(src, nxt)
        # Greedy step that stays on our side if the pocket is walled off.
        legal = game_state.get_legal_actions(self.index)
        best_action = legal[0]
        best_dist = 10 ** 9
        for action in legal:
            nxt = self._nxt(src, action)
            if not self.map.on_home(nxt):
                continue
            dist = self._md(nxt, dst)
            if dist < best_dist:
                best_dist = dist
                best_action = action
        return best_action

    # ----------------------------------------------------------------- utils

    def _path(self, start, goal, home_only):
        if start is None or goal is None:
            return None
        if start == goal:
            return [start]

        def allowed(pos):
            return self.map.on_home(pos) if home_only else True

        if not allowed(start) or not allowed(goal):
            return None
        queue = deque([start])
        parent = {start: None}
        while queue:
            pos = queue.popleft()
            for nxt in self.map.neighbors[pos]:
                if nxt in parent or not allowed(nxt):
                    continue
                parent[nxt] = pos
                if nxt == goal:
                    path = [nxt]
                    while path[-1] != start:
                        path.append(parent[path[-1]])
                    path.reverse()
                    return path
                queue.append(nxt)
        return None

    def _first(self, parent, start, goal):
        if goal == start or goal not in parent:
            return start
        cur = goal
        while parent[cur] is not None and parent[cur] != start:
            cur = parent[cur]
        return cur

    def _dir(self, src, dst):
        vector = (dst[0] - src[0], dst[1] - src[1])
        return {
            (0, 1): Directions.NORTH,
            (0, -1): Directions.SOUTH,
            (1, 0): Directions.EAST,
            (-1, 0): Directions.WEST,
            (0, 0): Directions.STOP,
        }.get(vector, Directions.STOP)

    def _nxt(self, pos, action):
        dx, dy = Actions.direction_to_vector(action)
        return int(round(pos[0] + dx)), int(round(pos[1] + dy))

    def _md(self, a, b):
        if a == b:
            return 0
        try:
            return int(self.get_maze_distance(a, b))
        except Exception:
            return _manhattan(a, b)

    def _blocked(self, nxt):
        """Avoid the square we just left when we have been bouncing."""
        if len(self.hist) < 4:
            return False
        if self.hist[-1] == self.hist[-3] and self.hist[-2] == self.hist[-4]:
            return nxt == self.hist[-2]
        return False

    def _fallback(self, game_state):
        legal = game_state.get_legal_actions(self.index)
        if not legal:
            return Directions.STOP
        pos = _ipos(game_state.get_agent_state(self.index).get_position())
        if pos is None or self.map is None:
            return legal[0]
        best = legal[0]
        best_dist = 10 ** 9
        for action in legal:
            if action == Directions.STOP:
                continue
            nxt = self._nxt(pos, action)
            dist = self.map.dist_home.get(nxt, 999)
            if dist < best_dist:
                best_dist = dist
                best = action
        return best
