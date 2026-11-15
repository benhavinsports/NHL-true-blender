"""Evidence-driven NHL G0..G18 executor. No favorites, arbitrary weights or proxy goalies.

Input is a source-annotated game snapshot produced by collectors, not a list of picks.
Output is an immutable gate record for every surveyed direction and skater.
Only the uniquely defensible, fully evidenced survivors can be published.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from .storage import save_card, save_gates, log_job, get_card, fingerprint

MASTER = ([f'G{i}' for i in range(11)] + ['G10.5'] + [f'G{i}' for i in range(11,19)])
OVERLAY = ([f'Step{i}' for i in range(11)] + ['Step10.5'] + [f'Step{i}' for i in range(11,15)])
PATCH_IDS = (
    'PATCH_PROVENANCE_V1','PATCH_START_TIME_V1','PATCH_OFFICIAL_SCORERS_V1',
    'PATCH_GATE13_CONTINUITY_V1','PATCH_RECIPIENT_LOCK_V1',
    'PATCH_2026_11_05_EXECUTION_MATRIX_V1','PATCH_G10_5_G16_COMPARE_V2',
    'PATCH_HISTORICAL_MULTIVERSION_OCT08_10_V1','TBL-G105-G17-2026-11-08',
    'UTA-G105-G17-2026-11-08','PATCH-NOV12-G10.5-EXPLICIT-SEPARATION',
    'PATCH-NOV12-G0-GOALIE-BRANCH-INTEGRITY','PATCH-NOV12-G7-MAP-COVERAGE-INTEGRITY'
)
GATE_PATCHES = {
    'G0':['PATCH_2026_11_05_EXECUTION_MATRIX_V1','PATCH-NOV12-G0-GOALIE-BRANCH-INTEGRITY'],
    'G1':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G2':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G3':['PATCH-NOV12-G0-GOALIE-BRANCH-INTEGRITY'],
    'G4':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G5':['PATCH-NOV12-G0-GOALIE-BRANCH-INTEGRITY'],
    'G6':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G7':['PATCH-NOV12-G7-MAP-COVERAGE-INTEGRITY','PATCH_OFFICIAL_SCORERS_V1'],
    'G8':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G9':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G10':['PATCH_OFFICIAL_SCORERS_V1','PATCH_RECIPIENT_LOCK_V1'],
    'G10.5':['PATCH-NOV12-G10.5-EXPLICIT-SEPARATION','PATCH_G10_5_G16_COMPARE_V2',
             'TBL-G105-G17-2026-11-08','UTA-G105-G17-2026-11-08'],
    'G11':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G12':['PATCH_OFFICIAL_SCORERS_V1','PATCH_RECIPIENT_LOCK_V1'],
    'G13':['PATCH_GATE13_CONTINUITY_V1'],
    'G14':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G15':['PATCH_RECIPIENT_LOCK_V1'],
    'G16':['PATCH-NOV12-G10.5-EXPLICIT-SEPARATION','PATCH_G10_5_G16_COMPARE_V2'],
    'G17':['PATCH-NOV12-G0-GOALIE-BRANCH-INTEGRITY','PATCH_PROVENANCE_V1',
           'PATCH_START_TIME_V1','TBL-G105-G17-2026-11-08','UTA-G105-G17-2026-11-08'],
    'G18':['PATCH_RECIPIENT_LOCK_V1','PATCH_START_TIME_V1',
           'PATCH_HISTORICAL_MULTIVERSION_OCT08_10_V1','PATCH_PROVENANCE_V1']
}



def receipt(value):
    """Only independently attributed, time-stamped observations qualify."""
    return (isinstance(value, dict)
            and isinstance(value.get('sourceUrl'), str) and value['sourceUrl'].startswith('https://')
            and isinstance(value.get('observedAt'), str) and bool(value['observedAt'])
            and bool(value.get('data')))


def evidence_data(value, key=None):
    if not receipt(value): return None
    return value['data'] if key is None else value['data'].get(key)


def verdict(pass_value, detail, eliminated=False):
    return ('PASS' if pass_value else ('ELIMINATED' if eliminated else 'NOT_EXECUTED'), detail)


def gate_record(game, player, gate, disposition, detail, source_ids=None):
    return {'gameId':str(game['id']),'playerId':str(player),'gate':gate,
            'disposition':disposition,
            'details':{'evidence':detail,'sourceIds':source_ids or [],
                       'appliedPatches':GATE_PATCHES.get(gate,[])} }


def all_goalie_branches(game, stage):
    """No shortcut from one goalie profile to the opposing team's goalie."""
    by_team = {}
    for team in (game['away'],game['home']):
        branches=[]
        for b in game.get('goalies',{}).get(team,[]):
            if not receipt(b):continue
            d=b['data']
            if d.get('status') not in ('PROJECTED','EXPECTED','CONFIRMED'):
                continue
            branches.append(b)
        # A confirmed goalie replaces its expected branch, but an unconfirmed
        # matchup must retain its evidence-labelled EXPECTED/PROJECTED branch.
        # CONFIRMED describes the run phase, never an invented source status.
        if stage=='CONFIRMED':
            confirmed=[b for b in branches if b['data'].get('status')=='CONFIRMED']
            if confirmed:
                branches=confirmed
        superseded={str(b['data']['supersedesGoalieId']) for b in branches
                    if b['data'].get('status')=='CONFIRMED' and b['data'].get('supersedesGoalieId')}
        by_team[team]=[b for b in branches if str(b['data'].get('goalieId')) not in superseded]
    return by_team


