"""Official slate calendar must distinguish source gaps from real NHL off-days."""
import asyncio
import json
import sys
from unittest.mock import patch

from scripts.replay_historical_season import main, grade_ledger


def run_manifest(tmp_path, manifest):
    src=tmp_path/"manifest.json"
    src.write_text(json.dumps(manifest))
    out=tmp_path/"selections.jsonl"
    with patch.object(sys,"argv",["replay_historical_season",str(src),str(out)]):
        outcome=main()
    rows=[json.loads(s) for s in out.read_text().splitlines()]
    return outcome, rows, out


def test_verified_nhl_off_day_is_not_counted_as_missing_source(tmp_path):
    calendar={"2026-11-18":{"source":"https://api-web.nhle.com/v1/score/2026-11-18",
                            "verifiedOffDay":True,"games":[]}}
    manifest={"start":"2026-11-18","end":"2026-11-18","stage":"PROJECTED",
              "officialSchedule":calendar,
              "verifiedOffDays":["2026-11-18"],"slates":{}}
    code,rows,selection=run_manifest(tmp_path,manifest)
    assert code==0
    assert rows==[{"date":"2026-11-18","status":"VERIFIED_OFF_DAY",
                  "officialScheduleSource":calendar["2026-11-18"]["source"]}]
    grades=tmp_path/"grades.jsonl"
    assert asyncio.run(grade_ledger(selection,grades))==0
    grade=json.loads(grades.read_text().splitlines()[0])
    assert grade["grade"]["status"]=="VERIFIED_OFF_DAY"


def test_schedule_without_archived_pregame_roster_stays_failure(tmp_path):
    manifest={"start":"2026-11-18","end":"2026-11-18","stage":"PROJECTED",
              "officialSchedule":{"2026-11-18":{
                 "source":"https://api-web.nhle.com/v1/score/2026-11-18",
                 "verifiedOffDay":False,"games":[{"gameId":123}]}},
              "slates":{}}
    result,rows,_=run_manifest(tmp_path,manifest)
    assert result==1
    assert rows[0]["status"]=="SCHEDULED_SOURCE_BLOCKED"


def test_unverified_off_day_flag_never_invents_off_day(tmp_path):
    manifest={"start":"2026-11-18","end":"2026-11-18",
              "stage":"PROJECTED","verifiedOffDays":["2026-11-18"],
              "officialSchedule":{"2026-11-18":{
                 "source":"https://api-web.nhle.com/v1/score/2026-11-18",
                 "verifiedOffDay":True,"games":[{"gameId":123}]}},
              "slates":{}}
    result,rows,_=run_manifest(tmp_path,manifest)
    assert result==1
    assert rows[0]["status"]=="SCHEDULE_UNVERIFIED"


def test_replayed_no_core_is_an_incomplete_historical_slate(tmp_path):
    """A green test suite cannot turn zero real scorers into a valid replay."""
    day = "2026-11-19"
    manifest = {"start": day, "end": day, "stage": "PROJECTED",
                "slates": {day: {"dummy": "independently timestamped bundle"}}}
    replay = {"date": day, "status": "REPLAYED",
              "engineResult": {"card": None},
              "gateCertification": {"selectedCoreOnlyFullyCertified": False}}
    with patch("scripts.replay_historical_season.replay_day", return_value=replay):
        code, rows, selection = run_manifest(tmp_path, manifest)
    assert code == 1
    assert rows[0]["status"] == "REPLAYED"
    assert rows[0]["coreIssuanceStatus"] == "NO_CORE"
    grades = tmp_path / "grades.jsonl"
    assert asyncio.run(grade_ledger(selection, grades)) == 1
    assert json.loads(grades.read_text())["grade"]["status"] == "NO_CORE"


def test_replayed_uncertified_core_fails_selection_and_grade(tmp_path):
    day = "2026-11-19"
    manifest = {"start": day, "end": day, "stage": "PROJECTED",
                "slates": {day: {"dummy": "pregame bundle"}}}
    replay = {"date": day, "status": "REPLAYED",
              "engineResult": {"card": {"current_legs": [{"gameId": "1", "playerId": "9"}]}},
              "gateCertification": {"selectedCoreOnlyFullyCertified": False}}
    with patch("scripts.replay_historical_season.replay_day", return_value=replay):
        code, rows, selection = run_manifest(tmp_path, manifest)
    assert code == 1
    assert rows[0]["coreIssuanceStatus"] == "CORE_NOT_CERTIFIED"
    grades = tmp_path / "grades.jsonl"
    assert asyncio.run(grade_ledger(selection, grades)) == 1
    assert json.loads(grades.read_text())["grade"]["status"] == "CORE_NOT_CERTIFIED"


def test_blocked_source_is_not_successful_postgame_grading(tmp_path):
    selection = tmp_path / "blocked.jsonl"
    selection.write_text(json.dumps({"date": "2026-11-19",
                                     "status": "SCHEDULED_SOURCE_BLOCKED"}) + "\n")
    grades = tmp_path / "blocked_grades.jsonl"
    assert asyncio.run(grade_ledger(selection, grades)) == 1
    assert json.loads(grades.read_text())["grade"]["status"] == "SCHEDULED_SOURCE_BLOCKED"
