#!/usr/bin/env python3
"""Replay one seeded bench game and log the events that decided it.

Takes the same seed string that `bench.py --game-seed` stores in its JSON
(`seed` field), so a lost game can be replayed exactly and inspected:

    python testing/why.py -r my_team.py -b astar \
        -l defaultCapture --seed "s1:astar:defaultCapture:3:red"
    python testing/why.py --from-json runs/x.json --index 17   # replay game 17 of a bench run

Output: who won, the score every 100 moves, and every death, bank, capsule
and scared-ghost kill with the move number, square and load carried.
"""
import argparse
import contextlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTEST_SRC = os.path.join(ROOT, "pacman-contest", "src")
CONTEST = os.path.join(CONTEST_SRC, "contest")


def replay(red, blue, layout, seed, length=1200, map_file=False):
    sys.path[:0] = [CONTEST_SRC, os.path.dirname(os.path.abspath(__file__))]
    if map_file:
        # Runs made after bench.py loaded RANDOM maps from files: do the same.
        import tempfile
        from bench import layout_file
        layout = layout_file(layout, tempfile.mkdtemp(prefix="why_"))
    os.chdir(CONTEST)
    import contest.capture as capture
    import contest.text_display as text_display

    argv = ["-r", red, "-b", blue, "-l", layout, "-Q", "-c", "--delay-step", "0", "-i", str(length)]
    if seed:
        argv += ["--setRandomSeed", seed]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        options = capture.read_command(argv)
        game = capture.run_games(**options)[0]
        state = capture.CaptureRules().new_game(options["layouts"][0], game.agents,
                                                text_display.NullGraphics(), length, False, False).state
    side = {0: "red", 2: "red", 1: "blue", 3: "blue"}
    starts = [tuple(map(int, state.get_agent_position(i))) for i in range(4)]
    events, timeline = [], []
    for move, (agent, action) in enumerate(game.move_history):
        before = [(state.get_agent_state(i).is_pacman, state.get_agent_state(i).num_carrying,
                   tuple(map(int, state.get_agent_position(i))), state.get_agent_state(i).num_returned)
                  for i in range(4)]
        caps = (set(state.get_red_capsules()), set(state.get_blue_capsules()))
        state = state.generate_successor(agent, action)
        for i in range(4):
            was_pac, carry, pos, returned = before[i]
            st = state.get_agent_state(i)
            now = tuple(map(int, state.get_agent_position(i)))
            if now == starts[i] and abs(now[0] - pos[0]) + abs(now[1] - pos[1]) > 1:
                near = [j for j in range(4) if side[j] != side[i] and
                        abs(state.get_agent_position(j)[0] - pos[0]) + abs(state.get_agent_position(j)[1] - pos[1]) <= 1]
                kind = "death" if was_pac else "scared ghost eaten"
                events.append((move, f"{side[i]} agent {i} {kind} at {pos}, carrying {carry}, by agent(s) {near}"))
            if st.num_returned > returned:
                events.append((move, f"{side[i]} agent {i} banked {st.num_returned - returned} at {now}"))
        for k, team in ((0, "red"), (1, "blue")):
            for c in caps[k] - set(state.get_red_capsules() if k == 0 else state.get_blue_capsules()):
                eater = "blue" if team == "red" else "red"
                events.append((move, f"{eater} ate {team}'s capsule at {c} (agent {agent})"))
        if (move + 1) % 100 == 0:
            timeline.append((move + 1, state.data.score))
    return {"score": game.state.data.score, "moves": len(game.move_history),
            "agents": [type(a).__name__ for a in game.agents], "timeline": timeline, "events": events}


def team(name):
    """A file path, or a bench name / git:<ref> fetched the way bench.py does."""
    if os.path.exists(name):
        return os.path.abspath(name)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import tempfile
    from bench import resolve
    return resolve(name, tempfile.mkdtemp(prefix="why_"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-r", "--red")
    ap.add_argument("-b", "--blue")
    ap.add_argument("-l", "--layout", default="defaultCapture")
    ap.add_argument("--seed")
    ap.add_argument("--agent", help="our agent file, with --from-json")
    ap.add_argument("--from-json", help="a bench.py --json file")
    ap.add_argument("--index", type=int, help="game index in that file")
    args = ap.parse_args()
    if args.from_json:
        g = json.load(open(args.from_json))[args.index]
        ours = os.path.abspath(args.agent or os.path.join(ROOT, "my_team.py"))
        opp = team(g["opponent"])
        red, blue = (ours, opp) if g["side"] == "red" else (opp, ours)
        layout, seed, map_file = g["layout"], g["seed"], g.get("map_file", False)
        print(f"bench recorded: result {g.get('result')} margin {g.get('margin')} for us as {g['side']}")
    else:
        red, blue, layout, seed = team(args.red), team(args.blue), args.layout, args.seed
        map_file = layout.startswith("RANDOM")
    r = replay(red, blue, layout, seed, map_file=map_file)
    print(f"{layout} seed={seed}  final score {r['score']:+d} (positive = red ahead) after {r['moves']} moves")
    print("agents:", ", ".join(f"{i}:{n}" for i, n in enumerate(r["agents"])))
    print("score every 100 moves:", " ".join(f"{m}:{s:+d}" for m, s in r["timeline"]))
    for move, text in r["events"]:
        print(f"  move {move:4d}  {text}")


if __name__ == "__main__":
    main()
