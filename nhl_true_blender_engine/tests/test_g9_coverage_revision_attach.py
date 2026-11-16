"""The new official G9 method must actually reach the live attached snapshot."""
from nhl_true_blender_engine.enrichment import attach,ingest
from nhl_true_blender_engine.storage import open_db

DATE="2026-11-16"
URL="https://api-web.nhle.com/v1/gamecenter/2026020331/play-by-play"

def test_new_official_attempt_rate_receipt_replaces_legacy_share_coverage(tmp_path):
    con=open_db(str(tmp_path/"coverage.sqlite"))
    ingest(con,{
        "evidence_id":"legacy-g9","slate_date":DATE,"stage":"PROJECTED",
        "game_id":"2026020331","kind":"TEAM_COVERAGE","source_url":URL,
        "observed_at":"2026-11-16T10:00:00+00:00",
        "payload":{
            "attackingTeam":"MTL","defendingTeam":"NYR",
            "comparison":"RECENT_OPPONENT_SHOT_ORIGIN_SHARES_AGAINST_PEER_MEDIAN",
            "greenWeakZones":["High Slot"],"redStrongZones":["L Point"]}})
    ingest(con,{
        "evidence_id":"new-g9-attempt-rate","slate_date":DATE,"stage":"PROJECTED",
        "game_id":"2026020331","kind":"TEAM_COVERAGE","source_url":URL,
        "observed_at":"2026-11-16T11:00:00+00:00",
        "payload":{
            "attackingTeam":"MTL","defendingTeam":"NYR",
            "sourceType":"OFFICIAL_HISTORICAL_NHL_PLAY_BY_PLAY",
            "comparison":"RECENT_OPPONENT_SHOT_ATTEMPT_ORIGIN_RATE_PER_GAME_VS_OTHER_TEAM_MEDIAN",
            "greenWeakZones":["L Point"],"redStrongZones":[],
            "lowShotVolumeIsNotEvidenceOfDefensiveStrength":True}})
    snapshot={"games":[{
        "id":"2026020331","away":"MTL","home":"NYR","coverage":{},"rosters":{},
        "goalies":{"MTL":[],"NYR":[]}}]}
    attach(con,snapshot,DATE,"PROJECTED")
    current=snapshot["games"][0]["coverage"]["MTL"]
    assert current["data"]["comparison"]=="RECENT_OPPONENT_SHOT_ATTEMPT_ORIGIN_RATE_PER_GAME_VS_OTHER_TEAM_MEDIAN"
    assert current["data"]["greenWeakZones"]==["L Point"]
    assert current["data"]["redStrongZones"]==[]
    assert current["data"]["previousCoverageRevision"]["data"]["redStrongZones"]==["L Point"]
    assert "new-g9-attempt-rate" in snapshot["attachedEvidenceIds"]
    con.close()
