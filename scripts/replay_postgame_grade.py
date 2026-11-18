"""Official frozen-leg grading with NHL boxscore/play-by-play reconciliation."""
from nhl_true_blender_engine.sources import NHLClient, credited_goals_from_pbp, SourceUnavailable


async def grade_frozen_legs(legs):
    """Grade exact frozen IDs; distinguish dressed skaters from absent skaters."""
    keys = [(str(leg['gameId']), str(leg['playerId'])) for leg in legs]
    if not keys:
        return {'status': 'NO_CORE', 'playerResults': []}
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate replay leg')
    if len({game_id for game_id, _ in keys}) != len(keys):
        raise ValueError('Historical Core contains more than one leg from a game')

    client = NHLClient()
    results = []
    sources = []
    try:
        for game_id, player_id in keys:
            box_report = await client.boxscore(game_id)
            box = box_report['data']
            if str(box.get('id')) != game_id or box.get('gameState') not in ('FINAL', 'OFF'):
                raise SourceUnavailable(f'Box score is not final or game ID does not match: {game_id}')

            pbp_report = await client.play_by_play(game_id)
            pbp = pbp_report['data']
            pbp_id = pbp.get('id')
            if pbp_id is not None and str(pbp_id) != game_id:
                raise SourceUnavailable(f'Play-by-play game ID does not match: {game_id}')
            counts, event_ids = credited_goals_from_pbp(pbp_report)

            stats = box.get('playerByGameStats') or {}
            skaters = []
            for side in ('homeTeam', 'awayTeam'):
                for group in ('forwards', 'defense'):
                    skaters.extend((stats.get(side) or {}).get(group) or [])
            if not skaters:
                raise SourceUnavailable(f'Empty official skater list: {game_id}')

            by_player = {}
            for player in skaters:
                if player.get('playerId') is None:
                    raise SourceUnavailable(f'Official boxscore skater missing player ID: {game_id}')
                pid = str(player['playerId'])
                goals = player.get('goals')
                if pid in by_player:
                    raise SourceUnavailable(f'Duplicate skater in box score: {game_id}/{pid}')
                if type(goals) is not int or goals < 0:
                    raise SourceUnavailable(f'Invalid official boxscore goal count: {game_id}/{pid}')
                by_player[pid] = player

            # Reconcile every credited scorer and every dressed skater. A
            # selected player's absence is recorded as non-participation only
            # when the NHL PBP independently confirms zero credited goals.
            for scorer_id, pbp_goals in counts.items():
                if scorer_id not in by_player:
                    raise SourceUnavailable(
                        f'PBP scorer absent from official boxscore: {game_id}/{scorer_id}')
                if by_player[scorer_id]['goals'] != pbp_goals:
                    raise SourceUnavailable(
                        f'PBP/boxscore scorer mismatch: {game_id}/{scorer_id}')
            for pid, player in by_player.items():
                if player['goals'] != counts.get(pid, 0):
                    raise SourceUnavailable(
                        f'PBP/boxscore goal-total mismatch: {game_id}/{pid}')

            selected = by_player.get(player_id)
            if selected is None:
                goals = int(counts.get(player_id, 0))
                if goals:
                    raise SourceUnavailable(
                        f'PBP credits absent selected player: {game_id}/{player_id}')
                participation = 'NOT_LISTED_IN_OFFICIAL_BOXSCORE'
                player_name = None
            else:
                goals = selected['goals']
                participation = 'LISTED_AS_DRESSED_SKATER'
                player_name = selected.get('name') or selected.get('firstName')

            results.append({
                'gameId': game_id,
                'playerId': player_id,
                'player': player_name,
                'participation': participation,
                'goals': goals,
                'result': 'HIT' if goals else 'MISS',
                'officialPbpGoalEvents': event_ids,
                'boxscoreSourceUrl': box_report['url'],
                'playByPlaySourceUrl': pbp_report['url'],
            })
            sources.extend([box_report['url'], pbp_report['url']])
    finally:
        await client.close()

    hits = sum(row['result'] == 'HIT' for row in results)
    return {
        'status': 'GRADED_FINAL_BOXSCORE_AND_PBP',
        'hits': hits,
        'legs': len(keys),
        'result': 'WIN' if hits == len(keys) else 'LOSS',
        'playerResults': results,
        'officialSources': sorted(set(sources)),
        'boxscoreAndPbpReconciled': True,
        'nonparticipantsSeparatedFromDressedZeroGoalPlayers': True,
    }
