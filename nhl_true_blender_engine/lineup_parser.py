"""Parse published lineup markdown into official-ID-matched source evidence.

Source's 'confirmed' goalie is retained as a *source claim*; projected lines
are never promoted to team-confirmed. No name-only player ID guesses.
"""
import re
import unicodedata
from .enrichment import ingest

URL = "https://www.betweenthelineshockey.com/tonight.md"

def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.casefold())


def unique_official_player(name, roster, reserved_ids=()):
    """Resolve a lineup name without guessing a player ID.

    First use the complete normalized official name. Only if absent, permit
    first-name/nickname variants with at least three matching initial letters
    and an *exact* remaining surname. Never collapse two same-name players,
    double-map published assignments, or infer a player's role from a team
    roster alone.
    """
    exact=[p for p in roster if norm(p.get("name",""))==norm(name)]
    if len(exact)==1 and str(exact[0]["id"]) not in reserved_ids:
        return exact[0]
    if exact:
        return None
    parts=str(name).split()
    if len(parts)<2:
        return None
    first=norm(parts[0]);surname=norm(" ".join(parts[1:]))
    if len(first)<3 or not surname:
        return None
    candidates=[]
    for p in roster:
        tokens=str(p.get("name","")).split()
        if len(tokens)<2:
            continue
        a=norm(tokens[0]);b=norm(" ".join(tokens[1:]))
        if (len(a)>=3 and a[:3]==first[:3] and b==surname and
            str(p.get("id")) not in reserved_ids):
            candidates.append(p)
    return candidates[0] if len(candidates)==1 else None

def parse_markdown(text):
    teams = {}
    goalies = []
    team = None
    section = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("## "):
            # Starting goalies belong to EACH matchup. Forget the preceding
            # team's Injuries section; otherwise every later goalie line is
            # accidentally stored as an injury instead of being parsed.
            team = None
            section = None
        elif line.startswith("### "):
            team = line[4:].strip()
            teams.setdefault(team, {"lines": [], "pairs": [], "pp": {}, "injuries": []})
            section = None
        elif line in ("Forward lines:", "Defense pairs:", "Injuries:"):
            section = line[:-1]
        elif line.startswith("Power play ") and team:
            m = re.match(r"Power play ([12]):\s*(.*)", line)
            if m:
                teams[team]["pp"][m.group(1)] = [x.strip() for x in re.split(r"\s+(?:--|[–—-])\s+", m.group(2))]
        elif team and section in ("Forward lines", "Defense pairs") and re.match(r"^[1-4]\. ", line):
            names = [x.strip() for x in re.split(r"\s+(?:--|[–—-])\s+", line.split(". ", 1)[1])]
            teams[team]["lines" if section == "Forward lines" else "pairs"].append(names)
        elif team and section == "Injuries" and line.startswith("- "):
            teams[team]["injuries"].append(line[2:])
        elif line.startswith("- ") and ("Confirmed" in line or "Unconfirmed" in line):
            m = re.match(r"- (.*?) \(([A-Z]{3})\), (Confirmed|Unconfirmed)\b", line)
            if m:
                goalies.append({"name": m.group(1), "team": m.group(2),
                                "status": m.group(3).upper()})
    return {"teams": teams, "goalies": goalies}

