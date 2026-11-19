"""GitHub-native watchdog: dispatch original NHL engine only if idle and stale."""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

ACTIVE = {"queued", "pending", "in_progress", "requested", "waiting"}


def evaluate(runs, now):
    if now.tzinfo is None or not isinstance(runs, list):
        raise ValueError("Watchdog needs timestamped GitHub run inventory")
    if any(run.get("status") in ACTIVE for run in runs):
        return {"dispatch": False, "reason": "ACTIVE_ENGINE"}
    if runs:
        times = [datetime.fromisoformat(str(r["created_at"]).replace("Z","+00:00"))
                 for r in runs]
        if any(t.tzinfo is None for t in times):
            raise ValueError("Unverified workflow run timestamp")
        if now.astimezone(timezone.utc) - max(times) < timedelta(minutes=35):
            return {"dispatch": False, "reason": "RECENT_ENGINE"}
    return {"dispatch": True, "reason": "ENGINE_STALE_AND_IDLE"}


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    url = f"repos/{repository}/actions/workflows/nhl-true-blender.yml/runs?per_page=30"
    raw = subprocess.run(["gh", "api", url], capture_output=True,
                         text=True, check=True).stdout
    decision = evaluate(json.loads(raw)["workflow_runs"],
                        datetime.now(timezone.utc))
    print("AUTOMATIC_BLENDER_WATCHDOG: " + json.dumps(decision), flush=True)
    if decision["dispatch"]:
        subprocess.run(["gh", "workflow", "run", "nhl-true-blender.yml",
                        "--repo", repository, "--ref", "main"], check=True)


if __name__ == "__main__":
    main()
