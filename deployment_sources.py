"""Multi-source lineup/PP deployment retrieval with explicit provenance.

Source order: Hockey Insights' public lineup snapshot (which credits PuckPedia,
Daily Faceoff, and NHL.com); NHL.com projected-lineup article; Daily Faceoff
line combinations. Names are only joined to official NHL IDs after exact normalized
name matching or an official NHL search response. Missing data remains missing.
"""
from __future__ import annotations
import json, re, unicodedata
from datetime import datetime, timezone
from urllib.parse import quote
import requests
from nhl_true_blender_engine.secondary_sources import TEAM_SLUGS

TIMEOUT = 12
_HTTP_CACHE = {}
_CACHE_TTL = 600
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; NHLBlender/4.0; +https://www.nhl.com)', 'Accept':'application/json,text/html,*/*'}
HI_BASE = 'https://hockeyinsights.ca/data/lineups'
NHL_LINEUP_URL = 'https://www.nhl.com/news/nhl-lineup-projections-2026-27-season'
DFO_URL = 'https://www.dailyfaceoff.com/teams/{team}/line-combinations'


def norm_name(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+',' ',s).strip()


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def _strings(obj):
    """Yield (path, dict) pairs from arbitrary JSON source schemas."""
    def walk(x, path=''):
        if isinstance(x, dict):
            yield path, x
            for k,v in x.items(): yield from walk(v, f'{path}.{k}' if path else str(k))
        elif isinstance(x, list):
            for i,v in enumerate(x): yield from walk(v, f'{path}[{i}]')
    yield from walk(obj)


def _player_name(d):
    for key in ('fullName','name','playerName','displayName','skater','player'):
        v=d.get(key)
        if isinstance(v,str) and len(v.strip())>2: return v.strip()
        if isinstance(v,dict):
            for nk in ('default','full','name'):
                if isinstance(v.get(nk),str): return v[nk].strip()
            first=v.get('firstName'); last=v.get('lastName')
            if first and last: return f'{first} {last}'.strip()
    first=d.get('firstName'); last=d.get('lastName')
    if isinstance(first,dict): first=first.get('default')
    if isinstance(last,dict): last=last.get('default')
    if first and last: return f'{first} {last}'.strip()
    return None


def parse_lineup_json(data, team, source, retrieved_at=None):
    """Normalize common public lineup JSON shapes without guessing missing units."""
    target=team.upper(); rows=[]
    for path,d in _strings(data):
        name=_player_name(d)
        if not name: continue
        # Unit labels are kept only when explicit in source fields/path.
        raw=' '.join([path]+[str(d.get(k,'')) for k in ('line','lineNumber','lineType','unit','unitName','position','role','type','specialTeamsUnit')]).lower()
        pp=None
        for key in ('powerPlayUnit','ppUnit','powerPlayLine','powerplay_unit',
                    'specialTeamsUnit','unit','unitName','lineType','type'):
            v=d.get(key)
            # A typed PP field containing 1 or 2 is an explicit assignment,
            # not an unlabelled generic unit or an inferred PP1 preference.
            if key in ('powerPlayUnit','ppUnit','powerPlayLine','powerplay_unit'):
                if type(v) is int and v in (1,2):
                    pp=v; break
                if isinstance(v,str) and v.strip() in ('1','2'):
                    pp=int(v.strip()); break
            if isinstance(v,str) and re.search(r'\b(pp|power.?play)\s*[-#:]?\s*([12])\b',v.lower()):
                pp=int(re.search(r'([12])\b',v).group(1)); break
        if pp is None:
            m=re.search(r'(?:power.?play|\bpp)\s*[-#:]?\s*([12])\b',raw)
            if m: pp=int(m.group(1))
        line=None
        for key in ('lineNumber','line','forwardLine','lineNo','line_number'):
            v=d.get(key)
            if isinstance(v,(int,float)) and 1<=int(v)<=4: line=int(v); break
            if isinstance(v,str):
                m=re.fullmatch(r'\s*(?:line\s*)?([1-4])\s*',v.lower())
                if m: line=int(m.group(1)); break
        if line is None:
            m=re.search(r'(?:forward.?line|line)\s*[-#:]?\s*([1-4])\b',raw)
            if m: line=int(m.group(1))
        if pp is None and line is None: continue
        # Public sources may use the full NHL club name rather than the
        # three-letter abbreviation. Match canonical identity, never a loose
        # substring (e.g. a team code embedded in an unrelated word).
        explicit_team=[d.get(k) for k in ('team','teamAbbrev','teamCode',
                                          'abbrev','teamName') if d.get(k)]
        aliases={norm_name(target),norm_name(TEAM_SLUGS.get(target,''))}
        has_target_path=bool(re.search(r'(?<![a-z0-9])'+re.escape(target.lower())+
                                       r'(?![a-z0-9])',path.lower()))
        if explicit_team and not has_target_path:
            matched=any(norm_name(value) in aliases
                        for value in explicit_team if isinstance(value,str))
            if not matched: continue
        rows.append({'playerName':name,'line':line,'powerPlayUnit':pp,'source':source,'sourcePath':path,'retrievedAt':retrieved_at or datetime.now(timezone.utc).isoformat(),'sourceTeam':target})
    # Avoid duplicates by player + deployment dimension; retain separate line/PP records.
    uniq={ (norm_name(x['playerName']),x['line'],x['powerPlayUnit']):x for x in rows }
    return list(uniq.values())


def fetch_hockeyinsights(team):
    """Try the published index and then the team's club file; source is dated in payload."""
    errors=[]
    for url in (f'{HI_BASE}/index.json', f'{HI_BASE}/{team.lower()}.json', f'{HI_BASE}/{team.upper()}.json'):
        try:
            d=get(url).json()
            # Index often maps abbreviations to a path/file. Follow exact team entries.
            if 'index.json' in url and isinstance(d,dict):
                candidate=None
                for k,v in d.items():
                    if team.upper() in str(k).upper() and isinstance(v,(str,dict)):
                        candidate=v.get('url') or v.get('file') or v.get('path') if isinstance(v,dict) else v
                        if candidate: break
                if candidate:
                    target=candidate if str(candidate).startswith('http') else 'https://hockeyinsights.ca/'+str(candidate).lstrip('/')
                    try: d=get(target).json(); url=target
                    except Exception as e: errors.append(f'{target}: {e}')
            rows=parse_lineup_json(d,team,'Hockey Insights snapshot')
            if rows: return rows, {'source':'Hockey Insights snapshot','url':url,'sourceDate':_date_in(d),'errors':errors}
            errors.append(f'{url}: no explicit line/PP assignments parsed')
        except Exception as e: errors.append(f'{url}: {type(e).__name__}: {e}')
    return [], {'source':None,'errors':errors}


def _date_in(obj):
    for _,d in _strings(obj):
        for k in ('updatedAt','builtAt','generatedAt','sourceDate','date','timestamp'):
            if isinstance(d.get(k),str) and re.search(r'20\d\d-\d\d-\d\d',d[k]): return d[k]
    return None


def _nhl_article_game_day_verified(text, slate_date, team_slug, opponent_slug):
    """Certify daily NHL.com publication and exact game under the game-day header.

    The real NHL article has a *publication* date and often publishes tomorrow's
    lineup today. Authenticate the official scheduled matchup AND its heading
    weekday before mapping these line assignments to the upcoming game.
    """
    if not (slate_date and team_slug and opponent_slug):
        return False
    from datetime import date as Date, datetime as Datetime
    from bs4 import BeautifulSoup
    try:
        target=Date.fromisoformat(slate_date)
    except (TypeError, ValueError):
        return False
    source=str(text or '')
    soup=BeautifulSoup(source,'html.parser')
    full=soup.get_text(' ',strip=True) if '<' in source else source
    date_expr=(r'\b(January|February|March|April|May|June|July|August|September|'
               r'October|November|December)\s+(\d{1,2}),\s*(20\d{2})\b')
    # Pull the NHL.com byline first, not the last updated/newsroom date from a
    # recommendation widget. If no byline is available, the first visible date
    # is accepted only with independent exact day+matchup corroboration.
    byline=re.search(r'\bBy\s+NHL\.com\b',full,re.I)
    date_window=full[byline.end():byline.end()+350] if byline else full
    published=re.search(date_expr,date_window,re.I)
    if published is None:
        return False
    try:
        publication=Datetime.strptime(published.group(0),'%B %d, %Y').date()
    except ValueError:
        return False
    if not 0 <= (target-publication).days <= 2:
        return False
    nickname=lambda slug: str(slug).replace('-',' ').split()[-1].lower()
    wanted={nickname(team_slug),nickname(opponent_slug)}
    days=r'MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY'
    matchup_pattern=(r'\b([A-Z][A-Z ]+?)\s*\(\d+-\d+-\d+\)\s+'
                    r'(?:at|vs\.?)\s+([A-Z][A-Z ]+?)\s*\(\d+-\d+-\d+\)')
    target_weekday=target.strftime('%A').lower()

    # Prefer actual HTML day and matchup HEADING boundaries. This prevents a
    # headline or status paragraph from being mistaken for the game's lineup.
    headings=soup.find_all(['h2','h3']) if '<' in source else []
    most_recent_day=None
    matchup_headings=0
    for header in headings:
        heading=header.get_text(' ',strip=True)
        day_hit=re.fullmatch(r'\s*('+days+r')\s*',heading,re.I)
        if day_hit:
            most_recent_day=day_hit.group(1).lower()
            continue
        for match in re.finditer(matchup_pattern,heading,re.I):
            pair={match.group(1).split()[-1].lower(),
                  match.group(2).split()[-1].lower()}
            matchup_headings+=1
            if pair==wanted:
                return most_recent_day==target_weekday
    if matchup_headings:
        # Other games exist on the site, but not this verified day/fixture.
        return False

    # Strict fallback for plain-text fixtures: keep the original weekday,
    # opposing-club, standings-record and source-publication requirements.
    for match in re.finditer(matchup_pattern,full,re.I):
        pair={match.group(1).split()[-1].lower(),
              match.group(2).split()[-1].lower()}
        if pair!=wanted:
            continue
        near=full[:match.start()]+' '+match.group(1)
        weekdays=list(re.finditer(r'\b('+days+r')\b',near,re.I))
        if weekdays and weekdays[-1].group(1).lower()==target_weekday:
            return True
    return False


def fetch_nhl_article(team, team_name=None, slate_date=None, opponent_slug=None):
    """Read only explicitly published NHL.com forward-line units.

    Preserve HTML block boundaries: flattening the entire article before
    splitting on dashes can turn adjacent players on different lines into
    imaginary teammates. A projected unit never becomes confirmed.
    """
    try:
        from html import unescape
        html = get(NHL_LINEUP_URL).text
        body = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', ' ', html, flags=re.I|re.S)
        body = re.sub(r'<br\s*/?>|</(?:p|div|h[1-6]|li)>', '\n', body, flags=re.I)
        body = re.sub(r'<[^>]+>', ' ', body)
        body = unescape(body)
        lines = [re.sub(r'\s+', ' ', row).strip()
                 for row in body.splitlines()]
        lines = [line for line in lines if line]
        flat = ' '.join(lines)
        aliases=[]
        if team_name:
            display = team_name.replace('-', ' ').strip()
            aliases.extend([display, display.split()[-1]])
        aliases.append(team)
        heading_pattern = re.compile(
            r'\b(?:'+'|'.join(re.escape(x) for x in dict.fromkeys(aliases) if x)+
            r')\s+projected lineup\b', re.I)
        found = next((i for i,line in enumerate(lines)
                      if heading_pattern.fullmatch(line)), None)
        if found is None:
            return [], {'source':None,'errors':[f'{team_name or team} not found as a projected-lineup heading in NHL.com article']}
        rows=[]; line_no=0
        for line in lines[found+1:]:
            if re.search(r'\bprojected lineup\b|^Scratched:|^Injured:|^Status report',line,re.I):
                break
            # Explicit three-name forward units only. Defense pairs (two)
            # and goalie names (one) are not forward-line assignments.
            parts = [x.strip() for x in re.split(r'\s+(?:--|[–—])\s+', line)]
            if len(parts)!=3:
                continue
            if not all(re.fullmatch(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'\u2019-]*", x)
                       and len(x)>2 for x in parts):
                continue
            line_no+=1
            if line_no>4: break
            for name in parts:
                rows.append({'playerName':name,'line':line_no,'powerPlayUnit':None,
                             'source':'NHL.com projected lineup article',
                             'sourcePath':f'forward line {line_no}',
                             'retrievedAt':datetime.now(timezone.utc).isoformat(),
                             'sourceTeam':team.upper()})
        if not rows:
            return [], {'source':None,'errors':['NHL.com team section found but no reliable forward-line rows parsed']}
        date_ok=_nhl_article_game_day_verified(html,slate_date,team_name,opponent_slug)
        return rows, {
            'source':'NHL.com projected lineup article',
            'url':NHL_LINEUP_URL,
            'sourceDate':slate_date if date_ok else None,
            'dateVerified':bool(date_ok),
            'errors':[] if date_ok else [
                'Article publication, target weekday and exact official opponent were not jointly verified; lineup is research-only']
        }
    except Exception as e:
        return [], {'source':None,'errors':[f'NHL.com article: {type(e).__name__}: {e}']}


def fetch_dailyfaceoff(team, team_name=None):
    """Last public-web fallback. If embedded schema cannot be parsed, report that honestly."""
    slug=(team_name or team).lower().replace(' ','-')
    url=DFO_URL.format(team=quote(slug))
    try:
        html=get(url).text
        matches=re.findall(r'"(?:fullName|playerName|name)"\s*:\s*"([^"]+)"[^{}]{0,300}?(?:"(?:line|lineNumber|ppUnit|powerPlayUnit)"\s*:\s*"?([1-4])"?)',html,re.I)
        rows=[]
        for name,unit in matches:
            near=html[max(0,html.find(name)-250):html.find(name)+350].lower()
            is_pp=('pp' in near or 'powerplay' in near or 'power-play' in near)
            is_line=('line' in near and not is_pp)
            if not (is_pp or is_line): continue
            rows.append({'playerName':name,'line':int(unit) if is_line else None,'powerPlayUnit':int(unit) if is_pp else None,'source':'Daily Faceoff page','sourcePath':'embedded page data','retrievedAt':datetime.now(timezone.utc).isoformat(),'sourceTeam':team.upper()})
        return rows, {'source':'Daily Faceoff page' if rows else None,'url':url,'errors':[] if rows else ['page loaded but no reliable line/PP schema parsed']}
    except Exception as e:
        return [], {'source':None,'url':url,'errors':[f'Daily Faceoff page: {type(e).__name__}: {e}']}


def fetch_web_search(team, team_name=None):
    """Search multiple public web indexes, then inspect discovered pages.

    Search titles/snippets are discovery only. Assignments are accepted only from
    explicit structured page data and remain subject to exact official-roster ID
    joins and cross-source conflict handling downstream.
    """
    from html import unescape
    import json as _json
    from urllib.parse import unquote
    team_label = team_name or team
    query = quote(f'"{team_label}" NHL projected line combinations power play PP1 PP2')
    providers = [
        ('DuckDuckGo HTML', f'https://html.duckduckgo.com/html/?q={query}', r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'),
        ('Bing HTML', f'https://www.bing.com/search?q={query}', r'<li class="b_algo"[^>]*>.*?<h2><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>'),
    ]
    attempts=[]; rows=[]; seen=set(); discovered=[]
    for provider, search_url, pattern in providers:
        try:
            html=get(search_url).text
            matches=re.findall(pattern,html,re.I|re.S)
            provider_count=0
            for href,title_html in matches:
                url=unescape(re.sub(r'<[^>]+>','',href)).strip()
                title=unescape(re.sub(r'<[^>]+>','',title_html)).strip()
                if 'uddg=' in url:
                    m=re.search(r'[?&]uddg=([^&]+)',url)
                    if m: url=unquote(m.group(1))
                if not url.startswith('http') or url in seen: continue
                if any(host in url.lower() for host in ('duckduckgo.com','bing.com/search')): continue
                seen.add(url); discovered.append((url,title,provider)); provider_count+=1
                if len(discovered)>=12: break
            attempts.append({'provider':provider,'url':search_url,'resultLinksFound':provider_count,
                             'result':'search results parsed' if provider_count else 'no parseable result links'})
        except Exception as e:
            attempts.append({'provider':provider,'url':search_url,'result':f'search failed: {type(e).__name__}: {e}'})
        # Search the second index if the first produced no candidates, or too few
        # pages to provide meaningful fallback coverage.
        if len(discovered)>=8: break
    for url,title,provider in discovered[:12]:
        page_meta={'provider':provider,'url':url,'title':title,'parsedRows':0}
        try:
            page=get(url).text
            blobs=re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',page,re.I|re.S)
            blobs += re.findall(r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',page,re.I|re.S)
            page_rows=[]
            for blob in blobs:
                try: data=_json.loads(unescape(blob.strip()))
                except Exception: continue
                parsed=parse_lineup_json(data,team,'Web-search discovered page: '+title)
                for row in parsed: row['sourcePath']=url+' :: '+row.get('sourcePath','structured data')
                page_rows.extend(parsed)
            rows.extend(page_rows); page_meta['parsedRows']=len(page_rows)
            page_meta['result']='explicit structured assignments found' if page_rows else 'page checked; no explicit structured line/PP assignments'
        except Exception as e:
            page_meta['result']=f'page fetch/parse failed: {type(e).__name__}: {e}'
        attempts.append(page_meta)
    if not discovered:
        attempts.append({'result':'all configured search indexes returned no parseable result links'})
    return rows, {'source':'General web search' if rows else None,
                  'url':providers[0][1],'attempts':attempts,
                  'errors':[] if rows else ['Multiple web indexes searched; no explicit structured line/PP assignments found']}


def fetch_deployment(team, team_name=None, mode='projected', slate_date=None, opponent_slug=None, expected_player_names=None):
    """Search all configured web sources; never silently choose between conflicts.

    In confirmed mode, projected-only sources are still searched for context but are
    not promoted to confirmed deployment. A source must explicitly identify its
    information as confirmed/actual before the resulting row can be labelled so.
    """
    attempts=[]; collected=[]
    for fn in (fetch_hockeyinsights, fetch_nhl_article, fetch_dailyfaceoff):
        rows,meta=(fn(team) if fn is fetch_hockeyinsights else
                   fn(team,team_name,slate_date,opponent_slug) if fn is fetch_nhl_article
                   else fn(team,team_name))
        attempts.append(meta)
        collected.extend(rows)

    # Keep broadening sources for the entire official player pool, not merely
    # until ONE player's line and ONE unrelated player's PP unit have been
    # found. Finding these isolated facts previously stopped web discovery
    # while dozens of G6 identities remained unresearched.
    expected_keys={norm_name(name) for name in (expected_player_names or [])
                   if norm_name(name)}
    by_identity={}
    for row in collected:
        key=norm_name(row.get('playerName'))
        if not key:
            continue
        fields=by_identity.setdefault(key,set())
        if row.get('line') is not None:
            fields.add('line')
        if row.get('powerPlayUnit') is not None:
            fields.add('powerPlayUnit')
    missing_players=expected_keys-set(by_identity)
    partial_players=any(fields!={'line','powerPlayUnit'}
                        for fields in by_identity.values())
    dated_source=any(
        str(meta.get('sourceDate') or '')[:10]==str(slate_date)
        and meta.get('dateVerified') is not False for meta in attempts)
    # Web search is discovery ONLY. The normal dated official-ID matching
    # still controls which evidence can pass G6; no undated source is promoted.
    if (not by_identity or missing_players or partial_players or not dated_source):
        rows,meta=fetch_web_search(team,team_name)
        attempts.append(meta)
        collected.extend(rows)

    # Preserve the fetched document URL, not a parser-local JSON path or a
    # human-readable provider label. Downstream G6 requires attributable URLs.
    source_urls={}
    source_dates={}
    for attempt in attempts:
        label=attempt.get('source')
        url=attempt.get('url')
        if label and isinstance(url,str) and url.startswith('https://'):
            source_urls.setdefault(label,set()).add(url)
            source_dates[(label,url)] = {
                'sourceDate':attempt.get('sourceDate'),
                'dateVerified':attempt.get('dateVerified')}
    for row in collected:
        label=row.get('source')
        path=row.get('sourcePath')
        if isinstance(path,str) and path.startswith('https://'):
            # The sourcePath includes an internal JSON-location suffix for
            # provenance; it is NOT part of the actual retrievable URL.
            row['sourceUrl']=path.split(' :: ',1)[0]
        elif len(source_urls.get(label,set()))==1:
            row['sourceUrl']=next(iter(source_urls[label]))
        else:
            row['sourceUrl']=None

    # Aggregate by exact normalized full name. If two sources disagree about a
    # deployment dimension, keep the conflict visible and leave that dimension
    # unresolved rather than using arbitrary source order as a tie-break.
    by_player={}
    for row in collected:
        key=norm_name(row.get('playerName'))
        if not key: continue
        item=by_player.setdefault(key, {
            'playerName':row.get('playerName'), 'line':None, 'powerPlayUnit':None,
            'sources':[], 'lineEvidence':[], 'powerPlayEvidence':[], 'conflicts':[],
            'retrievedAt':row.get('retrievedAt'), 'sourceTeam':team.upper()
        })
        src=row.get('source') or 'Unknown source'
        if src not in item['sources']: item['sources'].append(src)
        for field, evidence_key in (('line','lineEvidence'),('powerPlayUnit','powerPlayEvidence')):
            value=row.get(field)
            if value is None: continue
            # Retrieval time is not the source's lineup/slate date. Preserve
            # each provider's own freshness, never another provider's date.
            freshness=source_dates.get((src,row.get('sourceUrl')), {})
            evidence={'value':value,'source':src,'sourcePath':row.get('sourcePath'),'retrievedAt':row.get('retrievedAt'),'sourceUrl':row.get('sourceUrl'),**freshness}
            if evidence not in item[evidence_key]: item[evidence_key].append(evidence)

    for item in by_player.values():
        for field,evidence_key in (('line','lineEvidence'),('powerPlayUnit','powerPlayEvidence')):
            values=sorted({e['value'] for e in item[evidence_key]})
            if len(values)==1:
                item[field]=values[0]
                item[field+'Source']=item[evidence_key][0]['source']
                item[field+'SourcePath']=item[evidence_key][0].get('sourcePath')
            elif len(values)>1:
                item['conflicts'].append({'field':field,'values':values,'evidence':item[evidence_key]})
                item[field]=None
        item['evidenceStatus']='CONFLICT — DIMENSION LEFT UNRESOLVED' if item['conflicts'] else 'CONSISTENT SOURCE EVIDENCE'

    rows=list(by_player.values())
    has_line=any(r.get('line') is not None for r in rows)
    has_pp=any(r.get('powerPlayUnit') is not None for r in rows)
    conflicts=sum(len(r.get('conflicts',[])) for r in rows)
    if mode=='confirmed':
        # None of the configured generic sources proves a confirmed in-game unit
        # merely by listing a line. Do not re-label projected information.
        for row in rows:
            row['deploymentStatus']='PROJECTED / NOT CONFIRMED'
        status='CONFIRMED DEPLOYMENT NOT ESTABLISHED — PROJECTED SOURCES SEARCHED'
    else:
        for row in rows: row['deploymentStatus']='PROJECTED'
        status=('CONFLICTS FOUND — REVIEW REQUIRED' if conflicts else
                'FOUND LINE + PP EVIDENCE' if has_line and has_pp else
                'PARTIAL — LINE + PP SOURCE SEARCH COMPLETED' if has_line or has_pp else
                'NOT FOUND — ALL SOURCES SEARCHED')
    remaining_unmapped=sorted(expected_keys-set(by_player))
    incomplete_player_names=sorted(
        item['playerName'] for item in rows
        if item.get('line') is None or item.get('powerPlayUnit') is None)
    continuing=bool(remaining_unmapped or incomplete_player_names or
                    not any(str(a.get('sourceDate') or '')[:10]==str(slate_date)
                            and a.get('dateVerified') is not False
                            for a in attempts))
    return rows, {
        'status':status,
        'remainingOfficialRosterIdentityCount':len(remaining_unmapped),
        'partiallySourcedIdentityCount':len(incomplete_player_names),
        'researchContinuationRequired':continuing,
        'allConfiguredSourcesAttempted':True,
        'selectedSource':' + '.join(dict.fromkeys(s for r in rows for s in r.get('sources',[]))) or None,
        'sourceDate':next((x.get('sourceDate') for x in attempts if x.get('sourceDate')),None),
        'attempts':attempts, 'lineEvidenceFound':has_line, 'powerPlayEvidenceFound':has_pp,
        'conflictCount':conflicts, 'modeRequested':mode,
        'confirmedDeploymentEstablished':False,
        'sourceSearchComplete':True
    }
