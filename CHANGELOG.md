# Changelog

All notable changes to **Ren'Py Pulse** will be documented in this file.

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
