"""Confirmed-source fallback never invents confirmed goalie or skater role."""
from datetime import datetime,timedelta,timezone
from nhl_true_blender_engine.engine import all_goalie_branches,execute
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.enrichment import ingest,attach
from nhl_true_blender_engine.tests.test_engine import snapshot, DATE,SRC

def evidence_goalie(pid,status):
    return {"sourceUrl":SRC,"observedAt":"2026-11-15T12:00:00Z",
            "data":{"goalieId":pid,"team":"T1B","status":status,
                    "weakZones":{"slot":{"sample":90}},
                    "sample":"dated independent profile","counterevidence":"point defended"}}

def test_confirmed_stage_preserves_expected_label_when_no_confirmed_starter():
    s=snapshot(1)
    g=s["games"][0]
    g["goalies"][g["home"]]=[evidence_goalie("expected-1","EXPECTED")]
    branch=all_goalie_branches(g,"CONFIRMED")[g["home"]]
    assert len(branch)==1 and branch[0]["data"]["status"]=="EXPECTED"
    g["goalies"][g["home"]].append(evidence_goalie("confirmed-2","CONFIRMED"))
    branch=all_goalie_branches(g,"CONFIRMED")[g["home"]]
    assert len(branch)==1 and branch[0]["data"]["goalieId"]=="confirmed-2"

def test_a_projected_finalist_is_explicitly_mixed_not_falsely_confirmed(tmp_path):
    con=open_db(str(tmp_path/"mixed.sqlite"))
    s=snapshot()
    s["games"][0]["rosters"]["T1A"]["data"]["players"][0]["deployment"]["data"]["status"]="PROJECTED"
    result=execute(con,s,DATE,"CONFIRMED")
    assert result["card"],result["errors"]
    assert result["card"]["stage"]=="MIXED"
    row=con.execute("SELECT details,disposition FROM gates WHERE stage='CONFIRMED' AND player_id='1010' AND gate='G6'").fetchone()
    assert row["disposition"]=="PASS"
    assert '"status":"PROJECTED"' in row["details"]
    con.close()

def test_earlier_profile_survives_new_confirmed_starter_of_same_identity(tmp_path):
    con=open_db(str(tmp_path/"transition.sqlite"))
    g={"id":"5001","away":"NYR","home":"BOS","goalies":{},"rosters":{},"coverage":{}}
    snap={"games":[g]}
    base={"slate_date":DATE,"game_id":"5001","source_url":SRC}
    def put(id,kind,stage,at,payload):
        ingest(con,{**base,"evidence_id":id,"kind":kind,"stage":stage,
            "observed_at":at,"payload":payload})
    put("scouting","GOALIE_PROFILE","PROJECTED","2026-11-15T11:00:00Z",
        {"goalieId":"88","team":"BOS","status":"EXPECTED",
         "weakZones":{"slot":{"sample":100}},"sample":"100 on-net target observations",
         "counterevidence":"strong high slot"})
    put("expected","GOALIE_STARTER","PROJECTED","2026-11-15T12:00:00Z",
        {"goalieId":"88","team":"BOS","status":"EXPECTED"})
    put("confirmed","GOALIE_STARTER","CONFIRMED","2026-11-15T13:00:00Z",
        {"goalieId":"88","team":"BOS","status":"CONFIRMED"})
    attach(con,snap,DATE,"CONFIRMED")
    branches=all_goalie_branches(g,"CONFIRMED")["BOS"]
    assert len(branches)==1
    assert branches[0]["data"]["status"]=="CONFIRMED"
    assert branches[0]["data"]["weakZones"]=={"slot":{"sample":100}}
    assert branches[0]["data"]["goalieProfileSourceUrl"]==SRC
    con.close()
