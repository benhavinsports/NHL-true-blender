import asyncio
import json

from nhl_true_blender_engine.storage import open_db, record_evidence
from scripts.historical_season_credits import collect_historical_season_credits


def scene(tmp_path, *, credited_player="11", shots=3, goals=1):
    con = open_db(str(tmp_path/"source.sqlite"))
    record_evidence(con, {"evidence_id":"deployment", "slate_date":"2026-10-03",
        "stage":"PROJECTED", "game_id":"2026020010", "player_id":"11",
        "kind":"PLAYER_DEPLOYMENT", "source_url":"https://www.nhl.com/preview",
        "observed_at":"2026-10-03T15:00:00Z", "payload":{"EV":"F2"}})
    record_evidence(con, {"evidence_id":"sample-credit", "slate_date":"2026-10-03",
        "stage":"PROJECTED", "game_id":"2026020010", "player_id":"11",
        "kind":"PLAYER_FINISH_CREDIT", "source_url":"https://api-web.nhle.com/v1/gamecenter/2026020001/boxscore",
        "observed_at":"2026-10-02T05:00:00Z", "payload":{"ownedGoalsInActualAppearances":0}})
    class Client:
        requested = []
        async def game_log(self, pid, season):
            return {"url":f"https://api-web.nhle.com/v1/player/{pid}/game-log/{season}/2",
                "observedAt":"2026-11-20T12:00:00Z", "data":{"gameLog":[
                    {"gameId":2026020001,"gameDate":"2026-10-01","goals":goals,"shots":shots},
                    {"gameId":2026020010,"gameDate":"2026-10-03","goals":3,"shots":4},
                    {"gameId":2026020020,"gameDate":"2026-10-05","goals":4,"shots":5}]}}
        async def play_by_play(self, gid):
            self.requested.append(gid)
            return {"url":f"https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play",
                "data":{"plays":[{"typeDescKey":"goal","eventId":7,
                    "details":{"scoringPlayerId":credited_player,"xCoord":80,"yCoord":0}}]}}
    client = Client()
    emitted = []
    def emit(con, day, stage, gid, pid, kind, payload, sources, available):
        emitted.append({"kind":kind,"payload":payload,"sources":sources,"available":available})
    games = [{"id":"2026020010","startUTC":"2026-10-03T23:00:00Z"}]
    schedules = {"A":[{"id":"2026020001","startTimeUTC":"2026-10-01T23:00:00Z","gameState":"OFF"}]}
    result = asyncio.run(collect_historical_season_credits(
        client, con, "2026-10-03", games, schedules, {}, {}, emit, []))
    con.close()
    return emitted, client.requested, result


def test_reconstructed_credit_requires_pbp_shooter_and_excludes_same_slate_and_future(tmp_path):
    emitted, requested, result = scene(tmp_path)
    assert requested == ["2026020001"]
    season = next(r["payload"] for r in emitted if r["kind"] == "PLAYER_SEASON_HISTORY")
    assert season["officialPastSeasonGoals"] == 1
    assert season["actualAppearances"] == 1
    credit = next(r["payload"] for r in emitted if r["kind"] == "PLAYER_FINISH_CREDIT")
    assert credit["independentHistoricalGoalId"] == "2026020001:7"
    assert credit["ownedGoalsInActualAppearances"] == 0
    assert result["recentFormSampleUnchanged"] is True
    assert {r["available"].isoformat() for r in emitted} == {"2026-10-02T05:00:00+00:00"}


def test_another_players_goal_cannot_establish_ownership(tmp_path):
    emitted, _, result = scene(tmp_path, credited_player="22")
    assert result["independentlyVerifiedGoalCreditReceipts"] == 0
    assert not any(r["kind"] == "PLAYER_FINISH_CREDIT" for r in emitted)


def test_actual_dated_zero_shot_season_is_retained_without_inventing_a_goal(tmp_path):
    emitted, requested, result = scene(tmp_path, shots=0, goals=0)
    assert requested == []
    assert result["verifiedSeasonZeroShotReceipts"] == 1
    assert any(r["kind"] == "PLAYER_ZERO_ON_NET_ROUTE" for r in emitted)
    assert not any(r["kind"] == "PLAYER_FINISH_CREDIT" for r in emitted)
