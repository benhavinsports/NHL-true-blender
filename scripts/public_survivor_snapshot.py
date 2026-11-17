"""Choose a read-only, previously fully certified survivor cohort for display.

An incomplete NEW research run cannot silently blank the LAST verified
pre-puck game-survivor card collection. Never change gate outcomes, issue
a replacement Core, or represent projected evidence as confirmed.
"""
from datetime import datetime
from re import fullmatch


def _when(value):
    try:
        t=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return t if t.tzinfo is not None else None
    except (ValueError,TypeError):
        return None


def choose_public_survivors(status, snapshot, date):
    current=status.get('gameSurvivorPool') or []
    stage=status.get('stage')
    current_metadata={'sourceStage':stage,'origin':'CURRENT_ENGINE_RUN',
        'certifiedAtUTC':status.get('updatedUTC'),
        'currentRunFullyCertified':status.get('currentRunFullyCertified') is True}
    if status.get('currentRunFullyCertified') is True:
        return current,current_metadata
    if not isinstance(snapshot,dict):
        return current,current_metadata
    snapshot_rows=snapshot.get('gameSurvivorPool')
    count=snapshot.get('certifiedGameCount')
    valid=bool(
        snapshot.get('slateDate')==date and
        snapshot.get('stage') in ('PROJECTED','CONFIRMED') and
        snapshot.get('readOnlyDisplaySnapshot') is True and
        snapshot.get('originalFullRunSourceCertified') is True and
        snapshot.get('originalPublicationDecision')=='SOURCE_CERTIFIED_AND_PUBLISHED' and
        isinstance(snapshot.get('sourceGitCommit'),str) and
        fullmatch(r'[0-9a-f]{40}',snapshot['sourceGitCommit']) and
        isinstance(snapshot_rows,list) and
        type(count) is int and count>=2 and count==status.get('games') and
        len(snapshot_rows)==count)
    if not valid:return current,current_metadata
    source_at=_when(snapshot.get('certifiedAtUTC'))
    now=_when(status.get('updatedUTC'))
    if not source_at or not now or source_at>now:
        return current,current_metadata
    games=set();players=set()
    for row in snapshot_rows:
        if not isinstance(row,dict) or row.get('status')!='SURVIVOR':
            return current,current_metadata
        survivor=row.get('survivor')
        if not isinstance(survivor,dict):
            return current,current_metadata
        gid=str(row.get('gameId') or '')
        pid=str(survivor.get('playerId') or '')
        start=_when(row.get('gameStartUTC'))
        if not gid or not pid or not survivor.get('player') or (
            gid in games or pid in players or not start or source_at>=start):
            return current,current_metadata
        games.add(gid);players.add(pid)
    # Full original official slate coverage, no stale or wrong-game substitution.
    current_ids={str(row.get('gameId') or '') for row in current}
    if current_ids and current_ids!=games:
        return current,current_metadata
    return snapshot_rows,{
        'sourceStage':snapshot['stage'],
        'origin':'LAST_FULLY_SOURCE_CERTIFIED_PREPUCK_COHORT',
        'certifiedAtUTC':snapshot['certifiedAtUTC'],
        'sourceGitCommit':snapshot['sourceGitCommit'],
        'currentRunFullyCertified':False,
        'notAReissuedOrChangedCore':True,
        'newerResearchNotFullyCertified':True}


def persist_fully_certified_cohort(root, slate_date, stage, result, source_git_sha,
                                   run_id=None):
    """Save a real complete pre-puck survivor cohort only after G18 certification.

    No guesses, manual skater choices, or retroactive snapshot construction.
    The original run must already have selected and independently certified its
    Core. GitHub Actions stores this with the canonical source ledger.
    """
    import json
    from pathlib import Path
    from datetime import datetime, timezone
    if not (isinstance(source_git_sha,str) and
            fullmatch(r'[0-9a-f]{40}',source_git_sha) and
            stage in ('PROJECTED','CONFIRMED') and
            result.get('gateCertification',{}).get('selectedCoreOnlyFullyCertified') is True
            and result.get('card')):
        return False
    games=result.get('gameSurvivorPool') or []
    expected=result.get('games')
    if not (type(expected) is int and expected>=2 and
            len(games)==expected and
            all(g.get('status')=='SURVIVOR' and isinstance(g.get('survivor'),dict)
                for g in games)):
        return False
    observed=datetime.now(timezone.utc)
    gids=set();pids=set()
    for g in games:
        gid=str(g.get('gameId') or '')
        pid=str(g['survivor'].get('playerId') or '')
        start=_when(g.get('gameStartUTC'))
        if (not gid or not pid or not start or observed>=start or
                gid in gids or pid in pids):
            return False
        gids.add(gid);pids.add(pid)
    snapshot={
        'slateDate':slate_date,'stage':stage,
        'certifiedAtUTC':observed.isoformat(timespec='seconds'),
        'sourceGitCommit':source_git_sha,
        'sourceWorkflowRunId':str(run_id) if run_id else None,
        'originalPublicationDecision':'SOURCE_CERTIFIED_AND_PUBLISHED',
        'originalFullRunSourceCertified':True,
        'originalSourceGateCheckEveryGame':True,
        'readOnlyDisplaySnapshot':True,
        'certifiedGameCount':expected,
        'gameSurvivorPool':games}
    dst=Path(root)/'survivor_cohorts'/(slate_date+'.json')
    dst.parent.mkdir(parents=True,exist_ok=True)
    temp=dst.with_suffix('.tmp')
    temp.write_text(json.dumps(snapshot,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    temp.replace(dst)
    return True
