"""Merge independently sourced snapshots into NHL's official roster without inventing data.

No endpoint accepts a 'selected player' or scores submitted by clients. Imported records
are raw source evidence and the engine alone handles candidate elimination.
"""
import json
from .storage import record_evidence
from .goalie_zones import validate_goal_zone_evidence
from .goalie_baselines import compare_goalie_to_baseline

KINDS = {
 'GOALIE_PROFILE','GOALIE_STARTER','GOALIE_PBP_PEER_CONTEXT','PLAYER_STATUS','PLAYER_RELEASE',
 'PLAYER_DEPLOYMENT','PLAYER_GAME_LOG','PLAYER_GOAL_EVENTS','PLAYER_ZERO_ON_NET_ROUTE',
 'PLAYER_OFFICIAL_GOALS','PLAYER_MARKET','PLAYER_FINISH_CREDIT',
 'PLAYER_SEASON_HISTORY','PLAYER_PRESSURE','PLAYER_RECENT_ORIGIN','PLAYER_MILESTONE','PLAYER_WHO','PLAYER_TRANSFER',
 'PLAYER_CONTRADICTIONS','MATCH_CONTEXT','TEAM_COVERAGE'
}
OFFICIAL_COVERAGE_COMPARISONS=frozenset((
    'RECENT_OPPONENT_SHOT_ORIGIN_SHARES_AGAINST_PEER_MEDIAN',
    'RECENT_OPPONENT_SHOT_ATTEMPT_ORIGIN_RATE_PER_GAME_VS_OTHER_TEAM_MEDIAN',
))

KIND_TO_FIELD={
 'PLAYER_RELEASE':'release','PLAYER_ZERO_ON_NET_ROUTE':'zeroShotOriginProof',
 'PLAYER_DEPLOYMENT':'deployment',
 'PLAYER_GAME_LOG':'gameLog','PLAYER_GOAL_EVENTS':'mappedGoals',
 'PLAYER_OFFICIAL_GOALS':'officialGoalTotal','PLAYER_MARKET':'authenticMarket',
 'PLAYER_FINISH_CREDIT':'finishOwnership','PLAYER_SEASON_HISTORY':'seasonHistory','PLAYER_PRESSURE':'pressure',
 'PLAYER_RECENT_ORIGIN':'recentOrigin',
 'PLAYER_MILESTONE':'milestone','PLAYER_WHO':'whoAnomaly',
 'PLAYER_TRANSFER':'transferEvidence','PLAYER_CONTRADICTIONS':'contradictions'
}


def ingest(con, record):
    if record.get('kind') not in KINDS:
        raise ValueError('Unsupported evidence kind: '+str(record.get('kind')))
    if record['kind']=='GOALIE_PROFILE':
        data=record.get('payload',{})
        if data.get('goalMouthEvidence') is not None:
            if data.get('baselineGoalMouthEvidence') is None:
                raise ValueError('G0/G3/G5 goal-mouth evidence requires a pooled baseline')
            comparison=compare_goalie_to_baseline(
                data['goalMouthEvidence'],data['baselineGoalMouthEvidence'])
            declared=set(data.get('weakZones',{}))
            proven=set(comparison['weakZones'])
            if declared and not declared.issubset(proven):
                raise ValueError('Declared weakness is not separated from historical baseline')
            data['goalMouthBaselineReview']=comparison
            data['weakZones']={zone:comparison['zones'][zone] for zone in proven}
            data['strengthZones']={zone:comparison['zones'][zone] for zone in comparison['strengthZones']}
            data['sample']=comparison['goalieSample']
            data['counterevidence']={'baseline':comparison['baselineSample'],
                                     'unseparatedZones':[z for z,v in comparison['zones'].items()
                                         if v['status']!='EVIDENCED_RELATIVE_WEAKNESS']}
    if record['kind'] in ('GOALIE_PROFILE','GOALIE_STARTER'):
        if not record['payload'].get('team') or not record.get('game_id'):
            raise ValueError('Goalie source must declare game and owning team')
    if record['kind'].startswith('PLAYER_') and not record.get('player_id'):
        raise ValueError('Player evidence must include stable official player ID')
    return record_evidence(con,record)


