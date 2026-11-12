# Changelog

All notable changes to **Ren'Py Pulse** will be documented in this file.

## [1.0.2] - 2026-11-12
### Added
- **Starter Hook Template (`_pulse_hook.rpy`)**: Added an official, beginner-friendly `_pulse_hook.rpy` template with an out-of-the-box `"Verify Custom Hook"` check and 5 copy-pasteable visual novel recipes (stat/route cheats, persistent mode toggles, CG gallery unlockers, screen openers, and chapter jumps) compatible with both Ren'Py `7.5+` and `8.5+`.
- **Automated GitHub Release Packaging**: Added `.github/workflows/release.yml` so tagged releases automatically attach both `renpy_pulse.rpy` and `_pulse_hook.rpy` as 1-click downloadable `.rpy` assets.

### Changed
- **Singular & Plural Hook Auto-Exclusion**: Broadened `build.classify("**/*pulse_hook**", None)` and `.rpy` source scanner filtering in `renpy_pulse.rpy` so both singular (`_pulse_hook.rpy`, `my_pulse_hook.rpy`) and plural (`my_pulse_hooks.rpy`) hook files are automatically excluded from player release builds and skipped by the variable scanner.

## [1.0.1] - 2026-11-11
### Added
- **Top-Bar Corner HUD Toggle**: Added a live `● Top-Left HUD: ON / OFF (Shift+P)` toggle button to the `pulse_devtools_overlay` (`F12`) header bar—plus a matching `Top-Left HUD: ON / OFF` toggle in the Second-Window Live Dashboard header—so the corner pill can easily be turned back on after clicking `×`.
- **Custom Filter Hooks**: Added `pulse_configure(ignore_files=..., ignore_names=..., ignore_prefixes=..., force_enable=...)` so projects can exclude internal helper scripts or transient runtime variables without modifying `renpy_pulse.rpy`.

### Fixed
- **Persistent Default Initialization**: Declared top-level `default persistent._pulse_*` defaults and `is not False` visibility guards so unset Ren'Py `persistent` attributes (`None`) never evaluate as hidden before first interaction.
- **Release-Mode `config` Guard**: Removed `getattr(config, "pulse_force_enable", False)` (Ren'Py's `_Config.__getattr__` raises `Exception` rather than `AttributeError` on unknown keys, which could crash builds when `config.developer` is `False`).

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
