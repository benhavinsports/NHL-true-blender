# Complete master prompt comparison and implemented repair

Authority: the user's supplied **NHL TRUE BLENDER — COMPLETE MASTER EXECUTION,
DATA SOURCE AND APPLICATION REPAIR PROMPT**, compared with the saved
`NHL_Blender_Phase1_Restored_Master.md` and repository main
`9bb229160880e517cb4a545b8278703ef96db047`.

The canonical `NHL_Blender_Automated_Run_State.json` version 46 was also read
directly. Its SHA-256 is
`e2ba48dd46607d3be052af1ef5214c38c45433a56cd7737bee0ccc1a642d8238`.
Its `cross_chat_calibration.scope` explicitly forbids new gates, weights,
thresholds, formulas and name preferences. Its Nov12 overlay explicitly calls
Step7 archetype tagging and treats absent Step8 shift detail as uncertainty.

This is a comparison of actual code, not a declaration that a live Core was
issued. The supplied complete prompt takes precedence over older repair
summaries. Historical replay is a separate point-in-time verification path;
it is not tonight's scoring authority or a prerequisite for running the live
collector and original scorer pipeline.

## Material differences repaired

| Requirement | Observed implementation before repair | Implemented behavior |
|---|---|---|
| G4 / Step5 / Step7: actual shooter mechanism and archetype | The EDGE adapter's `OBSERVED_OWN_SHOT_ORIGIN` could satisfy the archetype check. It identifies an area, not a release action. | The live historical PBP collector stores player-owned, dated shot types with event/game/player/goalie IDs, coordinates, strength situation, clock and source. G4 and independent Steps5/7 review a documented action in the selected origin. Origin-only evidence remains unresolved. No rebound, xG, setup independence or goal-mouth location is inferred from coordinates. |
| G11 / Step9: current activity in the scoring route | Repeated overall individual shots could pass with no current shot in the selected lane. | G11 and Step9 independently inspect the reconciled dated own-lane sample. Verified zero activity is distinguished from incomplete or stale collection. Shots in other areas cannot substitute. |
| Optional historical shift detail | Step8 marked absent shift evidence nonblocking; final engine, census, export and publication checks nevertheless rejected it. | The same narrowly scoped optional-review rule is applied throughout selection, saving and publication. The Step8 operation and missing observation remain visible as `NOT_EXECUTED`; they are never rewritten to PASS. An elimination, copied verdict or missing required archetype cannot use this exemption. G5/G9 physical evidence remains mandatory. |
| TRANSFER classification | A change away from the player's usual origin could establish TRANSFER without a displaced competing recipient. | Lane adaptation alone does not establish recipient transfer. A verified direct recipient remains PRIMARY unless the actual separation supports TRANSFER or WHO. Defeated competing-recipient evidence is still retained and required for a transfer. This aligns the current supplied definition rather than the older Nov17 lane-change labeling rule. |
| G1 / Step2 schedule and travel research | Only last date, rest count and home designation were retained; actual venue and the recent venue sequence were dropped. | Official venue, game time, previous start, recent completed-game sequence, back-to-back status and scheduled venue transition are preserved in G1 and Step2. A scheduled transition is not called an observed flight, distance, travel duration or fatigue. |
| Source-failure recovery | A source-incomplete candidate could cause every unrelated game's collectors to run again. | Retry collection is scoped to still-incomplete pregame games. Valid evidence from unaffected games is retained. Actual original-gate eliminations are not reopened. The full original selection still executes against the refreshed whole slate; a shared league comparison cohort is still collected where needed. |
| Upcoming-slate official statistics | `collect_edge` and `collect_season_goal_history` rejected every date other than today, so tomorrow's live pregame collection was incorrectly classified as historical. | Past slates still reject current statistics. An upcoming slate can use currently observed, source-timestamped statistics. EDGE additionally prevents mixing the current season with an unobserved future season. Target-day results remain excluded from dated goal history. |
| Live validation dispatch | Ordinary code pushes intentionally run tests only; the current connector does not expose workflow dispatch. | An explicit date/phase-only `.github/nhl-live-validation.json` change triggers the existing serialized production workflow. There is no new selector, parallel Core writer, player input or gate override. Ordinary code pushes keep their existing behavior. |

