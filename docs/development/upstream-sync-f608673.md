# Upstream Sync Ledger: f608673

## Status

**In progress.** This ledger is the durable state for this upstream sync. Do not
describe the sync as complete until every row in the acceptance matrix is marked
`verified` or an explicit user-approved exception is recorded here.

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
| Status | in progress; detailed records below |

| ID | Local-only paths modified by `M` | Old local contract | Current RU contract and migration | Regression | Commit | Status |
| --- | --- | --- | --- | --- | --- | --- |
| M-01a | `CLAUDE.md` | Full LW/RU merge instructions were local-only. | The merge incorrectly compressed it; A-01 restores every behavior-affecting rule to `AGENTS.md` and leaves `CLAUDE.md` as its pointer. | Four-tree audit and A-01 review. | `11e71e1`, `6818c49` | verified |
| M-01b | `src/char/Requiem.py`, `src/lw/chars.py` | `lw_char_dict` extended the deleted old `CharFactory.char_dict`; Requiem depended on that explicit Chinese display name. | Register the same implementation IDs with the RU `CharRegistry`; `Requiem.cn_name` keeps automatic built-in discovery and explicit registration consistent. | `TestCharImplDb` resolves `builtin:requiem` after registry scanning and checks its class and Chinese name. | `6818c49` | verified |
| M-01c | `src/lw/combat_ext.py`, `tests/TestCombatSurvivalStatus.py`, `tests/TestUseUltimateConfig.py` | LW combat loop set direct task fields and started combat through the old start-switch path. | Use RU `CombatSession`, `begin_combat_session()`, and current public character snapshot. I-01 repaired the stale private lookup after this migration. | `TestUseUltimateConfig`, `TestCombatSurvivalStatus`, `TestTeamChangeCheck`, and `TestCD` cover the current session, reload, and CD contracts. | `f608673`, `ad031e6`, `6818c49` | in progress; full character/combat caller audit remains |
| M-01d | `src/lw/dsd_farm_ext.py`, `tests/test_dsd_farm_recovery.py` | LW had `lw_refresh_monsters()` to click the post-refresh confirmation dialog. | RU now owns `DSDFarmTask.refresh_monster()` and calls public `wait_click_confirm()` with the no-remind callback. The old LW duplicate was correctly retired. | `test_dsd_farm_recovery` covers the changed and unchanged branches; `test_find_confirm` exercises the current confirmation click contract. | `6818c49`, `c9b004e` | verified |
| M-01e | `src/lw/nte_task_ext.py` | `lw_find_confirm()` did not accept the new image mask parameter. | It forwards `mask_function` to both template searches; `BaseNTETask.find_confirm()` supplies the RU `confirm_mask`. | `test_find_confirm` verifies both forwarding and the confirmation click lifecycle. | `6818c49`, `c9b004e` | verified |

## Shared-path acceptance matrix

Each group below expands to the named shared paths. Every group is `pending`
until the individual contracts and regression evidence are added below it.

| Group | Shared paths | Required audit | Status |
| --- | --- | --- | --- |
| Agent contracts | `AGENTS.md`, `CLAUDE.md` | Compare all shared LW/RU rules and record any mismatch | verified; see A-01 |
| Planner documentation | `docs/development/combat-planner.md` | Check changed planner APIs, examples, and associated tests | pending |
| Localization | 13 `i18n/*/LC_MESSAGES/ok.po` or `ok.mo` paths | Verify no LW-visible strings were lost and generated catalogs match sources | pending |
| Bootstrap and dependencies | `main.py`, `main_debug.py`, `pyproject.toml`, `uv.lock` | Verify startup and dependency contract changes against LW initialization | pending |
| Character core | `src/char/BaseChar.py`, `Hotori.py`, `Nanally.py`, `Requiem.py`, `core/CharFactory.py`, `core/CharRegistry.py`, `custom/CustomCharDbMigrator.py` | Map character lifecycle, role registration, custom-character schema, and all LW callers | pending |
| Combat core | `src/combat/BaseCombatTask.py`, `planner/core.py`, `planner/types.py` | Map session lifecycle, planner action/result contracts, interrupt and team-reload behavior | pending |
| Runtime infrastructure | `src/config.py`, `src/globals.py`, `src/interaction/NTEInteraction.py` | Check registration, global lifecycle, interaction semantics, and LW connections | pending |
| LW layer | `src/lw/chars.py`, `combat_ext.py`, `dsd_farm_ext.py`, `nte_task_ext.py` | Reapply each required LW behavior on current RU public APIs; no stale private calls or dual paths | pending; I-01 is verified only |
| Tasks and mixins | `src/tasks/AnomalyTask.py`, `BaseNTETask.py`, `DSDFarmTask.py`, `DailyTask.py`, `daily/DailyRoutineTask.py`, `mixin/CharUIMixin.py` | Trace task lifecycle and each `[lw]` hook across changed RU contracts | pending |
| Regression suite | `TestCharImplDb.py`, `TestCombatPlanner.py`, `TestCombatSurvivalStatus.py`, `TestDailyCoffee.py`, `TestUseUltimateConfig.py`, `test_dsd_farm_recovery.py` | Remove obsolete mocks, prove current contracts and preserve LW results | pending |

## Post-merge changes requiring boundary audit

These changes were added after `f608673`; they do not close the upstream-sync
matrix and must themselves obey the LW/RU boundary before the ledger can close.

| Change | Files | Required action | Status |
| --- | --- | --- | --- |
| Account-aware daily summary and retry | `src/lw/daily_routine_ext.py`, `src/tasks/daily/DailyRoutineTask.py`, `src/tasks/daily/FurnitureTask.py`, `src/ui/DailyRoutineTab.py` | Move remaining daily-specific behavior behind `src/lw/` adapters or mark minimal RU connection points with `[lw]`; retain current tests | pending |
| Interface-break repair | `src/lw/combat_ext.py`, `src/lw/fish_catch_ext.py` | Keep I-01 and I-02 regression coverage during later migration work | verified |

## Required evidence before closure

- For each matrix row, record the exact RU contract change and each LW call site.
- Record the migration commit and the tests that fail without that migration.
- Run the relevant focused tests and the full unittest suite after the final row.
- Check the final diff for LW boundary violations and synchronise any shared
  `AGENTS.md`/`CLAUDE.md` convention changes.
- Leave no `pending` row. If an item cannot be proven, retain `pending` and
  report the sync as incomplete.
