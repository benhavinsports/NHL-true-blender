"""Player-owned shot mechanisms from dated events, distinct from rink origin.

No shot type is inferred from a coordinate, goal count, position or reputation.
PBP shot types describe the action; they do not prove rebound/setup dependence,
shot quality or where the puck entered the net.
"""
from __future__ import annotations
from datetime import date
from urllib.parse import urlsplit
from .official_defense_coverage import conservative_zone, detailed_shot_origin_zone

SOURCE_TYPE='OFFICIAL_NHL_DATED_PBP_SHOT_MECHANISM'
ORIGIN_TAGS={'OBSERVED_OWN_SHOT_ORIGIN','UNKNOWN','UNVERIFIED',''}

def mechanism_events(events, player_id, slate_date):
    """Retain the actual actor, action, game, clock and attributed source."""
    rows=[]; seen=set()
    cutoff=date.fromisoformat(slate_date)
    for event in events:
        if str(event.get('shooterId'))!=str(player_id):
            continue
        if event.get('type') not in ('goal','shot-on-goal','missed-shot','blocked-shot'):
            continue
        try:
            played=date.fromisoformat(str(event.get('date')))
        except ValueError:
            continue
        if played>=cutoff:
            continue
        shot=event.get('shotType')
        url=event.get('sourceUrl')
        if (not isinstance(shot,str) or not shot.strip() or
                shot.lower() in ('unknown','other') or not isinstance(url,str)):
            continue
        parsed=urlsplit(url)
        gid=str(event.get('gameId') or '')
        eid=str(event.get('eventId') or '')
        if (parsed.scheme!='https' or parsed.netloc!='api-web.nhle.com' or
                parsed.path!=f'/v1/gamecenter/{gid}/play-by-play' or
                not gid or not eid or eid=='None'):
            continue
        key=(gid,eid)
        if key in seen:
            continue
        seen.add(key)
        zones=sorted(set(filter(None,(
            conservative_zone(event.get('x'),event.get('y')),
            detailed_shot_origin_zone(event.get('x'),event.get('y'))))))
        rows.append({
            'playerId':str(player_id),'gameId':gid,'eventId':eid,
            'date':played.isoformat(),'type':event['type'],'shotType':shot,
            'x':event.get('x'),'y':event.get('y'),'originZones':zones,
            'period':event.get('period'),'timeInPeriod':event.get('timeInPeriod'),
            'situationCode':event.get('situationCode'),
            'goalieId':event.get('goalieId'),'sourceUrl':url,
        })
    return rows

def shooter_mechanism(player, release, slate_date=None):
    """Review the selected own lane without renaming its origin as archetype."""
    release=release or {}
    wrapper=player.get('shotMechanism') or {}
    data=wrapper.get('data') or {}
    rows=[]
    if (data.get('sourceType')==SOURCE_TYPE and
            str(data.get('playerId'))==str(player.get('id')) and
            wrapper.get('observedAt') and wrapper.get('sourceUrl') and
            (slate_date is None or data.get('slateDate')==slate_date)):
        # Revalidate the observations, including the strict pre-slate date and
        # actor/source IDs. A summary count or copied archetype is insufficient.
        events=[{**e,'shooterId':e.get('playerId')} for e in data.get('events',[])
                if isinstance(e,dict)]
        try:
            checked=mechanism_events(events,player.get('id'),data['slateDate'])
        except (KeyError,ValueError):
            checked=[]
        rows=[e for e in checked if release.get('zone') in e['originZones']]
    types=sorted({e['shotType'] for e in rows})
    raw=player.get('release') or {}
    archetype=(raw.get('data') or {}).get('archetype')
    # Existing independently sourced scouting may explicitly describe a
    # finishing action. The known location-only adapter is never that proof.
    explicit=(isinstance(archetype,str) and archetype.upper() not in ORIGIN_TAGS
              and any(word in archetype.lower() for word in
                  ('wrist','snap','slap','tip','deflect','backhand','wrap',
                   'rebound','poke','batting')))
    explicit=bool(explicit and raw.get('sourceUrl') and raw.get('observedAt'))
    supported=bool(types or explicit)
    return {
        'supported':supported,
        'archetype':('observed '+', '.join(types)+' release') if types else
                    archetype if explicit else None,
        'observedShotTypes':types,'selectedOrigin':release.get('zone'),
        'ownMechanismEvents':rows,
        'sourceIds':sorted({e['sourceUrl'] for e in rows} |
                           ({raw['sourceUrl']} if explicit else set())),
        'sourceObservedAt':wrapper.get('observedAt') if rows else raw.get('observedAt'),
        'originOnlyIsNotArchetype':not supported,
        'setupDependenceNotInferred':True,
        'reboundOrShotQualityNotInferred':True,
        'goalMouthPlacementNotInferred':True,
    }
