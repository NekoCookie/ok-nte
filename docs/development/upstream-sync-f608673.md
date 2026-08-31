# Upstream Sync Ledger: f608673

## Status

**Complete with corrective record I-03.** The original matrix lacked the Requiem
planner-action result contract, so its earlier `verified` status did not prove the
user-visible overlap handoff. I-03 records the missed behavior and its regression.
Future syncs must use `upstream-sync-template.md` and cannot treat a green full
suite as blanket completion. The user-modified `src/config.py` worktree was audited
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
| I-03 | Requiem true-skill overlap changed from a direct call into a planner action | The prior implementation had no return-value consumer. During planner migration `cast_real_skill()` still returned `None`, so the RU planner correctly treated the action as failed and ran `planner_field_time` for about 1.3 to 2.5 seconds before switching. | Return `True` only after the real skill enters long CD and the overlap window is set; return `False` for short CD or failed casts. This preserves the current RU planner contract without restoring a legacy switch path. | `TestRequiemSkill.test_real_skill_overlap_skips_field_time_fallback`; 607-test full suite | `2bfad64` | verified |

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
| Regression | `TestCharImplDb` migrates a pre-v7 database containing every LW legacy ID, including the four role templates and Requiem; it asserts every persisted `impl_id` and the scanned Requiem registry/display name. |
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

### P-02: Zankou main-DPS template and coordinated-axis integration