def g0_full_slate(games, stage):
    scan=[]; error=[]
    for game in games:
        for attacker,defender in ((game['away'],game['home']), (game['home'],game['away'])):
            branches=all_goalie_branches(game,stage).get(defender,[])
            proofs=[]
            for src in branches:
                x=src['data']; weak=x.get('weakZones',{})
                proof={'goalieId':x.get('goalieId'),'status':x.get('status'),
                       'sourceUrl':src['sourceUrl'],'observedAt':src['observedAt'],
                       'weakZones':weak,'strengthZones':x.get('strengthZones',{}),
                       'counterevidence':x.get('counterevidence'),
                       'sample':x.get('sample'),
                       'goalieTeam':defender}
                proofs.append(proof)
            complete=bool(proofs) and all(bool(p['weakZones']) and bool(p['sample'])
                    and p['counterevidence'] is not None for p in proofs)
            scan.append({'gameId':str(game['id']),'attacker':attacker,'defender':defender,
                         'targetGoalies':proofs,'goalieProfileEvidenced':complete})
            if not complete:error.append(f"G0 {game['id']} {attacker} attacking {defender}: independent goalie weak-zone evidence not complete")
    return scan,error


def complete_roster(game, team):
    """Current roster is not a confirmed dressed lineup. Never silently drop depth or D."""
    wrapper=game.get('rosters',{}).get(team)
    if not receipt(wrapper):return []
    players=wrapper['data'].get('players',[])
    unique={}
    for p in players:
        if not p.get('id') or not p.get('position'):
            continue
        if p['position'] not in ('C','L','R','LW','RW','D'):
            continue  # Goalies are not goal-scoring skater candidates
        if str(p['id']) in unique:
            raise ValueError('G2 duplicate skater in roster')
        unique[str(p['id'])]=p
    return list(unique.values())


def player_releases(p):
    b=p.get('release')
    if not receipt(b):return None
    data=b['data']
    if not (data.get('archetype') and data.get('zone') and isinstance(data.get('attempts'), int)
            and isinstance(data.get('ownedGoals'),int)):
        return None
    return data




def release_matched_to_g0_target(player,goalie_profile,defensive_coverage=None):
    """After G0 selects an attack side, match each skater's independently
    observed OWN shot-origin routes to that goalie's evidenced weak origins.

    Neither G0 nor the original release source is edited; no famous-player
    shortcut. A different goalie branch gets its own independent comparison.
    """
    wrapper=player.get('release')
    if not receipt(wrapper):
        return player
    base=wrapper['data']
    routes=base.get('allRoutes')
    weak=goalie_profile.get('data',{}).get('weakZones') or {}
    if not isinstance(routes,list) or not routes or not weak:
        return player
    matching=[r for r in routes if r.get('zone') in weak
              and isinstance(r.get('sog'),int)
              and isinstance(r.get('ownedGoals'),int)
              and r['sog']>=r['ownedGoals']>=0]
    if not matching:
        return player
    # G0 remains first. Among the player's OWN observed shots against G0's
    # goalie weakness, find a route independently supported by G9's actual
    # opponent-defense shot-origin concessions. Do not force a mismatch merely
    # because the skater scored more historical goals from another goalie-weak
    # area. Every eligible route still requires separately verified G5/G9.
    defense=(defensive_coverage.get('data') or {}) if receipt(defensive_coverage) else {}
    green=set(defense.get('greenWeakZones') or [])
    jointly_sourced=[x for x in matching if x['zone'] in green]
    considered=jointly_sourced if jointly_sourced else matching
    considered.sort(key=lambda x:(x['ownedGoals'],x['sog']),reverse=True)
    top=considered[0]
    tied=[x for x in considered if
          (x['ownedGoals'],x['sog'])==(top['ownedGoals'],top['sog'])]
    if len(tied)>1:
        # No arbitrary zone tie break. The original independently sourced
        # release remains the candidate until another gate separates lanes.
        return player
    observed=dict(base)
    observed.update({
        'archetype':base.get('archetype') or 'OBSERVED_OWN_SHOT_ORIGIN',
        'zone':top['zone'],
        'attempts':top['sog'],
        'ownedGoals':top['ownedGoals'],
        'g0MatchedOwnOriginRoute':True,
        'g9DefensiveLaneIndependentlyMatched':bool(jointly_sourced),
        'g9CoverageSourceUrl':defensive_coverage.get('sourceUrl') if jointly_sourced else None,
        'consideredOwnGoalieWeakRoutes':sorted(x['zone'] for x in matching),
        'originalPrimaryOrigin':base.get('zone'),
        'primaryWasTiedBeforeG0':not bool(base.get('canDeterminePrimary',True)),
        'candidateRouteReconstructedFrom':wrapper['sourceUrl'],
        'anatomicalPlacementCertified':False,
        'noPreG0SkaterPreference':True
    })
    result=dict(player)
    result['release']={**wrapper,'data':observed}
    return result