def _attach_goalie_profile(prior, wrapper):
    """Attach one coherent goalie profile, never a fieldwise hybrid.

    A partial research result cannot replace a previously sourced complete
    profile. A later equally complete observation may replace it as a unit.
    This does not infer goalie weakness or change the starter's status.
    """
    data=wrapper['data']
    current=prior['data']
    def complete(value):
        return (isinstance(value.get('sample'), dict)
                and value.get('counterevidence') is not None
                and isinstance(value.get('weakZones'), dict)
                and isinstance(value.get('strengthZones'), dict)
                and (value.get('sourceReviewed') is True
                     or value.get('fullySourceComparedAreas', 0)>0
                     or bool(value.get('weakZones'))))
    if current.get('goalieProfileEvidenceId') and complete(current) and not complete(data):
        return False
    # Profile-specific fields are replaced together; never retain old weak
    # zones while applying a new sample or counterevidence denominator.
    profile_keys=('weakZones','strengthZones','sample','counterevidence',
                  'sourceReviewed','fullySourceComparedAreas','sourceClass',
                  'sourceType','evidenceScope','observedAreas','goalMouthEvidence',
                  'baselineGoalMouthEvidence','goalMouthBaselineReview',
                  'historicalPbpSources','historicalSampleAsOf','sourceGameIds')
    for key in profile_keys:
        current.pop(key,None)
    current.update({k:v for k,v in data.items()
                    if k not in ('goalieId','team','status')})
    current['goalieProfileSourceUrl']=wrapper['sourceUrl']
    current['goalieProfileObservedAt']=wrapper['observedAt']
    current['goalieProfileEvidenceId']=wrapper['evidenceId']
    return True