def ingest_lineups(con, snapshot, date, stage, text, observed_at):
    parsed = parse_markdown(text)
    inserted = 0
    matched_goalie_reports = 0
    unmatched = []
    for game in snapshot["games"]:
        for abbrev in (game["away"], game["home"]):
            roster = (game.get("rosters", {}).get(abbrev) or {}).get("data", {}).get("players", [])
            by_name = {}
            for p in roster:
                by_name.setdefault(norm(p["name"]), []).append(p)
            # Team headings are mapped through a known NHL franchise name rather
            # than loose substrings of a player's name.
            from .secondary_sources import TEAM_SLUGS
            slug = TEAM_SLUGS.get(abbrev)
            if not slug:
                continue
            heading = next((k for k in parsed["teams"] if norm(k) == norm(slug.replace("-", " "))), None)
            if not heading:
                continue
            team = parsed["teams"][heading]
            assignments = {}
            for i, names in enumerate(team["lines"], 1):
                for name in names:
                    assignments.setdefault(name, {}).update({"line": i, "EV": f"F{i}"})
            for i, names in enumerate(team["pairs"], 1):
                for name in names:
                    assignments.setdefault(name, {}).update({"defensePair": i, "EV": f"D{i}"})
            for unit, names in team["pp"].items():
                for name in names:
                    assignments.setdefault(name, {})["powerPlayUnit"] = int(unit)
            # Reserve IDs with unambiguous full-name matches before trying
            # nicknames. Two source names cannot silently become one skater.
            exact_ids={}
            for name in assignments:
                matches=by_name.get(norm(name),[])
                if len(matches)==1:
                    exact_ids[name]=str(matches[0]["id"])
            seen={}
            for name,data in assignments.items():
                p=unique_official_player(name,roster,(
                    pid for other,pid in exact_ids.items() if other!=name))
                if not p:
                    unmatched.append({"team":abbrev,"name":name,
                                      "reason":"OFFICIAL_PLAYER_ID_NOT_UNIQUELY_MATCHED"})
                    continue
                pid=str(p["id"])
                if pid in seen:
                    unmatched.append({"team":abbrev,"name":name,
                                      "reason":"DUPLICATE_PLAYER_ID_LINEUP_CONFLICT"})
                    continue
                seen[pid]=name
                ingest(con, {
                    "evidence_id": f"btl-{date}-{stage}-{game['id']}-{p['id']}-{observed_at}",
                    "slate_date": date, "stage": stage,
                    "game_id": game["id"], "player_id": p["id"],
                    "kind": "PLAYER_DEPLOYMENT", "source_url": URL,
                    "observed_at": observed_at,
                    "payload": {**data, "status": "PROJECTED",
                                "sourceType": "SECONDARY_PROJECTED_LINEUP"}
                })
                ingest(con, {"evidence_id": f"btl-status-{date}-{stage}-{game['id']}-{p['id']}-{observed_at}",
                    "slate_date":date,"stage":stage,"game_id":game["id"],
                    "player_id":p["id"],"kind":"PLAYER_STATUS","source_url":URL,
                    "observed_at":observed_at,
                    "payload":{"status":"PROJECTED_ACTIVE","sourceType":"SECONDARY_PROJECTED_LINEUP"}})
                inserted += 1
        for goalie in parsed["goalies"]:
            if goalie["team"] not in (game["home"], game["away"]):
                continue
            roster = (game.get("rosters", {}).get(goalie["team"]) or {}).get("data", {})
            # The NHL official roster can spell a first name differently
            # (Dan/Daniel). Apply the SAME unambiguous full-name-or-first-name
            # variant matcher as skaters, with an exact surname. Never guess
            # from a surname alone or accept two matching official IDs.
            matched = unique_official_player(goalie["name"], roster.get("goalies", []))
            if matched is None:
                unmatched.append({"team": goalie["team"], "goalie": goalie["name"],
                                  "reason": "OFFICIAL_GOALIE_ID_UNMATCHED_OR_AMBIGUOUS"})
                continue
            ingest(con, {
                "evidence_id": f"btl-goalie-{date}-{stage}-{game['id']}-{goalie['team']}-{observed_at}",
                "slate_date": date, "stage": stage, "game_id": game["id"],
                "kind": "GOALIE_STARTER", "source_url": URL,
                "observed_at": observed_at,
                "payload": {"team": goalie["team"], "goalieName": goalie["name"],
                            "goalieId": matched["id"],
                            "status": "CONFIRMED" if goalie["status"] == "CONFIRMED" else "EXPECTED",
                            "identityMatched": True,
                            "starterSourceStatus": goalie["status"],
                            "note": "Secondary lineup report; not independent team confirmation"}
            })
            matched_goalie_reports += 1
    return {"deploymentRecords": inserted, "unmatched": unmatched,
            "goalieReports": len(parsed["goalies"]),
            "matchedGoalieReports": matched_goalie_reports,
            "unmatchedGoalieReports": sum("goalie" in x for x in unmatched),
            "source": URL}


