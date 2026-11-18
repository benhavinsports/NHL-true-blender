"""Replay archived pregame bundles without live collectors or site publication.

Run with python -m scripts.replay_historical_season MANIFEST OUTPUT.
Manifest: start, end (ISO dates), stage (PROJECTED or CONFIRMED), and
slates keyed by date. Each slate supplies cutoff, snapshot and evidenceDb
(relative paths), snapshotSha256, evidenceDbSha256, and inputs: an inventory
of all bundled evidence, with source and availableAt for each entry.
The bundle producer must attest completeness; timestamps do not establish
that a source or database is historically accurate by themselves.
"""
import argparse
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
            result = execute(con, snapshot, day, stage)
            certification = certify_gates(con, day, stage, result.get('games'))
            diagnostics = explain_live_blockers(con, day, stage)
            return {'date': day, 'status': 'REPLAYED', 'cutoff': bundle['cutoff'],
                    'stage': stage, 'inputInventory': inputs,
                    'snapshotSha256': bundle['snapshotSha256'],
                    'evidenceDbSha256': bundle['evidenceDbSha256'],
                    'masterGateOrder': MASTER, 'overlayGateOrder': OVERLAY,
                    'engineResult': {k: v for k, v in result.items() if k != 'scan'},
                    'gateCertification': certification,
                    'firstNonpassingGateAudit': first_gate_audit(con, day, stage),
                    'gateDiagnostics': diagnostics}
        finally:
            con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path, help='New JSON Lines ledger; existing files are never overwritten')
    args = parser.parse_args()
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
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
