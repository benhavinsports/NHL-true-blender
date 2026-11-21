"""Evidence-driven NHL G0..G18 executor. No favorites, arbitrary weights or proxy goalies.

Input is a source-annotated game snapshot produced by collectors, not a list of picks.
Output is an immutable gate record for every surveyed direction and skater.
Only the uniquely defensible, fully evidenced survivors can be published.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from .storage import save_card, save_gates, log_job, get_card, fingerprint, game_started, stamp
from .overlay_checks import independent_overlay, STEP_ORDER
from .rival_scope import g17_resolved_without_eliminated_rivals
from .semantic_certification import audit_gate, nonblocking_overlay_review
from .route_continuation import observed_own_shot_appearances, observed_dated_recurrence
from .shooter_mechanism import shooter_mechanism
from .recent_origin import independently_dated_origin_route, independently_bounded_origin_route

# The user's 18 numbered scorer gates remain individually named and ordered.
# G10.5 is the mandatory half-step between G10 and G11. G0 is the
# separate goalie-first direction decision, not a substitute for scorer gates.
SCORER_GATE_ORDER = ([f'G{i}' for i in range(1,11)] +
                     ['G10.5'] + [f'G{i}' for i in range(11,19)])
MASTER = ['G0'] + SCORER_GATE_ORDER
OVERLAY = ([f'Step{i}' for i in range(11)] + ['Step10.5'] +
           [f'Step{i}' for i in range(11,15)])
# The historical Step descriptions are functions WITHIN the original gates,
# never a second gate sequence, an independent pass, or 16 more selections.
# Keep their observation names solely to preserve evidence provenance.
STEP_OWNER = {'Step0':'G0','Step1':'G2','Step2':'G1','Step3':'G5',
              'Step4':'G7','Step5':'G4','Step6':'G6','Step7':'G4',
              'Step8':'G9','Step9':'G11','Step10':'G5',
              'Step10.5':'G10.5','Step11':'G14','Step12':'G16',
              'Step13':'G13','Step14':'G17'}
STEPS_BY_GATE = {gate:[step for step in OVERLAY if STEP_OWNER[step]==gate]
                 for gate in MASTER}
# Overlay operations run when their owning master gate reaches its original
# logical position. This is intentionally NOT the numeric Step label order:
# Step1 belongs to G2 while Step2 belongs to G1, and Step7 archetype tagging
# belongs to G4 before later recurrence/challenger/final-review operations.
OVERLAY_EXECUTION_ORDER = [step for gate in MASTER for step in STEPS_BY_GATE[gate]]
EXECUTION_ORDER = MASTER[:]
if EXECUTION_ORDER != ['G0'] + SCORER_GATE_ORDER or EXECUTION_ORDER[-1] != 'G18':
    raise RuntimeError('Authoritative NHL gate order was altered')
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
    if gate not in EXECUTION_ORDER:
        raise ValueError(f'Unknown gate outside the authoritative execution order: {gate}')
    index=EXECUTION_ORDER.index(gate)
    phase=('G0_GOALIE_FIRST' if gate=='G0' else
           'G18_FINAL' if gate=='G18' else 'MASTER')
    return {'gameId':str(game['id']),'playerId':str(player),'gate':gate,
            'disposition':disposition,
            'details':{'evidence':detail,'sourceIds':source_ids or [],
                       'appliedPatches':GATE_PATCHES.get(gate,[]),
                       'executionIndex':index,'executionPhase':phase}}


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
        # A genuinely CONFIRMED starter supersedes projected/expected
        # alternatives in either run phase. The old stage-only filter left
        # two alleged starters in PROJECTED, despite an independently
        # confirmed name, and G0 then failed before evaluating skaters.
        confirmed=[b for b in branches if b['data'].get('status')=='CONFIRMED']
        conflict_rows=[]
        def keep_authoritative(selected,reason):
            nonlocal branches
            selected_ids={str(b['data'].get('goalieId')) for b in selected}
            excluded=[b for b in branches if str(b['data'].get('goalieId')) not in selected_ids]
            conflict_rows.extend({
                'goalieId':str(b['data'].get('goalieId') or ''),
                'status':b['data'].get('status'),
                'sourceUrl':b.get('sourceUrl'),
                'sourceType':b['data'].get('starterSourceStatus') or b['data'].get('sourceType'),
                'sourceReportedConfidence':b['data'].get('sourceConfidenceLabel'),
                'reason':reason,
                'preservedAsCounterevidence':True,
            } for b in excluded)
            branches=selected
            for selected_branch in branches:
                selected_branch['data']['projectedBranchConflicts']=list(conflict_rows)
                selected_branch['data']['projectionAuthorityDecision']=reason
        if confirmed:
            confirmed_ids={str(b['data'].get('goalieId')) for b in confirmed}
            if len(confirmed_ids)==1:
                keep_authoritative(confirmed,'EXPLICIT_CONFIRMED_STARTER_SUPERSEDES_PROJECTIONS')
            else:
                lower=[b for b in branches if b not in confirmed]
                conflict_rows.extend({
                    'goalieId':str(b['data'].get('goalieId') or ''),
                    'status':b['data'].get('status'),
                    'sourceUrl':b.get('sourceUrl'),
                    'sourceType':b['data'].get('starterSourceStatus') or b['data'].get('sourceType'),
                    'reason':'LOWER_AUTHORITY_PROJECTED_CONFLICT_WITH_CONFIRMED_SOURCES',
                    'preservedAsCounterevidence':True,
                } for b in lower)
                branches=confirmed
                for selected_branch in branches:
                    selected_branch['data']['projectedBranchConflicts']=list(conflict_rows)
                    selected_branch['data']['projectionAuthorityDecision']='CONFIRMED_SOURCES_CONFLICT_KEEP_ALL'
        else:
            # A dated first-hand morning-skate FIRST-GOALIE-OFF report is
            # direct rink observation, stronger evidence than an algorithmic
            # probability prediction or generic roster-first ordering.
            # Never call it CONFIRMED or use a secondhand/stale report.
            first_off=[b for b in branches if
                b['data'].get('status')=='EXPECTED' and
                b['data'].get('datedEyewitnessMorningSkateFirstOff') is True and
                b['data'].get('sourceReportDate')==game.get('date') and
                bool(b['data'].get('morningSkateSourceUrls'))]
            first_off_ids={str(b['data'].get('goalieId')) for b in first_off}
            if len(first_off_ids)==1:
                reported=next(iter(first_off_ids))
                keep_authoritative(first_off,'DATED_FIRST_HAND_MORNING_SKATE_FIRST_OFF')
            elif len(first_off_ids)>1:
                lower=[b for b in branches if b not in first_off]
                conflict_rows.extend({
                    'goalieId':str(b['data'].get('goalieId') or ''),
                    'status':b['data'].get('status'),
                    'sourceUrl':b.get('sourceUrl'),
                    'sourceType':b['data'].get('starterSourceStatus') or b['data'].get('sourceType'),
                    'reason':'LOWER_AUTHORITY_PROJECTION_CONFLICT_WITH_FIRST_OFF_REPORTS',
                    'preservedAsCounterevidence':True,
                } for b in lower)
                branches=first_off
                for selected_branch in branches:
                    selected_branch['data']['projectedBranchConflicts']=list(conflict_rows)
                    selected_branch['data']['projectionAuthorityDecision']='FIRST_OFF_SOURCES_CONFLICT_KEEP_ALL'
            else:
                # For the projected-starter fact, a dated, matchup-specific
                # NHL.com projected-lineup receipt outranks a secondary
                # algorithmic probability estimate. Keep every conflicting
                # lower-tier identity in the selected branch's provenance;
                # if official NHL.com sources themselves disagree, retain
                # every official branch rather than inventing a tiebreak.
                official_projected=[b for b in branches
                    if (b['data'].get('starterSourceStatus')==
                        'NHL_OFFICIAL_PROJECTED_LINEUP'
                        or bool(b['data'].get('officialProjectedLineupSourceUrls')))
                    and b['data'].get('projectedPreferred') is True
                    and (not b['data'].get('publishedAsOfSlateDate')
                         or b['data'].get('publishedAsOfSlateDate')==game.get('date'))]
                official_ids={str(b['data'].get('goalieId')) for b in official_projected}
                if len(official_ids)==1:
                    keep_authoritative(official_projected,
                        'DATED_OFFICIAL_NHL_PROJECTED_LINEUP_OUTRANKS_SECONDARY_PROJECTION')
                elif len(official_ids)>1:
                    lower=[b for b in branches if b not in official_projected]
                    conflict_rows.extend({
                        'goalieId':str(b['data'].get('goalieId') or ''),
                        'status':b['data'].get('status'),
                        'sourceUrl':b.get('sourceUrl'),
                        'sourceType':b['data'].get('starterSourceStatus') or b['data'].get('sourceType'),
                        'reason':'LOWER_AUTHORITY_PROJECTION_CONFLICT',
                        'preservedAsCounterevidence':True,
                    } for b in lower)
                    branches=official_projected
                    for selected_branch in branches:
                        selected_branch['data']['projectedBranchConflicts']=list(conflict_rows)
                        selected_branch['data']['projectionAuthorityDecision']='OFFICIAL_PROJECTED_SOURCES_CONFLICT_KEEP_ALL'
                else:
                    # With no official dated projection, do not silently
                    # choose between conflicting third-party branches.
                    preferred=[b for b in branches if
                               b['data'].get('projectedPreferred') is True]
                    if len({str(b['data'].get('goalieId')) for b in preferred})==1:
                        keep_authoritative(preferred,'UNIQUE_DATED_PROJECTED_PREFERENCE')
        superseded={str(b['data']['supersedesGoalieId']) for b in branches
                    if b['data'].get('status')=='CONFIRMED' and b['data'].get('supersedesGoalieId')}
        branches=[b for b in branches
                  if str(b['data'].get('goalieId')) not in superseded]
        # Independent sources may report the SAME official goalie ID once as
        # PROJECTED and once as EXPECTED. That is one goalie, not two
        # possible starters. Do not turn duplicate identity receipts into an
        # unresolved G0 or evaluate the same player/goalie pair twice.
        # Different goalie IDs and incompatible complete scouting profiles
        # stay as separate branches. Every source URL remains inspectable.
        unique=[]
        profile_keys=('weakZones','strengthZones','sample','counterevidence',
                      'sourceClass','sourceType')
        for branch in branches:
            identity=str(branch['data'].get('goalieId') or '')
            duplicate_index=None
            for idx,prior in enumerate(unique):
                if not identity or identity!=str(prior['data'].get('goalieId') or ''):
                    continue
                pa,pb=prior['data'],branch['data']
                prior_complete=bool(pa.get('sample') and pa.get('counterevidence') is not None)
                new_complete=bool(pb.get('sample') and pb.get('counterevidence') is not None)
                if prior_complete and new_complete and any(
                    pa.get(k)!=pb.get(k) for k in profile_keys):
                    continue  # contradictory measured sources: do not erase
                duplicate_index=idx
                break
            if duplicate_index is None:
                unique.append(branch)
                continue
            prior=unique[duplicate_index]
            def precedence(b):
                d=b['data']
                complete=bool(d.get('sample') and d.get('counterevidence') is not None)
                certainty={'PROJECTED':0,'EXPECTED':1,'CONFIRMED':2}.get(d.get('status'),-1)
                return (int(complete),certainty,str(b.get('observedAt') or ''))
            chosen=max((prior,branch),key=precedence)
            urls=sorted({str(url) for item in (prior,branch) for url in
                ([item.get('sourceUrl')] + item['data'].get('sameGoalieIdentitySourceUrls',[]))
                if url and str(url).startswith('https://')})
            unique[duplicate_index]={**chosen,'data':{
                **chosen['data'],'sameGoalieIdentitySourceUrls':urls}}
        by_team[team]=unique
    return by_team


def g0_full_slate(games, stage):
    scan=[]; error=[]
    for game in games:
        for attacker,defender in ((game['away'],game['home']), (game['home'],game['away'])):
            branches=all_goalie_branches(game,stage).get(defender,[])
            proofs=[]
            for src in branches:
                x=src['data']; weak=x.get('weakZones',{})
                # A source-proven STRONG goalie has NO weak zones but still
                # has a measured independent G0 profile. Do not erase the
                # negative/strong goalie receipt or choose the other side
                # simply because this goalie lacked a weak zone.
                source_reviewed=(bool(weak) and bool(x.get('sample')) and
                                 x.get('counterevidence') is not None) or bool(
                    x.get('sourceReviewed') is True or
                    (x.get('sourceClass')=='INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY'
                     and x.get('fullySourceComparedAreas',0)>0))
                sample_peer=game.get('goaliePeerContexts',{}).get(str(x.get('goalieId')))
                proof={'goalieId':x.get('goalieId'),'status':x.get('status'),
                       'sourceUrl':src['sourceUrl'],'observedAt':src['observedAt'],
                       'weakZones':weak,'strengthZones':x.get('strengthZones',{}),
                       'counterevidence':x.get('counterevidence'),
                       'sample':x.get('sample'),
                       'profileReviewed':source_reviewed,
                       'evidenceScope':x.get('evidenceScope') or x.get('sourceType'),
                       'sourceClass':x.get('sourceClass'),
                       'goalieProfileSourceUrl':x.get('goalieProfileSourceUrl'),
                       'goalieProfileEvidenceId':x.get('goalieProfileEvidenceId'),
                       'sameCohortPbp':sample_peer,
                       'goalieTeam':defender,
                       'sameGoalieIdentitySourceUrls':x.get('sameGoalieIdentitySourceUrls',[]),
                       'projectedBranchConflicts':x.get('projectedBranchConflicts',[]),
                       'officialProjectedLineupSourceUrls':x.get('officialProjectedLineupSourceUrls',[]),
                       'projectionAuthorityDecision':x.get('projectionAuthorityDecision')}
                proofs.append(proof)
            complete=bool(proofs) and all(p['profileReviewed'] and bool(p['sample'])
                    and p['counterevidence'] is not None for p in proofs)
            scan.append({'gameId':str(game['id']),'attacker':attacker,'defender':defender,
                         'targetGoalies':proofs,'goalieProfileEvidenced':complete,
                         'attackableWeakZoneFound':any(bool(p['weakZones']) for p in proofs),
                         'oppositeDirectionMustAlsoBeReviewed':True})
            if not complete:error.append(f"G0 {game['id']} {attacker} attacking {defender}: independent source-backed goalie sample or peer review incomplete")
    return scan,error



def g0_source_coherent_scorer_goalie(game, direction, starter):
    """Carry the G0 deciding *source*, not an unrelated empty EDGE profile,
    into the original per-skater G0/G3/G5 route checks.

    A same-cohort official NHL PBP goalie comparison is sometimes the only
    measured source that G0 used to pick the attack side (e.g. VGK's starter
    has no separately qualified NHL EDGE weak area). Previously the source
    DID decide G0, yet skater evaluation silently reverted to the old empty
    EDGE weakZones and marked every player G0 NOT_EXECUTED. This function
    may NOT create a G0 direction or convert any estimated starter to
    CONFIRMED; it only carries the *same actual historical evidence* through
    the original gates, with the dated goalie ID, population, and source URL.
    """
    if not (isinstance(direction,dict) and
            direction.get('g0SelectionMethod') ==
                'ALL_SOURCE_REVIEWED_STARTER_PAIRS_AGREE' and
            direction.get('attacker') in (game['away'],game['home']) and
            starter and isinstance(starter.get('data'),dict)):
        return starter
    base=starter['data']
    if base.get('weakZones'):
        return starter  # Never replace an already source-qualified NHL EDGE lane
    gid=str(base.get('goalieId') or '')
    receipts=(direction.get('g0DecisionProof') or {}).get('pairwiseReceipts') or []
    if not receipts or not all(
        rec.get('attacker')==direction['attacker'] and
        rec.get('sourceDecisionMethod') in (
            'SAME_HISTORICAL_OFFICIAL_PBP_GOALIE_PEER_POOL',
            'SAME_HISTORICAL_OFFICIAL_PBP_ONE_SIDED_WEAKNESS') and
        gid in (str(rec.get('goalieA')),str(rec.get('goalieB'))) and
        (rec.get('proof') or {}).get('sourceCoherentIndependentHistoricalSample') is True
        for rec in receipts):
        return starter
    populations={str((rec.get('proof') or {}).get('samePeerPopulationId') or '') for rec in receipts}
    if len(populations)!=1 or not next(iter(populations)):
        return starter
    peer=(game.get('goaliePeerContexts') or {}).get(gid)
    if not receipt(peer):
        return starter
    data=peer.get('data') or {}
    weak=data.get('weakZones') or {}
    if not (
        str(data.get('goalieId'))==gid and
        data.get('samplePeerPopulationId') in populations and
        data.get('sourceClass')=='INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY' and
        data.get('peerSampleNeverLeagueEDGEPercentile') is True and
        isinstance(weak,dict) and bool(weak) and
        isinstance(data.get('sample'),dict) and
        isinstance(data.get('counterevidence'),dict) and
        type(data.get('fullySourceComparedAreas')) is int and
        data['fullySourceComparedAreas']>0 and
        all(type(v.get('shotsAgainst')) is int and v['shotsAgainst']>=20 and
            type(v.get('goalsAgainst')) is int and 0<v['goalsAgainst']<=v['shotsAgainst'] and
            v.get('peerComparedSameOrigin') is True and
            type(v.get('peerGoaliesSampled')) is int and v['peerGoaliesSampled']>=4
            for v in weak.values())):
        return starter
    # Keep the original starter identity/status. Every derived vulnerability
    # comes as one coherent official PBP peer source, never a hybrid with EDGE.
    pdata={**base,
        'weakZones':weak,
        'strengthZones':data.get('strengthZones') or {},
        'sample':data['sample'],
        'counterevidence':data['counterevidence'],
        'fullySourceComparedAreas':data['fullySourceComparedAreas'],
        'sourceReviewed':True,
        'sourceClass':data['sourceClass'],
        'sourceType':data.get('sourceType'),
        'evidenceScope':'INDEPENDENT_HISTORICAL_OFFICIAL_PBP_RINK_ORIGIN',
        'goalieProfileSourceUrl':peer['sourceUrl'],
        'goalieProfileObservedAt':peer['observedAt'],
        'goalieProfileEvidenceId':peer.get('evidenceId'),
        'samePeerPopulationId':data['samplePeerPopulationId'],
        'sourceCoherentG0ToG5':True,
        'notGoalMouthAnatomy':True}
    return {**starter,'data':pdata}

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


def _source_route_rows(data, source_url=None):
    """Return every independently measured own shot-origin route without ranking it."""
    data=data if isinstance(data,dict) else {}
    raw=data.get('allRoutes')
    if not isinstance(raw,list) or not raw:
        if data.get('zone'):
            raw=[{'zone':data.get('zone'),'sog':data.get('attempts'),
                  'ownedGoals':data.get('ownedGoals'),'sourceUrl':source_url}]
        else:
            raw=[]
    rows=[]
    for item in raw:
        if not isinstance(item,dict):
            continue
        zone=item.get('zone')
        shots=item.get('sog',item.get('attempts'))
        goals=item.get('ownedGoals')
        if (not isinstance(zone,str) or not zone or type(shots) is not int
                or shots<0 or type(goals) is not int or not 0<=goals<=shots):
            continue
        rows.append({**item,'zone':zone,'sog':shots,'attempts':shots,
                     'ownedGoals':goals,'sourceUrl':item.get('sourceUrl') or source_url})
    return rows


def player_releases(p):
    """Return all own routes and independently review each route's shot mechanism."""
    b=p.get('release')
    if not receipt(b):
        return None
    data=b['data']
    routes=_source_route_rows(data,b.get('sourceUrl'))
    if not routes:
        return None
    mechanism_rows=[]
    shot_wrapper=p.get('shotMechanism') or {}
    shot_data=shot_wrapper.get('data') or {}
    slate_date=data.get('slateDate') or shot_data.get('slateDate')
    for route in routes:
        route_data={**data,**route,'zone':route['zone'],
                    'attempts':route['attempts'],'ownedGoals':route['ownedGoals']}
        review=shooter_mechanism(p,route_data,slate_date)
        mechanism_rows.append({**route,'mechanismReview':review,
                               'mechanismSupported':review.get('supported') is True})
    supported=[x for x in mechanism_rows if x['mechanismSupported']]
    types=sorted({kind for x in supported
                  for kind in (x['mechanismReview'].get('observedShotTypes') or [])})
    source_ids=sorted({url for x in supported
                       for url in (x['mechanismReview'].get('sourceIds') or [])
                       if isinstance(url,str) and url.startswith('https://')})
    event_map={}
    for x in supported:
        for event in x['mechanismReview'].get('ownMechanismEvents') or []:
            key=(str(event.get('gameId')),str(event.get('eventId')))
            event_map[key]=event
    archetype=('observed '+', '.join(types)+' release') if types else next(
        (x['mechanismReview'].get('archetype') for x in supported
         if x['mechanismReview'].get('archetype')),None)
    mechanism={
        'supported':bool(supported),'archetype':archetype,
        'observedShotTypes':types,'ownMechanismEvents':list(event_map.values()),
        'sourceIds':source_ids,
        'supportedZones':sorted({x['zone'] for x in supported}),
        'originOnlyIsNotArchetype':not bool(supported),
        'setupDependenceNotInferred':True,
        'reboundOrShotQualityNotInferred':True,
        'goalMouthPlacementNotInferred':True,
    }
    g0_applied=isinstance(data.get('g0MatchedOwnOriginRoutes'),list)
    if isinstance(data.get('g9ViableRoutes'),list):
        selected=_source_route_rows({'allRoutes':data['g9ViableRoutes']},b.get('sourceUrl'))
    elif g0_applied:
        selected=_source_route_rows({'allRoutes':data.get('g0MatchedOwnOriginRoutes') or []},b.get('sourceUrl'))
    else:
        selected=[x for x in routes if x['zone']==data.get('zone')]
    unique=selected[0] if len(selected)==1 else None
    return {**data,'allRoutes':routes,
            'g0MatchedOwnOriginRoutes':_source_route_rows(
                {'allRoutes':data.get('g0MatchedOwnOriginRoutes') or []},b.get('sourceUrl')),
            'g0RouteSelectionApplied':g0_applied,
            'g9ViableRoutes':_source_route_rows(
                {'allRoutes':data.get('g9ViableRoutes') or []},b.get('sourceUrl')),
            'routeReviews':mechanism_rows,'mechanismReview':mechanism,
            'zone':unique['zone'] if unique else None,
            'attempts':unique['attempts'] if unique else None,
            'ownedGoals':unique['ownedGoals'] if unique else None,
            'sourceUrl':b['sourceUrl'],'observedAt':b['observedAt']}


