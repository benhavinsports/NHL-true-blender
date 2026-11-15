"""Validate anatomical goalie evidence for G0/G3/G5.

Shot *rink* coordinates are not goal-mouth impact zones. Sportradar's goal_zone
is a shooter-perspective goal-mouth zone; do not silently equate it with glove
or blocker without goalie handedness and a documented viewing convention.
"""
VALID_ZONES = {"upper left","upper middle","upper right","lower left","lower middle","lower right"}
VALID_HANDS = {"L","R"}

def validate_goal_zone_evidence(payload):
    if not isinstance(payload, dict):
        raise ValueError("Goalie evidence must be an object")
    hand = payload.get("catchingHand")
    if hand not in VALID_HANDS:
        raise ValueError("Verified goalie catching hand required")
    if payload.get("zonePerspective") != "shooter":
        raise ValueError("Goal zones require documented shooter perspective")
    if payload.get("sourceType") != "GOAL_MOUTH_IMPACT":
        raise ValueError("Rink shot coordinates cannot prove anatomical weakness")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("Individual sourced goal-mouth events required")
    counts = {z: {"shots": 0, "goals": 0} for z in VALID_ZONES}
    seen = set()
    for e in events:
        zone = e.get("goalZone")
        if zone not in VALID_ZONES:
            raise ValueError("Unrecognized goal-mouth zone")
        if not str(e.get("sourceUrl", "")).startswith("https://"):
            raise ValueError("Event source URL required")
        key = (str(e.get("gameId")), str(e.get("eventId")))
        if not all(key) or key in seen:
            raise ValueError("Unique source game and event IDs required")
        seen.add(key)
        if e.get("result") not in ("goal", "save"):
            raise ValueError("Goal-mouth result must be goal or save")
        counts[zone]["shots"] += 1
        counts[zone]["goals"] += e["result"] == "goal"
    # Do not create 'weakZones' merely by ranking raw counts.
    # A baseline, sufficient sample and contradiction review are separate requirements.
    return {"catchingHand": hand, "zoneCounts": counts, "sample": len(events),
            "sourceType": "GOAL_MOUTH_IMPACT", "anatomicalClaimCertified": False,
            "note": "Requires validated baseline, sample threshold, handedness mapping and counterevidence review."}