def attach(con, snapshot, date, stage):
    """Project/confirmed remain independent. Projected does not become confirmed by reuse."""
    if stage in ('WATCH','CONFIRMED'):
        # Independent projected evidence survives into the confirmed research
        # pass with its ORIGINAL label. New confirmed evidence takes precedence.
        rows=con.execute("SELECT * FROM evidence WHERE slate_date=? AND stage IN ('OFFICIAL','PROJECTED','CONFIRMED') ORDER BY observed_at ASC, rowid ASC",(date,)).fetchall()
    else:
        # PROJECTED is the skater analysis phase, not a command to throw
        # away source-confirmed GOALIE_STARTER and GOALIE_PROFILE receipts.
        # A real pre-cutoff goalie confirmation can coexist with projected
        # skater availability/deployment. Preserve the actual goalie status
        # while keeping CONFIRMED player receipts out of PROJECTED gates.
        rows=con.execute(
            """SELECT * FROM evidence WHERE slate_date=?
               AND (stage IN (?, 'OFFICIAL')
                    OR (stage='CONFIRMED' AND kind IN ('GOALIE_STARTER','GOALIE_PROFILE')))
               ORDER BY observed_at ASC, rowid ASC""",(date,stage)).fetchall()
    # A goalie profile cannot attach to a starter until the verified starter
    # branch exists. Ordered queries by timestamp alone can silently discard
    # valid earlier scouting whenever the lineup source arrives later.
    # Process identity first, then the independent profile in the same stage.
    rows=sorted(rows,key=lambda row:(0 if row['kind']=='GOALIE_STARTER' else
                   1 if row['kind']=='GOALIE_PROFILE' else 2,
                   {'OFFICIAL':0,'PROJECTED':1,'CONFIRMED':2}.get(row['stage'],0),
                   row['observed_at'], row['rowid'] if 'rowid' in row.keys() else 0))
    refs=[]
    for row in rows:
        kind=row['kind'];data=json.loads(row['payload'])
        if kind not in KINDS:continue
        g=next((x for x in snapshot['games'] if x['id']==row['game_id']),None)
        if not g:continue
        wrapper={'sourceUrl':row['source_url'],'observedAt':row['observed_at'],'evidenceId':row['evidence_id'],'data':data}
        if kind=='GOALIE_PBP_PEER_CONTEXT':
            # Same-source PBP goalie peer cohorts are G0 COMPARISON
            # supplements only. Never overwrite the authoritative goalie
            # starter/profile or promote a projected status to confirmed.
            team=data.get('team')
            pid=str(data.get('goalieId') or '')
            if team in (g['away'],g['home']) and pid:
                g.setdefault('goaliePeerContexts',{})[pid]=wrapper
        elif kind in ('GOALIE_PROFILE','GOALIE_STARTER'):
            team=data.get('team')
            if team not in (g['away'],g['home']):continue
            # Keep all probable/confirmed goalie branches rather than overwriting them.
            existing=g['goalies'].setdefault(team,[])
            if kind=='GOALIE_PROFILE':
                # An independent goalie-specific profile belongs to the SAME
                # goalie ID in every valid projected/confirmed starter branch.
                # Preserve each branch's original status and source proof.
                matched=[x for x in existing
                         if x['data'].get('goalieId')==data.get('goalieId')]
                for prior in matched:
                    _attach_goalie_profile(prior,wrapper)
                if matched:refs.append(row['evidence_id'])
                continue
            prior=next((x for x in existing
                        if x['data'].get('goalieId')==data.get('goalieId')
                        and x['data'].get('status')==data.get('status')),None)
            if kind=='GOALIE_PROFILE' and prior is None:
                # The same goalie does not lose an independent vulnerability
                # report when EXPECTED becomes CONFIRMED. Never change the
                # starter-status field based on a profile.
                prior=next((x for x in existing
                            if x['data'].get('goalieId')==data.get('goalieId')),None)
            if prior is None:
                if kind=='GOALIE_PROFILE':
                    # Scouting cannot independently establish who is starting.
                    continue
                existing.append(wrapper)
            elif kind=='GOALIE_STARTER' and data.get('projectedPreferred') is True:
                # Same goalie/expected-status identity existed from another
                # lineup source. Preserve the original source and attach the
                # independent NHL.com projected preference as its own receipt.
                prior['data']['projectedPreferred']=True
                prior['data'].setdefault('projectedPreferenceSources',[])
                if wrapper['sourceUrl'] not in prior['data']['projectedPreferenceSources']:
                    prior['data']['projectedPreferenceSources'].append(wrapper['sourceUrl'])
                # Merge separately observed, dated, first-off eyewitness
                # evidence into this SAME official goalie ID only. The
                # starter remains EXPECTED, never auto-confirmed. A stale
                # other-date report cannot defeat source disagreements.
                if (data.get('datedEyewitnessMorningSkateFirstOff') is True
                        and data.get('sourceReportDate')==date
                        and data.get('status')=='EXPECTED'):
                    prior['data']['datedEyewitnessMorningSkateFirstOff']=True
                    prior['data']['sourceReportDate']=date
                    prior['data'].setdefault('morningSkateSourceUrls',[])
                    if wrapper['sourceUrl'] not in prior['data']['morningSkateSourceUrls']:
                        prior['data']['morningSkateSourceUrls'].append(wrapper['sourceUrl'])
            elif kind=='GOALIE_PROFILE':
                # Profile has its own provenance; keep starter source separate.
                # Only a real source-linked profile may provide weakness claims.
                prior['data'].update({k:v for k,v in data.items()
                    if k not in ('goalieId','team','status')})
                prior['data']['goalieProfileSourceUrl']=wrapper['sourceUrl']
                prior['data']['goalieProfileObservedAt']=wrapper['observedAt']
                prior['data']['goalieProfileEvidenceId']=wrapper['evidenceId']
        elif kind=='MATCH_CONTEXT':g['context']=wrapper
        elif kind=='TEAM_COVERAGE':
            if data.get('attackingTeam') in (g['home'],g['away']):
                attack=data['attackingTeam']
                current=g['coverage'].get(attack)
                # A changed, source-backed G9 methodology must replace
                # the older official coverage snapshot. Hard-coding only the
                # previous comparison string silently kept stale red/green
                # zones attached even though the new receipt was persisted.
                is_official=bool(
                    data.get('sourceType')=='OFFICIAL_HISTORICAL_NHL_PLAY_BY_PLAY'
                    or data.get('comparison') in OFFICIAL_COVERAGE_COMPARISONS)
                current_official=bool(current and (
                    current['data'].get('sourceType')=='OFFICIAL_HISTORICAL_NHL_PLAY_BY_PLAY'
                    or current['data'].get('comparison') in OFFICIAL_COVERAGE_COMPARISONS))
                # Independently mapped actual recent NHL allowed shots outrank
                # a MoneyPuck season danger-share aggregate for G9 lane proof.
                if current_official and not is_official:
                    current['data'].setdefault('seasonDangerSupplement',wrapper)
                    continue
                if is_official and current and not current_official:
                    wrapper['data'].setdefault('seasonDangerSupplement',current)
                elif is_official and current and current_official:
                    # Retain the prior source revision for audit while making
                    # the newest official coverage receipt authoritative.
                    wrapper['data'].setdefault('previousCoverageRevision',current)
                g['coverage'][attack]=wrapper
        elif kind.startswith('PLAYER_'):
            pid=str(row['player_id'])
            for team in (g['away'],g['home']):
                roster=g.get('rosters',{}).get(team)
                if not roster:continue
                p=next((p for p in roster['data']['players'] if str(p.get('id'))==pid),None)
                if not p:continue
                if kind=='PLAYER_STATUS':
                    # A projected roster report is not a confirmation.
                    if data.get('status') in ('DRESSED','CONFIRMED','PROJECTED_ACTIVE','OUT','SCRATCHED','INJURED'):
                        # Projected activity cannot overwrite a verified
                        # dressed/confirmed official roster status.
                        prior_status=p.get('availability')
                        if (data['status']=='PROJECTED_ACTIVE' and
                            prior_status in ('DRESSED','CONFIRMED','OUT','SCRATCHED','INJURED')):
                            p.setdefault('availabilityAlternatives',[]).append(wrapper)
                        else:
                            p['availability']=data['status']
                            p['availabilitySource']=wrapper
                else:
                    fld=KIND_TO_FIELD.get(kind)
                    if fld:
                        if kind=='PLAYER_DEPLOYMENT' and p.get(fld):
                            # A later generic projected lineup must never
                            # erase an independently verified confirmed unit.
                            previous=p[fld]
                            prior=previous.get('data',{})
                            if (prior.get('status')=='CONFIRMED' and
                                data.get('status')!='CONFIRMED'):
                                prior.setdefault('projectedAlternatives',[]).append(wrapper)
                                continue
                            # Keep contradictory projected assignments visible
                            # rather than silently replacing the earlier one.
                            if (prior.get('status')=='PROJECTED' and
                                data.get('status')=='PROJECTED' and
                                prior.get('EV') and data.get('EV') and
                                prior.get('EV')!=data.get('EV')):
                                prior.setdefault('conflictingProjectedAssignments',[]).append(wrapper)
                                p['deploymentConflict']=True
                                continue
                        if kind=='PLAYER_FINISH_CREDIT' and p.get(fld):
                            previous=p[fld]
                            prior=previous.get('data',{})
                            # Two different evidence windows are not two
                            # conflicting goal claims. Preserve a verified
                            # positive recent PBP/boxscore credit, and let a
                            # positive NHL EDGE season credit establish OWN
                            # goals when the recent eight-game sample was 0.
                            if prior.get('recipient') is True and data.get('recipient') is not True:
                                previous['data'].setdefault('alternateSample',wrapper)
                                continue
                            if (prior.get('recipient') is True and
                                data.get('recipient') is True and
                                prior.get('scope')=='SAMPLED_RECENT_TEAM_GAMES_ONLY' and
                                data.get('scope')=='CURRENT_SEASON_GOALS_FROM_MEASURED_AREAS'):
                                previous['data'].setdefault('seasonGoalSupplement',wrapper)
                                continue
                            if (data.get('recipient') is True and
                                prior.get('recipient') is not True):
                                wrapper['data'].setdefault('recentGameLogSupplement',previous)
                        if kind=='PLAYER_PRESSURE' and p.get(fld):
                            # Favor actual dated appearance shots (list includes
                            # real zero-shot games) over a pooled historical shot
                            # total or MoneyPuck season aggregate.
                            current=p[fld]
                            old_shots=current.get('data',{}).get('recentAppearanceShots')
                            new_shots=data.get('recentAppearanceShots')
                            if isinstance(old_shots,list) and not isinstance(new_shots,list):
                                current['data'].setdefault('shotSampleSupplement',wrapper)
                                continue
                            if (current.get('data',{}).get('evidenceType')==
                                'OFFICIAL_HISTORICAL_SHOT_EVENTS'
                                and data.get('evidenceType')==
                                    'SEASON_AGGREGATE_NOT_RECENT_APPEARANCES'):
                                current['data'].setdefault('seasonAggregate',wrapper)
                                continue
                        p[fld]=wrapper
        refs.append(row['evidence_id'])
    snapshot['attachedEvidenceIds']=refs
    return snapshot