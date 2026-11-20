# NHL True Blender — November 20 system repair and calibration

## Acceptance status

**Not fully certified.** Software repairs and passing regression checks do not establish correct scorer selection. November 20 is an official NHL off-day; no new live pregame-to-final cycle can be demonstrated on that date.

## Repairs completed

1. **Dated evidence attachment:** preserve detailed official appearance and shot-origin observations when a later summary describes the same games, sources and counts but omits detail. Different counts, windows or sources retain normal revision handling. Completeness and gate dispositions are never manufactured. The November 17 frozen-bundle reproduction retained dated origin inventories for 364 players instead of 10, restoring 354 inventories.
   - Merged repair: https://github.com/benhavinsports/NHL-true-blender/pull/59
2. **One canonical archive:** historical research now restores the canonical ledger and engine from one pinned main commit. It no longer restores the historical branch's older standalone gzip while evaluating with a newer main engine. Immutable engine contents are compared directly against their extracted archive; later main commits do not invalidate a correctly pinned run.
   - Historical workflow: commit 7be783c5d47196cee3e22385364e9ec8518c6038; file-verification correction 0d2f167a1c5ac05c1351428c68807ab2acc753c4.
3. **Original postgame audit:** MIXED is a card evidence status, not a gate execution phase. Audits now recover the actual research phase and each frozen leg's own matching pre-puck card version. They read independently recorded original functions embedded inside their owning gates. They do not invent extra executed gates or copy a master PASS into a function.
   - Repair: https://github.com/benhavinsports/NHL-true-blender/commit/575eb4deb4a93fd54dd354b2cadf6abd562ac22e
   - November 19 reproduction recovered 20 master records plus 16 independently recorded functions for each selected player. Retrying grading preserved recipients, fingerprint, revision and official grade exactly.
4. **Complete regression execution:** fixed the root collector fixture's obsolete call signature and corrected-source second-run expectation; enabled unambiguous test imports. Main CI now executes the complete repository suite and includes root collector/test changes in its triggers.
   - CI expansion: c6315af143d4daba03d56373bfe1b2eb19aabc54.

## Verified checks

- Latest main verification: https://github.com/benhavinsports/NHL-true-blender/actions/runs/44813693116 — success. JUnit records 507 cases, zero failures, zero errors and zero skips; this includes 502 tests and five subtests.
- Frontend card verification: 27 tests passed locally; JavaScript syntax checks passed.
- Scheduled off-day execution: https://github.com/benhavinsports/NHL-true-blender/actions/runs/44813863994 — success. The November 20 receipt says NO_ORIGINAL_CORE_TO_GRADE; this is not a newly certified Core.
- The completed historical run at https://github.com/benhavinsports/NHL-true-blender/actions/runs/44810685203 no longer crashed on the legacy challenger_proof opponent_coverage mismatch. That compatibility repair preceded this turn. Its actual audit still reported zero fully completed slates and zero certified/graded replay cards across 50 scheduled slates. It recorded 117 G0 blocker messages and 24 G2 blocker messages; these are message counts, not distinct slate counts. All 50 slates retained provider availability limitations.
- Baseline comparison in that completed run recorded 49 identical-input rows. Different first-issuance windows must not be represented as identical frozen inputs.

## Historical execution still requiring acceptance

The first canonical-archive rerun collected and built its season bundles but stopped at a Git-index-dependent file verification check introduced during this repair. That check was corrected to compare actual extracted files. No scorer gates were bypassed.

The resumed frozen-input run completed at https://github.com/benhavinsports/NHL-true-blender/actions/runs/44816177284 . It verified the exact collector/scorer commit 575eb4deb4a93fd54dd354b2cadf6abd562ac22e, passed 502 tests plus five subtests, replayed all 50 scheduled slates, ran the baseline and official scorer research, and published its audits. Its actual summary is **0 fully completed slates, 0 graded leg opportunities, 0 goal hits**. The final certification step correctly failed; there was no replay software crash. Baseline comparison recorded 49 identical-input rows, one changed Core date and 44 changed G0 dates. These figures do not establish improved prediction quality. The recovery workflow is committed on repair/historical-replay-resume and does not write production selections.

A fresh full source-collection run also continues at https://github.com/benhavinsports/NHL-true-blender/actions/runs/44815935845 .

## Remaining limits

- No completed repaired full-season certification or improved scorer hit rate has been established.
- Missing/ambiguous G0, roster, deployment and recipient-separation evidence must remain unresolved; no weights, goal-total fallback, forced path labels or manual scorer substitutions were added.
- A real upcoming projected → confirmed research → authoritative saved card → individual puck-drop freeze → official-final grade cycle remains to be demonstrated with the repaired engine. Synthetic lifecycle tests and an idempotent prior-card grading retry are narrower evidence.
- The recovered operational master was checked. It explicitly identifies itself as a reconstruction, not the independently recovered verbatim original manuscript. No separate complete original 17-situation list was recovered from the retrieved thread context.

## Corrected production audits saved

The backfill at https://github.com/benhavinsports/NHL-true-blender/actions/runs/44817656138 completed successfully. It reran the complete test suite, restored the verified canonical ledger, rebuilt all four already-graded cards' miss audits, and compared every original card field and official grade before persistence. All four original cards and grades remained identical. The full lossless ledger and corrected audit exports were committed to main.

Receipt: https://github.com/benhavinsports/NHL-true-blender/blob/main/state/history/offday-audit-backfill-2026-11-20.json

The November 16, 17 and 19 misses now each recover their 20 master records plus 16 independently recorded original-function checks. November 15's Morgan Frost and Evan Bouchard still have zero recoverable original pre-lock receipts. Their missing original evidence remains explicitly unresolved; it was not recreated after the result. Every missed selection remains marked PREGAME_GATE_REPLAY_REQUIRED, not a proven source-caused error or an automatically patched winner.
