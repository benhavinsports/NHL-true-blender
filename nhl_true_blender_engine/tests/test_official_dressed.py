"""Do not mistake generic NHL rosters or partial future game feeds for dress."""
import unittest

from nhl_true_blender_engine.official_dressed import certified_dressed_ids

URL = "https://api-web.nhle.com/v1/gamecenter/2026020346/play-by-play"


def game():
    return {
        "id": "2026020346", "away": "COL", "home": "UTA",
        "startUTC": "2026-11-19T03:00:00Z", "gameState": "FUT",
        "rosters": {
            "COL": {"data": {"players": [{"id": str(100 + i)} for i in range(18)],
                             "goalies": [{"id": "199"}]}},
            "UTA": {"data": {"players": [{"id": str(200 + i)} for i in range(18)],
                             "goalies": [{"id": "299"}]}}
        }
    }


def source():
    ids = list(range(100, 118)) + [199] + list(range(200, 218)) + [299]
    return {"url": URL, "observedAt": "2026-11-19T02:31:00Z",
            "data": {"id": 2026020346, "gameState": "PRE",
                     "rosterSpots": [{"playerId": i} for i in ids]}}


class OfficialPregameDressedTest(unittest.TestCase):
    def test_pregame_complete_game_roster_is_game_dressed_evidence(self):
        ids, status = certified_dressed_ids(game(), source())
        self.assertEqual(status, "OFFICIAL_PREPUCK_DRESSED_ROSTER_VERIFIED")
        self.assertEqual(len(ids["COL"]), 18)
        self.assertEqual(len(ids["UTA"]), 18)

    def test_official_landing_can_verify_complete_roster_before_puck(self):
        raw=source()
        raw["url"]="https://api-web.nhle.com/v1/gamecenter/2026020346/landing"
        ids,status=certified_dressed_ids(game(),raw)
        self.assertEqual(status,"OFFICIAL_PREPUCK_DRESSED_ROSTER_VERIFIED")
        self.assertEqual(len(ids["COL"]),18)

    def test_official_boxscore_roster_spots_are_source_checked(self):
        raw=source()
        raw["url"]="https://api-web.nhle.com/v1/gamecenter/2026020346/boxscore"
        self.assertEqual(certified_dressed_ids(game(),raw)[1],
                         "OFFICIAL_PREPUCK_DRESSED_ROSTER_VERIFIED")
        raw["data"]["rosterSpots"] = []
        self.assertIsNone(certified_dressed_ids(game(),raw)[0])

    def test_arbitrary_external_roster_url_cannot_claim_game_dressed(self):
        raw=source()
        raw["url"]="https://example.com/gamecenter/2026020346/landing"
        self.assertEqual(certified_dressed_ids(game(),raw)[1],
                         "NOT_OFFICIAL_GAMECENTER_SOURCE")

    def test_current_roster_without_prepuck_spots_does_not_confirm(self):
        raw = source()
        raw["data"]["rosterSpots"] = []
        ids, status = certified_dressed_ids(game(), raw)
        self.assertIsNone(ids)
        self.assertEqual(status, "PREPUCK_GAME_ROSTER_NOT_PUBLISHED")

    def test_late_observation_rejected(self):
        raw = source()
        raw["observedAt"] = "2026-11-19T03:02:00Z"
        self.assertIsNone(certified_dressed_ids(game(), raw)[0])

    def test_started_game_rejected(self):
        raw = source()
        raw["data"]["gameState"] = "LIVE"
        self.assertIsNone(certified_dressed_ids(game(), raw)[0])

    def test_wrong_game_rejected(self):
        raw = source()
        raw["data"]["id"] = 2026020345
        self.assertIsNone(certified_dressed_ids(game(), raw)[0])

    def test_partial_one_team_rejected(self):
        raw = source()
        raw["data"]["rosterSpots"] = raw["data"]["rosterSpots"][:19]
        self.assertIsNone(certified_dressed_ids(game(), raw)[0])

    def test_unmatched_player_id_rejected(self):
        raw = source()
        raw["data"]["rosterSpots"][0]["playerId"] = 999
        self.assertIsNone(certified_dressed_ids(game(), raw)[0])


if __name__ == "__main__":
    unittest.main()
