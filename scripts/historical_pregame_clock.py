"""Pregame research windows; every matchup freezes at its own puck drop."""
from datetime import datetime, timedelta


def game_deadline(game):
    value=game.get('startTimeUTC') or game.get('startUTC')
    start=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if start.tzinfo is None:
        raise ValueError('Official game start requires a timezone')
    return start-timedelta(minutes=5)


def first_issuance_windows(games):
    """Try dated pregame windows until a first Core is issued, never repick it.

    Earlier games become ineligible at puck drop. A later first issuance
    still needs the original slate's complete Core size from unstarted games.
    """
    if not games:
        return []
    deadlines=[game_deadline(g) for g in games]
    required=2 if len(games)==2 else 3
    return sorted({min(deadlines)} | {
        t for t in deadlines if sum(d>=t for d in deadlines)>=required})
