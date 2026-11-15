"""Merge independently sourced snapshots into NHL's official roster without inventing data.

No endpoint accepts a 'selected player' or scores submitted by clients. Imported records
are raw source evidence and the engine alone handles candidate elimination.
"""
import json
from .storage import record_evidence
from .goalie_zones import validate_goal_zone_evidence

KINDS = {
 'GOALIE_PROFILE','GOALIE_STARTER','PLAYER_STATUS','PLAYER_RELEASE',
 'PLAYER_DEPLOYMENT','PLAYER_GAME_LOG','PLAYER_GOAL_EVENTS',
 'PLAYER_OFFICIAL_GOALS','PLAYER_MARKET','PLAYER_FINISH_CREDIT',
 'PLAYER_PRESSURE','PLAYER_MILESTONE','PLAYER_WHO','PLAYER_TRANSFER',
 'PLAYER_CONTRADICTIONS','MATCH_CONTEXT','TEAM_COVERAGE'
}
KIND_TO_FIELD={
 'PLAYER_RELEASE':'release','PLAYER_DEPLOYMENT':'deployment',
 'PLAYER_GAME_LOG':'gameLog','PLAYER_GOAL_EVENTS':'mappedGoals',
 'PLAYER_OFFICIAL_GOALS':'officialGoalTotal','PLAYER_MARKET':'authenticMarket',
 'PLAYER_FINISH_CREDIT':'finishOwnership','PLAYER_PRESSURE':'pressure',
 'PLAYER_MILESTONE':'milestone','PLAYER_WHO':'whoAnomaly',
 'PLAYER_TRANSFER':'transferEvidence','PLAYER_CONTRADICTIONS':'contradictions'
}


def ingest(con, record):
    if record.get('kind') not in KINDS:
        raise ValueError('Unsupported evidence kind: '+str(record.get('kind')))
    if record['kind']=='GOALIE_PROFILE':
        data=record.get('payload',{})
        if data.get('goalMouthEvidence') is not None:
            validated=validate_goal_zone_evidence(data.get('goalMouthEvidence'))
            if not validated['anatomicalClaimCertified']:
                raise ValueError('G0/G3/G5 weakZones require independently certified goal-mouth baseline and contradiction review')
    if record['kind'] in ('GOALIE_PROFILE','GOALIE_STARTER'):
        if not record['payload'].get('team') or not record.get('game_id'):
            raise ValueError('Goalie source must declare game and owning team')
    if record['kind'].startswith('PLAYER_') and not record.get('player_id'):
        raise ValueError('Player evidence must include stable official player ID')
    return record_evidence(con,record)


def attach(con, snapshot, date, stage):
    """Project/confirmed remain independent. Projected does not become confirmed by reuse."""
    if stage=='WATCH':
        rows=con.execute("SELECT * FROM evidence WHERE slate_date=? AND stage IN ('OFFICIAL','PROJECTED','CONFIRMED') ORDER BY observed_at ASC",(date,)).fetchall()
    else:
        rows=con.execute("SELECT * FROM evidence WHERE slate_date=? AND stage IN (?, 'OFFICIAL') ORDER BY observed_at ASC",(date,stage)).fetchall()
    refs=[]
    for row in rows:
        kind=row['kind'];data=json.loads(row['payload'])
        if kind not in KINDS:continue
        g=next((x for x in snapshot['games'] if x['id']==row['game_id']),None)
        if not g:continue
        wrapper={'sourceUrl':row['source_url'],'observedAt':row['observed_at'],'evidenceId':row['evidence_id'],'data':data}
        if kind in ('GOALIE_PROFILE','GOALIE_STARTER'):
            team=data.get('team')
            if team not in (g['away'],g['home']):continue
            # Keep all probable/confirmed goalie branches rather than overwriting them.
            existing=g['goalies'].setdefault(team,[])
            if not any(x['data'].get('goalieId')==data.get('goalieId') and
                       x['data'].get('status')==data.get('status') for x in existing):
                existing.append(wrapper)
        elif kind=='MATCH_CONTEXT':g['context']=wrapper
        elif kind=='TEAM_COVERAGE':
            if data.get('attackingTeam') in (g['home'],g['away']):
                g['coverage'][data['attackingTeam']]=wrapper
        elif kind.startswith('PLAYER_'):
            pid=str(row['player_id'])
            for team in (g['away'],g['home']):
                roster=g.get('rosters',{}).get(team)
                if not roster:continue
                p=next((p for p in roster['data']['players'] if p['id']==pid),None)
                if not p:continue
                if kind=='PLAYER_STATUS':
                    # A projected roster report is not a confirmation.
                    if data.get('status') in ('DRESSED','CONFIRMED','PROJECTED_ACTIVE','OUT','SCRATCHED','INJURED'):
                        p['availability']=data['status']
                        p['availabilitySource']=wrapper
                else:
                    fld=KIND_TO_FIELD.get(kind)
                    if fld:p[fld]=wrapper
        refs.append(row['evidence_id'])
    snapshot['attachedEvidenceIds']=refs
    return snapshot