| Field | Evidence |
| --- | --- |
| Scope | Historical record of the original Zankou main-DPS and coaxis integration. Its former raw ordinary-switch repeated-Q/E behavior is superseded by P-05, which retains one Requiem coaxis configuration switch for standard planner Q/E dispatch. Its original undifferentiated sound-dodge recovery is superseded by P-10. Its original single-ultimate coaxis entry is superseded by P-11 for awakened Zankou. |
| RU contract | `src/char/Zankou.py` remains unchanged and continues to own the normal template's role, action plan, ultimate flow, and skill combo. The current RU `BaseChar` entry window retains its normal-attack behavior, with minimal `[lw]` connections for the configurable shared duration and planner fallback accounting. `src/char/Requiem.py` retains its existing G, ultimate, real/free skill, pending-combo, and no-resource order; LW substitutes only its final no-resource field action and the paired free-skill follow-up when the exact templates and switches are active. `BaseCombatTask` retains the normal start decision and switch implementation; it has minimal `[lw]` hook-result connections that run a completed input-sensitive opening before RU's initial attack, a clean-first-action option used only by that insertion, and an optional switch-window input hook. `SwitchDecision.scoring_action_slot` reports the action slot that supplied normal switch scoring without changing `expected_entry` or the entry-action order. |
| Required LW behavior | `builtin:zankou_main_dps` appears as `残虹主C`. The standalone key test remains unchanged: default `8` toggles repeated Requiem normals, the test-only Zankou switch delay, held attack, sustained normals, and switching back. It requires a stable starter-key release before arming the next press as a stop edge and never sleeps for a negative duration. Automatic combat remains off by default. The generic Auto Combat intro window remains a configurable 1.5s default and attacks at RU's 0.1s interval. When enabled and exact `builtin:requiem` plus `builtin:zankou_main_dps` templates are alive in the same team, Requiem keeps all resource actions and starts its configured normal-attack axis only after reaching the no-resource fallback, then requests Zankou through the planner public API. Once that axis ends, Requiem forces its one pending departure through the planner rather than being held by MainDps field time; the flag clears when the request is fulfilled or expires. After a paired Requiem free skill, the old dodge break and follow-up combo are skipped; Requiem attacks at the fixed 0.1s interval for the configured duration. A pending support ultimate then follows the ordinary support switch path; otherwise Requiem requests Zankou. Zankou main-DPS exposes one standard main-DPS ultimate action followed by its axis field action; it does not use RU Zankou's purple-icon or repeated-ultimate flow. When Zankou enters through an intro in this axis, it bypasses the generic attack-filled intro window, waits its configured silent intro duration without input, then begins with heavy attack. A normal switch does not add either intro wait. All axis normal attacks use a fixed 0.1s interval; their configured phase durations are unchanged. When `残虹强化E打断合轴` is enabled, the axis detects RU's `Labels.zankou_skill_gold` once after each heavy phase and sends a direct 0.05s E input without consulting the base skill cooldown. If the gold template remains, it repeats that input every 0.1s and confirms the cast only when the template disappears, within 0.35s or the original phase deadline. These confirmation checks run between the unchanged normal-attack ticks; a false template never blocks or extends the axis. A confirmed cast requests Requiem through the public planner API. A non-confirmed attempt makes no further E input in that heavy phase and returns to normal attacks until the original phase deadline, so it cannot prolong Zankou's field time. When `开局残虹黄E后切辅助` is enabled, the input-sensitive opening runs before RU's unconditional initial attack, first calculates the same target that the ordinary start flow would choose, temporarily switches to Zankou without the generic switch-time attack click, performs one configured heavy attack to create the yellow E, waits up to 0.4s for the template, and returns directly to that original target with the same clean-first-action rule after the bounded yellow-E attempt. If Zankou is already that ordinary target, the completed opening suppresses the regular start attack rather than repeating the start flow. It never enters Zankou's ultimate or normal axis during this insertion. Its nested `黄E入场小怪也触发` switch defaults on, so the insertion runs in Boss and small-enemy battles; off limits it to the existing top Boss-bar detection. A preemptive BuffSupport resource claim receives a ring entry only when its target is the current ring reaction target; a claim for another target is a normal entry and does not consume the pending ring entry. With `普通切人重复按技能大招` on, an explicit planned Q/E entry remains authoritative. Otherwise a ready Q is preferred before Q/E scoring and then E. A confirmed BuffSupport ultimate or skill claim now provides that expectation explicitly. After the target entry is confirmed, Q calls the character's standard `click_ultimate()` action and E calls its standard `click_skill()` action with the template's `SKILL_DOWN_TIME`; Q therefore records and waits through the same ultimate freeze as every other ultimate, while E retains the character-specific confirmation and retry behavior. For a normal entry this happens immediately; for an ordinary RU intro it replaces normal filling and then waits only for the remaining intro duration. It is off by default and does not affect the input-sensitive yellow-E opening. During a failed switch with a revive prompt, if the requested target's active portrait is already confirmed, the old active character is marked dead and the successful target is retained; the target is only marked dead when it did not enter. A newly ready support cannot interrupt Zankou's blocking heavy/normal axis; planner arbitration occurs after it completes. If a completed sound-triggered dodge interrupts either Zankou phase, Zankou completes its configured perfect/ordinary recovery, then checks an already-lit yellow E before restarting heavy. A confirmed E requests the existing planner handoff; a missing or unconfirmed E resumes the original heavy-first continuation. With the enhanced-skill switch off, E/Q test switch off, disabled or unpaired configurations retain the original Requiem double-4A and RU Zankou plan. |
| Boundary | `src/lw/zankou_main_dps.py` owns the main-DPS-only plan override and silent axis-entry wait. `src/lw/requiem_zankou_axis.py` owns pairing, settings, standalone-loop state, fixed normal cadence, enhanced-skill interruption, the bounded opening insertion, and both combat actions. `CombatExtMixin` owns the default-off ordinary-switch Q/E selection, post-entry dispatch into each character's standard Q/E action, pending intro input state, generic ready-Q preference, and revive-prompt attribution; `BaseCombatTask` and `BaseChar.wait_intro()` retain only their minimal `[lw]` connections. `CombatPlannerExtMixin` uses the existing public `BaseCombatTask.find_element_reaction_target()` to finalize whether the selected switch target receives a ring entry. `AutoCombatTask` owns the shared standard intro duration; the planner's field fallback retains only its minimal `[lw]` duration connection. Requiem reads only its own LW pending-departure state through its existing `should_force_off_field()` extension point; the public planner request lifecycle clears it. `RequiemCombatConfigTask` contains the `[lw]` input adapter, folded configuration, default-off combat switch, enhanced-skill switch, opening switch and nested battle-scope switch, free-skill duration, ordinary-switch input setting, and trigger connection. The tester always releases the attack button on interruption or exit. No planner private state is accessed. |
| Regression | `TestRequiemZankouAxis` proves default-off/original-plan behavior, exact-template pairing, preserved Requiem resource and combo-test branches, Zankou's single standard ultimate action without a purple-icon gate, fixed 0.1s axis cadence with unchanged durations, public switch requests, Requiem's pending-departure lifecycle, standalone input order, stable starter-key release, no negative tester sleep, test-only switch delay, silent custom Zankou intro wait, ordinary RU intro behavior without the axis, held-button release on the stop edge, restart after a sound-triggered dodge during either heavy or normal attacks, post-dodge yellow-E success before a heavy restart, failed post-dodge E continuation through the original complete heavy, a direct yellow enhanced-skill input with template-disappearance confirmation, repeated delayed inputs while the template is unchanged, a failed confirmation that preserves both the original axis deadline and normal-attack cadence, the bounded opening yellow-E insertion and return to the original support target without a Zankou ultimate, Boss-only suppression of that insertion, a current-Zankou opening that completes without a regular start switch, and paired free-skill follow-up behavior for both pending and absent support ultimates. `TestCombatStartSupport` proves the completed/declined opening behavior, ordinary switch Q/E selection, ready-Q preference with explicit E entry preservation, revive-prompt attribution after a confirmed target entry, default-off behavior, post-entry Q/E dispatch through the standard character methods, target long-press duration, and ordinary-intro replacement without raw input. `TestBuffSupportPlan` proves preemptive support ultimate and skill claims carry Q/E entry expectations. `TestRequiemCombatConfigTask` proves the default-off switches, folded layout, edge-trigger dispatch, input-mode-aware switch keys, removal of the normal-interval setting, enhanced-skill setting, new opening/free-skill settings, ordinary-switch input setting, and construction of the LW tester without combat state. `TestCombatPlanner` proves fallback timing uses the character entry duration, exposes the selected normal switch scoring slot without changing expected-entry behavior, and preserves a preemptive support claim's ring entry only when it matches the reaction target. |
| Manual validation | A real game window is still required to confirm the automatic planner handoff, tune the standalone-test post-switch delay and Zankou's silent intro wait, and verify both foreground/background input modes. The combat switch remains off unless the user explicitly enables it. |
| Status | superseded in part by P-05; remaining real-window timings remain user validation |

### P-03: Support skill-ready switch control

