# Upstream Sync Ledger: f608673

## Status

**Complete.** Every acceptance-matrix row is marked `verified`; V-01 records the
final full regression run. The user-modified `src/config.py` worktree was audited
at `HEAD` only and was not changed as part of this sync.

## Immutable scope

| Field | Value |
| --- | --- |
| Local parent before merge | `62ac610fd2789185ad20ae0099b2013a740b678d` |
| Upstream parent | `91c5cf6812bb12a15ad39b311fbe12f57ff74ab3` |
| Merge base | `89fd1115c0d5ff88af335315c852a93645165d47` |
| Merge commit | `f608673c739ac03c25cd3b3609a1f82d5614dba0` |
| Shared-path count | 49 |
| Upstream changed-path count | 238 |
| Runtime-focused upstream paths | 105 |

## Rules for this ledger

1. The latest RU implementation is the baseline. Preserve LW behavior, not the
   previous LW implementation or old RU internals.
2. Every affected LW or `[lw]` call must record its old contract, new contract,
   migration, and regression test before it can become `verified`.
3. New LW logic belongs in `src/lw/`. A direct RU change is allowed only as a
   minimal `[lw]`-marked connection to that logic.
4. Tests must exercise current public APIs. A mock of a removed private API is
   invalid coverage.
5. A green full test run is evidence for rows with explicit coverage; it is not
   a blanket completion signal.

## Recorded incidents and completed repairs

| ID | Affected contract | Evidence | Migration | Tests | Commit | Status |
| --- | --- | --- | --- | --- | --- | --- |
| I-01 | `CustomCharManager._find_character_id_by_name` was removed by RU character-manager refactor | Auto-combat stopped twice with `AttributeError` after the first support skill | `CombatExtMixin` now uses the public `get_all_characters()` snapshot and stable `char_id` | `TestTeamChangeCheck` verifies the private API is not called | `ad031e6` | verified |
| I-02 | `game_filters.isolate_cd_to_black` was renamed/removed | Static upstream-break scan found the stale fishing CD OCR reference | Use `isolate_text_to_black` | `test_fish_catching` executes the OCR branch and asserts the processor | `ad031e6` | verified |

## Contract records

### A-01: Agent contracts

| Field | Evidence |
| --- | --- |
| Old local contract | `f608673^1:CLAUDE.md` contained the `999` alias, `[lw]` marker semantics, mixin/constructor restrictions, single-path prohibition, and same-delivery migration of changed RU exception/state contracts. |
| Upstream evidence | `f608673^2` has no `CLAUDE.md` and removed the LW/RU sections from its own `AGENTS.md`. This is absence of a file that only existed locally, not an upstream deletion of local content. |
| Merge defect | `f608673` itself changed the local `CLAUDE.md` from 73 lines to a five-line pointer (`4 insertions, 71 deletions`). The merge should have preserved the local file or explicitly migrated every rule; this was an unrecorded local merge decision. |
| Required LW behavior | Both agents must use the same durable LW/RU rules; the rules must prohibit retaining old interfaces or dual paths merely to make the merge pass. |
| Migration | `AGENTS.md` is the sole full source of shared rules, including the restored `LW implementation and connection details`; `CLAUDE.md` is a mandatory pointer with no exception. The four-tree provenance rule and audit tool prevent local-only code from being misattributed to RU. |
| Verification | Reviewed the complete former local `CLAUDE.md`, the two merge parents, and the current files. The current `CLAUDE.md` points to `AGENTS.md`; all behavior-affecting rules above are present in `AGENTS.md`. |
| Commit | `11e71e1`, `6818c49` |
| Status | verified |

### M-01: Four-tree provenance for the merge result

| Field | Evidence |
| --- | --- |
| Command | `python tools/audit_merge_provenance.py f608673` with `B=89fd111`, `L=62ac610`, `U=91c5cf6`, and `M=f608673`. |
| Result | 53 local-only paths were retained byte-for-byte; no local-only path was removed; nine local-only paths were modified by `M`; 37 paths changed on both sides. |
| Actual RU deletions | Only six paths that existed in `B` were absent from `U`: the old character factory/healer paths and the old daily/planner documentation paths. These must be migrated as RU refactors, not described as deletion of LW-only code. |
| Required process | The following nine paths are local merge decisions. Each needs an old/new contract, migration, and regression record before its containing matrix group can close. |
| Regression | `tests.test_merge_provenance` exercises the two classifications. |
| Commit | `6818c49` |
| Status | verified; detailed records below |