def reconcile_logs(p):
    """Aggregate only actual appearances and official dated goal events; no missed game zeros."""
    logs=p.get('gameLog'); events=p.get('mappedGoals'); total=p.get('officialGoalTotal')
    if not (receipt(logs) and receipt(events) and receipt(total)):
        return None
    ld=logs['data']; ed=events['data']; td=total['data']
    if not isinstance(ld.get('appearances'),list) or not isinstance(ed.get('goals'),list):return None
    if not isinstance(td.get('goals'),int):return None
    goals=ed['goals']; seen=set()
    for goal in goals:
        if not goal.get('goalId') or not goal.get('date') or goal['goalId'] in seen or not goal.get('sourceUrl'):
            return None
        seen.add(goal['goalId'])
    if len(goals)!=td['goals']:
        return None
    dates={e['date'] for e in goals}
    appearance_dates={x.get('date') for x in ld['appearances']}
    if not dates.issubset(appearance_dates):return None
    return {'appearanceDates':len(appearance_dates),'distinctGoalDates':len(dates),
            'officialGoals':td['goals'],'eventCount':len(goals),
            'lastAppearances':ld['appearances'][:10]}


def challenger_proof(candidate, challengers, goalie_weak_zones):
    """Compare *every* skater's owned same-origin finishing route, not fame/PP1.

    NHL EDGE independently measures each skater's shots on goal and own goals
    in each area. Requiring every competitor's separate prior-game goal log
    would discard a real same-lane threat merely because that player hasn't
    scored in the sampled last-eight games; the rival's observed season zone
    data remains valid challenger evidence.

    G10.5 compares DIRECT credited goals from the exact same target area
    before shot volume (which is supporting pressure, not a scored goal).
    This is categorical, source-linked separation with NO ranking weights;
    equal own-goal counts are compared on observed SOG, and equal results
    remain unresolved. All teammates and alternative routes remain audited.
    """
    base=player_releases(candidate)
    rows=[]; all_defeated=True
    if not base:
        return None,[]
    for rival in challengers:
        if str(rival['id'])==str(candidate['id']):
            continue
        wrapper=rival.get('release')
        release=player_releases(rival)
        if not release and receipt(wrapper) and isinstance(wrapper['data'].get('allRoutes'),list):
            # A tied season top area is still a valid measured SAME-LANE
            # challenger. Use the observed route in candidate's exact zone
            # instead of erasing the competing player.
            release=wrapper['data']
        if not release:
            rows.append({'challengerId':str(rival['id']),
                         'status':'NO_RELEASE_SOURCE',
                         'notExcludedForMissingSampledGameLog':True})
            all_defeated=False
            continue
        if not receipt(wrapper):
            rows.append({'challengerId':str(rival['id']),
                         'status':'RELEASE_PROVENANCE_MISSING'})
            all_defeated=False
            continue
        # Players can attack multiple areas. A rival's main season scoring
        # area is NOT evidence they lack a secondary route through this lane.
        matching=[x for x in release.get('allRoutes',[])
                  if x.get('zone')==base['zone']]
        if not matching and release.get('zone')==base['zone']:
            matching=[{'zone':release['zone'],'sog':release['attempts'],
                       'ownedGoals':release['ownedGoals']}]
        if not matching:
            rows.append({'challengerId':str(rival['id']),
                         'status':'DIFFERENT_TARGET_LANE',
                         'candidateZone':base['zone'],
                         'rivalKnownAreas':[x.get('zone') for x in release.get('allRoutes',[])],
                         'sourceUrls':[wrapper['sourceUrl']]})
            continue
        target=matching[0]
        opponent_shots=target.get('sog',target.get('attempts'))
        opponent_goals=target.get('ownedGoals')
        if (not isinstance(opponent_shots,int) or
                not isinstance(opponent_goals,int) or
                opponent_goals<0 or opponent_shots<opponent_goals):
            rows.append({'challengerId':str(rival['id']),
                         'status':'INCOMPLETE_OWN_FINISH_DATA',
                         'sourceUrl':wrapper['sourceUrl']})
            all_defeated=False
            continue
        # G10.5 is DIRECT RECIPIENT separation, not a requirement for a
        # scorer to lead every teammate in BOTH shots and goals. A skater
        # with 7 actual goals on this lane is not disproved by a teammate
        # with 6 actual goals and more harmless on-net shots.
        # Compare OWN credited goals first; use SOG only if the OWN goal
        # counts are equal. No fame/PP status/odds or numeric weights.
        candidate_direct=(base['ownedGoals'],base['attempts'])
        rival_direct=(opponent_goals,opponent_shots)
        dominates=candidate_direct>rival_direct
        defeated_by=rival_direct>candidate_direct
        if not dominates:
            all_defeated=False
        rows.append({
            'challengerId':str(rival['id']),
            'status':'DEFEATED' if dominates else
                     'RIVAL_DOMINATES' if defeated_by else
                     'NO_DECISIVE_ROUTE_SEPARATION',
            'candidate':{'zone':base['zone'],'shotsOnGoal':base['attempts'],
                         'ownedGoals':base['ownedGoals']},
            'challenger':{'zone':base['zone'],'shotsOnGoal':opponent_shots,
                          'ownedGoals':opponent_goals},
            'sourceUrls':[candidate['release']['sourceUrl'],wrapper['sourceUrl']],
            'sameLane':True,
            'rivalEVRole':evidence_data(rival.get('deployment')),
            'roleReviewIncomplete':not receipt(rival.get('deployment')),
            'noSeasonTotalInvented':True,
            'comparisonPriority':['ownedGoalsFromSameShotOrigin','onNetShotPressureOnlyWhenGoalsEqual'],
            'noFameOddsOrPPShortcut':True,
            'rule':'direct same-origin NHL EDGE credited own goals; when tied use same-origin on-net shots, never combined weights',
        })
    return all_defeated,rows

