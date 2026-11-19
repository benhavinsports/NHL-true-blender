"""Restore already-captured, source-dated DFO historical reports from GitHub Actions.

Fallback is accepted only when the current crawl is wholly unavailable,
not to override fresh successfully retrieved evidence.  This never creates a
goalie starter.  The existing strict importer still validates official game,
player ID, original reportUpdatedAt, team identity and per-game puck cutoff.

The pinned GitHub run is a known successful *capture* of the source archive,
not a baseline prediction. If its artifact disappears, fail closed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

CAPTURE_RUN = "44475340898"
ARTIFACT = "historical-replay-2026-09-29-through-2026-11-17"
CAPTURE_PERIOD = ("2026-09-29", "2026-11-17")


def _valid_archived_page(page, day):
    return (isinstance(page, dict)
            and page.get("date") == day
            and page.get("httpStatus") == 200
            and page.get("availableAsDatedHistoricalPage") is True
            and page.get("url") == f"https://www.dailyfaceoff.com/starting-goalies/{day}"
            and isinstance(page.get("pageSha256"), str)
            and len(page["pageSha256"]) == 64
            and isinstance(page.get("games"), list))


def select_prior_capture(current, prior, manifest, *, captured_run=CAPTURE_RUN):
    """Return a validated source archive or None, never manufacture receipts."""
    wanted = sorted(manifest.get("scheduledDates") or [])
    if (manifest.get("start"), manifest.get("end")) != CAPTURE_PERIOD:
        return None
    if not wanted or len(wanted) != 50:
        return None
    if current.get("accessibleDatedPages", 0) > 0:
        return None  # do not replace a partially successful live provider crawl
    if (prior.get("source") != "Daily Faceoff dated historical starting-goalie pages"
            or tuple(prior.get("dateRange") or ()) != CAPTURE_PERIOD
            or prior.get("scheduledDatesChecked") != len(wanted)):
        return None
    pages = prior.get("pages") or []
    by_day = {p["date"]: p for p in pages if isinstance(p, dict) and p.get("date")}
    if len(by_day) != len(wanted):
        return None
    if not all(_valid_archived_page(by_day[day], day) for day in wanted):
        return None
    if prior.get("accessibleDatedPages") != len(wanted):
        return None
    # The existing importer will independently reject every goalie report
    # that is not time-valid or not identity-matched to the frozen schedule.
    return {
        **prior,
        "reusedVerifiedPriorGitHubArtifact": True,
        "priorEvidenceCaptureRunId": str(captured_run),
        "providerOutageDidNotReplaceOriginalReportTimestamps": True,
        "originalPageDownloadedAtPreserved": True,
        "notCurrentLiveProviderObservation": True,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("archive", type=Path)
    p.add_argument("--run", default=CAPTURE_RUN)
    p.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    a = p.parse_args()
    manifest = json.loads(a.manifest.read_text())
    archive = json.loads(a.archive.read_text()) if a.archive.exists() else {}
    if archive.get("accessibleDatedPages", 0) > 0:
        print("DFO_ARCHIVE_RECOVERY_NOT_NEEDED: current source returned dated pages")
        return
    if (manifest.get("start"), manifest.get("end")) != CAPTURE_PERIOD:
        print("DFO_ARCHIVE_RECOVERY_NOT_APPLICABLE: unverified replay date range")
        return
    if not a.repo or not os.getenv("GH_TOKEN"):
        print("DFO_ARCHIVE_RECOVERY_UNAVAILABLE: GitHub Actions read token missing")
        return
    # Recovered archives are themselves uploaded as an artifact on each replay.
    # Prefer the newest verified prior capture, and keep the initial known
    # independently collected capture as the final retention-limited seed.
    # All candidates must pass select_prior_capture() before being consumed.
    choices = []
    try:
        listing = subprocess.run(
            ["gh", "api", "-X", "GET",
             f"repos/{a.repo}/actions/artifacts", "-f", "per_page=100",
             "-f", f"name={ARTIFACT}"],
            capture_output=True, text=True, timeout=25, check=False)
        if listing.returncode == 0:
            data = json.loads(listing.stdout)
            for artifact in data.get("artifacts") or []:
                source_run = str((artifact.get("workflow_run") or {}).get("id") or "")
                if (not source_run or source_run == os.getenv("GITHUB_RUN_ID")
                        or artifact.get("expired") is True
                        or artifact.get("name") != ARTIFACT
                        or artifact.get("size_in_bytes", 0) < 1_000_000):
                    continue
                if source_run not in choices:
                    choices.append(source_run)
                if len(choices) >= 5:
                    break
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass  # pinned original prior capture remains available as a fallback
    for source_run in (str(a.run),):
        if source_run not in choices:
            choices.append(source_run)

    with tempfile.TemporaryDirectory(prefix="dfo-prior-source-") as tmp:
        for idx, source_run in enumerate(choices):
            candidate_dir = Path(tmp) / f"run-{idx}"
            candidate_dir.mkdir()
            try:
                result = subprocess.run(
                    ["gh", "run", "download", source_run, "--repo", a.repo,
                     "--name", ARTIFACT, "--dir", str(candidate_dir)],
                    capture_output=True, text=True, timeout=180, check=False)
                if result.returncode != 0:
                    print("DFO_ARCHIVE_CAPTURE_MISSING: run="
                          + source_run + " " + result.stderr.strip()[:160])
                    continue
            except (OSError, subprocess.TimeoutExpired) as exc:
                print(f"DFO_ARCHIVE_CAPTURE_MISSING: run={source_run} "
                      f"{type(exc).__name__}: {exc}")
                continue
            candidate = candidate_dir / "dfo-goalie-archive.json"
            if not candidate.is_file():
                continue
            try:
                prior = json.loads(candidate.read_text(encoding="utf-8"))
            except ValueError:
                continue
            selected = select_prior_capture(
                archive, prior, manifest, captured_run=source_run)
            if not selected:
                continue
            a.archive.write_text(json.dumps(selected, indent=2), encoding="utf-8")
            print(json.dumps({
                "status": "RESTORED_ALREADY_OBSERVED_DATED_SOURCE_EVIDENCE",
                "priorCaptureRun": source_run,
                "verifiedDatedPages": selected["accessibleDatedPages"],
                "priorCompleteGamePairs": selected["completeGamePairs"],
                "pageDownloadsWereLaterThanGames": True,
                "originalIndividualGoalieReportTimesRetained": True,
            }, sort_keys=True))
            return
        print("DFO_ARCHIVE_RECOVERY_UNAVAILABLE: no prior artifact passed source/time checks")



if __name__ == "__main__":
    main()