| ID | Local-only paths modified by `M` | Old local contract | Current RU contract and migration | Regression | Commit | Status |
| --- | --- | --- | --- | --- | --- | --- |
| M-01a | `CLAUDE.md` | Full LW/RU merge instructions were local-only. | The merge incorrectly compressed it; A-01 restores every behavior-affecting rule to `AGENTS.md` and leaves `CLAUDE.md` as its pointer. | Four-tree audit and A-01 review. | `11e71e1`, `6818c49` | verified |
| M-01b | `src/char/Requiem.py`, `src/lw/chars.py` | `lw_char_dict` extended the deleted old `CharFactory.char_dict`; Requiem depended on that explicit Chinese display name. | Register the same implementation IDs with the RU `CharRegistry`; `Requiem.cn_name` keeps automatic built-in discovery and explicit registration consistent. | `TestCharImplDb` resolves `builtin:requiem` after registry scanning and checks its class and Chinese name. | `6818c49` | verified |
| M-01c | `src/lw/combat_ext.py`, `tests/TestCombatSurvivalStatus.py`, `tests/TestUseUltimateConfig.py` | LW combat loop set direct task fields and started combat through the old start-switch path. | Use RU `CombatSession`, `begin_combat_session()`, and current public character snapshot. I-01 repaired the stale private lookup after this migration. | `TestUseUltimateConfig`, `TestCombatSurvivalStatus`, `TestTeamChangeCheck`, and `TestCD` cover the current session, reload, and CD contracts. | `f608673`, `ad031e6`, `6818c49`, `25a2049` | verified; full character/combat caller audit is recorded in C-09 |
| M-01d | `src/lw/dsd_farm_ext.py`, `tests/test_dsd_farm_recovery.py` | LW had `lw_refresh_monsters()` to click the post-refresh confirmation dialog. | RU now owns `DSDFarmTask.refresh_monster()` and calls public `wait_click_confirm()` with the no-remind callback. The old LW duplicate was correctly retired. | `test_dsd_farm_recovery` covers the changed and unchanged branches; `test_find_confirm` exercises the current confirmation click contract. | `6818c49`, `c9b004e` | verified |
| M-01e | `src/lw/nte_task_ext.py` | `lw_find_confirm()` did not accept the new image mask parameter. | It forwards `mask_function` to both template searches; `BaseNTETask.find_confirm()` supplies the RU `confirm_mask`. | `test_find_confirm` verifies both forwarding and the confirmation click lifecycle. | `6818c49`, `c9b004e` | verified |

### C-01: Freeze-duration contract

| Field | Evidence |
| --- | --- |
| Old local contract | LW added a `cause` parameter to `BaseCombatTask.add_freeze_duration()` and changed RU `freeze_durations` entries from `(start, duration, freeze_time)` to four-tuples. `BaseChar` and `Hotori` passed the extra parameter. |
| New RU contract | The current RU contract uses a three-tuple; callers must not depend on a fourth field or an extended public method signature. |
| Required LW behavior | Preserve optional CD-diagnostic causes without changing cooldown accounting, tuple shape, or the public RU method. |
| Migration | `CombatExtMixin.lw_add_freeze_duration()` records causes in LW-owned side metadata and delegates to the unchanged RU method. The four former callers now use only this minimal `[lw]` connection. `_log_cd_estimate()` reads the side metadata. |
| Regression | `TestFreezeDiagnostics` asserts the stored tuple remains three fields; `TestRefreshCdReady`, `TestCD`, `TestUseUltimateConfig`, and `TestTeamChangeCheck` all pass. |
| Commit | `1dfd165` |
| Status | verified |

### C-02: Support-entry commit hook