async def fetch_and_ingest_lineups(con,snapshot,date,stage):
    """Fetch the actual daily lineup artifact every time, including watch refreshes.

    Source status labels remain independent third-party reports, not official
    club confirmation. The official NHL scheduled games are the only join targets.
    """
    import httpx
    from datetime import datetime,timezone
    try:
        async with httpx.AsyncClient(timeout=18,follow_redirects=True,
                headers={"Accept":"text/markdown","User-Agent":"NHLTrueBlender/1.0"}) as client:
            response=await client.get(URL)
            response.raise_for_status()
            if not response.text:
                raise ValueError("Empty lineup source")
            first=response.text.splitlines()[0]
            if f"games dated {date}" not in first:
                raise ValueError("Lineup snapshot slate date mismatch: "+first[:120])
            observed=datetime.now(timezone.utc).isoformat(timespec="seconds")
            parsed=ingest_lineups(con,snapshot,date,stage,response.text,observed)
            return {"status":"DATED_SOURCE_PARSED","asOf":observed,**parsed}
    except (httpx.HTTPError,ValueError,IndexError) as exc:
        return {"status":"SOURCE_UNAVAILABLE","source":URL,
                "error":f"{type(exc).__name__}: {exc}"}


async def fetch_and_ingest_additional_deployment(con,snapshot,date,stage):
    """Use the existing multi-source structured parser, not unparsed HTML.

    Evidence is projected unless a source explicitly proves confirmation.
    Conflicting line assignments remain unresolved and cannot pass G6.
    """
    import asyncio
    from datetime import datetime,timezone
    from deployment_sources import fetch_deployment
    from .enrichment import ingest
    from .secondary_sources import TEAM_SLUGS
    teams=sorted({team for game in snapshot['games']
                  for team in (game['home'],game['away'])})
    results=await asyncio.gather(*(asyncio.to_thread(
        fetch_deployment,team,TEAM_SLUGS.get(team),mode='confirmed'
        if stage=='CONFIRMED' else 'projected') for team in teams),
        return_exceptions=True)
    observed=datetime.now(timezone.utc).isoformat(timespec='seconds')
    inserted=0; unmatched=[]; reports={}; skipped=[]
    for team,result in zip(teams,results):
        if isinstance(result,Exception):
            reports[team]={'error':str(result)}
            continue
        rows,meta=result
        reports[team]=meta
        for game in snapshot['games']:
            if team not in (game['home'],game['away']):
                continue
            roster=(game.get('rosters',{}).get(team) or {}).get('data',{})
            players=roster.get('players') or []
            for row in rows:
                if row.get('conflicts') or row.get('line') is None:
                    continue
                player=unique_official_player(row.get('playerName'),players)
                if player is None:
                    unmatched.append({'team':team,'name':row.get('playerName')})
                    continue
                urls={item.get('sourceUrl') for item in row.get('lineEvidence',[])
                      if isinstance(item.get('sourceUrl'),str)
                      and item['sourceUrl'].startswith('https://')}
                # Ambiguous attribution cannot be certified by arbitrary
                # provider preference.
                url=sorted(urls)[0] if urls else None
                if not isinstance(url,str) or not url.startswith('https://'):
                    continue
                line=row['line']
                try:
                    line=int(line)
                except (ValueError,TypeError):
                    continue
                if not 1<=line<=4:
                    continue
                # This parser describes forward lines, not defense pairs.
                # Never manufacture a D1-D4 assignment from a forward line.
                position=str(player.get('position') or player.get('positionCode') or '').upper()
                if position in ('D','DEFENSEMAN','DEFENCE','DEFENSE'):
                    skipped.append({'team':team,'name':row.get('playerName'),
                                    'reason':'FORWARD_LINE_IS_NOT_DEFENSE_PAIR'})
                    continue
                # No confirmed claim: the sources are projected line reports.
                payload={'EV':'F'+str(line),
                         'status':'PROJECTED',
                         'sourceType':'MULTISOURCE_PROJECTED_LINEUP',
                         'lineEvidence':row.get('lineEvidence',[]),
                         'sourceUrls':sorted(urls),
                         'powerPlayEvidence':row.get('powerPlayEvidence',[])}
                if row.get('powerPlayUnit') is not None:
                    payload['PP']=row['powerPlayUnit']
                ingest(con,{'evidence_id':f'multisource-{date}-{stage}-{game["id"]}-{player["id"]}-{observed}',
                    'slate_date':date,'stage':stage,'game_id':game['id'],
                    'player_id':player['id'],'kind':'PLAYER_DEPLOYMENT',
                    'source_url':url,'observed_at':observed,'payload':payload})
                inserted+=1
    return {'deploymentRecords':inserted,'unmatched':unmatched,'skipped':skipped,'sources':reports}