def release_matched_to_g0_target(player,goalie_profile):
    """Apply G0 only: preserve EVERY own route matching the decided goalie weakness.

    G9 defensive coverage is later in the master order and is deliberately not
    an input here. Multiple G0-matched routes remain a route set; no historical
    primary, G9 preference or arbitrary tie-break chooses one before G5.
    """
    wrapper=player.get('release')
    if not receipt(wrapper):
        return player
    base=wrapper['data']
    routes=_source_route_rows(base,wrapper.get('sourceUrl'))
    if not routes:
        return player
    raw_routes=base.get('allRoutes')
    source_complete=(bool(routes) and (
        not isinstance(raw_routes,list) or len(routes)==len(raw_routes)))
    weak=(goalie_profile.get('data') or {}).get('weakZones') or {}
    matching=[x for x in routes if x['zone'] in weak]
    data={**base,'allRoutes':routes,
          'g0MatchedOwnOriginRoutes':matching,
          'g0MatchedOwnOriginRouteZones':sorted({x['zone'] for x in matching}),
          'g0RouteEvidenceComplete':source_complete,
          'g0RouteSelectionApplied':True,
          'g0RouteSelectionBasis':'G0_ONLY_GOALIE_WEAKNESS_ROUTE_SET',
          'g9RouteSelectionDeferred':True,
          'tonightRouteSelectionBasis':'G0_GOALIE_WEAKNESS_ROUTE_SET',
          'tonightRouteUnresolved':False,
          'originalPrimaryOrigin':base.get('zone')}
    unique=matching[0] if len(matching)==1 else None
    data.update({'zone':unique['zone'] if unique else None,
                 'attempts':unique['attempts'] if unique else None,
                 'ownedGoals':unique['ownedGoals'] if unique else None})
    return {**player,'release':{**wrapper,'data':data}}


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



def _tonight_route_comparison(candidate_zone, rival_zone, goalie_zones, coverage):
    """Source-comparable G0 + G9 opponent vulnerability for two scoring lanes.

    One opposing goalie is shared between the players; no skater's historical
    GOALS can declare a winner. NHL EDGE league and source-consistent PBP
    sampled-peer percentiles are *different populations*, not interchangeable.
    The defender may be independently vulnerable in on-net shots OR attempts.
    Compare identical methods only; otherwise preserve unresolved status.
    """
    if not isinstance(goalie_zones,dict) or not isinstance(coverage,dict):
        return None
    if candidate_zone==rival_zone:
        return None
    zones=coverage.get("zoneConcessions") or {}
    def observed(zone):
        goalie=goalie_zones.get(zone) or {}
        defense=zones.get(zone) or {}
        shots=goalie.get("shotsAgainst"); goals=goalie.get("goalsAgainst")
        if not (type(shots) is int and shots>=20 and
                type(goals) is int and 0<=goals<=shots):
            return None
        league=goalie.get("leagueSavePctgPercentile")
        sampled=goalie.get("samplePeerSavePctgPercentile")
        if type(league) in (int,float) and 0<=league<=1:
            method="NHL_EDGE_LEAGUE"
            pct=league
        elif (type(sampled) in (int,float) and 0<=sampled<=1
              and type(goalie.get("peerGoaliesSampled")) is int
              and goalie["peerGoaliesSampled"]>=4
              and goalie.get("samplePeerPopulationStable") is True
              and goalie.get("samplePeerPopulationId")):
            method="OFFICIAL_PBP_STABLE_PEERS:"+str(goalie["samplePeerPopulationId"])
            pct=sampled
        else:
            return None
        supported=defense.get("positiveConcessionBases") or []
        options={}
        onnet=defense.get("onNetShotsPerGame")
        peer_net=defense.get("peerMedianOnNetShotsPerGame")
        if ("ON_NET_SHOTS_AGAINST_PEER" in supported and
            defense.get("independentOnNetConcessionReview") is True and
            type(onnet) in (int,float) and type(peer_net) in (int,float) and
            onnet>peer_net>0):
            options["G9_ON_NET_VS_PEERS"]=onnet/peer_net
        attempts=defense.get("attemptsPerGame")
        peer_attempts=defense.get("peerMedianAttemptsPerGame")
        if ("ATTEMPTS_AGAINST_PEER" in supported and
            type(attempts) in (int,float) and
            type(peer_attempts) in (int,float) and
            attempts>peer_attempts>0):
            options["G9_ATTEMPTS_VS_PEERS"]=attempts/peer_attempts
        if not options:
            return None
        return {"savePercentile":pct, "goaliePeerMethod":method,
                "defensiveMethods":options,"goalieSource":goalie.get("sourceUrl")}
    a,b=observed(candidate_zone),observed(rival_zone)
    if a is None or b is None or a["goaliePeerMethod"]!=b["goaliePeerMethod"]:
        return None
    # On-net direct scoring opportunity is the first common comparable
    # method. When not shared, attempts against peers is independently
    # admissible under the original G9. No combined scoring weights.
    common=set(a["defensiveMethods"]) & set(b["defensiveMethods"])
    if "G9_ON_NET_VS_PEERS" in common:
        method="G9_ON_NET_VS_PEERS"
    elif "G9_ATTEMPTS_VS_PEERS" in common:
        method="G9_ATTEMPTS_VS_PEERS"
    else:
        return None
    a_exposure=a["defensiveMethods"][method]
    b_exposure=b["defensiveMethods"][method]
    a_better=(a["savePercentile"]<=b["savePercentile"] and
              a_exposure>=b_exposure)
    b_better=(b["savePercentile"]<=a["savePercentile"] and
              b_exposure>=a_exposure)
    result=("UNSEPARATED" if a_better==b_better else
            "CANDIDATE" if a_better else "RIVAL")
    return {"result":result,"candidate":a,"rival":b,
            "candidateZone":candidate_zone,"rivalZone":rival_zone,
            "comparableGoaliePeerMethod":a["goaliePeerMethod"],
            "comparableDefenseConcessionMethod":method,
            "sourceScope":"SAME_OPPONENT_GOALIE_AND_DEFENSE_PREPUCK",
            "noHistoricalGoalsUsedForDecision":True,
            "notGoalMouthAnatomy":True,"noWeightsOrOdds":True}



def _same_lane_tonight_shot_opportunity(candidate, rival, candidate_route,
                                       rival_route, goalie_areas, defense_areas):
    """Same-lane recipients: compare recent dated own shots per actual appearance.

    NHL EDGE season-to-date SOG totals are not tonight's access and cannot
    defeat a teammate. Once G0/G9 establish the same vulnerable lane, the only
    player-level separator here is a complete recent official PBP lane sample,
    normalized by each player's actual boxscore appearances. Exact cross
    multiplication avoids rounding; equal or missing evidence stays unresolved.
    """
    zone=candidate_route.get('zone')
    if (not zone or zone!=rival_route.get('zone') or
            zone not in (goalie_areas or {}) or
            (defense_areas is not None and zone not in defense_areas)):
        return None
    sources=[]
    recent_routes=[]
    recurring_pressure=[]
    for player in (candidate,rival):
        deployment=player.get('deployment')
        pressure=player.get('pressure')
        d=evidence_data(deployment) or {}
        p=evidence_data(pressure) or {}
        shot_review=observed_own_shot_appearances(p)
        if not (receipt(player.get('release')) and receipt(deployment) and
                receipt(pressure) and isinstance(d.get('EV'),str) and d['EV']
                and d.get('status') in ('CONFIRMED','PROJECTED') and
                shot_review.get('datedAppearanceAlignmentVerified') is True):
            return None
        route=independently_dated_origin_route(player,zone)
        if route is None or route.get('appearanceCount',0)<2:
            return None
        recent_routes.append(route)
        # A complete observed zero/one-off sample is still comparison
        # evidence. Requiring BOTH players to demonstrate recurring pressure
        # made a cold rival protect itself from an otherwise sourced defeat.
        # G11 independently requires recurrence for any eventual selection.
        recurring_pressure.append(shot_review.get('repeatedOwnShotPressure') is True)
        sources.extend([deployment['sourceUrl'],pressure['sourceUrl'],
                        player['recentOrigin']['sourceUrl']])
    candidate_recent,rival_recent=recent_routes
    # Compare shots/actual appearance by exact integer cross-product, never
    # cumulative NHL EDGE season shots or goal totals.
    left=(candidate_recent['shotsOnGoal']*rival_recent['appearanceCount'])
    right=(rival_recent['shotsOnGoal']*candidate_recent['appearanceCount'])
    result=('CANDIDATE' if left>right else
            'RIVAL' if right>left else 'UNSEPARATED')
    comparison={
        'candidate':{'recentSameLaneOnNetShots':candidate_recent['shotsOnGoal'],
                     'actualAppearances':candidate_recent['appearanceCount'],
                     'positiveShotAppearances':candidate_recent['positiveShotAppearances'],
                     'rateNumerator':candidate_recent['shotsOnGoal'],
                     'rateDenominator':candidate_recent['appearanceCount']},
        'rival':{'recentSameLaneOnNetShots':rival_recent['shotsOnGoal'],
                 'actualAppearances':rival_recent['appearanceCount'],
                 'positiveShotAppearances':rival_recent['positiveShotAppearances'],
                 'rateNumerator':rival_recent['shotsOnGoal'],
                 'rateDenominator':rival_recent['appearanceCount']},
        'comparison':'RECENT_OFFICIAL_PBP_SAME_LANE_SHOTS_PER_ACTUAL_APPEARANCE',
        'decisionByExactIntegerCrossProduct':True,
        'candidateCrossProduct':left,'rivalCrossProduct':right,
        'seasonEdgeCumulativeShotsNotUsed':True,
        'seasonOrRecentOwnedGoalTotalsNotUsed':True,
        'sampleGameIds':{'candidate':candidate_recent['sampleGameIds'],
                         'rival':rival_recent['sampleGameIds']},
        'sampleDates':{'candidate':candidate_recent['sampleDates'],
                       'rival':rival_recent['sampleDates']},
        'sourceUrls':sorted(set(candidate_recent['sourceUrls']+rival_recent['sourceUrls'])),
        'notProofOfFutureGoal':True,
    }
    return {'result':result,
            'sourceScope':'TONIGHT_G0_G9_SAME_LANE_PLUS_RECENT_DATED_PBP',
            'sameLaneRecentShotComparison':comparison,
            'bothHaveRecurringOwnShotPressure':all(recurring_pressure),
            'recurringOwnShotPressure':{
                'candidate':recurring_pressure[0],'rival':recurring_pressure[1]},
            'selectedRecipientStillRequiresIndependentG11':True,
            'bothHaveSourcedTonightEVDeployment':True,
            'seasonEdgeCumulativeShotsNotUsed':True,
            'seasonOrRecentOwnedGoalsNeverCompared':True,
            'notProofOfFutureGoal':True,
            'sourceUrls':sorted(set(sources+comparison['sourceUrls']))}


def _same_lane_bounded_shot_opportunity(candidate, rival, candidate_route,
                                        rival_route, goalie_areas, defense_areas):
    """Resolve only a PROVABLE, strict recent same-lane shot-rate advantage.

    Partial official PBP rink coordinates never become zeros. One shooter
    defeats another only if their documented lower bound exceeds the other's
    highest possible on-net shot rate under the same recorded appearances.
    The original exact-sample comparator remains preferred and unchanged.
    """
    zone = candidate_route.get("zone")
    if (not zone or zone != rival_route.get("zone")
        or zone not in (goalie_areas or {})
        or (defense_areas is not None and zone not in defense_areas)):
        return None
    rows = []
    sources = []
    for p in (candidate, rival):
        deploy = p.get("deployment")
        pressure = p.get("pressure")
        d = evidence_data(deploy) or {}
        review = observed_own_shot_appearances(evidence_data(pressure) or {})
        if (not receipt(p.get("release")) or not receipt(deploy)
            or not receipt(pressure) or not d.get("EV")
            or d.get("status") not in ("PROJECTED", "CONFIRMED")
            or review.get("datedAppearanceAlignmentVerified") is not True):
            return None
        bound = independently_bounded_origin_route(p, zone)
        if not bound or bound.get("appearanceCount", 0) < 2:
            return None
        rows.append(bound)
        sources.extend([deploy["sourceUrl"], pressure["sourceUrl"]])
        sources.extend(bound["sourceUrls"])
    a, b = rows
    a_lower = a["shotsOnGoalLowerBound"] * b["appearanceCount"]
    b_upper = b["shotsOnGoalUpperBound"] * a["appearanceCount"]
    b_lower = b["shotsOnGoalLowerBound"] * a["appearanceCount"]
    a_upper = a["shotsOnGoalUpperBound"] * b["appearanceCount"]
    result = ("CANDIDATE" if a_lower > b_upper else
              "RIVAL" if b_lower > a_upper else "UNSEPARATED")
    return {
        "result": result,
        "sourceScope": "TONIGHT_G0_G9_SAME_LANE_PLUS_OFFICIAL_PBP_CONSERVATIVE_BOUNDS",
        "comparison": "STRICT_RECENT_OWN_LANE_SHOT_RATE_BOUNDS_PER_ACTUAL_APPEARANCE",
        "candidate": a, "rival": b,
        "candidateLowerCrossProduct": a_lower,
        "rivalUpperCrossProduct": b_upper,
        "rivalLowerCrossProduct": b_lower,
        "candidateUpperCrossProduct": a_upper,
        "missingShotLocationsNeverTreatedAsZero": True,
        "historicalGoalTotalsNeverUsed": True,
        "sameOpponentWeakGoalieAndDefenseRouteRequired": True,
        "noWeightsOddsOrPPShortcut": True,
        "notProofOfFutureGoal": True,
        "sourceUrls": sorted(set(sources)),
    }


def challenger_proof(candidate, challengers, goalie_weak_zones, defense_weak_zones=None,
                     opponent_coverage=None):
    """Compare every viable candidate and rival route after G0, G5 and G9.

    Candidate routes are the G9-filtered set when supplied. Rival routes are
    independently filtered against the same G0 goalie weakness and G9 defense.
    One candidate route must defeat every viable route of a rival; a rival
    dominates only when one rival route defeats every candidate route.
    """
    base=player_releases(candidate)
    if not base:
        return None,[]
    goalie_areas=set(goalie_weak_zones or {})
    defensive_areas=(set(defense_weak_zones)
                     if defense_weak_zones is not None else None)

    def viable_routes(release, candidate_side=False):
        if candidate_side and isinstance(release.get('g9ViableRoutes'),list):
            raw=release['g9ViableRoutes']
        elif candidate_side and isinstance(release.get('g0MatchedOwnOriginRoutes'),list):
            raw=release['g0MatchedOwnOriginRoutes']
        else:
            raw=release.get('allRoutes') or []
        rows=_source_route_rows({'allRoutes':raw},release.get('sourceUrl'))
        return [x for x in rows if x['zone'] in goalie_areas and
                (defensive_areas is None or x['zone'] in defensive_areas)]

    candidate_routes=viable_routes(base,True)
    if not candidate_routes:
        return None,[]
    rows=[];all_defeated=True
    for rival in challengers:
        if str(rival['id'])==str(candidate['id']):
            continue
        wrapper=rival.get('release')
        release=player_releases(rival)
        if not release:
            zero=rival.get('zeroShotOriginProof')
            zdata=evidence_data(zero)
            if (receipt(zero) and
                zdata.get('sourceType') in (
                    'NHL_EDGE_SKATER_SHOT_ORIGIN_CURRENT_SEASON',
                    'NHL_OFFICIAL_PLAYER_DATED_REGULAR_SEASON_GAME_LOG') and
                zdata.get('verifiedNoSameLaneOnNetRoute') is True and
                zdata.get('observedOnNetShotsAcrossAllReportedOrigins')==0 and
                zdata.get('ownedGoalsAcrossAllReportedOrigins')==0):
                rows.append({'challengerId':str(rival['id']),
                             'status':'SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE',
                             'sourceUrls':[zero['sourceUrl']],
                             'evidenceId':zero.get('evidenceId'),
                             'noClaimOfFutureScoringImpossibility':True,
                             'sourceVerifiedZeroShotSeason':True,
                             'sourceEvidenceType':zdata.get('sourceType')})
                continue
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
        all_routes=release.get('allRoutes') or []
        viable=viable_routes(release,False)
        if not viable:
            rows.append({'challengerId':str(rival['id']),
                         'status':'DIFFERENT_TARGET_LANE',
                         'candidateZones':sorted({x['zone'] for x in candidate_routes}),
                         'rivalKnownAreas':[x.get('zone') for x in all_routes],
                         'G0GoalieWeakZones':sorted(goalie_areas),
                         'G9DefensiveWeakZones':sorted(defensive_areas)
                             if defensive_areas is not None else None,
                         'noneOfKnownRivalOriginsJointlyMatchG0G9':True,
                         'notEvidenceRivalCannotScoreTonight':True,
                         'sourceUrls':[wrapper['sourceUrl']]})
            continue

        route_comparisons=[]
        for candidate_route in candidate_routes:
            for rival_route in viable:
                if candidate_route['zone']==rival_route['zone']:
                    matchup=(_same_lane_tonight_shot_opportunity(
                        candidate,rival,candidate_route,rival_route,
                        goalie_weak_zones,defensive_areas) or
                        _same_lane_bounded_shot_opportunity(
                        candidate,rival,candidate_route,rival_route,
                        goalie_weak_zones,defensive_areas))
                else:
                    matchup=_tonight_route_comparison(
                        candidate_route['zone'],rival_route['zone'],
                        goalie_weak_zones,opponent_coverage)
                route_comparisons.append((candidate_route,rival_route,matchup))

        winning_candidate_routes=[]
        for candidate_route in candidate_routes:
            defeats_every_rival_route=all(
                any(c['zone']==candidate_route['zone'] and
                    r['zone']==rival_route['zone'] and proof is not None and
                    proof.get('result')=='CANDIDATE'
                    for c,r,proof in route_comparisons)
                for rival_route in viable)
            if defeats_every_rival_route:
                winning_candidate_routes.append(candidate_route)

        dominating_rival_routes=[]
        for rival_route in viable:
            defeats_every_candidate_route=all(
                any(c['zone']==candidate_route['zone'] and
                    r['zone']==rival_route['zone'] and proof is not None and
                    proof.get('result')=='RIVAL'
                    for c,r,proof in route_comparisons)
                for candidate_route in candidate_routes)
            if defeats_every_candidate_route:
                dominating_rival_routes.append(rival_route)

        dominates=bool(winning_candidate_routes) and not bool(dominating_rival_routes)
        defeated_by=bool(dominating_rival_routes) and not bool(winning_candidate_routes)
        status=('DEFEATED' if dominates else
                'RIVAL_DOMINATES' if defeated_by else
                'NO_DECISIVE_ROUTE_SEPARATION')
        if status!='DEFEATED':
            all_defeated=False
        candidate_report=(winning_candidate_routes[0] if len(winning_candidate_routes)==1
                          else candidate_routes[0])
        rival_report=(dominating_rival_routes[0] if len(dominating_rival_routes)==1
                      else viable[0])
        witness=next((proof for c,r,proof in route_comparisons
                      if c['zone']==candidate_report['zone'] and
                         r['zone']==rival_report['zone'] and proof is not None),None)
        same_lane=any(c['zone']==r['zone'] for c,r,_ in route_comparisons)
        recent_proofs=[proof for c,r,proof in route_comparisons
                       if c['zone']==r['zone'] and proof is not None]
        decision_basis=(
            'TONIGHT_G0_G9_MATCHUP_PLUS_DATED_SAME_LANE_SHOT_RATE'
            if (dominates or defeated_by) and recent_proofs else
            'TONIGHT_OPPONENT_GOALIE_AND_DEFENSE_ALL_CANDIDATE_AND_RIVAL_ROUTES'
            if dominates or defeated_by else
            'UNRESOLVED_TONIGHT_RECIPIENT_MATCHUP_NO_HISTORICAL_FALLBACK')
        sources={candidate['release']['sourceUrl'],wrapper['sourceUrl']}
        for _,_,proof in route_comparisons:
            if proof:
                sources.update(proof.get('sourceUrls',[]))
        candidate_routes_report=[
            {'zone':x['zone'],'shotsOnGoal':x['attempts'],
             'ownedGoals':x['ownedGoals']} for x in candidate_routes]
        rival_routes_report=[
            {'zone':x['zone'],'shotsOnGoal':x['attempts'],
             'ownedGoals':x['ownedGoals']} for x in viable]
        rows.append({
            'challengerId':str(rival['id']),'status':status,
            'candidate':{'zone':candidate_report['zone'],
                         'shotsOnGoal':candidate_report['attempts'],
                         'ownedGoals':candidate_report['ownedGoals']},
            'challenger':{'zone':rival_report['zone'],
                          'shotsOnGoal':rival_report['attempts'],
                          'ownedGoals':rival_report['ownedGoals']},
            'candidateRoutes':candidate_routes_report,
            'challengerRoutes':rival_routes_report,
            'candidateWinningRoutes':[
                {'zone':x['zone'],'shotsOnGoal':x['attempts'],
                 'ownedGoals':x['ownedGoals']} for x in winning_candidate_routes],
            'rivalDominatingRoutes':[
                {'zone':x['zone'],'shotsOnGoal':x['attempts'],
                 'ownedGoals':x['ownedGoals']} for x in dominating_rival_routes],
            'sourceUrls':sorted(set(u for u in sources if isinstance(u,str) and u.startswith('https://'))),
            'independentRecentTieReview':recent_proofs or None,
            'tonightMatchupComparison':witness,
            'allViableRivalRouteComparisons':[
                {'candidateZone':c['zone'],'zone':r['zone'],'matchup':proof}
                for c,r,proof in route_comparisons],
            'decisionBasis':decision_basis,
            'historicalTotalsCannotSetRecipient':True,
            'historicalTotalsNeverOverrideMeasuredTonightMatchup':True,
            'sameLane':same_lane,
            'rivalAlternateGoalieWeakLane':any(
                c['zone']!=r['zone'] for c,r,_ in route_comparisons),
            'allViableCandidateZones':sorted({x['zone'] for x in candidate_routes}),
            'allRivalJointlyViableZones':sorted({x['zone'] for x in viable}),
            'goalieWeaknessAndDefenseBothRequired':defensive_areas is not None,
            'rivalEVRole':evidence_data(rival.get('deployment')),
            'roleReviewIncomplete':not receipt(rival.get('deployment')),
            'noSeasonTotalInvented':True,
            'comparisonPriority':[
                'G0 goalie peer vulnerability in tonight opponent lane',
                'G9 tonight opponent defensive on-net exposure',
                'Every viable candidate and rival scoring lane compared, not just historical best'],
            'noFameOddsOrPPShortcut':True,
            'sameLaneSeasonCumulativeCountsNotUsed':True,
            'rule':'one source-backed candidate route must defeat every viable direct rival route; no season cumulative fallback',
        })
    return all_defeated,rows


