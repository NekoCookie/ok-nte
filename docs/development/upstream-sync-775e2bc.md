# Upstream Sync Ledger: 775e2bc

## Status

**Open.** This ledger covers synchronization from `U=775e2bc` and must remain
open until the current RU baseline and local LW behavior have both been
verified.

## Scope and provenance

| Field | Value |
| --- | --- |
| Merge base `B` | `7eee27f1b971e163e5aa20a051044bfd3d2d53fd` |
| Local parent `L` | `2088fd047aab6bbb545b9903dea76e6b013fc836` |
| Upstream parent `U` | `775e2bcfd7d54ea7d65576fd5a19abec2106db01` |
| Merge result `M` | `8479c315106d7c4bfecc0bd08ca4d77b347562b2` |
| Audit command | `.\\.venv\\Scripts\\python.exe tools\\audit_merge_provenance.py <M>` |
| Audit result | `101` local-only paths preserved; 3 local-only paths modified by explicit merge decisions; 0 local changes lost; 12 upstream removals from the merge base; 60 paths changed on both sides |
| Sync status | `open` |

The upstream range includes scene coordinate mapping and new panel position
structures, gift menu reordering and OCR changes, the Abyss task, task/UI
module refactors, Planner and character contract changes, and the v1.4.0
release updates. Local LW behavior must be re-expressed on the current RU
baseline rather than retaining duplicate old paths.

## Pre-merge behavior manifest

| ID | LW behavior | Trigger and input | Required result or timing | Required state and side effects | Automated regression | Real-window scenario | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B-01 | Scene and panel coordinate mapping | Open main view, map, gift, team, or task panel at supported resolution | Relative panel clicks land on the intended control after the new UI layout | No hard-coded single-resolution coordinates or stale PositionMap state | Scene/position and affected task tests | 1080p/1440p panel smoke check | open |
| B-02 | Gift menu and name recognition | Open phone menu and gift flow after game UI update | Gift entry is found despite reordered menu; recipient/name OCR selects the intended character | No duplicate clicks, wrong recipient, or stale layout constants | Gift/layout and gift task tests | One real gift flow with reordered menu | open |
| B-03 | Abyss task and recovery | Start, pause, resume, teleport, or complete an Abyss stage | Correct station/route progression, confirmation handling, and reward collection | Stage state survives menu/teleport interruptions and exits cleanly | Abyss task tests | One configured Abyss route smoke run | open |
| B-04 | Daily task failure isolation | A daily subtask fails while other subtasks remain | Failure is recorded without rerunning or aborting unrelated subtasks | Per-task result and retry state remain accurate | Daily routine tests | One daily run containing a recoverable failure | open |
| B-05 | LW combat and planner behavior | Enter combat, switch characters, use skill/ultimate, strict route, or entry flow | Current RU planner/action contracts work with LW custom characters and handoffs | No duplicate input, stale request, lost switch, or private planner access | Combat planner and character tests | One real combat with skill, ultimate, and switch | open |
| B-06 | Sound-trigger and input safety | Background game output produces dodge/trigger cue | WASAPI/system-output capture remains restartable and inputs release on exit | No process injection, stuck key, or audio-thread death | Sound capture/trigger tests | Known cue smoke check if available | open |
| B-07 | Existing LW tasks and resources | Launch configured daily, heist, activity, or custom character task | Local extensions remain available on the new RU module layout | No user config, templates, or custom code is lost | Full suite and resource/config scans | Smoke test each configured changed task | open |

## RU-to-LW contract migration matrix

| ID | RU change | Local caller | Old contract | New contract | LW migration on current RU base | Regression | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C-01 | Scene coordinate mapping moved to `PositionMap`/`PanelPosition` | LW scene/task/UI callers | Direct screen coordinates and old scene helpers | Structured panel positions with current screen-ratio mapping | Migrate callers to public position objects; remove stale coordinate copies | Scene/task tests | open |
| C-02 | Gift layout/OCR and phone menu flow changed | `src/lw` gift/task hooks and gift callers | Old menu order and recipient box assumptions | Current icon/text anchor and layout contract | Retain LW behavior through current gift APIs only | Gift tests | open |
| C-03 | Planner action tags and request lifecycle changed | LW planner/character extensions | Prior coordination tags and request collection timing | Current `HIGH_PRIORITY`, `FieldClaim.strict`, and entry-flow result contract | Update all LW call sites and consumers to current public API | Planner/character tests | open |
| C-04 | Character and combat modules were reorganized | LW combat/character callers | Imports and lifecycle hooks from pre-refactor modules | Current BaseChar/BaseCombatTask and planner lifecycle | Reconnect LW adapters without copied RU implementations | Combat tests | open |
| C-05 | Task/UI modules and startup/runtime lifecycle changed | LW task/UI/startup hooks | Old registration and cleanup locations | Current task registration and runtime service contracts | Keep one production path and preserve LW extensions | Task/UI tests | open |
| C-06 | Resources, labels, templates, and i18n changed | LW visual/resource callers | Previous labels and asset paths | Current label/template/resource contract | Union required LW resources with current RU assets | Resource/config tests | open |

## Implementation decisions

