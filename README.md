# Pacman Agent

Our team for the UPF capture-the-flag Pacman contest. `my_team.py` is the
contest entry: a `Raider` that collects food and a `Sentinel` that guards our
side, both able to switch roles on any turn. How it works and how each part
was measured is in [`docs/AGENT.md`](docs/AGENT.md).

Only the contest agent lives on `main`. Every other team we built or used for
testing (sparring opponents, the v2 team, the earlier `ContestAgent` and
proxies of real contest teams) has its own branch, `agent/<name>`. The list
is in `docs/AGENT.md` and `testing/README.md`.

## Setting up the environment
1. Clone the repository (e.g., `git clone git@github.com:Lomsss/pacman-agent.git`)
2. Go into the pacman-agent folder, `cd pacman-agent/`
3. Run `git submodule update --init --remote` to pull the last pacman-contest
4. Create a virtual environment (e.g., `python3.8 -m venv venv`)
5. Activate the virtual environment with `source venv/bin/activate`
6. Go to the pacman-contest folder and install the requirements:
    - `cd pacman-contest/`
    - `pip install -r requirements.txt`
    - `pip install -e .`

## Playing a game
```bash
cd pacman-contest/src/contest/
python capture.py -r ../../../my_team.py -b baseline_team
```

## Testing
`testing/bench.py` plays the agent against the sparring opponents on many
maps and both colours; `testing/paired.py` compares two versions on the same
seeded games. Run `git fetch origin` first so the opponent branches are
available. See [`testing/README.md`](testing/README.md).