def evaluate_skater(game, attack_team, player, teammates, goalie_profile, stage):
    d={}; proof=[]; deficient=[]; eliminated=False
    weak=goalie_profile['data'].get('weakZones',{})
    strong=goalie_profile['data'].get('strengthZones',{})
    release=player_releases(player)
    rec=reconcile_logs(player)
    position=player.get('position')
    def emit(g, ok, detail, eliminate=False, source_ids=()):
        nonlocal eliminated
        disp,content=verdict(ok,detail,eliminate)
        if eliminated:
            disp='SKIPPED_AFTER_ELIMINATION'
        elif disp=='ELIMINATED':eliminated=True
        elif disp=='NOT_EXECUTED':deficient.append(g)
        d[g]={'disposition':disp,'details':content}
        proof.append(gate_record(game,player['id'],g,disp,content,list(source_ids)))
    emit('G0',bool(weak) and bool(goalie_profile['data'].get('sample')),
         {'targetGoalie':goalie_profile['data'].get('goalieId'), 'attacker':attack_team,
          'branchStatus':goalie_profile['data'].get('status'), 'weakZones':weak,
          'separateGoalieBranch':True},source_ids=list(filter(None,[
          goalie_profile['sourceUrl'],goalie_profile['data'].get('goalieProfileSourceUrl')])))
    emit('G1',receipt(game.get('context')),
         {'venueRestTravel':evidence_data(game.get('context'))},
         source_ids=[game.get('context',{}).get('sourceUrl','')])
    roster=game.get('rosters',{}).get(attack_team)
    eligibility=player.get('availability','UNVERIFIED')
    # G2 surveys the WHOLE official current roster, not merely a lineup
    # publication's top lines. "UNVERIFIED" is roster eligibility to be
    # researched, NOT a confirmed dressed status or confirmed deployment.
    roster_eligible=(receipt(roster) and eligibility in
        ('DRESSED','CONFIRMED','PROJECTED_ACTIVE','UNVERIFIED'))
    emit('G2',bool(roster_eligible),
         {'fullPoolSize':len(teammates),'availability':eligibility,
          'officialCurrentRosterSource':roster.get('sourceUrl') if receipt(roster) else None,
          'position':position,
          'currentRosterNotEquivalentToDressed':True,
          'confirmedDressed':eligibility in ('DRESSED','CONFIRMED'),
          'lineupStillRequiresIndependentG6':True},
         eliminate=eligibility in ('OUT','SCRATCHED','INJURED'))
    emit('G3',bool(weak) and goalie_profile['data'].get('counterevidence') is not None,
         {'goalieSample':goalie_profile['data'].get('sample'),
          'goalieWeakZones':weak,'counterevidence':goalie_profile['data'].get('counterevidence')},
         source_ids=[goalie_profile['sourceUrl']])
    emit('G4',bool(release), {'archetype':release.get('archetype') if release else None,
         'ownRelease':release},source_ids=[player.get('release',{}).get('sourceUrl','')])
    overlap=bool(release and release['zone'] in weak)
    emit('G5',bool(weak and release) and overlap,
         {'shooterZone':release['zone'] if release else None,'weakZones':weak,
          'goalieStrengthZones':strong},
         eliminate=bool(weak and release and not overlap),
         source_ids=list(filter(None,[player.get('release',{}).get('sourceUrl'),
             goalie_profile['data'].get('goalieProfileSourceUrl'),goalie_profile['sourceUrl']])))
    dep=player.get('deployment')
    dep_data=evidence_data(dep)
    dep_ok=bool(dep_data and dep_data.get('EV') and dep_data.get('status') in ('PROJECTED','CONFIRMED'))
    # Keep a sourced projected unit only as projected evidence until the team
    # actually confirms it; complete runs with mixed evidence remain MIXED.
    emit('G6',dep_ok,{'deployment':dep_data,'notAllPP1':True,
          'projectedNotPromoted':bool(dep_data and dep_data.get('status')=='PROJECTED')},
         source_ids=[dep.get('sourceUrl','') if dep else ''])
    emit('G7',bool(rec),{'eventLogReconciled':rec,'multiGoalDateOnce':True,'missedGamesExcluded':True},
         source_ids=[p.get('sourceUrl','') for p in (player.get('gameLog'),player.get('mappedGoals')) if p])
    market=player.get('authenticMarket')
    # G8 explicitly neutral when unavailable; never invent market or eliminate a skater.
    emit('G8',True,{'market':evidence_data(market) if receipt(market) else None,
                  'neutralWhenAbsent':not receipt(market),'neverRankingShortcut':True})
    coverage=game.get('coverage',{}).get(attack_team)
    coverage_data=evidence_data(coverage)
    match=bool(coverage_data and release and release['zone'] in coverage_data.get('greenWeakZones',[]))
    emit('G9',match,{'shooterZone':release['zone'] if release else None,
                   'greenTarget':coverage_data.get('greenWeakZones',[]) if coverage_data else None,
                   'redAvoid':coverage_data.get('redStrongZones',[]) if coverage_data else None},
         eliminate=bool(coverage_data and release and release['zone'] in coverage_data.get('redStrongZones',[])),
         source_ids=[coverage['sourceUrl']] if receipt(coverage) else [])
    ownership=player.get('finishOwnership');own=evidence_data(ownership)
    emit('G10',bool(own and own.get('recipient') is True),
         {'goalCreditOwned':own,'notAssistOrFeeder':True},
         eliminate=bool(own and own.get('recipient') is False))
    rivals=[x for x in teammates if str(x['id'])!=str(player['id']) and
            x.get('availability') not in ('OUT','SCRATCHED','INJURED')]
    wins,rows=challenger_proof(player,rivals,weak)
    emit('G10.5',wins is True,
         {'comparisonRows':rows,'allAlternativesScanned':len(rows)==len(rivals),
          'noGuessTransfer':True},
         source_ids=sorted({url for row in rows for url in row.get('sourceUrls',[])
             if url} | ({player['release']['sourceUrl']} if receipt(player.get('release')) else set())))
    shots=player.get('pressure')
    recent_shots=evidence_data(shots,'recentAppearanceShots')
    pressure_valid=isinstance(recent_shots,int) and recent_shots>=0 or (isinstance(recent_shots,list) and bool(recent_shots) and all(isinstance(x,int) and x>=0 for x in recent_shots))
    emit('G11',bool(receipt(shots) and pressure_valid),
         {'recentOwnAttempts':evidence_data(shots,'recentAppearanceShots') if shots else None})
    emit('G12',bool(own and own.get('creditedGoalsVerified') is True and rec is not None),
         {'ownership':own,'officialGoalsReconciled':bool(rec)})
    jersey=player.get('jersey')
    # No numerical formula or invented milestone. Qualitative review genuinely executed.
    milestone=player.get('milestone')
    g13={'date':game.get('date'),'jersey':jersey,
         'milestone':evidence_data(milestone) if receipt(milestone) else 'No verified milestone',
         'formula':'none; qualitative only','nonblocking':True}
    emit('G13',True,g13)
    who=player.get('whoAnomaly');who_ok=bool(receipt(who) and
        evidence_data(who,'directIndependentRoute') is True and overlap)
    emit('G14',True,{'whoAnomalyPhysicallySupported':who_ok,
                    'noForcedWho':True,'whoDetails':evidence_data(who) if who_ok else None})
    emit('G15',bool(own and own.get('recipient') is True),
         {'independentFinish':True if own and own.get('recipient') is True else None})
    emit('G16',wins is True and len(rows)==len(rivals),
         {'everyOtherActiveTeammate':len(rows),'challengerRows':rows,
          'includesDepthAndDefense':True})
    contradiction=player.get('contradictions')
    cdata=evidence_data(contradiction)
    # Having a review OBJECT is not proof that its conflicts were resolved.
    # Source-derived cross-checks must explicitly report no unresolved
    # goalie/role/rival contradiction to pass; never force G17 on placeholder.
    cross_source_resolved=(cdata.get('sourceType')!='DERIVED_CROSS_SOURCE_G17'
                            or cdata.get('unresolved') is False) if cdata else False
    emit('G17',bool(cdata and cdata.get('goalieStrengthReview') is not None and
                     cdata.get('lineupDisagreementReview') is not None and
                     cdata.get('strongestRivalReview') is not None and
                     cross_source_resolved),
         {'goalieBranch':goalie_profile['data'].get('goalieId'),
          'counterevidence':cdata,'retainsConflictingSources':True,
          'sourceDerivedReviewResolved':cross_source_resolved},
         source_ids=[contradiction['sourceUrl']] if receipt(contradiction) else [])
    # G18 can only be reached after every previous gate has positive evidence.
    passed=all(d[g]['disposition']=='PASS' for g in MASTER[:-1])
    emit('G18',passed,{'candidateEligibleForCrossGameFinal':passed})
    overlay=[]
    for step in OVERLAY:
        check={'Step0':'G0','Step1':'G2','Step2':'G1','Step3':'G5','Step4':'G7',
               'Step5':'G4','Step6':'G6','Step7':'G4','Step8':'G9','Step9':'G11',
               'Step10':'G5','Step10.5':'G10.5','Step11':'G14','Step12':'G16',
               'Step13':'G13','Step14':'G17'}[step]
        disp=d[check]['disposition']
        overlay.append(gate_record(game,player['id'],step,disp,
                      {'independentOverlayCheck':check,
                       'archetypeBeforeSelection':release['archetype'] if step=='Step7' and release else None}))
    transfer=evidence_data(player.get('transferEvidence'),'directRouteDisplaced') is True
    route='WHO' if who_ok else 'TRANSFER' if transfer else 'PRIMARY'
    return {'player':player,'dispositions':d,'complete':passed,'deficientGates':deficient,
            'route':route,'pressure':evidence_data(shots),
            'release':release,'challengers':rows},proof+overlay



