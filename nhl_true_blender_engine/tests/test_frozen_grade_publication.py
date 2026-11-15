"""Grade and audit the ONE frozen Core card without re-picking or modifying its G18 identity."""
import json
import pytest
from scripts.run_cycle import _publish_official_grade
from scripts.publish_site_state import PublicationConflict

DATE="2026-11-15"
URL="https://api-web.nhle.com/v1/gamecenter/2026020327/boxscore"

def create_card(folder):
    path=folder/"site_cards"/f"{DATE}.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    legs=[
        {"gameId":"2026020326","playerId":"8480803","player":"Evan Bouchard",
         "path":"PRIMARY","matchup":"EDM@PHI"},
        {"gameId":"2026020327","playerId":"8480027","player":"Jason Robertson",
         "path":"PRIMARY","matchup":"FLA@DAL"},
        {"gameId":"2026020328","playerId":"8480028","player":"Morgan Frost",
         "path":"PRIMARY","matchup":"CGY@ANA"},
    ]
    saved={"cardId":"NHL-2026-11-15-CANONICAL","revision":1,
           "fingerprint":"do-not-alter-original-fingerprint",
           "stage":"MIXED","verified":True,"status":"G18_SOURCE_VERIFIED",
           "legsJson":json.dumps(legs),"gradeJson":"{}"}
    path.write_text(json.dumps(saved))
    return path,legs,saved

def official_grade(legs,goals=(0,1,0)):
    score=[{"gameId":x["gameId"],"playerId":x["playerId"],
            "player":x["player"],"goals":goals[i],
            "result":"HIT" if goals[i] else "MISS"}
            for i,x in enumerate(legs)]
    return {"card_id":"NHL-2026-11-15-CANONICAL","result":"LOSS",
            "legs":score,"official_sources":[URL],
            "graded_at":"2026-11-16T04:00:00-05:00"}

def test_grade_updates_only_frozen_card_status_and_postgame_evidence(tmp_path):
    path,legs,original=create_card(tmp_path)
    grade=official_grade(legs)
    misses=[{"player":legs[0]["player"],"conclusion":"MISS_WITHOUT_PROVEN_PREGAME_GATE_DEFECT"},
            {"player":legs[2]["player"],"conclusion":"MISS_WITHOUT_PROVEN_PREGAME_GATE_DEFECT"}]
    report=_publish_official_grade(tmp_path,DATE,grade,misses)
    current=json.loads(path.read_text())
    assert current["cardId"]==original["cardId"]
    assert current["fingerprint"]==original["fingerprint"]
    assert current["legsJson"]==original["legsJson"]
    assert current["revision"]==original["revision"]
    assert current["stage"]==original["stage"]
    assert current["status"]=="FROZEN_GRADED"
    assert report["result"]=="LOSS"
    assert report["hits"]==1
    assert report["legs"]==3
    assert len(report["playerResults"])==3
    assert report["missAudits"]==misses
    assert report["officialSources"]==[URL]
    assert report["patchesApplied"]==[]
    before=path.read_bytes()
    assert _publish_official_grade(tmp_path,DATE,grade,misses)==report
    assert path.read_bytes()==before

def test_grade_cannot_change_original_frozen_selection_or_conflict_with_first_grade(tmp_path):
    path,legs,_=create_card(tmp_path)
    grade=official_grade(legs)
    wrong=dict(grade,card_id="NHL-2026-11-15-DIFFERENT")
    with pytest.raises(PublicationConflict,match="original locked Core"):
        _publish_official_grade(tmp_path,DATE,wrong,[])
    changed=dict(grade,legs=[*grade["legs"][:-1],{
        **grade["legs"][-1],"playerId":"OTHER"}])
    with pytest.raises(PublicationConflict,match="frozen card"):
        _publish_official_grade(tmp_path,DATE,changed,[])
    assert json.loads(path.read_text())["status"]=="G18_SOURCE_VERIFIED"
    _publish_official_grade(tmp_path,DATE,grade,[])
    later=official_grade(legs,goals=(1,1,1))
    later["result"]="WIN"
    with pytest.raises(PublicationConflict,match="conflicts"):
        _publish_official_grade(tmp_path,DATE,later,[])