def adjudicate_scoring_path(player, teammates, release, goalie_profile, coverage,
                            dispositions, challenger_rows, who_supported):
    """Determine PRIMARY / TRANSFER / WHO from positive gate evidence only.

    This runs AFTER G0, direct route, goal recipient, G10.5 and G17 decisions.
    Never fill a label quota; never label the lack of WHO/TRANSFER as PRIMARY.
    Requiring direct evidence for each named path prevents the old automatic
    'else PRIMARY' behavior.
    """
    own=evidence_data(player.get('finishOwnership')) or {}
    goalie_data=evidence_data(goalie_profile) or {}
    cover=evidence_data(coverage) or {}
    zone=(release or {}).get('zone')
    all_gates=all(dispositions.get(g,{}).get('disposition')=='PASS'
                  for g in ('G0','G3','G4','G5','G6','G7','G9',
                            'G10','G10.5','G12','G15','G16','G17'))
    # G15 has already separately certified either OWN scored goals in this
    # target lane, or a fully reconciled OWN season-goal record AND observed
    # own on-net shots from this exact goalie/defense-matched lane. G18 only
    # assembles a proved route; it must not silently reintroduce the old
    # exact-lane-scored-goal demand that was repaired at G15.
    g15=dispositions.get('G15') or {}
    finisher=(g15.get('details') or {})
    lane_scored=bool(release and type(release.get('ownedGoals')) is int
                     and release['ownedGoals']>0)
    own_lanes_shot=bool(release and type(release.get('attempts')) is int
                        and release['attempts']>0)
    cross_origin_finisher=bool(
        g15.get('disposition')=='PASS' and
        finisher.get('fullSeasonGoalCreditsReconciledAgainstEdgeOrigins') is True and
        finisher.get('matchedOriginHasHistoricalGoal') is False and
        type(finisher.get('officialOwnedGoalsInMatchedOrigin')) is int and
        finisher['officialOwnedGoalsInMatchedOrigin']==0 and
        type(finisher.get('officialDatedSeasonGoals')) is int and
        finisher['officialDatedSeasonGoals']>0 and
        type(finisher.get('totalOwnedGoalsFromEveryNhlEdgeOrigin')) is int and
        finisher['totalOwnedGoalsFromEveryNhlEdgeOrigin']==
            finisher['officialDatedSeasonGoals'] and
        type(finisher.get('matchedOriginOwnOnNetShots')) is int and
        finisher['matchedOriginOwnOnNetShots']==(release or {}).get('attempts') and
        finisher['matchedOriginOwnOnNetShots']>0 and
        finisher.get('sameLaneGoalsNotInferredFromScoringElsewhere') is True and
        finisher.get('directFinisherEvidenceMethod')==
        'OFFICIAL_FULL_SEASON_GOALS_MATCH_ALL_EDGE_OWN_ORIGINS_AND_SOURCED_MATCHED_LANE_SHOTS')
    credited_finisher=bool(lane_scored or cross_origin_finisher)
    direct={
        'G0ThruG17SourcePass':all_gates,
        'independentOwnScoringSource':receipt(player.get('release')),
        'observedOwnOnNetShotsInSelectedLane':own_lanes_shot,
        'goalieWeakAreaDirectlyMatched':bool(zone and zone in (goalie_data.get('weakZones') or {})),
        'independentDefenseAreaDirectlyMatched':bool(zone and zone in
            (cover.get('greenWeakZones') or [])),
        'historicallyCreditedIndependentGoalRecipient':bool(
            own.get('recipient') is True and
            own.get('creditedGoalsVerified') is True and
            receipt(player.get('release')) and credited_finisher and
            g15.get('disposition')=='PASS'),
        'allRelevantChallengersReviewed':bool(dispositions.get('G10.5',{}).get('disposition')=='PASS'
            and dispositions.get('G16',{}).get('disposition')=='PASS'),
        'opponentContradictionsReviewed':bool(dispositions.get('G17',{}).get('disposition')=='PASS'),
        'verifiedEVAccess':receipt(player.get('deployment')),
    }
    route_direct=all(direct.values())
    original=(release or {}).get('originalPrimaryOrigin')
    changed_lane=bool(original and original!=zone)
    # A tie in the player's PRE-G0 usual-lane origin is not an additional
    # gate AFTER a fully source-certified goalie-first attack. G0/G4/G5/G9,
    # G10.5 and G17 have already tested the exact own route and rival paths.
    # If that source-supported route did not change lane and every direct
    # gate passed, classify the direct recipient PRIMARY rather than
    # silently rejecting the game's survivor at G18. Incomplete or
    # contradictory paths still have route_direct=False and cannot pass.
    # No new ranking, player preference, historical goal or shot is inferred.
    primary_source_lane=bool(route_direct)
    approved_rivals=[]
    defeated={str(x.get('challengerId')):x for x in challenger_rows
              if x.get('status')=='DEFEATED' and x.get('sameLane')}
    for rival in teammates:
        rid=str(rival.get('id'))
        proof=defeated.get(rid)
        if not proof:
            continue
        rival_primary=player_releases(rival)
        if not rival_primary or rival_primary.get('zone')!=zone:
            continue
        if not receipt(rival.get('release')):
            continue
        rival_direct=proof.get('challenger') or {}
        base_direct=proof.get('candidate') or {}
        if (rival_primary.get('ownedGoals',0)>0 and
            type(rival_direct.get('ownedGoals'))==int and
            type(base_direct.get('ownedGoals'))==int and
            # G10.5 can use shot volume to separate competing shooters,
            # but it cannot claim a direct PRIMARY goal recipient was
            # displaced by a TRANSFER when their observed OWN goals tie.
            # Historical on-net shot pressure is not credited goal ownership.
            base_direct['ownedGoals']>rival_direct['ownedGoals']):
            approved_rivals.append({
                'displacedDirectPrimaryPlayerId':rid,
                'sameLane':zone,
                'directGoalCreditCandidate':base_direct['ownedGoals'],
                'directGoalCreditPrior':rival_direct['ownedGoals'],
                'rivalOriginalPrimaryOrigin':rival_primary['zone'],
                'sourceUrls':sorted(set(filter(None,proof.get('sourceUrls',[])))),
                'G10_5Verdict':proof['status'],
            })
    # A source can separately verify the prior primary losing the same route;
    # a naked Boolean without a sourced G10.5 defeated rival is insufficient.
    transfer=player.get('transferEvidence')
    tdata=evidence_data(transfer) or {}
    supplied_displaced=(str(tdata.get('displacedPlayerId')) if
                        tdata.get('displacedPlayerId') is not None else None)
    confirmed_displacement=(receipt(transfer) and
        tdata.get('directRouteDisplaced') is True and
        tdata.get('routeZone')==zone and
        any(x['displacedDirectPrimaryPlayerId']==supplied_displaced
            for x in approved_rivals))
    derived_displacement=bool(changed_lane and approved_rivals)
    # The supplied complete master definition requires a defeated competing
    # recipient for TRANSFER. Moving between a player's own areas alone is
    # route adaptation, not evidence of recipient transfer. Keep the lane
    # change visible without inventing a competing player or a label quota.
    off_lane_transfer=False
    who=player.get('whoAnomaly')
    who_data=evidence_data(who) or {}
    physical_anomaly=bool(who_supported and receipt(who) and
        who_data.get('directIndependentRoute') is True and
        isinstance(who_data.get('mechanism'),str) and who_data['mechanism'].strip() and
        direct['goalieWeakAreaDirectlyMatched'] and
        direct['independentDefenseAreaDirectlyMatched'] and all_gates)
    # If two different source-supported mechanisms compete, even the path
    # label must survive contradiction review; there is no WHO-over-TRANSFER
    # priority or arbitrary fallback ordering.
    path_contradiction=bool(physical_anomaly and
        (confirmed_displacement or derived_displacement or off_lane_transfer))
    if path_contradiction:
        path=None
        rationale='Two different sourced physical paths remain unseparated; no preferred label assigned'
    elif physical_anomaly:
        path='WHO'
        rationale='Sourced independent anomaly scoring mechanism survived G14, goalie route and full gates'
    elif route_direct and (confirmed_displacement or derived_displacement):
        path='TRANSFER'
        rationale='Own secondary scoring route defeated independently sourced same-lane original PRIMARY recipient under G10.5'
    elif route_direct and primary_source_lane and not tdata.get('directRouteDisplaced'):
        path='PRIMARY'
        rationale='Independently sourced direct own-goal recipient and primary lane survived goalie, defense and every challenger'
    else:
        path=None
        rationale='No independently sufficient evidence to certify PRIMARY, TRANSFER or WHO for this route'
    sources=sorted({x for x in (
        (player.get('release') or {}).get('sourceUrl'),
        (player.get('finishOwnership') or {}).get('sourceUrl'),
        (player.get('deployment') or {}).get('sourceUrl'),
        (goalie_profile or {}).get('sourceUrl'),
        goalie_data.get('goalieProfileSourceUrl'),
        (coverage or {}).get('sourceUrl'),
        (player.get('contradictions') or {}).get('sourceUrl'),
        (who or {}).get('sourceUrl') if path=='WHO' else None,
        (transfer or {}).get('sourceUrl') if confirmed_displacement else None,
    ) if isinstance(x,str) and x.startswith('https://')})
    sources=sorted(set(sources).union(
        x for rival in approved_rivals for x in rival['sourceUrls']))
    return path,{
        'path':path,'rationale':rationale,
        'scoringLane':zone,
        'originalScoringLane':original,
        'laneChangedAfterGoalieFirstG0':changed_lane,
        'primaryOriginIsSourceDistinct':primary_source_lane,
        'positiveDirectGateEvidence':direct,
        'historicMatchedLaneOwnedGoals':(release or {}).get('ownedGoals'),
        'historicMatchedLaneOwnedGoalsExactlyPreserved':True,
        'G15IndependentFinisherReconciledBeyondMatchedOrigin':cross_origin_finisher,
        'neverClaimUnobservedSameLaneGoals':True,
        'futureAssistOrGoalOutcomeNeverProvedFromHistory':True,
        'G10_5DisplacedPrimaryEvidence':approved_rivals,
        'explicitDisplacementSourceValidated':bool(confirmed_displacement),
        'independentTransferDerivedFromG0AndG10_5':derived_displacement,
        'offUsualLaneTransferIntoGoalieWeakLane':off_lane_transfer,
        'laneChangeAloneDoesNotProveRecipientTransfer':True,
        'G14IndependentWhoAnomalyVerified':physical_anomaly,
        'competingWHOandTRANSFERPathsUnseparated':path_contradiction,
        'whoPhysicalMechanism':who_data.get('mechanism') if physical_anomaly else None,
        'sourceUrls':sources,
        'selectionIndependentOfLabel':True,
        'pathQuotaApplied':False,
        'fallbackToPrimary':False,
        'unknownIsNotAPath':True,
    }



def stopped_before_g10_5(results):
    """Map each player to their pre-G10.5 challenger status.

    Any source-verified ELIMINATED verdict in G0-G10 removes that player
    from later recipient comparisons, even if an earlier gate was
    NOT_EXECUTED. Otherwise preserve the first unresolved gate so missing
    evidence keeps the comparison open. All these decisions occur before
    G10.5; no later gate can rewrite an earlier verdict.
    """
    before=MASTER[:MASTER.index('G10.5')]
    out={}
    for result in results:
        d=result['dispositions']
        eliminated=next((g for g in before
                         if (d.get(g) or {}).get('disposition')=='ELIMINATED'),None)
        if eliminated is not None:
            out[str(result['player']['id'])]=f"{eliminated}:ELIMINATED"
            continue
        unresolved=next((g for g in before
                         if (d.get(g) or {}).get('disposition')!='PASS'),None)
        if unresolved is not None:
            # A missing gate row is an unexecuted decision, not an exception
            # and never an elimination. Keep the challenger unresolved so
            # pregame source recovery can research that gate.
            status=(d.get(unresolved) or {}).get('disposition') or 'NOT_EXECUTED'
            out[str(result['player']['id'])]=f"{unresolved}:{status}"
    return out


def _finish_pool(games,game_pool,card,g16_receipt):
    """Every slate game in schedule order, marked with its Core outcome."""
    core={(str(x['gameId']),str(x['playerId'])) for x in (card or {}).get('current_legs') or []}
    g16={str(f.get('playerId')):f for f in (g16_receipt or {}).get('finalists') or []}
    out=[]
    for match in games:
        e=dict(game_pool.get(str(match['id'])) or {'gameId':str(match['id']),
               'matchup':match['away']+'@'+match['home'],'status':'NOT_EVALUATED'})
        sv=e.get('survivor') or {}
        e['inCore']=(e['gameId'],str(sv.get('playerId')))in core if sv else False
        if sv and str(sv.get('playerId')) in g16:
            f=g16[str(sv['playerId'])]
            e['g16Decision']=f.get('g16Decision'); e['g16DominatedBy']=f.get('dominatedBy')
        e['poolIsDiagnosticAndNeverSelects']=True
        out.append(e)
    return out