| Field | Evidence |
| --- | --- |
| Old local contract | `BaseCombatTask` called the private mixin method `_committing_to_ready_support()` while reconsidering an intro switch. |
| New RU contract | RU switch logic has no LW private helper; the local policy must be an explicit, minimal extension point. |
| Migration | Renamed the LW method to `lw_is_committing_to_ready_support()` and retained one `[lw]` condition in the RU decision. |
| Regression | `TestBuffSupportPlan` exercises the public LW hook and `TestCombatPlanner` verifies the related planner paths. |
| Commit | `df46aeb` |
| Status | verified |

### C-03: Nanally ultimate policy boundary

| Field | Evidence |
| --- | --- |
| Old local contract | Local code embedded the cooldown-transition tolerance and forced six-second ultimate field time directly in `src/char/Nanally.py`. |
| New RU contract | RU still owns Nanally's planner plan and action loop; only the two LW-specific decisions differ. |
| Migration | `NanallyExtMixin` owns `lw_ultimate_action_landed()` and `lw_should_continue_ultimate_field()`. `Nanally` retains the RU flow with two minimal `[lw]` calls. |
| Regression | `TestNanallyLw` drives the real plan entry generator, the loop connection, and cooldown-transition rule; `TestCombatPlanner` remains green. |
| Commit | `6c6bc47` |
| Status | verified |

### C-04: BaseChar skill-settlement API

| Field | Evidence |
| --- | --- |
| Old local contract | LW appended `settle_cooldown` and `settle_max_duration` to RU `BaseChar.click_skill()`, then Requiem called those local-only parameters. |
| New RU contract | `click_skill()` retains the upstream signature and action lifecycle. |
| Required LW behavior | Retain one retry for a lost input and the optional post-dodge settlement window, including Requiem's 16-second and three-second override. |
| Migration | `CharExtMixin` owns the input action factory, post-action settlement, and `lw_click_skill_with_settlement()` wrapper. `BaseChar` has two minimal `[lw]` calls; Requiem uses the LW wrapper rather than extending RU arguments. |
| Regression | `TestSettleSkill` executes the current RU method and asserts its signature excludes the two LW arguments; `TestRequiemSkill`, `TestBuffSupportPlan`, and `TestCombatPlanner` pass. |
| Commit | `d75e8a2` |
| Status | verified |

### C-05: Character registry and persisted implementation IDs

| Field | Evidence |
| --- | --- |
| Old local contract | `lw_char_dict` extended the removed `CharFactory.char_dict`, and existing user databases used `char_requiem` and template combo IDs. |
| New RU contract | `CharRegistry.register()` is the extension API; persisted characters reference `impl_id` values such as `builtin:requiem`. |
| Migration | `register_lw_char_implementations()` uses the registry API; the registry extension point and the five LW legacy-ID mappings are explicitly marked `[lw]`. |
| Regression | `TestCharImplDb` migrates the legacy DB, resolves Requiem in the scanned registry, and checks its display name. |
| Commit | `6818c49`, `7d37ed9` |
| Status | verified |

### C-06: Combat snapshot and action-loop hooks

| Field | Evidence |
| --- | --- |
| Old local contract | LW had a full replacement of `BaseCombatTask.get_cd()`, plus multi-line direct changes to the RU action poll and combat-start method. |
| New RU contract | RU owns `get_cd()` control flow, the action loop, and first-switch sequence. LW supplies only its CD policy, animation-safe poll, and pre-start cleanup/resource observation. |
| Migration | `lw_get_cd()`, `lw_after_action_poll()`, and `lw_prepare_combat_start()` now contain the LW behavior. The RU files retain one minimal `[lw]` call at each extension point. |
| Regression | `TestCombatExtensionHooks` asserts the current snapshot and start-preparation wiring; `TestSettleSkill`, `TestRefreshCdReady`, `TestCD`, `TestUseUltimateConfig`, and `TestTeamChangeCheck` pass. |
| Commit | `e4201e2` |
| Status | verified |

### C-07: LW preemptive FieldClaim policy

