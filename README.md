# NHL Blender — automated full-slate analysis and audit

## Live website — GitHub Pages (authoritative)

The production site is **https://benhavinsports.github.io/NHL-true-blender/**.
It is published by `.github/workflows/deploy-pages.yml` from `site/`.
The independently scheduled Blender engine runs in GitHub Actions under
`.github/workflows/nhl-true-blender.yml`, persists its locked G18 card in
`state/site_cards/YYYY-MM-DD.json`, and saves the source-based run receipt
in `state/site_runs/YYYY-MM-DD.json`. GitHub Pages packages those results
as `site/data/latest.json`; the dashboard displays only a verified Core.
The site is free and static. It does not rely on a visitor opening ChatGPT,
a paid application server, or a separate website host to trigger analysis.
A successful GitHub workflow means code executed; it does not by itself
prove that all scorer gates passed or that a Core 3 was issued.

## Original gate execution — single pipeline

The active scorer sequence is one G0–G18 pipeline:

`G0 → G1 → G2 → G3 → G4 → G5 → G6 → G7 → G8 → G9 → G10 → G10.5 → G11 → G12 → G13 → G14 → G15 → G16 → G17 → G18`

The historical Phase-1 overlay retains **16 distinct operations**, each with
its own evaluated evidence and verdict at the owning gate. Attaching a Step
to a gate is not proof that its logic ran. Its independent observations are preserved under each
gate's `originalFunctionEvidence` field. The canonical database trace contains
one gate row per original position. The dashboard shows one gate deck and
expands these internal functions in the relevant gate detail.

G4/Step7 must identify an actual player-owned finishing action. A rink-origin
label by itself is not a shooter archetype. Official dated PBP shot types and
documented release mechanisms are retained separately from location samples.
G11/Step9 check current activity in the selected lane, not merely shots from
other locations. A lane change alone does not establish a TRANSFER recipient.
Unobserved optional Step8 shift detail stays explicitly unobserved, without
becoming a PASS or a new veto over independently evidenced G5/G9 routes.

An explicit change to `.github/nhl-live-validation.json` requests a projected
date through the existing serialized production workflow. Ordinary code
pushes still run tests only. The request contains no players or gate verdicts.

A complete recorded trace is **not** proof of scorer qualification. The
corresponding source-backed decisions must pass the actual original rules;
missing evidence cannot be silently promoted to a PASS. Existing historical
36-row archives remain intact and are not retroactively relabeled as a
newly executed G0–G18 run.

## Local development app (optional)

The legacy local app provides read-only source analysis. It cannot construct
or publish an independent Core; the integrated engine and saved canonical
state remain the sole selection and publication authority.

- **Windows:** double-click `start_windows.bat`
- **macOS/Linux:** run `./start_unix.sh`

