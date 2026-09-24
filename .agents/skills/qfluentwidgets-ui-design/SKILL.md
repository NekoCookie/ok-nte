---
name: qfluentwidgets-ui-design
description: Design, implement, or review PySide6/PyQt QFluentWidgets user interfaces in the library's official Fluent style. Use for new windows, navigation shells, settings pages, forms, dashboards, dialogs, component selection, visual refinements, or QSS/theme work in QFluentWidgets projects; especially when a UI should resemble the official Fluent Gallery rather than generic Qt widgets.
---

# QFluentWidgets UI Design

## Overview

Design coherent desktop UI around native QFluentWidgets components, Qt layouts, and the active theme. Prefer clear task hierarchy, familiar Fluent patterns, and small local changes over custom visual systems.

Assume the free Community Edition unless the user explicitly authorizes QFluentWidgets Pro. Do not design with or import Pro-only components by default.

## Workflow

1. Inspect the existing application shell, dependency version, theme/config system, and nearby interfaces before choosing components. Reuse the project’s window base, sizing, spacing, icon, and translation patterns.
2. Confirm the available edition. Treat the project as Community Edition unless the user explicitly says it has QFluentWidgets Pro; check the official component catalogue for a Pro label when uncertain and choose a free alternative.
3. Classify the surface:
   - App-level sections: `FluentWindow` / `MSFluentWindow` with `NavigationInterface`.
   - Closely related subpages: `Pivot`, `SegmentedWidget`, or `TabBar`; do not add a second sidebar.
   - Persistent preferences: `ScrollArea` + `SettingCardGroup` + appropriate setting cards.
   - Compact actions: `CommandBar`, menus, `ToolButton`, or a small action row.
   - Focused confirmation or input: `Dialog`, `MessageBox`, `Flyout`, or `TeachingTip` according to interruption level.
   - Content collections: `CardWidget`/`SimpleCardWidget`, `ListView`, `TableView`, or `TreeView` based on data structure.
4. Sketch the information hierarchy before coding: page title, one-line purpose, primary content/action, then secondary detail. Keep a single visually dominant primary action.
5. Build with layouts, semantic Fluent text widgets, and native controls. Do not rely on absolute positioning except for intentional overlays.
6. Verify light and dark themes, keyboard traversal, disabled/loading/empty/error states, scaling, and truncation. Compare visually with Fluent Gallery patterns when available.

## Fluent Design Rules

- Use `LargeTitleLabel`/`TitleLabel` for page hierarchy, `SubtitleLabel` for sections, and `BodyLabel`/`CaptionLabel` for supporting copy. Do not simulate hierarchy with arbitrary fonts or bold `QLabel`s.
- Use `FluentIcon` (`FIF`) for standard actions; use an icon only when it clarifies meaning. Pair unfamiliar icons with text or a tooltip.
- Use `PrimaryPushButton` only for the page’s main action. Use `PushButton` for ordinary actions and transparent/tool buttons for low-emphasis contextual actions.
- Favor vertical rhythm, aligned left edges, generous outer margins, and restrained card grouping. Use `HorizontalSeparator` or `CardSeparator` only when grouping alone is insufficient.
- Keep labels short and action-led. Explain a setting beneath its title when its effect, privacy, restart requirement, or risk is not self-evident.
- Use `InfoBar` for transient feedback; use inline copy for field validation; use `TeachingTip` for contextual onboarding. Do not surface success with modal dialogs.
- Prefer progressive disclosure: reveal advanced controls after an explicit choice, menu, expander, or dedicated subpage.

## Implementation Constraints

- Prefer QFluentWidgets classes over raw Qt counterparts where an official equivalent exists, but preserve existing project conventions and compatibility.
- Do not use `Pro`-labelled controls or APIs unless the user explicitly requests/authorizes Pro. When an official component is Pro-only, compose an equivalent with free QFluentWidgets and standard Qt layouts/views instead.
- Keep user-visible state in the application's configuration/model layer; wire controls through signals and slots. Do not put I/O, OCR/model inference, or long-running work in paint/layout/event paths.
- Use `ScrollArea` for pages that can exceed the window. Give content a practical maximum readable width where appropriate; let layouts adapt rather than hard-code a single resolution.
- Respect light, dark, and auto theme behavior. Use `setCustomStyleSheet()` only for small exceptions and provide both light and dark QSS. Reuse theme tokens such as `--ThemeColorPrimary` and `--FontFamilies`; do not hard-code light-only colors.
- Ensure icon-only actions have tooltips and accessible names where the project supports them. Preserve tab order, focus visibility, keyboard activation, and readable contrast.
- Avoid redesigning library internals with global QSS, dense grids of tiny controls, excessive rounded cards, multiple accent colors, or non-native animation unless the task explicitly calls for it.

## Settings Page Pattern

Use a scrollable page with a title and `SettingCardGroup`s. Group settings by user goal, not implementation subsystem. Choose the most specific card: `SwitchSettingCard` for booleans, `RangeSettingCard` for bounded numeric values, `ComboBoxSettingCard`/`OptionsSettingCard` for choices, and `PrimaryPushSettingCard` only for the main destructive or irreversible action. Mark restart requirements in helper text or the existing application convention.

## Official Layout Fidelity

Treat the installed QFluentWidgets source and its official examples as the
authoritative contract for component construction. Before changing a layout or
diagnosing animation behaviour, reproduce the example's widget ownership,
layout hierarchy, scroll-area setup, and sizing policy.

- Do not assume an official widget has a bug. First compare the application's
  parent-child relationships and layout nesting with the relevant official
  example, then make the application follow that structure.
- Put an `ExpandSettingCard` directly in the official `ExpandLayout` that
  manages its card list. Create the card with that layout's parent widget (or
  explicitly set that parent) before adding it. Do not place it only in an
  unrelated `QVBoxLayout` and compensate afterwards.
- Keep page shells, scroll areas, action bars, stretches, and ordinary nested
  layouts in their normal Qt layouts. Use `ExpandLayout` only for the direct
  list of expandable cards; never replace a generic page layout globally just
  to support one card type.
- Do not override `ExpandSettingCard` animation or final-height behaviour to
  compensate for an application layout problem. If a dynamic list needs
  operations not exposed by the official layout, keep that list-management
  concern separate from the card's animation behaviour and verify the result
  against the official construction first.

## Review Checklist

- Does the chosen navigation scale to the number and relationship of pages?
- Does each screen have a scannable title, a primary task, and meaningful empty/loading/error feedback?
- Are controls native QFluentWidgets components with correct emphasis and concise labels?
- Is every selected control available in the Community Edition, unless the user explicitly authorized Pro?
- Does the design remain usable in dark mode, at high DPI, and with longer translated text?
- Are custom QSS, colors, fonts, and icons necessary, themed, and localized to the component?
- Is all expensive work outside the UI render/event hot path?

## Reference

Read [references/official-patterns.md](references/official-patterns.md) when choosing a component, applying themes/QSS, or implementing navigation/settings. Check the current official documentation for APIs that may have changed before relying on version-specific details.
