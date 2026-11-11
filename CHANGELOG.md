# Changelog

All notable changes to **Ren'Py Pulse** will be documented in this file.

## [1.0.1] - 2026-11-11
### Added
- **Top-Bar Corner HUD Toggle**: Added a live `● Top-Left HUD: ON / OFF (Shift+P)` toggle button to the `pulse_devtools_overlay` (`F12`) header bar—plus a matching `Top-Left HUD: ON / OFF` toggle in the Second-Window Live Dashboard header—so the corner pill can easily be turned back on after clicking `×`.
- **Custom Filter Hooks**: Added optional `config.pulse_ignore_files`, `config.pulse_ignore_names`, and `config.pulse_ignore_prefixes` settings so projects can exclude internal helper scripts or transient runtime variables without modifying `renpy_pulse.rpy`.

### Fixed
- **Persistent Default Initialization**: Declared top-level `default persistent._pulse_*` defaults and `is not False` visibility guards so unset Ren'Py `persistent` attributes (`None`) never evaluate as hidden before first interaction.

### Security
- **Localhost Bridge Request Hardening**: Restricted `/api/*` endpoints on the Second-Window HTTP server (`127.0.0.1:7367`) to loopback `Host`/`Origin` headers and required `Content-Type: application/json` on `/api/cmd` to block DNS-rebinding and cross-site requests.

## [1.0.0] - 2026-11-03
### Added
- **Smart `.rpy` Source Scanner**: Automatically indexes all `default`, `default persistent.*`, and data `define` variables across the project, grouping them by `.rpy` file and `# Section Header` comments.
- **Hybrid Dual-UI Architecture**:
  - **In-Game GUI Overlay (`F12` / `Shift+D`)** & **Collapsible Corner Mini-HUD Pill (`Shift+P`)** with zero external image dependencies.
  - **Zero-Install Second-Window Live Dashboard (`Shift+W`)** served via an embedded localhost HTTP bridge (`127.0.0.1:7367`), opening as a standalone frameless desktop app window (Edge/Chrome `--app` mode) or browser tab.
- **Live Variable Diff Log**: Real-time tracking of variable modifications with `file:line` attribution, floating corner toasts, and 1-click Undo.
- **Scene Teleporter & Choice Condition Unlocker**: Searchable label jumper plus live inspection of `menu:` choice `if` conditions with 1-click **Force Unlock**.
- **Route Preset Snapshots ("Loadouts")**: Save and load JSON variable presets with optional label bookmark jumping.
- **Live Screen, Layer & Audio Inspector**: View and toggle active screens, displayed images/movies, and multi-channel audio playback.
- **Safe Persistent Manager & Python Console**: 1-click backup, restore, and reset of `persistent` data alongside an interactive Python expression/statement runner.
- **Quick Actions Hook API (`pulse_register_action`)**: Simple plugin API for registering game-specific cheat/debug buttons.
- **Automatic Release Build Protection**: Auto-disables when `config.developer` is `False` and strips itself from player builds via `build.classify`.
