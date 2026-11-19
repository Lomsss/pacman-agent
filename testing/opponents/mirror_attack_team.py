"""Our own agent with both players on offense (a coordinated double attack)."""
import importlib.util
import os

_path = os.environ.get("MIRROR_AGENT") or os.path.join(os.path.dirname(__file__), "..", "..", "my_team.py")
_spec = importlib.util.spec_from_file_location("mirror_attack_base", os.path.abspath(_path))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def create_team(first_index, second_index, is_red, **kw):
    return [_mod.ContestAgent(first_index, role="offense"), _mod.ContestAgent(second_index, role="offense")]
