"""Dated player-owned lane observations shared by independent gate operations."""

def receipt(value):
    return (isinstance(value,dict) and isinstance(value.get('sourceUrl'),str)
            and value['sourceUrl'].startswith('https://') and
            bool(value.get('observedAt')) and bool(value.get('data')))

def evidence_data(value):
    return value['data'] if receipt(value) else None

def independently_dated_origin_route(player,zone):
    """Return a complete, dated recent PBP lane sample for one actual appearance.

    A missing lane is a measured zero ONLY when every actual appearance has
    complete official PBP coverage and every on-net event was mappable. Season
    EDGE totals and goal totals never substitute for this sample.
    """
    wrapper=player.get("recentOrigin")
    pressure=player.get("pressure")
    if not receipt(wrapper) or not receipt(pressure):
        return None
    data=wrapper.get("data") or {}
    pressure_data=evidence_data(pressure) or {}
    if (data.get("sourceType")!="OFFICIAL_NHL_DATED_PBP_SHOOTER_ORIGIN"
        or data.get("scope")!="RECENT_PRE_SLATE_TARGET_CLUB_GAMES_ONLY"
        or data.get("rinkBinsApproximateNotNhlEdgePolygons") is not True
        or data.get("historicalOwnGoalCreditOnly") is not True
        or data.get("sampleCoverageComplete") is not True
        or data.get("sampleIncludesActualZeroShotAppearances") is not True
        or data.get("unclassifiedOnNetShots")!=0
        or data.get("pbpBoxscoreSogReconciled") is not True):
        return None
    as_of=data.get("sampleAsOfSlateDate")
    sample_ids=data.get("sampleGameIds")
    appearances=pressure_data.get("appearances")
    sample_sources=data.get("sampleSourcesByGame")
    if (not isinstance(as_of,str) or len(as_of)<10
        or not isinstance(sample_ids,list) or not sample_ids
        or type(data.get("sampleAppearanceCount")) is not int
        or data["sampleAppearanceCount"]!=len(sample_ids)
        or not isinstance(appearances,list) or len(appearances)!=len(sample_ids)
        or not isinstance(sample_sources,dict)
        or len({str(x) for x in sample_ids})!=len(sample_ids)):
        return None
    appearance_dates={}
    appearance_shots={}
    appearance_ids=[]
    for item in appearances:
        if not isinstance(item,dict):
            return None
        gid=str(item.get("gameId") or "")
        day=item.get("date")
        shots=item.get("shotsOnGoal")
        if (not gid or not isinstance(day,str) or len(day)<10 or day[:10]>=as_of
            or gid in appearance_dates or type(shots) is not int or shots<0):
            return None
        appearance_ids.append(gid)
        appearance_dates[gid]=day[:10]
        appearance_shots[gid]=shots
    normalized_ids=[str(x) for x in sample_ids]
    if appearance_ids!=normalized_ids:
        return None
    pbp_sog=data.get("pbpOnNetShotsByGame")
    boxscore_sog=data.get("boxscoreShotsOnGoalByGame")
    if (not isinstance(pbp_sog,dict) or not isinstance(boxscore_sog,dict)
        or set(pbp_sog)!=set(normalized_ids)
        or set(boxscore_sog)!=set(normalized_ids)
        or any(type(pbp_sog.get(gid)) is not int or pbp_sog[gid]<0
               or type(boxscore_sog.get(gid)) is not int or boxscore_sog[gid]<0
               or pbp_sog[gid]!=boxscore_sog[gid]
               or boxscore_sog[gid]!=appearance_shots[gid]
               for gid in normalized_ids)):
        return None
    for gid in normalized_ids:
        urls=sample_sources.get(gid)
        if (not isinstance(urls,list) or not urls
            or any(not isinstance(u,str) or not u.startswith("https://") for u in urls)):
            return None
    zone_counts=data.get("zoneCounts")
    if not isinstance(zone_counts,dict):
        return None
    area=zone_counts.get(zone)
    by_game={}
    if area is not None:
        if (not isinstance(area,dict) or not isinstance(area.get("byGame"),list)
            or not isinstance(area.get("sourceUrls"),list) or not area["sourceUrls"]):
            return None
        for item in area["byGame"]:
            if not isinstance(item,dict):
                return None
            gid=str(item.get("gameId") or "")
            day=item.get("date")
            shots=item.get("shotsOnGoal")
            goals=item.get("ownedGoals")
            urls=item.get("sourceUrls")
            if (gid not in appearance_dates or gid in by_game
                or day!=appearance_dates[gid]
                or type(shots) is not int or shots<0
                or type(goals) is not int or goals<0 or goals>shots
                or not isinstance(urls,list) or not urls
                or any(u not in sample_sources[gid] for u in urls)):
                return None
            by_game[gid]={"shotsOnGoal":shots,"ownedGoals":goals}
        total_shots=area.get("shotsOnGoal")
        total_goals=area.get("ownedGoals")
        if (type(total_shots) is not int or type(total_goals) is not int
            or total_shots!=sum(x["shotsOnGoal"] for x in by_game.values())
            or total_goals!=sum(x["ownedGoals"] for x in by_game.values())):
            return None
    # An absent zone is a source-verified zero only because sampleCoverageComplete
    # and unclassifiedOnNetShots==0 were checked above.
    rows=[{"gameId":gid,"date":appearance_dates[gid],
           "shotsOnGoal":by_game.get(gid,{}).get("shotsOnGoal",0),
           "ownedGoals":by_game.get(gid,{}).get("ownedGoals",0)}
          for gid in normalized_ids]
    source_urls=sorted({u for gid in normalized_ids for u in sample_sources[gid]})
    return {"zone":zone,
            "ownedGoals":sum(x["ownedGoals"] for x in rows),
            "shotsOnGoal":sum(x["shotsOnGoal"] for x in rows),
            "appearanceCount":len(rows),
            "positiveShotAppearances":sum(x["shotsOnGoal"]>0 for x in rows),
            "shotsByAppearance":rows,
            "sampleGameIds":normalized_ids,
            "sampleDates":[appearance_dates[x] for x in normalized_ids],
            "sourceUrls":source_urls,
            "pbpBoxscoreSogReconciled":True,
            "pbpOnNetShotsByGame":{gid:pbp_sog[gid] for gid in normalized_ids},
            "boxscoreShotsOnGoalByGame":{gid:boxscore_sog[gid] for gid in normalized_ids},
            "scope":"SOURCE_DATED_PBP_APPROXIMATE_RINK_ORIGIN",
            "notAnNhlEdgeAreaPolygon":True,
            "seasonTotalsNotUsed":True,
            "notProofOfFutureGoal":True}




