"""Same-day projected lineup changes may not alter a goalie peer baseline.

Entirely SYNTHETIC shot records. No NHL player or game is asserted as real.
"""
from nhl_true_blender_engine.goalie_history_fallback import (
    summarize_goalie_origin_pbp, derive_independent_pbp_goalie_profile,
    combine_official_pregame_goalie_peers,
)

URL="https://api-web.nhle.com/v1/gamecenter/2026020001/play-by-play"

def shots(goalie,game,goals,date="2026-11-14"):
    return [{
       "goalieId":str(goalie),"gameId":str(game),"eventId":str(i),
       "type":"goal" if i<=goals else "shot-on-goal",
       "x":82,"y":4,"date":date,"sourceUrl":URL
    } for i in range(1,26)]

def test_fixed_league_pbp_pool_stops_g0_goalie_rank_flipping_with_projected_starters():
    independent_league_peers=[]
    for i,goals in enumerate((1,2,3,4)):
        independent_league_peers.extend(shots(800+i,200+i,goals))
    league_only,league_games=combine_official_pregame_goalie_peers(
        [],independent_league_peers,"2026-11-16")
    assert league_games==4
    peer_stats=summarize_goalie_origin_pbp(league_only)
    own=shots(44,144,8)
    original=summarize_goalie_origin_pbp(own)
    a=derive_independent_pbp_goalie_profile("44",original,peer_counts=peer_stats)
    # An unconfirmed backup appears in a projected lineup and brings 25
    # new shots; that backup has NO authority to change the fixed league
    # reference population for the original starter.
    added=summarize_goalie_origin_pbp(own+shots(55,155,20))
    b=derive_independent_pbp_goalie_profile("44",added,peer_counts=peer_stats)
    assert a["weakZones"]==b["weakZones"]
    assert a["fullySourceComparedAreas"]==b["fullySourceComparedAreas"]==1
    assert a["weakZones"]["Low Slot"]["peerGoaliesSampled"]==4
    assert a["weakZones"]["Low Slot"]["samplePeerSavePctgPercentile"]==0
    assert "55" not in a["weakZones"]["Low Slot"]["peerGoalieIds"]
    # Original dynamic sampled peer pool WOULD shift on the extra goalie.
    dynamic_a=derive_independent_pbp_goalie_profile("44",original)
    dynamic_b=derive_independent_pbp_goalie_profile("44",added)
    assert dynamic_a["fullySourceComparedAreas"]==0
    assert dynamic_b["fullySourceComparedAreas"]==0

def test_reference_rejects_today_and_future_goalie_pbp_before_comparing():
    dated=shots(44,144,8)
    today=shots(55,155,10,date="2026-11-16")
    future=shots(66,166,11,date="2026-11-17")
    reference,_=combine_official_pregame_goalie_peers(
        [],dated+today+future,"2026-11-16")
    assert {x["goalieId"] for x in reference}=={"44"}
