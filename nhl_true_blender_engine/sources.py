"""Official NHL feed connector and separate supplemental-evidence adapter.

The NHL public Web API is unofficial/undocumented and may rate-limit or deny hosts.
A failed feed never becomes a projected lineup or an invented G0 weakness.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import quote
from typing import Optional
import httpx
from .storage import record_evidence

NHL = 'https://api-web.nhle.com/v1'


def time_utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class SourceUnavailable(RuntimeError):pass


class NHLClient:
    def __init__(self, client: Optional[httpx.AsyncClient]=None):
        self._external = client is not None
        self._client = client or httpx.AsyncClient(timeout=18, follow_redirects=True,
                        headers={'User-Agent':'NHL-True-Blender/1.0 (+evidence-grounded NHL slate tracking)',
                                 'Accept':'application/json'})

    async def close(self):
        if not self._external: await self._client.aclose()

    async def get(self, route):
        url = NHL+'/'+route.lstrip('/')
        last=None
        for retry in range(3):
            try:
                r=await self._client.get(url)
                r.raise_for_status()
                value=r.json()
                return {'url':url,'observedAt':time_utc(),'data':value}
            except (httpx.TimeoutException,httpx.TransportError,httpx.HTTPStatusError,
                    ValueError) as e:
                last=e
                if retry<2:await asyncio.sleep(0.4*(retry+1))
        raise SourceUnavailable(f'Official NHL endpoint unavailable: {url}: {last}')

    async def score(self, date):return await self.get(f'score/{date}')
    async def roster(self, team):return await self.get(f'roster/{quote(team)}/current')
    async def boxscore(self, game_id):return await self.get(f'gamecenter/{game_id}/boxscore')
    async def play_by_play(self, game_id):return await self.get(f'gamecenter/{game_id}/play-by-play')
    async def game_log(self, player_id, season):
        return await self.get(f'player/{int(player_id)}/game-log/{season}/2')


def normalize_games(payload, date):
    raw=payload['data'].get('games')
    if not isinstance(raw,list):raise SourceUnavailable('NHL score feed omitted games array')
    out=[]
    for g in raw:
        away=g.get('awayTeam',{}).get('abbrev')
        home=g.get('homeTeam',{}).get('abbrev')
        t=g.get('startTimeUTC')
        if not away or not home or not t or g.get('id') is None:
            raise SourceUnavailable('NHL official game missing ID/teams/start time')
        out.append({'id':str(g['id']),'date':date,'away':away,'home':home,
                    'startUTC':t,'gameState':g.get('gameState') or 'UNKNOWN',
                    'officialSourceUrl':payload['url'],'officialObservedAt':payload['observedAt'],
                    'goalies':{},'rosters':{},'context':{},'coverage':{}})
    return out


def roster_as_evidence(payload, team):
    r=payload['data'];ps=[]
    for group in ('forwards','defensemen'):
        for p in r.get(group,[]):
            first=p.get('firstName',{}).get('default',''); last=p.get('lastName',{}).get('default','')
            ps.append({'id':str(p['id']),'name':(first+' '+last).strip(),
                       'jersey':p.get('sweaterNumber'),'position':p.get('positionCode') or ('D' if group=='defensemen' else ''),
                       'availability':'UNVERIFIED',
                       'note':'Official current roster; not dressed/EV/PP confirmation.'})
    goalies=[]
    for p in r.get('goalies',[]):
        first=p.get('firstName',{}).get('default',''); last=p.get('lastName',{}).get('default','')
        goalies.append({'id':str(p['id']),'name':(first+' '+last).strip()})
    return {'sourceUrl':payload['url'],'observedAt':payload['observedAt'],
            'data':{'team':team,'players':ps,'goalies':goalies,'sourceType':'OFFICIAL_CURRENT_ROSTER_NOT_DRESSED'}}


async def official_slate(client, date, con=None):
    """Collect actual scheduled games and all 32(?) game-team rosters, not goalie guesses.
    Every matchup gets two attack directions from the selector afterwards."""
    raw=await client.score(date)
    games=normalize_games(raw,date)
    teams=sorted({team for g in games for team in (g['away'],g['home'])})
    sem=asyncio.Semaphore(5)
    async def one(team):
        async with sem:
            try:return team,roster_as_evidence(await client.roster(team),team),None
            except SourceUnavailable as exc:return team,None,str(exc)
    responses=await asyncio.gather(*(one(t) for t in teams))
    refs={t:v for t,v,_ in responses if v}
    errs=[{'team':t,'error':e} for t,_,e in responses if e]
    for g in games:
        g['rosters']={t:refs.get(t) for t in (g['away'],g['home'])}
    if con:
        record_evidence(con,{'evidence_id':f'official-schedule-{date}-'+hashlib.sha256(json.dumps(raw['data'],sort_keys=True).encode()).hexdigest()[:16],
            'slate_date':date,'stage':'OFFICIAL','kind':'GAME_SCHEDULE','source_url':raw['url'],
            'observed_at':raw['observedAt'],'payload':raw['data']})
        for t,v in refs.items():
            record_evidence(con,{'evidence_id':f'official-roster-{date}-{t}-'+hashlib.sha256(json.dumps(v['data'],sort_keys=True).encode()).hexdigest()[:16],
                'slate_date':date,'stage':'OFFICIAL','kind':'TEAM_CURRENT_ROSTER','source_url':v['sourceUrl'],
                'observed_at':v['observedAt'],'payload':v['data']})
    return {'date':date,'games':games,'collectionErrors':errs,'officialSource':raw['url']}


def credited_goals_from_pbp(payload):
    """Strict official goal events. No disallowed or shootout goal credit."""
    plays=payload['data'].get('plays')
    if not isinstance(plays,list):raise SourceUnavailable('NHL PBP lacks plays')
    counts={}
    source_goal_ids=[]
    for p in plays:
        if p.get('typeDescKey')!='goal':continue
        desc=p.get('periodDescriptor') or {}
        if desc.get('periodType')=='SO':continue
        details=p.get('details') or {}
        scorer=details.get('scoringPlayerId')
        if scorer is None:raise SourceUnavailable('NHL goal event without scoringPlayerId')
        key=str(scorer)
        counts[key]=counts.get(key,0)+1
        source_goal_ids.append(p.get('eventId'))
    return counts,source_goal_ids


async def official_final_grade(client, con, slate_date):
    from .storage import get_card, grade_frozen_card
    card=get_card(con,slate_date)
    if not card: raise ValueError('Cannot grade; this slate has no original issued G18')
    scores=await client.score(slate_date)
    games=normalize_games(scores,slate_date)
    if not games: raise SourceUnavailable('No official games returned for date')
    # Only the three original LOCKED Core matchups determine when this card
    # can be graded. Other late-start games in the five-game NHL slate must
    # not delay the source-verified result for an already final Core.
    # Never grade any individual Core leg from a nonfinal game.
    by_game={str(g['id']):g for g in games}
    selected_game_ids={str(l['gameId']) for l in card['current_legs']}
    missing=sorted(selected_game_ids-set(by_game))
    if missing:
        raise SourceUnavailable('Original frozen Core game(s) missing from NHL official schedule: '+', '.join(missing))
    pending=sorted(gid for gid in selected_game_ids
                   if by_game[gid]['gameState'] not in ('OFF','FINAL'))
    if pending:
        return {'grade':None,'status':'CORE_MATCHUPS_NOT_ALL_OFFICIALLY_FINAL',
                'coreGames':len(selected_game_ids),
                'officiallyFinalCoreGames':len(selected_game_ids)-len(pending),
                'pendingCoreGameIds':pending,
                'nonCoreGamesDoNotBlockGrading':True}
    verified={};sources=[scores['url']]
    for leg in card['current_legs']:
        gid=str(leg['gameId'])
        if gid not in by_game:
            raise ValueError('Frozen leg game not in official schedule: '+gid)
        pbp=await client.play_by_play(gid)
        counts,source_events=credited_goals_from_pbp(pbp)
        box=await client.boxscore(gid)
        official_player_counts={}
        stats=box['data'].get('playerByGameStats') or {}
        for team in ('homeTeam','awayTeam'):
            for pos in ('forwards','defense'):
                for player in (stats.get(team) or {}).get(pos,[]):
                    if player.get('playerId') is not None:
                        official_player_counts[str(player['playerId'])]=player.get('goals')
        if not official_player_counts:
            raise SourceUnavailable('NHL boxscore skater goal totals unavailable for '+gid)
        player_id=str(leg['playerId'])
        # NHL boxscores list dressed skaters only. A frozen scorer who was
        # scratched will therefore be absent from playerByGameStats. Official
        # PBP is the authoritative credited-goal event ledger: absence from
        # the boxscore is a valid zero ONLY when PBP also records zero goals.
        # If PBP credits a goal to an absent boxscore player, fail closed.
        credited_from_pbp=int(counts.get(player_id,0))
        if player_id not in official_player_counts:
            if credited_from_pbp != 0:
                raise SourceUnavailable('NHL PBP credited frozen player absent from official boxscore '+gid+' / '+player_id)
            credited=0
        else:
            credited=int(official_player_counts[player_id])
            if credited_from_pbp!=credited:
                raise SourceUnavailable('NHL PBP and official boxscore goal credit disagree '+gid+' / '+player_id)
        verified[(gid,player_id)]=credited
        sources.extend([pbp['url'],box['url']])
    return {'grade':grade_frozen_card(con,slate_date,verified,sources,True),
            'status':'GRADED_OFFICIAL_GOAL_EVENTS'}


async def collect_watch(client, con, date, snapshot):
    """Quiet initial baseline; only source-verified pre-puck changes become alerts."""
    from .storage import record_watch, encode
    import hashlib
    import json
    from datetime import datetime, timezone
    baseline_count=0; changes=0; skipped=0
    now=datetime.now(timezone.utc)
    for g in snapshot.get('games',[]):
        start=datetime.fromisoformat(g['startUTC'].replace('Z','+00:00'))
        if g['gameState'] in ('LIVE','CRIT','OFF','FINAL') or now>=start:
            skipped+=1;continue
        reports=[]
        for team in (g['away'],g['home']):
            goalies=g.get('goalies',{}).get(team,[])
            if goalies:
                reports.append({'team':team,'kind':'goalie_status',
                    'facts':sorted([{'goalieId':x['data'].get('goalieId'),
                                     'status':x['data'].get('status'),
                                     'supersedesGoalieId':x['data'].get('supersedesGoalieId')}
                                    for x in goalies],key=lambda x:str(x['goalieId'])),
                    'source':goalies[-1]['sourceUrl']})
            roster=g.get('rosters',{}).get(team)
            if roster and roster.get('data'):
                players=roster['data'].get('players',[])
                affected=[{'playerId':p['id'],'availability':p['availability'],
                           'role':p.get('deployment',{}).get('data',{})}
                          for p in players if p.get('availabilitySource') or p.get('deployment')]
                if affected:
                    cited=[(p.get('deployment') or p.get('availabilitySource'))
                           for p in players if p.get('availabilitySource') or p.get('deployment')]
                    reports.append({'team':team,'kind':'role_or_availability',
                        'facts':sorted(affected,key=lambda v:v['playerId']),
                        'source':cited[-1]['sourceUrl']})
        for report in reports:
            prior=con.execute("SELECT payload FROM evidence WHERE slate_date=? AND game_id=? AND kind='WATCH_COMPARISON_BASELINE' ORDER BY observed_at DESC LIMIT 200",
                              (date,str(g['id']))).fetchall()
            previous=None
            for row in prior:
                item=json.loads(row['payload'])
                if item.get('kind')==report['kind'] and item.get('team')==report['team']:
                    previous=item;break
            new_payload={'team':report['team'],'kind':report['kind'],
                         'facts':report['facts']}
            if previous==new_payload:continue
            h=hashlib.sha256(encode(new_payload).encode()).hexdigest()[:18]
            receipt_id=f"watch-{date}-{g['id']}-{report['team']}-{report['kind']}-{h}"
            record_evidence(con,{'evidence_id':receipt_id,'slate_date':date,
                'stage':'WATCH','game_id':str(g['id']),'kind':'WATCH_COMPARISON_BASELINE',
                'source_url':report['source'],'observed_at':time_utc(),'payload':new_payload})
            if not previous:
                baseline_count+=1
                continue
            event_id='change-'+receipt_id
            category=report['kind']
            gates=['G0','G3','G5','G17'] if category=='goalie_status' else ['G2','G6','G10.5','G17']
            if record_watch(con,{'event_id':event_id,'slate_date':date,
                'game_id':str(g['id']),'category':category,'old':previous,'new':new_payload,
                'source_url':report['source'],'dependent_gates':gates},
                g['startUTC'],now=now):changes+=1
    return {'initialBaselinesSavedWithoutAlert':baseline_count,
            'verifiedMaterialChanges':changes,'startedGamesSkipped':skipped}