Or start manually:
```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Scheduled/command-line run
```bash
python run_daily.py --date 2026-10-12 --mode projected --history 8
python run_daily.py --date 2026-10-12 --mode confirmed --history 8
```

## Included automated work
- Fetches the NHL schedule for the selected date and processes every eligible pregame game. Live, completed, and unknown-state games are excluded from pregame analysis and listed in the report rather than back-solved.
- Fetches landing, boxscore, and play-by-play payloads for each game.
- Retains the available complete skater pool; when the game boxscore has not populated yet, falls back to the official current team roster instead of returning an empty slate. Does not pre-filter to stars, chalk, or PP1.
- Retrieves recent completed team games and their play-by-play, then builds per-player shot/goal history and goalie shot-type / goals-against samples.
- Matches shooter player IDs to opposing goalie IDs only when the same historical event feed contains both IDs. A Main path requires a source-explicitly-marked starter plus a direct goal and shared damage lane; a listed backup cannot inherit the starter label.
- Runs and records the complete active gate sequence, exposing gate evidence, limitations, data errors, player route history, goalie shot-type/zone outcomes, exact direct matchup records, and JSON/CSV exports.
- Keeps projected and confirmed passes separate. The included GitHub Actions workflow supports daily automated JSON runs.
- Includes retry handling for transient NHL API errors and a categorical path board that compares player goal-shot types/zones with observed opposing-goalie goals allowed by shot type/zone. Each player receives an individual ordered gate trace. G10.5 exposes recorded finishers separately from recorded facilitators using event IDs; G14–G17 expose categorical path and contradiction findings without numeric weights.

## Live-data boundary

The official NHL feed remains the schedule, player identity, boxscore, and play-by-play source. If it does not contain projected lines or PP units, the app searches the additional public sources described below and records each attempt. It only attaches rows to player IDs after an exact normalized full-name join to the official roster. Projected lines never become confirmed lines merely because the user selected the Confirmed pass. Source data may be unavailable or change format; when that happens, G2/G6 remain unresolved and the source audit shows why. G6 cannot be completed from historical TOI alone, and final path certification remains withheld until comparative finisher and contradiction checks are supported.

## Evidence integrity

This is an analysis/audit workflow, not a prediction engine. It does not force a winner, invent a numeric prediction score, use odds as a shortcut, or fabricate player/evidence values. Missing data stays pending. Official line/PP assignments, injuries, confirmed starters, market data, and full environment/rest/travel context are shown only when supported by source data; otherwise they remain unresolved.

## API
Uses NHL public Web API endpoints for schedule, gamecenter landing, boxscore, play-by-play, and club-schedule-season. The NHL may change payload schemas; failures are recorded in the report. Not affiliated with the NHL.


## Line / power-play source fallback (v4)

When the official NHL game payload does not contain projected line or power-play deployment, the app now searches additional public sources instead of stopping at the roster: (1) Hockey Insights' published lineup snapshot (its source notes credit PuckPedia first, Daily Faceoff second, and same-day NHL.com third), (2) the current NHL.com projected-lineup article, then (3) Daily Faceoff's team line-combinations page. Source attempts, errors, freshness/date where available, unmatched names, and exact roster-ID join counts are saved in the run report and displayed in **Deployment source audit**.

Important distinctions: an article that only publishes even-strength lines does not establish PP1/PP2; no PP unit is inferred. Exact normalized full-name matching to the official NHL roster is required before attaching deployment to a player ID. Projected-source rows remain labelled `PROJECTED` even in a Confirmed pass; they cannot masquerade as confirmation. If all sources fail or the schema changes, the app reports that search result as unresolved rather than converting missing data to a negative finding.


## General web-search fallback (v1.5)

If the first three lineup sources do not establish both a forward-line assignment and a PP unit, the deployment layer searches DuckDuckGo and Bing for the club's projected combinations and power-play units. Search snippets are discovery only. Both search indexes are attempted when parseable coverage is limited. Candidate pages are opened and accepted only when structured page data contains explicit line/PP assignments; a headline or snippet never becomes player-level evidence. Candidate URLs and parsing outcomes are retained in the source audit. Exact normalized full-name joins to official roster IDs remain mandatory, conflicting assignments remain unresolved, and projected rows never become confirmed rows.

## Final-lock safety note

The engine deliberately does **not** certify a G18 survivor merely because a candidate has a complete gate trace. A trace records what was checked; it is not proof that the evidence passed. Current unresolved areas include current deployment/line access (G6), finisher protection (G15), final candidate competition (G16), and the structured tactical contradiction audit (G17). Until those checks are evidenced and certified, the run reports `NOT VALIDATED` and emits no official locked Core pick. Do not remove the G17 blocker or set `g18Eligible = True` as a workaround; that would create unsupported locks.


### Pre-Core survivor receipt

New engine and published-run JSON use `preCoreQualifiedSurvivors` for the complete source-backed game survivor pool, including valid game survivors excluded by cross-game G16 competition. `gameSurvivorPool` preserves each game's survivor and G16 outcome; a G16-excluded survivor is not a G18 PASS. Only final Core recipients receive G18 PASS. Immutable historical `state/` records may still contain the old field; read-only consumers accept it as a fallback, but new output never emits it.

