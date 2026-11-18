from nhl_true_blender_engine.sources import NHLClient


async def grade_frozen_legs(legs):
    """Grade selected game/player IDs against final NHL box scores."""
    keys = [(str(leg['gameId']), str(leg['playerId'])) for leg in legs]
    if not keys:
        return {'status': 'NO_CORE', 'playerResults': []}
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate replay leg')
    client = NHLClient()
    results = []
    try:
        for game_id, player_id in keys:
            report = await client.boxscore(game_id)
            box = report['data']
            if str(box.get('id')) != game_id or box.get('gameState') not in ('FINAL', 'OFF'):
                raise ValueError(f'Box score is not final or game ID does not match: {game_id}')
            stats = box['playerByGameStats']
            skaters = [p for side in ('homeTeam', 'awayTeam')
                       for group in ('forwards', 'defense')
                       for p in stats[side][group]]
            if not skaters:
                raise ValueError(f'Empty official skater list: {game_id}')
            matches = [p for p in skaters if str(p['playerId']) == player_id]
            if len(matches) > 1:
                raise ValueError(f'Duplicate skater in box score: {player_id}')
            goals = matches[0]['goals'] if matches else None
            if matches and (type(goals) is not int or goals < 0):
                raise ValueError(f'Invalid official goal count: {player_id}')
            results.append({'gameId': game_id, 'playerId': player_id, 'goals': goals,
                            'result': ('NOT_IN_BOXSCORE' if goals is None else
                                       'HIT' if goals else 'MISS'),
                            'sourceUrl': report['url']})
    finally:
        await client.close()
    hits = sum(row['result'] == 'HIT' for row in results)
    return {'status': 'GRADED_FINAL_BOXSCORES', 'hits': hits, 'legs': len(keys),
            'notInBoxscore': sum(row['goals'] is None for row in results),
            'result': 'WIN' if hits == len(keys) else 'LOSS', 'playerResults': results}