| Field | Evidence |
| --- | --- |
| Old local contract | The merge result added `FieldClaimTiming`, `FieldClaim.timing`, and `FieldClaim.preemptive()` to the RU public planner API. It also embedded a 47-line preemptive-claim selector in `CombatPlanner`. BuffSupport used the extended API to place confirmed ultimate or skill resources before automatic element reactions. |
| New RU contract | In `f608673^2`, `FieldClaim` has only source, level, reason, and expected-entry data. It has no timing dimension or `preemptive()` factory; the planner documentation likewise describes ordinary claims only. |
| Required LW behavior | A confirmed LW BuffSupport resource must be allowed to run before the automatic element reaction and at combat start, while a strict route and an explicit combat-start priority still win. A current support must not be switched away solely for another support claim. |
| Migration | `LwPreemptiveFieldClaim` and `lw_preemptive_field_claim()` live in `src/lw/field_claim_ext.py`. `CombatPlannerExtMixin` owns candidate selection and the opening policy. RU restores its `FieldClaim` and documentation exactly, retaining only the `[lw]` mixin connection and the two decision calls. |
| Regression | `TestLwPreemptiveFieldClaim` proves the RU data contract has no timing field or preemptive factory. `TestCombatPlanner`, `TestBuffSupportPlan`, `TestCombatStartSupport`, `TestUltimateDiamond`, `TestCombatExtensionHooks`, and `TestUseUltimateConfig` exercise the public switch and resource behaviors. |
| Commit | `aee9558` |
| Status | verified |

### C-08: BaseChar action-loop and ultimate-safety extension boundary

| Field | Evidence |
| --- | --- |
| Old local contract | The local result embedded input-mode retry, post-dodge skill settlement, action-frame polling, ultimate wait protection, idle attack filling, and freeze diagnostic causes directly in `BaseChar`. It also changed the upstream ten-second ultimate-unfreeze timeout. Those behaviors must remain, but must not replace the current RU character lifecycle. |
| New RU contract | In `f608673^2`, `BaseChar` owns the action lifecycle, `click_skill()` signature, cooldown/freeze tuple updates, normal-attack loop, and the initial `combat_detect_uncertain` wait. It has no LW mixin and no extended public API. Character callers must use the current task methods and public `click_skill()` rather than reintroducing the former local parameters or a second action loop. |
| Migration | `CharExtMixin` owns the retry and safety algorithms: `lw_skill_send_action()`, `lw_after_skill_action()`, `lw_after_action_poll()`, `fill_idle_attack()`, and the ultimate-unfreeze helper. `BaseChar` retains only minimal `[lw]` connections in the current RU flow. `CombatExtMixin.lw_wait_ultimate_combat_settle()` owns the uncertain-combat policy. Freeze causes use `lw_add_freeze_duration()` and preserve the RU three-field storage; this is the C-01 contract. The 4-second unfreeze bound is now the LW mixin constant, not a replacement copy of the RU method. |
| Required LW behavior | A missed input mode may receive one retry; a dodge during a skill receives a bounded settlement window; polling advances the frame without treating a valid animation as combat exit; ultimate and idle filling stop safely when the current character or team is no longer valid; and failed ultimate OCR cannot hold the combat loop for the former ten seconds. |
| Regression | Focused current-API tests: `TestSettleSkill`, `TestUltimateCombatSettle`, `TestFreezeDiagnostics`, `TestRequiemSkill`, `TestNanallyLw`, and `TestCharImplDb` (48 tests) passed on 2026-08-16. They exercise `BaseChar`'s real signatures and current mixin connection points; mocks are confined to visual/input leaves and do not mock removed planner or factory APIs. C-03, C-04, and C-05 retain their dedicated coverage. |
| Commit | `1dfd165`, `d75e8a2`, `e4201e2` |
| Status | verified |

### C-09: Combat session, planner lifecycle, and reload extension boundary

