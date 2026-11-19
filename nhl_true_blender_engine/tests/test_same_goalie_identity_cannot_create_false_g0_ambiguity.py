"""Guard against treating two independently sourced statuses of ONE goalie as two starters."""
from nhl_true_blender_engine.engine import all_goalie_branches, g0_full_slate

DATE="2026-11-19"
SRC1="https://www.betweenthelineshockey.com/tonight.md"
SRC2="https://daily.hockey/starting-goalies/2026-11-19"

def starter(pid, status, source, zone="Low Slot"):
    return {"sourceUrl":source,"observedAt":"2026-11-19T10:01:00Z",
        "data":{"goalieId":pid,"status":status,
                "sourceClass":"DERIVED_RINK_ORIGIN_NOT_ANATOMICAL",
                "weakZones":{zone:{"shotsAgainst":48,"goalsAgainst":7}},
                "strengthZones":{},"sample":{"allZoneObservations":48},
                "counterevidence":{"reviewed":True}}}

def test_same_official_goalie_is_one_projected_branch_with_both_sources():
    g={"id":"9001","date":DATE,"away":"AAA","home":"BBB",
       "goalies":{"AAA":[starter("200","EXPECTED",SRC2)],
                  "BBB":[starter("100","PROJECTED",SRC1),
                         starter("100","EXPECTED",SRC2)]}}
    selected=all_goalie_branches(g,"PROJECTED")
    assert len(selected["BBB"])==1
    assert selected["BBB"][0]["data"]["goalieId"]=="100"
    assert selected["BBB"][0]["data"]["status"]=="EXPECTED"
    assert selected["BBB"][0]["data"]["sameGoalieIdentitySourceUrls"]==sorted([SRC1,SRC2])
    scan,_=g0_full_slate([g],"PROJECTED")
    aaa=next(x for x in scan if x["attacker"]=="AAA")
    assert len(aaa["targetGoalies"])==1
    assert aaa["targetGoalies"][0]["sameGoalieIdentitySourceUrls"]==sorted([SRC1,SRC2])

def test_two_distinct_projected_starters_stay_two_independent_branches():
    g={"id":"9002","date":DATE,"away":"AAA","home":"BBB",
       "goalies":{"AAA":[starter("200","EXPECTED",SRC2)],
                  "BBB":[starter("100","EXPECTED",SRC1),
                         starter("101","EXPECTED",SRC2)]}}
    assert {b["data"]["goalieId"] for b in all_goalie_branches(g,"PROJECTED")["BBB"]}=={"100","101"}

def test_contradictory_complete_profiles_of_same_goalie_not_silently_merged():
    g={"id":"9003","date":DATE,"away":"AAA","home":"BBB",
       "goalies":{"AAA":[starter("200","EXPECTED",SRC2)],
                  "BBB":[starter("100","EXPECTED",SRC1,"Low Slot"),
                         starter("100","PROJECTED",SRC2,"R Circle")]}}
    assert len(all_goalie_branches(g,"PROJECTED")["BBB"])==2