def evaluate_skater(game, attack_team, player, teammates, goalie_profile, stage,
                    stopped_before_g10_5=None, defer_g18=False, stop_at_g10=False,
                    g17_review=None, stop_at_g16=False, cross_game_g16=None):
    d={}; proof=[]; deficient=[]; eliminated=False; first_elimination_gate=None
    # Teammates who passed G0-G10 (see stopped_before_g10_5). Only these are
    # meaningful G10.5/G16 challengers, for the master gate and its overlay.
    stopped=dict(stopped_before_g10_5 or {})
    # Only source-verified ELIMINATED teammates leave the challenger pool.
    # Unresolved (NOT_EXECUTED) teammates are still compared: they cannot
    # eliminate anyone, but while unresolved they keep the decision open.
    eliminated_before={k for k,v in stopped.items() if v.endswith(':ELIMINATED')}
    unresolved_before={k for k,v in stopped.items() if not v.endswith(':ELIMINATED')}
    live_teammates=[x for x in teammates if str(x['id'])==str(player['id'])
                    or str(x['id']) not in eliminated_before]
    weak=goalie_profile['data'].get('weakZones',{})
    strong=goalie_profile['data'].get('strengthZones',{})
    release=player_releases(player)
    rec=reconcile_logs(player)
    # Immutable source observations; G7, G11 and overlays decide independently.
    shot_review=observed_own_shot_appearances(evidence_data(player.get('pressure')) or {})
    dated_recurrence=observed_dated_recurrence(rec,shot_review)
    position=player.get('position')
    # G10.5 is the first gate allowed to adjudicate same-lane recipients.
    # Earlier gates must not silently precompute or preselect a winner.
    rows=[]
    wins=None
    overlay=[]
    execution_trace=[]
    # Source observations use their OWN original sequence, Step0..Step14.
    # Their facts are consumed only when the corresponding G0..G17 gate
    # executes, never used to change an earlier gate's decision.
    overlay_at_gate={}
    overlay_execution=[]
    def observation_record(_game,_player,step,status,evidence,ids):
        return {'gate':step,'disposition':status,
                'details':{'evidence':evidence,'sourceIds':list(ids)}}
    def source_steps(step_names, challenger_rows, eliminated_rivals=None):
        observations=independent_overlay(
            game,attack_team,player,live_teammates,goalie_profile,release,rec,
            challenger_rows,stage,receipt,evidence_data,observation_record,
            only_steps=set(step_names),
            eliminated_rivals=(eliminated_before if eliminated_rivals is None
                               else eliminated_rivals))
        for item in observations:
            step=item['gate']
            if step in overlay_at_gate:
                raise ValueError(f'Original overlay step ran twice: {step}')
            overlay_at_gate[step]=item
            overlay_execution.append(step)
    # Overlay checks are invoked just-in-time by their original owner gate.
    # No later overlay operation is precomputed before an earlier master
    # decision, and every independent step is executed exactly once.
    def emit(g, ok, detail, eliminate=False, source_ids=()):
        nonlocal eliminated,first_elimination_gate
        # Every candidate gets an ACTUAL G0-G18 source check. A previous
        # elimination is permanent, but it does NOT excuse skipping later
        # evidence checks or silently calling them completed.
        disp,content=verdict(ok,detail,eliminate)
        if disp=='PASS':
            gaps=audit_gate(g,content,list(source_ids),stage)
            if gaps:
                disp='NOT_EXECUTED'
                content={**content,'semanticProofGaps':gaps,
                         'evidenceReviewedButInsufficient':True}
        if first_elimination_gate:
            content={**content,'alreadyEliminatedAtGate':first_elimination_gate,
                     'laterPositiveEvidenceCannotReinstate':True}
        if disp=='ELIMINATED':
            eliminated=True
            if first_elimination_gate is None:first_elimination_gate=g
        elif disp=='NOT_EXECUTED':
            deficient.append(g)
        # Consume ONLY this gate's previously independently observed source
        # facts. Source functions are checked in Step0..Step14 order, while
        # the master gate decisions remain G0..G18 in their own order.
        expected=STEPS_BY_GATE[g]
        if any(step not in overlay_at_gate for step in expected):
            raise ValueError(f'Overlay source step not ready for {g}: {expected}')
        observations=[overlay_at_gate[step] for step in expected]
        overlay.extend(observations)
        if observations:
            function_evidence=[{
                'step':item['gate'],'disposition':item['disposition'],
                'sourceIds':item['details'].get('sourceIds',[]),
                'evidence':item['details'].get('evidence',{})}
                for item in observations]
            content={**content,'originalFunctionEvidence':function_evidence,
                     # Historical consumers can read the same nested evidence.
                     'independentOverlayEvidence':function_evidence}
            mandatory=[item for item in observations
                       if item['disposition']!='PASS'
                       and item['details'].get('evidence',{}).get('nonblocking') is not True]
            for item in mandatory:
                deficient.append(g+':'+item['gate'])
            if mandatory and disp=='PASS':
                # The original function is part of THIS gate's result, not
                # another veto stage operating after the master sequence.
                disp=('ELIMINATED' if any(
                    x['disposition']=='ELIMINATED' for x in mandatory)
                    else 'NOT_EXECUTED')
                content['ownFunctionDispositions']={
                    x['gate']:x['disposition'] for x in mandatory}
                if disp=='ELIMINATED':
                    eliminated=True
                    if first_elimination_gate is None:first_elimination_gate=g
        d[g]={'disposition':disp,'details':content}
        record=gate_record(game,player['id'],g,disp,content,list(source_ids))
        proof.append(record)
        execution_trace.append(record)
    # G0's per-skater record must point to an attack direction already
    # adjudicated from BOTH goalies. A shared goalie profile is not itself
    # a completed first-gate decision.
    selected_direction=game.get('_g0SelectedDirection') or {}
    goalie_id=str(goalie_profile['data'].get('goalieId') or '')
    direction_ok=bool(
        selected_direction.get('attacker')==attack_team
        and selected_direction.get('defender') in (game['away'],game['home'])
        and any(str(b.get('goalieId'))==goalie_id
                for b in selected_direction.get('targetGoalies',[]))
        and selected_direction.get('goalieProfileEvidenced') is True)
    source_steps(['Step0'],[])
    emit('G0',bool(direction_ok and weak and goalie_profile['data'].get('sample')
                   and goalie_profile['data'].get('counterevidence') is not None),
         {'targetGoalie':goalie_id,'attacker':attack_team,
          'branchStatus':goalie_profile['data'].get('status'),'weakZones':weak,
          'separateGoalieBranch':True,'directionSelectedBeforeSkaters':direction_ok,
          'selectedAttacker':selected_direction.get('attacker'),
          'selectedDefender':selected_direction.get('defender')},
         source_ids=list(filter(None,[
          goalie_profile['sourceUrl'],goalie_profile['data'].get('goalieProfileSourceUrl')])))
    context=evidence_data(game.get('context')) or {}
    has_venue=bool(context.get('venueHome') or context.get('venue'))
    has_rest=(isinstance(context.get('homeRestDays'),int)
              and isinstance(context.get('awayRestDays'),int)) or bool(context.get('rest'))
    context_ok=bool(receipt(game.get('context')) and has_venue and has_rest)
    source_steps(['Step2'],[])
    emit('G1',context_ok,
         {'venueRestTravel':context if context else None,
          'venueReviewed':has_venue,'bothTeamRestReviewed':has_rest,
          'travelUnobservedNotInvented':context.get('travelDistanceNotInSource') is True
              or context.get('travelMiles') is None},
         source_ids=[game.get('context',{}).get('sourceUrl','')])
    roster=game.get('rosters',{}).get(attack_team)
    eligibility=player.get('availability','UNVERIFIED')
    # G2 surveys the WHOLE official current roster, not merely a lineup
    # publication's top lines. "UNVERIFIED" is roster eligibility to be
    # researched, NOT a confirmed dressed status or confirmed deployment.
    roster_member=bool(receipt(roster) and any(
        str(p.get('id'))==str(player.get('id'))
        for p in (roster['data'].get('players') or [])))
    roster_eligible=(roster_member and eligibility in
        ('DRESSED','CONFIRMED','PROJECTED_ACTIVE','UNVERIFIED'))
    source_steps(['Step1'],[])
    emit('G2',bool(roster_eligible),
         {'candidateOnOfficialRoster':roster_member,
          'fullPoolSize':len(teammates),'availability':eligibility,
          'officialCurrentRosterSource':roster.get('sourceUrl') if receipt(roster) else None,
          'position':position,
          'currentRosterNotEquivalentToDressed':True,
          'confirmedDressed':eligibility in ('DRESSED','CONFIRMED'),
          'projectedAvailabilitySourceReviewed':bool(
              eligibility=='PROJECTED_ACTIVE' and
              receipt(player.get('availabilitySource')) and
              evidence_data(player['availabilitySource']).get('status')=='PROJECTED_ACTIVE'),
          'lineupStillRequiresIndependentG6':True},
         eliminate=eligibility in ('OUT','SCRATCHED','INJURED'),
         source_ids=[roster['sourceUrl']] if receipt(roster) else [])
    g3_reviewed=bool(direction_ok and weak and goalie_profile['data'].get('sample')
                      and goalie_profile['data'].get('counterevidence'))
    emit('G3',g3_reviewed,
         {'goalieSample':goalie_profile['data'].get('sample'),
          'goalieWeakZones':weak,
          'goalieStrengthZones':goalie_profile['data'].get('strengthZones'),
          'counterevidence':goalie_profile['data'].get('counterevidence'),
          'opposingGoalieBranchReviewed':direction_ok},
         source_ids=list(filter(None,[goalie_profile['sourceUrl'],
             goalie_profile['data'].get('goalieProfileSourceUrl')])))
     route_reviews=(release or {}).get('routeReviews') or []
     g0_routes=(release or {}).get('g0MatchedOwnOriginRoutes') or []
     if release and not release.get('g0RouteSelectionApplied'):
         g0_routes=[x for x in route_reviews if x.get('zone') in weak]
     g0_zones={x.get('zone') for x in g0_routes}
     g0_route_reviews=[x for x in route_reviews if x.get('zone') in g0_zones]
     g4_supported_routes=[x for x in route_reviews if x.get('mechanismSupported') is True]
     g5_supported_routes=[x for x in g0_route_reviews if x.get('mechanismSupported') is True]
     mechanism=(release or {}).get('mechanismReview') or {
         'supported':False,'archetype':None,'observedShotTypes':[],'sourceIds':[]}
     source_steps(['Step5','Step7'],[])
     emit('G4',bool(g4_supported_routes),
          {'archetype':mechanism.get('archetype'),
           'ownRelease':release,'ownReleaseRoutes':route_reviews,
           'individualMechanismReview':mechanism},
          source_ids=sorted(set(
              ([player.get('release',{}).get('sourceUrl','')]
               if receipt(player.get('release')) else [])+
              mechanism.get('sourceIds',[]))))
     overlap=bool(g5_supported_routes)
     g5_no_source_matched_route=bool(
         release and release.get('g0RouteEvidenceComplete') is True and not g0_routes)
     source_steps(['Step3','Step10'],[])
     emit('G5',overlap,
          {'shooterZone':g5_supported_routes[0]['zone']
               if len(g5_supported_routes)==1 else None,
           'matchedRoutes':[{'zone':x['zone'],'shotsOnGoal':x['attempts'],
                             'ownedGoals':x['ownedGoals'],
                             'mechanismSupported':True}
                            for x in g5_supported_routes],
           'weakZones':weak,'goalieStrengthZones':strong,
           'tonightRouteSelectionBasis':'G0_ONLY_GOALIE_WEAKNESS_ROUTE_SET',
           'tonightRouteUnresolved':False,
           'routeSelectionNotInfluencedByG9':True},
          eliminate=g5_no_source_matched_route,
          source_ids=list(filter(None,[player.get('release',{}).get('sourceUrl'),
              goalie_profile['data'].get('goalieProfileSourceUrl'),goalie_profile['sourceUrl']])))

    dep=player.get('deployment')
    dep_data=evidence_data(dep)
    dep_ok=bool(dep_data and dep_data.get('EV') and dep_data.get('status') in ('PROJECTED','CONFIRMED') and not player.get('deploymentConflict'))
    # Keep a sourced projected unit only as projected evidence until the team
    # actually confirms it; complete runs with mixed evidence remain MIXED.
    source_steps(['Step6'],[])
    emit('G6',dep_ok,{'deployment':dep_data,'notAllPP1':True,
          'projectedNotPromoted':bool(dep_data and dep_data.get('status')=='PROJECTED'),
          'deploymentConflict':bool(player.get('deploymentConflict'))},
         source_ids=[dep.get('sourceUrl','') if dep else ''])
    # G7: two observed dates are the minimal meaning of recurrence. Compare
    # credited goals OR dated shooter-owned attempts, not mere log existence.
    source_steps(['Step4'],[])
    emit('G7',dated_recurrence['datedScoringOrShotRecurrence'],
         {'eventLogReconciled':rec,'multiGoalDateOnce':True,
          'missedGamesExcluded':True,**dated_recurrence},
         source_ids=[p['sourceUrl'] for p in (
             player.get('gameLog'),player.get('mappedGoals'),player.get('pressure'))
             if receipt(p)],
         # Complete dated counterevidence is an elimination, not "data missing".
         eliminate=bool(rec and shot_review['valid']
                        and shot_review['datedAppearanceAlignmentVerified']
                        and not dated_recurrence['datedScoringOrShotRecurrence']))
    market=player.get('authenticMarket')
    # G8 explicitly neutral when unavailable; never invent market or eliminate a skater.
    emit('G8',True,{'market':evidence_data(market) if receipt(market) else None,
                  'neutralWhenAbsent':not receipt(market),'neverRankingShortcut':True})
    coverage=game.get('coverage',{}).get(attack_team)
    coverage_data=evidence_data(coverage)
    match=bool(coverage_data and release and release['zone'] in coverage_data.get('greenWeakZones',[]))
    zone_concession=(coverage_data.get('zoneConcessions') or {}).get(
        release['zone']) if coverage_data and release else None
    g9_sources=sorted(set(
        ([coverage['sourceUrl']] if receipt(coverage) else [])+
        [u for u in ((coverage_data or {}).get('sourceUrls') or [])
         if isinstance(u,str) and u.startswith('https://')]))
    source_steps(['Step8'],[])
    emit('G9',match,{'shooterZone':release['zone'] if release else None,
                   'greenTarget':coverage_data.get('greenWeakZones',[]) if coverage_data else None,
                   'redAvoid':coverage_data.get('redStrongZones',[]) if coverage_data else None,
                   'coverageSourceType':coverage_data.get('sourceType') if coverage_data else None,
                   'coverageComparison':coverage_data.get('comparison') if coverage_data else None,
                   'zoneConcessionEvidence':zone_concession,
                   'lowShotVolumeNotStrengthEvidence':bool(
                       coverage_data and coverage_data.get(
                           'lowShotVolumeIsNotEvidenceOfDefensiveStrength') is True)},
         eliminate=bool(coverage_data and release and release['zone'] in coverage_data.get('redStrongZones',[])),
         source_ids=g9_sources)
    ownership=player.get('finishOwnership');own=evidence_data(ownership)
    # G10 proves historical OWN goal credit. It cannot certify that this
    # skater will be the recipient rather than an assist provider TONIGHT.
    # The previous hard-coded "notAssistOrFeeder: True" overstated evidence
    # for playmakers and must never appear as proof of tonight's role.
    own_goals=own.get('ownedGoalsInActualAppearances') if own else None
    season_supplement=(own.get('seasonGoalSupplement') or {}).get('data',{}) if own else {}
    season_history=player.get('seasonHistory')
    season_data=evidence_data(season_history) or {}
    season_goal_games=season_data.get('goalScoringGames')
    # An eight-game sample cannot disprove an independently sourced goal
    # earlier in THIS regular season. Official dated player game logs can
    # corroborate OWN season goals shown separately by NHL EDGE shot origin.
    verified_season_goals=bool(
        receipt(season_history)
        and season_data.get('sourceType')=='NHL_OFFICIAL_PLAYER_DATED_REGULAR_SEASON_GAME_LOG'
        and season_data.get('scope')=='OFFICIAL_CURRENT_SEASON_DATED_GAMES_PRIOR_TO_SLATE'
        and str(season_data.get('playerId'))==str(player['id'])
        and type(season_data.get('officialPastSeasonGoals')) is int
        and season_data['officialPastSeasonGoals']>0
        and isinstance(season_goal_games,list) and bool(season_goal_games)
        and all(type(x.get('goals')) is int and x['goals']>0
                and isinstance(x.get('date'),str) and x['date']<str(game['date'])
                and x.get('gameId') for x in season_goal_games)
        and sum(x['goals'] for x in season_goal_games)==
            season_data['officialPastSeasonGoals'])
    sample_goals=bool(rec and type(rec.get('officialGoals')) is int
                      and rec['officialGoals']>0)
    historic_direct=bool(
        receipt(ownership) and own.get('creditedGoalsVerified') is True
        and own.get('recipient') is True and rec and
        (sample_goals or verified_season_goals)
        and (own_goals is None or
             (type(own_goals) is int and own_goals>=0))
        and (not season_supplement or
             type(season_supplement.get('ownedSeasonGoalsFromNhlEdgeShotOrigins')) is int))
    emit('G10',historic_direct,
         {'goalCreditOwned':own,
          'historicalDirectGoalRecipientVerified':historic_direct,
          'historicalDirectGoalRecipientVerificationMethod':
              'RECENT_DATED_PBP_BOXSCORE' if sample_goals else
              'FULL_SEASON_GAME_LOG' if verified_season_goals else None,
          'independentOfficialSeasonGoalHistory':season_data if verified_season_goals else None,
          'directGoalProofIsHistoricalNotTonight':True,
          'futureAssistsVsGoalRecipientUnresolved':True,
          'futureNotAssistOrFeederProven':False,
          'G10_5AndG17MustSeparatelyReviewRecipientCompetition':True},
         eliminate=bool(own and own.get('recipient') is False),
         source_ids=sorted(set(x['sourceUrl'] for x in
             (ownership, season_history if verified_season_goals else None)
             if receipt(x))))
    # The first teammate-qualification pass ends at G10, precisely before
    # recipient comparisons. Previously it ran G10.5–G17 (and their source
    # functions) using an empty rival-stop map, then ran those same gates a
    # second time with different rivals. That let later calculations execute
    # before the first G10.5 decision and could contaminate source reviews.
    if stop_at_g10:
        expected=EXECUTION_ORDER[:EXECUTION_ORDER.index('G10.5')]
        observed=[row['gate'] for row in proof]
        if observed!=expected:
            raise ValueError(f'Pre-G10.5 phase order mismatch: {observed}')
        return {'player':player,'dispositions':d,'overlayExecutionOrder':overlay_execution},proof
    # G10.5/G16 compare against MEANINGFUL challengers only. A teammate
    # already ELIMINATED before G10.5 cannot own a route (G18 never reopens
    # eliminated candidates). An unresolved teammate is still compared but
    # cannot eliminate; it can only keep the decision NOT_EXECUTED.
    rivals=[x for x in live_teammates if str(x['id'])!=str(player['id']) and
            x.get('availability') not in ('OUT','SCRATCHED','INJURED')]
    # Use the actual G9 coverage finding and G4 shooter release, only now.
    wins,rows=challenger_proof(player,rivals,weak,
        (coverage_data or {}).get('greenWeakZones'),
        opponent_coverage=coverage_data)
    # A same-route rival whose OWN direct evidence is strictly stronger owns
    # the route: that is a genuine G10.5 recipient-separation loss, not an
    # unresolved source gap. Unresolved rows (missing rival source, exact
    # ties) remain NOT_EXECUTED so research continues instead of a fake loss.
    route_owned_by=sorted(str(r['challengerId']) for r in rows
                          if r.get('status')=='RIVAL_DOMINATES'
                          and str(r['challengerId']) not in unresolved_before)
    unresolved_dominators=sorted(str(r['challengerId']) for r in rows
                          if r.get('status')=='RIVAL_DOMINATES'
                          and str(r['challengerId']) in unresolved_before)
    # Keep Step14 until after cross-game G16 has been finalized.
    source_steps(['Step10.5'],rows)
    emit('G10.5',wins is True,
         {'comparisonRows':rows,'allAlternativesScanned':len(rows)==len(rivals),
          'noGuessTransfer':True,
          'challengersStoppedBeforeG10_5':{k:v for k,v in sorted(stopped.items())
                                           if k!=str(player['id'])} or None,
          'eliminatedChallengersExcluded':sorted(eliminated_before-{str(player['id'])}) or None,
          'unresolvedChallengersCannotEliminate':unresolved_dominators or None,
          'routeOwnedByStrongerRival':route_owned_by or None},
         eliminate=bool(route_owned_by),
         source_ids=sorted({url for row in rows for url in row.get('sourceUrls',[])
             if url} | ({player['release']['sourceUrl']} if receipt(player.get('release')) else set())))
    shots=player.get('pressure')
    recent_shots=evidence_data(shots,'recentAppearanceShots')
    route_pressure=independently_dated_origin_route(player,(release or {}).get('zone'))
    bounded_route=(independently_bounded_origin_route(
        player,(release or {}).get('zone')) if route_pressure is None else None)
    observed_route=route_pressure or bounded_route
    current_route_reviewed=bool(observed_route and
        evidence_data(player.get('recentOrigin')).get('sampleAsOfSlateDate')==game.get('date'))
    current_route_active=bool(current_route_reviewed and
        ((route_pressure and route_pressure['shotsOnGoal']>0) or
         (bounded_route and bounded_route['shotsOnGoalLowerBound']>0)))
    # G11: observed own-shot pressure in separate actual appearances.
    # [0,0,3] is one isolated active game, not recurring pressure.
    source_steps(['Step9'],[])
    emit('G11',bool(receipt(shots) and shot_review['valid']
                    and shot_review['repeatedOwnShotPressure'] and current_route_active),
         {'recentOwnAttempts':recent_shots,
          'shotContinuation':shot_review,
          'selectedRouteRecentOrigin':observed_route,
          'conservativeUnknownLocationBounds':bounded_route,
          'currentShotPressureInSelectedRoute':current_route_active,
          'noOneOffPressureCalledContinuation':True},
         # Missing appearance dates are an evidence gap, not proof that
         # the player failed to repeat his own shot pressure.
         eliminate=bool(receipt(shots) and shot_review['valid']
                        and shot_review['datedAppearanceAlignmentVerified']
                        and (not shot_review['repeatedOwnShotPressure'] or
                             (route_pressure is not None and current_route_reviewed and
                              not current_route_active))),
         source_ids=sorted(set(([shots['sourceUrl']] if receipt(shots) else [])+
             ([player['recentOrigin']['sourceUrl']] if receipt(player.get('recentOrigin')) else []))))
    emit('G12',bool(own and own.get('creditedGoalsVerified') is True and rec is not None),
         {'ownership':own,'officialGoalsReconciled':bool(rec)},
         source_ids=sorted(set(x['sourceUrl'] for x in (
             ownership,player.get('gameLog'),player.get('mappedGoals'),
             player.get('officialGoalTotal')) if receipt(x))))
    jersey=player.get('jersey')
    milestone=player.get('milestone')
    birth=player.get('birthDate') or player.get('birthdate')
    date_value=game.get('date')
    jersey_digits=''.join(ch for ch in str(jersey or '') if ch.isdigit())
    date_digits=''.join(ch for ch in str(date_value or '') if ch.isdigit())
    name=player.get('name')
    # Genuine qualitative name/date/jersey/birth and milestone review,
    # with no formula requirement or fabricated milestone/weights.
    g13={'date':date_value,'name':name,'jersey':jersey,'birthDate':birth,
         'jerseyDateSharedDigits':sorted(set(jersey_digits)&set(date_digits)),
         'verifiedMilestone':evidence_data(milestone) if receipt(milestone) else None,
         'milestoneSourcePresent':receipt(milestone),
         'birthDateAvailable':bool(birth),
         'qualitativeNameDateReview':bool(name and date_value),
         'formula':'none; qualitative only','nonblockingNoInventedWeights':True}
    source_steps(['Step13'],rows)
    emit('G13',bool(name and date_value),g13,
         source_ids=[milestone['sourceUrl']] if receipt(milestone) else [])
    who=player.get('whoAnomaly');who_ok=bool(receipt(who) and
        evidence_data(who,'directIndependentRoute') is True and overlap)
    # G14 can neutrally exclude a WHO route, but never invent an anomaly.
    # Checking a sourced release is a real review; constant True was not.
    who_reviewed=bool(receipt(player.get('release')) and release and
                      goalie_profile.get('sourceUrl') and weak)
    unsupported_who=bool(receipt(who) and not who_ok)
    source_steps(['Step11'],rows)
    emit('G14',who_reviewed and not unsupported_who,
         {'whoRouteReviewed':who_reviewed,
          'whoAnomalyPhysicallySupported':who_ok,
          'neutralNoWhoAnomaly':not receipt(who),
          'unsupportedWhoEvidence':unsupported_who,
          'noForcedWho':True,
          'whoDetails':evidence_data(who) if who_ok else None},
         source_ids=sorted(set([player['release']['sourceUrl']] if
             receipt(player.get('release')) else []) | set(
             [who['sourceUrl']] if receipt(who) else []) | set(
             [goalie_profile['sourceUrl']] if receipt(goalie_profile) else [])))
    # G15: own GOAL FINISHER (not the assist provider), independently
    # corroborated by the official dated season goal log and the skater's
    # separate NHL EDGE own shot-origin record. G5 already proved which
    # observed own shooting lane attacks the G0 goalie weakness.
    #
    # A player may have actual shots but no historically credited goal in
    # that SPECIFIC weak lane while independently owning historical goals in
    # other lanes. Requiring a SAME-LANE goal here wrongly duplicates the
    # physical-lane G5 check and labels a real historical scorer NOT_EXECUTED
    # despite independent positive goal credits from both sources.
    # DO NOT claim any historical goal in the matched lane when there is zero.
    season_release_consistent=bool(
        verified_season_goals and release and
        type(release.get('ownedGoals')) is int and
        release['ownedGoals']<=season_data['officialPastSeasonGoals'])
    edge_routes=(release.get('allRoutes') or []) if release else []
    edge_full_own_goal_reconciliation=bool(
        verified_season_goals and receipt(player.get('release')) and
        isinstance(release,dict) and
        release.get('sourceType')=='NHL_EDGE_SHOT_ORIGIN_PEER_PERCENTILE' and
        isinstance(edge_routes,list) and len(edge_routes)>0 and
        all(isinstance(row,dict) and bool(row.get('zone')) and
            type(row.get('sog')) is int and row['sog']>=0 and
            type(row.get('ownedGoals')) is int and
            0<=row['ownedGoals']<=row['sog'] for row in edge_routes) and
        len({row.get('zone') for row in edge_routes})==len(edge_routes) and
        sum(row['ownedGoals'] for row in edge_routes)==
            season_data['officialPastSeasonGoals'] and
        release.get('attempts',0)>0 and
        (season_history or {}).get('sourceUrl') !=
            player['release']['sourceUrl'] and
        season_data['officialPastSeasonGoals']>0)
    # One direct finishing proof already in THIS chosen lane remains the
    # strongest form of historical route attribution. The independent
    # full-season cross-origin option is NOT a claim he scored from this
    # lane; it verifies a goal recipient who shoots from the targeted lane.
    exact_matched_lane_goal=bool(release and
        type(release.get('ownedGoals')) is int and
        release['ownedGoals']>0)
    finish_corrob=bool(
        own and own.get('recipient') is True and
        receipt(ownership) and rec and
        (sample_goals or season_release_consistent) and
        receipt(player.get('release')) and release and
        type(release.get('ownedGoals')) is int and
        (exact_matched_lane_goal or edge_full_own_goal_reconciliation))
    emit('G15',finish_corrob,
         {'independentHistoricalGoalFinishingEvidence':finish_corrob,
          'goalSourceReconciledToDatedAppearances':bool(rec),
          'separateOfficialShotOriginSource':bool(receipt(player.get('release'))),
          'officialOwnedGoalsInMatchedOrigin':release.get('ownedGoals') if release else None,
          'matchedOriginOwnOnNetShots':release.get('attempts') if release else None,
          'matchedOriginHasHistoricalGoal':exact_matched_lane_goal,
          'officialDatedSeasonGoals':season_data.get('officialPastSeasonGoals') if verified_season_goals else None,
          'totalOwnedGoalsFromEveryNhlEdgeOrigin':sum(
              row.get('ownedGoals',0) for row in edge_routes
              if isinstance(row,dict) and type(row.get('ownedGoals')) is int)
              if edge_routes else None,
          'fullSeasonGoalCreditsReconciledAgainstEdgeOrigins':edge_full_own_goal_reconciliation,
          'directFinisherEvidenceMethod':(
              'POSITIVE_OWN_GOALS_FROM_MATCHED_ROUTE' if exact_matched_lane_goal else
              'OFFICIAL_FULL_SEASON_GOALS_MATCH_ALL_EDGE_OWN_ORIGINS_AND_SOURCED_MATCHED_LANE_SHOTS'
              if edge_full_own_goal_reconciliation else None),
          'sameLaneGoalsNotInferredFromScoringElsewhere':True,
          'seasonAndReleaseGoalCreditsConsistent':season_release_consistent if verified_season_goals else None,
          'independentSeasonLogSource':season_history.get('sourceUrl') if verified_season_goals else None,
          'futureGoalVersusAssistRoleNotProven':True,
          'notASecondCopyOfG10RecipientBoolean':True},
         source_ids=sorted(set(x['sourceUrl'] for x in (
             ownership,player.get('release'),player.get('mappedGoals'),
             season_history if verified_season_goals else None)
             if receipt(x))))
    # Global G16 has already compared all G0-G16-qualified game candidates.
    # Apply the resulting evidence now, BEFORE G17, not after it has passed.
    global_row=cross_game_g16 or {}
    # The global G16 source verdict is applied at G16, not after G17.
    # A source-proven game scorer remains a game survivor even if G16
    # excludes that route from the final cross-game Core competition.
    globally_excluded=str(global_row.get('g16Decision') or '').startswith('EXCLUDED_')
    source_steps(['Step12'],rows)
    emit('G16',wins is True and len(rows)==len(rivals) and not globally_excluded,
         {'everyOtherActiveTeammate':len(rows),'challengerRows':rows,
          'includesDepthAndDefense':True,
          'routeOwnedByStrongerRival':route_owned_by or None,
          'crossGameFinalistCompetitionRunsAfterEveryGame':True,
          'crossGameFinalistCompetition':({
              'decision':global_row.get('g16Decision'),
              'dominatedBy':global_row.get('dominatedBy',[]),
              'comparedAgainstAllGames':True}
              if cross_game_g16 is not None else None),
          'globalG16AppliedBeforeG17':True,
          'challengersStoppedBeforeG10_5':stopped or None,
          'eliminatedChallengersExcluded':sorted(eliminated_before-{str(player['id'])}) or None,
          'unresolvedChallengersCannotEliminate':unresolved_dominators or None},
         eliminate=bool(route_owned_by) or globally_excluded,
         # The candidate side of every comparison is its own official release
         # record, so it is cited even when no live challenger remains.
         source_ids=sorted(set([url for row in rows for url in row.get('sourceUrls',[])
             if isinstance(url,str) and url.startswith('https://')]+
             ([player['release']['sourceUrl']] if receipt(player.get('release')) else []))))
    # Earlier full-slate scouting pass ends here: NO G17 or Step14 source
    # adjudication before the actual cross-game G16 competition.
    if stop_at_g16:
        expected=EXECUTION_ORDER[:EXECUTION_ORDER.index('G17')]
        if [row['gate'] for row in execution_trace]!=expected:
            raise ValueError('Original G0-G16 scouting gate order mismatch')
        return {'player':player,'dispositions':d,'release':release,
                'overlayExecutionOrder':overlay_execution,
                'preG17Qualified':all(d[g]['disposition']=='PASS'
                                      for g in MASTER[:MASTER.index('G17')])},execution_trace
    # G17 is a contradiction audit, not a second G10.5 elimination round.
    # A challenger already defeated (or independently shown to have no route
    # into any jointly viable G0/G9 area) by this candidate's G10.5 comparison
    # is no longer a live rival for G17. Preserve actual dominators and
    # unresolved comparisons; do not let a defeated roster member reopen the
    # contradiction review after its original comparison has been decided.
    g10_5_resolved_rivals={str(row['challengerId']) for row in rows
        if row.get('status') in (
            'DEFEATED','SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE',
            'DIFFERENT_TARGET_LANE') and row.get('challengerId') is not None}
    g17_excluded_rivals=eliminated_before | g10_5_resolved_rivals
    # G17 source retrieval must precede Step14's independent source
    # evaluation, but neither may run until the full-slate G16 decision.
    if g17_review is not None:
        source_receipt=g17_review(game,attack_team,player,g17_excluded_rivals)
        if source_receipt is not None:
            player['contradictions']=source_receipt
        elif (evidence_data(player.get('contradictions')) or {}).get('sourceType') == 'DERIVED_CROSS_SOURCE_G17':
            # Do not reuse a stale derived result from a previous G0 goalie
            # branch when the current G17 review found no valid source route.
            player.pop('contradictions',None)
    source_steps(['Step14'],rows,g17_excluded_rivals)
    contradiction=player.get('contradictions')
    cdata=evidence_data(contradiction)
    # Having a review OBJECT is not proof that its conflicts were resolved.
    # Source-derived cross-checks must explicitly report no unresolved
    # goalie/role/rival contradiction to pass; never force G17 on placeholder.
    # G17's contradiction decision is authoritative regardless of which
    # independent source supplied the structured review. Previously ANY
    # non-DERIVED source with unresolved=True was silently marked PASS.
    # Require a positive resolved outcome, not merely a source label.
    cross_source_resolved=bool(cdata and cdata.get('unresolved') is False)
    # The pregame review compared every teammate, including teammates the
    # gates already ELIMINATED. Like G10.5/G16, such a teammate is not a
    # meaningful rival and cannot keep this candidate's G17 unresolved. Every
    # other stored review condition (goalie branch, weak-area match, stronger
    # area contradiction, lineup role, unresolved live rivals) still applies.
    g17_live=g17_resolved_without_eliminated_rivals(cdata,g17_excluded_rivals)
    if not cross_source_resolved and g17_live['resolved']:
        cross_source_resolved=True
    emit('G17',bool(cdata and cdata.get('goalieStrengthReview') is not None and
                     cdata.get('lineupDisagreementReview') is not None and
                     cdata.get('strongestRivalReview') is not None and
                     cross_source_resolved),
         {'goalieBranch':goalie_profile['data'].get('goalieId'),
          'counterevidence':cdata,'retainsConflictingSources':True,
          'sourceDerivedReviewResolved':cross_source_resolved,
          'eliminatedRivalsIgnoredInRivalReview':g17_live['ignoredEliminatedRivals'] or None,
          'G10_5ResolvedRivalsExcludedFromG17':sorted(g10_5_resolved_rivals) or None},
         source_ids=[contradiction['sourceUrl']] if receipt(contradiction) else [])
    # Both independent tracks must pass. Neither may overwrite the other's
    # original verdict or masquerade as a completed source check.
    if overlay_execution!=OVERLAY_EXECUTION_ORDER:
        raise ValueError(f'Original overlay owner-gate execution order mismatch: {overlay_execution}')
    overlay.sort(key=lambda item:OVERLAY.index(item['gate']))
    master_passed=all(d[gate]['disposition']=='PASS'
                      for gate in MASTER[:-1])
    # Preserve original optional reviews without turning an unobserved shift
    # sample or qualitative fact into either a PASS or an extra scorer veto.
    overlay_passed=all(
        row['disposition']=='PASS' or
        nonblocking_overlay_review(row['gate'],
            row.get('details',{}).get('evidence',{}),row['disposition'])
        for row in overlay)
    # Cross-game G16 exclusion is recorded in the authoritative G16 row,
    # but must not erase the already qualified game-level scorer. This is
    # the same source-backed opponent route that G18 may choose NOT to use.
    otherwise_passed=all(d[g]['disposition']=='PASS'
                         for g in MASTER[:-1] if g!='G16')
    cross_game_only_exclusion=bool(
        globally_excluded and wins is True and not route_owned_by and
        d['G16']['disposition']=='ELIMINATED' and otherwise_passed)
    previous_gates_passed=(master_passed or cross_game_only_exclusion) and overlay_passed
    route,path_proof=adjudicate_scoring_path(player,teammates,release,
        goalie_profile,coverage,d,rows,who_ok)
    # A game survivor has passed the ENTIRE original G0-G17 source process.
    # Do NOT turn G18 path-label classification into a hidden pre-Core gate:
    # G18 is the final shared Core assembly, not another game eliminator.
    pre_core_qualified=previous_gates_passed
    passed=pre_core_qualified and route is not None
    # In the scheduled full-slate run G18 is deferred until G16 finishes
    # cross-game competition. A game finalist is NOT yet a Core recipient.
    if not defer_g18:
        emit('G18',passed,{
            'candidateEligibleForCrossGameFinal':passed,
            'pathClassificationEvidence':path_proof,
            'classificationOccursAfterAllSourceGates':True,
            'originalFunctionsReviewedBeforeG18':overlay_passed,
            'notPresetOneOfEach':True},
            source_ids=path_proof['sourceUrls'])
    master_trace=[row['gate'] for row in proof]
    overlay_trace=[row['gate'] for row in overlay]
    expected_master=MASTER[:-1] if defer_g18 else MASTER
    if master_trace!=expected_master:
        raise ValueError(f'Master scorer-gate execution order mismatch: {master_trace}')
    if overlay_trace!=OVERLAY:
        raise ValueError(f'Original overlay source observation order mismatch: {overlay_trace}')
    expected_execution=EXECUTION_ORDER[:-1] if defer_g18 else EXECUTION_ORDER
    if [row['gate'] for row in execution_trace]!=expected_execution:
        raise ValueError('Single original gate trace does not match G0–G18')
    final_g18_passed=(passed if defer_g18 else
                      passed and d['G18']['disposition']=='PASS')
    return {'player':player,'dispositions':d,'complete':final_g18_passed,
            'preCoreQualified':pre_core_qualified,'pathClassificationCertified':route is not None,
            'g18Deferred':defer_g18,
            'deficientGates':deficient,'route':route,'pathEvidence':path_proof,
            'overlayExecutionOrder':overlay_execution,
            'pressure':evidence_data(shots),
            'release':release,'challengers':rows},execution_trace