| Field | Evidence |
| --- | --- |
| Scope | This post-merge LW setting separates whether a confirmed ready support skill may initiate a switch from whether that switch receives preemptive priority. It is placed in the existing Requiem support-resource fold and defaults on to preserve current behavior. |
| RU contract | RU planner actions, scoring, field claims, and switch APIs remain unchanged. `ResourceSupportMixin` continues to declare executable support skill actions; `BuffSupport` controls only its LW claim and `priority_ready` policy. |
| Required LW behavior | When `辅助技能就绪是否切人` is on, a BuffSupport whose calculated E cooldown is ready may initiate a switch, with `辅助E是否提权` independently selecting preemptive versus ordinary priority. When off, confirmed E readiness publishes no field claim and supplies no normal switch priority. The skill remains executable when the support is already on field or arrives through another route. Support Q behavior and the existing periodic unknown-resource probe are unchanged. |
| Boundary | `ResourceSupportMixin.should_switch_for_ready_skill()` is a default-true LW policy hook. `BuffSupport` reads the configuration through its LW settings adapter and applies the hook to both action priority and ready-skill claims. No RU file or planner private state is changed. |
| Regression | `TestBuffSupportPlan` proves default behavior, disabled claim removal, disabled action priority, retained on-field executability, and that planner scoring no longer selects the support solely for a ready E. `TestRequiemCombatConfigTask` proves the default-on value and folded layout. Focused tests passed (142 tests), and the full suite passed (642 tests) on 2026-08-22. All seven PO/MO catalogs contain compiled translations for the four new or revised visible strings. |
| Manual validation | A real game window is still required to confirm the calculated-CD transition and observe that disabling the setting removes ready-E switches without affecting Q or explicit routes. |
| Status | verified; real-window scheduling remains user validation |

### P-04: LW E/Q test switch and configuration ordering

| Field | Evidence |
| --- | --- |
| Scope | This post-merge LW extension makes the existing test switch apply to every LW combat template and moves the Requiem configuration task immediately before Auto Combat in the trigger-task list. |
| RU contract | RU planner actions, resource state, and Zankou behavior remain unchanged. The switch has no effect on RU character templates. |
| Required LW behavior | The default remains off. When enabled, MainDps, Requiem, ZankouMainDps, BuffSupport, HealSupport, and SakiriBuffSupport do not execute E or Q, and resource-support templates publish no E/Q-driven resource claim or probe. Requiem still evaluates G normally. If exact paired templates have automatic combat axis enabled, Requiem uses the configured no-resource normal-attack axis and Zankou skips Q before its heavy-attack axis; neither side falls back to Requiem double-4A. Without the axis, main-DPS templates use their normal-attack field action. |
| Boundary | `LWCombatTestPolicyMixin` owns the shared configuration read in `src/lw/`. MainDps, support templates, and Zankou consume that policy through existing LW extension points. `Requiem` retains only its local action guards and no-resource field-action connection. No RU planner APIs or internal state are accessed. |
| Regression | `TestBuffSupportPlan`, `TestRequiemZankouAxis`, `TestRequiemCombatConfigTask`, and `TestCharImplDb` prove suppression of every LW template's E/Q actions, preserved Requiem G and axis behavior, default-off configuration, and the selected templates' registry contracts. The focused suites passed (63 tests), and the full suite passed (683 tests) on 2026-08-24. All seven PO/MO catalogs compile and parse without duplicate message IDs. |
| Manual validation | Restart the app to observe Requiem configuration above Auto Combat. In a real game, enable the test switch with automatic axis enabled and verify G remains available while Requiem performs configured normal attacks before switching to Zankou's heavy attack. |
| Status | verified; real-window input timing remains user validation |

### P-05: Ordinary switch Q/E planner entry dispatch

| Field | Evidence |
| --- | --- |
| Scope | Removes the stale `普通切人重复按技能大招` setting. Requiem coaxis configuration's default-off `入场提前执行技能大招` now accelerates ring-entry timing without overriding each character's declared ordinary entry order. |
| Required LW behavior | With `入场提前执行技能大招` off, ordinary switching and ring entry retain RU behavior. With it on, ordinary entry immediately runs the unchanged character entry flow; no supplemental Q-first `ExpectedEntry` is generated from ready-Q state or switch scoring. A ring entry runs `1.0s` of its existing intro wait and then calls `CombatPlanner.perform_entry_lead_action()`. An explicit route or claim `ExpectedEntry` remains authoritative. Without one, planner advances the real entry flow through failed Q/E attempts and pauses after the first successful Q/E, then resumes the same saved entry session after the remaining intro time. Generator pre-yield side effects run once, `E -> Q` and `Q -> E` declarations retain their order, and both actions continue to use the character's standard execution helpers. No switch-loop code sends Q or E directly. |
| Boundary | `CombatExtMixin` only reads the default-off configuration. `BaseCombatTask.switch_next_char()` registers only an explicit decision `ExpectedEntry`. `CombatPlanner.perform_entry_lead_action()` owns order-preserving pre-intro execution and retained entry-session state; `BaseChar.perform()` calls it only when the setting is on and otherwise preserves RU's `wait_intro()` call. No raw input helper, ordinary-switch selector, pending input alias, or second feature switch remains. |
| Regression | `TestCombatStartSupport` proves the `1.0s` ring delay calls the order-preserving lead API, disabled mode keeps RU wait behavior, and ordinary switching no longer registers a supplemental expected action while explicit route expectations remain intact. `TestCombatPlanner` proves `E -> Q`, `Q -> E`, one-time generator setup, and explicit `ExpectedEntry` precedence across the retained entry session. |
| Manual validation | With the setting on, let Iroi enter with both E and Q ready and confirm E executes before Q on both its first ordinary entry and later ring entries. Confirm a Q-first support still uses Q before E. With Zankou main-DPS Q unavailable, confirm the intro lead does not execute its coordinated-axis heavy before the character-specific intro wait ends. |
| Status | pending real-window verification |