## Master gate coverage

Every entry below refers to an actual code path. Presence is not certification
that every current source is complete or that each decision implements every
qualitative requirement in the supplied prompt.

| Gate | Existing operation and comparison finding |
|---|---|
| G0 | Full schedule, both goalie directions, retained projected branches and branch-specific research. Same-origin, different-origin and shared-cohort comparators are implemented. Quantitative-method fidelity remains a review item below. |
| G1 | Sourced venue/rest check; this repair adds actual schedule/venue sequence and timing. No invented travel measurement. |
| G2 | Official roster pool includes depth and D; unavailable statuses are distinguished from an omitted lineup name. Roster membership is not dressed confirmation. |
| G3 | Goalie-specific origin sample and counterevidence. Rink origin is explicitly distinguished from anatomical net placement. |
| G4 | Own release and mechanism; repaired to reject a location-only archetype. |
| G5 | Selected own origin versus opposing goalie weakness, with exact scope limitations. Mechanism observations are carried from G4 rather than fabricated from rink location. |
| G6 | Sourced EV and available PP/PK assignments with projected/confirmed labels. Missing PP data is not invented. All-provider current availability must be checked by the live run. |
| G7 | Dated real appearances, reconciled goals and shot recurrence; no missed-game zero filling. |
| G8 | Optional authentic market context; absent market data stays neutral. |
| G9 | Independently collected opponent shot-origin allowances and shift joins; GREEN opportunity / RED resistance. Its hardcoded analytical floors still require original-rule provenance review. |
| G10 | Direct historical scorer-credit review separate from creator/assist roles. It does not guarantee tonight's event. |
| G10.5 | Every meaningful rival is compared against jointly viable goalie/defense lanes. Dated same-lane samples and opponent-specific comparisons replace season-total fallback. Full tactical mechanism/dependence coverage is not certified merely because rows exist. |
| G11 | Repeated dated individual pressure, now also grounded in the selected current lane. |
| G12 | Official goal-credit reconciliation. |
| G13 | Qualitative name/date/jersey/birth/milestone review; no formula prerequisite. |
| G14 | WHO route requires positive physical anomaly evidence; no forced quota. |
| G15 | Separate source corroboration of own finishing credit and shot origin. Goal credit by itself does not prove every aspect of setup dependence or shot quality. |
| G16 | Complete same-game challenger and cross-game finalist comparison. No first-three truncation. Original provenance of the quantitative comparator remains to be established. |
| G17 | Structured goalie, deployment, rival and source-conflict review, including exclusion of genuinely eliminated rivals. |
| G18 | Final construction from upstream survivors; one canonical saved card, no label quota, no alternate dashboard selector. |

## Independent overlay operations

The 16 operations may be stored under their master-gate owners. Each must
still compute its own evidence and verdict. Nesting is a storage arrangement,
not permission to omit an operation or copy its master verdict. There is no
overlay Step15.