def verify_complete_matrix(games, records, scan, now=None, selected_directions=None):
    """Verify each original gate and its internal source functions before G18."""
    errors=[]
    now=now or datetime.now(timezone.utc)
    expected_set=set(EXECUTION_ORDER)
    if set(OVERLAY)!=set(STEP_ORDER):
        errors.append('Phase-1 overlay source order differs from the authoritative mapping')
    for game in games:
        already_started=(game.get('gameState') in ('LIVE','CRIT','OFF','FINAL') or
          (game.get('startUTC') and datetime.fromisoformat(game['startUTC'].replace('Z','+00:00'))<=now))
        if already_started:continue
        direction=(selected_directions or {}).get(str(game['id']))
        if not direction:
            # G0 is itself an executed gate, even when its evidence does not
            # establish a direction. Verify both recorded attack-side reviews
            # rather than silently treating the matchup as absent.
            direction_rows=[r for r in records
                if r['gameId']==str(game['id']) and r['gate']=='G0'
                and r['playerId'].startswith('GOALIE_DIRECTION:')]
            expected_attackers={
                'GOALIE_DIRECTION:'+str(game['away']),
                'GOALIE_DIRECTION:'+str(game['home'])}
            if {r['playerId'] for r in direction_rows}!=expected_attackers:
                errors.append(f"{game['id']} G0 both attack directions not executed")
            continue  # Skater gates require an evidenced G0 attack direction
        active_roster=complete_roster(game,direction['attacker'])
        for person in active_roster:
            pid=str(person['id'])
            candidate_records=[r for r in records
                if r['gameId']==str(game['id']) and r['playerId']==pid]
            actual=[r['gate'] for r in candidate_records]
            if set(actual)!=expected_set:
                missing=[gate for gate in EXECUTION_ORDER if gate not in set(actual)]
                errors.append(f"{game['id']} player {pid} missing original gate records {missing}")
            if actual!=EXECUTION_ORDER:
                errors.append(
                    f"{game['id']} player {pid} wrong gate execution order; "
                    f"expected {EXECUTION_ORDER}, got {actual}")
            for index,entry in enumerate(candidate_records):
                metadata=(entry.get('details') or {})
                if metadata.get('executionIndex')!=index:
                    errors.append(
                        f"{game['id']} player {pid} gate {entry['gate']} "
                        f"has execution index {metadata.get('executionIndex')} not {index}")
            # Source functions are evidence within each original gate; they
            # cannot be skipped, copied from its verdict, or stored as gates.
            for entry in candidate_records:
                gate=entry['gate']
                expected=STEPS_BY_GATE[gate]
                content=(entry.get('details') or {}).get('evidence') or {}
                functions=content.get('originalFunctionEvidence') or []
                actual_steps=[x.get('step') for x in functions]
                if actual_steps!=expected:
                    errors.append(
                        f"{game['id']} player {pid} gate {gate} missing original functions "
                        f"{expected}: got {actual_steps}")
                for fn in functions:
                    ev=fn.get('evidence') or {}
                    if not (ev.get('independentOverlayEvaluation') is True
                            and ev.get('checkedBeforeG18') is True
                            and ev.get('masterGateVerdictCopied') is False):
                        errors.append(
                            f"{game['id']} player {pid} gate {gate} "
                            f"function {fn.get('step')} lacks independent evidence")
        count=sum(1 for r in records if r['gameId']==str(game['id']) and r['gate']=='G0'
                  and r['playerId'].startswith('GOALIE_DIRECTION:'))
        if count!=2:errors.append(f"{game['id']} G0 source directions saved {count} not 2")
    return errors


# G17 evidence-status levels: a source-CONFIRMED goalie/role carries less
# branch uncertainty than an EXPECTED/PROJECTED one. Ordinal only, never a
# weight; EXPECTED and PROJECTED are the same (unconfirmed) level.
_STATUS_LEVEL={'CONFIRMED':2,'EXPECTED':1,'PROJECTED':1}


def finalist_route_evidence(item):
    """Carry THIS game's goalie, defense and scorer-route evidence into G16.

    Historical own goals and shots remain visible as source-backed finishing
    context. When both opponent-specific matchup indicators are available,
    they—not old scoring totals—determine cross-game separation.
    """
    cand=item['candidate']; release=cand.get('release') or {}
    goalie=(item.get('targetGoalie') or {}).get('data') or {}
    dep=evidence_data(cand['player'].get('deployment')) or {}
    zone=release.get('zone')
    attack=item.get('attackTeam')
    coverage=(item['game'].get('coverage') or {}).get(attack)
    coverage_data=evidence_data(coverage) or {}
    return {
        'gameId':str(item['game']['id']),
        'playerId':str(cand['player']['id']),
        'player':cand['player'].get('name'),
        'routeZone':zone,
        'ownedGoalsInMatchedLane':release.get('ownedGoals'),
        'ownShotsOnGoalInMatchedLane':release.get('attempts'),
        'opponentGoalieZone':(goalie.get('weakZones') or {}).get(zone),
        'opponentDefenseZone':(coverage_data.get('zoneConcessions') or {}).get(zone),
        'goalieSamplePeerPopulationId':goalie.get('samplePeerPopulationId'),
        'goalieSamplePeerPopulationStable':goalie.get('samplePeerPopulationStable'),
        'goalieProfileSourceUrl':(item.get('targetGoalie') or {}).get('sourceUrl'),
        'defensiveCoverageSourceUrl':coverage.get('sourceUrl') if receipt(coverage) else None,
        'goalieStatus':goalie.get('status'),
        'deploymentStatus':dep.get('status'),
    }


def _route_vector(ev):
    """G16 compares opponent vulnerability only within identical peer methods.

    NHL EDGE league percentiles are NOT equivalent to locally measured
    NHL PBP peer percentiles. PBP comparison requires the same independently
    sourced, fixed pregame population; the collector must retain its ID.
    G9 can certify either on-net or shot-attempt concessions. Those methods
    are also incomparable and never combined into an invented weighted score.
    """
    goalie=ev.get('opponentGoalieZone') or {}
    defense=ev.get('opponentDefenseZone') or {}
    league=goalie.get('leagueSavePctgPercentile')
    sample=goalie.get('samplePeerSavePctgPercentile')
    gshots=goalie.get('shotsAgainst')
    ggoals=goalie.get('goalsAgainst')
    if (type(gshots) is not int or gshots<20 or type(ggoals) is not int
            or not 0<=ggoals<=gshots
            or not ev.get('goalieProfileSourceUrl')
            or not ev.get('defensiveCoverageSourceUrl')):
        return None
    if type(league) in (int,float) and 0<=league<=1:
        goalie_method='NHL_EDGE_LEAGUE_SAVEPCTG_PERCENTILE'
        percentile=league
    elif (type(sample) in (int,float) and 0<=sample<=1
          and type(goalie.get('peerGoaliesSampled')) is int
          and goalie['peerGoaliesSampled']>=4
          and ev.get('goalieSamplePeerPopulationStable') is True
          and ev.get('goalieSamplePeerPopulationId')):
        goalie_method=('OFFICIAL_PBP_STABLE_PEERS:'+
                       str(ev['goalieSamplePeerPopulationId']))
        percentile=sample
    else:
        return None
    methods=defense.get('positiveConcessionBases') or []
    on_net=defense.get('onNetShotsPerGame')
    on_net_peer=defense.get('peerMedianOnNetShotsPerGame')
    attempts=defense.get('attemptsPerGame')
    attempts_peer=defense.get('peerMedianAttemptsPerGame')
    available={}
    if ('ON_NET_SHOTS_AGAINST_PEER' in methods
        and defense.get('independentOnNetConcessionReview') is True
        and type(on_net) in (int,float) and type(on_net_peer) in (int,float)
        and on_net>on_net_peer>0):
        available['G9_INDEPENDENT_ON_NET_VS_PEERS']=on_net/on_net_peer
    if ('ATTEMPTS_AGAINST_PEER' in methods
        and type(attempts) in (int,float)
        and type(attempts_peer) in (int,float)
        and attempts>attempts_peer>0):
        available['G9_OFFICIAL_ATTEMPTS_VS_PEERS']=attempts/attempts_peer
    if not available:
        return None
    # Preserve a readable preferred source label, but retain BOTH certified
    # methods so pairwise G16 comparisons can select a genuinely SHARED
    # method rather than erasing shot-attempt evidence on dual-proof routes.
    preferred=('G9_INDEPENDENT_ON_NET_VS_PEERS'
               if 'G9_INDEPENDENT_ON_NET_VS_PEERS' in available else
               'G9_OFFICIAL_ATTEMPTS_VS_PEERS')
    return (goalie_method+'|'+preferred,1-percentile,available,
            _STATUS_LEVEL.get(ev['goalieStatus'],0),
            _STATUS_LEVEL.get(ev['deploymentStatus'],0))


def _g16_shared_method(a,b):
    """One compatible goalie peer population and one COMMON G9 method."""
    if not a or not b:
        return None
    goalie_a=a[0].split('|',1)[0]
    goalie_b=b[0].split('|',1)[0]
    if goalie_a!=goalie_b or not isinstance(a[2],dict) or not isinstance(b[2],dict):
        return None
    common=set(a[2]) & set(b[2])
    if 'G9_INDEPENDENT_ON_NET_VS_PEERS' in common:
        return 'G9_INDEPENDENT_ON_NET_VS_PEERS'
    if 'G9_OFFICIAL_ATTEMPTS_VS_PEERS' in common:
        return 'G9_OFFICIAL_ATTEMPTS_VS_PEERS'
    return None


def _dominates(a,b):
    """Only source-comparable, source-positive goalie+defense dimensions.

    If both have independently verified on-net evidence, compare on-net.
    Otherwise compare shot attempts only when BOTH have valid attempts.
    An unrelated historical-goal record cannot manufacture domination.
    """
    method=_g16_shared_method(a,b)
    if method is None:
        return False
    va=(a[1],a[2][method],a[3],a[4])
    vb=(b[1],b[2][method],b[3],b[4])
    return all(x>=y for x,y in zip(va,vb)) and any(
        x>y for x,y in zip(va,vb))


def g16_cross_game_finalists(finalists, required):
    """G16 FINAL CHALLENGER COMPETITION across every per-game survivor.

    Each finalist already passed G0-G16 inside its own game. G16 now compares
    all meaningful surviving candidates, prioritizing tonight's opponent
    goalie-area vulnerability and defensive concession exposure whenever
    independently comparable. Season goals stay finishing context, never
    outrank direct matchup alignment. Goalie and deployment source statuses
    are available from G0/G6; they do not constitute an early G17 verdict.

    A finalist is excluded only when at least ``required`` finalists from
    OTHER games each strictly dominate it, i.e. a full Core can be built
    entirely from routes that are at least as strong on every dimension and
    stronger on one. Nothing is summed, weighted or tie-broken. If more than
    ``required`` finalists remain unseparated, there is no Core and the
    receipt says exactly which finalists remain tied.
    """
    rows=[]
    vectors=[]
    for item in finalists:
        ev=finalist_route_evidence(item)
        vector=_route_vector(ev)
        vectors.append(vector)
        ev['g16ComparisonBasis']=vector[0] if vector else 'NOT_COMPARABLE'
        ev['g16AvailableDefenseMethods']=(sorted(vector[2]) if vector else [])
        rows.append(ev)
    retained=[];excluded=[]
    for i,(ev,vec) in enumerate(zip(rows,vectors)):
        if vec is None:
            ev['g16Decision']='RETAINED_ROUTE_EVIDENCE_NOT_COMPARABLE'
            ev['dominatedBy']=[]
            retained.append(i); continue
        by=[rows[j]['playerId'] for j,other in enumerate(vectors)
            if j!=i and other is not None and
            rows[j]['gameId']!=ev['gameId'] and _dominates(other,vec)]
        ev['dominatedBy']=by
        ev['dominatedBySharedMethods']={
            rows[j]['playerId']:_g16_shared_method(other,vec)
            for j,other in enumerate(vectors)
            if j!=i and rows[j]['playerId'] in by
            and rows[j]['gameId']!=ev['gameId']}
        if len(by)>=required:
            ev['g16Decision']='EXCLUDED_STRICTLY_DOMINATED_BY_A_FULL_CORE'
            excluded.append(i)
        else:
            ev['g16Decision']='RETAINED'
            retained.append(i)
    receipt_out={
        'gate':'G16','phase':'CROSS_GAME_FINALIST_COMPETITION',
        'requiredCoreSize':required,
        'finalistCount':len(finalists),
        'finalists':rows,
        'retainedPlayerIds':[rows[i]['playerId'] for i in retained],
        'excludedPlayerIds':[rows[i]['playerId'] for i in excluded],
        'comparisonDimensions':['G0 NHL EDGE league or source-proven stable PBP peer save-percentile (never mixed)',
            'G9 source-positive on-net or shot-attempt concessions vs peers (never mixed)',
            'G0 goalie starter status (CONFIRMED > EXPECTED/PROJECTED)',
            'G6 deployment source status (CONFIRMED > PROJECTED)',
            'Historical goals/shots: context only; NEVER a fallback selection'],
        'rule':('Exclude a finalist only if >= requiredCoreSize finalists from '
                'other games strictly dominate it on every dimension'),
        'noWeightsSumsRatesOrTieBreaks':True,
        'noStarPP1OrOddsPreference':True,
        'separated':len(retained)==required,
    }
    return [finalists[i] for i in retained],receipt_out