### P-06: Requiem real-skill configured handoff boundary

| Field | Evidence |
| --- | --- |
| Scope | Replaces the boolean `安魂曲真技能后切残虹` with the default-off `安魂曲真技能后固定切人位置` dropdown: `关闭`, `1`, `2`, `3`, or `4`. |
| Required LW behavior | After Requiem confirms its real skill entered long CD, a configured live target slot receives a strict planner handoff. If it is the paired Zankou main-DPS, the existing optional Q then coordinated-axis route remains unchanged. Any other selected slot receives a strict pure-switch route: the route completes on confirmed entry and the target immediately uses its own normal planner action flow. A Requiem real skill pre-executed at entry must end Requiem's ordinary entry before it can emit a follow-up Q or coaxis field action; the existing switch path then selects the strict target or, with `关闭`, the ordinary planner target. A BuffSupport target with neither Q nor E available must not use generic field-time normal attacks; it immediately yields to the next planner decision. Requiem is unavailable as a planner switch target only through its existing `3.0s` real-skill off-field window. While either strict route is switching, a newly detected element ring cannot replan the still-unconfirmed target. A selected missing, dead, or current Requiem slot publishes no route. With `关闭`, the prior Requiem path remains unchanged. |
| Boundary | `Requiem` owns confirmation of its existing long-CD skill and publishes only the public `CombatContext.request_route()` request. `FollowupStep.for_switch()` is the generic public planner primitive for a strict route that completes on actual entry without requiring an action; it does not send input. `src/lw/requiem_zankou_axis.py` owns coaxis settings and timing. The one minimal `[lw]` connection in `CombatPlanner._can_switch_to()` delegates to `CombatPlannerExtMixin.lw_can_switch_to()`, which reads an optional character `lw_can_switch_in()` hook; it never emits raw switch input. |
| Regression | `TestRequiemCombatConfigTask` verifies dropdown default and options. `TestRequiemZankouAxis` verifies the existing strict Zankou Q-to-axis route and a configured non-Zankou pure switch. `TestCombatPlanner` verifies a pure-switch strict route selects the target without an expected action and completes exactly on `record_switch()`. `TestCombatStartSupport` verifies a strict route disables pending-switch ring replanning. Existing Requiem-skill regression coverage verifies long-CD confirmation still controls the `3.0s` overlap window. |
| Manual validation | Set the dropdown to the slot containing Zankou main-DPS: after `requiem REAL skill fixed handoff to zankou`, verify its Q-if-ready then heavy-attack flow. Set it to a support slot: verify the log reports `fixed handoff to slot N`, the switch completes without a forced Zankou action, and that support starts its ordinary planner flow. |
| Status | pending real-window verification |

### P-07: Zankou coordinated-axis entry-action boundary

| Field | Evidence |
| --- | --- |
| Scope | Keeps `builtin:zankou_main_dps` inside the order-preserving `入场提前执行技能大招` flow without a character-ID special case. |
| Required LW behavior | Zankou main-DPS declares Q before its coordinated-axis action. When Q is available, the ring-entry lead executes the standard Q action. When Q is unavailable, planner advances past that failed action but stops before the non-Q/E coordinated-axis action; the heavy phase still begins only after the remaining character-specific intro wait. Its yellow E remains exclusively inside the coordinated-axis detection and confirmation path. |
| Boundary | The generic planner lead API filters by action slot and preserves the live entry session. `CombatExtMixin` no longer imports or identifies the Zankou main-DPS implementation for ordinary-switch Q/E selection. No raw input or duplicate Zankou action declaration is introduced. |
| Regression | `TestCombatPlanner` covers stopping before a non-Q/E follow-up after an unavailable lead ability; Zankou axis tests retain the character-specific silent intro and heavy-phase behavior. |
| Manual validation | Enable entry ability input and let Requiem finish a normal coaxis phase while Zankou Q is unavailable. Confirm no synthetic E expectation appears and the coordinated-axis heavy begins only after the configured silent intro wait. |
| Status | pending real-window verification |

### P-08: Zankou yellow-E opening intro and handoff boundary

| Field | Evidence |
| --- | --- |
| Scope | Corrects the optional Zankou yellow-E combat opening when Zankou is the actual ring-entry target or is already the current character. This supersedes P-02's earlier current-Zankou no-switch regression statement. |
| Required LW behavior | Before switching to Zankou, the opening checks both current ring availability and the actual reaction target. A matching Zankou entry keeps `has_intro=True`, records the existing intro freeze, and consumes the configured Zankou silent intro duration before the heavy attack; a non-matching switch remains an ordinary entry with no added wait. After the bounded yellow-E attempt, the opening always leaves Zankou and recalculates whether that actual handoff target receives the current ring entry. It returns to the precomputed ordinary opening target when that target is another character; when Zankou was already the target, planner selection chooses the handoff, with the paired live Requiem as the safe fallback. The completed yellow E can therefore never flow directly into Zankou's ultimate. |
| Boundary | The opening remains entirely in `src/lw/requiem_zankou_axis.py`; its visible configuration description is updated in `RequiemCombatConfigTask`. It reuses `CombatPlannerExtMixin.lw_switch_target_has_intro()`, Zankou's existing `wait_intro()` override, the standard freeze recorder, planner `decide_switch()`, and the existing `_switch_to_char()` entry. No RU action implementation or raw Q/E input is added. |
| Regression | `TestRequiemZankouAxis` proves a matching ring target switches with `has_intro=True`, records and waits the configured `1.25s` silently before heavy attack, clears the consumed intro, keeps a full ring for another target from adding a false Zankou wait, preserves ordinary no-intro insertion, and falls back from a current Zankou to its paired Requiem instead of leaving it on field for Q. |
| Manual validation | Start combat once with a full ring whose actual reaction target is Zankou and confirm the log shows the configured silent intro wait before the opening heavy attack. Start once while Zankou is already current and no support resource is ready; confirm yellow E is followed by a switch to Requiem or another planner-selected teammate, with no Zankou ultimate between them. |
| Status | pending real-window verification |