| Field | Evidence |
| --- | --- |
| Old local contract | The pre-migration local combat path replaced CD refresh/load behavior, tracked team changes during any combat check, and depended on planner APIs that RU later renamed or removed. The original merge also embedded LW preemptive claims in `FieldClaim` and in the planner core. |
| New RU contract | `f608673^2` owns `CombatSession`, `begin_combat_session()`, the combat-start switch sequence, `CombatContext.is_slot_available()`, `CombatContext.is_action_allowed()`, `request_role()`, and repeatable entry actions. `FieldClaim` is again a four-field RU value object; planner state remains internal to planner/context implementation. `can_execute_action`, `FieldClaimTiming`, and `FieldClaim.preemptive()` are not current APIs. |
| Migration | `BaseCombatTask` retains the RU session and switch lifecycle. Its `[lw]` connections delegate one-way into `CombatExtMixin` for CD snapshots, bounded start observation, support-commit protection, team-monitor opt-in, and weak-recognition recovery; `lw_combat_run()` is the sole consumer of `TeamReloadRequested`. Thus `combat_once` paths do not receive an unhandled reload signal. `CombatPlannerExtMixin` supplies the two preemptive decisions while RU `core`, `types`, and `context` remain on their current contracts; see C-07 for the claim policy. |
| Required LW behavior | Keep conservative OCR CD anchoring and post-cast grace, preserve valid teams through transient UI/recognition loss, reload only a confirmed changed team in trigger auto-combat, and allow confirmed support resources before an automatic element reaction without weakening strict routes or public planner contracts. |
| Caller audit | Repository scan found no callers of removed `can_execute_action`, removed `FieldClaimTiming`/`preemptive()`, or the removed private character lookup. Character and LW code use `is_action_allowed()`, `is_slot_available()`, request methods, and standard `ActionIntent` declarations; direct state references are confined to planner implementation and its context, not character policy code. |
| Regression | `TestCombatPlanner`, `TestCombatSurvivalStatus`, `TestUseUltimateConfig`, `TestTeamChangeCheck`, `TestCombatExtensionHooks`, `TestUltimateCombatSettle`, `TestCD`, `TestRefreshCdReady`, `TestBuffSupportPlan`, and `TestCombatStartSupport` passed (162 tests) on 2026-08-16. The tests cover the current session API, planner request/action lifecycle, team-reload scope, OCR CD path, and current source-level API restrictions. |
| Commit | `e4201e2`, `df46aeb`, `ad031e6`, `aee9558` |
| Status | verified |

### L-02: LW adapter-layer caller audit

| Field | Evidence |
| --- | --- |
| Old local contract | User behavior was spread across character registration, combat, confirmation, 999, and character-UI files. Some 999 code retained `_ru_*` helper copies inside `DSDFarmTask`, making later upstream comparison needlessly ambiguous. |
| New RU contract | The active RU contracts are the registry API, current combat session/planner APIs, `BaseNTETask.find_confirm()` with its internal mask, and the current 999 public task method signatures. No LW extension may call removed factory/planner APIs or retain a parallel RU helper in a task class. |
| Migration | `chars.py`, `combat_ext.py`, and `nte_task_ext.py` use the contracts recorded in C-01 to C-09, C-05, I-01, and M-01e. `DSDFarmExtMixin` now owns bounded teleport recovery and deterministic target selection; `DSDFarmTask` retains only `[lw]` delegation. `_ru_teleport_to_nearest_bonfire()` and `_ru_teleport_to_top_bonfire()` no longer exist. `CharUIExtMixin` remains a visual extension; its off-field diamond signal is limited to opening observation and does not override RU normal-dispatch ultimate truth. |
| Caller audit | Static scan found no removed factory lookup, planner timing API, old action-availability API, or retained 999 `_ru_teleport_*` helper. Every production connection is a mixin inheritance or a marked one-way call. |
| Regression | `test_dsd_farm_recovery`, `test_find_confirm`, `TestUltimateDiamond`, `TestTeamChangeCheck`, and the combat records above cover the current adapters. After the 999 extraction, `test_dsd_farm_recovery` passed 24 tests on 2026-08-16, including real LW top-bonfire selection rather than a removed-helper mock. |
| Commit | `e37f9fb` plus the prior migration commits in C-01 to C-09 |
| Status | verified |

### T-01: Task and mixin lifecycle boundary

