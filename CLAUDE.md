# Claude repository instructions

All shared repository instructions are maintained in [AGENTS.md](AGENTS.md). Read and follow that file in full before making changes. This indirection keeps Codex and Claude conventions synchronized during upstream merges.

There are no Claude-specific exceptions to the shared RU/LW architecture, safety boundaries, testing requirements, or commit rules.

Project preference: do not synchronize gettext catalogs for each individual feature. Update and compile translations only when the user explicitly requests a release, localization, or consolidated translation pass.