| Overlay | Current owner | Evaluated operation |
|---|---|---|
| Step0 | G0 | Target side and goalie branch evidence |
| Step1 | G2 | Actual dated roster membership and availability review |
| Step2 | G1 | Venue/rest and sourced schedule/venue transition review |
| Step3 | G5 | Own shooting origin versus goalie vulnerability and defense resistance |
| Step4 | G7 | Independent dated goal/shot recurrence observation |
| Step5 | G4 | Own documented mechanism; unsupported shot-quality precision is not invented |
| Step6 | G6 | EV and sourced special-team role/status review |
| Step7 | G4 | Actual archetype/action tagging before final selection, repaired here |
| Step8 | G9 | Historical defensive shift coverage review; missing detail retained honestly |
| Step9 | G11 | Current own pressure in the selected lane, repaired here |
| Step10 | G5 | Goalie mechanism/route recheck with source scope retained |
| Step10.5 | G10.5 | Separate adjacent/competing recipient comparison |
| Step11 | G14 | Sourced blue-line/WHO mechanisms or neutral absence |
| Step12 | G16 | All meaningful remaining rival comparisons |
| Step13 | G13 | Qualitative numerical/milestone review, nonblocking |
| Step14 | G17 | Final rival/goalie/lineup separation and contradictions |

## Remaining fidelity and live-evidence limits

These are not relabeled as completed repairs:

1. **Quantitative rule provenance:** `edge_derived_routes.py` uses a 20-shot
   floor and .35 peer-percentile boundary; `goalie_history_fallback.py` repeats
   these and requires four peers. `official_defense_coverage.py` uses 120/16/12
   shot floors and six-game/six-peer conditions. The supplied prompt does not
   authorize these exact constants. Calling them conservative does not prove
   original-rule fidelity. Removing them or substituting other numbers without
   recovering the original vulnerability decision would also invent logic.
2. **Mechanism versus full tactical proof:** collecting a wrist/tip/etc. event
   fixes the missing archetype operation. It does not by itself establish shot
   quality, rebound causality, passing dependence, coverage shifts, strength-
   specific exposure or anatomical goalie weakness. G5/G9/G10.5/G15/G17 must
   retain the limits of the actual evidence. Existing comparison rows are not
   proof that every required tactical dimension was measured.
3. **Cross-game selection provenance:** the current G16 exposure/peer-method
   comparison must be reconciled with the original complete survivor decision;
   moving a numeric preference from G18 into G16 would not make it original.
4. **Live source success:** named collectors and optional research candidates
   are not declared operational solely from imports or successful page fetches.
   The real requested slate must record usable dates, exact IDs, provider scope
   and conflicts. Missing sources are not gate eliminations.
5. **Website acceptance:** the current public UI tests deliberately keep grade
   and audit panels out of the public deck. The supplied prompt additionally
   requests accessible official historical results and source/overlay details.
   Existing stored grades do not prove all those views are available on the
   deployed site. This repair does not claim a complete UI acceptance pass.
6. **Future phases:** a projected run cannot demonstrate a later real goalie
   confirmation, actual puck-drop freeze or official postgame grade in advance.
   Those must be verified against the same canonical card when they occur.

Past cards and grades are preserved. The past-card reader can retain an older
frozen contract; it is not permitted to certify a new live origin-only
archetype. No historical card is replaced with a retrospectively preferred
player because of these changes.

The production verification and live run links, source receipts, exact failure
paths and any actual saved Core are the completion evidence. A passing test
suite alone is not that completion evidence.

## First real upcoming-slate execution

Repair commit: `00ceb83ce009a328f174e447862ab1da3fd3d2e6`.
GitHub verification run `44853261360` passed 519 Python tests; frontend tests
also passed. Deployment run `44853261398` succeeded.

Production execution `44853261426` processed the Nov21 projected slate:
14 games, 28 goalie directions, 27 complete goalie profiles, 387 official
skaters surveyed and 7,788 recorded gate rows including branch research.
It saved **no Core** and correctly failed final issuance certification.
The dated main lineup feed did not establish Nov21 deployment. The actual
source report identified the EDGE historical-date guard above, which prevented
every skater release from being populated. That live failure directly motivated
the follow-up guard correction; source access was not falsely blamed.

The saved diagnostics are `state/site_runs/2026-11-21.json`. Their row counts
are execution coverage, not source-backed gate passes. No candidate names in
those diagnostics are promoted to manual picks. The follow-up uses request ID
`master-repair-future-slate-source-guard-2` through the same canonical writer.
