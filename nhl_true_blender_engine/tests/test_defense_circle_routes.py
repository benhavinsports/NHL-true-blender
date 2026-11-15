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
