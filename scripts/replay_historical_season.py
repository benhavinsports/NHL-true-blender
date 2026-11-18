"""Replay archived pregame bundles, optionally grading a separate ledger."""
import argparse
import asyncio
import hashlib
import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from nhl_true_blender_engine.engine import execute, MASTER, OVERLAY
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.first_gate_audit import first_gate_audit
from nhl_true_blender_engine.gate_input_diagnostics import explain_live_blockers
from nhl_true_blender_engine.storage import open_db
from scripts.replay_postgame_grade import grade_frozen_legs


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('Evidence timestamps require a timezone')
    return result


def verified_bytes(root, path, digest):
    data = (root / path).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f'Hash mismatch: {path}')
    return data


def assert_database_as_of(con, cutoff):
    \"\"\"Reject a bundle whose persisted receipts contain post-cutoff knowledge.\"\"\"
    rows = con.execute(\"SELECT evidence_id, observed_at FROM evidence\").fetchall()
    future = []
    for row in rows:
        try:
            observed = timestamp(row['observed_at'])
        except (TypeError, ValueError, AttributeError):
            raise ValueError('Evidence database contains an invalid or timezone-free observation timestamp')
        if observed > cutoff:
            future.append(row['evidence_id'])
    if future:
        raise ValueError(f'Evidence database is contaminated by {len(future)} post-cutoff receipt(s): {future[:10]}')


def replay_day(root, day, stage, bundle):
    cutoff = timestamp(bundle['cutoff'])
    inputs = bundle['inputs']
    if not inputs or any(not row['source'] or timestamp(row['availableAt']) > cutoff
                         for row in inputs):
        raise ValueError('Missing source inventory or evidence after cutoff')
    snapshot = json.loads(verified_bytes(root, bundle['snapshot'], bundle['snapshotSha256']))
    games = snapshot['games']
    if not games:
        raise ValueError('Empty game list is not evidence of an off day')
    for game in games:
        start = game.get('startTimeUTC') or game.get('startUTC')
        state = game.get('gameState') or game.get('state')
        if not start or cutoff >= timestamp(start) or state not in ('FUT', 'PRE'):
            raise ValueError('Expected a pregame snapshot with start times after cutoff')
    evidence = verified_bytes(root, bundle['evidenceDb'], bundle['evidenceDbSha256'])
    with tempfile.TemporaryDirectory(prefix='blender-replay-') as temp:
        db = Path(temp) / 'replay.sqlite'
        db.write_bytes(evidence)
        con = open_db(str(db))
        try:
            assert_database_as_of(con, cutoff)
            result = execute(con, snapshot, day, stage, now=cutoff)
            return {'date': day, 'status': 'REPLAYED', 'cutoff': bundle['cutoff'],
                    'stage': stage, 'inputInventory': inputs,
                    'snapshotSha256': bundle['snapshotSha256'],
                    'evidenceDbSha256': bundle['evidenceDbSha256'],
                    'masterGateOrder': MASTER, 'overlayGateOrder': OVERLAY,
                    'engineResult': {k: v for k, v in result.items() if k != 'scan'},
                    'gateCertification': certify_gates(con, day, stage, result.get('games')),
                    'firstNonpassingGateAudit': first_gate_audit(con, day, stage),
                    'gateDiagnostics': explain_live_blockers(con, day, stage),
                    'historicalClockAppliedToEngineAndPersistence': True,
                    'databasePointInTimeVerified': True}
        finally:
            con.close()


async def grade_ledger(source, target):
    failures = 0
    with source.open(encoding='utf-8') as frozen, target.open('x', encoding='utf-8') as grades:
        for line in frozen:
            row = json.loads(line)
            receipt = {'date': row['date'], 'selectionStatus': row['status'],
                       'selectionRowSha256': hashlib.sha256(line.encode('utf-8')).hexdigest()}
            try:
                if row['status'] != 'REPLAYED':
                    grade = {'status': 'NOT_REPLAYED'}
                else:
                    card = row['engineResult'].get('card')
                    if not card:
                        grade = {'status': 'NO_CORE'}
                    elif row['gateCertification'].get('selectedCoreOnlyFullyCertified') is not True:
                        grade = {'status': 'CORE_NOT_CERTIFIED'}
                        failures += 1
                    else:
                        legs = card['current_legs']
                        if len(legs) not in (2, 3) or len({x['gameId'] for x in legs}) != len(legs):
                            raise ValueError('Invalid G18 card shape')
                        receipt['cardId'] = card['card_id']
                        receipt['fingerprint'] = card['fingerprint']
                        grade = await grade_frozen_legs(legs)
            except Exception as exc:
                grade = {'status': 'GRADE_UNAVAILABLE', 'errorType': type(exc).__name__,
                         'reason': str(exc)}
                failures += 1
            grades.write(json.dumps({**receipt, 'grade': grade}) + '\n')
            grades.flush()
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path, help='Pregame bundle manifest with start, end, stage and slates')
    parser.add_argument('output', type=Path, help='New frozen selection JSONL ledger')
    parser.add_argument('--grades', type=Path, help='New postgame JSONL ledger, written after selection closes')
    args = parser.parse_args()
    if args.grades and (args.grades.exists() or args.grades.resolve() == args.output.resolve()):
        parser.error('--grades must be a fresh path different from the selection ledger')
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    stage = manifest['stage']
    start, end = date.fromisoformat(manifest['start']), date.fromisoformat(manifest['end'])
    if stage not in ('PROJECTED', 'CONFIRMED') or end < start:
        parser.error('Expected PROJECTED or CONFIRMED and a valid date range')
    failures = 0
    with args.output.open('x', encoding='utf-8') as out:
        for offset in range((end - start).days + 1):
            day = (start + timedelta(days=offset)).isoformat()
            bundle = manifest['slates'].get(day)
            if bundle is None:
                row = {'date': day, 'status': 'SOURCE_BLOCKED', 'reason': 'No archived pregame bundle'}
                failures += 1
            else:
                try:
                    row = replay_day(args.manifest.parent, day, stage, bundle)
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    row = {'date': day, 'status': 'REPLAY_ERROR',
                           'errorType': type(exc).__name__, 'reason': str(exc)}
                    failures += 1
            out.write(json.dumps(row, default=str) + '\n')
            out.flush()
    if args.grades:
        failures += asyncio.run(grade_ledger(args.output, args.grades))
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
