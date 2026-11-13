# Changelog

All notable changes to **Ren'Py Pulse** will be documented in this file.

## [1.2.1] - 2026-11-13
### Fixed
- **Variable List Alignment (`Tab 1`)**: Isolated Pulse overlay container/text alignment (`pulse_ovl_vbox`, `pulse_ovl_hbox`, `pulse_ovl_text`) from host-game default `vbox`/`text` centering overrides and grouped the watch star + variable name/metadata into a single left-aligned `hbox` so every row lines up flush-left regardless of `Code` button visibility.
- **Audio Channel Inspector (`Tab 6` & Second Window)**: Fixed empty audio channel list caused by direct `renpy.audio.audio` attribute access raising `AttributeError` before `import` and whole-loop exception swallowing; added explicit `_get_audio_channels_map()` fallback via `renpy.audio.music.get_channel`, per-channel error isolation, `renpy.music.get_pos`/`get_duration` + `preferences.get_volume`/`get_mute` fallbacks, and an explicit empty/diagnostic card when no channels are active.

## [1.2.0] - 2026-11-13
### Added
- **Visual "Jump-to-Definition" (`Code` Button)**:
  - Added 1-click **Code** buttons across Variables (`Tab 1`), Diff Timeline (`Tab 2`), Scenes / Labels / Unlocks (`Tab 3`), and Registered Assets (`Tab 7`) in both the `F12` In-Game Overlay and `Shift+W` Second Window.
  - Opens files at exact line numbers (`code -g <file>:<line>`) in VS Code (with `PATH`, Windows `%LOCALAPPDATA%`/`Program Files`, and macOS/Linux fallback detection) plus optional custom editor templates via `pulse_configure(editor_cmd=...)`.
- **Dedicated Audio Channel Inspector (`Tab 6 — Dual-UI`)**:
  - Split Audio monitoring out of Screens/Layers into its own dedicated **Audio** tab displaying per-channel status (`music`, `sound`, `voice`, plus custom registered mixers/channels), playing track filename, elapsed/duration progress bar, channel & mixer volume controls, mute/pause badges, and queued tracks.
  - Added direct **Pause/Resume**, **Stop**, **Volume (-10% / +10% / slider)**, and **Clear Queue** controls in both UIs.
- **In-Game Asset & Style Previewer (`Tab 7 — Dual-UI`)**:
  - **Images Gallery**: Searchable list of registered images (`renpy.list_images()`) showing resolved source image paths, live scaled preview inside the `F12` overlay (`Transform(..., xysize=(900, 470), fit="contain")`), thumbnail previews via `GET /api/asset?file=...` in the Second Window, `Code` jump-to-source, and 1-click **Show on Master** / **Clear Preview**.
  - **Style Inspector**: Searchable index of registered styles (`renpy.style.styles`) inspecting the style inheritance chain (`style.parent`) and resolved properties safely without mutating active overlay styles.
- **Command History "Macro" System (`Header + Tab 2 + Tab 8 — Dual-UI`)**:
  - Added header **Rec Macro / Stop Rec** toggle to record variable edits, Force Unlocks, Python console commands, and registered actions into replayable JSON macro files saved under `saves/pulse_macros/`.
  - Added **+ Save Last 10 Diffs as Macro** button directly in Diff Timeline (`Tab 2`) to turn recent observed variable changes into a named macro preset.
  - Expanded **Actions & Macros (`Tab 8`)** to record, clear, save, rename/run (`Replay`), and delete macro presets from both the `F12` Overlay and `Shift+W` Second Window.

### Changed
- Expanded navigation across both UIs from 7 tabs to **9 tabs** (`1. Variables`, `2. Diffs`, `3. Scenes & Unlocks`, `4. Watchlist`, `5. Screens & Layers`, `6. Audio`, `7. Assets & Styles`, `8. Actions & Macros`, `9. Perf & Lag`).
- Refocused **Screens & Layers (`Tab 5`)** cleanly on active screens, display layers, scene/say attributes, and Persistent Manager / Python Console.

### Security
- Hardened `GET /api/asset` with `_pulse_local_only()` loopback validation, `os.path.realpath` containment strictly inside `config.gamedir`, and an image extension/MIME whitelist to prevent directory traversal.
- Enforced `config.gamedir`-relative path resolution and argument-list `subprocess.Popen` (`shell=False`) in `open_in_editor` to prevent shell injection.

## [1.1.0] - 2026-11-13
### Added
- **Live Memory, Resource & Custom UI Lag Monitor (Tab 7 — Dual-UI)**:
  - **GPU Texture & Image Cache Telemetry**: Live GPU texture memory (`MB` and active texture count via `renpy.get_texture_size()`), Image Cache utilization (`MB`, limit, and visual percentage bar via `renpy.display.im.cache`), renderer/GPU info (`renpy.get_renderer_info()`), `store`/`persistent`/`render_cache` counts, GC generation counts, and a 1-click **Free Memory (GC)** (`renpy.free_memory()`) button.
  - **Image Load Stall Detector**: Tracks recent `renpy.get_image_load_log()` entries and flags unpredicted image loads as `STALL` vs `PRELOAD`.
  - **Active Screen UI Lag Audit**: Safely inspects every active screen's displayable tree (capped at 2,500 nodes per screen, sampled on a 2.0s throttle) to report widget/node counts, active `Transform`s, pixel-level `focus_mask` buttons, `Timer`s, `Viewport`s, and automatic plain-English **Lag Hints**.
  - **Opt-In Live Screen Profiler**: Toggleable `ScreenDisplayable.update` / `render` timing profiler (`OFF` by default for zero overhead) measuring per-screen `avg ms`, `peak ms`, and `updates/s` in real time, plus 1-click `renpy.profile_screen()` file logging (`profile_screen.txt`).

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
