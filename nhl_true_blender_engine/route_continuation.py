"""Source-measured dated recurrence and independent shot continuation.

Two observed appearances are the minimal meaning of *recurrence*. No goal
probability, odds, point score, name priority, or preselected final Core.
The helper extracts observations; G7/Step4 and G11/Step9 still independently
apply their own original source rules and retain separate gate receipts.
"""
from __future__ import annotations


def observed_own_shot_appearances(pressure):
    """Review one NHL on-net shot count per observed player appearance.

    All source rows must be nonnegative integer counts. When official
    appearance dates accompany the list, keep the direct date alignment
    instead of inferring missing appearances or inventing played games.
    """
    pressure = pressure if isinstance(pressure, dict) else {}
    values = pressure.get('recentAppearanceShots')
    valid = (isinstance(values, list) and bool(values) and
             all(type(value) is int and value >= 0 for value in values))
    if not valid:
        return {'valid': False, 'appearanceCount': 0,
                'positiveShotAppearances': 0,
                'positiveDatedShotAppearances': 0,
                'datedAppearanceAlignmentVerified': False,
                'repeatedOwnShotPressure': False}

    dated = pressure.get('appearances')
    aligned = bool(
        isinstance(dated, list) and len(dated) == len(values)
        and all(isinstance(item, dict) and
                isinstance(item.get('date'), str) and item['date']
                for item in dated)
        and len({item['date'] for item in dated}) == len(dated))
    positive = sum(value > 0 for value in values)
    positive_dates = (sum(value > 0 for value in values)
                      if aligned else 0)
    return {
        'valid': True,
        'appearanceCount': len(values),
        'positiveShotAppearances': positive,
        'positiveDatedShotAppearances': positive_dates,
        'datedAppearanceAlignmentVerified': aligned,
        'repeatedOwnShotPressure': positive >= 2,
    }


def observed_dated_recurrence(reconciled, shot_review):
    """G7/Step4 source observation: documented repeat goal OR shot dates.

    Goal dates are deduplicated by the reconciler; own shots must be mapped
    to separate official appearance dates. A player with one isolated shot
    and zero recent goal dates has not yet demonstrated recurrence.
    """
    r = reconciled if isinstance(reconciled, dict) else {}
    goal_dates = r.get('distinctGoalDates')
    score_repeats = type(goal_dates) is int and goal_dates >= 2
    shot_repeats = (shot_review.get('datedAppearanceAlignmentVerified') is True
                    and shot_review.get('positiveDatedShotAppearances', 0) >= 2)
    return {
        'datedGoalRecurrence': score_repeats,
        'datedOwnShotRecurrence': shot_repeats,
        'datedScoringOrShotRecurrence': bool(r and (score_repeats or shot_repeats)),
        'distinctGoalDates': goal_dates,
        'positiveDatedShotAppearances': shot_review.get('positiveDatedShotAppearances', 0),
        'observedOnlyActualAppearances': True,
        'noOneOffShotCalledRecurrence': True,
        'noNewWeightOrRanking': True,
    }
