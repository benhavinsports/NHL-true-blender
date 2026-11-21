"""GitHub-native watchdog: dispatch original NHL engine only if idle and stale."""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACTIVE = {"queued", "pending", "in_progress", "requested", "waiting"}


def evaluate(runs, now, verified_sha=None):
    if now.tzinfo is None or not isinstance(runs, list):
        raise ValueError("Watchdog needs timestamped GitHub run inventory")
    if any(run.get("status") in ACTIVE for run in runs):
        return {"dispatch": False, "reason": "ACTIVE_ENGINE"}
    if verified_sha and not any(
            r.get("head_sha") == verified_sha for r in runs):
        # A new fully verified code revision requires a real source execution
        # before puck drop. Recent tests are not a substitute for live G0-G18.
        return {"dispatch": True, "reason": "NEW_VERIFIED_ENGINE_REVISION"}
    if runs:
        times = [datetime.fromisoformat(str(r["created_at"]).replace("Z","+00:00"))
                 for r in runs]
        if any(t.tzinfo is None for t in times):
            raise ValueError("Unverified workflow run timestamp")
        if now.astimezone(timezone.utc) - max(times) < timedelta(minutes=35):
            return {"dispatch": False, "reason": "RECENT_ENGINE"}
    return {"dispatch": True, "reason": "ENGINE_STALE_AND_IDLE"}



def latest_pregame_slate(root, now):
    """Return the latest saved slate and its not-yet-started game IDs."""
    folder = Path(root) / "site_runs"
    states = []
    if not folder.is_dir():
        return None, []
    for path in folder.glob("*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (isinstance(state, dict) and state.get("slateDate")
                and isinstance(state.get("gameSurvivorPool"), list)):
            states.append(state)
    if not states:
        return None, []
    state = max(states, key=lambda x: (
        str(x.get("slateDate") or ""), str(x.get("updatedUTC") or "")))
    upcoming = []
    for game in state["gameSurvivorPool"]:
        raw = game.get("gameStartUTC")
        if not raw:
            continue
        try:
            start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if start.tzinfo is not None and start.astimezone(timezone.utc) > now.astimezone(timezone.utc):
            upcoming.append(str(game.get("gameId") or ""))
    return state, upcoming

def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    url = f"repos/{repository}/actions/workflows/nhl-true-blender.yml/runs?per_page=30"
    raw = subprocess.run(["gh", "api", url], capture_output=True,
                         text=True, check=True).stdout
    verified_sha = os.getenv("VERIFIED_SHA") or None
    # A workflow_run can fire after another code push. Do not launch based on
    # old test evidence for a newer, untested main branch.
    if verified_sha and verified_sha != os.getenv("GITHUB_SHA"):
        print("AUTOMATIC_BLENDER_WATCHDOG: STALE_VERIFICATION", flush=True)
        return
    now = datetime.now(timezone.utc)
    runs = json.loads(raw)["workflow_runs"]
    completed_workflow = os.getenv("COMPLETED_WORKFLOW") or ""
    if completed_workflow == "NHL True Blender - independent scheduled engine":
        # Every completed full engine cycle hands off to the next full source
        # cycle while at least one official game remains before its own puck drop.
        # This is not a retry cap or a gate: it ends only when the saved slate's
        # scheduled games have started. Active-run detection still prevents overlap.
        if any(run.get("status") in ACTIVE for run in runs):
            decision = {"dispatch": False, "reason": "ACTIVE_ENGINE"}
        else:
            state, upcoming = latest_pregame_slate("state", now)
            if state and upcoming:
                decision = {
                    "dispatch": True,
                    "reason": "CONTINUE_SOURCE_RECOVERY_UNTIL_PUCK_DROP",
                    "slateDate": state["slateDate"],
                    "remainingPregameGames": len(upcoming),
                    "gameIds": upcoming,
                }
            else:
                decision = {"dispatch": False, "reason": "NO_UPCOMING_PREGAME_GAMES"}
    else:
        decision = evaluate(runs, now, verified_sha=verified_sha)
    print("AUTOMATIC_BLENDER_WATCHDOG: " + json.dumps(decision), flush=True)
    if decision["dispatch"]:
        command = ["gh", "workflow", "run", "nhl-true-blender.yml",
                   "--repo", repository, "--ref", "main"]
        if decision.get("slateDate"):
            command.extend(["--field", "date=" + decision["slateDate"]])
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