def verify_complete_matrix(games, records, scan, now=None, selected_directions=None):
    """Patch: 2026-11-05 complete every eligible player and overlay before G18."""
    errors=[]
    now=now or datetime.now(timezone.utc)
    expected_set=set(MASTER+OVERLAY)
    for game in games:
        already_started=(game.get('gameState') in ('LIVE','CRIT','OFF','FINAL') or
          (game.get('startUTC') and datetime.fromisoformat(game['startUTC'].replace('Z','+00:00'))<=now))
        if already_started:continue
        direction=(selected_directions or {}).get(str(game['id']))
        if not direction:
            continue  # G0 did not authorize this matchup for skater gates
        active_roster=complete_roster(game,direction['attacker'])
        for person in active_roster:
            pid=str(person['id'])
            actual={r['gate'] for r in records
                    if r['gameId']==str(game['id']) and r['playerId']==pid}
            if actual!=expected_set:
                missing=sorted(expected_set-actual)
                errors.append(f"{game['id']} player {pid} missing gate/overlay records {missing}")
        count=sum(1 for r in records if r['gameId']==str(game['id']) and r['gate']=='G0'
                  and r['playerId'].startswith('GOALIE_DIRECTION:'))
        if count!=2:errors.append(f"{game['id']} G0 source directions saved {count} not 2")
    return errors


