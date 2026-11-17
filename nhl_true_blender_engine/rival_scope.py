"""Shared meaningful-rival scope for G17 and its Step 14 overlay."""


G17_GOOD_RIVAL_STATUSES=('DEFEATED','DIFFERENT_TARGET_LANE',
                         'SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE')


def g17_resolved_without_eliminated_rivals(cdata,eliminated):
    """Re-read a stored G17 review with eliminated teammates set aside.

    Resolves only when every non-rival condition the review itself checked
    already holds and every unresolved rival row belongs to a teammate the
    gates ELIMINATED before G10.5. Nothing else is relaxed.
    """
    out={'resolved':False,'ignoredEliminatedRivals':[]}
    if not isinstance(cdata,dict) or cdata.get('unresolved') is not True:
        return out
    gs=cdata.get('goalieStrengthReview') or {}
    lr=cdata.get('lineupDisagreementReview') or {}
    rr=cdata.get('strongestRivalReview') or {}
    rows=rr.get('rivalResults')
    if not (gs.get('opposingBranchesReviewed') and gs.get('matchedWeakAreas')
            and gs.get('strongerAreaContradiction') is False
            and lr.get('hasProjectedOrConfirmedRole') is True
            and rr.get('everyRivalReviewed') is True and isinstance(rows,list)):
        return out
    open_rows=[x for x in rows if x.get('status') not in G17_GOOD_RIVAL_STATUSES]
    eliminated={str(x) for x in (eliminated or ())}
    if not open_rows or any(str(x.get('challengerId')) not in eliminated for x in open_rows):
        return out
    out['ignoredEliminatedRivals']=sorted(str(x.get('challengerId')) for x in open_rows)
    out['resolved']=True
    return out