### P-09: Combat-opening roster reload recovery

| Field | Evidence |
| --- | --- |
| Scope | Prevents a confirmed team-roster correction during the one-shot combat opening from terminating Auto Combat or replaying the Zankou yellow-E opening. |
| Required LW behavior | A portrait lookup miss creates `BaseChar(char_id="unknown", char_name="default")`; that placeholder cannot expand an authoritative initial team snapshot, while a recognized character with a real portrait ID but no configured implementation remains a valid generic `BaseChar` and may expand it. Slots already included by the authoritative team snapshot remain loaded even when their portraits are unknown. The one-shot combat opening completes before `team_reload_watch()` enables roster-change signals. The first guarded combat-loop check then confirms and reloads any real roster correction through the existing recovery path. Every team reload resumes through the ordinary start selector with the one-shot LW opening explicitly marked checked, so yellow E is not replayed. |
| Boundary | Unknown-character classification, Auto Combat reload handling, and the one-shot-opening skip remain in `src/lw/combat_ext.py`. RU `CombatSession`, `BaseCombatTask.begin_combat_session()`, character actions, and planner APIs are unchanged. |
| Regression | `TestTeamChangeCheck` distinguishes an unmatched default placeholder from a recognized but unconfigured generic character during initial snapshot expansion. `TestUseUltimateConfig` proves the reload monitor starts only after the one-shot opening, normal action-time reload still works, cleanup still runs, and `_reload_combat_team()` skips the one-shot opening. |
| Manual validation | Start the two-character Requiem/Zankou team with yellow-E opening enabled and confirm no `initial snapshot expanded ... 2 -> 4` appears from default slots. If a roster correction is logged during opening, Auto Combat must remain enabled and yellow E must occur at most once. Load a real three- or four-character team containing a recognized portrait with no implementation and confirm the slot remains visible as `BaseChar`. |
| Status | pending real-window verification |

### P-10: Sound-dodge outcome confirmation boundary

