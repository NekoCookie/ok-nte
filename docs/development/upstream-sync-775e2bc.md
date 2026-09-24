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
| Merge result `M` | `<pending>` |
| Audit command | `.\\.venv\\Scripts\\python.exe tools\\audit_merge_provenance.py <M>` |
| Audit result | `<pending>` |
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
| I-01 | `<pending>` | `<pending>` | `<pending>` | `<pending>` | `<pending>` | open |

## Verification evidence

| ID | Behavior rows | Command or scenario | Evidence | Result | Status |
| --- | --- | --- | --- | --- | --- |
| V-01 | B-01 to B-07 | Focused tests for changed scene, gift, abyss, task, planner, character, sound, and resource paths | `<pending>` | `<pending>` | open |
| V-02 | B-01 to B-07 | `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -p "*.py"` | `<pending>` | `<pending>` | open |
| V-03 | B-01 to B-07 | `git diff --check`, changed-file `py_compile`, stale API scan, provenance audit | `<pending>` | `<pending>` | open |
| V-04 | B-01, B-02, B-03, B-05 | De-identified real-window smoke scenarios | `<pending>` | `<pending>` | open |

## Closure gate

- Four-tree provenance audit is attached and all local merge decisions are classified.
- Every behavior row has a current-API regression or documented real-window limitation.
- Every affected LW caller has a contract-migration row.
- No stale API, copied RU implementation, compatibility alias, or A/B path remains.
- Focused tests, full tests, syntax checks, and `git diff --check` pass.
- Real-window rows are recorded as pass or explicitly blocked with evidence.
- Sync status remains `open` until every required row is verified.