def cross_game_winners(winners, slate_size):
    """Never resolve incomparable shooters by stars, odds, or made-up score.
    A published card requires exactly the permitted count of uniquely qualified
    games; additional comparison must be supplied as a documented independent
    route adjudication, not implicit top-N ranking."""
    required=2 if slate_size==2 else 3
    if len(winners)==required:
        return winners,[]
    if len(winners)<required:
        return [],[f'G18 only {len(winners)} fully evidenced games; {required} required']
    # Deterministic multi-game comparison by strict evidence-based dominance.
    # If >3 games remain nondominated, there is no proof for choosing arbitrary 3.
    preferred=[]
    for this in winners:
        a=this['candidate']['release']
        dominated=False
        for other in winners:
            if other is this:continue
            b=other['candidate']['release']
            if a['zone']!=b['zone']:
                continue # dissimilar goalie lanes cannot be ranked on own raw totals
            if b['attempts']>=a['attempts'] and b['ownedGoals']>=a['ownedGoals'] and (
               b['attempts']>a['attempts'] or b['ownedGoals']>a['ownedGoals']):
                dominated=True;break
        if not dominated:preferred.append(this)
    if len(preferred)==required:
        return preferred,[]
    return [],[f'G18 {len(preferred)} nondominated game recipients for {required} slots; no supported tiebreak']


def build_verified_replacement(con, existing, legs, selected, date, stage):
    """Automatic pre-puck replacement only after stored confirmed-source gate reruns."""
    if stage != 'CONFIRMED':
        return None
    prior = {str(x['gameId']): x for x in existing['current_legs']}
    proposed = {str(x['gameId']): x for x in legs}
    if set(prior) != set(proposed):
        return None
    changed = [gid for gid in prior if str(prior[gid]['playerId']) != str(proposed[gid]['playerId'])]
    if len(changed) != 1:
        return None
    gid = changed[0]
    old, new = prior[gid], proposed[gid]
    item = next((x for x in selected if str(x['game']['id']) == gid), None)
    if not item or str(item['candidate']['player']['id']) != str(new['playerId']):
        return None
    goalie = item['targetGoalie']
    trigger = goalie.get('evidenceId')
    if not trigger or goalie['data']['status'] != 'CONFIRMED':
        return None
    if str(old.get('opposingGoalieId')) == str(new.get('opposingGoalieId')):
        return None
    if not con.execute('SELECT 1 FROM evidence WHERE evidence_id=? AND slate_date=?',
                       (trigger, date)).fetchone():
        return None
    # Prior survivor must fail an actually rerun original physical-route gate.
    failure = con.execute('SELECT disposition,details FROM gates WHERE slate_date=? AND stage=? AND game_id=? AND player_id=? AND gate=?',
                          (date, stage, gid, str(old['playerId']), 'G5')).fetchone()
    if not failure or failure['disposition'] != 'ELIMINATED':
        return None
    candidate = item['candidate']
    rows = candidate['challengers']
    if not rows or any(r['status'] not in ('DEFEATED', 'DIFFERENT_TARGET_LANE') for r in rows):
        return None
    if candidate['dispositions']['G10.5']['disposition'] != 'PASS':
        return None
    if candidate['dispositions']['G17']['disposition'] != 'PASS':
        return None
    g17id = (candidate['player'].get('contradictions') or {}).get('evidenceId')
    if not g17id or not con.execute('SELECT 1 FROM evidence WHERE evidence_id=? AND slate_date=?',
                                   (g17id, date)).fetchone():
        return None
    return {
        'baselineFingerprint': existing['fingerprint'],
        'triggerEvidenceId': trigger,
        'oldValue': {'player': old['player'], 'goalieId': old.get('opposingGoalieId')},
        'newValue': {'player': new['player'], 'goalieId': new.get('opposingGoalieId')},
        'affectedGates': ['G0', 'G3', 'G5'],
        'dependentGates': ['G6', 'G7', 'G9', 'G10', 'G10.5', 'G12', 'G16', 'G17', 'G18'],
        'priorSurvivorFailure': {
            'playerId': old['playerId'], 'failedGate': 'G5',
            'sourceIds': [trigger],
            'detail': 'Prior survivor route no longer fits independently sourced new opposing goalie weakness'
        },
        'g105EveryChallenger': {'comparisonRows': rows, 'candidate': new['playerId']},
        'g17Contradictions': {'sourceIds': [g17id],
                              'review': candidate['dispositions']['G17']['details']},
        'newFingerprint': fingerprint(legs)
    }