| Field | Evidence |
| --- | --- |
| Scope | Replaces the LW behavior that started a character counter sequence immediately after dodge input with a shared two-stage sound outcome, and routes a manually produced perfect-dodge sound into the same character follow-up without sending another input. The Requiem coordinated-axis fold contains a default `0.5s` ordinary-dodge confirmation wait for non-Requiem characters, followed immediately by an independent default `0.5s` Requiem-main-DPS wait; the old Sound Trigger Config field and double-4A-only override are removed. |
| Required LW behavior | The attack cue still runs RU's ordinary dodge input. The configured outcome window begins at the first Shift input, not at attack-cue detection or action dispatch. Shift and audio observations use the same high-resolution monotonic clock, so a perfect-dodge sound a few milliseconds later remains distinguishable from a pre-Shift match. Counter-sample matches before that Shift cannot confirm the current dodge. A score above `Counter Attack Threshold` after Shift confirms a perfect dodge and immediately publishes `perfect_dodge=True`; its follow-up timing anchor is the confirmed perfect-dodge sound itself for both automatic and manual perfect dodges. The current character is resolved after Shift while combat input is paused. Requiem main DPS uses `安魂曲普通闪避等待(s)` and falls back to its own `0.5s` default when that field is absent; every other character uses `普通闪避等待(s)`. Timeout at exactly `first Shift + selected wait` publishes `False`, and both settings are read live. Every resolved path writes one explicit file-log marker: `声音闪避结果: 自动完美`, `声音闪避结果: 普通闪避`, or `声音闪避结果: 手动完美`; the automatic marker retains `after_shift` and score details. Auto Combat also owns a persistent `闪避情况` status row immediately below its replaceable `Log` row. It resets to `等待触发` at each combat start and shows the latest of the same three results before any character follow-up begins, so unrelated combat logs cannot overwrite it; an in-combat team reload preserves the current result. A perfect-dodge sound with no automatic confirmation in progress is treated as a manual perfect dodge: it records `last_dodge_time`, publishes the same `perfect_dodge=True` result, and sends no Shift or attack of its own. Requiem perfect dodges start its configured double-4A counter follow-up from the confirmed sound. During an enabled Requiem/Zankou axis, that follow-up interrupts any remaining ordinary or free-skill Requiem axis normals, completes both double-4A segments before leaving, publishes a successful planner action, and immediately requests the normal axis handoff; it cannot fall through to MainDps field-time attacks or defer the continuation until a later Requiem entry. Requiem ordinary dodges make no attack during their dedicated wait. With coordinated axis enabled, timeout discards the pre-dodge axis deadline and starts a new full `安魂曲普攻时长(s)` plain-normal phase at `0.1s` cadence; a later ordinary dodge restarts that full phase again, while a perfect dodge replaces it with double-4A. If an ordinary dodge interrupts an active double-4A, the interrupted sequence is not reported as complete and does not request an immediate switch; it transitions to the same new full plain-normal phase. Outside coordinated axis, ordinary timeout starts the configured combo. An unconsumed restart is cleared when Requiem leaves the field. Zankou's coordinated-axis heavy is sound-interruptible: automatic handling releases the held mouse before Shift, manual-perfect handling releases it before follow-up dispatch, and the old heavy phase ends as soon as the resolved outcome is observed instead of consuming its original remaining duration. Zankou's existing `残虹声音闪避后普攻时长(s)` is perfect-only: from the confirmed sound it sends exactly two normal attacks at the shared `0.1s` cadence, waits without input for the remainder of that recovery duration, keeps at least one `0.1s` separation after the second click, then starts a complete new heavy-attack axis before its normal phase and planner handoff. Zankou ordinary dodges make no recovery normal attack and restart a complete heavy as soon as the global Shift-based wait has expired. Other characters simply resume planner-controlled normal combat after the same global ordinary wait. One acoustic event is consumed once across both the raw observer and RU callback; the latch resets only after two consecutive below-threshold observations, preventing an overlapping `0.2s` match window from starting or interrupting the follow-up twice. Task changes, context exit, and failed dodge input cancel the pending result. |
| Boundary | The confirmation state machine, raw-score observer, Shift-relative timeout, outcome dispatch and disabled-by-default bounded diagnostic sampler live in `src/lw/sound_ext.py`. The producer-side chunk observer lives in `src/lw/sound_capture_ext.py`; `AudioCaptureSource` invokes it before RU's latest-only queue can discard backlog. `SoundListener` binds that observer before capture starts and matches only the newest continuous `0.2s` producer window, so recognition remains low latency. `SoundCombatContext`, `DodgeCounterTrigger`, and `BaseCombatTask` retain minimal `[lw]` connections. `counter.wav` is a mono 48 kHz, `0.025s` template made by aligning and averaging the common post-Shift core from five user-confirmed perfect dodges; their observed starts were `0.246s`, `0.365s`, `0.252s`, `0.463s`, and `0.246s`. The raw local recordings remain ignored and are not committed. Post-dodge WAV capture remains available only for explicit diagnostics and is off during normal combat. No visual detector, microphone capture, or second audio source is introduced. |
| Regression | `test_sound_trigger_capture` proves the producer observer receives every pushed chunk before queue backlog is discarded and the committed counter template cannot exceed the listener's `0.2s` matching window. `test_sound_dodge_confirmation` proves continuous latest-window assembly, one-second capture without timestamp-jitter holes, Shift-before rejection, immediate Shift-after confirmation, non-Requiem use of the global ordinary deadline, Requiem use and independent fallback of its dedicated deadline, perfect-sound timing anchors, confirmation while action arbitration is busy, bounded retention, result-specific character dispatch, automatic pre-Shift and manual-perfect character preparation, manual-perfect dispatch without extra input, one action per acoustic event with a two-frame quiet reset, the three stable outcome markers, Requiem's non-axis ordinary combo and coaxis full plain-normal restart handoffs, switch-out cleanup, and propagation of the exact result to Auto Combat. `TestRequiemCombatConfigTask` proves both waits default to `0.5s`, appear consecutively after Zankou's perfect-recovery setting in the coordinated-axis fold, and remain absent from the double-4A style. `TestRequiemZankouAxis` proves ordinary and free-skill Requiem axes discard their old deadline and run a full standard normal phase after ordinary dodge, a double-4A interrupted by ordinary dodge transitions to that phase without publishing perfect completion, and both Requiem axis variants still finish double-4A before requesting handoff when perfect dodge wins. It also proves a Zankou heavy-phase dodge shortens the old hold, releases its input, sends exactly two perfect-recovery normals, preserves at least a `0.1s` post-click gap even when the configured window is shorter, starts a complete replacement heavy before normal attacks and switching, and sends no recovery normal for an ordinary dodge. `TestCombatExtensionHooks` proves the persistent status row is inserted directly after `Log` and updated for ordinary and perfect results. Offline validation against the five confirmed continuous samples exceeded the `0.12` threshold before the `0.5s` deadline for every simulated `25ms` listener phase; a likely ordinary-dodge sample peaked at `0.046`, while `dodge.wav` peaked at `0.028`. |
| Manual validation | Fight a boss with Requiem and compare `声音闪避结果: 自动完美 ... after_shift=...`, `声音闪避结果: 普通闪避`, and `声音闪避结果: 手动完美` in the file log. Set visibly different values for `普通闪避等待(s)` and the following `安魂曲普通闪避等待(s)`: the ordinary marker's `waited=` value must follow the dedicated field on Requiem and the global field on Zankou or another character. Confirm the Auto Combat status table keeps a separate `闪避情况` row directly under `Log` and updates it to the same latest result without being replaced by CD diagnostics. Confirm automatic and manual perfect dodges each start exactly one full configured Requiem double-4A follow-up from the confirmed sound; while coordinated axis is enabled, its continuation must finish immediately, log `requiem perfect-dodge double-4a complete`, and switch without another combo or axis-normal phase, including when the perfect dodge interrupts free-skill axis normals. Ordinary Requiem makes no attack during its dedicated wait; with axis enabled, the next log must state `requiem ordinary dodge starts full coordinated-axis normals`, followed by one complete configured-duration `0.1s` plain-normal phase before switching, even when the ordinary result arrives after the old axis deadline. If ordinary dodge interrupts double-4A, the log must state `double-4a interrupted by ordinary dodge`, must not state perfect completion, and must run that same full plain-normal phase. Outside the axis, ordinary Requiem enters the configured combo. With Zankou on field, confirm a perfect dodge sends exactly two normal attacks, remains idle for any configured remainder, and restarts heavy; an ordinary dodge remains idle until the global wait expires and then restarts heavy without a normal attack. The current sample set includes one feedback onset at `0.463s`, so retain a sufficient Shift-relative ordinary wait and use `after_shift` to monitor its real timing margin. |
| Status | pending real-window sample verification |

