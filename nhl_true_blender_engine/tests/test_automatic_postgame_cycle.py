"""Full automatic grade -> miss audit -> patch adjudication -> season JSON.

Fixture grade is synthetic and already officially verified in SQLite. Never
contacts the NHL network, invents live final scores, or changes the frozen card.
"""
import asyncio
import json
from scripts.run_cycle import execute_cycle
from nhl_true_blender_engine.storage import open_db, encode
from nhl_true_blender_engine.postgame_recalibration import GUARD_POLICIES

DATE="2026-11-15"
OFFICIAL="https://api-web.nhle.com/v1/gamecenter/2026020327/boxscore"
PREGAME="https://api-web.nhle.com/v1/edge/skater-shot-location-detail/888/now"
TIME="2026-11-15T14:00:00-05:00"

def fixture(root):
    root.mkdir(parents=True,exist_ok=True)
    con=open_db(str(root/"true_blender.sqlite"))
    legs=[{"gameId":str(8880+i),"playerId":str(888+i),
           "player":f"Synthetic {i}","path":"PRIMARY",
           "startUTC":"2026-11-16T01:00:00Z"}
          for i in range(3)]
    cid=f"NHL-{DATE}-CANONICAL"
    encoded=encode(legs)
    con.execute("""INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (DATE,cid,encoded,encoded,"MIXED","frozen-synthetic-fingerprint",
                 1,TIME,TIME,encode({"result":"LOSS","hits":2,"legs":3})))
    scored=[{"gameId":x["gameId"],"playerId":x["playerId"],
             "player":x["player"],"result":"MISS" if i==0 else "HIT",
             "goals":0 if i==0 else 1} for i,x in enumerate(legs)]
    con.execute("""INSERT INTO grades VALUES(?,?,?,?,?,?,?)""",
                (cid,DATE,"LOSS",encode(scored),encode([OFFICIAL]),
                 encode([]),TIME))
    # One sourced pregame proof contradiction deliberately inserted in the
    # missed candidate's original G10.5 row.
    con.execute("""INSERT INTO gates VALUES(?,?,?,?,?,?,?,?)""",(
        DATE,"CONFIRMED",legs[0]["gameId"],legs[0]["playerId"],"G10.5",
        "PASS",encode({"evidence":{"allAlternativesScanned":True,
                       "comparisonRows":[{"challengerId":"999",
                                          "status":"RIVAL_DOMINATES"}]},
                       "sourceIds":[PREGAME]}),TIME))
    con.close()
    site=root/"site_cards"/(DATE+".json")
    site.parent.mkdir(parents=True,exist_ok=True)
    original={"slateDate":DATE,"cardId":cid,"fingerprint":"frozen-synthetic-fingerprint",
              "revision":1,"status":"G18_SOURCE_VERIFIED","stage":"MIXED",
              "verified":True,"legsJson":encoded,"gradeJson":"{}"}
    site.write_text(json.dumps(original))
    return site,original

def test_cycle_applies_sourced_future_guard_and_saves_cumulative_official_history(tmp_path,monkeypatch):
    # Synthetic official recipient comparison fixture, no live NHL request.
    async def synthetic_official_recipients(con,date,nhl):
        return {'status':'OFFICIALLY_VERIFIED_FULL_SCORER_COMPARISON',
                'cardId':f'NHL-{DATE}-CANONICAL','readOnlyPostgameAudit':True,
                'selectedLegs':[],'officialSourceUrls':[OFFICIAL],
                'syntheticTestFixtureOnly':True}
    monkeypatch.setattr('scripts.run_cycle.collect_official_recipients',
                        synthetic_official_recipients)
    root=tmp_path/"state"
    card_path,original=fixture(root)
    run=asyncio.run(execute_cycle("grade",DATE,root))
    assert run["status"]=="ALREADY_OFFICIALLY_GRADED"
    assert run["originalCardPreserved"] is True
    assert run["grade"]["result"]=="LOSS"
    assert run["grade"]["hits"]==2
    assert run["grade"]["legs"]==3
    assert len(run["missAudits"])==1
    assert run["patchAdjudication"]["activated"]==[
        GUARD_POLICIES["G10.5"]]
    assert run["grade"]["patchesApplied"]==[GUARD_POLICIES["G10.5"]]
    history=json.loads((root/"history"/"2026-27.json").read_text())
    assert history["officiallyGradedSlates"]==1
    assert history["wins"]==0 and history["losses"]==1
    assert history["legHits"]==2
    assert history["monthlyThreeSlateCalibration"]["2026-11"]["sampleCount"]==1
    assert history["verifiedAutomaticGuardPatches"]==[GUARD_POLICIES["G10.5"]]
    after=json.loads(card_path.read_text())
    assert after["status"]=="FROZEN_GRADED"
    for key in ("cardId","fingerprint","revision","legsJson","stage"):
        assert after[key]==original[key]
    site_grade=json.loads(after["gradeJson"])
    assert site_grade["officialSources"]==[OFFICIAL]
    before_bytes=card_path.read_bytes()
    again=asyncio.run(execute_cycle("grade",DATE,root))
    assert again["patchAdjudication"]["activated"]==[GUARD_POLICIES["G10.5"]]
    assert card_path.read_bytes()==before_bytes

def test_cycle_without_card_cannot_generate_fake_patch_or_history(tmp_path):
    root=tmp_path/"empty"
    result=asyncio.run(execute_cycle("grade",DATE,root))
    assert result["status"]=="NO_ORIGINAL_CORE_TO_GRADE"
    assert not (root/"history").exists()
    assert not (root/"site_cards").exists()
