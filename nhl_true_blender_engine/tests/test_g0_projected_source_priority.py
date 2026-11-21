from nhl_true_blender_engine.engine import all_goalie_branches


DATE="2026-11-21"


def branch(goalie_id,url,source_type,*,status="EXPECTED",preferred=True):
    data={
        "goalieId":goalie_id,"team":"CAR","status":status,
        "projectedPreferred":preferred,
        "starterSourceStatus":source_type,
        "sample":{"shots":40,"games":3},
        "counterevidence":{"sourceReviewed":True},
        "weakZones":{"Low Slot":{"goalsAgainst":4}},
        "strengthZones":{},
    }
    if source_type=="NHL_OFFICIAL_PROJECTED_LINEUP":
        data["publishedAsOfSlateDate"]=DATE
    return {"sourceUrl":url,"observedAt":DATE+"T10:00:00+00:00","data":data}


def game_with(*branches):
    return {"date":DATE,"away":"EDM","home":"CAR",
            "goalies":{"CAR":list(branches),"EDM":[]}}


def test_dated_official_nhl_projection_resolves_lower_tier_algorithmic_conflict():
    official=branch("KOC","https://www.nhl.com/news/edm-car-projected-lineups-2026-11-21",
                    "NHL_OFFICIAL_PROJECTED_LINEUP")
    algorithmic=branch("BUS","https://daily.hockey/starting-goalies/2026-11-21",
                       "DATED_SECONDARY_ALGORITHMIC_PROJECTION")
    selected=all_goalie_branches(game_with(algorithmic,official),"PROJECTED")["CAR"]
    assert [x["data"]["goalieId"] for x in selected]==["KOC"]
    conflicts=selected[0]["data"]["projectedBranchConflicts"]
    assert any(x["goalieId"]=="BUS" and x["preservedAsCounterevidence"] for x in conflicts)
    assert selected[0]["data"]["projectionAuthorityDecision"] == (
        "DATED_OFFICIAL_NHL_PROJECTED_LINEUP_OUTRANKS_SECONDARY_PROJECTION")


def test_conflicting_official_projected_goalies_remain_separate():
    first=branch("KOC","https://www.nhl.com/news/edm-car-game-preview-2026-11-21",
                 "NHL_OFFICIAL_PROJECTED_LINEUP")
    second=branch("BUS","https://www.nhl.com/news/nhl-lineup-projections-2026-27-season",
                  "NHL_OFFICIAL_PROJECTED_LINEUP")
    secondary=branch("ALT","https://daily.hockey/starting-goalies/2026-11-21",
                     "DATED_SECONDARY_ALGORITHMIC_PROJECTION")
    selected=all_goalie_branches(game_with(first,second,secondary),"PROJECTED")["CAR"]
    assert {x["data"]["goalieId"] for x in selected}=={"KOC","BUS"}
    assert all(any(x["goalieId"]=="ALT" for x in b["data"]["projectedBranchConflicts"])
               for b in selected)


def test_secondary_projection_disagreement_is_not_arbitrarily_broken():
    a=branch("KOC","https://daily.hockey/starting-goalies/2026-11-21",
             "DATED_SECONDARY_ALGORITHMIC_PROJECTION")
    b=branch("BUS","https://www.fsroundup.com/nhl/starting-goalies",
             "SECONDARY_PROJECTED_STARTER")
    selected=all_goalie_branches(game_with(a,b),"PROJECTED")["CAR"]
    assert {x["data"]["goalieId"] for x in selected}=={"KOC","BUS"}


def test_explicit_confirmed_starter_supersedes_projected_conflicts_and_preserves_them():
    confirmed=branch("KOC","https://www.nhl.com/news/edm-car-game-preview-2026-11-21",
                     "NHL_OFFICIAL_CONFIRMED_STARTER",status="CONFIRMED",preferred=False)
    projected=branch("BUS","https://daily.hockey/starting-goalies/2026-11-21",
                     "DATED_SECONDARY_ALGORITHMIC_PROJECTION")
    selected=all_goalie_branches(game_with(projected,confirmed),"PROJECTED")["CAR"]
    assert [x["data"]["goalieId"] for x in selected]==["KOC"]
    assert any(x["goalieId"]=="BUS" for x in selected[0]["data"]["projectedBranchConflicts"])



def test_official_projected_source_survives_same_goalie_identity_merge():
    merged=branch("KOC","https://daily.hockey/starting-goalies/2026-11-21",
                  "DATED_SECONDARY_ALGORITHMIC_PROJECTION")
    merged["data"]["officialProjectedLineupSourceUrls"]=[
        "https://www.nhl.com/news/edm-car-projected-lineups-2026-11-21"]
    secondary=branch("BUS","https://www.fsroundup.com/nhl/starting-goalies",
                     "SECONDARY_PROJECTED_STARTER")
    selected=all_goalie_branches(game_with(secondary,merged),"PROJECTED")["CAR"]
    assert [x["data"]["goalieId"] for x in selected]==["KOC"]
    assert selected[0]["data"]["officialProjectedLineupSourceUrls"]