def cross_game_winners(winners, slate_size):
    """G18 ONLY ASSEMBLES THE CORE produced by prior independent gates.

    G0-G17, G10.5 and the complete independent overlay decide who survives.
    G18 never runs another rank, weighted/lexicographic/dominance score,
    goalie-percentile comparison, or source-evidence threshold. It merely
    places three distinct-game survivors (two on a two-game slate) onto
    the one canonical card.

    If earlier gates have not uniquely settled that Core, the solution is
    to resolve their actual source evidence, not for G18 to invent a winner.
    """
    required=2 if slate_size==2 else 3
    game_ids=[str(item['game']['id']) for item in winners]
    if len(game_ids)!=len(set(game_ids)):
        return [],['PRE_CORE_REVIEW: multiple survivors from one game; G10.5/G17 must separate recipients before final Core assembly']
    if len(winners)!=required:
        return [],[f'PRE_CORE_REVIEW: {len(winners)} independently qualified game recipients, '
                   f'but Core {required} requires exactly {required}; G18 cannot '
                   'rank, preselect, or eliminate any of them']
    return list(winners),[]


def revalidate_authoritative_finalists(con, date, finalists, receipt, required):
    """Apply the existing single-card lock after every live gate was rechecked.

    An additional qualified game does not, by itself, fail an incumbent's
    route or authorize replacing a saved card. First issuance still requires
    unique G16 separation. A missing/failed incumbent is never rescued here.
    """
    if not receipt or receipt.get('separated'):
        return finalists, receipt
    prior=get_card(con,date)
    if not prior:
        return finalists, receipt
    legs=prior.get('current_legs') or []
    keys={(str(x['gameId']),str(x['playerId'])) for x in legs}
    if len(legs)!=required or len(keys)!=required or len({x[0] for x in keys})!=required:
        return finalists, receipt
    by_key={(str(x['game']['id']),str(x['candidate']['player']['id'])):x for x in finalists}
    if not keys.issubset(by_key):
        return finalists, receipt  # a current source gate defeated an old leg
    version=con.execute(
        'SELECT fingerprint,created_at FROM card_versions WHERE slate_date=? AND revision=?',
        (date,prior['revision'])).fetchone()
    if not version or version['fingerprint']!=prior['fingerprint'] or fingerprint(legs)!=prior['fingerprint']:
        return finalists, receipt
    proof={
        'cardId':prior['card_id'],'fingerprint':prior['fingerprint'],
        'baselineRevision':prior['revision'],'baselineCreatedAt':version['created_at'],
        'baselineIdentities':[{'gameId':str(x['gameId']),'playerId':str(x['playerId'])} for x in legs],
        'everyIncumbentRepassedCurrentG0ThroughG16':True,
        'G17StillRequiresIndependentLaterVerdict':True,
        'everyIncumbentRetainedByFullG16Comparison':True,
        'newRecipientSelected':False,'replacementAuthorized':False,
        'reason':'Additional qualifying games do not defeat a saved recipient or authorize a second Core',
    }
    revised={**receipt,'decisionMode':'REVALIDATE_AUTHORITATIVE_CARD',
             'comparisonSeparated':False,
             'comparisonRetainedPlayerIds':receipt['retainedPlayerIds'],
             'canonicalCardPreservation':proof,'separated':True}
    rows=[]
    for row in receipt['finalists']:
        key=(str(row['gameId']),str(row['playerId']))
        if row['g16Decision'].startswith('RETAINED'):
            row={**row,'g16Decision':('RETAINED_REVALIDATED_AUTHORITATIVE_RECIPIENT' if key in keys
                                    else 'NOT_SELECTED_NO_GATE_CHANGING_REPLACEMENT')}
        rows.append(row)
    revised['finalists']=rows
    revised['retainedPlayerIds']=[r['playerId'] for r in rows if r['g16Decision'].startswith('RETAINED')]
    revised['notSelectedExistingCardPlayerIds']=[r['playerId'] for r in rows
        if r['g16Decision']=='NOT_SELECTED_NO_GATE_CHANGING_REPLACEMENT']
    return [x for x in finalists if (str(x['game']['id']),str(x['candidate']['player']['id'])) in keys], revised


def _authorized_retraction_reselection(con, existing, legs, selected, date, stage):
    """Repair a previously REVOKED November 17 card from a fresh full-gate run.

    The one-slate user-authorized retraction archived the bad G18 selection,
    but a later run reissued the SAME bad fingerprint. Normal goalie-only
    replacement cannot correct a wrong GAME recipient. This exception does
    not elect any scorer: it uses only the already-executed G16/G18 survivors
    and independently saved source receipts. An unknown prior gate is recorded
    as NOT_EXECUTED, never misrepresented as source elimination.
    """
    if date != '2026-11-17' or stage not in ('PROJECTED', 'CONFIRMED'):
        return None
    try:
        archived = con.execute(
            "SELECT original_fingerprint,original_card FROM card_retractions "
            "WHERE slate_date=?", (date,)).fetchone()
    except Exception:
        return None
    if not archived or existing.get('grade') is not None:
        return None
    old_original = json.loads(archived['original_card'])
    if (archived['original_fingerprint'] != existing['fingerprint']
            or old_original.get('fingerprint') != existing['fingerprint']
            or str(existing['first_issued_at']) <= str(old_original['first_issued_at'])):
        return None

    old_by_id = {(str(x['gameId']), str(x['playerId'])): x
                 for x in existing['current_legs']}
    new_by_id = {(str(x['gameId']), str(x['playerId'])): x for x in legs}
    removed = [old_by_id[k] for k in old_by_id.keys() - new_by_id.keys()]
    added = [new_by_id[k] for k in new_by_id.keys() - old_by_id.keys()]
    if len(removed) != 1 or len(added) != 1 or len(legs) != len(existing['current_legs']):
        return None
    old, new = removed[0], added[0]

    # Current G0-G18 is the selection authority, not the historical card.
    # The engine has just saved these rows for the SAME phase/source snapshot.
    chosen_ids = {(str(x['game']['id']), str(x['candidate']['player']['id']))
                  for x in selected}
    if chosen_ids != set(new_by_id) or len(selected) != len(legs):
        return None
    if any(not item['candidate'].get('complete') or any(
            (item['candidate'].get('dispositions', {}).get(g) or {}).get('disposition') != 'PASS'
            for g in MASTER) for item in selected):
        return None
    candidate_item = next((x for x in selected
        if str(x['game']['id']) == str(new['gameId'])
        and str(x['candidate']['player']['id']) == str(new['playerId'])), None)
    if candidate_item is None:
        return None
    candidate = candidate_item['candidate']
    comparison = candidate.get('challengers') or []
    if (not comparison or
            any(row.get('status') not in (
                'DEFEATED', 'DIFFERENT_TARGET_LANE',
                'SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE')
                for row in comparison)):
        return None

    # Prove why the previously retracted recipient no longer has a CURRENT
    # certified route. Source-unknown is never upgraded to ELIMINATED.
    previous = con.execute(
        "SELECT gate,disposition,details FROM gates WHERE slate_date=? "
        "AND stage=? AND game_id=? AND player_id=? AND gate!='G18'",
        (date, stage, str(old['gameId']), str(old['playerId']))).fetchall()
    prior_nonpass = next((row for gate in ('G10.5','G15','G16','G17',
        'G0','G1','G2','G3','G4','G5','G6','G7','G8','G9','G10','G11','G12','G13','G14')
        for row in previous if row['gate'] == gate and
        row['disposition'] in ('ELIMINATED', 'NOT_EXECUTED')), None)
    if not prior_nonpass:
        return None

    # Match the source IDs to persisted immutable evidence; URL-only prose
    # cannot satisfy the ledger's audited replacement contract.
    old_receipt = con.execute(
        "SELECT evidence_id FROM evidence WHERE slate_date=? AND game_id=? "
        "AND player_id=? ORDER BY evidence_id LIMIT 1",
        (date, str(old['gameId']), str(old['playerId']))).fetchone()
    release = candidate['player'].get('release') or {}
    g17 = candidate['player'].get('contradictions') or {}
    new_id, g17id = release.get('evidenceId'), g17.get('evidenceId')
    for ref in (new_id, g17id):
        if not ref or not con.execute(
            "SELECT 1 FROM evidence WHERE slate_date=? AND evidence_id=? "
            "AND game_id=? AND player_id=?",
            (date, ref, str(new['gameId']), str(new['playerId']))).fetchone():
            return None
    if not old_receipt:
        return None
    return {
        'baselineFingerprint': existing['fingerprint'],
        'triggerEvidenceId': new_id,
        'oldValue': {'player': old['player'], 'gameId': old['gameId']},
        'newValue': {'player': new['player'], 'gameId': new['gameId']},
        'affectedGates': ['G10.5','G15','G16','G17','G18'],
        'dependentGates': ['G10.5','G15','G16','G17','G18'],
        'priorSurvivorFailure': {
            'playerId': old['playerId'],
            'failedGate': prior_nonpass['gate'],
            'disposition': prior_nonpass['disposition'],
            'sourceIds': [old_receipt['evidence_id']],
            'savedGateEvidence': json.loads(prior_nonpass['details']),
            'notAnEliminationWhenMissing': prior_nonpass['disposition'] == 'NOT_EXECUTED',
            'reason': 'Previously user-retracted card; current gate evidence is not a PASS',
        },
        'g105EveryChallenger': {'candidate': new['playerId'],
                                'comparisonRows': comparison},
        'g17Contradictions': {
            'sourceIds': [g17id],
            'review': candidate['dispositions']['G17']['details']},
        'newFingerprint': fingerprint(legs),
        'exceptionScope': 'NOV17_PREVIOUSLY_RETRACTED_FINGERPRINT_ONLY',
        'retractedOriginalFirstIssuedAt': old_original['first_issued_at'],
        'notAManualSelection': True,
    }



def _material_g0_goalie_change(con, existing, date, game_id, source_ids):
    """Prove a NEW measured goalie input changed, not just G0 code or status.

    A freshly re-fetched NHL EDGE/PBP profile with identical observed physical
    weakness measurements is not a gate-changing source. Compare each current
    verified profile with the latest source receipt for the same team/goalie
    before the active card version was saved. A genuinely new confirmed goalie
    identity also qualifies, but routine EXPECTED -> CONFIRMED for the SAME
    starter is not a change in that goalie's physical weakness.
    """
    version=con.execute(
        'SELECT created_at FROM card_versions WHERE slate_date=? AND revision=?',
        (date,existing['revision'])).fetchone()
    if not version or not version['created_at']:
        return None
    try:
        baseline=datetime.fromisoformat(version['created_at'].replace('Z','+00:00'))
        if baseline.tzinfo is None:
            return None
    except (TypeError, ValueError, AttributeError):
        return None

    def instant(raw):
        try:
            result=datetime.fromisoformat(raw.replace('Z','+00:00'))
            return result if result.tzinfo is not None else None
        except (TypeError, ValueError, AttributeError):
            return None

    def measured(data):
        # Ignore refreshed source URLs, observation times, goalie status and
        # descriptive text: only real numeric goalie weakness observations
        # can change the recorded physical G0 route.
        keep=('goalsAgainst','shotsAgainst','saves','savePctg',
              'leagueSavePctgPercentile','samplePeerSavePctgPercentile')
        areas={}
        for fld in ('weakZones','observedAreas','strengthZones'):
            zones=data.get(fld) or {}
            if isinstance(zones,dict):
                selected={}
                for zone,detail in zones.items():
                    if isinstance(detail,dict):
                        numeric={k:detail[k] for k in keep
                                 if type(detail.get(k)) in (int,float)}
                        if numeric:
                            selected[zone]=numeric
                if selected:
                    areas[fld]=selected
        return areas

    evidence=con.execute(
        "SELECT evidence_id,kind,observed_at,payload FROM evidence "
        "WHERE slate_date=? AND game_id=? AND kind IN ('GOALIE_PROFILE','GOALIE_STARTER')",
        (date,str(game_id))).fetchall()
    earlier=[]
    for row in evidence:
        observed=instant(row['observed_at'])
        if observed is None:
            continue
        try:
            data=json.loads(row['payload'])
        except (TypeError, ValueError):
            continue
        if not isinstance(data,dict):
            continue
        earlier.append((row,data,observed))
    prior=[(row,payload,seen) for row,payload,seen in earlier if seen<=baseline]
    for eid in source_ids:
        current=next(((row,data,seen) for row,data,seen in earlier
                      if row['evidence_id']==eid and row['kind']=='GOALIE_PROFILE'),None)
        if current is None:
            continue
        row,data,seen=current
        if seen<=baseline:
            continue
        team=str(data.get('team') or '')
        goalie=str(data.get('goalieId') or '')
        if not team or not goalie:
            continue
        baseline_profiles=sorted((
            (old,prior_data,old_time) for old,prior_data,old_time in prior
            if old['kind']=='GOALIE_PROFILE' and
               str(prior_data.get('team'))==team and
               str(prior_data.get('goalieId'))==goalie and measured(prior_data)
        ),key=lambda x:x[2],reverse=True)
        latest=baseline_profiles[0] if baseline_profiles else None
        current_measured=measured(data)
        if latest and current_measured and current_measured!=measured(latest[1]):
            return {
                'reason':'MEASURED_GOALIE_WEAK_ORIGIN_CHANGED',
                'gameId':str(game_id),'team':team,'goalieId':goalie,
                'priorEvidenceId':latest[0]['evidence_id'],
                'triggerEvidenceId':eid,
                'priorObservedAt':latest[0]['observed_at'],
                'triggerObservedAt':row['observed_at'],
                'baselineVersionCreatedAt':version['created_at'],
                'noUnchangedProfileRefreshAsNewTrigger':True,
            }
        # A different CONFIRMED starter not on the original source roster
        # changes the goalie branch; a confirmation of the same projected
        # starter, by itself, never reverses G0.
        prior_starters={str(payload.get('goalieId')) for old,payload,_ in prior
                        if old['kind']=='GOALIE_STARTER' and
                           str(payload.get('team'))==team}
        if goalie not in prior_starters and prior_starters:
            confirmed=next(((old,payload,when) for old,payload,when in earlier
                            if old['kind']=='GOALIE_STARTER' and
                               str(payload.get('team'))==team and
                               str(payload.get('goalieId'))==goalie and
                               payload.get('status')=='CONFIRMED' and when>baseline),None)
            if confirmed and current_measured:
                return {
                    'reason':'NEW_CONFIRMED_STARTER_IDENTITY',
                    'gameId':str(game_id),'team':team,'goalieId':goalie,
                    'priorStarterIds':sorted(prior_starters),
                    'starterEvidenceId':confirmed[0]['evidence_id'],
                    'triggerEvidenceId':eid,
                    'triggerObservedAt':row['observed_at'],
                    'baselineVersionCreatedAt':version['created_at'],
                }
    return None


def source_verified_g0_direction_replacement(
        con, existing, legs, selected, date, scan, selected_directions):
    """Replace a lost-game leg ONLY if sourced G0 reverses its attack side.

    G0's goalie-first decision, not G18 or a human, removes the former
    attack route. The replacement must then independently pass every gate.
    """
    old={(str(x['gameId']),str(x['playerId'])):x for x in existing['current_legs']}
    new={(str(x['gameId']),str(x['playerId'])):x for x in legs}
    lost=[old[k] for k in old.keys()-new.keys()]
    gained=[new[k] for k in new.keys()-old.keys()]
    if (existing.get('grade') is not None or len(old)!=3 or len(new)!=3
            or len(lost)!=1 or len(gained)!=1 or not scan
            or not selected_directions):
        return None
    prior,replacement=lost[0],gained[0]
    gid=str(prior['gameId'])
    if gid==str(replacement['gameId']):
        return None
    sides=[x for x in scan if str(x['gameId'])==gid]
    current=selected_directions.get(gid) or {}
    if (len(sides)!=2 or not all(x.get('goalieProfileEvidenced') is True for x in sides)
            or current.get('g0SelectedOnlyAfterBothStarterProfiles') is not True):
        return None
    old_sides=[x for x in sides if any(
        str(z.get('goalieId'))==str(prior['opposingGoalieId'])
        for z in x.get('targetGoalies') or [])]
    if len(old_sides)!=1 or old_sides[0]['attacker']==current.get('attacker'):
        return None
    if not any(x['attacker']==current.get('attacker')
               and x['defender']==current.get('defender') for x in sides):
        return None
    old_profiles=[x for x in old_sides[0]['targetGoalies']
                  if str(x.get('goalieId'))==str(prior['opposingGoalieId'])]
    new_profiles=current.get('targetGoalies') or []
    if len(old_profiles)!=1 or len(new_profiles)!=1:
        return None
    prior_goalie,new_goalie=old_profiles[0],new_profiles[0]
    proof=current.get('g0DecisionProof') or {}
    urls=proof.get('goalieSourceUrls') or []
    original_url=prior_goalie.get('goalieProfileSourceUrl') or prior_goalie.get('sourceUrl')
    selected_url=new_goalie.get('goalieProfileSourceUrl') or new_goalie.get('sourceUrl')
    if (proof.get('oppositeDirectionSourceReviewed') is not True
            or len(urls)!=2 or set(urls)!={original_url,selected_url}
            or not all(isinstance(u,str) and u.startswith('https://') for u in urls)):
        return None
    old_id=prior_goalie.get('goalieProfileEvidenceId')
    new_id=new_goalie.get('goalieProfileEvidenceId')
    if not old_id or not new_id or old_id==new_id:
        return None
    for eid in (old_id,new_id):
        if not con.execute("SELECT 1 FROM evidence WHERE slate_date=? AND game_id=? "
                           "AND kind='GOALIE_PROFILE' AND evidence_id=?",
                           (date,gid,eid)).fetchone():
            return None
    material=_material_g0_goalie_change(
        con,existing,date,gid,(old_id,new_id))
    if material is None:
        # Replaying historical NHL EDGE values or changing G0 implementation
        # does not satisfy the user's post-card replacement evidence rule.
        return None
    identified={(str(x['game']['id']),str(x['candidate']['player']['id'])) for x in selected}
    if (identified!=set(new) or len(selected)!=3 or any(
            not x['candidate'].get('complete') or any(
                x['candidate']['dispositions'][g]['disposition']!='PASS'
                for g in MASTER) for x in selected)):
        return None
    item=next((x for x in selected if str(x['game']['id'])==str(replacement['gameId'])
        and str(x['candidate']['player']['id'])==str(replacement['playerId'])),None)
    if item is None:
        return None
    c=item['candidate']; rows=c.get('challengers') or []
    if (not rows or any(r.get('status') not in (
            'DEFEATED','DIFFERENT_TARGET_LANE',
            'SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE') for r in rows)
            or c['dispositions']['G10.5']['disposition']!='PASS'
            or c['dispositions']['G17']['disposition']!='PASS'):
        return None
    release_id=(c['player'].get('release') or {}).get('evidenceId')
    g17_id=(c['player'].get('contradictions') or {}).get('evidenceId')
    for eid in (release_id,g17_id):
        if not eid or not con.execute(
            "SELECT 1 FROM evidence WHERE slate_date=? AND game_id=? "
            "AND player_id=? AND evidence_id=?",
            (date,str(replacement['gameId']),str(replacement['playerId']),eid)).fetchone():
            return None
    return {
        'baselineFingerprint':existing['fingerprint'],
        'triggerEvidenceId':material['triggerEvidenceId'],
        'g0MaterialSourceChange':material,
        'oldValue':{'player':prior['player'],'gameId':gid,
                    'opposingGoalieId':prior['opposingGoalieId']},
        'newValue':{'player':replacement['player'],'gameId':replacement['gameId']},
        'affectedGates':['G0','G3','G4','G5','G9','G10.5','G16','G17','G18'],
        'dependentGates':['G3','G4','G5','G9','G10','G10.5','G11',
                          'G12','G13','G14','G15','G16','G17','G18'],
        'priorSurvivorFailure':{
            'playerId':prior['playerId'],'failedGate':'G0',
            'sourceIds':[old_id,new_id],
            'oldAttackSide':old_sides[0]['attacker'],
            'currentAttackSide':current['attacker'],
            'review':proof,'oldGoalie':prior_goalie['goalieId'],
            'newGoalie':new_goalie['goalieId'],
            'oldRouteExcludedBySourcedG0NotByManualSelection':True},
        'g105EveryChallenger':{'candidate':replacement['playerId'],
                               'comparisonRows':rows},
        'g17Contradictions':{'sourceIds':[g17_id],
                              'review':c['dispositions']['G17']['details']},
        'newReleaseEvidenceId':release_id,
        'newFingerprint':fingerprint(legs),
        'reason':'VERIFIED_G0_ATTACK_SIDE_REVERSAL',
        'allOriginalGatesExecutedForNewCard':True,
        'noManualPlayerSelection':True,
    }


