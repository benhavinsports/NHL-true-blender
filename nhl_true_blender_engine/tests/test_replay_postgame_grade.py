import asyncio

import pytest

from scripts import replay_postgame_grade


class FakeNHLClient:
    payloads = {}

    async def boxscore(self, game_id):
        return self.payloads[game_id]["box"]

    async def play_by_play(self, game_id):
        return self.payloads[game_id]["pbp"]

    async def close(self):
        return None


def report(url, data):
    return {"url": url, "data": data}


def test_official_grade_separates_dressed_zero_from_not_listed(monkeypatch):
    FakeNHLClient.payloads = {
        "100": {
            "box": report("https://nhl.test/box/100", {
                "id": 100, "gameState": "FINAL",
                "playerByGameStats": {
                    "homeTeam": {"forwards": [{"playerId": 11, "goals": 0}], "defense": []},
                    "awayTeam": {"forwards": [{"playerId": 12, "goals": 1}], "defense": []},
                },
            }),
            "pbp": report("https://nhl.test/pbp/100", {
                "id": 100, "plays": [
                    {"typeDescKey": "goal", "periodDescriptor": {"periodType": "REG"},
                     "details": {"scoringPlayerId": 12}, "eventId": 7}
                ],
            }),
        },
        "101": {
            "box": report("https://nhl.test/box/101", {
                "id": 101, "gameState": "OFF",
                "playerByGameStats": {
                    "homeTeam": {"forwards": [{"playerId": 21, "goals": 0}], "defense": []},
                    "awayTeam": {"forwards": [{"playerId": 22, "goals": 0}], "defense": []},
                },
            }),
            "pbp": report("https://nhl.test/pbp/101", {"id": 101, "plays": []}),
        },
    }
    monkeypatch.setattr(replay_postgame_grade, "NHLClient", FakeNHLClient)
    result = asyncio.run(replay_postgame_grade.grade_frozen_legs([
        {"gameId": "100", "playerId": "11"},
        {"gameId": "101", "playerId": "99"},
    ]))
    assert result["status"] == "GRADED_FINAL_BOXSCORE_AND_PBP"
    assert result["hits"] == 0
    assert result["playerResults"][0]["participation"] == "LISTED_AS_DRESSED_SKATER"
    assert result["playerResults"][0]["goals"] == 0
    assert result["playerResults"][1]["participation"] == "NOT_LISTED_IN_OFFICIAL_BOXSCORE"
    assert result["playerResults"][1]["goals"] == 0


def test_official_grade_rejects_boxscore_pbp_goal_disagreement(monkeypatch):
    FakeNHLClient.payloads = {
        "200": {
            "box": report("https://nhl.test/box/200", {
                "id": 200, "gameState": "FINAL",
                "playerByGameStats": {
                    "homeTeam": {"forwards": [{"playerId": 31, "goals": 1}], "defense": []},
                    "awayTeam": {"forwards": [{"playerId": 32, "goals": 0}], "defense": []},
                },
            }),
            "pbp": report("https://nhl.test/pbp/200", {"id": 200, "plays": []}),
        },
    }
    monkeypatch.setattr(replay_postgame_grade, "NHLClient", FakeNHLClient)
    with pytest.raises(Exception, match="PBP/boxscore"):
        asyncio.run(replay_postgame_grade.grade_frozen_legs([
            {"gameId": "200", "playerId": "31"},
        ]))
