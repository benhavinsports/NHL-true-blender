"""Conservative single-card publication. Never turns an audit into a pick."""
from __future__ import annotations
import json
from pathlib import Path

def publish_verified_core(report, directory="runs"):
    core_output = report.get("coreOutput") or {}
    validation = report.get("validationSummary") or {}
    core = core_output.get("core") or []
    games = {str(p.get("gameId")) for p in core}
    slate_date = report.get("slateDate")
    if not slate_date:
        raise ValueError("Slate date is required")
    if not validation.get("finalPlayerPathsCertified"):
        return {"published": False, "reason": "No verified G18 Core; existing card unchanged"}
    if len(core) not in (2, 3) or len(games) != len(core):
        raise ValueError("Invalid Core: duplicate games or invalid length")
    if len(core) == 2 and report.get("gameCount") != 2:
        raise ValueError("Core 2 only allowed for a two-game slate")
    if len(core) == 3 and report.get("gameCount", 0) < 3:
        raise ValueError("Core 3 requires at least three games")
    if any(not p.get("playerId") or not p.get("gateTrace") for p in core):
        raise ValueError("Every Core player needs identity and gate evidence")
    required = [f"G{i}" for i in range(19)]
    required.insert(11, "G10.5")
    for player in core:
        trace = player["gateTrace"]
        by_gate = {entry.get("gate"): entry for entry in trace}
        missing = [g for g in required if g not in by_gate]
        if missing:
            raise ValueError(f"Core player missing gate evidence: {missing}")
        for gate_id in required:
            entry = by_gate[gate_id]
            state = str(entry.get("status", "")).upper()
            if not (("PASS" in state or "LOCKED" in state) and
                    not any(x in state for x in ("UNRESOLVED", "NOT VALIDATED", "REVIEW REQUIRED", "PENDING"))):
                if gate_id == "G13" and "QUALITATIVE REVIEW" in state:
                    continue
                raise ValueError(f"Core player has unpassed gate {gate_id}: {state}")
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"authoritative_core_{slate_date}.json"
    ids = [(str(p["gameId"]), str(p["playerId"])) for p in core]
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        old = [(str(p["gameId"]), str(p["playerId"])) for p in existing.get("core", [])]
        if ids != old:
            return {"published": False, "reason": "Different existing Core; gate-changing replacement audit required", "path": str(target)}
        return {"published": False, "reason": "Identical authoritative Core already saved; no replacement", "path": str(target)}
    payload = {"slateDate": slate_date, "mode": report.get("mode"),
               "runId": report.get("runId"), "core": core,
               "status": core_output.get("status"), "validated": True}
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"published": True, "path": str(target)}