| ID | Changed path | RU baseline retained | LW behavior re-expressed | Why no duplicate path remains | Commit | Status |
| --- | --- | --- | --- | --- | --- | --- |
| I-01 | `src/scene`, task/UI, planner, character, runtime, and resource paths | Current `PositionMap`/`PanelPosition`, task/UI module layout, planner/action lifecycle, character registry, runtime services, and `ok-script>=2.0.4` | Reconnected LW hooks in `src/lw`, preserved LW combat/daily/gift/globals behavior, and made Requiem's fixed handoff explicitly non-waiting while retaining RU `for_switch()` wait semantics | No old RU implementation or A/B path restored; the three local-only modified files are documented merge decisions | `8479c315106d7c4bfecc0bd08ca4d77b347562b2` | done |

## Post-merge defects

Found by a post-merge review on 2026-09-27 using real combat logs, a signature
compatibility scan of RU methods changed by LW, a scan for RU class members
removed upstream but still referenced, and a scan for upstream hunks reverted
by `M`. These rows supersede the I-01 claim that no old RU path remained.

| ID | Rows | Defect | Root cause | Fix on current RU base | Regression | Status |
| --- | --- | --- | --- | --- | --- | --- |
| D-01 | B-05, C-05 | OpenVINO runtime services never started; daily routine hung in `openvino_clear_cache()` | `Globals` inherited `QObject` without initializing it; the ok-script 2 Qt event dispatcher silently drops callbacks owned by invalid QObjects | `Globals` no longer inherits `QObject`, matching RU | `TestGlobalsRuntimeStart` | fixed |
| D-02 | B-05, C-04 | `AutoCombatTask` stopped with `TypeError` at combat start whenever the LW opening declined | LW had added `lw_opening_checked` to RU `switch_to_combat_start_char()`; upstream then added a no-argument `AutoCombatTask` override | RU signature restored; `begin_combat_session()` alone gates the one-shot LW opening | `TestUseUltimateConfig.test_combat_start_reaches_auto_combat_start_priority_override` | fixed |
| D-03 | B-05, C-03 | Duplicate strict-route switch path | LW `requires_switch` was kept beside RU `switch_step` with `wait_for_turn=False`, which already completes on arrival | LW field, `wants_switch()` and all duplicate branches removed; Requiem uses RU `for_switch(..., wait_for_turn=False)` | `TestRequiemZankouAxis`, planner suite | fixed |
| D-04 | B-05 | Upstream Nanally delay removal (`ad49604`) lost | Merge kept the base entry flow in that hunk | RU entry restored; LW ultimate-landing hooks retained | None beyond RU parity; covered by V-04 real combat | fixed |
| D-05 | B-05, C-04 | Unmarked compatibility fallbacks in RU code (`Zankou` mouse hold, `switch_next_char` strict flag, coffee entry) | Added during the merge to keep incomplete test fakes passing; the coffee fallback coordinate targeted the restock button | RU code restored; test fakes completed with the current contract | `TestZankou`, `TestCombatStartSupport`, `TestDailyCoffee` | fixed |
| D-06 | B-01, B-07, C-01 | `lw_find_confirm()` without a box and the 999 volcano bonfire search raised `AttributeError` | RU removed `BaseNTETask.main_viewport`; two LW callers were not migrated | LW callers use `self.pos.screen.main_viewport.to_box()` | `test_find_confirm` | fixed |
| D-07 | B-07 | Heist path 1 ran the wrong WP5 route for "no avoider" and the G strategy | Upstream renumbered routes (`f32d585`); the merged dispatch and LW G route kept old numbers | User chose the RU G route: `HeistPathA` and `AutoHeistTask.perform_avoidance_action()` restored to RU, LW G-then-Shift route retired | `TestHeistPathA.test_run_path_maps_each_avoider_strategy_to_its_route` | fixed |

Reviewed and intentionally kept: LW gift entry OCR instead of the RU coordinate,
LW volleyball rally/position logic superseding upstream `dcacb83`, and task icons
on LW-owned tasks. Pre-existing, not merge-caused: boss fights retarget for up to
3 seconds when the boss bar briefly disappears, which can void an ultimate.

## Verification evidence

| ID | Behavior rows | Command or scenario | Evidence | Result | Status |
| --- | --- | --- | --- | --- | --- |
| V-01 | B-04, B-05, B-07 | `.\\.venv\\Scripts\\python.exe -m unittest tests.TestCharImplDb tests.TestCombatPlanner tests.TestRequiemZankouAxis tests.TestSwitchNextDispatch` | 190 tests passed | pass |
| V-02 | B-01 to B-07 | `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -p "*.py" -q` | 1015 tests passed in 25.069s | pass |
| V-03 | B-01 to B-07 | `.\\.venv\\Scripts\\python.exe -m compileall -q src tests`; `git -c core.whitespace=cr-at-eol diff --check`; provenance audit for `M` | All commands passed; audit classified local merge decisions and upstream removals | pass |
| V-04 | B-01, B-02, B-03, B-05 | De-identified real-window smoke scenarios | Not run in this environment; requires the updated game UI and manual interaction | open |
| V-05 | D-01 to D-07 | Full suite, `compileall`, and `git diff --check` after the post-merge fixes | 1017 tests passed; new regressions for D-01, D-02, D-06 and D-07 failed before their fixes | pass |

## Closure gate

- Four-tree provenance audit is attached and all local merge decisions are classified.
- Every behavior row has a current-API regression or documented real-window limitation.
- Every affected LW caller has a contract-migration row.
- No stale API, copied RU implementation, compatibility alias, or A/B path remains.
- Focused tests, full tests, syntax checks, and `git diff --check` pass.
- Real-window rows are recorded as pass or explicitly blocked with evidence.
- Sync status remains `open` until every required row is verified.