def build_verified_replacement(con, existing, legs, selected, date, stage,
                               scan=None, selected_directions=None):
    """Automatic pre-puck replacement only after source-backed gate reruns."""
    corrected = _authorized_retraction_reselection(
        con, existing, legs, selected, date, stage)
    if corrected is not None:
        return corrected
    g0_reversal=source_verified_g0_direction_replacement(
        con,existing,legs,selected,date,scan,selected_directions)
    if g0_reversal is not None:
        return g0_reversal
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
    g105_details=(candidate['dispositions'].get('G10.5') or {}).get('details') or {}
    eliminated_before_g105=set(str(x) for x in
        (g105_details.get('eliminatedChallengersExcluded') or []))
    prior_player_eliminated_before_g105=str(old['playerId']) in eliminated_before_g105
    # The prior incumbent may correctly be absent from G10.5 rows when an
    # earlier gate (e.g. G5) already eliminated him. An empty row list is
    # valid only when every alternative was scanned and that prior elimination
    # is explicitly recorded in the G10.5 receipt.
    if (not g105_details.get('allAlternativesScanned') or
            (not rows and not prior_player_eliminated_before_g105) or
            any(r['status'] not in ('DEFEATED', 'DIFFERENT_TARGET_LANE',
                                    'SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE') for r in rows)):
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
        'g105EveryChallenger': {
            'comparisonRows': rows, 'candidate': new['playerId'],
            'allAlternativesScanned':g105_details.get('allAlternativesScanned') is True,
            'priorIncumbentEliminatedBeforeG10_5':prior_player_eliminated_before_g105,
            'eliminatedChallengersExcluded':sorted(eliminated_before_g105),
        },
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


def compare_g0_different_weak_origins(a,b):
    """When physical weak ORIGINS differ, use NHL's published area peer ranks.

    Before any skaters: two separately sourced starter goalie profiles are
    required. NHL EDGE savePctgPercentile is a PERCENTILE RELATIVE TO
    COMPARABLE GOALIES IN THAT RINK AREA; it is the only common scale
    between distinct shot-origin zones. Lowest percentile = weaker
    published save record vs NHL peers, not biggest raw goals/sample or
    shooting odds. No fabricated weight, no reputation, no skater info.

    Two independent PBP proxy profiles may share the same peer population;
    never compare a PBP-local percentile against a league EDGE percentile.
    Exact ties/noncomparable provenance remain unresolved, not guessed.
    """
    profiles=(a.get('targetGoalies') or [],b.get('targetGoalies') or [])
    if any(len(p)!=1 or p[0].get('profileReviewed') is not True for p in profiles):
        return None
    pa,pb=profiles[0][0],profiles[1][0]
    wa,wb=pa.get('weakZones') or {},pb.get('weakZones') or {}
    if not wa or not wb or set(wa)==set(wb):
        return None  # matched-zone goalie weakness requires direct comparator
    src_a=pa.get('sourceClass')
    src_b=pb.get('sourceClass')
    if src_a!=src_b:
        return None
    # Explicit NHL EDGE (official full-league percentile) or peer-sampled
    # NHL PBP (local percentile), never mixing their meaning.
    if src_a=='DERIVED_RINK_ORIGIN_NOT_ANATOMICAL':
        key='leagueSavePctgPercentile'
        method='NHL_EDGE_SOURCE_PEER_PERCENTILE_CROSS_ORIGIN_G0'
    elif src_a=='INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY':
        key='samplePeerSavePctgPercentile'
        method='NHL_PBP_SAMPLED_PEER_RANK_CROSS_ORIGIN_G0'
    else:
        return None
    def weakest(profile,zones):
        measured=[]
        for zone,metrics in zones.items():
            if not isinstance(metrics,dict):
                return None
            n=metrics.get('shotsAgainst')
            goals=metrics.get('goalsAgainst')
            percentile=metrics.get(key)
            if not (type(n) is int and n>=20 and
                    type(goals) is int and 0<goals<=n and
                    type(percentile) in (int,float) and 0<=percentile<=1):
                return None
            measured.append((percentile,zone,n,goals,metrics))
        if not measured:
            return None
        ordered=sorted(measured,key=lambda row:(row[0],row[1]))
        return ordered[0]
    weakest_a=weakest(pa,wa)
    weakest_b=weakest(pb,wb)
    if weakest_a is None or weakest_b is None:
        return None
    score_a=weakest_a[0];score_b=weakest_b[0]
    if score_a==score_b:
        # NHL EDGE and some sampled PBP peer ranks are rounded into discrete
        # percentile bands. Equal *published* percentiles do NOT mean equal
        # measured direct scoring vulnerability if the official goal/on-net
        # shot fractions are independently different. Compare those ACTUAL
        # source observations, not goalie fame, shot volume, home/away status,
        # team goal forecasts, or an invented numerical weight.
        #
        # Both goalies must have a UNIQUE weakest peer-ranked origin. If
        # either goalie has multiple tied origins, the raw-rate selection
        # would arbitrarily pick an area and MUST remain unresolved.
        for profile,weakest_row in ((pa,weakest_a),(pb,weakest_b)):
            all_weak=profile.get('weakZones') or {}
            if sum(type(z.get(key)) in (int,float) and
                   z.get(key)==weakest_row[0] for z in all_weak.values())!=1:
                return None
        _,zone_a,na,ga,_=weakest_a
        _,zone_b,nb,gb,_=weakest_b
        if ga*nb==gb*na:
            return None  # a real empirical tie, not an unresolved round-off
        chosen,other=(a,b) if ga*nb>gb*na else (b,a)
        win,lose=(weakest_a,weakest_b) if ga*nb>gb*na else (weakest_b,weakest_a)
        return {**chosen,
            'g0SelectionMethod':'TIED_PUBLISHED_PEER_PERCENTILE_DIRECT_OBSERVED_GOAL_RATE',
            'g0SelectedOnlyAfterBothStarterProfiles':True,
            'g0DecisionProof':{
                'reason':'Official peer percentiles tied, but independently observed direct goals per on-net shot differed at each goalie’s uniquely weakest source-supported origin',
                'winnerWeakOrigin':win[1],'oppositeWeakOrigin':lose[1],
                'winnerGoalieOnNetShots':win[2],'winnerGoalsAllowedFromOrigin':win[3],
                'oppositeGoalieOnNetShots':lose[2],'oppositeGoalsAllowedFromOrigin':lose[3],
                'publishedEqualPeerSavePercentile':score_a,
                'directRateComparedByExactIntegerCrossProduct':True,
                'uniqueWeakestOriginForEachGoalie':True,
                'sourceClassSameForBothGoalies':src_a,
                'noWeightsOrExternalOdds':True,
                'notGloveBlockerFiveHole':True,
                'oppositeDirectionSourceReviewed':True,
                'goalieSourceUrls':[pa.get('goalieProfileSourceUrl') or pa.get('sourceUrl'),
                                    pb.get('goalieProfileSourceUrl') or pb.get('sourceUrl')],
                'noScorerOrTeamPopularityComparison':True,
            }}
    chosen,other=(a,b) if score_a<score_b else (b,a)
    win,lose=(weakest_a,weakest_b) if score_a<score_b else (weakest_b,weakest_a)
    return {**chosen,
        'g0SelectionMethod':method,
        'g0SelectedOnlyAfterBothStarterProfiles':True,
        'g0DecisionProof':{
            'reason':'Independent goalie-origin lower published peer save percentile, not game score or skater rank',
            'winnerWeakOrigin':win[1],
            'winnerGoalieOnNetShots':win[2],
            'winnerGoalsAllowedFromOrigin':win[3],
            'winnerGoaliePeerSavePercentile':win[0],
            'oppositeWeakOrigin':lose[1],
            'oppositeGoalieOnNetShots':lose[2],
            'oppositeGoalsAllowedFromOrigin':lose[3],
            'oppositeGoaliePeerSavePercentile':lose[0],
            'samePeerComparatorScope':src_a,
            'noWeightsOrExternalOdds':True,
            'notGloveBlockerFiveHole':True,
            'oppositeDirectionSourceReviewed':True,
            'goalieSourceUrls':[pa.get('goalieProfileSourceUrl') or pa.get('sourceUrl'),
                               pb.get('goalieProfileSourceUrl') or pb.get('sourceUrl')],
        }}


def compare_g0_shared_official_pbp(a,b):
    """G0 only: compare BOTH goalies against ONE historical NHL PBP peer pool.

    The NHL EDGE league percentile and local PBP sample percentiles are NOT
    interchangeable. Only identical, date-locked peer-population IDs and
    exact goalieInNetId PBP historical receipts make this review comparable.
    The chosen attack direction still requires separate skater G3..G18
    confirmation using its independently attached goalie/defense evidence.
    """
    profiles=[x.get('targetGoalies') or [] for x in (a,b)]
    if any(len(x)!=1 for x in profiles):return None
    orig_a,orig_b=profiles[0][0],profiles[1][0]
    pa,pb=orig_a.get('sameCohortPbp'),orig_b.get('sameCohortPbp')
    if not isinstance(pa,dict) or not isinstance(pb,dict):return None
    if not all(isinstance(x.get('sourceUrl'),str)
               and x['sourceUrl'].startswith('https://') for x in (pa,pb)):
        return None
    da,db=pa.get('data') or {},pb.get('data') or {}
    population=da.get('samplePeerPopulationId')
    if not (population and population==db.get('samplePeerPopulationId') and
            da.get('sourceClass')=='INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY' and
            db.get('sourceClass')=='INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY' and
            da.get('peerSampleNeverLeagueEDGEPercentile') is True and
            db.get('peerSampleNeverLeagueEDGEPercentile') is True and
            str(da.get('goalieId'))==str(orig_a.get('goalieId')) and
            str(db.get('goalieId'))==str(orig_b.get('goalieId'))):
        return None
    wa,wb=da.get('weakZones') or {},db.get('weakZones') or {}
    if not wa and not wb:return None
    def qualified(zones):
        return all(isinstance(v,dict) and type(v.get('shotsAgainst')) is int
                   and v['shotsAgainst']>=20
                   and type(v.get('goalsAgainst')) is int
                   and 0<v['goalsAgainst']<=v['shotsAgainst']
                   and type(v.get('samplePeerSavePctgPercentile')) in (int,float)
                   and 0<=v['samplePeerSavePctgPercentile']<=1
                   and v.get('peerComparedSameOrigin') is True
                   and type(v.get('peerGoaliesSampled')) is int
                   and v['peerGoaliesSampled']>=4
                   for v in zones.values())
    if not qualified(wa) or not qualified(wb):return None
    if not wa or not wb:
        one_sided=_g0_pbp_one_sided_weakness(a,b,pa,pb,da,db,wa,wb,qualified)
        if one_sided is None:return None
        original,proof=one_sided
        return {**original,
            'g0SelectionMethod':'SAME_HISTORICAL_OFFICIAL_PBP_ONE_SIDED_WEAKNESS',
            'g0SelectedOnlyAfterBothStarterProfiles':True,
            'g0DecisionProof':{
                **proof,
                'reason':'Same pre-slate official PBP peer pool: only one goalie has a peer-qualified weak origin, and the other goalie is better on BOTH goal rate and peer rank from every one of those origins',
                'samePeerPopulationId':population,
                'goaliePbpSourceUrls':[pa['sourceUrl'],pb['sourceUrl']],
                'sourceCoherentIndependentHistoricalSample':True,
                'opposingGoaliesIndividuallyIdentified':True,
                'noWeightsOrExternalOdds':True,
                'notGloveBlockerFiveHole':True,
                'notGuaranteedTonightGoal':True,
            }}
    def comparable(original,context,zones):
        g=original['targetGoalies'][0]
        return {**original,'targetGoalies':[{
            **g,'weakZones':zones,
            'sourceClass':'INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY',
            'profileReviewed':True,'goalieProfileSourceUrl':context['sourceUrl']}]}
    aa,bb=comparable(a,pa,wa),comparable(b,pb,wb)
    chosen=compare_g0_different_weak_origins(aa,bb)
    if chosen is None and set(wa)==set(wb):
        # Same-origin zones: demand agreement between the DIRECT on-net
        # goal allowance rate and the peer comparison for EVERY zone.
        # No winner on conflict, exact ties or different peer denominators.
        winner=None
        for zone in sorted(wa):
            x,y=wa[zone],wb[zone]
            na,nb=x['shotsAgainst'],y['shotsAgainst']
            ga,gb=x['goalsAgainst'],y['goalsAgainst']
            ra,rb=x['samplePeerSavePctgPercentile'],y['samplePeerSavePctgPercentile']
            side=('a' if ra<rb and ga*nb>gb*na else
                  'b' if rb<ra and gb*na>ga*nb else None)
            if side is None or (winner is not None and winner!=side):
                return None
            winner=side
        chosen=aa if winner=='a' else bb if winner=='b' else None
    if chosen is None:return None
    original=a if chosen['attacker']==a['attacker'] else b
    proof=chosen.get('g0DecisionProof') or {}
    return {**original,
        'g0SelectionMethod':'SAME_HISTORICAL_OFFICIAL_PBP_GOALIE_PEER_POOL',
        'g0SelectedOnlyAfterBothStarterProfiles':True,
        'g0DecisionProof':{
            **proof,
            'reason':'Same pre-slate official historical goalie PBP peer sample, not mixed with NHL EDGE ranking',
            'samePeerPopulationId':population,
            'goaliePbpSourceUrls':[pa['sourceUrl'],pb['sourceUrl']],
            'sourceCoherentIndependentHistoricalSample':True,
            'opposingGoaliesIndividuallyIdentified':True,
            'noWeightsOrExternalOdds':True,
            'notGloveBlockerFiveHole':True,
            'notGuaranteedTonightGoal':True,
        }}


def _g0_pbp_one_sided_weakness(a,b,pa,pb,da,db,wa,wb,qualified):
    """Same-cohort PBP: one goalie has peer-qualified weak origins, the other none.

    Mirrors the existing EDGE superset rule (a source-reviewed goalie with no
    weak origin is negative evidence, not missing evidence) but demands more:
    for EVERY weak origin of the exposed goalie, the other goalie must have a
    peer-compared row from that SAME origin in the SAME population and be
    better on BOTH direct goals-per-on-net-shot and peer save rank. Any
    missing comparator, tie, or disagreement leaves G0 unresolved.
    """
    if wa and wb:return None
    weak_side,weak,other_data=('a',wa,db) if wa else ('b',wb,da)
    if not weak:return None
    other_areas=other_data.get('observedAreas') or {}
    if not (type(other_data.get('fullySourceComparedAreas')) is int
            and other_data['fullySourceComparedAreas']>0):
        return None
    rows=[]
    for zone in sorted(weak):
        x=weak[zone];y=other_areas.get(zone)
        if not isinstance(y,dict) or not qualified_row(y):
            return None
        nx,ny=x['shotsAgainst'],y['shotsAgainst']
        gx,gy=x['goalsAgainst'],y['goalsAgainst']
        rx,ry=x['samplePeerSavePctgPercentile'],y['samplePeerSavePctgPercentile']
        if not (rx<ry and gx*ny>gy*nx):
            return None
        rows.append({'origin':zone,
            'exposedGoalieShots':nx,'exposedGoalieGoals':gx,'exposedGoaliePeerRank':rx,
            'otherGoalieShots':ny,'otherGoalieGoals':gy,'otherGoaliePeerRank':ry})
    original=a if weak_side=='a' else b
    other=b if weak_side=='a' else a
    return original,{
        'exposedGoalieId':str((da if weak_side=='a' else db).get('goalieId')),
        'otherGoalieId':str(other_data.get('goalieId')),
        'otherGoalieWeakOrigins':[],
        'otherGoalieFullySourceComparedAreas':other_data['fullySourceComparedAreas'],
        'sameOriginComparisons':rows,
        'everyExposedOriginDirectlyCompared':True,
        'oppositeDirectionSourceReviewed':True,
        'oppositeAttacker':other.get('attacker'),
    }


def qualified_row(v):
    """Same per-origin floor used by compare_g0_shared_official_pbp."""
    return (isinstance(v,dict) and type(v.get('shotsAgainst')) is int
            and v['shotsAgainst']>=20
            and type(v.get('goalsAgainst')) is int
            and 0<=v['goalsAgainst']<=v['shotsAgainst']
            and type(v.get('samplePeerSavePctgPercentile')) in (int,float)
            and 0<=v['samplePeerSavePctgPercentile']<=1
            and v.get('peerComparedSameOrigin') is True
            and type(v.get('peerGoaliesSampled')) is int
            and v['peerGoaliesSampled']>=4)


def compare_g0_consensus_across_starters(a,b):
    """Never choose a PROJECTED starter by picking a convenient candidate.

    If every independently sourced candidate-goalie pairing agrees on one
    attacking side, that side is defensible before starter confirmation.
    Otherwise preserve all branches, record unresolved G0 and do not publish.
    """
    left=a.get('targetGoalies') or []
    right=b.get('targetGoalies') or []
    if not left or not right:return None
    agreed=None;audits=[]
    for goalie_a in left:
        for goalie_b in right:
            if not goalie_a.get('profileReviewed') or not goalie_b.get('profileReviewed'):
                return None
            aa={**a,'targetGoalies':[goalie_a]}
            bb={**b,'targetGoalies':[goalie_b]}
            choice=(compare_g0_same_origin(aa,bb)
                    or compare_g0_different_weak_origins(aa,bb)
                    or compare_g0_shared_official_pbp(aa,bb))
            if choice is None:
                return None
            if agreed is not None and choice['attacker']!=agreed:
                return None
            agreed=choice['attacker']
            audits.append({
                'attacker':choice['attacker'],
                'goalieA':goalie_a.get('goalieId'),
                'goalieB':goalie_b.get('goalieId'),
                'sourceDecisionMethod':choice.get('g0SelectionMethod') or 'MATCHED_ORIGIN_GOAL_RATE_AND_PEER_PERCENTILE',
                'proof':choice.get('g0DecisionProof'),
            })
    if not audits or agreed is None:return None
    original=a if a['attacker']==agreed else b
    return {**original,
        'g0SelectionMethod':'ALL_SOURCE_REVIEWED_STARTER_PAIRS_AGREE',
        'g0SelectedOnlyAfterBothStarterProfiles':True,
        'g0DecisionProof':{
            'allProjectedGoalieCombinationsIndependentlyChecked':len(audits),
            'eachCombinationAttacksSameSide':True,
            'pairwiseReceipts':audits,
            'projectedBranchesNeverSilentlyConfirmed':True,
            'noUnknownGoalieAssumed':True,
            'noWeightsOrArbitraryTieBreaks':True,
        }}



def partition_nonselected_g0_diagnostics(errors, selected_game_ids):
    """Separate failed G0 research for non-Core games from Core-fatal failures.

    This is called only AFTER the original G0-G18 engine independently saves a
    real card. No G0 disposition changes; unresolved games remain visible and
    still count against whole-slate research completeness. A selected game's
    G0 issue and any non-G0 error ALWAYS remain fatal.
    """
    nonselected_g0=(
        ' G0 attack sides not physically separated by certified goalie weaknesses',
        ' G0 no independently evidenced goalie target',
        ' G0 both attack directions REQUIRE independent goalie profiles',
        ' G0 neither a shared official goalie-peer comparison nor unanimous projected-starter evidence distinguished the attacking direction',
        ' G0 source consensus exists but multiple potential opposing goalies remain;',
    )
    kept=[]; notes=[]
    for message in errors:
        game_id=message.split(' ',1)[0] if isinstance(message,str) else None
        if (game_id not in selected_game_ids and isinstance(message,str) and
                any(marker in message for marker in nonselected_g0)):
            notes.append(message)
        else:
            kept.append(message)
    return kept,notes