### P-11: Awakened Zankou double-ultimate coaxis entry

| Field | Evidence |
| --- | --- |
| Scope | Extends only the enabled Requiem/Zankou main-DPS coordinated-axis entry. It preserves the disabled/unpaired RU path. |
| Required LW behavior | Zankou main-DPS always runs its first Q through the standard `click_ultimate()` action. After a successful first Q, it polls the generic current-character `ultimate_available()` state for at most `0.8s` at a `0.1s` cadence. If a second Q becomes available, it immediately repeats the same standard Q action; both Q stages finish before the heavy/yellow-E axis begins. The coaxis path does not use RU's `zankou_ult_purple` template as a pre-Q gate: that template is required by RU's skill/heavy prelude, but is unstable for the awakened direct-double-Q flow and must not cause an available second Q to be skipped. Both Q stages retain the common animation, cooldown, and freeze lifecycle, but Zankou main-DPS disables the common unfreeze-period normal-attack filler so queued clicks cannot contaminate the following Q or heavy input. A failed first Q or a missing second-stage window continues the original axis without an unbounded wait. The test-only E/Q disable setting skips both Q actions and the second-Q poll. |
| Boundary | `src/lw/zankou_main_dps.py` owns the Zankou-main-DPS-only bounded second-Q wait and the silent-unfreeze override. RU `src/char/Zankou.py`, `BaseChar`, detector labels/assets, and planner APIs are unchanged. Both Q inputs delegate to the executor produced by the standard `click_ultimate_action()` helper; no raw Q input is introduced. RU's skill/heavy prelude and purple-E flow are not restored. |
| Regression | `TestRequiemZankouAxis` separately creates the expected-action plan and entry plan to prove a successful first Q is carried through the real cross-snapshot boundary, then drives the same standard Q action a second time before axis entry. It proves a false RU purple detector cannot gate this path, both Q stages call the existing unfreeze implementation with normal filling disabled, failed first stages do not wait, missing second stages continue the axis, polling is bounded to `0.8s` with at most `0.1s` sleeps, the test-only E/Q disable switch bypasses Q actions, and disabling coordinated axis still delegates to RU Zankou. |
| Manual validation | With awakened Zankou and coordinated axis enabled, every successful first Q must log `zankou first ultimate complete; checking awakened second`; a ready second Q must then log `zankou awakened second ultimate available` and complete before the heavy/yellow-E axis. No normal attack should occur between the Q stages or between the second Q and held heavy input. If the second Q is not ready, the log must state `unavailable; continuing axis` after no more than `0.8s`. Image detection and real animation timing still require a live game window. |
| Status | pending real-window verification |

### P-12: Requiem real-skill sound-dodge departure guard

| Field | Evidence |
| --- | --- |
| Scope | Changes only automatic sound-triggered dodge while Requiem is casting a real skill or waiting to leave after that real skill. Free skill, ordinary field time, other characters, and planner switching remain unchanged. |
| Required LW behavior | After Requiem's real-skill engage attack and immediately before the real-skill action starts, it blocks automatic sound dodge. A queued attack sound resolved during this state sends no Shift, starts no perfect-dodge confirmation, publishes no ordinary/perfect outcome, and triggers no character dodge follow-up. If the skill ultimately fails to enter long cooldown, the block clears immediately. If it succeeds, the block remains until Requiem actually receives `switch_out()`, then clears. Combat reset also clears it. The block does not attempt to prevent a player's manual keyboard input. |
| Boundary | Requiem owns one LW departure flag and exposes a reason through `lw_sound_dodge_block_reason()`. `SoundContextExtMixin` reads that optional character policy before creating an automatic dodge-confirmation attempt. RU `DodgeCounterTrigger`, `SoundCombatContext`, planner APIs, and generic Q/E behavior are unchanged. |
| Regression | `TestRequiemSkill` proves the flag is active when the real-skill helper runs, remains active after a confirmed cast, clears on actual switch-out, and clears immediately after a failed cast. `test_sound_dodge_confirmation` proves a blocked automatic event sends no dodge input and creates no confirmation state. The focused Requiem/sound/axis suites passed 95 tests and the full suite passed 783 tests on 2026-08-30. |
| Manual validation | Trigger a Boss attack sound from the start of Requiem's real-skill cast until its switch completes. The log may contain `声音闪避跳过: requiem real skill waiting for off-field switch`, but must contain no intervening `Dodge sequence: Left Shift` or dodge outcome for that event. After Requiem leaves, later attack sounds must dodge normally. |
| Status | pending real-window verification |

