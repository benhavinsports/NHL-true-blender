"""Independently verify frozen Core identity and fresh unstarted gate evidence."""
import json
from datetime import datetime
from pathlib import Path

from nhl_true_blender_engine.engine import EXECUTION_ORDER, STEPS_BY_GATE
from nhl_true_blender_engine.semantic_certification import audit_gate
from nhl_true_blender_engine.storage import fingerprint, get_card
from scripts.preserved_core_receipt import verified_original_receipt


def _clock(value):
    t=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    assert t.tzinfo is not None, 'Clock lacks timezone'
    return t


def capture_current_incumbent_reviews(con,date,stage,card):
    return [{'gameId':str(l['gameId']),'playerId':str(l['playerId']),
        'rows':[dict(r) for r in con.execute('''SELECT gate,disposition,details,evaluated_at
            FROM gates WHERE slate_date=? AND stage=? AND game_id=? AND player_id=?''',
            (date,stage,str(l['gameId']),str(l['playerId']))).fetchall()]}
        for l in card['current_legs']]


def verify_frozen_continuation(root,date,run):
    root=Path(root)
    assert run.get('slateDate')==date and run.get('stage') in ('PROJECTED','CONFIRMED'), 'Invalid continuation phase or date'
    proof=run.get('frozenCardContinuation') or {}
    card=json.loads((root/'site_cards'/f'{date}.json').read_text())
    assert verified_original_receipt(root,date,card), 'Original frozen G0-G18 source cohort is unverified'
    legs=json.loads(card['legsJson'])
    assert (proof.get('cardId')==card.get('cardId') and
        proof.get('fingerprint')==card.get('fingerprint')==fingerprint(legs) and
        proof.get('revision')==card.get('revision') and proof.get('newCardIssued') is False), 'Frozen identity changed'
    now=_clock(proof['reviewedAt'])
    frozen={str(l['gameId']) for l in legs if _clock(l['startUTC'])<=now}
    assert frozen and frozen==set(proof.get('frozenGameIds') or []), 'Incorrect puck-drop freeze set'
    reviews=proof.get('incumbentReviews') or []
    by_key={(str(r['gameId']),str(r['playerId'])):r for r in reviews}
    identities={(str(l['gameId']),str(l['playerId'])) for l in legs}
    assert len(reviews)==len(legs) and set(by_key)==identities, 'Incumbent review identities differ'
    census=run.get('gateCertification') or {}
    n=census.get('scannedSkaters')
    assert type(n) is int and n>=0, 'Missing current candidate count'
    assert (census.get('allSkatersHaveEachGateRecord') is True and
        census.get('allSkatersHaveExactExecutionOrder') is True and
        census.get('allOriginalFunctionsWereCheckedWithinGates') is True and
        census.get('copiedOverlayReceiptCount')==0 and
        census.get('twoDirectionsPerScheduledGameRecorded') is True), 'Current source execution incomplete'
    for gate in EXECUTION_ORDER:
        assert (census.get('gateChecksAttempted') or {}).get(gate)==n, 'Current gate matrix incomplete'
    assert ((census.get('masterGateDispositions') or {}).get('G18') or {}).get('PASS',0)==0, 'Another Core was authorized after freeze'
    for leg in legs:
        key=(str(leg['gameId']),str(leg['playerId']))
        rows=by_key[key]['rows']
        if key[0] in frozen:
            assert not rows, 'Started recipient was monitored again'
            continue
        by_gate={r['gate']:r for r in rows}
        assert len(rows)==len(EXECUTION_ORDER) and set(by_gate)==set(EXECUTION_ORDER), 'Missing unstarted recipient source gates'
        for index,gate in enumerate(EXECUTION_ORDER):
            row=by_gate[gate];details=json.loads(row['details']);ev=details.get('evidence') or {}
            assert details.get('executionIndex')==index, 'Unstarted gate order differs'
            assert _clock(row['evaluated_at'])==now<_clock(leg['startUTC']), 'Stale or post-puck unstarted review'
            if gate=='G18':
                assert row['disposition']=='NOT_EXECUTED' and ev.get('frozenCanonicalCardPreventsNewIssuance') is True, 'G18 incorrectly reopened frozen Core'
                assert (ev.get('pathClassificationEvidence') or {}).get('path')==leg['path'], 'Saved scoring path no longer supported'
                continue
            assert row['disposition']=='PASS', 'Unstarted incumbent failed '+gate
            assert not audit_gate(gate,ev,details.get('sourceIds'),run['stage']), 'Unstarted source proof failed '+gate
            checks=ev.get('originalFunctionEvidence') or []
            assert [x.get('step') for x in checks]==STEPS_BY_GATE[gate], 'Original function missing'
            for check in checks:
                v=check.get('evidence') or {}
                assert (check.get('disposition')=='PASS' or check.get('step')=='Step13' and v.get('nonblocking') is True), 'Original function failed'
                assert v.get('independentOverlayEvaluation') is True and v.get('checkedBeforeG18') is True and v.get('masterGateVerdictCopied') is False, 'Copied original function'
        g0=json.loads(by_gate['G0']['details'])['evidence']
        assert str(g0.get('targetGoalie'))==str(leg.get('opposingGoalieId')), 'Unstarted incumbent goalie changed; source revision required'
    return {'verified':True,'date':date,'cardId':card['cardId'],'fingerprint':card['fingerprint'],
        'frozenLegs':len(frozen),'unstartedLegsRevalidated':len(legs)-len(frozen),
        'newCardIssued':False,'purpose':'FROZEN_CORE_CONTINUATION'}