| Field | Evidence |
| --- | --- |
| Old local contract | Confirmation recognition, 999 recovery, routine retry/account summaries, daily ordering, stamina completion, and character UI observations were mixed into task classes with several extended methods. |
| New RU contract | `BaseNTETask.find_confirm(box, threshold)`, `DailyRoutineTask.do_run(self)`, and `FurnitureTask.claim_anomaly_furniture(self)` retain current signatures; RU owns the task lifecycle, confirmation lifecycle, and ordinary combat paths. `AnomalyTask.exit_anomaly()` uses the current RU-safe confirmation range. |
| Migration | `NTETaskExtMixin` receives the internal confirmation mask and OCR candidate policy; `DSDFarmExtMixin` receives 999 recovery; `DailyRoutineExtMixin` and the furniture/UI extensions receive targeted retry/account behavior (P-01). `DailyTaskExtMixin` now owns LW daily ordering and the stamina-only completion policy, leaving `DailyTask` with three minimal `[lw]` calls. `CharUIExtMixin` owns the UI visual extension. |
| Regression | `test_dsd_farm_recovery`, `test_find_confirm`, `TestDailyRoutine`, `TestDailyStamina`, `TestDailyCoffee`, `TestAnomalyTask`, `TestUltimateDiamond`, `TestSwitchAccount`, `test_fish_catching`, and `TestRequiemCombatConfigTask` passed (121 tests) before the 999 extraction; its 24-test focused suite passed after extraction. `TestDailyCoffee`, `TestDailyStamina`, and `TestDailyRoutine` passed again (41 tests) after `DailyTaskExtMixin` migration. |
| Commit | `2fde742`, `c7c52eb`, `e37f9fb` |
| Status | verified |

### R-02: Runtime task-registration audit with user-worktree protection

| Field | Evidence |
| --- | --- |
| Audit target | `HEAD:src/config.py`, not the dirty worktree file. |
| New RU contract | RU owns config bootstrap and task discovery. The committed LW additions are four registrations only: Switch Account, Fish Catching, Requiem Combat Config, and Nanally Super Jump. |
| Verification | `git diff f608673^2 HEAD -- src/config.py` shows only those four `[lw]` entries. `TestConfigTaskRegistration` verifies all four remain registered (1 test passed on 2026-08-16). The working-tree Hide Seek registration and its untracked implementation are user changes; they were neither read as sync evidence nor modified, staged, or committed. |
| Commit | `8045e5d` |
| Status | verified; audit-only for the user-modified working-tree file |

### L-01: Gettext catalog provenance and compilation

| Field | Evidence |
| --- | --- |
| Old local contract | `f608673^1` already contained the four LW auto-fish strings and six LW virtual-gamepad configuration strings in every locale. Those strings are still used by `FishCatchingTask` and `RequiemCombatConfigTask`. |
| New RU contract | `f608673^2` updated all seven locale catalogs with its current source strings and generated `.mo` files. It contains two identical `"自动战斗任务不可用"` entries per catalog even though the current `TeamManagerTab` source has one use. |
| Merge result | `f608673` is the required union: it retains the RU catalog updates and the ten LW-visible strings. It retains one, not zero, `"自动战斗任务不可用"` entry. This is catalog de-duplication in the merge result, not an upstream deletion. |
| Verification | All seven `.po` files parse, have no duplicate `msgid`, and contain the ten LW strings plus the live TeamManager string. The i18n helper recompiled all seven `.mo` files without producing a Git diff. Every non-empty `.po` translation is returned by its `.mo`; `TestI18nPatch` passes. |
| Commit | `35d80c7` (audit record) |
| Status | verified |

### B-01: Startup order and optional virtual-gamepad dependency

