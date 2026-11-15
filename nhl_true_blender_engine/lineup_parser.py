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

def parse_markdown(text):
    teams = {}
    goalies = []
    team = None
    section = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("### "):
            team = line[4:].strip()
            teams.setdefault(team, {"lines": [], "pairs": [], "pp": {}, "injuries": []})
            section = None
        elif line in ("Forward lines:", "Defense pairs:", "Injuries:"):
            section = line[:-1]
        elif line.startswith("Power play ") and team:
            m = re.match(r"Power play ([12]):\s*(.*)", line)
            if m:
                teams[team]["pp"][m.group(1)] = [x.strip() for x in re.split(r"\s+[–—-]\s+", m.group(2))]
        elif team and section in ("Forward lines", "Defense pairs") and re.match(r"^[1-4]\. ", line):
            names = [x.strip() for x in re.split(r"\s+[–—-]\s+", line.split(". ", 1)[1])]
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
            for name, data in assignments.items():
                candidates = by_name.get(norm(name), [])
                if len(candidates) != 1:
                    unmatched.append({"team": abbrev, "name": name})
                    continue
                p = candidates[0]
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
            matches = [p for p in roster.get("goalies", []) if norm(p["name"]) == norm(goalie["name"])]
            if len(matches) != 1:
                unmatched.append({"team": goalie["team"], "goalie": goalie["name"],
                                  "reason": "Official goalie ID not uniquely matched"})
                continue
            ingest(con, {
                "evidence_id": f"btl-goalie-{date}-{stage}-{game['id']}-{goalie['team']}-{observed_at}",
                "slate_date": date, "stage": stage, "game_id": game["id"],
                "kind": "GOALIE_STARTER", "source_url": URL,
                "observed_at": observed_at,
                "payload": {"team": goalie["team"], "goalieName": goalie["name"],
                            "goalieId": matches[0]["id"],
                            "status": "CONFIRMED" if goalie["status"] == "CONFIRMED" else "EXPECTED",
                            "identityMatched": True,
                            "starterSourceStatus": goalie["status"],
                            "note": "Secondary lineup report; not independent team confirmation"}
            })
    return {"deploymentRecords": inserted, "unmatched": unmatched,
            "goalieReports": len(parsed["goalies"]), "source": URL}