### P-13: Cross-combat and continuous Abyss roster replacement

| Field | Evidence |
| --- | --- |
| Scope | Changes only Auto Combat roster recognition and confirmed roster reload. Character actions, planner scoring, fixed-team slots, combat detection, and scripted `combat_once` tasks keep their existing behavior. |
| Required LW behavior | A combat entered after a real out-of-combat boundary must identify every slot against the full saved portrait library instead of testing the previous combat's same-slot character first. If an Abyss half changes directly while combat remains active, the between-action roster check must also compare every slot against the full library. A same-size replacement requires two identical observations at least `0.5s` apart. The confirming observation carries the recognized character objects and current slot into the reload signal, so the old planner is atomically replaced without a third recognition pass. An unmatched companion slot becomes generic `BaseChar` when at least one other slot positively identifies a new character. A frame in which every slot is unknown cannot replace a valid roster, protecting long ultimate effects. |
| Boundary | `src/lw/combat_ext.py` owns the full-scan policy, confirmation snapshot, and direct commit. `src/lw/team_roster.py` carries the immutable confirmed snapshot. RU `BaseCombatTask` retains one optional `[lw]` roster-load parameter and passes `None` as the previous character during a forced scan; `CharFactory` remains unchanged and its default fast path remains available. Signature scans run between `perform()` calls, never inside an active combo/Q poll. |
| Regression | `TestTeamChangeCheck` proves a new combat bypasses the old-slot probe, an unchanged full scan stays stable, same-size replacements require confirmation and carry the new roster, confirmed snapshots commit without a third scan, one positively identified replacement can carry an unknown companion, all-unknown effect frames cannot replace the team, and the normal same-combat load retains the fast path. `TestUseUltimateConfig` proves size-change reload still flows through the same consumer and skips one-shot opening behavior. |
| Manual validation | In a two-team Abyss stage, test both transitions: an upper half that visibly leaves combat before the lower half, and an upper kill that enters the lower fight without a detected combat gap. The first lower-team log must contain the actual lower roster, and a continuous transition must log one candidate followed by `commit confirmed team signature without another recognition pass`. It must not run another `load_chars` scan after confirmation, repeat switches using the upper planner, or replace the team during a long Q effect. |
| Status | pending real-window verification |

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
| Zankou main-DPS template and coordinated-axis integration | `src/char/Requiem.py`, `src/lw/chars.py`, `src/lw/zankou_main_dps.py`, `src/lw/requiem_zankou_axis.py`, `src/tasks/trigger/RequiemCombatConfigTask.py`, `i18n/*/LC_MESSAGES/ok.po`, `i18n/*/LC_MESSAGES/ok.mo` | Keep RU Zankou and planner unchanged; keep the single Requiem `[lw]` connection minimal; isolate pairing, timing, actions, and test loop in `src/lw/`; prove default-off/original behavior, exact-template gating, switch requests, input release, registry/config contracts, and awakened double-Q completion before axis handoff | pending real-window verification; see P-02 and P-11 |
| Requiem real-skill sound-dodge departure guard | `src/char/Requiem.py`, `src/lw/sound_ext.py` | Suppress only automatic sound dodge from real-skill cast commitment through actual switch-out; keep free-skill, other-character, manual-input, and planner behavior unchanged | pending real-window verification; see P-12 |
| Cross-combat and continuous Abyss roster replacement | `src/combat/BaseCombatTask.py`, `src/lw/combat_ext.py`, `src/lw/team_roster.py` | Bypass prior-slot bias on a fresh combat, detect same-size replacements with confirmed full-library scans between actions, and atomically commit the confirming snapshot without a third scan | pending real-window verification; see P-13 |
| Support skill-ready switch control | `src/lw/resource_support.py`, `src/lw/combat_templates.py`, `src/tasks/trigger/RequiemCombatConfigTask.py`, `i18n/*/LC_MESSAGES/ok.po`, `i18n/*/LC_MESSAGES/ok.mo` | Keep RU planner unchanged; gate both ready-skill claims and action priority while preserving action executability, Q behavior, and periodic resource probes | verified; see P-03 |
| LW E/Q test switch and configuration ordering | `src/char/Requiem.py`, `src/config.py`, `src/lw/combat_test_policy.py`, `src/lw/combat_templates.py`, `src/lw/resource_support.py`, `src/lw/zankou_main_dps.py`, `src/tasks/trigger/RequiemCombatConfigTask.py`, `i18n/*/LC_MESSAGES/ok.po`, `i18n/*/LC_MESSAGES/ok.mo` | Keep the policy in `src/lw/`; preserve G and automatic axis behavior while suppressing only E/Q; keep the Requiem task before Auto Combat; prove every LW template contract | verified; see P-04 |
| Interface-break repair | `src/lw/combat_ext.py`, `src/lw/fish_catch_ext.py` | Keep I-01 and I-02 regression coverage during later migration work | verified |

## Required evidence before closure

- For each matrix row, record the exact RU contract change and each LW call site.
- Record the migration commit and the tests that fail without that migration.
- Run the relevant focused tests and the full unittest suite after the final row.
- Check the final diff for LW boundary violations and synchronise any shared
  `AGENTS.md`/`CLAUDE.md` convention changes.
- Leave no `pending` row. If an item cannot be proven, retain `pending` and
  report the sync as incomplete.