| Field | Evidence |
| --- | --- |
| Old local contract | `f608673^1` contained the saved-window visibility repair, the bounded debug-image cleanup call, and the `virtual-gamepad` optional dependency. The gamepad module imports `vgamepad` only when the disabled-by-default test pulse is used. |
| New RU contract | `f608673^2` imports config and installs `startup_patches` before loading `ok`; it upgrades `ok-script` and `onnxocr-ppocrv5`, and adds the required `pywin32` dependency. |
| Migration | The current entry points preserve the RU import and patch order. The LW cleanup remains after `ok` loads; the window repair stays before app construction. `pyproject.toml` retains the RU required dependencies and the LW `virtual-gamepad` extra; `uv.lock` records the extra rather than making `vgamepad` a base dependency. |
| Verification | `main.py` and `main_debug.py` compile. `TestMainEntry` verifies off-screen recovery without opening a GUI and preserves visible positions. `TestCleanup` and `test_virtual_gamepad` pass. `uv lock --check` passes and direct import of the virtual-gamepad module performs no driver creation. |
| Commit | `9df71ca` |
| Status | verified |

### P-01: Post-merge daily account summary and targeted retry boundary

| Field | Evidence |
| --- | --- |
| Scope | This post-merge feature does not close a shared-path row by itself. It is recorded because it changes LW behavior in RU daily task and UI files and must obey the same boundary rules. |
| Old local contract | Account summaries and retry state were in `DailyRoutineExtMixin`, but `DailyRoutineTask.do_run(task_ids=None)` and `FurnitureTask.claim_anomaly_furniture(furniture_list=None)` extended RU method signatures. The retry button implementation also lived directly in `DailyRoutineTab`. |
| RU contract | RU keeps `DailyRoutineTask.do_run(self)` and `FurnitureTask.claim_anomaly_furniture(self)` as zero-argument task lifecycle methods. Daily UI has no retry-specific state or callback. |
| Required LW behavior | Each account has a separate success/failed/skipped summary. Retry runs only the failed task IDs from the most recent account and does not switch accounts. Furniture failures name the affected furniture and do not prevent later furniture from running. |
| Migration | `DailyRoutineExtMixin` owns retry filtering, start rejection cleanup, and account-cycle wrapping. `FurnitureTaskExtMixin` owns per-furniture retry state and failure details. `DailyRoutineTabExtMixin` owns the retry button. RU files retain only `[lw]` mixin connections; no old signature or retry helper remains. The existing gettext entry `"重试失败项"` is present in all eight locale catalogs. |
| Regression | `TestDailyRoutine`, `TestDailyCoffee`, and `TestI18nPatch` pass. Tests assert restored signatures, no account cycle during retry, rejection cleanup, disabled/enabled retry-button policy, continued furniture processing after an exception, and the house-list-specific failure reason. |
| Commit | `2fde742` |
| Status | verified |

### R-01: Window layout and focus-stability extension boundary

| Field | Evidence |
| --- | --- |
| Old local contract | The merge result put `Globals.on_show_main_window()` and `NTEInteraction._lw_stabilize_click_focus()` directly in RU files. The former installs the LW task-info layout; the latter retries activation once before suppressing a click during a foreground transition. |
| New RU contract | RU owns the global lifecycle and click delivery flow. LW must not add its own state or retry algorithm to their public implementation classes. |
| Migration | `GlobalsExtMixin` owns the main-window hook; `NTEInteractionExtMixin` owns the focus retry constant and algorithm. `Globals` and `NTEInteraction` retain only `[lw]` mixin connections and the two click guard calls. |
| Regression | `test_window_focus_stabilizer`, `test_nte_interaction`, `test_task_info_layout`, and `test_globals_ext` pass. The new checks prove the hook and focus policy are resolved from the LW mixins, without operating a real game window or input device. |
| Commit | `00ef976` |
| Status | verified |

### V-01: Full regression snapshot after boundary migrations

| Field | Evidence |
| --- | --- |
| Command | `python -m unittest discover -s tests -p "*.py"` |
| Result | 591 tests passed in 15.143 seconds on 2026-08-16. |
| Scope | The suite uses headless initialization and mocks for input/visual leaves. It is regression evidence for each completed record, not a substitute for real-game validation. The run used the existing user worktree, whose untracked Hide Seek task is discoverable through the user's dirty config; that file was not modified, staged, or used as merge evidence. |
| Matrix effect | The focused contract records C-01 to C-09, L-02, T-01, R-01, and R-02 are complete; this final suite closes the regression-matrix row. |

