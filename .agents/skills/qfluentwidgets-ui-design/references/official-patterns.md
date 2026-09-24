# Official QFluentWidgets Patterns

Use this as a concise routing guide, not as a substitute for the current official documentation.

## Edition policy

Assume the free Community Edition. Only select a Pro-only component when the user explicitly says QFluentWidgets Pro is available or requests its use. The official component catalogue and documentation mark Pro features; if a component’s edition is unclear, do not use it. Prefer a free composition from standard Qt layouts plus Community controls, for example `FlowLayout` or grid layouts instead of a Pro layout, and standard views/cards instead of a Pro-only visualisation.

## Source map

- Component catalogue: https://qfluentwidgets.com/pages/componentlist
- Fluent window and navigation: https://qfluentwidgets.com/pages/components/fluentwindow/
- Theme and custom QSS: https://qfluentwidgets.com/pages/theme/
- Configuration and setting cards: https://qfluentwidgets.com/pages/setting/
- Layout and responsive flow: https://qfluentwidgets.com/pages/components/flowlayout/

## Component map

| Need | Prefer |
| --- | --- |
| Main application shell | `FluentWindow`; use `MSFluentWindow` only when the Microsoft Store-style shell fits the product |
| Major page navigation | `NavigationInterface` and `addSubInterface()` |
| Few peer views within a page | `Pivot`, `SegmentedWidget`, or `TabBar` |
| Preferences | `SettingCardGroup` with the matching `*SettingCard` |
| One primary action | `PrimaryPushButton` / `PrimaryPushSettingCard` |
| Supporting action | `PushButton`; contextual icon action: `ToolButton` |
| Small status/outcome | `InfoBar`, `InfoBadge`, `ProgressRing`, or `StateToolTip` |
| Contextual help | `ToolTip`, `TeachingTip`, or `Flyout` |
| Related visual blocks | `CardWidget`, `SimpleCardWidget`, or `HeaderCardWidget` |
| Overflowing page | `ScrollArea` / `SmoothScrollArea` |

## Theme notes

- `setTheme(Theme.LIGHT | Theme.DARK | Theme.AUTO)` controls the component theme; `qconfig.themeChanged` signals a change.
- For a small custom exception, call `setCustomStyleSheet(widget, lightQss, darkQss)` rather than replacing component QSS globally.
- The official QSS placeholders include `--ThemeColorPrimary`, the `--ThemeColorLight*` and `--ThemeColorDark*` families, and `--FontFamilies`.
- The documented default font-family order is Segoe UI, Microsoft YaHei, and PingFang SC. Do not override it without a product reason.

## Navigation notes

- `FluentWindow` hosts subinterfaces in a stacked widget; use its navigation methods rather than maintaining a parallel page state machine.
- The navigation sidebar is responsive by default. If setting a custom expanded width, call `setExpandWidth()` before `setCollapsible(False)`.
- Use a top-level navigation item for a durable user goal, not every implementation area. Keep settings/help secondary.

## Version caution

The documentation and PySide/PyQt compatibility evolve. Confirm the installed package version and component API before adding newer controls or relying on behavior not already used by the project.