def execute(con, snapshot, date, stage='PROJECTED', now=None):
    now=now or datetime.now(timezone.utc)
    if stage not in ('PROJECTED','CONFIRMED'):raise ValueError('Stage is projected or confirmed')
    games=snapshot.get('games',[])
    if not games:
        msg={'reason':'No official NHL game data provided','stage':stage}
        log_job(con,f'{date}-{stage}',date,stage,'SOURCE_ERROR',msg,now=now)
        # Keep the normal execution contract even when there is no player
        # pool. The CLI and evidence exporters still consume these fields;
        # a missing schedule must report its source error, not crash later
        # while printing a report that has already been persisted.
        return {'card':None,'date':date,'stage':stage,'games':0,
                'errors':[msg['reason']],'gateRows':0,'scan':[],
                'eligibleSkaterRows':0,'g0Directions':0,'g0Complete':0,
                'missingByGate':{},'preCoreQualifiedSurvivors':[],
                'gameSurvivorPool':[]}
    prior_card=get_card(con,date)
    frozen_games=sorted(str(l['gameId']) for l in (prior_card or {}).get('current_legs',[])
                        if game_started(l,now))
    scan,g0_direction_notes=g0_full_slate(games,stage)
    # Unselected opposing directions are audited, not fatal to the G0-selected side.
    errors=[]
    # Postgame learning is audit-only: original gate verdicts alone select scorers.
    records=[];qualified=[];all_survivor_receipts=[];pool_size=0
    deferred_g18=[]  # All candidate G18 receipts wait for the G16 decision
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
        options=[x for x in scan if x['gameId']==str(match['id'])]
        # HARD G0 DEPENDENCY: both source-backed starter profiles must be
        # observed, even when one is independently measured as stronger/no
        # weakness. The old len(options)==1 route selected a team SOLELY
        # because the opposing goalie had no data, never an evidence decision.
        if len(options)!=2 or not all(o['goalieProfileEvidenced'] for o in options):
            errors.append(f"{match['id']} G0 both attack directions REQUIRE independent goalie profiles; one-sided source presence is NOT a selection rule")
            continue
        # Never choose an attack side from the NUMBER or containment of
        # weak-zone labels. Different zone sets are not a vulnerability
        # comparison: each goalie must be compared using its source-backed
        # per-origin peer percentile and observed goals/on-net shots below.
        # Same-origin and cross-origin comparators are the only quantitative
        # G0 decisions; unresolved or noncomparable profiles remain unresolved.
        comparative=compare_g0_same_origin(options[0],options[1])
        if comparative is not None:
            selected_directions[str(match['id'])]={**comparative,
                'g0SelectionMethod':'MATCHED_ORIGIN_DIRECT_GOAL_RATE_AND_PEER_PERCENTILE',
                'g0SelectedOnlyAfterBothStarterProfiles':True}
            continue
        # Different goalie weaknesses are not unreviewed/uncomparable merely
        # because they come from different named zones. Compare the league's
        # normalized SOURCE percentile on each goalie's independently
        # demonstrated worst vulnerable origin, while the full opposing
        # profiles stay on record and every skater later passes G4/G5/G9.
        distinct=compare_g0_different_weak_origins(options[0],options[1])
        if distinct is not None:
            selected_directions[str(match['id'])]=distinct
            continue
        # Both goalie directions and every projected starter must be
        # source-reviewed BEFORE advancing players. A common official PBP
        # peer cohort can resolve mixed NHL EDGE/PBP evidence WITHOUT ever
        # comparing their incompatible percentile populations directly.
        consensus=compare_g0_consensus_across_starters(options[0],options[1])
        if consensus is not None and len(consensus['targetGoalies'])==1:
            selected_directions[str(match['id'])]=consensus
            continue
        if consensus is not None:
            # An attack side can be consistent across all projected goalies,
            # yet a SPECIFIC opposing goalie still isn't independently
            # identified. The scorer matrix is keyed by official player ID,
            # so proceeding through two goalie branches would overwrite the
            # other branch's source proof and falsely certify one result.
            # Continue ALL source checks in namespaced G0 research instead.
            errors.append(f"{match['id']} G0 source consensus exists but multiple potential opposing goalies remain; cannot bind unique scorer-to-goalie route")
            continue
        errors.append(f"{match['id']} G0 neither a shared official goalie-peer comparison nor unanimous projected-starter evidence distinguished the attacking direction")
    # G0 supplies the opponent context. G17 source verification happens
    # only at the independent G17 gate, never immediately following G0.
    g17_review_summary={'reviewedSkaters':0,'unresolved':0,
                        'resolvedFromSourceEvidence':0,'computedAtGate':'G17'}
    def review_at_g17(match,attack_team,person,eliminated_before):
        from .contradiction_review import review_all_candidates
        gid=str(match['id'])
        decision=selected_directions.get(gid)
        report=review_all_candidates(
            con,{'games':[match]},date,stage,
            selected_directions={gid:decision} if decision else None,
            only_player_ids={str(person['id'])},
            eliminated_player_ids=eliminated_before,
            return_receipts=True)
        for key in ('reviewedSkaters','unresolved','resolvedFromSourceEvidence'):
            g17_review_summary[key]+=report.get(key,0)
        return report['receipts'].get(str(person['id']))
    # A G0 failure MUST NOT silently short-circuit all 36 source checks.
    # Investigate each available goalie branch against each official skater
    # on BOTH sides, while retaining a FAILED G0 and forbidding selection.
    unresolved_branch_analyses=[]
    unresolved_unique_pool=0
    for match in games:
        gid=str(match['id'])
        if gid in selected_directions:
            continue
        started=match.get('gameState') in ('LIVE','CRIT','OFF','FINAL') or (
            match.get('startUTC') and
            datetime.fromisoformat(match['startUTC'].replace('Z','+00:00'))<=now)
        if started:
            continue
        for attacker,defender in ((match['away'],match['home']),
                                  (match['home'],match['away'])):
            players=complete_roster(match,attacker)
            unresolved_unique_pool+=len(players)
            branches=all_goalie_branches(match,stage).get(defender,[])
            for branch in branches:
                goalie_id=str(branch['data'].get('goalieId') or 'UNKNOWN')
                scoped_players=[release_matched_to_g0_target(
                    player,branch,match.get('coverage',{}).get(attacker)) for player in players]
                stopped=stopped_before_g10_5([
                    evaluate_skater(match,attacker,x,players,branch,stage,
                                     stop_at_g10=True)[0]
                    for x in scoped_players])
                for player,scoped in zip(players,scoped_players):
                    # No _g0SelectedDirection: these are NOT proposed Core
                    # paths. Every gate is physically checked with the real
                    # source branch, but G0 and G18 must remain nonpassing.
                    candidate,trace=evaluate_skater(
                        match,attacker,scoped,players,branch,stage,
                        stopped_before_g10_5=stopped,
                         g17_review=review_at_g17)
                    if candidate['dispositions']['G0']['disposition']=='PASS' or candidate['complete']:
                        raise ValueError('G0 research cannot become a certified scorer')
                    research_id=f'G0_RESEARCH:{attacker}:{goalie_id}:{player["id"]}'
                    for row in trace:
                        row['playerId']=research_id
                        row['details']['g0ResearchOnly']=True
                        row['details']['actualOfficialPlayerId']=str(player['id'])
                        row['details']['researchGoalieId']=goalie_id
                        row['details']['g0DirectionNotDecided']=True
                        row['details']['cannotBeSelectedOrPublished']=True
                    if [row['gate'] for row in trace]!=EXECUTION_ORDER:
                        raise ValueError('G0 research skipped master or overlay gates')
                    records.extend(trace)
                    unresolved_branch_analyses.append({
                        'gameId':gid,'attacker':attacker,'goalieId':goalie_id,
                        'playerId':str(player['id']),
                        'masterAndOverlayChecks':len(trace),
                        'g0Disposition':'NOT_EXECUTED',
                        'cannotEnterG18Card':True})
    # Missing G0 direction remains a hard selection blocker. It is NOT
    # permission to skip the rest of the physical-evidence investigation.
    # game_pool: every game's own Blender outcome (the Core player pool).
    # Display/receipt only; it never selects, ranks or reopens anyone.
    game_pool={}
    def pool_entry(match,status,**extra):
        game_pool[str(match['id'])]={'gameId':str(match['id']),
            'matchup':match['away']+'@'+match['home'],
            'gameStartUTC':match.get('startUTC'),'status':status,**extra}
    # Phase A: evaluate every G0-selected candidate through G16 without
    # running G17 or saving provisional scorer-gate rows.
    required_core=2 if len(games)==2 else 3
    pre_g17_qualified=[]
    for preliminary_game in games:
        gid=str(preliminary_game['id'])
        started=(preliminary_game.get('gameState') in ('LIVE','CRIT','OFF','FINAL') or
                 (preliminary_game.get('startUTC') and datetime.fromisoformat(
                     preliminary_game['startUTC'].replace('Z','+00:00'))<=now))
        direction=selected_directions.get(gid)
        if started or direction is None:
            continue
        attack=direction['attacker']
        team_players=complete_roster(preliminary_game,attack)
        if not team_players:
            continue
        for original in all_goalie_branches(
                preliminary_game,stage).get(direction['defender'],[]):
            goalie=g0_source_coherent_scorer_goalie(
                preliminary_game,direction,original)
            scoped={**preliminary_game,'_g0SelectedDirection':direction}
            scoped_players=[release_matched_to_g0_target(
                person,goalie,preliminary_game.get('coverage',{}).get(attack))
                for person in team_players]
            stopped=stopped_before_g10_5([
                evaluate_skater(scoped,attack,person,team_players,goalie,stage,
                                stop_at_g10=True)[0]
                for person in scoped_players])
            for person in scoped_players:
                early,_=evaluate_skater(
                    scoped,attack,person,team_players,goalie,stage,
                    stopped_before_g10_5=stopped,
                    stop_at_g16=True,defer_g18=True)
                if early['preG17Qualified']:
                    pre_g17_qualified.append({
                        'game':preliminary_game,'attackTeam':attack,
                        'targetGoalie':goalie,'candidate':early})
    # Original G16 source comparison now occurs before any G17 review.
    g16_receipt=None
    g16_decisions={}
    if len(pre_g17_qualified)>required_core:
        # Check the entire full-slate pool, even with multiple contenders
        # from one game. Same-game recipient separation remains governed by
        # G10.5/G17; G18 still requires one survivor from each game.
        _,g16_receipt=g16_cross_game_finalists(pre_g17_qualified,required_core)
        _,g16_receipt=revalidate_authoritative_finalists(
            con,date,pre_g17_qualified,g16_receipt,required_core)
        g16_decisions={(str(x['gameId']),str(x['playerId'])):x
                       for x in g16_receipt['finalists']}
    # Phase B records the one authoritative G0-G18 trace for each skater.
    for match in games:
        is_started=match.get('gameState') in ('LIVE','CRIT','OFF','FINAL') or (
            match.get('startUTC') and datetime.fromisoformat(match['startUTC'].replace('Z','+00:00')) <= now)
        if is_started:
            # Not eligible for new selection; frozen cards remain in storage.
            pool_entry(match,'STARTED_NOT_ELIGIBLE_FOR_NEW_SELECTION')
            continue
        direction=selected_directions.get(str(match['id']))
        if direction is None:
            pool_entry(match,'NO_SURVIVOR',stoppedAt='G0',
                       reason='G0 did not decide which goalie is attacked')
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
        first_stops=defaultdict(int); furthest={}
        for original_branch in branches:
            branch=g0_source_coherent_scorer_goalie(match,direction,original_branch)
            scoped_game={**match,'_g0SelectedDirection':direction}
            scoped_players=[release_matched_to_g0_target(player,branch,match.get('coverage',{}).get(team))
                            for player in players]
            # Pass 1 actually executes only G0-G10 (teammate-independent).
            # No G10.5/G16/G17 decisions are computed before the rivals are scoped.
            stopped=stopped_before_g10_5([
                evaluate_skater(scoped_game,team,x,players,branch,stage,
                                 stop_at_g10=True)[0]
                for x in scoped_players])
            for scoped in scoped_players:
                # Bind the G0 direction receipt to every skater checked after
                # goalie-first selection; never infer direction from a PASS.
                result,traces=evaluate_skater(scoped_game,team,scoped,players,branch,stage,
                                              stopped_before_g10_5=stopped,defer_g18=True,
                                               g17_review=review_at_g17,
                                               cross_game_g16=g16_decisions.get(
                                                   (str(match['id']),str(scoped['id']))))
                records+=traces
                deferred_g18.append((match,result))
                stop=next((g for g in MASTER[:-1] if
                           (result['dispositions'].get(g) or {}).get('disposition')!='PASS'),None)
                if stop:
                    stop_label=f"{stop}:{result['dispositions'][stop]['disposition']}"
                    first_stops[stop_label]+=1
                    furthest.setdefault(MASTER.index(stop),[]).append({
                        'playerId':str(result['player']['id']),
                        'player':result['player'].get('name'),'stoppedAt':stop_label})
                if result['preCoreQualified']:
                    # G18 has not run yet. Qualified G0-G17 players cannot be
                    # discarded because G18's final-card path label is still
                    # unclassified. Keep the exact evidence deficit visible.
                    all_per_game.append({'game':match,'attackTeam':team,'targetGoalie':branch,
                                         'candidate':result})
                    z=result['release']['zone']
                    gweak=branch['data'].get('weakZones') or {}
                    defense=match.get('coverage',{}).get(team) or {}
                    coverage=(defense.get('data') or {}).get('zoneConcessions') or {}
                    own=result['player']
                    all_survivor_receipts.append({
                        'gameId':str(match['id']),
                        'matchup':match['away']+'@'+match['home'],
                        'gameStartUTC':match.get('startUTC'),
                        'attackTeam':team,'opponentTeam':opponent,
                        'playerId':str(own['id']),'player':own.get('name'),
                        'routeLabel':result['route'],
                        'pathClassificationStatus':('G18_PATH_SOURCE_CERTIFIED'
                            if result['route'] else 'G18_PATH_NOT_YET_CERTIFIED'),
                        'pathClassificationEvidence':result.get('pathEvidence',{}),
                        'ownRouteZone':z,
                        'ownedGoals':result['release']['ownedGoals'],
                        'ownShotsOnGoal':result['release']['attempts'],
                        'routeSource':(own.get('release') or {}).get('sourceUrl'),
                        'goalieId':branch['data'].get('goalieId'),
                        'goalieStatus':branch['data'].get('status'),
                        'goalieSourceUrl':branch['data'].get('goalieProfileSourceUrl'),
                        'goalieObservedZoneStats':gweak.get(z),
                        'independentOpponentDefense':coverage.get(z),
                        'defenseSourceUrl':defense.get('sourceUrl'),
                        'deployment':(own.get('deployment') or {}).get('data'),
                        'deploymentSourceUrl':(own.get('deployment') or {}).get('sourceUrl'),
                        'nonRankingDiagnosticOnly':True,
                    })
        far=furthest.get(max(furthest)) if furthest else []
        base=dict(attackTeam=team,opponentTeam=opponent,
                  targetGoalieIds=[b['data'].get('goalieId') for b in branches],
                  candidatesEvaluated=len(players),
                  firstNonPassGateCounts=dict(sorted(first_stops.items())),
                  furthestCandidatesDiagnosticOnly=far[:5] if len(all_per_game)==0 else [])
        if len(all_per_game)==1:
            own=all_per_game[0]['candidate']['player']
            pool_entry(match,'SURVIVOR',**base,survivor=next(
                (r for r in all_survivor_receipts if r['gameId']==str(match['id'])
                 and r['playerId']==str(own['id'])),{'playerId':str(own['id']),'player':own.get('name')}))
        elif len(all_per_game)>1:
            pool_entry(match,'UNSEPARATED_SAME_GAME_SURVIVORS',**base,
                       survivors=[{'playerId':str(x['candidate']['player']['id']),
                                   'player':x['candidate']['player'].get('name')} for x in all_per_game])
        else:
            pool_entry(match,'NO_SURVIVOR',**base,
                       # The furthest first failure of any REJECTED skater is
                       # not a uniquely remaining game-wide source blocker.
                       furthestFirstNonPassGate=MASTER[max(furthest)] if furthest else None,
                       reason='no candidate passed every pre-Core gate G0-G17')
        if len(all_per_game)==1:
            qualified.append(all_per_game[0])
        elif len(all_per_game)>1:
            # G18 is the final Core CARD, not a new game-level scorer ranker.
            # Keep all fully qualified source receipts; require the original
            # G10.5/G17 comparison to actually separate same-game rivals.
            errors.append(
                f"{match['id']} PRE_CORE_REVIEW: {len(all_per_game)} qualified same-game "
                "recipients remain after G10.5/G17; no arbitrary final pick")
    pool_size+=unresolved_unique_pool
    # G16 already decided cross-game Core eligibility before G17.
    # A non-selected game winner remains a G16-qualified game survivor.
    selected_g16={(str(x['gameId']),str(x['playerId']))
                  for x in (g16_receipt or {}).get('finalists',[])
                  if str(x.get('g16Decision') or '').startswith('RETAINED')}
    finalists=[x for x in qualified if not g16_receipt
               or (str(x['game']['id']),str(x['candidate']['player']['id']))
                  in selected_g16]
    chosen,selection_errors=cross_game_winners(finalists,len(games))
    if g16_receipt and not g16_receipt['separated'] and len(finalists)>required_core:
        selection_errors.insert(0,
            f"G16 retained {len(finalists)} G17-surviving finalists for "
            f"Core {required_core}; original full-slate sources did not separate them")
    # A started canonical leg is closed, not a vacancy for another game.
    # Keep researching the unstarted recipients without issuing a second Core.
    if frozen_games:
        chosen=[]
        selection_errors=[]
    # Finish the same G16 adjudication across ALL game survivors before
    # writing the only authoritative G18 final-card decision.
    final_keys={(str(x['game']['id']),str(x['candidate']['player']['id']))
                for x in chosen} if not selection_errors else set()
    decisions={(str(x['gameId']),str(x['playerId'])):x
               for x in ((g16_receipt or {}).get('finalists') or [])}
    for match,candidate in deferred_g18:
        key=(str(match['id']),str(candidate['player']['id']))
        finalist=decisions.get(key)
        if finalist:
            # Inspect the pre-G17 G16 verdict; never mutate it afterward.
            g16=candidate['dispositions']['G16']
            actual=g16['details'].get('crossGameFinalistCompetition')
            if not actual or actual.get('decision')!=finalist['g16Decision']:
                raise ValueError('G16 cross-game result missing before G17')
            if finalist['g16Decision'].startswith('EXCLUDED_') and g16['disposition']!='ELIMINATED':
                raise ValueError('Excluded G16 contender was not rejected before G17')
            if g16['details'].get('globalG16AppliedBeforeG17') is not True:
                raise ValueError('Pre-G17 G16 full-slate decision absent')
        # Only the actual G16-selected recipient may be G18 certified;
        # per-game G0-G17 qualification is NOT conditional on a G18 label.
        # Missing final path evidence fails G18 with explicit audit gaps,
        # rather than vanishing a real pre-Core survivor at G10.5.
        selected=key in final_keys and candidate['preCoreQualified']
        proof={
            'candidateEligibleForCrossGameFinal':bool(candidate['preCoreQualified']),
            'pathClassificationEvidence':candidate['pathEvidence'],
            'classificationOccursAfterAllSourceGates':True,
            'originalFunctionsReviewedBeforeG18':True,
            'notPresetOneOfEach':True,
            'G18FinalAssemblyAfterFullG16':True,
            'frozenCanonicalCardPreventsNewIssuance':bool(frozen_games),
            'G18CoreSlotGrantedOnlyAfterG16':bool(selected),
            'G16FinalistDecision':(finalist or {}).get('g16Decision'),
            'G16Exclusion':(finalist or {}).get('dominatedBy',[]) if not selected else [],
        }
        urls=candidate['pathEvidence'].get('sourceUrls',[])
        gaps=audit_gate('G18',proof,urls,stage) if selected else []
        if gaps:
            selection_errors.append(
                f"{key[0]} player {key[1]} G18 final source certification: {gaps}")
            proof['semanticProofGaps']=gaps
        disposition='PASS' if selected and not gaps else 'NOT_EXECUTED'
        candidate['dispositions']['G18']={'disposition':disposition,'details':proof}
        candidate['complete']=disposition=='PASS'
        records.append(gate_record(match,key[1],'G18',disposition,proof,urls))
    # Exactly one authoritative row for every original gate per skater.
    # Only the true final Core recipients are allowed a G18 PASS.
    save_gates(con,date,stage,records,now=now)
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
                audit=build_verified_replacement(
                    con,existing,legs,chosen,date,stage,
                    scan=scan,selected_directions=selected_directions)
                if not audit:
                    raise ValueError('Different scorer candidates did not satisfy a verified old-to-new source, prior-player failure, and G10.5/G17 replacement audit; the original card is preserved.')
            evidence_stage=stage
            if stage=='CONFIRMED' and any(
                x['targetGoalie']['data'].get('status')!='CONFIRMED' or
                x['candidate']['player'].get('availability') not in ('DRESSED','CONFIRMED') or
                (x['candidate']['player'].get('deployment') or {}).get('data',{}).get('status')!='CONFIRMED'
                for x in chosen):
                evidence_stage='MIXED'
            card=save_card(con,date,evidence_stage,legs,len(games),audit=audit,now=now)
        except ValueError as e:errors.append(str(e))
    # Additional matchups are allowed to have unseparated goalies once
    # three distinct, source-qualified game recipients have been saved.
    # Such a game is still recorded as rejected by G0. It is NOT a failure
    # of a separately certified and preserved Core 3.
    nonselected_game_notes=[]
    if card:
        errors,nonselected_game_notes=partition_nonselected_g0_diagnostics(
            errors,{str(x['gameId']) for x in card['current_legs']})
    gaps=defaultdict(int)
    g18_intentionally_not_selected=0
    for rec in records:
        if rec['disposition']!='NOT_EXECUTED':
            continue
        # A non-Core player deliberately does not pass final assembly G18.
        # This is not a missing G18 source, and must not inflate source gaps.
        evidence=(rec.get('details') or {}).get('evidence') or {}
        if (rec['gate']=='G18' and
            evidence.get('G18FinalAssemblyAfterFullG16') is True and
            evidence.get('G18CoreSlotGrantedOnlyAfterG16') is False):
            g18_intentionally_not_selected+=1
        else:
            gaps[rec['gate']]+=1
    result={'card':card,'date':date,'stage':stage,'games':len(games),
            'g0TwoGoalieDirectionDecisions':{
                gid:{'attackingTeam':d['attacker'],'targetGoalieTeam':d['defender'],
                     'goalieSourceMethod':d.get('g0SelectionMethod') or 'SOURCE_WEAK_ZONE_SET_CONTAINMENT',
                     'decisionEvidence':d.get('g0DecisionProof'),
                     'bothGoaliesReviewedFirst':True,
                     'isAnatomicalWeaknessClaim':False}
                for gid,d in selected_directions.items()},
            'g0Directions':len(scan),'g0Complete':sum(bool(x['goalieProfileEvidenced']) for x in scan),
            'eligibleSkaterRows':pool_size,'gateRows':len(records),
            'g17ReviewSummary':g17_review_summary,
            # Audit counts are a summary, never the gate schedule.  Preserve
            # the original chronological order even when the first missing
            # receipt appears late in an arbitrary roster/branch iteration.
            'gateExecutionOrder':EXECUTION_ORDER[:],
            'missingByGate':{gate:gaps[gate] for gate in EXECUTION_ORDER if gaps[gate]},
            'g18IntentionallyNotSelectedNotMissingSource':g18_intentionally_not_selected,
            'unresolvedG0ResearchBranchCount':len(unresolved_branch_analyses),
            'unresolvedG0PlayerSourceChecks':sum(x['masterAndOverlayChecks']
                    for x in unresolved_branch_analyses),
            'unresolvedG0ResearchDoesNotSelect':True,
            'unresolvedG0ResearchExamples':unresolved_branch_analyses[:20],
            'uniqueGameSurvivors':len(qualified),
            'g16FinalistCompetition':g16_receipt,
            'preCoreQualifiedSurvivors':all_survivor_receipts,
            'gameSurvivorPool':_finish_pool(games,game_pool,card,g16_receipt),
            'nonselectedGameResearchNotes':nonselected_game_notes,
            'nonselectedGameResearchNeverReplacesLockedCore':True,
            'retroactiveCardMutation':False,
            'frozenCardContinuation':({
                'cardId':prior_card['card_id'],'fingerprint':prior_card['fingerprint'],
                'revision':prior_card['revision'],'frozenGameIds':frozen_games,
                'reviewedAt':stamp(now),'newCardIssued':False,
                'reason':'Started canonical legs remain closed; independently recheck every unstarted incumbent'
            } if frozen_games else None),
            'errors':errors,'scan':scan}
    log_job(con,f'{date}-{stage}',date,stage,'COMPLETE' if card else 'INPUT_INCOMPLETE',
            {k:v for k,v in result.items() if k not in ('card','scan')},now=now)
    return result

