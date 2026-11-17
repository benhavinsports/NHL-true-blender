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
        'nonselectedGameResearchNotes':result.get('nonselectedGameResearchNotes',[]),
        'nonselectedGameResearchIsDiagnosticOnly':True,
        'allG18QualifiedSurvivors':result.get('allG18QualifiedSurvivors',[]),
        'cardSavedByEngine':bool(card),
        'publishedToSite':False,
        'edgeSourceCoverage':result.get('edgeSourceCoverage',{}),
        'lineupSourceCoverage':result.get('lineupSourceCoverage',{}),
        'datedGoalieSourceCoverage':result.get('datedGoalieSourceCoverage',{}),
        'g0RinkOriginResearch':result.get('g0RinkOriginResearch',[]),
        'g0TwoGoalieDirectionDecisions':result.get('g0TwoGoalieDirectionDecisions',{}),
        'g0OfficialPbpFallback':result.get('g0OfficialPbpFallback',{}),
        'bothGoaliesRequiredBeforeG0PlayerElimination':True,
        'anatomicalEvidenceMisrepresented':False,
        'officialBoxscoreCoverage':result.get('officialBoxscoreCoverage',{}),
        'officialDefenseCoverage':result.get('officialDefenseCoverage',{}),
        'historicalShiftCoverage':result.get('historicalShiftCoverage',{}),
        'firstNonpassingGateAudit':result.get('firstNonpassingGateAudit',{}),
        'gateCertification':result.get('gateCertification',{}),
        'selectionFunnel':(result.get('gateCertification') or {}).get('selectionFunnel',{}),
        'survivorOnlyCertification':(result.get('gateCertification') or {}).get('selectedCoreOnlyFullyCertified'),
        'nonselectedGateAuditIsDiagnosticOnly':True,
    }
    # "Gate executed" and "player passed the gate" are distinct. Every
    # surveyed skater MUST have an ordered receipt for every gate, but rejected
    # skaters are expected to have ELIMINATED / NOT_EXECUTED source outcomes.
    # Those outcomes remain visible in missingByGate; they do not disqualify
    # fully proven surviving recipients. The recipient-specific checks below
    # independently enforce all 36 PASSes and their source/overlay evidence.
    census=result.get('gateCertification') or {}
    scanned=census.get('scannedSkaters')
    attempts=census.get('gateChecksAttempted') or {}
    all_gates_attempted=(type(scanned) is int and scanned>0
        and all(attempts.get(gate)==scanned for gate in MASTER+OVERLAY))
    full_execution=(
        all_gates_attempted
        and census.get('allSkatersHaveEachGateRecord') is True
        and census.get('allSkatersHaveExactExecutionOrder') is True
        and census.get('allOverlayStepsWereIndependentlyChecked') is True
        and census.get('copiedOverlayReceiptCount') == 0
        and census.get('twoDirectionsPerScheduledGameRecorded') is True
    )
    if not full_execution:
        prior=root/'site_cards'/f'{slate_date}.json'
        old=json.loads(prior.read_text(encoding='utf-8')) if prior.exists() else None
        status.update({
            'currentRunFullyCertified':False,
            'publishedToSite':False,
            'retainedOriginalLockedCard':bool(old),
            'cardId':old.get('cardId') if old else None,
            'publicationDecision':'FULL_GATE_EXECUTION_INCOMPLETE',
            'executionCertificationGaps':{
                'missingByGate':result.get('missingByGate',{}),
                'fullIndependentCardCertification':census.get('fullIndependentCardCertification'),
                'allGateChecksExecutedWithEvidence':census.get('allGateChecksExecutedWithEvidence'),
                'allSkatersHaveEachGateRecord':census.get('allSkatersHaveEachGateRecord'),
                'allSkatersHaveExactExecutionOrder':census.get('allSkatersHaveExactExecutionOrder'),
                'twoDirectionsPerScheduledGameRecorded':census.get('twoDirectionsPerScheduledGameRecorded'),
            },
        })
        _write(status_path,status)
        return status
    if not card:
        # Post-puck freeze is intentional: the selection engine may no longer
        # issue a new card even though today's ORIGINAL locked card is saved.
        # Do not erase or mark that frozen Core unpublished. Keep the prior
        # artifact unchanged, and distinguish an audit from a new selection.
        prior=root/'site_cards'/f'{slate_date}.json'
        if prior.exists():
            locked=json.loads(prior.read_text(encoding='utf-8'))
            status.update({
                'cardId':locked.get('cardId'),
                'publishedToSite':True,
                'retainedOriginalLockedCard':True,
                'currentRunFullyCertified':bool(
                    (result.get('gateCertification') or {}).get('selectedCoreOnlyFullyCertified')),
                'publicationDecision':'PRESERVED_FROZEN_CORE_NO_NEW_SELECTION',
            })
        else:
            status['publicationDecision']='NO_ELIGIBLE_G18_CARD'
            status['currentRunFullyCertified']=False
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
    validation_gaps=[]
    for leg in legs:
        game_id, player_id = str(leg['gameId']),str(leg['playerId'])
        rows=con.execute("""SELECT gate, disposition, details FROM gates
               WHERE slate_date=? AND stage=? AND game_id=? AND player_id=?""",
               (slate_date,stage,game_id,player_id)).fetchall()
        trace={x['gate']:x for x in rows}
        if set(trace)!=required:
            validation_gaps.append({'gameId':game_id,'playerId':player_id,
                'missingGateRows':sorted(required-set(trace))})
            continue
        incomplete={g:x['disposition'] for g,x in trace.items() if x['disposition']!='PASS'}
        alias=[g for g,x in trace.items() if g in OVERLAY and
               not (json.loads(x['details']).get('evidence',{})
                    .get('independentOverlayEvaluation') is True)]
        if incomplete or alias:
            validation_gaps.append({'gameId':game_id,'playerId':player_id,
                'notPassing':incomplete,'copiedOverlayGates':alias})
            continue
        g0=json.loads(trace['G0']['details'])['evidence']
        if leg.get('opposingGoalieId') and str(g0.get('targetGoalie'))!=str(leg['opposingGoalieId']):
            raise PublicationConflict('G0 starter branch does not match final recipient')
        if any(not leg.get(k) for k in ('player','path','startUTC','sourceIds')):
            raise PublicationConflict('Recipient source or game-time field missing')
        if leg['path'] not in ('PRIMARY','TRANSFER','WHO'):
            raise PublicationConflict('Unsupported scorer path label')
    # Selected-recipient certification is the publication requirement:
    # nonselected players are allowed to fail or lack scorer evidence.
    # If the independent census exists, do not publish a new card when its
    # selected recipients have not all been genuinely verified.
    source_census=result.get('gateCertification') or {}
    if source_census and source_census.get('selectedCoreOnlyFullyCertified') is not True:
        validation_gaps.append({
            'reason':'SELECTED_CORE_INDEPENDENT_SOURCE_CERTIFICATION_FAILED',
            'selectedLegSourceGaps':source_census.get('selectedSourceAttributionGaps',[]),
            'selectedLegReviews':source_census.get('selectedLegs',[]),
        })
    # A newly missing independent overlay source cannot retroactively
    # overwrite or erase the previously frozen Core. Keep its immutable
    # JSON, record the exact current audit failure and do NOT claim that
    # the new run recertified the original card. No invented PASS/transfer.
    if validation_gaps:
        previous=root/'site_cards'/f'{slate_date}.json'
        retained=previous.exists()
        status.update({
            'currentRunFullyCertified':False,
            'independentOverlaySourceGaps':validation_gaps,
            'retainedOriginalLockedCard':retained,
            'publishedToSite':retained,
            'cardId':card['card_id'] if retained else None,
            'publicationDecision':'PRESERVED_ORIGINAL_WITH_AUDIT_GAPS' if retained
                                  else 'NEW_CARD_NOT_PUBLISHED_INCOMPLETE_OVERLAY',
        })
        _write(status_path,status)
        return status
    status['currentRunFullyCertified']=True
    status['publicationDecision']='SOURCE_CERTIFIED_AND_PUBLISHED'
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
    # Record issuance once, at the actual first publication. This is
    # provenance, never a reconstructed timestamp from a later grade/run.
    # A later confirmed pass may retain the original issuance but cannot
    # manufacture an earlier one for a legacy card.
    if path.exists():
        old=json.loads(path.read_text(encoding='utf-8'))
        if old.get('issuedAtUTC'):
            payload['issuedAtUTC']=old['issuedAtUTC']
        # Never erase a postgame grade during a late projected/confirmed
        # replay. The grade is attached to the immutable original card.
        if old.get('gradeJson') and json.loads(old['gradeJson'] or '{}'):
            if old.get('cardId')!=payload['cardId']:
                raise PublicationConflict('Cannot replay over a graded card')
            payload['gradeJson']=old['gradeJson']
            payload['auditJson']=old.get('auditJson','')
            payload['status']=old.get('status','FROZEN_GRADED')
        # Existing cards without a first-issuance receipt stay explicitly
        # unknown. Never backfill from a later confirmation or postgame run.
    else:
        issued=datetime.now(timezone.utc)
        from datetime import datetime as _dt
        starts=[_dt.fromisoformat(str(leg['startUTC']).replace('Z','+00:00'))
                for leg in legs]
        if any(issued>=start for start in starts):
            raise PublicationConflict(
                'First card publication occurred at/after a leg puck drop; '
                'refusing to invent a pre-puck issuance')
        payload['issuedAtUTC']=issued.isoformat(timespec='seconds')
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