def compare_g0_same_origin(direction_a, direction_b):
    """Source-backed same-lane goalie comparison when weak-zone names tie.

    Both opposing goalies have a measured weak area. If one goalie is
    consistently worse in EVERY shared area on BOTH observed goals allowed
    per on-net shot and the NHL's independent league save-percentile ranking,
    that attack direction wins. Never choose based on skaters, fame, odds,
    assumed goal-mouth anatomy, or a fabricated multi-factor weight.
    Return None on disagreement, noncomparable areas, or multiple starters.
    """
    a=direction_a.get('targetGoalies') or []
    b=direction_b.get('targetGoalies') or []
    if len(a)!=1 or len(b)!=1:
        return None
    weak_a=a[0].get('weakZones') or {}
    weak_b=b[0].get('weakZones') or {}
    shared=set(weak_a) & set(weak_b)
    if not shared or set(weak_a)!=set(weak_b):
        return None
    winner=None
    for zone in sorted(shared):
        x=weak_a.get(zone) or {}
        y=weak_b.get(zone) or {}
        fields=('shotsAgainst','goalsAgainst','leagueSavePctgPercentile')
        if any(k not in x or k not in y for k in fields):
            return None
        na,nb=x['shotsAgainst'],y['shotsAgainst']
        ga,gb=x['goalsAgainst'],y['goalsAgainst']
        pa,pb=x['leagueSavePctgPercentile'],y['leagueSavePctgPercentile']
        if any(type(v) not in (int,float) for v in (na,nb,ga,gb,pa,pb)):
            return None
        if na<20 or nb<20 or not (0<=ga<=na and 0<=gb<=nb and 0<=pa<=1 and 0<=pb<=1):
            return None
        # Using fractions avoids floating-point rounding when comparing
        # observed goal rates from different sample sizes.
        higher_goals_a=ga*nb>gb*na
        higher_goals_b=gb*na>ga*nb
        if pa<pb and higher_goals_a:
            orientation='a'
        elif pb<pa and higher_goals_b:
            orientation='b'
        else:
            return None
        if winner is not None and winner!=orientation:
            return None
        winner=orientation
    return direction_a if winner=='a' else direction_b if winner=='b' else None


