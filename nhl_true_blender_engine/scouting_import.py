"""Attach sourced anatomical goalie scouting to the goalie starter for G0/G3/G5.

Scouting describes a goalie, not a starting assignment. Only an independently
reported goalieId/status is eligible for pairing; no projected->confirmed upgrade.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from .enrichment import ingest

def ingest_scouting(con, snapshot, date, stage, path):
    records=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(records,list):raise ValueError("Scouting JSON must be a list")
    imported=0
    for g in snapshot["games"]:
        for team in (g["away"],g["home"]):
            for branch in g.get("goalies",{}).get(team,[]):
                goalie_id=str(branch.get("data",{}).get("goalieId") or "")
                status=branch.get("data",{}).get("status")
                if not goalie_id or status not in ("PROJECTED","EXPECTED","CONFIRMED"):
                    continue
                for record in records:
                    if str(record.get("goalieId"))!=goalie_id:continue
                    if record.get("publishedDate","9999")>date:continue
                    if not str(record.get("sourceUrl","")).startswith("https://"):continue
                    if not record.get("weakZones") or not record.get("sample"):
                        continue
                    if record.get("counterevidence") is None:continue
                    # No invented mapping from report phrases to shooter release lanes.
                    payload={"team":team,"goalieId":goalie_id,"status":status,
                             "weakZones":record["weakZones"],
                             "strengthZones":record.get("strengthZones",{}),
                             "sample":record["sample"],
                             "counterevidence":record["counterevidence"],
                             "publishedDate":record["publishedDate"],
                             "scoutingMethod":record.get("method"),
                             "starterSourceUrl":branch["sourceUrl"],
                             "anatomicalSourceType":"PUBLISHED_GOALS_AGAINST_SCOUTING"}
                    ingest(con,{"evidence_id":f"scout-{date}-{stage}-{g['id']}-{goalie_id}",
                        "slate_date":date,"stage":stage,"game_id":g["id"],
                        "kind":"GOALIE_PROFILE","source_url":record["sourceUrl"],
                        "observed_at":datetime.now(timezone.utc).isoformat(),
                        "payload":payload})
                    imported+=1
                    break
    return {"scoutingProfilesAttached":imported,"inputRecords":len(records),
            "note":"Only independently identified starters paired with dated anatomical goal scouting"}
