---
name: combat-planner-dx-audit
description: >
  Audit the ok-nte combat planner system for developer experience, public API usability,
  role-authoring ergonomics, coordination expressiveness, and behavior predictability.
  Use when reviewing or releasing src/combat/planner, BaseChar planner helpers,
  docs/combat_planner.md, or character implementations such as Hotori, Nanally, Zero,
  Jiuyuan, Fadia, Healer, and custom characters. Focus on whether ordinary roles are
  easy to write, coordination roles can naturally express teammate needs, planner
  behavior matches developer intuition, and internal concepts are not leaked into role code.
---

# Combat Planner DX Audit

## Purpose

Review the ok-nte combat planner as a developer-facing battle coordination API. The planner should feel like a team brain: characters declare actions and needs, while planner decides switching, action attempts, coordination routes, reservations, entry reactions, and fallback field time.

## Core Design Standard

Evaluate every issue against these principles:

- **Flexible**: supports many future roles, not only Hotori-style record windows.
- **General**: core concepts are not named after one character mechanic.
- **Easy**: ordinary Q/E/field-time roles require little code.
- **Smart**: planner behavior matches role-author intuition.
- **Bounded**: role code imports stable API from `src.combat.planner`, not internals.

Expected planner mental model:

- `ActionIntent`: what a role may try after entering.
- `FieldClaim`: why a role should be switched in.
- `CombatContext.request_route()`: fixed teammate route.
- `CombatContext.request_route_window()`: route plus window-long holds.
- `CombatContext.reserve_actions()`: pure action reservation, not route progress.
- `ActionSlot`: normal route/reservation matching surface.
- `action_name`: advanced precision escape hatch only.
- `priority_ready`: scoring only.
- `can_execute`: hard planner permission.
- `EntryChainPolicy`: controls whether an entry action chain continues.
- `SwitchOutGuard`: delays leaving the current role safely.

## Files To Inspect

Start with these files when present:

- `src/combat/planner/__init__.py`
- `src/combat/planner/core.py`
- `src/combat/planner/types.py`
- `src/combat/planner/context.py`
- `src/combat/planner/requests.py`
- `src/combat/planner/state.py`
- `src/char/BaseChar.py`
- `docs/combat_planner.md`
- `tests/TestCombatPlanner.py`

Use representative role files as pressure tests:

- `src/char/Hotori.py`
- `src/char/Nanally.py`
- `src/char/Zero.py`
- `src/char/Jiuyuan.py`
- `src/char/Fadia.py`
- `src/char/Healer.py`
- `src/char/custom/CustomChar.py`

## Audit Workflow

### 1. Scope The Public API

Check that角色作者只需要从 `src.combat.planner` 导入正式 API. Flag external imports from internal modules such as `src.combat.planner.core`, `types`, `requests`, `state`, or `context`, except tests that explicitly validate architecture boundaries.

Check `__all__` and docs together:

- Every public type should be intentional.
- Internal request classes should not be public role API.
- Docs should explain public concepts in role-author terms.

### 2. Audit Ordinary Role Authoring

A simple role should be expressible with:

- `describe_role()`
- `combat_intents(context)`
- `click_ultimate_action()`
- `click_skill_action()`
- optional `planner_action(...)`
- optional `EntryChainPolicy`
- optional `RoleProfile.max_field_time`

Flag if a normal role must understand route, reservation, request internals, source tracking, action names, or score internals.

Use Fadia-style and Healer-style roles as checks:

- Q then leave should be one obvious action-chain choice.
- support role should not need fake coordination machinery.
- field-time preference should not require hand-written field damage actions.

### 3. Audit Coordination Role Authoring

A coordination role should declare needs, not manually drive teammates.

Check whether Hotori-like roles can naturally express:

- who should act
- which slot to use
- whether a step is optional
- which actions to hold
- when the window expires
- what to do on completion or expiration

Flag if role code manually tracks completed steps, source indices, route internals, request kinds, action-name strings for ordinary slots, or hidden planner state.

### 4. Audit Behavior Predictability

Compare actual behavior against these expectations:

- Switch scoring chooses who enters; it does not force ordinary first action.
- Ordinary entry executes allowed actions in declaration order.
- Strict route and expected entry can force first action.
- `priority_ready=False` lowers switch appeal but should not be confused with hard blocking.
- `can_execute=False` hard-blocks execution.
- Reservation blocks only matching actions; it does not imply progress and should not stop entry chains by itself.
- Route completion and window expiration are distinct.
- FieldClaim asks to enter later; SwitchOutGuard delays leaving now.

Flag any behavior likely to surprise a role developer.

### 5. Audit Naming And Concept Boundaries

Prefer domain-neutral names:

- good: `ActionSlot`, `ActionReservation`, `FieldClaim`, `request_route_window`
- suspicious: character-specific words in core planner, vague setup terms, tags used as control flow

Flag overlap between concepts:

- action score vs field claim
- route vs reservation
- priority readiness vs can execute
- field time vs custom action
- tags vs slots

### 6. Audit Tests As API Documentation

Tests should mostly validate public behavior:

- ordinary action chaining
- strict route ordering
- reservation permissions
- request route window lifetime
- field claim switching
- expected entry semantics
- public BaseChar helpers

Flag tests that depend on internal class names, exact log/score-breakdown formatting, or implementation-only request types unless they are deliberately named as architecture guard tests.

## Report Format

Use this structure:

```markdown
# Combat Planner DX Audit

## Verdict
One paragraph: ready/not ready for role developers, and why.

## Score
- Flexibility: X/10
- Generality: X/10
- Ease of Use: X/10
- Smart Behavior: X/10
- API Boundary: X/10

## Findings

### [Severity] [Title]
Symptom: what was observed.
Developer expectation: what a role author would reasonably expect.
Evidence: file/function/log/test evidence.
Consequence: what gets harder or breaks over time.
Recommended fix: concrete next step.

## Role Authoring Check

| Role Type | Expected Code Shape | Status |
|-----------|---------------------|--------|
| Simple Q/E role | `click_ultimate_action`, `click_skill_action` | Pass/Concern |
| DPS with field time | `RoleProfile.max_field_time` | Pass/Concern |
| Q then leave | `EntryChainPolicy` | Pass/Concern |
| Strict coordination role | `request_route` / `request_route_window` | Pass/Concern |
| Reservation role | `reserve_actions` | Pass/Concern |
| Legacy combo role | `LEGACY_COMBO` action | Pass/Concern |

## Release Gate
Must-fix items before planner API release.

## Nice To Have
Improvements that can wait.
```

Keep the report practical. Do not require perfect abstraction if current role code is clear, tested, and unlikely to confuse future role authors.
