"""Export independently source-verified Core and run JSON for GitHub Pages.

GitHub Actions commits state/site_cards and state/site_runs. The separate
Deploy Pages workflow packages their authoritative result in
site/data/latest.json. This transport never picks or substitutes scorers.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from nhl_true_blender_engine.engine import MASTER, OVERLAY
from nhl_true_blender_engine.storage import fingerprint

class PublicationConflict(RuntimeError):
    pass

def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)

def export_run(con, slate_date, stage, result, root='state'):
    root = Path(root)
    card = result.get('card')
    status_path = root / 'site_runs' / f'{slate_date}.json'
    status = {
        'slateDate':slate_date, 'stage':stage,
        'runner':'GITHUB_ACTIONS_AUTONOMOUS',
        'updatedUTC':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'games':result.get('games',0),
        'g0Directions':result.get('g0Directions',0),
        'g0Complete':result.get('g0Complete',0),
        'eligibleSkaterRows':result.get('eligibleSkaterRows',0),
        'gateRows':result.get('gateRows',0),
        'missingByGate':result.get('missingByGate',{}),
        'errors':result.get('errors',[])[:20],
        'cardSavedByEngine':bool(card),
        'publishedToSite':False,
        'edgeSourceCoverage':result.get('edgeSourceCoverage',{}),
        'lineupSourceCoverage':result.get('lineupSourceCoverage',{}),
        'g0RinkOriginResearch':result.get('g0RinkOriginResearch',[]),
        'anatomicalEvidenceMisrepresented':False,
        'officialBoxscoreCoverage':result.get('officialBoxscoreCoverage',{}),
        'officialDefenseCoverage':result.get('officialDefenseCoverage',{}),
        'firstNonpassingGateAudit':result.get('firstNonpassingGateAudit',{}),
    }
    if not card:
        _write(status_path,status)
        return status
    legs = card.get('current_legs') or []
    required_count = 2 if result.get('games')==2 else 3
    if len(legs)!=required_count or len({str(x.get('gameId')) for x in legs})!=required_count:
        raise PublicationConflict('Invalid G18 count or duplicate game')
    if card.get('fingerprint')!=fingerprint(legs):
        raise PublicationConflict('G18 card fingerprint mismatches its saved recipients')
    if result.get('g0Directions',0) < result.get('games',0):
        raise PublicationConflict('G0 game scan incomplete')
    required=set(MASTER+OVERLAY)
    for leg in legs:
        game_id, player_id = str(leg['gameId']),str(leg['playerId'])
        rows=con.execute("""SELECT gate, disposition, details FROM gates
               WHERE slate_date=? AND stage=? AND game_id=? AND player_id=?""",
               (slate_date,stage,game_id,player_id)).fetchall()
        trace={x['gate']:x for x in rows}
        if set(trace)!=required or any(x['disposition']!='PASS' for x in rows):
            raise PublicationConflict('Incomplete or nonpassing full G0-G18 and overlay: '+game_id+'/'+player_id)
        g0=json.loads(trace['G0']['details'])['evidence']
        if leg.get('opposingGoalieId') and str(g0.get('targetGoalie'))!=str(leg['opposingGoalieId']):
            raise PublicationConflict('G0 starter branch does not match final recipient')
        if any(not leg.get(k) for k in ('player','path','startUTC','sourceIds')):
            raise PublicationConflict('Recipient source or game-time field missing')
        if leg['path'] not in ('PRIMARY','TRANSFER','WHO'):
            raise PublicationConflict('Unsupported scorer path label')
    payload={
        'slateDate':slate_date,'cardId':card['card_id'],
        'stage':card['stage'],'status':'G18_SOURCE_VERIFIED',
        'source':'GITHUB_ACTIONS_FULL_GATE_MATRIX','verified':True,
        'fingerprint':card['fingerprint'],'revision':card['revision'],
        'originalFingerprint':fingerprint(card['initial_legs']),
        'legsJson':json.dumps(legs,sort_keys=True),
        'gradeJson':json.dumps(card.get('grade') or {}),
        'auditJson':'',
        'provenance':'Independent scheduled NHL G0-G18 and overlay with source-backed recipient evidence',
        'gateRows':result.get('gateRows'),
        'g0Directions':result.get('g0Directions'),
        'eligibleSkaterRows':result.get('eligibleSkaterRows'),
    }
    path=root/'site_cards'/f'{slate_date}.json'
    if path.exists():
        old=json.loads(path.read_text(encoding='utf-8'))
        if old.get('cardId')!=payload['cardId']:
            raise PublicationConflict('Different authoritative card ID already published')
        if old.get('fingerprint')!=payload['fingerprint']:
            versions=con.execute('''SELECT rationale FROM card_versions
                  WHERE slate_date=? AND revision>? ORDER BY revision''',
                  (slate_date,int(old.get('revision',1)))).fetchall()
            if not versions or not all(
                    json.loads(x['rationale']).get('type')=='GATE_VALIDATED_REPLACEMENT'
                    for x in versions):
                raise PublicationConflict('Scorer replacement missing verified G10.5/G17 version audit')
        order={'PROJECTED':0,'MIXED':1,'CONFIRMED':2}
        if order.get(payload['stage'],-1)<order.get(old.get('stage'),-1):
            raise PublicationConflict('Cannot demote already confirmed official card')
    _write(path,payload)
    status.update(publishedToSite=True,cardId=payload['cardId'],
                  fingerprint=payload['fingerprint'],cardPath=str(path))
    _write(status_path,status)
    return status
