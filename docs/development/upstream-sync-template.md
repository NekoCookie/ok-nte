# Upstream Sync Ledger Template

Copy this file to `upstream-sync-<merge>.md` before a large RU sync. A sync is not
complete until every behavior row is `verified`; a green full suite alone is not a
completion signal. Each new upstream parent `U` requires a new copy of this
ledger. A completed ledger is immutable evidence for its recorded `B/L/U/M`
scope; it is not a completion certificate for later upstream commits. If the
ledger is created after a merge, label additions as corrective records and do
not treat them as a substitute for the pre-merge behavior manifest.

## Scope and provenance

| Field | Value |
| --- | --- |
| Merge base `B` | `<sha>` |
| Local parent `L` | `<sha>` |
| Upstream parent `U` | `<sha>` |
| Merge result `M` | `<sha>` |
| Audit command | `python tools/audit_merge_provenance.py <M>` |
| Audit result | `<summary and retained output location>` |
| Sync status | `open` |

Record whether every apparent removal is an actual RU removal from `B`, or a local
merge decision. Do not call a local-only path an upstream deletion.

## Pre-merge behavior manifest

Create these rows before resolving conflicts. Describe the user-visible result,
not the old code shape.

| ID | LW behavior | Trigger and input | Required result or timing | Required state and side effects | Automated regression | Real-window scenario | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B-01 | `<name>` | `<event>` | `<observable result and threshold>` | `<state, input, persistence>` | `<test>` | `<scenario or N/A>` | `open` |

For a character action that hands off to planner, include all of these in the row:

- What makes the action successful.
- The exact action result expected by the planner.
- What must happen next, such as switch, route, cooldown, or no fallback action.
- What must not happen, such as a duplicate input, stale retry, or extra field-time action.

## RU-to-LW contract migration matrix

Complete one row for every affected LW call site, including `[lw]` connections.

| ID | RU change | Local caller | Old contract | New contract | LW migration on current RU base | Regression | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C-01 | `<interface or lifecycle change>` | `<path:symbol>` | `<args, return, error, state>` | `<args, return, error, state>` | `<new implementation>` | `<test>` | `open` |

For action, callback, hook, and planner integrations, `Old contract` and `New
contract` must explicitly include return value meaning, consumed side effects, and
the next control-flow step. A state field being set is not proof that its consumer
will act on it.

## Implementation decisions

| ID | Changed path | RU baseline retained | LW behavior re-expressed | Why no duplicate path remains | Commit | Status |
| --- | --- | --- | --- | --- | --- | --- |
| I-01 | `<path>` | `<current RU behavior>` | `<LW adapter or hook>` | `<single production path>` | `<sha>` | `open` |

Place new LW logic in `src/lw/` where possible. A direct RU edit must be a minimal
`[lw]` connection, not a copied old implementation.

## Verification evidence

| ID | Behavior rows | Command or scenario | Evidence | Result | Status |
| --- | --- | --- | --- | --- | --- |
| V-01 | `<IDs>` | `<focused unit command>` | `<test count or assertion>` | `<pass/fail>` | `open` |
| V-02 | `<IDs>` | `<full unit command>` | `<test count>` | `<pass/fail>` | `open` |
| V-03 | `<IDs>` | `<real-window scenario, if required>` | `<de-identified timing or outcome>` | `<pass/fail/N/A>` | `open` |

Do not commit screenshots, logs, account identifiers, local paths, or configuration
data. Record only the minimum de-identified evidence needed to establish the
behavioral result.

## Closure gate

Before marking the sync complete, verify every item below:

- Four-tree provenance audit is attached and all local merge decisions are classified.
- Every pre-merge behavior row has an automated regression or a documented reason it cannot.
- Every affected caller has a current RU contract-migration row.
- Every action, callback, or hook row verifies its return value and downstream control flow.
- Required real-window scenarios have explicit outcomes and timing thresholds.
- No legacy API, copied RU implementation, temporary compatibility alias, or A/B path remains.
- Focused tests, full tests, syntax checks, and `git diff --check` have passed.
- No row remains `open` or `blocked`.

Only then set `Sync status` to `verified` and record the final commit.
