"""Source-separated G0/G9 own-lane ties must not be lost at G18.

These are synthetic route receipts, never published player selections.
"""
from nhl_true_blender_engine.engine import adjudicate_scoring_path
from nhl_true_blender_engine.tests.test_engine import evidence


SOURCE="https://api-web.nhle.com/v1/edge/skater-shot-location-detail/1000/now"


def scene(resolved):
    release={
        "archetype": "OBSERVED_OWN_SHOT_ORIGIN",
        "zone": "slot", "attempts": 7, "ownedGoals": 2,
        "originalPrimaryOrigin": "slot",
        "primaryWasTiedBeforeG0": True,
        "g0MatchedOwnOriginRoute": resolved,
        "g9DefensiveLaneIndependentlyMatched": resolved,
    }
    player={
        "id": "1000",
        "release": evidence(release, SOURCE),
        "finishOwnership": evidence(
            {"recipient": True, "creditedGoalsVerified": True}, SOURCE),
        "deployment": evidence({"EV": "F1", "status": "PROJECTED"}, SOURCE),
    }
    goalie=evidence({"weakZones": {"slot": {"goalsAgainst": 2}}},
        "https://api-web.nhle.com/v1/edge/goalie-shot-location-detail/2000/now")
    coverage=evidence({"greenWeakZones": ["slot"]},
        "https://api-web.nhle.com/v1/gamecenter/2026020001/play-by-play")
    gates={key: {"disposition": "PASS"} for key in
        ("G0", "G3", "G4", "G5", "G6", "G7", "G9", "G10",
         "G10.5", "G12", "G15", "G16", "G17")}
    return player,release,goalie,coverage,gates


def test_independent_g0_g9_lane_separation_permits_direct_primary():
    player,release,goalie,coverage,gates=scene(True)
    path,proof=adjudicate_scoring_path(
        player,[],release,goalie,coverage,gates,[],False)
    assert path=="PRIMARY", proof
    assert proof["primaryOriginIsSourceDistinct"] is True
    assert proof["positiveDirectGateEvidence"]["G0ThruG17SourcePass"] is True


def test_unseparated_original_lane_tie_never_gets_forced_primary():
    player,release,goalie,coverage,gates=scene(False)
    path,proof=adjudicate_scoring_path(
        player,[],release,goalie,coverage,gates,[],False)
    assert path is None, proof
    assert proof["primaryOriginIsSourceDistinct"] is False
