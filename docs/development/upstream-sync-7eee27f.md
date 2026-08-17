# Upstream Sync Ledger: 7eee27f

## Status

**Open.** This ledger covers only the synchronization from `U=7eee27f`.
No merge, push, or completion claim is allowed while any row remains `open` or
`blocked`.

## Scope and provenance

| Field | Value |
| --- | --- |
| Merge base `B` | `91c5cf6812bb12a15ad39b311fbe12f57ff74ab3` |
| Local parent `L` | `febe54cb9d021074261650f0b0cdeac26fb6cc21` |
| Upstream parent `U` | `7eee27f1b971e163e5aa20a051044bfd3d2d53fd` |
| Merge result `M` | `<pending>` |
| Audit command | `.\.venv\Scripts\python.exe tools\audit_merge_provenance.py <merge>` |
| Audit result | `<pending>` |
| Sync status | `open` |

The upstream range changes 47 paths, including character lifecycle and planner
contracts, task lifecycle and configuration, sound-trigger timing, resources,
and new tasks. The previous ledger does not cover this `U` and cannot be reused
as completion evidence.

## Pre-merge behavior manifest

| ID | LW behavior | Trigger and input | Required result or timing | Required state and side effects | Automated regression | Real-window scenario | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B-01 | Combat action lifecycle | Enter combat, switch characters, cast skill or ultimate | Current RU action lifecycle remains active; LW retry, dodge settlement, freeze accounting, and safe handoff still work | No duplicate input, stale fallback, or lost current character | `TestSettleSkill`, `TestUltimateCombatSettle`, `TestFreezeDiagnostics`, `TestCombatPlanner` | Verify one real combat with skill, ultimate, dodge, and switch timing | open |
| B-02 | Zankou combat behavior | Zankou enters with skill or ultimate ready | Preserve LW/RU intended sequence; verify gold/purple skill branch, heavy/normal attack cadence, first and repeat ultimate waits | Planner receives correct action result and does not add field-time fallback unexpectedly | New focused Zankou contract test | Real window: Zankou entry with ready and non-ready ultimate | open |
| B-03 | Support resource scheduling | Haniel, Iroi, or Sakiri skill/ultimate becomes ready | `TEAM_BUFF` and `add_tags` changes must not bypass LW preemptive field claims or strict route ordering | Reservations and support handoff remain single-path | `TestBuffSupportPlan`, `TestCombatStartSupport`, `TestLwPreemptiveFieldClaim` | Real window: support resource followed by main DPS handoff | open |
| B-04 | Daily account summaries and targeted retry | Daily run completes or retry button is pressed | Per-account success/fail/skip summaries remain separated; retry runs only the selected account's failed IDs and can be repeated | Retry state is cleared or retained exactly per result; account selection is preserved | `TestDailyRoutine`, `TestDailyCoffee`, `TestSwitchAccount` | Two-account run with failures, partial retry success, and another retry | open |
| B-05 | Anomaly furniture failure isolation | One furniture lookup or claim fails | Failure names the affected furniture and later furniture continues | No first-error abort; retry targets only failed furniture | `TestDailyRoutine` and furniture-focused tests | Real anomaly furniture list containing one missing item | open |
| B-06 | 999 and confirmation flow | Monster refresh or confirmation dialog appears | Current RU confirmation contract and LW recovery remain active | No duplicate `_ru_*` implementation or lost confirmation click | `test_dsd_farm_recovery`, `test_find_confirm` | Real refresh requiring confirmation | open |
| B-07 | Heist route and input interception | Auto-heist path, including Zankou avoidance route, starts | New path and Shift/key interception do not break existing paths or LW input safety | Key-down/up state is always released on exit or failure | `TestHeistTask`, heist path tests | Run each configured path once; verify path C only if configured | open |
| B-08 | Sound-trigger dodge timing | Background game audio produces a dodge cue | New listener/counter interval remains responsive without duplicate triggers or audio-thread death | Capture remains WASAPI/system-output based and restartable | `test_sound_trigger_capture` | Background window with known dodge-cue sample | open |
| B-09 | Scene/task lifecycle refactors | Anomaly, volleyball, auction, route, or round task starts/exits | New task registration, scene transitions, confirmation, and round state use current public contracts | No UI-thread blocking or stale task state | Relevant focused task tests and config registration tests | One real-window smoke scenario per changed existing task; new tasks N/A unless used | open |
| B-10 | Resources and localization | Templates, labels, config, or locale catalog are loaded | New assets/labels/i18n are present; existing LW strings and template mappings remain | No generated local data, user config, or template path is lost | `TestI18nPatch`, config/template tests, resource scan | Visual recognition spot-check for changed templates | open |

## RU-to-LW contract migration matrix