def independently_bounded_origin_route(player, zone):
    """Conservative dated lane bounds when an otherwise reconciled PBP sample
    has on-net shots without usable coordinates.

    Known mapped PBP shots establish a LOWER bound in the exact rink lane.
    ALL officially credited on-net shots establish an UPPER bound. Missing
    coordinates can NEVER be treated as zero, and no historical goals are
    used for recipient selection. If the exact sample is complete, both
    bounds coincide with the already certified lane count.
    """
    exact = independently_dated_origin_route(player, zone)
    if exact is not None:
        return {**exact, "shotsOnGoalLowerBound": exact["shotsOnGoal"],
                "shotsOnGoalUpperBound": exact["shotsOnGoal"],
                "completeExactOriginSample": True,
                "unknownLocationShotsMayBeInLane": False,
                "boundsAreOfficialDatedOnNetShots": True}
    wrapper = player.get("recentOrigin")
    pressure = player.get("pressure")
    if not receipt(wrapper) or not receipt(pressure) or not isinstance(zone, str) or not zone:
        return None
    d = wrapper["data"]
    p = pressure["data"]
    if (d.get("sourceType") != "OFFICIAL_NHL_DATED_PBP_SHOOTER_ORIGIN"
        or d.get("scope") != "RECENT_PRE_SLATE_TARGET_CLUB_GAMES_ONLY"
        or d.get("historicalOwnGoalCreditOnly") is not True
        or d.get("rinkBinsApproximateNotNhlEdgePolygons") is not True
        or d.get("sampleIncludesActualZeroShotAppearances") is not True
        or d.get("pbpBoxscoreSogReconciled") is not True
        or type(d.get("unclassifiedOnNetShots")) is not int
        or d["unclassifiedOnNetShots"] < 0):
        return None
    ids = d.get("sampleGameIds")
    as_of = d.get("sampleAsOfSlateDate")
    appearances = p.get("appearances")
    pressure_shots = p.get("recentAppearanceShots")
    by_game_sog = d.get("boxscoreShotsOnGoalByGame")
    pbp_sog = d.get("pbpOnNetShotsByGame")
    sources = d.get("sampleSourcesByGame")
    if (not isinstance(as_of, str) or len(as_of) < 10
        or not isinstance(ids, list) or not ids
        or type(d.get("sampleAppearanceCount")) is not int
        or d["sampleAppearanceCount"] != len(ids)
        or len({str(x) for x in ids}) != len(ids)
        or not isinstance(appearances, list) or len(appearances) != len(ids)
        or not isinstance(pressure_shots, list) or len(pressure_shots) != len(ids)
        or not isinstance(by_game_sog, dict) or not isinstance(pbp_sog, dict)
        or not isinstance(sources, dict)):
        return None
    ids = [str(x) for x in ids]
    if set(by_game_sog) != set(ids) or set(pbp_sog) != set(ids):
        return None
    dates = {}
    total = 0
    for i, (gid, appearance) in enumerate(zip(ids, appearances)):
        if not isinstance(appearance, dict):
            return None
        day = appearance.get("date")
        shots = appearance.get("shotsOnGoal")
        urls = sources.get(gid)
        if (str(appearance.get("gameId") or "") != gid
            or not isinstance(day, str) or len(day) < 10 or day[:10] >= as_of
            or type(shots) is not int or shots < 0
            or type(pressure_shots[i]) is not int or pressure_shots[i] != shots
            or type(by_game_sog.get(gid)) is not int or by_game_sog[gid] != shots
            or type(pbp_sog.get(gid)) is not int or pbp_sog[gid] != shots
            or not isinstance(urls, list) or not urls
            or any(not isinstance(u, str) or not u.startswith("https://") for u in urls)):
            return None
        dates[gid] = day[:10]
        total += shots
    counts = d.get("zoneCounts")
    if not isinstance(counts, dict):
        return None
    area = counts.get(zone)
    lower = 0
    if area is not None:
        if (not isinstance(area, dict) or not isinstance(area.get("byGame"), list)
            or type(area.get("shotsOnGoal")) is not int
            or type(area.get("ownedGoals")) is not int):
            return None
        seen = set()
        goals = 0
        for event in area["byGame"]:
            if not isinstance(event, dict):
                return None
            gid = str(event.get("gameId") or "")
            n = event.get("shotsOnGoal")
            g = event.get("ownedGoals")
            urls = event.get("sourceUrls")
            if (gid not in dates or gid in seen or event.get("date") != dates[gid]
                or type(n) is not int or type(g) is not int
                or not 0 <= g <= n <= by_game_sog[gid]
                or not isinstance(urls, list) or not urls
                or any(u not in sources[gid] for u in urls)):
                return None
            seen.add(gid)
            lower += n
            goals += g
        if lower != area["shotsOnGoal"] or goals != area["ownedGoals"]:
            return None
    if lower > total:
        return None
    return {"zone": zone, "appearanceCount": len(ids),
            "shotsOnGoalLowerBound": lower, "shotsOnGoalUpperBound": total,
            "completeExactOriginSample": False,
            "unknownLocationShotsMayBeInLane": lower < total,
            "boundsAreOfficialDatedOnNetShots": True,
            "sampleGameIds": ids, "sampleDates": [dates[gid] for gid in ids],
            "sourceUrls": sorted({u for gid in ids for u in sources[gid]}),
            "sampleAsOfSlateDate": as_of,
            "seasonGoalTotalsNeverUsed": True,
            "notProofOfFutureGoal": True,
            "scope": "RECONCILED_NHL_BOXSCORE_PBP_LANE_LOWER_UPPER_BOUNDS"}