## Shared-path acceptance matrix

Each group below expands to the named shared paths. Every group is `pending`
until the individual contracts and regression evidence are added below it.

| Group | Shared paths | Required audit | Status |
| --- | --- | --- | --- |
| Agent contracts | `AGENTS.md`, `CLAUDE.md` | Compare all shared LW/RU rules and record any mismatch | verified; see A-01 |
| Planner documentation | `docs/development/combat-planner.md` | Check changed planner APIs, examples, and associated tests | verified; current file matches `f608673^2`, see C-07 |
| Localization | 13 `i18n/*/LC_MESSAGES/ok.po` or `ok.mo` paths | Verify no LW-visible strings were lost and generated catalogs match sources | verified; see L-01 |
| Bootstrap and dependencies | `main.py`, `main_debug.py`, `pyproject.toml`, `uv.lock` | Verify startup and dependency contract changes against LW initialization | verified; see B-01 |
| Character core | `src/char/BaseChar.py`, `Hotori.py`, `Nanally.py`, `Requiem.py`, `core/CharFactory.py`, `core/CharRegistry.py`, `custom/CustomCharDbMigrator.py` | Map character lifecycle, role registration, custom-character schema, and all LW callers | verified; see C-01, C-03 to C-05, and C-08 |
| Combat core | `src/combat/BaseCombatTask.py`, `planner/core.py`, `planner/types.py` | Map session lifecycle, planner action/result contracts, interrupt and team-reload behavior | verified; see C-07 and C-09 |
| Runtime infrastructure | `src/config.py`, `src/globals.py`, `src/interaction/NTEInteraction.py` | Check registration, global lifecycle, interaction semantics, and LW connections | verified; see R-01 and R-02; config is audited at HEAD because its worktree has user changes |
| LW layer | `src/lw/chars.py`, `combat_ext.py`, `dsd_farm_ext.py`, `nte_task_ext.py` | Reapply each required LW behavior on current RU public APIs; no stale private calls or dual paths | verified; see L-02 and C-01 to C-09 |
| Tasks and mixins | `src/tasks/AnomalyTask.py`, `BaseNTETask.py`, `DSDFarmTask.py`, `DailyTask.py`, `daily/DailyRoutineTask.py`, `mixin/CharUIMixin.py` | Trace task lifecycle and each `[lw]` hook across changed RU contracts | verified; see T-01 and P-01 |
| Regression suite | `TestCharImplDb.py`, `TestCombatPlanner.py`, `TestCombatSurvivalStatus.py`, `TestDailyCoffee.py`, `TestUseUltimateConfig.py`, `test_dsd_farm_recovery.py` | Remove obsolete mocks, prove current contracts and preserve LW results | verified; see V-01 and the focused records C-01 to C-09, L-02, and T-01 |

## Post-merge changes requiring boundary audit

These changes were added after `f608673`; they do not close the upstream-sync
matrix and must themselves obey the LW/RU boundary before the ledger can close.

| Change | Files | Required action | Status |
| --- | --- | --- | --- |
| Account-aware daily summary and retry | `src/lw/daily_routine_ext.py`, `src/tasks/daily/DailyRoutineTask.py`, `src/tasks/daily/FurnitureTask.py`, `src/ui/DailyRoutineTab.py` | Move remaining daily-specific behavior behind `src/lw/` adapters or mark minimal RU connection points with `[lw]`; retain current tests | verified; see P-01 |
| Interface-break repair | `src/lw/combat_ext.py`, `src/lw/fish_catch_ext.py` | Keep I-01 and I-02 regression coverage during later migration work | verified |

## Required evidence before closure

- For each matrix row, record the exact RU contract change and each LW call site.
- Record the migration commit and the tests that fail without that migration.
- Run the relevant focused tests and the full unittest suite after the final row.
- Check the final diff for LW boundary violations and synchronise any shared
  `AGENTS.md`/`CLAUDE.md` convention changes.
- Leave no `pending` row. If an item cannot be proven, retain `pending` and
  report the sync as incomplete.
