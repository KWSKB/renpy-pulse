# ● Ren'Py Pulse (`renpy_pulse.rpy`)

![Ren'Py 7.5+ / 8.5+](https://img.shields.io/badge/Ren'Py-7.5%2B%20%7C%208.5%2B-00F7FF?style=for-the-badge)
![Zero Dependencies](https://img.shields.io/badge/Dependencies-None%20(Single%20.rpy%20File)-00FF88?style=for-the-badge)
![License: MIT](https://img.shields.io/badge/License-MIT-FF00D4?style=for-the-badge)

**Ren'Py Pulse** is a universal, zero-dependency, single-file drop-in **Live Variable Inspector, Choice Unlocker, and Dual-Monitor DevTool** for Ren'Py visual novels.

Drop **`renpy_pulse.rpy`** anywhere inside your project's `game/` folder and get both an **In-Game GUI Overlay (`F12`)** and a **Zero-Install Second-Window Live Dashboard (`Shift+W`)** that runs side-by-side on your second monitor while you test your game!

---

## ✨ Key Features

### 1. 🔍 Smart `.rpy` Source Scanner + Live Runtime Store
- Automatically scans your project's `.rpy` files at startup to index every `default`, `default persistent.*`, and data `define`—no manual watchlist setup required!
- **Auto-Grouping by `# Section Headers`**: Reads your code comments (e.g., `# Heroine Points`, `# Act 2 Flags`, `# Inventory`) and filenames to organize variables into clean categories automatically.
- **Type-Aware Controls**:
  - `bool`: 1-click `TRUE` / `FALSE` toggle switch.
  - `int` / `float`: `-10`, `-1`, `+1`, `+10` quick steppers + direct expression input.
  - `str` / `list` / `dict`: Inline expression editor + **1-Click Reset to Default**.
- **Watchlist (`★`) & Modified Filter (`Δ`)**: Pin your most-used variables to the top or filter strictly to variables whose values have diverged from their initial `default`.

### 2. 🖥️ Dual-Mode UI: In-Game Overlay + Second-Window App Dashboard
- **In-Game Overlay (`F12` or `Shift+D`)**: Fullscreen dark-glass HUD built with pure Ren'Py `Solid` containers (zero image assets required, zero conflict with your game's GUI).
- **Corner Mini-HUD Pill (`Shift+P` or Top-Bar Toggle)**: Non-intrusive top-left badge showing your live `label` and `file.rpy:line`, plus floating 3.5-second **Live Diff Toasts** whenever a script line or choice modifies a variable! Can be dismissed via `×` and toggled back on anytime from the top header bar in both the `F12` overlay and the Second-Window Dashboard.
- **Second-Window Live Dashboard (`Shift+W`)**: Spins up an embedded localhost bridge (`http://127.0.0.1:7367`) and pops out a **frameless desktop app window** (via Edge/Chrome `--app` mode or your default browser). Keep it on your second monitor to watch variables update every 350ms and edit values without covering your game canvas!

### 3. ⚡ Live Variable Diff Feed & 1-Click Undo
- Tracks every variable change as you play through scenes (`ayase_point: 4 -> 5 @ act2_3 (script2.rpy:412)`).
- Distinguishes between changes made by your **Script** vs. **DevTool**, with a **1-Click Undo** button on every history entry.

### 4. 🧭 Scene Teleporter & 1-Click Choice Condition Unlocker
- Search and **Jump** (`renpy.jump`) or **Call** (`renpy.call_in_new_context`) to any label in your project.
- **Choice Condition Analyzer**: Automatically inspects `menu:` blocks in your current chapter, evaluates each choice's `if <condition>:` live (`UNLOCKED` vs. `LOCKED`), displays the current values of all referenced variables, and gives you a **1-Click `Force Unlock`** button that automatically sets the required variables to satisfy the branch condition!

### 5. 💾 Route Preset Snapshots ("Loadouts")
- Save your current story variable state into named JSON presets (stored in `saves/pulse_presets/`).
- Load any route loadout at any time—either **Load Variables Only** or **Load + Jump to Bookmarked Label**—so you can test late-game branches without replaying from Act 1.

### 6. 🎛️ Live Screen, Layer & Multi-Channel Audio Inspector
- View all currently active screens on `screens` / `overlay` layers with 1-click **Hide**.
- View all currently displayed CGs, sprites, and WebM movies on `master`, `transient`, and `overlay` layers with 1-click **Hide**.
- Inspect every active audio channel (`music`, `sound`, `voice`, and custom channels) with 1-click **Stop**.

### 7. 🛡️ Safe Persistent Manager, Python Console & Auto-Strip on Release
- **Backup / Restore / Reset Persistent**: Back up your `persistent` data to JSON with one click before testing fresh-install states, and restore it anytime.
- **Interactive Python Console**: Evaluate expressions or execute statements directly inside `renpy.store`.
- **Automatic Release Build Protection**: Strictly gated behind `config.developer` and automatically registers `build.classify("**/renpy_pulse**", None)` so Ren'Py strips the tool out when you build a public release ZIP for players.

---

## 🚀 30-Second Installation

1. Download **`renpy_pulse.rpy`**.
2. Drop it anywhere inside your Ren'Py project's **`game/`** directory (for example, `game/renpy_pulse.rpy` or `game/script/devtools/renpy_pulse.rpy`).
3. Launch your game in developer mode (`config.developer = True`, which is the default when launching from the Ren'Py SDK).

That's it! No external Python packages, no images, and no configuration files needed.

---

## ⌨️ Default Hotkeys

| Hotkey | Action |
| :--- | :--- |
| **`F12`** *(or `Shift + D`)* | Toggle the **In-Game DevTool Overlay** |
| **`Shift + W`** | Pop out the **Second-Window Live Dashboard** (`http://127.0.0.1:7367`) |
| **`Shift + P`** | Show / Hide the **Corner Mini-HUD Pill** |
| **`Esc`** | Close active modal editor or close the DevTool Overlay |

---

## 🔌 Extending Pulse: Custom Game Quick-Actions API

Want to add 1-click cheat buttons specific to your visual novel (like *"Max Affection"*, *"Unlock All Gallery Scenes"*, or *"Set Weather: Rain"*)?

Call **`pulse_register_action(...)`** inside any `init python:` block in your project:

```renpy
init 998 python:
    if _pulse_is_enabled() and hasattr(store, "pulse_register_action"):

        def _my_max_stats_cheat():
            store.affection_points = 100
            store.gold = 9999

        pulse_register_action(
            label="Max Affection & Gold",
            category="Cheats",
            callback=_my_max_stats_cheat,
            description="Sets affection_points=100 and gold=9999 for route testing.",
            badge_fn=lambda: f"Affection: {getattr(store, 'affection_points', 0)}",
        )
```

Your custom actions will automatically appear in **Tab 6 (Quick Actions & Console)** in both the In-Game Overlay and the Second-Window Dashboard!

---

## 📜 License

Released under the [MIT License](LICENSE). Free for personal and commercial Ren'Py projects!
