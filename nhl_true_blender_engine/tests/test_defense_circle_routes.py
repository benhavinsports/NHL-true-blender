"""Independent opponent G9 coverage must measure the routes NHL EDGE names.

Coordinates are venue-frame PBP, not actual goal-mouth puck placement or
NHL tracking polygon membership. Test both attacker orientations.
"""
from nhl_true_blender_engine.official_defense_coverage import (
    detailed_shot_origin_zone, conservative_zone, summarize_concessions)

def test_circle_and_point_areas_available_as_derived_source_zones():
    assert detailed_shot_origin_zone(64,22)=="L Circle"
    assert detailed_shot_origin_zone(-64,-22)=="L Circle"
    assert detailed_shot_origin_zone(64,-22)=="R Circle"
    assert detailed_shot_origin_zone(-64,22)=="R Circle"
    assert detailed_shot_origin_zone(42,23)=="L Point"
    assert detailed_shot_origin_zone(42,-23)=="R Point"
    assert detailed_shot_origin_zone(-42,-23)=="L Point"
    assert detailed_shot_origin_zone(-42,23)=="R Point"
    assert detailed_shot_origin_zone(42,5)=="Center Point"
    assert conservative_zone(83,4)=="Low Slot"
    assert conservative_zone(60,4)=="High Slot"
    assert detailed_shot_origin_zone(None,22) is None
    assert detailed_shot_origin_zone(130,22) is None

def test_team_defense_conceded_official_events_have_circle_lanes_independent_of_goalie():
    games={"1234":{"homeTeamId":"101","awayTeamId":"102"}}
    events=[
        {"gameId":"1234","eventId":"11","type":"shot-on-goal",
         "ownerTeamId":"101","x":64,"y":22,"sourceUrl":"https://api-web.nhle.com/v1/gamecenter/1234/play-by-play"},
        {"gameId":"1234","eventId":"12","type":"goal",
         "ownerTeamId":"101","x":-64,"y":22,"sourceUrl":"https://api-web.nhle.com/v1/gamecenter/1234/play-by-play"},
        {"gameId":"1234","eventId":"13","type":"shot-on-goal",
         "ownerTeamId":"102","x":-64,"y":-22,"sourceUrl":"https://api-web.nhle.com/v1/gamecenter/1234/play-by-play"},
        {"gameId":"1234","eventId":"14","type":"shot-on-goal",
         "ownerTeamId":"102","x":42,"y":4,"sourceUrl":"https://api-web.nhle.com/v1/gamecenter/1234/play-by-play"},
    ]
    counts=summarize_concessions(events,games)
    away=counts["102"];home=counts["101"]
    assert away["bins"]["L Circle"]==1
    assert away["bins"]["R Circle"]==1
    assert home["bins"]["L Circle"]==1
    assert home["bins"]["Center Point"]==1
    assert home["bins"]["Point"]==1
    assert away["totalShots"]==2
    assert home["totalShots"]==2
    assert len(home["gameIds"])==1


def test_g9_counts_all_attempts_and_never_calls_low_volume_a_strong_zone(tmp_path):
    from nhl_true_blender_engine.official_defense_coverage import (
        summarize_concessions, make_coverage)
    from nhl_true_blender_engine.storage import open_db

    meta={}
    events=[]
    seq=0
    def add_game(home_id,away_id,home_abbrev,away_abbrev,home_zone_counts):
        nonlocal seq
        seq+=1
        gid=str(seq)
        meta[gid]={"homeTeamId":str(home_id),"awayTeamId":str(away_id),
                   "homeAbbrev":home_abbrev,"awayAbbrev":away_abbrev}
        # The away club owns these attempts, so the home club is defending.
        for zone,count in home_zone_counts.items():
            if zone=="L Point": x,y=42,23
            elif zone=="R Point": x,y=42,-23
            else: x,y=83,4
            for n in range(count):
                typ=("shot-on-goal","missed-shot","blocked-shot","goal")[n%4]
                events.append({"gameId":gid,"eventId":f"{gid}-{zone}-{n}",
                    "type":typ,"ownerTeamId":str(away_id),"x":x,"y":y,
                    "sourceUrl":f"https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play"})

    # Target NYR: 10 L-Point attempts and 10 Low-Slot attempts per game.
    # Its lower-volume R-Point exposure is NOT proof of a strong defensive area.
    for i in range(8):
        add_game(100,3000+i,"NYR",f"X{i}",{"L Point":10,"Low Slot":10})
    # Seven independent peer clubs, each with eight games and 20 attempts/game.
    # Peer medians: L Point 2/game, R Point 10/game, Low Slot 8/game.
    for team_index in range(7):
        team_id=200+team_index
        for game_index in range(8):
            add_game(team_id,4000+team_index*100+game_index,
                     f"P{team_index}",f"Q{team_index}-{game_index}",
                     {"L Point":2,"R Point":10,"Low Slot":8})

    counts=summarize_concessions(events,meta)
    target=counts["100"]
    assert target["totalAttempts"]==160
    assert target["totalShots"]==80
    assert target["bins"]["L Point"]==80
    assert target["onNetBins"]["L Point"]==40
    assert target["goalBins"]["L Point"]==20

    con=open_db(str(tmp_path/"g9.sqlite"))
    snapshot={"games":[{"id":"TODAY","away":"MTL","home":"NYR"}]}
    result=make_coverage(con,snapshot,"2026-11-16","PROJECTED",
                         events,meta,shift_receipts={})
    row=con.execute("""SELECT payload FROM evidence WHERE kind='TEAM_COVERAGE'
        AND game_id='TODAY' AND payload LIKE '%MTL%'""").fetchone()
    assert row is not None
    import json
    coverage=json.loads(row["payload"])
    assert "L Point" in coverage["greenWeakZones"]
    assert coverage["zoneConcessions"]["L Point"]["attemptsAgainst"]==80
    assert coverage["zoneConcessions"]["L Point"]["attemptsPerGame"]==10
    assert coverage["zoneConcessions"]["L Point"]["peerMedianAttemptsPerGame"]==2
    assert coverage["redStrongZones"]==[]
    assert coverage["lowShotVolumeIsNotEvidenceOfDefensiveStrength"] is True
    con.close()