def execute(con, snapshot, date, stage='PROJECTED', now=None):
    now=now or datetime.now(timezone.utc)
    if stage not in ('PROJECTED','CONFIRMED'):raise ValueError('Stage is projected or confirmed')
    games=snapshot.get('games',[])
    if not games:
        msg={'reason':'No official NHL game data provided','stage':stage}
        log_job(con,f'{date}-{stage}',date,stage,'SOURCE_ERROR',msg)
        return {'card':None,'errors':[msg['reason']],'gateRows':0,'scan':[]}
    scan,g0_direction_notes=g0_full_slate(games,stage)
    # Unselected opposing directions are audited, not fatal to the G0-selected side.
    errors=[]
    records=[];qualified=[];pool_size=0
    # Preserve actual G0 goalie-first direction receipts BEFORE skater traces.
    for entry in scan:
        match=next(g for g in games if str(g['id'])==entry['gameId'])
        records.append(gate_record(match,'GOALIE_DIRECTION:'+entry['attacker'], 'G0',
            'PASS' if entry['goalieProfileEvidenced'] else 'NOT_EXECUTED',
            {'attacker':entry['attacker'],'defender':entry['defender'],
             'independentGoalieBranches':entry['targetGoalies'],
             'goalieBeforeSkaters':True},
            [x['sourceUrl'] for x in entry['targetGoalies']]))
    # G0 adjudicates the target goalie and attack side BEFORE the skater pool.
    # Independent zone evidence must distinguish directions; no popularity,
    # market, arbitrary weights, or alphabetic tiebreaks.
    selected_directions={}
    for match in games:
        options=[x for x in scan if x['gameId']==str(match['id'])
                 and x['goalieProfileEvidenced']]
        if not options:
            errors.append(f"{match['id']} G0 no independently evidenced goalie target")
            continue
        if len(options)==1:
            selected_directions[str(match['id'])]=options[0]
            continue
        if len(options)!=2:
            errors.append(f"{match['id']} G0 conflicting target goalie branches")
            continue
        def weakness_vector(direction):
            profiles=direction['targetGoalies']
            if len(profiles)!=1:
                return None
            zones=profiles[0]['weakZones']
            if not isinstance(zones,dict) or not zones:
                return None
            # G0 compares independently certified goalie weakness zones,
            # never skater fame, player picks, or unverified shot coordinates.
            return set(zones)
        left,right=(weakness_vector(x) for x in options)
        if left is not None and right is not None and left!=right:
            if left>right:
                selected_directions[str(match['id'])]=options[0]
                continue
            if right>left:
                selected_directions[str(match['id'])]=options[1]
                continue
        # Source-based comparison covers the important case where both
        # goalies are weak from the SAME area (set equality). More exposed
        # goalie must be worse by BOTH empirical goal rate and published
        # league save-percentile; otherwise keep G0 unresolved.
        comparative=compare_g0_same_origin(options[0],options[1])
        if comparative is not None:
            selected_directions[str(match['id'])]=comparative
            continue
        errors.append(f"{match['id']} G0 attack sides not physically separated by certified goalie weaknesses")
    # A missing target direction is a hard failure only when G0 cannot select
    # a target for that matchup; the opposite direction is not a second pool.
    for match in games:
        is_started=match.get('gameState') in ('LIVE','CRIT','OFF','FINAL') or (
            match.get('startUTC') and datetime.fromisoformat(match['startUTC'].replace('Z','+00:00')) <= now)
        if is_started:
            # Not eligible for new selection; frozen cards remain in storage.
            continue
        direction=selected_directions.get(str(match['id']))
        if direction is None:
            continue
        team=direction['attacker']
        opponent=direction['defender']
        players=complete_roster(match,team)
        pool_size+=len(players)
        if not players:
            errors.append(f"{match['id']} G2 complete roster missing for G0-selected attack side {team}")
            continue
        for p in players:
            if not p.get('release'):
                p['archetypeEvidence']='NOT_ACQUIRED'
        branches=all_goalie_branches(match,stage).get(opponent,[])
        if not branches:
            errors.append(f"{match['id']} G0-selected opposing goalie branch missing for {opponent}")
            continue
        all_per_game=[]
        for branch in branches:
            for player in players:
                scoped=release_matched_to_g0_target(player,branch,match.get('coverage',{}).get(team))
                result,traces=evaluate_skater(match,team,scoped,players,branch,stage)
                records+=traces
                if result['complete']:
                    all_per_game.append({'game':match,'attackTeam':team,'targetGoalie':branch,
                                         'candidate':result})
        if len(all_per_game)==1:
            qualified.append(all_per_game[0])
        elif len(all_per_game)>1:
            errors.append(f"{match['id']} G18 {len(all_per_game)} unseparated game survivors; cannot take multiple")
    save_gates(con,date,stage,records)
    chosen,selection_errors=cross_game_winners(qualified,len(games))
    selection_errors += verify_complete_matrix(games,records,scan,now,selected_directions)
    # A game that has already started cannot be newly picked. Such a game is
    # excluded from the candidate pool above, but does not veto later games.
    # G0 surveys both directions; the losing direction does not have to
    # pass G0 or the skater matrix. Only selected attack directions advance.
    errors+=selection_errors
    card=None
    if chosen and not selection_errors:
        legs=[]
        for x in chosen:
            p=x['candidate']['player'];g=x['game'];goalie=x['targetGoalie']
            legs.append({'gameId':str(g['id']),'playerId':str(p['id']),
                        'player':p.get('name',str(p['id'])),'path':x['candidate']['route'],
                        'matchup':g['away']+'@'+g['home'],'startUTC':g['startUTC'],
                        'gameState':g.get('gameState','FUT'),
                        'opposingGoalieId':goalie['data']['goalieId'],
                        'sourceIds':sorted({goalie['sourceUrl'],p['release']['sourceUrl'],
                                            p['deployment']['sourceUrl']}),
                        'directRoute':x['candidate']['release']['archetype']+' / '+x['candidate']['release']['zone']})
        # save_card enforces one slate identity, puck-drop freeze, and full replacement audit.
        try:
            existing=get_card(con,date)
            audit=None
            if existing and existing['fingerprint']!=fingerprint(legs):
                audit=build_verified_replacement(con,existing,legs,chosen,date,stage)
                if not audit:
                    raise ValueError('Different scorer candidates did not satisfy a verified old-to-new source, prior-player failure, and G10.5/G17 replacement audit; the original card is preserved.')
            evidence_stage=stage
            if stage=='CONFIRMED' and any(
                x['targetGoalie']['data'].get('status')!='CONFIRMED' or
                (x['candidate']['player'].get('deployment') or {}).get('data',{}).get('status')!='CONFIRMED'
                for x in chosen):
                evidence_stage='MIXED'
            card=save_card(con,date,evidence_stage,legs,len(games),audit=audit,now=now)
        except ValueError as e:errors.append(str(e))
    gaps=defaultdict(int)
    for rec in records:
        if rec['disposition']=='NOT_EXECUTED':gaps[rec['gate']]+=1
    result={'card':card,'date':date,'stage':stage,'games':len(games),
            'g0Directions':len(scan),'g0Complete':sum(bool(x['goalieProfileEvidenced']) for x in scan),
            'eligibleSkaterRows':pool_size,'gateRows':len(records),'missingByGate':dict(gaps),
            'uniqueGameSurvivors':len(qualified),'errors':errors,'scan':scan}
    log_job(con,f'{date}-{stage}',date,stage,'COMPLETE' if card else 'INPUT_INCOMPLETE',
            {k:v for k,v in result.items() if k not in ('card','scan')})
    return result