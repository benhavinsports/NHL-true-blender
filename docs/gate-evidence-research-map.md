# Original Blender gate-to-source research map

The **one** gate order is G0, G1–G10, G10.5, G11–G18. Historical Step0–Step14 functions execute within their owners (see `STEP_OWNER` in `nhl_true_blender_engine/engine.py`), never as a second gate pipeline. This file maps research requirements, not alternative selection rules. No ranking weights, arbitrary odds, or manufactured confirmation are allowed.

| Gate | Original decision / evidence to research | Active collection and validation path | Unavailable/conflicting evidence |
|---|---|---|---|
| G0 | Investigate both starting-goalie branches and choose an attack only from source-comparable weak-origin evidence, sample and counterevidence | `sources.official_slate`; `lineup_parser`, `nhl_projected_goalies`, `dated_goalie_projections`; `edge_live`, `goalie_history_fallback`; `engine.g0_full_slate` | Unmatched starter ID, conflicting branch or non-comparable goalie cohorts remain unresolved |
| G1 | Venue, both clubs' previous games/rest, travel only when observed | NHL score + `official_context`; G1/Step2 | Missing team schedule/rest remains unresolved; no inferred mileage |
| G2 | Every official roster skater, actual injury/scratch or documented availability | `sources.roster_as_evidence`, `lineup_parser`, `nhl_projected_goalies.parse_official_unavailable`; G2/Step1 | Roster alone never asserts dressed; OUT/INJURED/SCRATCHED may eliminate |
| G3 | Opposing goalie weak and strong shot-origin areas, reliable samples, counterevidence | `edge_live`, `goalie_history_fallback`, `goalie_baselines`; G3 | Unverified sample/peer group is unresolved, never anatomical weakness |
| G4 | Skater's own measured shot/goal release origin and shot mechanism | `edge_live`, `edge_derived_routes`, `historical_shots`; G4/Step5/Step7 | No verified own release is unresolved |
| G5 | Direct alignment of shooter origin with the relevant opposing goalie's weak origin, avoiding known stronger area | G4 + G3 receipts; G5/Step3/Step10 | Source-backed disjoint/strong area is elimination; absent origin is unresolved |
| G6 | Current EV assignment and sourced PP assignment/status when reported, never PP1 priority | `lineup_parser`, `enrichment`; `nhl_projected_goalies` for context; G6/Step6 | Unknown EV or contradictory deployment unresolved; absent PP is not invented |
| G7 | Repeat dated credited goals or own shots in *actual appearances* | `historical_shots`, `route_continuation`; G7/Step4 | Incomplete dates remain unresolved; verified one-off pattern may eliminate |
| G8 | Authentic optional market context, not selection odds | `enrichment`; G8 | Neutral when source absent; never a ranking shortcut |
| G9 | Independent opponent defense allowances in this same shooting origin, peer/scope and actual shift context | `official_defense_coverage`, `shift_coverage`; G9/Step8 | Missing scoped concession or shift proof unresolved; measured red area may eliminate |
| G10 | Verified own historical goal credit, not assists/facilitation | `historical_shots`, `season_goal_history`; G10 | No observed goal-credit proof unresolved |
| G10.5 | Direct scoring-lane recipient vs every meaningful teammate challenger, including TRANSFER's own direct route | `engine.challenger_proof`, `rival_scope`, dated own origins; Step10.5 | Verified stronger same-lane challenger eliminates; unclear/tied evidence unresolved |
| G11 | Repeated own-shot pressure from independently dated played appearances | `historical_shots`, `route_continuation`; G11/Step9 | Undated counts do not prove separate appearances; verified one-off eliminates |
| G12 | Official credited-goal/appearance reconciliation | `historical_shots`, `season_goal_history`; G12 | Missing source or ID reconciliation unresolved |
| G13 | Original qualitative name/date/jersey/milestone review (nonblocking) | Official NHL roster/context; G13/Step13 | Unknown optional facts retained; no invented numerology formula |
| G14 | WHO alternative direct route only with independent positive anomaly proof | `edge_live`, `engine.adjudicate_scoring_path`; G14/Step11 | No anomaly remains neutral, unsupported claimed anomaly cannot qualify |
| G15 | Independently corroborated **direct credited goal finisher**, not copied G10 or forced tonight's scorer; G5 already proves the **specific goalie-weak shot lane** | Official dated current-season own goals independently cross-checked against the **sum of all NHL EDGE owned goals across origins**, with own on-net shots separately observed in G5's target lane; alternatively direct credited goals in that exact lane | If either separate source is missing, inconsistent, or lane has no independently sourced own shots, unresolved. Never claim scored goals in the lane when zero observed; future scoring is never guaranteed |
| G16 | Review all legitimate challengers and *cross-game* competition without first-three shortcut | `engine.challenger_proof` and `g16_cross_game_finalists`; Step12 | Valid game survivor stays in pool even if G16 excludes him; unresolved comparison is not a loss |
| G17 | Goal/role/opponent strength/rival contradiction review | `contradiction_review`, `rival_scope`; G17/Step14 | Conflicting evidence remains unresolved unless source-reconciled; only previously eliminated rivals are excluded |
| G18 | Final verified Core assembly from G16-retained survivors; only final recipients PASS | `engine.execute`, `core_identity`, `scripts.publish_site_state`, `scripts.verify_published_core` | No manual Core, re-ranking, or G18 PASS for non-Core game survivors |

### Failure categories and historical evidence

Collection failures, stale or incorrect dates, impossible official-ID joins, unresolved contradictions, valid route eliminations, and G16 nonselection are **different** states. `gate_input_diagnostics`, `first_gate_audit` and published `gameSurvivorPool` retain different receipts. New output uses `preCoreQualifiedSurvivors`; archived `state/` files are immutable and may require the explicit read-only legacy-key fallback.

The supplemental daily goalie source is a projection, not NHL confirmation. Its collected values are never scoring probabilities. The collection report now distinguishes a source fetch error, unverifiable slate date, missing matchup card, starter-card parsing failure, and ambiguous official goalie ID. Transient HTTP/transport errors are retried within three requests; unsupported facts stay unresolved.

Shot-origin location on the ice is not glove/blocker/five-hole goal-mouth placement. Historical conversion or peer percentiles are not calibrated probabilities of scoring tonight. Any actual implementation audit must follow source links, observation time, and correctly scoped samples before accepting a gate PASS.
