"""Actual first nonpassing G0-G18 decision by skater, for source repair only.

This is NOT a scorer ranking, picks list, or replacement authority.
"""
from collections import Counter,defaultdict
from .engine import MASTER

def first_gate_audit(con,date,stage):
    rows=con.execute("""SELECT game_id,player_id,gate,disposition FROM gates
        WHERE slate_date=? AND stage=?""",(date,stage)).fetchall()
    by_player=defaultdict(dict)
    for r in rows:
        if r["player_id"].startswith("GOALIE_DIRECTION:"):
            continue
        by_player[(r["game_id"],r["player_id"])][r["gate"]]=r["disposition"]
    counts=Counter()
    traces=[]
    for (game_id,pid),gates in by_player.items():
        reason=next((g for g in MASTER if gates.get(g)!="PASS"),None)
        if reason is None:reason="FULL_G0_G18_PASS"
        counts[reason]+=1
        traces.append({"gameId":game_id,"playerId":pid,
                       "firstNonpassingGate":reason,
                       "reasonDisposition":gates.get(reason,"MISSING") if reason!="FULL_G0_G18_PASS" else "PASS"})
    return {"scannedSkaters":len(by_player),
            "firstNonpassingGateCounts":dict(sorted(counts.items())),
            "allGateRowsPresent":sum(len(v)==len(MASTER)+16 for v in by_player.values()),
            "samplesByFirstGate":{
                gate:[x for x in traces if x["firstNonpassingGate"]==gate][:3]
                for gate in counts},
            "notAScorerRanking":True}
