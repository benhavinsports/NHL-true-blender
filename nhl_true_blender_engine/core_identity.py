"""Expected Core identity from a saved run receipt.

The published Core must equal the per-game survivors that the saved G16
cross-game finalist competition retained. When no G16 receipt exists (the
survivor count already equaled the Core size), it must equal every survivor.
This module never selects players; it only reads what the engine saved.
"""


def _ids(rows, key='playerId'):
    return [(str(x.get('gameId')), str(x.get(key))) for x in rows
            if isinstance(x, dict)]


def pre_core_survivors(run):
    """Read a saved pre-Core pool; archived runs use the legacy key.

    The new field takes priority if both exist. This read-only fallback
    never adds the old key to new engine or publication output.
    """
    if 'preCoreQualifiedSurvivors' in run:
        return run['preCoreQualifiedSurvivors']
    return run.get('allG18QualifiedSurvivors')


def expected_core_ids(run):
    """Return the list of (gameId, playerId) G18 was authorized to assemble,
    or None when the receipt is malformed/inconsistent."""
    survivors = pre_core_survivors(run)
    if not isinstance(survivors, list):
        return None
    survivor_ids = _ids(survivors)
    g16 = run.get('g16FinalistCompetition')
    if not g16:
        return survivor_ids
    finalists = g16.get('finalists') or []
    finalist_ids = _ids(finalists)
    # The G16 receipt must cover exactly the same survivors, once each.
    if (len(finalist_ids) != len(survivor_ids) or
            set(finalist_ids) != set(survivor_ids) or
            len(set(finalist_ids)) != len(finalist_ids)):
        return None
    if g16.get('separated') is not True:
        return None
    retained = [(str(x['gameId']), str(x['playerId'])) for x in finalists
                if x.get('g16Decision', '').startswith('RETAINED')]
    if [pid for _, pid in retained] != [str(x) for x in g16.get('retainedPlayerIds', [])]:
        return None
    for row in finalists:
        if row.get('g16Decision') == 'EXCLUDED_STRICTLY_DOMINATED_BY_A_FULL_CORE':
            if len(row.get('dominatedBy') or []) < int(g16.get('requiredCoreSize') or 99):
                return None
    return retained