| ID | RU change | Local caller | Old contract | New contract | LW migration on current RU base | Regression | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C-01 | `BaseChar` skill settlement and ultimate recognition changed | `src/lw/char_ext.py`, character callers | LW hooks relied on the prior skill wait and ultimate box behavior | Use current RU lifecycle and public signatures; retain LW retry, settlement, and bounded waits through marked hooks | Rebase `CharExtMixin` behavior onto current RU implementation; no copied old action loop | `TestSettleSkill`, `TestUltimateCombatSettle`, `TestFreezeDiagnostics` | open |
| C-02 | Zankou action/entry logic changed | `src/char/Zankou.py` and planner tests | Skill combo accepted `CombatContext`, single-clicked during polling, and waited 2 seconds for repeat ultimate | Current action callable, heavy-attack cadence, corrected name/element, and 3-second repeat wait | Preserve intended LW behavior and audit slot reservation/result consumption | New Zankou contract tests | open |
| C-03 | Support base and action tags changed | `src/char/Support.py`, `Haniel.py`, `Iroi.py`, `Sakiri.py`, `src/lw/*` | Existing support actions used prior tags and base methods | `TEAM_BUFF` and `add_tags` are current planner contracts | Re-express LW support claims and reservations using current public API | `TestBuffSupportPlan`, `TestCombatPlanner` | open |
| C-04 | Planner action score/tag model changed | `src/lw/planner_ext.py`, character action declarations | Planner had prior tag set and LW preemptive extension | RU owns current tags; LW preemptive behavior remains in its adapter and marked connections | Verify no direct planner-internal state or removed API remains | `TestLwPreemptiveFieldClaim`, `TestCombatPlanner` | open |
| C-05 | `BaseNTETask` and `RoundMixin` extraction changed task lifecycle | `src/lw/nte_task_ext.py`, daily/999/task callers | LW called prior task methods and lifecycle points | Use current public task and round contracts | Migrate callers and retain only minimal `[lw]` connections | Focused daily, DSD, round, and task tests | open |
| C-06 | `FurnitureTask` and anomaly furniture flow changed | `src/lw/daily_routine_ext.py`, UI retry path | LW retry and per-furniture state used prior task flow | Current RU method signatures and item iteration must be preserved | Keep per-item failure isolation and retry state in LW mixin | `TestDailyRoutine` and furniture tests | open |
| C-07 | `AnomalyTask`/`AnomalyHunter` confirmation and timing changed | LW confirmation/recovery callers | Prior boxes, waits, or exit paths | Use current confirmation range and public exit lifecycle | Migrate only affected hooks; do not restore old duplicate helpers | `TestAnomalyTask`, `test_find_confirm`, DSD tests | open |
| C-08 | Heist and input interception changed | `src/lw` input/route callers | Prior Shift/key release and route assumptions | Current key lifecycle and route APIs | Preserve safe release and route-specific LW behavior | `TestHeistTask` and route tests | open |
| C-09 | Sound listener/counter interval changed | `src/lw` sound hooks and trigger tests | Prior interval and callback timing | Current listener timing and restart contract | Keep system-output capture and bounded trigger behavior | `test_sound_trigger_capture` | open |
| C-10 | Detector notification and template assets changed | OpenVINO/LW visual callers | Prior notification or label/resource contract | Current detector callback and labels/assets | Update only current public resource/notification contracts | Detector/resource tests | open |

## Implementation decisions

| ID | Changed path | RU baseline retained | LW behavior re-expressed | Why no duplicate path remains | Commit | Status |
| --- | --- | --- | --- | --- | --- | --- |
| I-01 | `<pending>` | `<pending>` | `<pending>` | `<pending>` | `<pending>` | open |

## Verification evidence

| ID | Behavior rows | Command or scenario | Evidence | Result | Status |
| --- | --- | --- | --- | --- | --- |
| V-01 | B-01 to B-10 | Focused current-API unittest commands | `<pending>` | `<pending>` | open |
| V-02 | B-01 to B-10 | `.\.venv\Scripts\python.exe -m unittest discover -s tests -p "*.py"` | `<pending>` | `<pending>` | open |
| V-03 | B-01, B-02, B-04, B-05, B-08, B-09, B-10 | De-identified real-window scenarios with timing/outcome thresholds | `<pending>` | `<pending>` | open |
| V-04 | All paths | `git diff --check` and stale-API/provenance scans | `<pending>` | `<pending>` | open |

## Closure gate

- All rows remain `open` until current-RU migration and evidence are complete.
- No push or completion claim is allowed while any required row is `open` or
  `blocked`.
- The final merge must include the provenance audit output and a clean review of
  user-owned files, local configs, logs, screenshots, and generated data.
