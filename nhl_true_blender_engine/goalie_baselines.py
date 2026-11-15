"""Evidence-based goalie goal-mouth baselines; no fabricated anatomy.

Requires observed *saves as well as goals* with goalie identity. A goals-only
feed is insufficient to measure a vulnerability. Zone evidence is compared to
a pooled same-zone goalie baseline with Wilson uncertainty intervals.
"""
from math import sqrt
from .goalie_zones import validate_goal_zone_evidence

def wilson(goals, shots, z=1.96):
    if not shots or goals < 0 or goals > shots:
        raise ValueError("Invalid goal/shot denominator")
    p = goals / shots
    den = 1 + z*z/shots
    mid = (p + z*z/(2*shots))/den
    spread = z*sqrt((p*(1-p)+z*z/(4*shots))/shots)/den
    return max(0, mid-spread), min(1, mid+spread)

def compare_goalie_to_baseline(goalie, baseline, min_shots=30):
    """Only classify relative weaknesses when goalie lower bound exceeds
    baseline upper bound; avoid unproven hard-coded 'weakness' thresholds.
    Sample minimum is a conservative evidence floor, not a scoring weight.
    """
    g = validate_goal_zone_evidence(goalie)
    b = validate_goal_zone_evidence(baseline)
    if goalie["zonePerspective"] != baseline["zonePerspective"]:
        raise ValueError("Perspective mismatch")
    out = {}
    for zone, row in g["zoneCounts"].items():
        ref = b["zoneCounts"][zone]
        if row["shots"] < min_shots or ref["shots"] < min_shots:
            out[zone] = {"status":"INSUFFICIENT_SAMPLE",
                         "goalieShots":row["shots"],"baselineShots":ref["shots"]}
            continue
        low, high = wilson(row["goals"],row["shots"])
        ref_low, ref_high = wilson(ref["goals"],ref["shots"])
        status = ("EVIDENCED_RELATIVE_WEAKNESS" if low > ref_high else
                  "EVIDENCED_RELATIVE_STRENGTH" if high < ref_low else
                  "NOT_SEPARATED")
        out[zone] = {"status":status,
                     "goalieGoalRate":row["goals"]/row["shots"],
                     "baselineGoalRate":ref["goals"]/ref["shots"],
                     "goalieInterval":[low,high],"baselineInterval":[ref_low,ref_high],
                     "goalieShots":row["shots"],"baselineShots":ref["shots"]}
    return {"zones":out,"weakZones":[z for z,v in out.items()
            if v["status"]=="EVIDENCED_RELATIVE_WEAKNESS"],
            "strengthZones":[z for z,v in out.items()
            if v["status"]=="EVIDENCED_RELATIVE_STRENGTH"],
            "goalieSample":g["sample"],"baselineSample":b["sample"],
            "anatomicalHandMappingRequired":True,
            "note":"Shooter-perspective goal-mouth weakness, not automatically glove/blocker/five-hole."}
