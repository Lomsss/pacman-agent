"""The staff baseline with both agents on offense."""
from contest.baseline_team import OffensiveReflexAgent


def create_team(first_index, second_index, is_red, **kw):
    return [OffensiveReflexAgent(first_index), OffensiveReflexAgent(second_index)]
