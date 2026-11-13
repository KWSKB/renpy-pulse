################################################################################
## REN'PY PULSE (v1.2.1) — Live Variable Inspector, Overlay & 2nd-Window DevTool
## License: MIT License | Single-File Drop-In Plugin for Ren'Py 7.5+ / 8.5+
##
## Features:
##   1. Smart .rpy Source Scanner (indexes `default`, `persistent`, `define`,
##      `# Section Headers`, `label`s, and `menu:` choice `if` conditions).
##   2. Live Variable & Persistent Inspector/Editor + VS Code Jump-to-Definition.
##   3. Scene Teleporter & 1-Click Choice Condition Unlocker.
##   4. Route Preset Snapshots ("Loadouts") — Save/Load JSON variable states.
##   5. Live Screen & Layer Inspector + Dedicated Multi-Channel Audio Inspector.
##   6. In-Game Asset & Style Previewer (Images Gallery + Style Inspector).
##   7. Command History Macro Recorder & 1-Click Test Scenario Runner.
##   8. Safe Persistent Backup/Restore/Reset & Interactive Python Console.
##   9. Live Memory, Resource & Custom UI Lag Monitor (GPU Textures, Image Cache,
##      Image Stall Detector, Per-Screen Tree Audit & Opt-In Screen Profiler).
##  10. Zero-Install Second-Window Live Dashboard (`http://127.0.0.1:7367`)
##      that pops out as a standalone frameless desktop window for dual monitors.
##  11. Public Quick-Actions Hook API (`pulse_register_action`) for game cheats.
##
## Hotkeys (when `config.developer` is True):
##   - F12 (or Shift+D) : Toggle In-Game DevTool Overlay
##   - Shift+W          : Pop Out Second-Window Live Dashboard
##   - Shift+P          : Toggle Corner Mini-HUD Pill
################################################################################

init -999 python:
    # Auto-exclude DevTool files from player release distributions
    if hasattr(build, "classify"):
        build.classify("**/renpy_pulse**", None)
        build.classify("**/*pulse_hook**", None)

    def _pulse_is_enabled():
        return bool(
            getattr(config, "developer", False)
            or getattr(store, "_pulse_force_enable", False)
        )

    # Public Filter & Hook Registration API (available at any init level)
    if not hasattr(store, "_pulse_custom_filters"):
        _pulse_custom_filters = {
            "ignore_files": set(),
            "ignore_names": set(),
            "ignore_prefixes": [],
            "editor_cmd": None,
        }

    def pulse_configure(ignore_files=None, ignore_names=None, ignore_prefixes=None, force_enable=None, editor_cmd=None):
        """
        Configure project-specific file/variable exclusions, custom editor command
        (e.g. ["code", "-g", "{file}:{line}"]), or force-enable mode in Ren'Py Pulse
        without touching Ren'Py's locked `config` namespace.
        """
        if ignore_files:
            _pulse_custom_filters["ignore_files"].update(ignore_files)
        if ignore_names:
            _pulse_custom_filters["ignore_names"].update(ignore_names)
        if ignore_prefixes:
            for pfx in ignore_prefixes:
                if pfx not in _pulse_custom_filters["ignore_prefixes"]:
                    _pulse_custom_filters["ignore_prefixes"].append(pfx)
        if force_enable is not None:
            store._pulse_force_enable = bool(force_enable)
        if editor_cmd is not None:
            _pulse_custom_filters["editor_cmd"] = list(editor_cmd) if isinstance(editor_cmd, (list, tuple)) else str(editor_cmd)

    if not hasattr(store, "_pulse_registered_actions"):
        _pulse_registered_actions = []

    def pulse_register_action(label, category="General", callback=None, description="", badge_fn=None):
        """
        Register a custom 1-click Quick Action button in Ren'Py Pulse.
        - label: Button title (str)
        - category: Grouping header name (str)
        - callback: Zero-arg Python callable executed when clicked
        - description: Tooltip / subtitle text (str)
        - badge_fn: Optional zero-arg callable returning a current status string (e.g. "ON" / "OFF")
        """
        if callback is None:
            return
        for existing in _pulse_registered_actions:
            if existing["label"] == label and existing["category"] == category:
                existing["callback"] = callback
                existing["description"] = description
                existing["badge_fn"] = badge_fn
                return
        _pulse_registered_actions.append({
            "id": "act_" + str(len(_pulse_registered_actions) + 1),
            "label": str(label),
            "category": str(category),
            "callback": callback,
            "description": str(description),
            "badge_fn": badge_fn,
        })


default persistent._pulse_watchlist = []
default persistent._pulse_hud_visible = True
default persistent._pulse_toasts_enabled = True


init 999 python:
    import gc
    import os
    import re
    import sys
    import json
    import time as _pulse_time
    import copy
    import socket
    import subprocess
    import threading
    import webbrowser
    from collections import OrderedDict

    try:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import urlparse, parse_qs
    except ImportError:
        BaseHTTPRequestHandler = object
        ThreadingHTTPServer = None

    def _pulse_esc(val):
        """Escape square brackets and curly braces for safe Ren'Py screen text rendering."""
        if val is None:
            return "None"
        s = str(val)
        return s.replace("[", "[[").replace("{", "{{")

    def _pulse_short_repr(val, max_len=68):
        try:
            r = repr(val)
        except Exception:
            r = "<unrepresentable>"
        if len(r) > max_len:
            r = r[:max_len - 3] + "..."
        return r

    def _pulse_type_name(val):
        if isinstance(val, bool):
            return "bool"
        elif isinstance(val, int):
            return "int"
        elif isinstance(val, float):
            return "float"
        elif isinstance(val, str):
            return "str"
        elif isinstance(val, list):
            return "list"
        elif isinstance(val, dict):
            return "dict"
        elif isinstance(val, set):
            return "set"
        elif isinstance(val, tuple):
            return "tuple"
        elif val is None:
            return "NoneType"
        return type(val).__name__

    # Ignored internal store / persistent prefixes and engine objects
    _PULSE_IGNORED_STORE_NAMES = set([
        "config", "gui", "build", "preferences", "persistent", "style",
        "achievement", "updater", "store", "renpy", "sys", "os", "re",
        "json", "time", "copy", "socket", "subprocess", "threading",
        "webbrowser", "OrderedDict", "BaseHTTPRequestHandler",
        "ThreadingHTTPServer", "urlparse", "parse_qs", "main_menu",
        "save_name", "mouse_visible", "suppress_overlay", " adv", "name_only",
        "narrator", "centered", "vcentered", " default", "menu", "say",
    ])

    _PULSE_IGNORED_DEFINE_PREFIXES = (
        "Character(", "DynamicCharacter(", "Image(", "Movie(", "Solid(",
        "Frame(", "Transform(", "Dissolve(", "Fade(", "Pixellate(",
        "MoveTransition(", "ComposeTransition(", "MultipleTransition(",
        "CropMove(", "PushMove(", "FontGroup(", "AudioData(", "_p(",
        "ConditionSwitch(", "LayeredImage(", "LiveComposite(", "AlphaMask(",
        " At(", "Text(", "Flatten(", "Fixed(", "HBox(", "VBox(",
    )

    def _pulse_is_mini_hud_visible():
        return getattr(persistent, "_pulse_hud_visible", True) is not False

    class _PulseManager(object):
        def __init__(self):
            self.initialized = False
            self.var_meta = OrderedDict()       # key -> metadata dict
            self.initial_values = {}            # key -> deepcopied initial value
            self.categories = ["All", "Watchlist", "Modified", "Store", "Persistent", "Defines"]
            self.header_categories = []         # Dynamic # Header categories from .rpy files
            self.file_categories = []           # .rpy source filenames
            self.labels = []                    # list of {"name", "file", "file_short", "line", "category"}
            self.menus = []                     # list of {"name", "file", "file_short", "line", "label", "choices": [...]}

            # UI State (shared with in-game screen)
            self.active_tab = "variables"       # "variables", "diffs", "teleport", "presets", "inspector", "actions"
            self.selected_category = "All"
            self.search_query = ""
            self.label_search = ""
            self.screen_search = ""
            self.page_offset = 0
            self.page_size = 22

            # Inline Editor Modal State
            self.editing_var = None             # var_key currently being edited via text input
            self.editing_buffer = ""
            self.editing_error = ""

            # Preset Modal State
            self.preset_name_input = "My Route Loadout"
            self.preset_status_msg = ""

            # Python Console State
            self.console_input = ""
            self.console_history = []           # list of {"expr", "output", "is_error", "time"}

            # Live Change Tracking & Toasts
            self.last_snapshot = {}             # key -> repr(val)
            self.last_val_snapshot = {}         # key -> deepcopy/raw value for Undo
            self.diff_log = []                  # list of diff dicts (newest first)
            self.toasts = []                    # list of {"text", "time", "color"}
            self.current_label = "start"
            self.suppress_diff_capture = False

            # Second-Window Localhost Bridge
            self.server_port = 7367
            self.server_running = False
            self.server_url = "http://127.0.0.1:7367"
            self.cmd_queue = []
            self.cmd_lock = threading.Lock()
            self.cached_api_payload = "{}"
            self.last_cache_time = 0.0

            # Performance, Memory & Custom UI Lag Monitor
            self.ui_profiler_enabled = False
            self.ui_prof_stats = {}
            self.ui_prof_window_start = 0.0
            self.perf_cache = {}
            self.last_perf_sample_time = 0.0
            self.last_audio_error = ""

            # Asset & Style Previewer State
            self.asset_subtab = "images"        # "images" or "styles"
            self.asset_search = ""
            self.asset_tag_filter = "All"
            self.selected_image_name = None
            self.style_search = ""
            self.style_scope_filter = "All"     # "All" or "Custom"
            self.selected_style_name = "default"

            # Command History Macro Recorder State
            self.macro_recording = False
            self.macro_steps = []
            self.macro_name_input = "Test Scenario A"
            self.macro_status_msg = ""
            self.suppress_macro_capture = False

        # ------------------------------------------------------------------
        # 1. Initialization & Smart .rpy Source Scanner
        # ------------------------------------------------------------------
        def setup(self):
            if self.initialized or not _pulse_is_enabled():
                return
            self.initialized = True

            # Ensure persistent preferences exist
            if getattr(persistent, "_pulse_watchlist", None) is None:
                persistent._pulse_watchlist = []
            if getattr(persistent, "_pulse_hud_visible", None) is None:
                persistent._pulse_hud_visible = True
            if getattr(persistent, "_pulse_toasts_enabled", None) is None:
                persistent._pulse_toasts_enabled = True

            self.scan_project_files()
            self.capture_initial_values()
            self.sync_runtime_variables()
            self.take_baseline_snapshot()
            self.start_http_bridge()

        def scan_project_files(self):
            gamedir = renpy.config.gamedir
            re_header = re.compile(r"^\s*#\s*([A-Za-z0-9][A-Za-z0-9 _\-/&'():]{1,42}?)\s*$")
            re_default = re.compile(r"^\s*default\s+(persistent\.[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")
            re_define = re.compile(r"^\s*define\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")
            re_label = re.compile(r"^\s*label\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\([^)]*\))?\s*:")
            re_menu = re.compile(r"^(\s*)menu(?:\s+([A-Za-z_][A-Za-z0-9_]*))?\s*:")
            re_choice = re.compile(r'^\s*"([^"]+)"(?:\s+if\s+(.+?))?\s*:')

            extra_ignore_files = set(_pulse_custom_filters["ignore_files"])
            rpy_files = []
            for root, dirs, files in os.walk(gamedir):
                # Skip cache/saves/tl directories
                rel_root = os.path.relpath(root, gamedir).replace("\\", "/")
                if rel_root.startswith("saves") or rel_root.startswith("cache") or rel_root.startswith("tl"):
                    continue
                for f in sorted(files):
                    rel_f = os.path.relpath(os.path.join(root, f), gamedir).replace("\\", "/")
                    if (
                        f.endswith(".rpy")
                        and f != "renpy_pulse.rpy"
                        and "pulse_hook" not in f.lower()
                        and f not in extra_ignore_files
                        and rel_f not in extra_ignore_files
                    ):
                        rpy_files.append(os.path.join(root, f))

            for full_path in rpy_files:
                rel_path = os.path.relpath(full_path, gamedir).replace("\\", "/")
                file_short = os.path.basename(full_path)
                current_header = None
                current_label_in_file = "global"
                active_menu = None
                active_menu_indent = -1

                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as fp:
                        lines = fp.readlines()
                except Exception:
                    continue

                for idx, raw_line in enumerate(lines):
                    line_no = idx + 1
                    stripped = raw_line.strip()

                    # Check if we exited an active menu block
                    if active_menu is not None and stripped and not stripped.startswith("#"):
                        indent_len = len(raw_line) - len(raw_line.lstrip(" "))
                        if indent_len <= active_menu_indent and not re_menu.match(raw_line):
                            active_menu = None
                            active_menu_indent = -1

                    # Check section header comments (only in define/var files or right above a top-level default)
                    if stripped.startswith("#") and not stripped.startswith("##") and not stripped.startswith("#-"):
                        indent_len = len(raw_line) - len(raw_line.lstrip(" "))
                        # Look ahead 1-2 lines to see if a default/define immediately follows
                        next_is_def = False
                        for look_idx in range(idx + 1, min(idx + 4, len(lines))):
                            nxt = lines[look_idx].strip()
                            if not nxt:
                                continue
                            if nxt.startswith("default ") or nxt.startswith("define "):
                                next_is_def = True
                            break
                        if indent_len <= 4 and (file_short == "define.rpy" or next_is_def):
                            m_hdr = re_header.match(raw_line)
                            if m_hdr:
                                cand = m_hdr.group(1).strip()
                                upper_c = cand.upper()
                                if upper_c not in ("VARIABLES", "DEFINITIONS", "CHARACTER DEFINITIONS", "IMAGES", "TRANSFORMS", "OTHERS", "CHOICE MENU", "SPECIAL", "SUPPORT", "NORMAL SCENES"):
                                    if not cand.startswith("TODO") and not cand.startswith("FIXME") and not cand.startswith("MAX ") and len(cand) <= 28:
                                        current_header = cand
                        continue

                    if not stripped:
                        continue

                    # Reset section header if we hit a label or screen block
                    if stripped.startswith("screen ") or stripped.startswith("label "):
                        current_header = None

                    # Check label declaration
                    m_lbl = re_label.match(raw_line)
                    if m_lbl:
                        lbl_name = m_lbl.group(1)
                        current_label_in_file = lbl_name
                        self.labels.append({
                            "name": lbl_name,
                            "file": rel_path,
                            "file_short": file_short,
                            "line": line_no,
                            "category": file_short,
                        })
                        continue

                    # Check menu declaration
                    m_mnu = re_menu.match(raw_line)
                    if m_mnu:
                        active_menu_indent = len(m_mnu.group(1))
                        mnu_name = m_mnu.group(2) or ("menu_L" + str(line_no))
                        active_menu = {
                            "name": mnu_name,
                            "file": rel_path,
                            "file_short": file_short,
                            "line": line_no,
                            "label": current_label_in_file,
                            "choices": [],
                        }
                        self.menus.append(active_menu)
                        continue

                    # Check choice inside active menu
                    if active_menu is not None:
                        m_ch = re_choice.match(raw_line)
                        if m_ch:
                            active_menu["choices"].append({
                                "caption": m_ch.group(1),
                                "condition": m_ch.group(2).strip() if m_ch.group(2) else None,
                                "line": line_no,
                            })
                            continue

                    # Check default declaration (only top-level or inside `init:`, indent <= 4)
                    m_def = re_default.match(raw_line)
                    if m_def and (len(raw_line) - len(raw_line.lstrip(" "))) <= 4:
                        var_key = m_def.group(1).strip()
                        expr = m_def.group(2).split("#")[0].strip()
                        is_pers = var_key.startswith("persistent.")
                        short_name = var_key[11:] if is_pers else var_key
                        if short_name.startswith("_"):
                            continue
                        cat = current_header if (current_header and file_short == "define.rpy") else ("File: " + file_short)
                        self._register_var_meta(
                            var_key=var_key,
                            short_name=short_name,
                            scope="persistent" if is_pers else "store",
                            default_expr=expr,
                            file_rel=rel_path,
                            file_short=file_short,
                            line_no=line_no,
                            category=cat,
                        )
                        continue

                    # Check define declaration (only top-level or inside `init:`, indent <= 4)
                    m_dfn = re_define.match(raw_line)
                    if m_dfn and (len(raw_line) - len(raw_line.lstrip(" "))) <= 4:
                        var_key = m_dfn.group(1).strip()
                        expr = m_dfn.group(2).split("#")[0].strip()
                        if var_key.startswith("_") or "." in var_key:
                            continue
                        if any(expr.startswith(pfx) for pfx in _PULSE_IGNORED_DEFINE_PREFIXES):
                            continue
                        cat = current_header if (current_header and file_short == "define.rpy") else ("File: " + file_short)
                        self._register_var_meta(
                            var_key=var_key,
                            short_name=var_key,
                            scope="define",
                            default_expr=expr,
                            file_rel=rel_path,
                            file_short=file_short,
                            line_no=line_no,
                            category=cat,
                        )

        def _is_ignored_var(self, var_key, short_name):
            extra_names = _pulse_custom_filters["ignore_names"]
            if var_key in extra_names or short_name in extra_names:
                return True
            extra_prefixes = tuple(_pulse_custom_filters["ignore_prefixes"])
            if extra_prefixes and (var_key.startswith(extra_prefixes) or short_name.startswith(extra_prefixes)):
                return True
            return False

        def _register_var_meta(self, var_key, short_name, scope, default_expr, file_rel, file_short, line_no, category):
            if self._is_ignored_var(var_key, short_name):
                return
            self.var_meta[var_key] = {
                "key": var_key,
                "name": short_name,
                "scope": scope,
                "default_expr": default_expr,
                "file": file_rel,
                "file_short": file_short,
                "line": line_no,
                "category": category,
            }

        def _rebuild_category_lists(self):
            self.header_categories = []
            self.file_categories = []
            for meta in self.var_meta.values():
                cat = meta["category"]
                if not cat.startswith("File: ") and cat not in self.categories and cat not in self.header_categories:
                    self.header_categories.append(cat)
                file_cat = "File: " + meta["file_short"]
                if file_cat not in self.file_categories:
                    self.file_categories.append(file_cat)

        def capture_initial_values(self):
            # Filter out non-data defines, screen-local defaults, and Displayable instances
            to_remove = []
            for var_key, meta in list(self.var_meta.items()):
                val, exists = self._raw_get(var_key, meta["scope"])
                if not exists and meta["scope"] != "persistent":
                    to_remove.append(var_key)
                    continue
                if exists and not isinstance(val, (bool, int, float, str, list, dict, set, tuple, type(None))):
                    to_remove.append(var_key)
                    continue
                try:
                    self.initial_values[var_key] = copy.deepcopy(val)
                except Exception:
                    self.initial_values[var_key] = val

            for k in to_remove:
                del self.var_meta[k]
            self._rebuild_category_lists()

        def sync_runtime_variables(self):
            """Discover dynamic runtime variables in store and persistent not declared via static `default`."""
            # 1. Inspect store.ever_been_changed
            store_dicts = getattr(renpy.python, "store_dicts", {})
            main_store = store_dicts.get("store", None)
            changed_set = getattr(main_store, "ever_been_changed", set()) if main_store else set()

            extra_ignore_names = set(_pulse_custom_filters["ignore_names"])
            extra_ignore_prefixes = tuple(_pulse_custom_filters["ignore_prefixes"])
            for name in sorted(changed_set):
                if (
                    name.startswith("_")
                    or (extra_ignore_prefixes and name.startswith(extra_ignore_prefixes))
                    or name in _PULSE_IGNORED_STORE_NAMES
                    or name in extra_ignore_names
                    or name in self.var_meta
                ):
                    continue
                val = getattr(store, name, None)
                if isinstance(val, (bool, int, float, str, list, dict, set)):
                    self._register_var_meta(
                        var_key=name,
                        short_name=name,
                        scope="store",
                        default_expr="None",
                        file_rel="runtime",
                        file_short="runtime",
                        line_no=0,
                        category="Runtime Store",
                    )

            # 2. Inspect persistent.__dict__
            for pname, pval in sorted(persistent.__dict__.items()):
                if pname.startswith("_") or pval is None:
                    continue
                full_key = "persistent." + pname
                if full_key in self.var_meta:
                    continue
                if isinstance(pval, (bool, int, float, str, list, dict, set)):
                    self._register_var_meta(
                        var_key=full_key,
                        short_name=pname,
                        scope="persistent",
                        default_expr="None",
                        file_rel="persistent",
                        file_short="persistent",
                        line_no=0,
                        category="Persistent Runtime",
                    )

        # ------------------------------------------------------------------
        # 2. Value Getters, Setters & Diff Tracking
        # ------------------------------------------------------------------
        def _raw_get(self, var_key, scope=None):
            if scope is None:
                meta = self.var_meta.get(var_key)
                scope = meta["scope"] if meta else ("persistent" if var_key.startswith("persistent.") else "store")
            if scope == "persistent" or var_key.startswith("persistent."):
                pname = var_key[11:] if var_key.startswith("persistent.") else var_key
                if hasattr(persistent, pname):
                    return getattr(persistent, pname), True
                return None, False
            else:
                if hasattr(store, var_key):
                    return getattr(store, var_key), True
                return None, False

        def get_value(self, var_key):
            val, _ = self._raw_get(var_key)
            return val

        def is_watched(self, var_key):
            wl = getattr(persistent, "_pulse_watchlist", None) or []
            return var_key in wl

        def toggle_watch(self, var_key):
            if getattr(persistent, "_pulse_watchlist", None) is None:
                persistent._pulse_watchlist = []
            if var_key in persistent._pulse_watchlist:
                persistent._pulse_watchlist.remove(var_key)
            else:
                persistent._pulse_watchlist.append(var_key)
            renpy.save_persistent()
            renpy.restart_interaction()

        def is_modified_from_default(self, var_key):
            val, exists = self._raw_get(var_key)
            if not exists:
                return False
            if var_key in self.initial_values:
                try:
                    return val != self.initial_values[var_key]
                except Exception:
                    return False
            return False

        def set_value(self, var_key, new_val, source="DevTool"):
            old_val, _ = self._raw_get(var_key)
            self.suppress_diff_capture = True
            try:
                if var_key.startswith("persistent."):
                    pname = var_key[11:]
                    setattr(persistent, pname, new_val)
                    renpy.save_persistent()
                else:
                    setattr(store, var_key, new_val)
                self._record_diff(var_key, old_val, new_val, source=source)
                if self.macro_recording and not self.suppress_macro_capture and source not in ("Script", "Macro"):
                    self._record_macro_set(var_key, new_val)
                self.last_snapshot[var_key] = _pulse_short_repr(new_val, 200)
                try:
                    self.last_val_snapshot[var_key] = copy.deepcopy(new_val)
                except Exception:
                    self.last_val_snapshot[var_key] = new_val
            finally:
                self.suppress_diff_capture = False
            renpy.restart_interaction()

        def toggle_bool(self, var_key, source="DevTool"):
            cur = self.get_value(var_key)
            self.set_value(var_key, not bool(cur), source=source)

        def step_number(self, var_key, delta, source="DevTool"):
            cur = self.get_value(var_key)
            if isinstance(cur, float) or isinstance(delta, float):
                new_val = round(float(cur or 0.0) + float(delta), 4)
            else:
                new_val = int(cur or 0) + int(delta)
            self.set_value(var_key, new_val, source=source)

        def reset_var(self, var_key, source="DevTool"):
            meta = self.var_meta.get(var_key)
            if var_key in self.initial_values:
                try:
                    restored = copy.deepcopy(self.initial_values[var_key])
                except Exception:
                    restored = self.initial_values[var_key]
                self.set_value(var_key, restored, source=source)
                return
            if meta and meta.get("default_expr") and meta["default_expr"] != "None":
                try:
                    restored = eval(meta["default_expr"], store.__dict__)
                    self.set_value(var_key, restored, source=source)
                except Exception:
                    pass

        def reset_all_store_vars(self):
            count = 0
            for var_key, meta in self.var_meta.items():
                if meta["scope"] == "store" and self.is_modified_from_default(var_key):
                    self.reset_var(var_key, source="ResetAll")
                    count += 1
            self.add_toast("Reset " + str(count) + " store variables to default", "#00F7FF")
            renpy.restart_interaction()

        def open_inline_editor(self, var_key):
            val = self.get_value(var_key)
            self.editing_var = var_key
            if isinstance(val, str):
                self.editing_buffer = val
            else:
                try:
                    self.editing_buffer = repr(val)
                except Exception:
                    self.editing_buffer = str(val)
            self.editing_error = ""
            renpy.restart_interaction()

        def apply_inline_edit(self, raw_str=None):
            if not self.editing_var:
                return
            var_key = self.editing_var
            buf = self.editing_buffer if raw_str is None else str(raw_str)
            cur_val = self.get_value(var_key)
            try:
                if isinstance(cur_val, str) and not (buf.startswith("'") or buf.startswith('"')):
                    new_val = buf
                elif isinstance(cur_val, bool):
                    new_val = buf.strip().lower() in ("true", "1", "yes", "on")
                elif isinstance(cur_val, int) and not isinstance(cur_val, bool):
                    new_val = int(eval(buf, store.__dict__))
                elif isinstance(cur_val, float):
                    new_val = float(eval(buf, store.__dict__))
                else:
                    new_val = eval(buf, store.__dict__)
                self.set_value(var_key, new_val, source="Editor")
                self.editing_var = None
                self.editing_error = ""
            except Exception as e:
                self.editing_error = str(e)
            renpy.restart_interaction()

        def take_baseline_snapshot(self):
            for var_key, meta in self.var_meta.items():
                if meta["scope"] == "define":
                    continue
                val, exists = self._raw_get(var_key, meta["scope"])
                if exists:
                    self.last_snapshot[var_key] = _pulse_short_repr(val, 200)
                    try:
                        self.last_val_snapshot[var_key] = copy.deepcopy(val)
                    except Exception:
                        self.last_val_snapshot[var_key] = val

        def check_for_diffs(self):
            if not self.initialized or self.suppress_diff_capture:
                return
            self.sync_runtime_variables()
            for var_key, meta in list(self.var_meta.items()):
                if meta["scope"] == "define":
                    continue
                val, exists = self._raw_get(var_key, meta["scope"])
                if not exists:
                    continue
                cur_repr = _pulse_short_repr(val, 200)
                prev_repr = self.last_snapshot.get(var_key)
                if prev_repr is not None and cur_repr != prev_repr:
                    old_val = self.last_val_snapshot.get(var_key, prev_repr)
                    self._record_diff(var_key, old_val, val, source="Script")
                self.last_snapshot[var_key] = cur_repr
                try:
                    self.last_val_snapshot[var_key] = copy.deepcopy(val)
                except Exception:
                    self.last_val_snapshot[var_key] = val

        def _record_diff(self, var_key, old_val, new_val, source="Script"):
            fn, ln = self.get_current_file_line()
            entry = {
                "id": int(_pulse_time.time() * 1000) % 100000000 + len(self.diff_log),
                "var_key": var_key,
                "old_val": old_val,
                "new_val": new_val,
                "old_repr": _pulse_short_repr(old_val, 40),
                "new_repr": _pulse_short_repr(new_val, 40),
                "label": self.current_label,
                "file": fn,
                "line": ln,
                "file_line": fn + ":" + str(ln),
                "time": _pulse_time.strftime("%H:%M:%S"),
                "source": source,
            }
            self.diff_log.insert(0, entry)
            if len(self.diff_log) > 150:
                self.diff_log.pop()

            if getattr(persistent, "_pulse_toasts_enabled", True) is not False:
                col = "#00F7FF" if source == "Script" else "#FFB800"
                self.add_toast(var_key + ": " + entry["old_repr"] + " -> " + entry["new_repr"], col)

        def undo_diff(self, diff_id):
            for entry in self.diff_log:
                if entry["id"] == diff_id:
                    self.set_value(entry["var_key"], entry["old_val"], source="Undo")
                    self.add_toast("Reverted " + entry["var_key"] + " to " + entry["old_repr"], "#00FF88")
                    break

        def add_toast(self, text, color="#00F7FF"):
            now = _pulse_time.time()
            self.toasts.append({"text": str(text), "expires": now + 3.5, "color": color})
            if len(self.toasts) > 5:
                self.toasts = self.toasts[-5:]

        def prune_toasts(self):
            now = _pulse_time.time()
            before = len(self.toasts)
            self.toasts = [t for t in self.toasts if t["expires"] > now]
            return len(self.toasts) != before

        # ------------------------------------------------------------------
        # 3. Filtering & Variable Querying
        # ------------------------------------------------------------------
        def get_all_categories(self):
            return self.categories + self.header_categories + self.file_categories

        def get_filtered_variables(self, category=None, query=None):
            cat = (category if category is not None else self.selected_category) or "All"
            q = (query if query is not None else self.search_query).strip().lower()
            wl = set(getattr(persistent, "_pulse_watchlist", None) or [])

            results = []
            for var_key, meta in self.var_meta.items():
                scope = meta["scope"]
                if cat == "Watchlist" and var_key not in wl:
                    continue
                elif cat == "Modified" and not self.is_modified_from_default(var_key):
                    continue
                elif cat == "Store" and scope != "store":
                    continue
                elif cat == "Persistent" and scope != "persistent":
                    continue
                elif cat == "Defines" and scope != "define":
                    continue
                elif cat.startswith("File: "):
                    target_f = cat[6:]
                    if meta["file_short"] != target_f:
                        continue
                elif cat not in ("All", "Watchlist", "Modified", "Store", "Persistent", "Defines"):
                    if meta["category"] != cat:
                        continue

                val, exists = self._raw_get(var_key, scope)
                val_repr = _pulse_short_repr(val, 64) if exists else "<unset>"
                if q:
                    haystack = (var_key + " " + meta["category"] + " " + meta["file_short"] + " " + val_repr).lower()
                    if q not in haystack:
                        continue

                results.append({
                    "key": var_key,
                    "name": meta["name"],
                    "scope": scope,
                    "category": meta["category"],
                    "file": meta["file"],
                    "file_short": meta["file_short"],
                    "line": meta["line"],
                    "default_expr": meta["default_expr"],
                    "value": val,
                    "val_repr": val_repr,
                    "type": _pulse_type_name(val),
                    "watched": var_key in wl,
                    "modified": self.is_modified_from_default(var_key),
                })

            # Sort watched items first, then alphabetically
            results.sort(key=lambda x: (0 if x["watched"] else 1, x["key"].lower()))
            return results

        # ------------------------------------------------------------------
        # 4. Scene Teleporter & Choice Condition Unlocker
        # ------------------------------------------------------------------
        def get_current_file_line(self):
            try:
                fn, ln = renpy.get_filename_line()
                fn_short = os.path.basename(fn.replace("\\", "/"))
                return fn_short, ln
            except Exception:
                return "unknown", 0

        def get_filtered_labels(self, query=None):
            q = (query if query is not None else self.label_search).strip().lower()
            if not q:
                return self.labels
            return [
                l for l in self.labels
                if q in l["name"].lower() or q in l["file_short"].lower()
            ]

        def jump_to_label(self, label_name):
            if not renpy.has_label(label_name):
                self.add_toast("Label not found: " + str(label_name), "#FF4444")
                return
            self.add_toast("Jumping to " + str(label_name), "#00F7FF")
            renpy.hide_screen("pulse_devtools_overlay")
            renpy.jump_out_of_context(label_name)

        def call_label_in_context(self, label_name):
            if not renpy.has_label(label_name):
                self.add_toast("Label not found: " + str(label_name), "#FF4444")
                return
            self.add_toast("Calling " + str(label_name), "#00FF88")
            renpy.hide_screen("pulse_devtools_overlay")
            renpy.call_in_new_context(label_name)

        def get_relevant_menus(self):
            """Return menus belonging to the current label or near the current file & line."""
            fn_short, cur_ln = self.get_current_file_line()
            matched = []
            for m in self.menus:
                if m["label"] == self.current_label or (m["file_short"] == fn_short and abs(m["line"] - cur_ln) <= 350):
                    annotated_choices = []
                    for ch in m["choices"]:
                        cond = ch["condition"]
                        passed = True
                        vars_info = []
                        if cond:
                            try:
                                passed = bool(eval(cond, store.__dict__))
                            except Exception:
                                passed = False
                            # Extract referenced identifiers
                            tokens = re.findall(r"\b(persistent\.[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*)\b", cond)
                            seen_t = set()
                            for tok in tokens:
                                if tok in ("and", "or", "not", "True", "False", "None", "in", "is") or tok in seen_t:
                                    continue
                                if tok in self.var_meta or hasattr(store, tok) or tok.startswith("persistent."):
                                    val, ok = self._raw_get(tok)
                                    if ok and not callable(val):
                                        seen_t.add(tok)
                                        vars_info.append(tok + "=" + _pulse_short_repr(val, 20))
                        annotated_choices.append({
                            "caption": ch["caption"],
                            "condition": cond,
                            "line": ch["line"],
                            "passed": passed,
                            "vars_summary": ", ".join(vars_info),
                        })
                    matched.append({
                        "name": m["name"],
                        "file_short": m["file_short"],
                        "line": m["line"],
                        "label": m["label"],
                        "choices": annotated_choices,
                    })
            return matched[:8]

        def force_satisfy_condition(self, cond_str):
            """Parse `if` condition expressions and set store/persistent variables so the condition evaluates to True."""
            if not cond_str:
                return
            changed_any = False
            # 1. Handle binary comparisons: `var >= 10`, `var == True`, `var < 5`, etc.
            comp_pattern = re.compile(r"\b(persistent\.[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*(-?\d+(?:\.\d+)?|True|False|'[^']*'|" + r'"[^"]*")')
            matched_vars = set()
            for m in comp_pattern.finditer(cond_str):
                var_key, op, rhs_raw = m.group(1), m.group(2), m.group(3)
                matched_vars.add(var_key)
                try:
                    target = eval(rhs_raw, store.__dict__)
                except Exception:
                    continue
                cur_val = self.get_value(var_key)
                new_val = target
                if op == ">=":
                    new_val = target if (cur_val is None or cur_val < target) else cur_val
                elif op == ">":
                    new_val = (target + 1) if isinstance(target, int) else (target + 0.1)
                elif op == "<=":
                    new_val = target if (cur_val is None or cur_val > target) else cur_val
                elif op == "<":
                    new_val = (target - 1) if isinstance(target, int) else (target - 0.1)
                elif op == "==":
                    new_val = target
                elif op == "!=":
                    if isinstance(target, bool):
                        new_val = not target
                    elif isinstance(target, (int, float)):
                        new_val = target + 1
                    else:
                        new_val = str(target) + "_1"
                self.set_value(var_key, new_val, source="ForceUnlock")
                changed_any = True

            # 2. Handle `not var_name`
            for m in re.finditer(r"\bnot\s+(persistent\.[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*)\b", cond_str):
                var_key = m.group(1)
                if var_key not in matched_vars and (var_key in self.var_meta or hasattr(store, var_key)):
                    matched_vars.add(var_key)
                    self.set_value(var_key, False, source="ForceUnlock")
                    changed_any = True

            # 3. Handle bare truthy variable flags (`if ayase_shield_1 and ...`)
            for m in re.finditer(r"\b(persistent\.[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*)\b", cond_str):
                var_key = m.group(1)
                if var_key in ("and", "or", "not", "True", "False", "None", "in", "is") or var_key in matched_vars:
                    continue
                if var_key in self.var_meta or hasattr(store, var_key):
                    val = self.get_value(var_key)
                    if isinstance(val, bool):
                        self.set_value(var_key, True, source="ForceUnlock")
                        changed_any = True
                    elif isinstance(val, (int, float)) and val == 0:
                        self.set_value(var_key, 1, source="ForceUnlock")
                        changed_any = True

            if changed_any:
                self.add_toast("Condition unlocked: " + cond_str[:36], "#00FF88")
            else:
                self.add_toast("Could not auto-solve: " + cond_str[:36], "#FFB800")

        # ------------------------------------------------------------------
        # 5. Route Presets / State Snapshots ("Loadouts")
        # ------------------------------------------------------------------
        def _presets_dir(self):
            d = os.path.join(renpy.config.savedir, "pulse_presets")
            if not os.path.exists(d):
                try:
                    os.makedirs(d)
                except Exception:
                    pass
            return d

        def list_presets(self):
            d = self._presets_dir()
            presets = []
            if not os.path.exists(d):
                return presets
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".json"):
                    full = os.path.join(d, fn)
                    try:
                        with open(full, "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                        presets.append({
                            "filename": fn,
                            "name": data.get("name", fn[:-5]),
                            "label": data.get("label", "unknown"),
                            "created": data.get("created", ""),
                            "var_count": len(data.get("store_vars", {})),
                        })
                    except Exception:
                        continue
            return presets

        def save_preset(self, name=None):
            preset_name = (name if name is not None else self.preset_name_input).strip()
            if not preset_name:
                preset_name = "Preset_" + _pulse_time.strftime("%H%M%S")
            safe_fn = re.sub(r"[^A-Za-z0-9_\- ]", "_", preset_name).strip().replace(" ", "_") + ".json"
            store_vars = {}
            for var_key, meta in self.var_meta.items():
                if meta["scope"] == "store":
                    val, exists = self._raw_get(var_key, "store")
                    if exists and isinstance(val, (bool, int, float, str, list, dict)):
                        try:
                            json.dumps(val)
                            store_vars[var_key] = val
                        except Exception:
                            pass
            payload = {
                "name": preset_name,
                "label": self.current_label,
                "created": _pulse_time.strftime("%Y-%m-%d %H:%M:%S"),
                "store_vars": store_vars,
            }
            full_path = os.path.join(self._presets_dir(), safe_fn)
            try:
                with open(full_path, "w", encoding="utf-8") as fp:
                    json.dump(payload, fp, indent=2)
                self.preset_status_msg = "Saved preset: " + preset_name
                self.add_toast("Saved preset: " + preset_name, "#00FF88")
            except Exception as e:
                self.preset_status_msg = "Error saving preset: " + str(e)
            renpy.restart_interaction()

        def load_preset(self, filename, also_jump=False):
            full_path = os.path.join(self._presets_dir(), filename)
            if not os.path.exists(full_path):
                return
            try:
                with open(full_path, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                store_vars = data.get("store_vars", {})
                for k, v in store_vars.items():
                    setattr(store, k, v)
                self.take_baseline_snapshot()
                pname = data.get("name", filename)
                self.preset_status_msg = "Loaded preset: " + pname + " (" + str(len(store_vars)) + " vars)"
                self.add_toast("Loaded preset: " + pname, "#00F7FF")
                if also_jump and data.get("label") and renpy.has_label(data["label"]):
                    self.jump_to_label(data["label"])
            except Exception as e:
                self.preset_status_msg = "Failed to load: " + str(e)
            renpy.restart_interaction()

        def delete_preset(self, filename):
            full_path = os.path.join(self._presets_dir(), filename)
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
                    self.preset_status_msg = "Deleted " + filename
            except Exception:
                pass
            renpy.restart_interaction()

        # ------------------------------------------------------------------
        # 6. Live Screen, Layer & Audio Inspector
        # ------------------------------------------------------------------
        def get_active_screens(self):
            active = []
            try:
                for layer in ("screens", "overlay", "transient", "master"):
                    scr_list = renpy.display.screen.screens_by_name
                    for sname in sorted(scr_list.keys()):
                        if renpy.get_screen(sname, layer=layer):
                            active.append({"name": sname, "layer": layer})
            except Exception:
                pass
            return active

        def get_all_screen_names(self, query=None):
            q = (query if query is not None else self.screen_search).strip().lower()
            try:
                names = sorted([k[0] for k in renpy.display.screen.screens.keys() if isinstance(k, tuple) and len(k) > 0])
                # Deduplicate
                seen = set()
                unique = []
                for n in names:
                    if n not in seen and not n.startswith("_"):
                        seen.add(n)
                        if not q or q in n.lower():
                            unique.append(n)
                return unique[:60]
            except Exception:
                return []

        def toggle_screen_by_name(self, sname):
            try:
                if renpy.get_screen(sname):
                    renpy.hide_screen(sname)
                    self.add_toast("Hidden screen: " + sname, "#FFB800")
                else:
                    renpy.show_screen(sname)
                    self.add_toast("Showing screen: " + sname, "#00FF88")
            except Exception as e:
                self.add_toast("Screen error: " + str(e), "#FF4444")
            renpy.restart_interaction()

        def get_showing_images(self):
            items = []
            for layer in ("master", "transient", "overlay"):
                try:
                    tags = renpy.get_showing_tags(layer=layer)
                    for t in sorted(tags):
                        attrs = renpy.get_attributes(t, layer=layer) or ()
                        full_name = " ".join([t] + list(attrs))
                        items.append({"tag": t, "full": full_name, "layer": layer})
                except Exception:
                    pass
            return items

        def hide_showing_image(self, tag, layer="master"):
            try:
                renpy.hide(tag, layer=layer)
                self.add_toast("Hidden image: " + tag, "#FFB800")
            except Exception:
                pass
            renpy.restart_interaction()

        def _get_audio_channels_map(self):
            chans = {}
            try:
                import renpy.audio.audio as _ra
                raw = getattr(_ra, "channels", None)
                if isinstance(raw, dict):
                    chans.update(raw)
            except Exception:
                pass
            if not chans:
                try:
                    aud_pkg = getattr(renpy, "audio", None)
                    aud_mod = getattr(aud_pkg, "audio", None) if aud_pkg is not None else None
                    raw = getattr(aud_mod, "channels", None) if aud_mod is not None else None
                    if isinstance(raw, dict):
                        chans.update(raw)
                except Exception:
                    pass
            if not chans:
                try:
                    import renpy.audio.music as _rm
                    get_ch = getattr(_rm, "get_channel", None)
                    if callable(get_ch):
                        for cname in ("music", "music_1", "music_2", "sound", "sound_1", "sound_2", "voice", "audio", "ambient", "movie"):
                            try:
                                cobj = get_ch(cname)
                                if cobj is not None:
                                    chans[cname] = cobj
                            except Exception:
                                pass
                except Exception:
                    pass
            return chans

        def get_audio_channels_status(self):
            channels = []
            self.last_audio_error = ""
            try:
                chan_dict = self._get_audio_channels_map()
                prefs = getattr(renpy.game, "preferences", None)
                pref_vols = getattr(prefs, "volumes", {}) if prefs else {}
                pref_mute = getattr(prefs, "mute", {}) if prefs else {}
                get_vol_fn = getattr(prefs, "get_volume", None) if prefs else None
                get_mute_fn = getattr(prefs, "get_mute", None) if prefs else None

                core_order = ["music", "sound", "voice", "audio", "music_1", "music_2", "sound_1", "sound_2", "ambient"]
                seen = set()
                ordered_names = []
                for cname in core_order:
                    if cname in chan_dict or cname in ("music", "sound", "voice", "audio"):
                        if cname not in seen:
                            ordered_names.append(cname)
                            seen.add(cname)
                for cname in sorted(list(chan_dict.keys()), key=lambda x: str(x)):
                    if cname not in seen:
                        ordered_names.append(cname)
                        seen.add(cname)

                for ch_name in ordered_names:
                    try:
                        ch_obj = chan_dict.get(ch_name)
                        if ch_obj is None:
                            try:
                                import renpy.audio.music as _rm
                                get_ch = getattr(_rm, "get_channel", None)
                                if callable(get_ch):
                                    ch_obj = get_ch(ch_name)
                            except Exception:
                                ch_obj = None

                        playing = None
                        try:
                            playing = renpy.music.get_playing(channel=ch_name)
                        except Exception:
                            playing = None

                        queue_items = []
                        if ch_obj is not None:
                            try:
                                raw_queue = getattr(ch_obj, "queue", None) or []
                                for q in list(raw_queue):
                                    q_fn = getattr(q, "filename", q)
                                    if q_fn:
                                        q_str = str(q_fn)
                                        queue_items.append({
                                            "file": q_str,
                                            "short": os.path.basename(q_str.replace("\\", "/")),
                                            "loop": bool(getattr(q, "loop", False)),
                                        })
                            except Exception:
                                pass

                        is_registered = (ch_name in chan_dict) or (ch_name in ("music", "sound", "voice", "audio"))
                        if playing or queue_items or is_registered:
                            paused = False
                            try:
                                paused = bool(renpy.music.get_pause(channel=ch_name))
                            except Exception:
                                paused = False

                            pos = -1.0
                            dur = 0.0
                            if playing:
                                try:
                                    p_val = renpy.music.get_pos(channel=ch_name)
                                    if p_val is None and ch_obj is not None and hasattr(ch_obj, "get_pos"):
                                        p_val = ch_obj.get_pos()
                                    if p_val is not None:
                                        pos = float(p_val)
                                except Exception:
                                    pos = -1.0
                                try:
                                    d_val = renpy.music.get_duration(channel=ch_name)
                                    if d_val is None and ch_obj is not None and hasattr(ch_obj, "get_duration"):
                                        d_val = ch_obj.get_duration()
                                    if d_val is not None:
                                        dur = float(d_val)
                                except Exception:
                                    dur = 0.0

                            default_mixer = "sfx" if (str(ch_name) in ("sound", "sound_1", "sound_2", "audio")) else ("voice" if "voice" in str(ch_name) else "music")
                            raw_mixer = getattr(ch_obj, "mixer", None) if ch_obj is not None else None
                            mixer = str(raw_mixer or default_mixer)

                            raw_chan_vol = getattr(ch_obj, "chan_volume", 1.0) if ch_obj is not None else 1.0
                            try:
                                chan_vol = round(float(1.0 if raw_chan_vol is None else raw_chan_vol), 2)
                            except Exception:
                                chan_vol = 1.0

                            raw_mixer_vol = None
                            try:
                                if callable(get_vol_fn):
                                    raw_mixer_vol = get_vol_fn(mixer)
                                elif isinstance(pref_vols, dict):
                                    raw_mixer_vol = pref_vols.get(mixer, 1.0)
                            except Exception:
                                raw_mixer_vol = 1.0
                            try:
                                mixer_vol = round(float(1.0 if raw_mixer_vol is None else raw_mixer_vol), 2)
                            except Exception:
                                mixer_vol = 1.0

                            muted = False
                            try:
                                if callable(get_mute_fn):
                                    muted = bool(get_mute_fn(mixer))
                                elif isinstance(pref_mute, dict):
                                    muted = bool(pref_mute.get(mixer, False))
                            except Exception:
                                muted = False

                            progress_pct = 0.0
                            if dur > 0.0 and pos >= 0.0:
                                progress_pct = round(min(100.0, max(0.0, 100.0 * pos / dur)), 1)

                            channels.append({
                                "channel": str(ch_name),
                                "playing": str(playing) if playing else None,
                                "short": os.path.basename(str(playing).replace("\\", "/")) if playing else "Idle",
                                "paused": paused,
                                "pos": round(pos, 1) if pos >= 0.0 else 0.0,
                                "duration": round(dur, 1) if dur > 0.0 else 0.0,
                                "progress_pct": progress_pct,
                                "mixer": mixer,
                                "chan_volume": chan_vol,
                                "mixer_volume": mixer_vol,
                                "muted": muted,
                                "queue": queue_items,
                            })
                    except Exception:
                        continue
            except Exception as e:
                self.last_audio_error = str(e)
            return channels

        def toggle_audio_pause(self, ch_name):
            try:
                cur_pause = bool(renpy.music.get_pause(channel=ch_name))
                renpy.music.set_pause(not cur_pause, channel=ch_name)
                self.add_toast(("Resumed " if cur_pause else "Paused ") + ch_name, "#00F7FF")
            except Exception as e:
                self.add_toast("Audio pause error: " + str(e), "#FF4444")
            renpy.restart_interaction()

        def set_audio_volume(self, ch_name, new_vol):
            try:
                clamped = round(min(1.0, max(0.0, float(new_vol))), 2)
                renpy.music.set_volume(clamped, delay=0.05, channel=ch_name)
                self.add_toast(ch_name + " volume -> " + str(int(clamped * 100)) + "%", "#00FF88")
            except Exception as e:
                self.add_toast("Audio volume error: " + str(e), "#FF4444")
            renpy.restart_interaction()

        def clear_audio_queue(self, ch_name):
            try:
                chan_dict = self._get_audio_channels_map()
                ch_obj = chan_dict.get(ch_name)
                if ch_obj is not None and hasattr(ch_obj, "queue"):
                    ch_obj.queue = []
                    self.add_toast("Cleared queue on " + ch_name, "#FFB800")
            except Exception as e:
                self.add_toast("Queue clear error: " + str(e), "#FF4444")
            renpy.restart_interaction()

        def stop_audio_channel(self, ch_name):
            try:
                renpy.music.stop(channel=ch_name, fadeout=0.3)
                self.add_toast("Stopped channel: " + ch_name, "#FFB800")
            except Exception:
                pass
            renpy.restart_interaction()

        # ------------------------------------------------------------------
        # 6B. Performance, Memory & Custom UI Lag Monitor
        # ------------------------------------------------------------------
        def _perf_clock(self):
            fn = getattr(_pulse_time, "perf_counter", None)
            if fn is not None:
                return fn()
            return _pulse_time.time()

        def _extract_screen_name(self, scr_disp):
            raw_name = getattr(scr_disp, "screen_name", None)
            if isinstance(raw_name, (tuple, list)) and raw_name:
                return str(raw_name[0])
            if raw_name:
                return str(raw_name)
            scr_obj = getattr(scr_disp, "screen", None)
            return str(getattr(scr_obj, "name", "unknown"))

        def _record_screen_sample(self, sname, kind, dt_ms):
            st = self.ui_prof_stats.get(sname)
            if st is None:
                st = {
                    "updates": 0,
                    "update_ms_total": 0.0,
                    "update_ms_peak": 0.0,
                    "renders": 0,
                    "render_ms_total": 0.0,
                    "render_ms_peak": 0.0,
                }
                self.ui_prof_stats[sname] = st
            if kind == "update":
                st["updates"] += 1
                st["update_ms_total"] += dt_ms
                if dt_ms > st["update_ms_peak"]:
                    st["update_ms_peak"] = dt_ms
            else:
                st["renders"] += 1
                st["render_ms_total"] += dt_ms
                if dt_ms > st["render_ms_peak"]:
                    st["render_ms_peak"] = dt_ms

        def _install_screen_profiler_hooks(self):
            ScreenCls = getattr(renpy.display.screen, "ScreenDisplayable", None)
            if ScreenCls is None:
                return False
            if getattr(ScreenCls, "_pulse_wrapped", False):
                return True

            orig_update = ScreenCls.update
            orig_render = ScreenCls.render
            ScreenCls._pulse_orig_update = orig_update
            ScreenCls._pulse_orig_render = orig_render

            def _wrapped_update(scr_self, *args, **kwargs):
                mgr = getattr(store, "_pulse", None)
                if not mgr or not mgr.ui_profiler_enabled:
                    return orig_update(scr_self, *args, **kwargs)
                sname = mgr._extract_screen_name(scr_self)
                if sname.startswith("pulse_"):
                    return orig_update(scr_self, *args, **kwargs)
                t0 = mgr._perf_clock()
                try:
                    return orig_update(scr_self, *args, **kwargs)
                finally:
                    dt_ms = (mgr._perf_clock() - t0) * 1000.0
                    mgr._record_screen_sample(sname, "update", dt_ms)

            def _wrapped_render(scr_self, w, h, st, at):
                mgr = getattr(store, "_pulse", None)
                if not mgr or not mgr.ui_profiler_enabled:
                    return orig_render(scr_self, w, h, st, at)
                sname = mgr._extract_screen_name(scr_self)
                if sname.startswith("pulse_"):
                    return orig_render(scr_self, w, h, st, at)
                t0 = mgr._perf_clock()
                try:
                    return orig_render(scr_self, w, h, st, at)
                finally:
                    dt_ms = (mgr._perf_clock() - t0) * 1000.0
                    mgr._record_screen_sample(sname, "render", dt_ms)

            ScreenCls.update = _wrapped_update
            ScreenCls.render = _wrapped_render
            ScreenCls._pulse_wrapped = True
            return True

        def _restore_screen_profiler_hooks(self):
            ScreenCls = getattr(renpy.display.screen, "ScreenDisplayable", None)
            if ScreenCls is None or not getattr(ScreenCls, "_pulse_wrapped", False):
                return
            orig_update = getattr(ScreenCls, "_pulse_orig_update", None)
            orig_render = getattr(ScreenCls, "_pulse_orig_render", None)
            if orig_update is not None:
                ScreenCls.update = orig_update
            if orig_render is not None:
                ScreenCls.render = orig_render
            ScreenCls._pulse_wrapped = False

        def toggle_ui_profiler(self):
            if self.ui_profiler_enabled:
                self.ui_profiler_enabled = False
                self._restore_screen_profiler_hooks()
                self.add_toast("Live UI Profiler: OFF", "#FFB800")
            else:
                if self._install_screen_profiler_hooks():
                    self.ui_prof_stats = {}
                    self.ui_prof_window_start = self._perf_clock()
                    self.ui_profiler_enabled = True
                    self.add_toast("Live UI Profiler: ON (measuring screens)", "#00FF88")
                else:
                    self.add_toast("ScreenDisplayable not found", "#FF4444")
            self.get_resource_metrics(force=True)
            renpy.restart_interaction()

        def reset_ui_profiler(self):
            self.ui_prof_stats = {}
            self.ui_prof_window_start = self._perf_clock()
            self.get_resource_metrics(force=True)
            self.add_toast("Reset UI Profiler counters", "#00F7FF")
            renpy.restart_interaction()

        def trigger_free_memory(self):
            try:
                renpy.free_memory()
                self.get_resource_metrics(force=True)
                self.add_toast("Freed unused textures, cache & GC", "#00FF88")
            except Exception as e:
                self.add_toast("Free memory error: " + str(e), "#FF4444")
            renpy.restart_interaction()

        def enable_engine_screen_profile(self, sname):
            if not sname:
                return
            try:
                renpy.profile_screen(
                    sname,
                    predict=True,
                    show=True,
                    update=True,
                    request=True,
                    time=True,
                )
                self.add_toast("Engine profiling '" + sname + "' -> profile_screen.txt", "#00F7FF")
            except Exception as e:
                self.add_toast("Profile error: " + str(e), "#FF4444")
            renpy.restart_interaction()

        def _audit_displayable_tree(self, root, max_nodes=2500):
            stats = {
                "nodes": 0,
                "transforms": 0,
                "focus_masks": 0,
                "timers": 0,
                "viewports": 0,
                "truncated": False,
            }
            if root is None:
                return stats

            TransformCls = getattr(getattr(renpy.display, "transform", None), "Transform", None)
            TimerCls = getattr(getattr(renpy.display, "behavior", None), "Timer", None)
            ViewportCls = getattr(getattr(renpy.display, "viewport", None), "Viewport", None)

            visited = set()
            stack = [root]
            while stack:
                node = stack.pop()
                if node is None:
                    continue
                nid = id(node)
                if nid in visited:
                    continue
                visited.add(nid)
                stats["nodes"] += 1

                if TransformCls is not None and isinstance(node, TransformCls):
                    stats["transforms"] += 1
                if TimerCls is not None and isinstance(node, TimerCls):
                    stats["timers"] += 1
                if ViewportCls is not None and isinstance(node, ViewportCls):
                    stats["viewports"] += 1

                fm = getattr(node, "focus_mask", None)
                if fm is not None and fm is not False:
                    stats["focus_masks"] += 1

                if stats["nodes"] >= max_nodes:
                    stats["truncated"] = True
                    break

                children = getattr(node, "children", None)
                if children:
                    try:
                        for ch in children:
                            if ch is not None and id(ch) not in visited:
                                stack.append(ch)
                    except TypeError:
                        pass
                single_child = getattr(node, "child", None)
                if single_child is not None and id(single_child) not in visited:
                    stack.append(single_child)

            return stats

        def audit_active_screens(self):
            results = []
            seen = set()
            scr_dict = getattr(renpy.display.screen, "screens_by_name", {})
            elapsed = max(0.1, (self._perf_clock() - self.ui_prof_window_start)) if self.ui_profiler_enabled and self.ui_prof_window_start else 1.0

            for layer in ("screens", "overlay", "transient", "master"):
                for sname in sorted(scr_dict.keys()):
                    if sname.startswith("pulse_") or (sname, layer) in seen:
                        continue
                    try:
                        scr = renpy.get_screen(sname, layer=layer)
                    except Exception:
                        scr = None
                    if scr is None:
                        continue
                    seen.add((sname, layer))

                    tree = self._audit_displayable_tree(getattr(scr, "child", None))
                    scr_def = getattr(scr, "screen", None)
                    predict_flag = getattr(scr_def, "predict", None)
                    prof = self.ui_prof_stats.get(sname)

                    avg_upd_ms = 0.0
                    peak_upd_ms = 0.0
                    upd_per_sec = 0.0
                    avg_ren_ms = 0.0
                    peak_ren_ms = 0.0
                    upd_count = 0
                    ren_count = 0
                    if prof:
                        upd_count = prof["updates"]
                        ren_count = prof["renders"]
                        if upd_count > 0:
                            avg_upd_ms = round(prof["update_ms_total"] / upd_count, 2)
                            peak_upd_ms = round(prof["update_ms_peak"], 2)
                            upd_per_sec = round(upd_count / elapsed, 1)
                        if ren_count > 0:
                            avg_ren_ms = round(prof["render_ms_total"] / ren_count, 2)
                            peak_ren_ms = round(prof["render_ms_peak"], 2)

                    hints = []
                    if avg_upd_ms >= 8.0 or peak_upd_ms >= 16.0:
                        hints.append("Slow update (" + str(peak_upd_ms) + "ms peak)")
                    if upd_per_sec >= 8.0:
                        hints.append("High update rate (" + str(upd_per_sec) + "/s)")
                    if avg_ren_ms >= 8.0 or peak_ren_ms >= 16.0:
                        hints.append("Slow render (" + str(peak_ren_ms) + "ms peak)")
                    if tree["nodes"] >= 350:
                        hints.append("Heavy tree (" + str(tree["nodes"]) + ("+" if tree["truncated"] else "") + " nodes)")
                    if tree["focus_masks"] >= 4:
                        hints.append("Pixel focus_mask x" + str(tree["focus_masks"]))
                    if tree["transforms"] >= 12:
                        hints.append("Active Transforms x" + str(tree["transforms"]))
                    if tree["timers"] >= 2:
                        hints.append("Timers x" + str(tree["timers"]))

                    severity = (
                        (peak_upd_ms * 10.0)
                        + (peak_ren_ms * 10.0)
                        + (upd_per_sec * 6.0)
                        + (tree["focus_masks"] * 12.0)
                        + (tree["transforms"] * 3.0)
                        + (tree["nodes"] * 0.2)
                    )

                    results.append({
                        "name": sname,
                        "layer": layer,
                        "nodes": tree["nodes"],
                        "truncated": tree["truncated"],
                        "transforms": tree["transforms"],
                        "focus_masks": tree["focus_masks"],
                        "timers": tree["timers"],
                        "viewports": tree["viewports"],
                        "predict": predict_flag,
                        "updates": upd_count,
                        "renders": ren_count,
                        "avg_upd_ms": avg_upd_ms,
                        "peak_upd_ms": peak_upd_ms,
                        "upd_per_sec": upd_per_sec,
                        "avg_ren_ms": avg_ren_ms,
                        "peak_ren_ms": peak_ren_ms,
                        "hints": hints,
                        "severity": round(severity, 1),
                    })

            results.sort(key=lambda x: (-x["severity"], x["name"]))
            return results

        def get_resource_metrics(self, force=False):
            now = _pulse_time.time()
            if not force and self.perf_cache and (now - self.last_perf_sample_time) < 2.0:
                return self.perf_cache

            tex_mb = 0.0
            tex_count = 0
            try:
                if hasattr(renpy, "get_texture_size"):
                    t_bytes, t_cnt = renpy.get_texture_size()
                    tex_mb = round(float(t_bytes) / 1024.0 / 1024.0, 1)
                    tex_count = int(t_cnt)
            except Exception:
                pass

            cache_mb = 0.0
            cache_total_mb = 0.0
            cache_limit_mb = 0.0
            cache_pct = 0.0
            try:
                cache_obj = getattr(getattr(renpy.display, "im", None), "cache", None)
                if cache_obj is not None:
                    cur_px = cache_obj.get_current_size(2)
                    tot_px = cache_obj.get_total_size()
                    lim_px = max(1, getattr(cache_obj, "cache_limit", 1))
                    cache_mb = round(cur_px * 4.0 / 1024.0 / 1024.0, 1)
                    cache_total_mb = round(tot_px * 4.0 / 1024.0 / 1024.0, 1)
                    cache_limit_mb = round(lim_px * 4.0 / 1024.0 / 1024.0, 1)
                    cache_pct = round(100.0 * cur_px / float(lim_px), 1)
            except Exception:
                pass

            renderer_name = "unknown"
            gpu_name = ""
            try:
                if hasattr(renpy, "get_renderer_info"):
                    rinfo = renpy.get_renderer_info() or {}
                    renderer_name = str(rinfo.get("renderer", "unknown"))
                    gpu_name = str(rinfo.get("gpu_name") or rinfo.get("gpu_vendor") or "")
            except Exception:
                pass

            render_cache_count = 0
            try:
                rc = getattr(getattr(renpy.display, "render", None), "render_cache", None)
                if rc is not None:
                    render_cache_count = len(rc)
            except Exception:
                pass

            image_loads = []
            stall_count = 0
            try:
                raw_log = list(renpy.get_image_load_log())
                for ts, fn, preloaded in reversed(raw_log[-18:]):
                    is_pre = bool(preloaded)
                    if not is_pre:
                        stall_count += 1
                    image_loads.append({
                        "time": _pulse_time.strftime("%H:%M:%S", _pulse_time.localtime(ts)),
                        "file": str(fn),
                        "short": os.path.basename(str(fn).replace("\\", "/")),
                        "preloaded": is_pre,
                    })
            except Exception:
                pass

            prof_elapsed = 0.0
            if self.ui_profiler_enabled and self.ui_prof_window_start:
                prof_elapsed = round(max(0.0, self._perf_clock() - self.ui_prof_window_start), 1)

            self.perf_cache = {
                "tex_mb": tex_mb,
                "tex_count": tex_count,
                "cache_mb": cache_mb,
                "cache_total_mb": cache_total_mb,
                "cache_limit_mb": cache_limit_mb,
                "cache_pct": cache_pct,
                "renderer": renderer_name,
                "gpu_name": gpu_name,
                "store_count": len(store.__dict__),
                "persistent_count": len(persistent.__dict__),
                "render_cache_count": render_cache_count,
                "gc_counts": list(gc.get_count()),
                "image_loads": image_loads,
                "stall_count": stall_count,
                "screen_audit": self.audit_active_screens(),
                "profiler_enabled": self.ui_profiler_enabled,
                "profiler_elapsed": prof_elapsed,
                "sampled_at": _pulse_time.strftime("%H:%M:%S"),
            }
            self.last_perf_sample_time = now
            return self.perf_cache

        # ------------------------------------------------------------------
        # 6C. Visual Jump-to-Definition (VS Code & Code Editors)
        # ------------------------------------------------------------------
        def _resolve_gamedir_path(self, file_ref):
            if not file_ref:
                return None
            clean = str(file_ref).strip().replace("\\", "/")
            if clean in ("", "runtime", "persistent", "unknown"):
                return None
            if clean.startswith("game/"):
                clean = clean[5:]
            if ".." in clean.split("/"):
                return None

            gamedir_real = os.path.realpath(renpy.config.gamedir)
            direct = os.path.realpath(os.path.join(gamedir_real, clean))
            if (direct == gamedir_real or direct.startswith(gamedir_real + os.sep)) and os.path.isfile(direct):
                return direct

            # Fallback: search by basename inside gamedir
            target_base = os.path.basename(clean)
            if not target_base:
                return None
            for root, dirs, files in os.walk(gamedir_real):
                rel_root = os.path.relpath(root, gamedir_real).replace("\\", "/")
                if rel_root.startswith("saves") or rel_root.startswith("cache") or rel_root.startswith("tl"):
                    continue
                if target_base in files:
                    cand = os.path.realpath(os.path.join(root, target_base))
                    if cand.startswith(gamedir_real + os.sep) and os.path.isfile(cand):
                        return cand
            return None

        def _find_executable(self, names, extra_paths=None):
            path_dirs = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
            exts = [""]
            if sys.platform.startswith("win"):
                exts = [".cmd", ".exe", ".bat", ""]
            for d in path_dirs:
                for n in names:
                    for ext in exts:
                        cand = os.path.join(d, n + ext)
                        if os.path.isfile(cand):
                            return cand
            for p in (extra_paths or []):
                exp = os.path.expandvars(p)
                if os.path.isfile(exp):
                    return exp
            return None

        def open_in_editor(self, file_ref, line_no=1):
            full_path = self._resolve_gamedir_path(file_ref)
            if not full_path:
                self.add_toast("No .rpy source file for this item", "#FFB800")
                renpy.restart_interaction()
                return

            try:
                ln = max(1, int(line_no or 1))
            except Exception:
                ln = 1

            spawn_kw = {}
            if sys.platform.startswith("win"):
                spawn_kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

            # 1. Explicit user override via pulse_configure(editor_cmd=...)
            custom_cmd = _pulse_custom_filters.get("editor_cmd")
            if custom_cmd:
                try:
                    if isinstance(custom_cmd, (list, tuple)):
                        args = [str(a).replace("{file}", full_path).replace("{line}", str(ln)) for a in custom_cmd]
                        subprocess.Popen(args, **spawn_kw)
                    else:
                        cmd_str = str(custom_cmd).replace("{file}", full_path).replace("{line}", str(ln))
                        subprocess.Popen(cmd_str, shell=True, **spawn_kw)
                    self.add_toast("Opened " + os.path.basename(full_path) + ":" + str(ln), "#00FF88")
                    renpy.restart_interaction()
                    return
                except Exception:
                    pass

            # 2. Ren'Py configured editor (when launched from Ren'Py Launcher)
            if os.environ.get("RENPY_EDIT_PY") or getattr(renpy.config, "editor", None):
                try:
                    renpy.launch_editor([full_path], line=ln, transient=True)
                    self.add_toast("Opened " + os.path.basename(full_path) + ":" + str(ln), "#00FF88")
                    renpy.restart_interaction()
                    return
                except Exception:
                    pass

            # 3. Direct VS Code / Cursor / Sublime / Notepad++ detection
            vscode_exe = self._find_executable(
                ["code"],
                [
                    r"%LocalAppData%\Programs\Microsoft VS Code\bin\code.cmd",
                    r"%ProgramFiles%\Microsoft VS Code\bin\code.cmd",
                    r"%ProgramFiles(x86)%\Microsoft VS Code\bin\code.cmd",
                    "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
                ],
            )
            if vscode_exe:
                try:
                    subprocess.Popen([vscode_exe, "-g", full_path + ":" + str(ln)], **spawn_kw)
                    self.add_toast("VS Code -> " + os.path.basename(full_path) + ":" + str(ln), "#00FF88")
                    renpy.restart_interaction()
                    return
                except Exception:
                    pass

            cursor_exe = self._find_executable(
                ["cursor"],
                [r"%LocalAppData%\Programs\cursor\resources\app\bin\cursor.cmd"],
            )
            if cursor_exe:
                try:
                    subprocess.Popen([cursor_exe, "-g", full_path + ":" + str(ln)], **spawn_kw)
                    self.add_toast("Cursor -> " + os.path.basename(full_path) + ":" + str(ln), "#00FF88")
                    renpy.restart_interaction()
                    return
                except Exception:
                    pass

            subl_exe = self._find_executable(["subl"], [r"%ProgramFiles%\Sublime Text\subl.exe"])
            if subl_exe:
                try:
                    subprocess.Popen([subl_exe, full_path + ":" + str(ln)], **spawn_kw)
                    self.add_toast("Sublime -> " + os.path.basename(full_path) + ":" + str(ln), "#00FF88")
                    renpy.restart_interaction()
                    return
                except Exception:
                    pass

            # 4. OS fallback
            try:
                if sys.platform.startswith("win"):
                    os.startfile(full_path)
                else:
                    renpy.launch_editor([full_path], line=ln, transient=True)
                self.add_toast("Opened " + os.path.basename(full_path), "#00F7FF")
            except Exception as e:
                self.add_toast("Editor open failed: " + str(e), "#FF4444")
            renpy.restart_interaction()

        # ------------------------------------------------------------------
        # 6D. In-Game Asset & Style Previewer
        # ------------------------------------------------------------------
        def _get_image_file_info(self, img_name):
            disp_type = "Displayable"
            filename = None
            try:
                obj = renpy.get_registered_image(img_name)
                if obj is not None:
                    disp_type = type(obj).__name__
                    filename = getattr(obj, "filename", None)
                    if not filename:
                        ch = getattr(obj, "child", None)
                        if ch is not None:
                            filename = getattr(ch, "filename", None)
            except Exception:
                pass
            file_str = str(filename).replace("\\", "/") if filename else ""
            is_previewable_file = False
            if file_str:
                ext = os.path.splitext(file_str)[1].lower()
                if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"):
                    is_previewable_file = self._resolve_gamedir_path(file_str) is not None
            return {
                "type": disp_type,
                "file": file_str,
                "file_short": os.path.basename(file_str) if file_str else "",
                "has_file": is_previewable_file,
            }

        def get_registered_images_list(self, query=None, tag_filter=None, limit=180):
            q = (query if query is not None else self.asset_search).strip().lower()
            tf = tag_filter if tag_filter is not None else self.asset_tag_filter
            tags_set = set()
            all_names = []
            try:
                all_names = sorted(renpy.list_images())
            except Exception:
                all_names = []

            for n in all_names:
                parts = str(n).split(" ")
                if parts and parts[0]:
                    tags_set.add(parts[0])

            filtered = []
            for n in all_names:
                ns = str(n)
                tag = ns.split(" ")[0] if " " in ns else ns
                if tf and tf != "All" and tag != tf:
                    continue
                if q and q not in ns.lower():
                    continue
                filtered.append((ns, tag))

            items = []
            for ns, tag in filtered[:limit]:
                info = self._get_image_file_info(ns)
                items.append({
                    "name": ns,
                    "tag": tag,
                    "type": info["type"],
                    "file": info["file"],
                    "file_short": info["file_short"],
                    "has_file": info["has_file"],
                })
            return items, ["All"] + sorted(tags_set), len(filtered)

        def preview_image_on_master(self, img_name):
            if not img_name:
                return
            try:
                renpy.show(img_name, layer="master")
                self.add_toast("Shown on master: " + str(img_name), "#00FF88")
            except Exception as e:
                self.add_toast("Show image error: " + str(e), "#FF4444")
            renpy.restart_interaction()

        def get_styles_list(self, query=None, scope_filter=None, limit=180):
            q = (query if query is not None else self.style_search).strip().lower()
            sf = scope_filter if scope_filter is not None else self.style_scope_filter
            style_map = getattr(renpy.style, "styles", {}) or {}
            items = []
            total = 0
            for sname in sorted(style_map.keys()):
                if str(sname).startswith("_"):
                    continue
                sobj = style_map.get(sname)
                raw_props = getattr(sobj, "properties", None)
                has_custom = bool(raw_props)
                if sf == "Customized" and not has_custom:
                    continue
                if q and q not in str(sname).lower():
                    continue
                total += 1
                if len(items) < limit:
                    parent_obj = getattr(sobj, "parent", None)
                    parent_name = str(getattr(parent_obj, "name", "") or "") if parent_obj is not None else ""
                    if isinstance(parent_name, tuple):
                        parent_name = str(parent_name[0]) if parent_name else ""
                    items.append({
                        "name": str(sname),
                        "parent": parent_name,
                        "customized": has_custom,
                    })
            return items, total

        def inspect_style_details(self, style_name):
            style_map = getattr(renpy.style, "styles", {}) or {}
            sobj = style_map.get(style_name)
            if sobj is None:
                return None

            chain = []
            try:
                if hasattr(sobj, "inspect") and callable(sobj.inspect):
                    for s_entry, p_dict in sobj.inspect():
                        en = str(s_entry)
                        props_list = []
                        if isinstance(p_dict, dict):
                            for pk in sorted(p_dict.keys()):
                                props_list.append({"prop": str(pk), "val": _pulse_short_repr(p_dict[pk], 52)})
                        chain.append({"style": en, "props": props_list})
            except Exception:
                chain = []

            probe_keys = (
                "font", "size", "color", "hover_color", "insensitive_color",
                "background", "hover_background", "padding", "xpadding", "ypadding",
                "spacing", "line_spacing", "xalign", "yalign", "xsize", "ysize",
                "bold", "italic", "outlines",
            )
            resolved = []
            for pk in probe_keys:
                try:
                    val = getattr(sobj, pk)
                    if val is not None and val is not False and val != "" and val != 0:
                        resolved.append({"prop": pk, "val": _pulse_short_repr(val, 52)})
                except Exception:
                    pass

            parent_obj = getattr(sobj, "parent", None)
            parent_name = str(getattr(parent_obj, "name", "") or "") if parent_obj is not None else ""
            return {
                "name": str(style_name),
                "parent": parent_name,
                "chain": chain,
                "resolved": resolved,
            }

        # ------------------------------------------------------------------
        # 6E. Command History Macro Recorder & Runner
        # ------------------------------------------------------------------
        def _macros_dir(self):
            d = os.path.join(renpy.config.savedir, "pulse_macros")
            if not os.path.exists(d):
                try:
                    os.makedirs(d)
                except Exception:
                    pass
            return d

        def _record_macro_set(self, var_key, new_val):
            try:
                json.dumps(new_val)
                val_copy = copy.deepcopy(new_val)
                self.macro_steps.append({"op": "set", "key": var_key, "value": val_copy})
            except Exception:
                self.macro_steps.append({"op": "exec", "expr": var_key + " = " + repr(new_val)})

        def _record_macro_exec(self, expr):
            self.macro_steps.append({"op": "exec", "expr": str(expr)})

        def _record_macro_action(self, act_id, label):
            self.macro_steps.append({"op": "action", "id": str(act_id), "label": str(label)})

        def toggle_macro_recording(self):
            if self.macro_recording:
                self.macro_recording = False
                self.add_toast("Macro Recording Stopped (" + str(len(self.macro_steps)) + " steps)", "#FFB800")
            else:
                self.macro_steps = []
                self.macro_recording = True
                self.add_toast("Macro Recording ON — edit vars or run commands!", "#FF00D4")
            renpy.restart_interaction()

        def clear_macro_steps(self):
            self.macro_steps = []
            self.macro_status_msg = "Cleared recorded steps."
            renpy.restart_interaction()

        def _write_macro_file(self, macro_name, steps):
            clean_name = (macro_name or "").strip() or ("Macro_" + _pulse_time.strftime("%H%M%S"))
            safe_fn = re.sub(r"[^A-Za-z0-9_\- ]", "_", clean_name).strip().replace(" ", "_") + ".json"
            payload = {
                "name": clean_name,
                "created": _pulse_time.strftime("%Y-%m-%d %H:%M:%S"),
                "steps": list(steps),
            }
            full_path = os.path.join(self._macros_dir(), safe_fn)
            with open(full_path, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, indent=2)
            return clean_name

        def save_recorded_macro(self, name=None):
            if not self.macro_steps:
                self.macro_status_msg = "No steps recorded yet!"
                self.add_toast("Record at least 1 step first!", "#FFB800")
                renpy.restart_interaction()
                return
            try:
                saved_name = self._write_macro_file(name if name is not None else self.macro_name_input, self.macro_steps)
                self.macro_recording = False
                self.macro_status_msg = "Saved macro: " + saved_name + " (" + str(len(self.macro_steps)) + " steps)"
                self.add_toast("Saved Macro: " + saved_name, "#00FF88")
            except Exception as e:
                self.macro_status_msg = "Error saving macro: " + str(e)
            renpy.restart_interaction()

        def save_recent_diffs_as_macro(self, count=10, name=None):
            if not self.diff_log:
                self.add_toast("No diff history to save as macro!", "#FFB800")
                return
            steps = []
            for d in reversed(self.diff_log[:int(count)]):
                vkey = d["var_key"]
                nval = d["new_val"]
                try:
                    json.dumps(nval)
                    steps.append({"op": "set", "key": vkey, "value": copy.deepcopy(nval)})
                except Exception:
                    steps.append({"op": "exec", "expr": vkey + " = " + repr(nval)})
            try:
                mname = name if name is not None else ("Diffs_" + _pulse_time.strftime("%H%M%S"))
                saved_name = self._write_macro_file(mname, steps)
                self.macro_status_msg = "Saved " + str(len(steps)) + " diffs as Macro: " + saved_name
                self.add_toast("Saved Macro from Diffs: " + saved_name, "#00FF88")
            except Exception as e:
                self.macro_status_msg = "Error saving macro: " + str(e)
            renpy.restart_interaction()

        def list_macros(self):
            d = self._macros_dir()
            macros = []
            if not os.path.exists(d):
                return macros
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".json"):
                    full = os.path.join(d, fn)
                    try:
                        with open(full, "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                        steps = data.get("steps", [])
                        preview_parts = []
                        for st in steps[:4]:
                            if st.get("op") == "set":
                                preview_parts.append(str(st.get("key")) + "=" + _pulse_short_repr(st.get("value"), 16))
                            elif st.get("op") == "exec":
                                preview_parts.append(str(st.get("expr"))[:24])
                            elif st.get("op") == "action":
                                preview_parts.append("[" + str(st.get("label", st.get("id"))) + "]")
                        macros.append({
                            "filename": fn,
                            "name": data.get("name", fn[:-5]),
                            "created": data.get("created", ""),
                            "step_count": len(steps),
                            "summary": ", ".join(preview_parts) + ("..." if len(steps) > 4 else ""),
                        })
                    except Exception:
                        continue
            return macros

        def run_macro(self, filename):
            full_path = os.path.join(self._macros_dir(), filename)
            if not os.path.exists(full_path):
                return
            try:
                with open(full_path, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                steps = data.get("steps", [])
                mname = data.get("name", filename)
                self.suppress_macro_capture = True
                try:
                    for st in steps:
                        op = st.get("op")
                        if op == "set":
                            self.set_value(st.get("key", ""), st.get("value"), source="Macro")
                        elif op == "exec":
                            exec(str(st.get("expr", "")), store.__dict__)
                        elif op == "action":
                            self.run_registered_action(str(st.get("id", "")))
                finally:
                    self.suppress_macro_capture = False
                self.check_for_diffs()
                self.macro_status_msg = "Executed macro: " + mname + " (" + str(len(steps)) + " steps)"
                self.add_toast("Ran Macro: " + mname + " (" + str(len(steps)) + " steps)", "#00FF88")
            except Exception as e:
                self.macro_status_msg = "Macro error: " + str(e)
                self.add_toast("Macro error: " + str(e), "#FF4444")
            renpy.restart_interaction()

        def delete_macro(self, filename):
            full_path = os.path.join(self._macros_dir(), filename)
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
                    self.macro_status_msg = "Deleted macro " + filename
            except Exception:
                pass
            renpy.restart_interaction()

        # ------------------------------------------------------------------
        # 7. Safe Persistent Manager & Interactive Python Console
        # ------------------------------------------------------------------
        def backup_persistent_data(self):
            d = self._presets_dir()
            backup_path = os.path.join(d, "persistent_backup.json")
            data = {}
            for k, v in persistent.__dict__.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, (bool, int, float, str, list, dict)):
                    try:
                        json.dumps(v)
                        data[k] = v
                    except Exception:
                        pass
            try:
                with open(backup_path, "w", encoding="utf-8") as fp:
                    json.dump({"timestamp": _pulse_time.strftime("%Y-%m-%d %H:%M:%S"), "data": data}, fp, indent=2)
                self.add_toast("Backed up " + str(len(data)) + " persistent keys!", "#00FF88")
            except Exception as e:
                self.add_toast("Backup failed: " + str(e), "#FF4444")
            renpy.restart_interaction()

        def restore_persistent_backup(self):
            backup_path = os.path.join(self._presets_dir(), "persistent_backup.json")
            if not os.path.exists(backup_path):
                self.add_toast("No persistent_backup.json found!", "#FF4444")
                return
            try:
                with open(backup_path, "r", encoding="utf-8") as fp:
                    payload = json.load(fp)
                data = payload.get("data", {})
                for k, v in data.items():
                    setattr(persistent, k, v)
                renpy.save_persistent()
                self.take_baseline_snapshot()
                self.add_toast("Restored " + str(len(data)) + " persistent keys!", "#00F7FF")
            except Exception as e:
                self.add_toast("Restore failed: " + str(e), "#FF4444")
            renpy.restart_interaction()

        def reset_all_persistent_vars(self):
            self.backup_persistent_data()
            count = 0
            for var_key, meta in self.var_meta.items():
                if meta["scope"] == "persistent":
                    self.reset_var(var_key, source="PersistentReset")
                    count += 1
            renpy.save_persistent()
            self.add_toast("Reset " + str(count) + " persistent vars (backup saved)", "#FFB800")
            renpy.restart_interaction()

        def execute_console_command(self, cmd_str=None):
            expr = (cmd_str if cmd_str is not None else self.console_input).strip()
            if not expr:
                return
            is_err = False
            try:
                try:
                    res = eval(expr, store.__dict__)
                    out = repr(res)
                except SyntaxError:
                    exec(expr, store.__dict__)
                    out = "Executed statement successfully."
            except Exception as e:
                is_err = True
                out = type(e).__name__ + ": " + str(e)

            self.console_history.insert(0, {
                "expr": expr,
                "output": out,
                "is_error": is_err,
                "time": _pulse_time.strftime("%H:%M:%S"),
            })
            if len(self.console_history) > 40:
                self.console_history.pop()
            if not is_err and self.macro_recording and not self.suppress_macro_capture:
                self._record_macro_exec(expr)
            self.console_input = ""
            self.check_for_diffs()
            renpy.restart_interaction()

        def run_registered_action(self, act_id):
            for act in _pulse_registered_actions:
                if act["id"] == act_id:
                    try:
                        act["callback"]()
                        if self.macro_recording and not self.suppress_macro_capture:
                            self._record_macro_action(act_id, act["label"])
                        self.check_for_diffs()
                        self.add_toast("Ran: " + act["label"], "#00FF88")
                    except Exception as e:
                        self.add_toast("Action error: " + str(e), "#FF4444")
                    break
            renpy.restart_interaction()

        # ------------------------------------------------------------------
        # 8. Second-Window Localhost Server & Frameless App Launcher
        # ------------------------------------------------------------------
        def build_api_state_dict(self):
            fn_short, ln = self.get_current_file_line()
            vars_list = self.get_filtered_variables(category="All", query="")
            # Serialize safe JSON values
            clean_vars = []
            for v in vars_list:
                clean_vars.append({
                    "key": v["key"],
                    "name": v["name"],
                    "scope": v["scope"],
                    "category": v["category"],
                    "file": v["file"],
                    "file_short": v["file_short"],
                    "line": v["line"],
                    "val_repr": v["val_repr"],
                    "type": v["type"],
                    "watched": v["watched"],
                    "modified": v["modified"],
                    "bool_val": bool(v["value"]) if v["type"] == "bool" else False,
                })

            actions_list = []
            for act in _pulse_registered_actions:
                badge = ""
                if act.get("badge_fn"):
                    try:
                        badge = str(act["badge_fn"]())
                    except Exception:
                        badge = ""
                actions_list.append({
                    "id": act["id"],
                    "label": act["label"],
                    "category": act["category"],
                    "description": act["description"],
                    "badge": badge,
                })

            if not getattr(self, "_api_assets_cache", None):
                img_items, img_tags, img_total = self.get_registered_images_list(query="", tag_filter="All", limit=400)
                self._api_assets_cache = {"images": img_items, "tags": img_tags, "total": img_total}
            if not getattr(self, "_api_styles_cache", None):
                sty_items, sty_total = self.get_styles_list(query="", scope_filter="All", limit=400)
                self._api_styles_cache = {"items": sty_items, "total": sty_total}

            return {
                "game_name": str(getattr(config, "name", "Ren'Py Project")),
                "game_version": str(getattr(config, "version", "")),
                "current_label": self.current_label,
                "file_line": fn_short + ":" + str(ln),
                "hud_visible": _pulse_is_mini_hud_visible(),
                "categories": self.get_all_categories(),
                "variables": clean_vars,
                "diffs": [
                    {
                        "id": d["id"],
                        "var_key": d["var_key"],
                        "old_repr": d["old_repr"],
                        "new_repr": d["new_repr"],
                        "label": d["label"],
                        "file": d.get("file", ""),
                        "line": d.get("line", 1),
                        "file_line": d["file_line"],
                        "time": d["time"],
                        "source": d["source"],
                    }
                    for d in self.diff_log[:60]
                ],
                "menus": self.get_relevant_menus(),
                "labels": self.labels,
                "presets": self.list_presets(),
                "screens": self.get_active_screens(),
                "images": self.get_showing_images(),
                "audio": self.get_audio_channels_status(),
                "actions": actions_list,
                "console": self.console_history[:25],
                "perf": self.get_resource_metrics(force=False),
                "macro_recording": self.macro_recording,
                "macro_step_count": len(self.macro_steps),
                "macros": self.list_macros(),
                "asset_images": self._api_assets_cache["images"],
                "asset_tags": self._api_assets_cache["tags"],
                "asset_total": self._api_assets_cache["total"],
                "styles": self._api_styles_cache["items"],
                "selected_style": self.inspect_style_details(self.selected_style_name),
            }

        def refresh_api_cache(self):
            try:
                self.cached_api_payload = json.dumps(self.build_api_state_dict())
                self.last_cache_time = _pulse_time.time()
            except Exception:
                pass

        def enqueue_command(self, cmd_dict):
            with self.cmd_lock:
                self.cmd_queue.append(cmd_dict)

        def poll_cmd_queue(self):
            """Called by the lightweight 0.2s screen timer on the main thread."""
            toast_changed = self.prune_toasts()
            cmds = []
            with self.cmd_lock:
                if self.cmd_queue:
                    cmds = list(self.cmd_queue)
                    self.cmd_queue = []

            if not cmds:
                if _pulse_time.time() - self.last_cache_time > 0.4:
                    self.refresh_api_cache()
                if toast_changed:
                    renpy.restart_interaction()
                return

            for cmd in cmds:
                op = cmd.get("op")
                key = cmd.get("key", "")
                if op == "toggle":
                    self.toggle_bool(key, source="2ndWin")
                elif op == "step":
                    self.step_number(key, float(cmd.get("delta", 1)) if "." in str(cmd.get("delta", 1)) else int(cmd.get("delta", 1)), source="2ndWin")
                elif op == "set":
                    self.editing_var = key
                    self.apply_inline_edit(str(cmd.get("value", "")))
                elif op == "reset":
                    self.reset_var(key, source="2ndWin")
                elif op == "watch":
                    self.toggle_watch(key)
                elif op == "undo_diff":
                    self.undo_diff(int(cmd.get("id", 0)))
                elif op == "satisfy":
                    self.force_satisfy_condition(str(cmd.get("cond", "")))
                elif op == "jump":
                    self.jump_to_label(str(cmd.get("label", "")))
                elif op == "call":
                    self.call_label_in_context(str(cmd.get("label", "")))
                elif op == "save_preset":
                    self.save_preset(str(cmd.get("name", "Preset")))
                elif op == "load_preset":
                    self.load_preset(str(cmd.get("filename", "")), also_jump=bool(cmd.get("jump", False)))
                elif op == "delete_preset":
                    self.delete_preset(str(cmd.get("filename", "")))
                elif op == "reset_all_store":
                    self.reset_all_store_vars()
                elif op == "toggle_screen":
                    self.toggle_screen_by_name(str(cmd.get("screen", "")))
                elif op == "hide_image":
                    self.hide_showing_image(str(cmd.get("tag", "")), str(cmd.get("layer", "master")))
                elif op == "stop_audio":
                    self.stop_audio_channel(str(cmd.get("channel", "music")))
                elif op == "run_action":
                    self.run_registered_action(str(cmd.get("id", "")))
                elif op == "console":
                    self.execute_console_command(str(cmd.get("expr", "")))
                elif op == "backup_persistent":
                    self.backup_persistent_data()
                elif op == "restore_persistent":
                    self.restore_persistent_backup()
                elif op == "toggle_hud":
                    _pulse_toggle_mini_hud()
                elif op == "toggle_ui_profiler":
                    self.toggle_ui_profiler()
                elif op == "reset_ui_profiler":
                    self.reset_ui_profiler()
                elif op == "free_memory":
                    self.trigger_free_memory()
                elif op == "profile_screen_file":
                    self.enable_engine_screen_profile(str(cmd.get("screen", "")))
                elif op == "refresh_perf":
                    self.get_resource_metrics(force=True)
                elif op == "open_editor":
                    self.open_in_editor(str(cmd.get("file", "")), int(cmd.get("line", 1)))
                elif op == "toggle_audio_pause":
                    self.toggle_audio_pause(str(cmd.get("channel", "music")))
                elif op == "set_audio_volume":
                    self.set_audio_volume(str(cmd.get("channel", "music")), float(cmd.get("volume", 1.0)))
                elif op == "clear_audio_queue":
                    self.clear_audio_queue(str(cmd.get("channel", "music")))
                elif op == "toggle_macro_rec":
                    self.toggle_macro_recording()
                elif op == "clear_macro_steps":
                    self.clear_macro_steps()
                elif op == "save_macro":
                    self.save_recorded_macro(str(cmd.get("name", "Test Scenario")))
                elif op == "save_diffs_macro":
                    self.save_recent_diffs_as_macro(int(cmd.get("count", 10)), cmd.get("name"))
                elif op == "run_macro":
                    self.run_macro(str(cmd.get("filename", "")))
                elif op == "delete_macro":
                    self.delete_macro(str(cmd.get("filename", "")))
                elif op == "show_asset_image":
                    self.preview_image_on_master(str(cmd.get("name", "")))
                elif op == "select_style":
                    self.selected_style_name = str(cmd.get("name", "default"))
                elif op == "refresh_assets":
                    self._api_assets_cache = None
                    self._api_styles_cache = None

            self.refresh_api_cache()
            renpy.restart_interaction()

        def start_http_bridge(self):
            if self.server_running or ThreadingHTTPServer is None:
                return
            # Reuse existing server across Shift+R script reloads
            existing_port = getattr(sys, "_pulse_httpd_port", None)
            if existing_port:
                self.server_port = existing_port
                self.server_url = "http://127.0.0.1:" + str(existing_port)
                self.server_running = True
                self.refresh_api_cache()
                return

            mgr = self

            class _PulseHTTPHandler(BaseHTTPRequestHandler):
                def log_message(self, format, *args):
                    return  # Silence console spam

                def _pulse_local_only(self, need_json=False):
                    """
                    Rejects requests that did not come from the dashboard page itself.
                    Host must be this loopback server (blocks DNS rebinding), any
                    Origin header must match it (blocks other websites), and commands
                    must be JSON (a cross-site form POST cannot send that without a
                    CORS preflight, which this server never answers).
                    """
                    port = str(self.server.server_address[1])
                    allowed_hosts = ("127.0.0.1:" + port, "localhost:" + port)
                    host = (self.headers.get("Host") or "").strip().lower()
                    origin = (self.headers.get("Origin") or "").strip().lower()
                    ok = host in allowed_hosts
                    if ok and origin:
                        ok = origin in tuple("http://" + h for h in allowed_hosts)
                    if ok and need_json:
                        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                        ok = (ctype == "application/json")
                    if not ok:
                        self.send_response(403)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                    return ok

                def do_GET(self):
                    if not self._pulse_local_only():
                        return
                    active_mgr = getattr(store, "_pulse", mgr)
                    active_html = getattr(store, "_PULSE_WEB_DASHBOARD_HTML", _PULSE_WEB_DASHBOARD_HTML)
                    parsed = urlparse(self.path)
                    if parsed.path == "/api/state":
                        body = active_mgr.cached_api_payload.encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    elif parsed.path == "/api/asset":
                        qs = parse_qs(parsed.query)
                        rel = qs.get("file", [""])[0]
                        ext = os.path.splitext(rel)[1].lower()
                        mime_map = {
                            ".png": "image/png",
                            ".jpg": "image/jpeg",
                            ".jpeg": "image/jpeg",
                            ".webp": "image/webp",
                            ".gif": "image/gif",
                            ".avif": "image/avif",
                        }
                        resolved = active_mgr._resolve_gamedir_path(rel) if ext in mime_map else None
                        if resolved:
                            try:
                                with open(resolved, "rb") as fp:
                                    img_bytes = fp.read()
                                self.send_response(200)
                                self.send_header("Content-Type", mime_map[ext])
                                self.send_header("Cache-Control", "no-store")
                                self.send_header("Content-Length", str(len(img_bytes)))
                                self.end_headers()
                                self.wfile.write(img_bytes)
                                return
                            except Exception:
                                pass
                        self.send_response(404)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                    else:
                        body = active_html.encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)

                def do_POST(self):
                    if not self._pulse_local_only(need_json=True):
                        return
                    active_mgr = getattr(store, "_pulse", mgr)
                    parsed = urlparse(self.path)
                    if parsed.path == "/api/cmd":
                        length = int(self.headers.get("Content-Length", 0))
                        raw = self.rfile.read(length).decode("utf-8", errors="ignore") if length > 0 else "{}"
                        try:
                            cmd = json.loads(raw)
                            active_mgr.enqueue_command(cmd)
                            resp = b'{"ok":true}'
                        except Exception as e:
                            resp = json.dumps({"ok": False, "error": str(e)}).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(resp)))
                        self.end_headers()
                        self.wfile.write(resp)

            def _serve_thread():
                for candidate_port in range(7367, 7378):
                    try:
                        httpd = ThreadingHTTPServer(("127.0.0.1", candidate_port), _PulseHTTPHandler)
                        sys._pulse_httpd_port = candidate_port
                        mgr.server_port = candidate_port
                        mgr.server_url = "http://127.0.0.1:" + str(candidate_port)
                        mgr.server_running = True
                        mgr.refresh_api_cache()
                        httpd.serve_forever()
                        break
                    except Exception:
                        continue

            t = threading.Thread(target=_serve_thread, name="RenPyPulseBridge")
            t.daemon = True
            t.start()

        def open_second_window(self):
            """Launch the Second-Window Live Dashboard in a frameless desktop `--app` window (Edge/Chrome) or browser."""
            if not self.server_running:
                self.start_http_bridge()
            url = self.server_url
            launched = False
            if sys.platform.startswith("win"):
                # Look for Microsoft Edge or Google Chrome to launch in standalone frameless `--app=` window mode
                candidates = [
                    os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
                    os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
                    os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
                ]
                for exe in candidates:
                    if os.path.exists(exe):
                        try:
                            subprocess.Popen([exe, "--app=" + url, "--window-size=1180,820"])
                            launched = True
                            break
                        except Exception:
                            pass
            if not launched:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
            self.add_toast("Opened 2nd Window (" + url + ")", "#00F7FF")
            renpy.restart_interaction()


    # Embedded Zero-Dependency HTML5/CSS/JS Dashboard for Second-Window Mode
    _PULSE_WEB_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Ren'Py Pulse — Live Second-Window DevTool</title>
<style>
  :root {
    --bg: #070b12; --panel: #0d1422; --card: #121c2e; --border: #1e2d47;
    --cyan: #00F7FF; --pink: #FF00D4; --green: #00FF88; --amber: #FFB800; --red: #FF4455;
    --text: #EAEFF8; --sub: #8496B0;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }
  body { background: var(--bg); color: var(--text); display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
  header { background: var(--panel); border-bottom: 1px solid var(--border); padding: 10px 18px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 16px; letter-spacing: 0.6px; color: var(--cyan); }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--green); box-shadow: 0 0 8px var(--green); }
  .status-badges { display: flex; gap: 10px; align-items: center; font-size: 12px; }
  .badge { background: var(--card); border: 1px solid var(--border); padding: 4px 10px; border-radius: 6px; color: var(--sub); }
  .badge b { color: var(--text); font-family: Consolas, monospace; }
  nav { background: #0a101b; border-bottom: 1px solid var(--border); display: flex; gap: 4px; padding: 6px 16px; }
  nav button { background: transparent; border: 1px solid transparent; color: var(--sub); padding: 7px 14px; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 13px; transition: 0.15s; }
  nav button:hover { color: var(--text); background: var(--card); }
  nav button.active { color: var(--cyan); background: rgba(0, 247, 255, 0.1); border-color: rgba(0, 247, 255, 0.35); }
  main { flex: 1; display: flex; overflow: hidden; }
  aside { width: 240px; flex-shrink: 0; background: var(--panel); border-right: 1px solid var(--border); overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 4px; }
  aside button { flex-shrink: 0; display: block; width: 100%; min-height: 32px; line-height: 18px; text-align: left; background: transparent; border: 1px solid transparent; color: #b8c7e0; padding: 6px 11px; border-radius: 6px; cursor: pointer; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  aside button:hover { background: var(--card); color: var(--text); }
  aside button.active { background: rgba(0, 247, 255, 0.14); border-color: rgba(0, 247, 255, 0.35); color: var(--cyan); font-weight: 600; }
  .content { flex: 1; display: flex; flex-direction: column; overflow: hidden; padding: 14px 18px; gap: 12px; }
  .toolbar { display: flex; gap: 10px; align-items: center; flex-shrink: 0; }
  input[type="text"] { background: var(--card); border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 6px; font-size: 13px; outline: none; }
  input[type="text"]:focus { border-color: var(--cyan); }
  .scroll-area { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; padding-right: 4px; }
  .var-row { flex-shrink: 0; background: var(--card); border: 1px solid var(--border); border-radius: 7px; padding: 8px 12px; display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .var-row.modified { border-left: 3px solid var(--amber); }
  .var-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
  .var-name { font-family: Consolas, monospace; font-size: 13.5px; font-weight: 600; color: var(--text); display: flex; align-items: center; gap: 8px; }
  .var-meta { font-size: 11px; color: var(--sub); }
  .tag { font-size: 10px; padding: 1px 6px; border-radius: 4px; font-family: sans-serif; font-weight: 600; text-transform: uppercase; }
  .tag.store { background: rgba(0,247,255,0.12); color: var(--cyan); }
  .tag.persistent { background: rgba(255,0,212,0.15); color: var(--pink); }
  .tag.define { background: rgba(132,150,176,0.18); color: var(--sub); }
  .var-controls { display: flex; align-items: center; gap: 5px; }
  .val-box { font-family: Consolas, monospace; font-size: 13px; color: var(--green); background: #080d16; padding: 4px 9px; border-radius: 5px; border: 1px solid var(--border); max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .btn { background: #19263c; border: 1px solid var(--border); color: var(--text); padding: 4px 9px; border-radius: 5px; cursor: pointer; font-size: 12px; font-weight: 600; transition: 0.12s; }
  .btn:hover { border-color: var(--cyan); color: var(--cyan); }
  .btn.cyan { background: rgba(0,247,255,0.14); border-color: rgba(0,247,255,0.4); color: var(--cyan); }
  .btn.green { background: rgba(0,255,136,0.14); border-color: rgba(0,255,136,0.4); color: var(--green); }
  .btn.amber { background: rgba(255,184,0,0.14); border-color: rgba(255,184,0,0.4); color: var(--amber); }
  .btn.red { background: rgba(255,68,85,0.14); border-color: rgba(255,68,85,0.4); color: var(--red); }
  .star { cursor: pointer; font-size: 15px; color: #3b4b66; user-select: none; }
  .star.on { color: var(--amber); }
  .grid-2 { display: grid; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); gap: 10px; }
  .card { flex-shrink: 0; background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
  .card h4 { color: var(--cyan); font-size: 13px; }
</style>
</head>
<body>
<header>
  <div class="brand"><div class="dot" id="connDot"></div> REN'PY PULSE <span style="color:var(--sub);font-weight:400;font-size:12px;" id="gameTitle">Connecting...</span></div>
  <div class="status-badges">
    <div class="badge">Label: <b id="curLabel">-</b></div>
    <div class="badge">Script: <b id="curFileLine">-</b></div>
    <button class="btn" id="macroRecBtn" onclick="sendCmd({op:'toggle_macro_rec'})">● Rec Macro</button>
    <button class="btn green" id="hudToggleBtn" onclick="sendCmd({op:'toggle_hud'})">Top-Left HUD: ON</button>
    <button class="btn amber" onclick="sendCmd({op:'reset_all_store'})">Reset Store Vars</button>
  </div>
</header>
<nav style="flex-wrap:wrap;">
  <button class="active" onclick="setTab('variables', this)">Variables & Persistent</button>
  <button onclick="setTab('diffs', this)">Live Diffs (<span id="diffCount">0</span>)</button>
  <button onclick="setTab('teleport', this)">Teleporter & Choices</button>
  <button onclick="setTab('presets', this)">Route Presets</button>
  <button onclick="setTab('inspector', this)">Screens & Layers</button>
  <button onclick="setTab('audio', this)">Audio</button>
  <button onclick="setTab('assets', this)">Assets & Styles</button>
  <button onclick="setTab('actions', this)">Actions & Macros</button>
  <button onclick="setTab('perf', this)">Perf & UI Lag</button>
</nav>
<main id="mainArea"></main>
<script>
let state = null;
let lastRawJson = '';
let currentTab = 'variables';
let currentCat = 'All';
let searchQuery = '';
let labelQuery = '';
let presetName = 'My Route Loadout';
let macroName = 'Test Scenario A';
let consoleExpr = '';
let assetSubtab = 'images';
let assetQuery = '';
let assetTag = 'All';
let selectedAssetImg = null;
let styleQuery = '';
let styleScope = 'All';

async function sendCmd(payload) {
  try {
    await fetch('/api/cmd', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    lastRawJson = '';
    setTimeout(fetchState, 120);
  } catch (e) {}
}

async function fetchState() {
  try {
    const res = await fetch('/api/state');
    const raw = await res.text();
    document.getElementById('connDot').style.background = '#00FF88';
    if (raw === lastRawJson) return;
    lastRawJson = raw;
    state = JSON.parse(raw);
    document.getElementById('gameTitle').textContent = state.game_name + ' ' + state.game_version;
    document.getElementById('curLabel').textContent = state.current_label;
    document.getElementById('curFileLine').textContent = state.file_line;
    document.getElementById('diffCount').textContent = state.diffs.length;
    const hudBtn = document.getElementById('hudToggleBtn');
    if (hudBtn) {
      const hudOn = state.hud_visible !== false;
      hudBtn.textContent = 'Top-Left HUD: ' + (hudOn ? 'ON' : 'OFF');
      hudBtn.className = 'btn ' + (hudOn ? 'green' : '');
    }
    const recBtn = document.getElementById('macroRecBtn');
    if (recBtn) {
      const recOn = !!state.macro_recording;
      recBtn.textContent = recOn ? ('■ Stop Rec (' + (state.macro_step_count||0) + ')') : '● Rec Macro';
      recBtn.className = 'btn ' + (recOn ? 'red' : '');
    }
    if (!document.activeElement || document.activeElement.tagName !== 'INPUT') {
      render();
    }
  } catch (e) {
    document.getElementById('connDot').style.background = '#FF4455';
  }
}

function setTab(t, btn) {
  currentTab = t;
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  render();
}

function escHtml(s) {
  return String(s === undefined || s === null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function promptSetVar(key, curVal) {
  const next = prompt('Set new value for ' + key + ':', curVal);
  if (next !== null) sendCmd({op: 'set', key: key, value: next});
}

function render() {
  if (!state) return;
  const main = document.getElementById('mainArea');
  const prevAside = main.querySelector('aside');
  const prevAsideScroll = prevAside ? prevAside.scrollTop : 0;
  const prevScrollAreas = Array.from(main.querySelectorAll('.scroll-area')).map(el => el.scrollTop);
  if (currentTab === 'variables') {
    const cats = state.categories || ['All'];
    let vars = (state.variables || []).filter(v => {
      if (currentCat === 'Watchlist' && !v.watched) return false;
      if (currentCat === 'Modified' && !v.modified) return false;
      if (currentCat === 'Store' && v.scope !== 'store') return false;
      if (currentCat === 'Persistent' && v.scope !== 'persistent') return false;
      if (currentCat === 'Defines' && v.scope !== 'define') return false;
      if (currentCat.startsWith('File: ') && v.file_short !== currentCat.slice(6)) return false;
      if (!['All','Watchlist','Modified','Store','Persistent','Defines'].includes(currentCat) && !currentCat.startsWith('File: ') && v.category !== currentCat) return false;
      if (searchQuery) {
        const hay = (v.key + ' ' + v.category + ' ' + v.file_short + ' ' + v.val_repr).toLowerCase();
        if (!hay.includes(searchQuery.toLowerCase())) return false;
      }
      return true;
    });
    main.innerHTML = `
      <aside>
        ${cats.map(c => `<button class="${c===currentCat?'active':''}" onclick="currentCat=${JSON.stringify(c).replace(/"/g,"'")};render()">${c}</button>`).join('')}
      </aside>
      <div class="content">
        <div class="toolbar">
          <input type="text" style="flex:1" placeholder="Search variable name, category, file, or value..." value="${searchQuery.replace(/"/g,'&quot;')}" oninput="searchQuery=this.value;renderRowsOnly()">
          <span style="font-size:12px;color:var(--sub)" id="varCountLabel">${vars.length} variables</span>
        </div>
        <div class="scroll-area" id="varRowsContainer">${ renderVarRows(vars) }</div>
      </div>`;
  } else if (currentTab === 'diffs') {
    main.innerHTML = `<div class="content">
      <div class="toolbar">
        <span style="font-size:13px;color:var(--cyan);font-weight:600;">Real-Time Variable Change Feed</span>
        <button class="btn green" style="margin-left:auto;" onclick="sendCmd({op:'save_diffs_macro', count:10})">+ Save Last 10 Diffs as Macro</button>
      </div>
      <div class="scroll-area">
      ${(state.diffs || []).length === 0 ? '<div style="color:var(--sub);padding:20px;">No variable changes recorded yet. Play through the game or edit a variable!</div>' :
        state.diffs.map(d => `
          <div class="var-row">
            <div class="var-info">
              <div class="var-name">${escHtml(d.var_key)} <span class="tag store">${escHtml(d.source)}</span></div>
              <div class="var-meta">${escHtml(d.time)} | Label: ${escHtml(d.label)} (${escHtml(d.file_line)})</div>
            </div>
            <div class="var-controls">
              <span class="val-box" style="color:var(--sub)">${escHtml(d.old_repr)}</span>
              <span style="color:var(--cyan)">→</span>
              <span class="val-box">${escHtml(d.new_repr)}</span>
              ${d.file && d.line > 0 ? `<button class="btn" onclick="sendCmd({op:'open_editor', file:${JSON.stringify(d.file).replace(/"/g,"'")}, line:${d.line}})" title="Open in VS Code">Code</button>` : ''}
              <button class="btn amber" onclick="sendCmd({op:'undo_diff', id:${d.id}})">Undo</button>
            </div>
          </div>`).join('')}
      </div>
    </div>`;
  } else if (currentTab === 'teleport') {
    const menus = state.menus || [];
    const labels = (state.labels || []).filter(l => !labelQuery || l.name.toLowerCase().includes(labelQuery.toLowerCase()) || l.file_short.toLowerCase().includes(labelQuery.toLowerCase()));
    main.innerHTML = `<div class="content" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
      <div style="display:flex;flex-direction:column;gap:10px;overflow:hidden;">
        <h3 style="font-size:14px;color:var(--cyan)">Choices & Conditions in Current Chapter (${escHtml(state.current_label)})</h3>
        <div class="scroll-area">
          ${menus.length === 0 ? '<div style="color:var(--sub)">No conditional menus detected near current label.</div>' :
            menus.map(m => `<div class="card">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <h4>Menu: ${escHtml(m.name)} (${escHtml(m.file_short)}:${m.line})</h4>
                <button class="btn" onclick="sendCmd({op:'open_editor', file:${JSON.stringify(m.file_short).replace(/"/g,"'")}, line:${m.line}})">Code</button>
              </div>
              ${m.choices.map(ch => `
                <div class="var-row" style="padding:6px 10px;">
                  <div class="var-info">
                    <div class="var-name" style="font-size:12.5px;">"${escHtml(ch.caption)}"</div>
                    <div class="var-meta">${ch.condition ? 'if ' + escHtml(ch.condition) + ' [' + escHtml(ch.vars_summary) + ']' : 'Always available (no condition)'}</div>
                  </div>
                  ${ch.condition ? `<div class="var-controls">
                    <span class="tag ${ch.passed?'store':'persistent'}">${ch.passed?'UNLOCKED':'LOCKED'}</span>
                    ${!ch.passed ? `<button class="btn green" onclick="sendCmd({op:'satisfy', cond:${JSON.stringify(ch.condition).replace(/"/g,"'")}})">Force Unlock</button>` : ''}
                  </div>` : '<span class="tag store">OPEN</span>'}
                </div>`).join('')}
            </div>`).join('')}
        </div>
      </div>
      <div style="display:flex;flex-direction:column;gap:10px;overflow:hidden;">
        <div class="toolbar">
          <input type="text" style="flex:1" placeholder="Filter labels (e.g. act4_7)..." value="${escHtml(labelQuery)}" oninput="labelQuery=this.value;render()">
        </div>
        <div class="scroll-area">
          ${labels.slice(0, 120).map(l => `
            <div class="var-row">
              <div class="var-info">
                <div class="var-name">${escHtml(l.name)}</div>
                <div class="var-meta">${escHtml(l.file)}:${l.line}</div>
              </div>
              <div class="var-controls">
                <button class="btn" onclick="sendCmd({op:'open_editor', file:${JSON.stringify(l.file).replace(/"/g,"'")}, line:${l.line}})" title="Open in VS Code">Code</button>
                <button class="btn cyan" onclick="sendCmd({op:'jump', label:'${l.name}'})">Jump</button>
                <button class="btn" onclick="sendCmd({op:'call', label:'${l.name}'})">Call</button>
              </div>
            </div>`).join('')}
        </div>
      </div>
    </div>`;
  } else if (currentTab === 'presets') {
    const presets = state.presets || [];
    main.innerHTML = `<div class="content">
      <div class="toolbar">
        <input type="text" style="width:280px" value="${escHtml(presetName)}" oninput="presetName=this.value" placeholder="Preset Name...">
        <button class="btn green" onclick="sendCmd({op:'save_preset', name:presetName})">+ Save Current State as Preset</button>
      </div>
      <div class="scroll-area">
        ${presets.length === 0 ? '<div style="color:var(--sub)">No saved route presets yet. Save one above!</div>' :
          presets.map(p => `
            <div class="var-row">
              <div class="var-info">
                <div class="var-name">${escHtml(p.name)} <span class="tag store">${p.var_count} vars</span></div>
                <div class="var-meta">Saved at label: ${escHtml(p.label)} | ${escHtml(p.created)}</div>
              </div>
              <div class="var-controls">
                <button class="btn cyan" onclick="sendCmd({op:'load_preset', filename:'${p.filename}', jump:false})">Load Vars Only</button>
                <button class="btn green" onclick="sendCmd({op:'load_preset', filename:'${p.filename}', jump:true})">Load + Jump to ${escHtml(p.label)}</button>
                <button class="btn red" onclick="sendCmd({op:'delete_preset', filename:'${p.filename}'})">Delete</button>
              </div>
            </div>`).join('')}
      </div>
    </div>`;
  } else if (currentTab === 'inspector') {
    main.innerHTML = `<div class="content"><div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;overflow-y:auto;">
      <div class="card"><h4>Active Screens</h4>
        ${(state.screens||[]).map(s => `<div class="var-row"><span>${escHtml(s.name)} <small style="color:var(--sub)">(${escHtml(s.layer)})</small></span><button class="btn amber" onclick="sendCmd({op:'toggle_screen', screen:'${s.name}'})">Hide</button></div>`).join('')}
      </div>
      <div class="card"><h4>Showing Images & Movies</h4>
        ${(state.images||[]).map(img => `<div class="var-row"><span>${escHtml(img.full)} <small style="color:var(--sub)">(${escHtml(img.layer)})</small></span><button class="btn amber" onclick="sendCmd({op:'hide_image', tag:'${img.tag}', layer:'${img.layer}'})">Hide</button></div>`).join('')}
      </div>
    </div></div>`;
  } else if (currentTab === 'audio') {
    const chans = state.audio || [];
    main.innerHTML = `<div class="content">
      <div class="toolbar"><span style="font-size:13px;color:var(--cyan);font-weight:600;">Multi-Channel Audio Inspector</span><span style="font-size:12px;color:var(--sub);">Live playback, mixer/channel volumes, and queued tracks</span></div>
      <div class="scroll-area">
        <div class="grid-2" style="grid-template-columns:repeat(auto-fill, minmax(360px, 1fr));">
          ${chans.length === 0 ? '<div class="card"><h4>No Audio Channels Detected</h4><div style="font-size:12px;color:var(--sub);">No registered or active Ren\'Py audio channels reported yet.</div></div>' : ''}
          ${chans.map(a => `
            <div class="card">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <h4>${escHtml(a.channel)} <span class="tag store">${escHtml(a.mixer||'music')}</span></h4>
                <div style="display:flex;gap:5px;align-items:center;">
                  ${a.muted ? '<span class="tag persistent">MUTED</span>' : ''}
                  ${a.paused ? '<span class="tag persistent">PAUSED</span>' : ''}
                  <span class="tag ${a.playing?'store':'define'}" style="${a.playing?'color:var(--green);background:rgba(0,255,136,0.12);':''}">${a.playing?'PLAYING':'IDLE'}</span>
                </div>
              </div>
              <div style="font-family:Consolas,monospace;font-size:12.5px;color:${a.playing?'var(--text)':'var(--sub)'};word-break:break-all;">${escHtml(a.playing || 'Idle')}</div>
              <div style="display:flex;justify-content:space-between;font-size:11.5px;color:var(--sub);font-family:Consolas,monospace;">
                <span>Pos: ${a.pos||0}s / ${a.duration||0}s</span>
                <span>Chan: ${Math.round((a.chan_volume??1)*100)}% • Mixer: ${Math.round((a.mixer_volume??1)*100)}%</span>
              </div>
              <div style="height:6px;background:#080d16;border-radius:4px;overflow:hidden;border:1px solid var(--border);"><div style="height:100%;width:${a.progress_pct||0}%;background:var(--cyan);"></div></div>
              <div style="display:flex;flex-wrap:wrap;gap:6px;">
                <button class="btn" onclick="sendCmd({op:'set_audio_volume', channel:'${a.channel}', volume:${Math.max(0, Number(((a.chan_volume??1)-0.1).toFixed(2)))}})">Vol -10%</button>
                <button class="btn" onclick="sendCmd({op:'set_audio_volume', channel:'${a.channel}', volume:${Math.min(1, Number(((a.chan_volume??1)+0.1).toFixed(2)))}})">Vol +10%</button>
                <button class="btn" onclick="sendCmd({op:'set_audio_volume', channel:'${a.channel}', volume:1.0})">100%</button>
                ${a.playing ? `<button class="btn cyan" onclick="sendCmd({op:'toggle_audio_pause', channel:'${a.channel}'})">${a.paused?'Resume':'Pause'}</button>` : ''}
                ${a.playing ? `<button class="btn red" onclick="sendCmd({op:'stop_audio', channel:'${a.channel}'})">Stop</button>` : ''}
                ${(a.queue||[]).length > 0 ? `<button class="btn amber" onclick="sendCmd({op:'clear_audio_queue', channel:'${a.channel}'})">Clear Queue (${a.queue.length})</button>` : ''}
              </div>
              ${(a.queue||[]).length > 0 ? `<div style="font-size:11.5px;color:var(--sub);">Queue: ${a.queue.map(q => escHtml(q.short)).join(' → ')}</div>` : ''}
            </div>`).join('')}
        </div>
      </div>
    </div>`;
  } else if (currentTab === 'assets') {
    const allImgs = state.asset_images || [];
    const tags = state.asset_tags || ['All'];
    const filteredImgs = allImgs.filter(img => {
      if (assetTag !== 'All' && img.tag !== assetTag) return false;
      if (assetQuery && !img.name.toLowerCase().includes(assetQuery.toLowerCase()) && !(img.file||'').toLowerCase().includes(assetQuery.toLowerCase())) return false;
      return true;
    });
    if (!selectedAssetImg && filteredImgs.length > 0) selectedAssetImg = filteredImgs[0];
    const styles = (state.styles || []).filter(s => {
      if (styleScope === 'Customized' && !s.customized) return false;
      if (styleQuery && !s.name.toLowerCase().includes(styleQuery.toLowerCase())) return false;
      return true;
    });
    const selStyle = state.selected_style;
    main.innerHTML = `<div class="content">
      <div class="toolbar">
        <button class="btn ${assetSubtab==='images'?'cyan':''}" onclick="assetSubtab='images';render()">Images Gallery (${allImgs.length})</button>
        <button class="btn ${assetSubtab==='styles'?'cyan':''}" onclick="assetSubtab='styles';render()">Style Inspector (${(state.styles||[]).length})</button>
        <button class="btn" style="margin-left:auto;" onclick="sendCmd({op:'refresh_assets'})">Refresh Index</button>
      </div>
      ${assetSubtab === 'images' ? `
        <div style="flex:1;display:grid;grid-template-columns:1.1fr 1fr;gap:14px;overflow:hidden;">
          <div style="display:flex;flex-direction:column;gap:8px;overflow:hidden;">
            <div class="toolbar">
              <input type="text" style="flex:1" placeholder="Search registered image name or file..." value="${escHtml(assetQuery)}" oninput="assetQuery=this.value;render()">
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:4px;max-height:72px;overflow-y:auto;">
              ${tags.slice(0, 35).map(t => `<button class="btn ${t===assetTag?'cyan':''}" onclick="assetTag=${JSON.stringify(t).replace(/"/g,"'")};render()">${escHtml(t)}</button>`).join('')}
            </div>
            <div class="scroll-area">
              ${filteredImgs.slice(0, 150).map(img => `
                <div class="var-row" style="cursor:pointer;${selectedAssetImg && selectedAssetImg.name===img.name?'border-color:var(--cyan);':''}" onclick="selectedAssetImg=${JSON.stringify(img).replace(/"/g,"'")};render()">
                  <div class="var-info">
                    <div class="var-name" style="font-size:12.5px;">${escHtml(img.name)} <span class="tag store">${escHtml(img.type)}</span></div>
                    <div class="var-meta">${escHtml(img.file || 'Composite / Dynamic Displayable')}</div>
                  </div>
                </div>`).join('')}
            </div>
          </div>
          <div class="card" style="overflow:hidden;justify-content:space-between;">
            ${selectedAssetImg ? `
              <div>
                <h4>${escHtml(selectedAssetImg.name)}</h4>
                <div style="font-size:12px;color:var(--sub);margin-top:4px;">Type: ${escHtml(selectedAssetImg.type)} • ${escHtml(selectedAssetImg.file || 'No static file path')}</div>
              </div>
              <div style="flex:1;display:flex;align-items:center;justify-content:center;background:#060a12;border:1px solid var(--border);border-radius:6px;overflow:hidden;min-height:220px;">
                ${selectedAssetImg.has_file ? `<img src="/api/asset?file=${encodeURIComponent(selectedAssetImg.file)}" style="max-width:100%;max-height:100%;object-fit:contain;" />` : '<div style="color:var(--sub);font-size:12px;padding:16px;text-align:center;">Dynamic/LayeredImage — click "Show on Master" below to preview live inside the game window!</div>'}
              </div>
              <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <button class="btn green" onclick="sendCmd({op:'show_asset_image', name:${JSON.stringify(selectedAssetImg.name).replace(/"/g,"'")}})">Show on Master</button>
                <button class="btn amber" onclick="sendCmd({op:'hide_image', tag:${JSON.stringify(selectedAssetImg.tag).replace(/"/g,"'")}, layer:'master'})">Hide Tag</button>
                ${selectedAssetImg.has_file ? `<button class="btn" onclick="sendCmd({op:'open_editor', file:${JSON.stringify(selectedAssetImg.file).replace(/"/g,"'")}, line:1})">Open File</button>` : ''}
              </div>` : '<div style="color:var(--sub)">Select an image to preview.</div>'}
          </div>
        </div>` : `
        <div style="flex:1;display:grid;grid-template-columns:0.9fr 1.2fr;gap:14px;overflow:hidden;">
          <div style="display:flex;flex-direction:column;gap:8px;overflow:hidden;">
            <div class="toolbar">
              <input type="text" style="flex:1" placeholder="Search styles..." value="${escHtml(styleQuery)}" oninput="styleQuery=this.value;render()">
              <button class="btn ${styleScope==='All'?'cyan':''}" onclick="styleScope='All';render()">All</button>
              <button class="btn ${styleScope==='Customized'?'cyan':''}" onclick="styleScope='Customized';render()">Custom</button>
            </div>
            <div class="scroll-area">
              ${styles.slice(0, 150).map(s => `
                <div class="var-row" style="cursor:pointer;" onclick="sendCmd({op:'select_style', name:${JSON.stringify(s.name).replace(/"/g,"'")}})">
                  <div class="var-info">
                    <div class="var-name" style="font-size:12.5px;">${escHtml(s.name)} ${s.customized?'<span class="tag store">custom</span>':''}</div>
                    ${s.parent ? `<div class="var-meta">inherits: ${escHtml(s.parent)}</div>` : ''}
                  </div>
                </div>`).join('')}
            </div>
          </div>
          <div class="card" style="overflow:hidden;">
            <h4>Style: ${escHtml(selStyle ? selStyle.name : 'None')} ${selStyle && selStyle.parent ? '(is ' + escHtml(selStyle.parent) + ')' : ''}</h4>
            <div class="scroll-area">
              ${selStyle ? `
                ${(selStyle.resolved||[]).map(r => `<div class="var-row" style="padding:5px 9px;"><span style="color:var(--cyan);font-family:Consolas,monospace;font-size:12px;">${escHtml(r.prop)}</span><span class="val-box">${escHtml(r.val)}</span></div>`).join('')}
                ${(selStyle.chain||[]).length > 0 ? `<h4 style="margin-top:8px;">Inheritance Chain</h4>` + selStyle.chain.map(c => `<div class="card" style="padding:8px;"><b style="font-size:12px;color:var(--amber);">${escHtml(c.style)}</b><div style="font-size:11px;color:var(--sub);font-family:Consolas,monospace;">${(c.props||[]).map(p => escHtml(p.prop)+'='+escHtml(p.val)).join(' • ') || '(defaults)'}</div></div>`).join('') : ''}
              ` : '<div style="color:var(--sub)">Select a style on the left to inspect properties.</div>'}
            </div>
          </div>
        </div>`}
    </div>`;
  } else if (currentTab === 'actions') {
    const acts = state.actions || [];
    const macros = state.macros || [];
    main.innerHTML = `<div class="content">
      <div class="toolbar">
        <button class="btn cyan" onclick="sendCmd({op:'backup_persistent'})">Backup Persistent</button>
        <button class="btn amber" onclick="sendCmd({op:'restore_persistent'})">Restore Persistent Backup</button>
        <input type="text" style="flex:1" placeholder="Run Python in renpy.store (e.g. ayase_point += 10)..." value="${escHtml(consoleExpr)}" oninput="consoleExpr=this.value" onkeydown="if(event.key==='Enter')sendCmd({op:'console',expr:consoleExpr})">
        <button class="btn green" onclick="sendCmd({op:'console',expr:consoleExpr})">Execute</button>
      </div>
      <div class="scroll-area">
        <div class="card" style="margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
            <h4>Command History Macro Recorder (${state.macro_step_count||0} recorded steps)</h4>
            <div style="display:flex;gap:6px;align-items:center;">
              <input type="text" style="width:200px;padding:5px 8px;" value="${escHtml(macroName)}" oninput="macroName=this.value" placeholder="Macro Name...">
              <button class="btn ${state.macro_recording?'red':'cyan'}" onclick="sendCmd({op:'toggle_macro_rec'})">${state.macro_recording?'■ Stop Rec':'● Start Rec'}</button>
              <button class="btn green" onclick="sendCmd({op:'save_macro', name:macroName})">Save Macro</button>
              <button class="btn" onclick="sendCmd({op:'clear_macro_steps'})">Clear</button>
            </div>
          </div>
          ${macros.length === 0 ? '<div style="font-size:12px;color:var(--sub)">No saved macros yet. Click "● Start Rec", edit variables/commands, then click "Save Macro"!</div>' :
            macros.map(m => `
              <div class="var-row" style="padding:6px 10px;">
                <div class="var-info">
                  <div class="var-name" style="font-size:12.5px;">${escHtml(m.name)} <span class="tag store">${m.step_count} steps</span></div>
                  <div class="var-meta">${escHtml(m.summary)} • ${escHtml(m.created)}</div>
                </div>
                <div class="var-controls">
                  <button class="btn green" onclick="sendCmd({op:'run_macro', filename:'${m.filename}'})">Run Macro</button>
                  <button class="btn red" onclick="sendCmd({op:'delete_macro', filename:'${m.filename}'})">Delete</button>
                </div>
              </div>`).join('')}
        </div>
        <div class="grid-2">
          ${acts.map(a => `
            <div class="card">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <h4>${escHtml(a.label)}</h4>
                ${a.badge ? `<span class="tag store">${escHtml(a.badge)}</span>` : `<span class="tag define">${escHtml(a.category)}</span>`}
              </div>
              <div style="font-size:11.5px;color:var(--sub)">${escHtml(a.description)}</div>
              <button class="btn cyan" onclick="sendCmd({op:'run_action', id:'${a.id}'})">Run Action</button>
            </div>`).join('')}
        </div>
        <h4 style="margin-top:12px;color:var(--cyan)">Console Output History</h4>
        ${(state.console||[]).map(c => `<div class="var-row"><div class="var-info"><div class="var-name">&gt;&gt;&gt; ${escHtml(c.expr)}</div><div class="var-meta" style="color:${c.is_error?'var(--red)':'var(--green)'}">${escHtml(c.output)}</div></div></div>`).join('')}
      </div>
    </div>`;
  } else if (currentTab === 'perf') {
    const p = state.perf || {};
    const pct = Math.min(100, Math.max(0, Number(p.cache_pct || 0)));
    const barColor = pct >= 85 ? 'var(--red)' : (pct >= 60 ? 'var(--amber)' : 'var(--green)');
    const profOn = !!p.profiler_enabled;
    const screens = p.screen_audit || [];
    const loads = p.image_loads || [];
    main.innerHTML = `<div class="content">
      <div class="toolbar" style="flex-wrap:wrap;">
        <button class="btn ${profOn ? 'green' : 'cyan'}" onclick="sendCmd({op:'toggle_ui_profiler'})">Live UI Profiler: ${profOn ? 'ON (' + (p.profiler_elapsed||0) + 's)' : 'OFF'}</button>
        <button class="btn" onclick="sendCmd({op:'reset_ui_profiler'})">Reset Profiler</button>
        <button class="btn amber" onclick="sendCmd({op:'free_memory'})">Free Memory (GC)</button>
        <button class="btn" onclick="sendCmd({op:'refresh_perf'})">Sample Now</button>
        <span style="font-size:12px;color:var(--sub);margin-left:auto;">Renderer: <b style="color:var(--text)">${escHtml(p.renderer||'unknown')}</b> ${p.gpu_name ? '(' + escHtml(p.gpu_name) + ')' : ''} • Sampled ${escHtml(p.sampled_at||'-')}</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(4, minmax(180px, 1fr));gap:10px;flex-shrink:0;">
        <div class="card">
          <h4>GPU Texture Memory</h4>
          <div style="font-size:20px;font-weight:700;color:var(--cyan);font-family:Consolas,monospace;">${p.tex_mb ?? 0} MB</div>
          <div style="font-size:12px;color:var(--sub);">${p.tex_count ?? 0} active GPU textures</div>
        </div>
        <div class="card">
          <h4>Image Cache (${pct}%)</h4>
          <div style="font-size:20px;font-weight:700;color:${barColor};font-family:Consolas,monospace;">${p.cache_mb ?? 0} / ${p.cache_limit_mb ?? 0} MB</div>
          <div style="height:6px;background:#080d16;border-radius:4px;overflow:hidden;border:1px solid var(--border);"><div style="height:100%;width:${pct}%;background:${barColor};"></div></div>
        </div>
        <div class="card">
          <h4>Store &amp; Render Cache</h4>
          <div style="font-size:14px;font-family:Consolas,monospace;color:var(--text);">Store: <b style="color:var(--cyan)">${p.store_count ?? 0}</b> • Persistent: <b style="color:var(--pink)">${p.persistent_count ?? 0}</b></div>
          <div style="font-size:12px;color:var(--sub);">Render cache: ${p.render_cache_count ?? 0} • GC: ${(p.gc_counts||[]).join('/')}</div>
        </div>
        <div class="card">
          <h4>Image Load Stalls</h4>
          <div style="font-size:20px;font-weight:700;color:${(p.stall_count||0)>0?'var(--red)':'var(--green)'};font-family:Consolas,monospace;">${p.stall_count ?? 0} Stalls</div>
          <div style="font-size:12px;color:var(--sub);">In last ${loads.length} image loads</div>
        </div>
      </div>
      <div style="flex:1;display:grid;grid-template-columns:1.4fr 0.9fr;gap:14px;overflow:hidden;">
        <div class="card" style="overflow:hidden;">
          <h4>Active Screen UI Lag Audit (Ranked by Cost / Complexity)</h4>
          <div class="scroll-area">
            ${screens.length === 0 ? '<div style="color:var(--sub);font-size:12px;">No non-Pulse game screens currently active.</div>' :
              screens.map(s => `
                <div class="var-row" style="flex-direction:column;align-items:stretch;gap:6px;">
                  <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
                    <div class="var-name">${escHtml(s.name)} <span class="tag store">${escHtml(s.layer)}</span> ${s.predict === false ? '<span class="tag persistent">predict=False</span>' : ''}</div>
                    <button class="btn" onclick="sendCmd({op:'profile_screen_file', screen:${JSON.stringify(s.name).replace(/"/g,"'")}})" title="Log detailed AST timings to profile_screen.txt">Log File</button>
                  </div>
                  <div class="var-meta" style="display:flex;flex-wrap:wrap;gap:10px;font-family:Consolas,monospace;">
                    <span>Nodes: <b style="color:var(--text)">${s.nodes}${s.truncated?'+':''}</b></span>
                    <span>Transforms: <b style="color:${s.transforms>=12?'var(--amber)':'var(--text)'}">${s.transforms}</b></span>
                    <span>focus_mask: <b style="color:${s.focus_masks>=4?'var(--red)':'var(--text)'}">${s.focus_masks}</b></span>
                    <span>Timers: <b style="color:${s.timers>=2?'var(--amber)':'var(--text)'}">${s.timers}</b></span>
                    <span>Viewports: <b style="color:var(--text)">${s.viewports}</b></span>
                  </div>
                  ${profOn || s.updates > 0 || s.renders > 0 ? `
                    <div class="var-meta" style="font-family:Consolas,monospace;color:var(--cyan);">
                      Update: ${s.avg_upd_ms}ms avg / ${s.peak_upd_ms}ms peak (${s.upd_per_sec}/s, ${s.updates}x) • Render: ${s.avg_ren_ms}ms avg / ${s.peak_ren_ms}ms peak (${s.renders}x)
                    </div>` : ''}
                  ${(s.hints||[]).length > 0 ? `<div style="display:flex;flex-wrap:wrap;gap:5px;">${s.hints.map(h => `<span class="tag persistent">${escHtml(h)}</span>`).join('')}</div>` : '<div style="font-size:11px;color:var(--green);">No UI lag red flags detected</div>'}
                </div>`).join('')}
          </div>
        </div>
        <div class="card" style="overflow:hidden;">
          <h4>Recent Image Load Log (Stall Detector)</h4>
          <div class="scroll-area">
            ${loads.length === 0 ? '<div style="color:var(--sub);font-size:12px;">No recent image loads logged yet.</div>' :
              loads.map(item => `
                <div class="var-row" style="padding:6px 10px;">
                  <div class="var-info">
                    <div class="var-name" style="font-size:12.5px;">${escHtml(item.short)}</div>
                    <div class="var-meta">${escHtml(item.time)} • ${escHtml(item.file)}</div>
                  </div>
                  <span class="tag ${item.preloaded ? 'store' : 'persistent'}" style="${item.preloaded ? 'color:var(--green);background:rgba(0,255,136,0.12);' : 'color:var(--red);background:rgba(255,68,85,0.16);'}">${item.preloaded ? 'PRELOAD' : 'STALL'}</span>
                </div>`).join('')}
          </div>
        </div>
      </div>
    </div>`;
  }
  const newAside = main.querySelector('aside');
  if (newAside && prevAsideScroll) newAside.scrollTop = prevAsideScroll;
  const newScrollAreas = main.querySelectorAll('.scroll-area');
  newScrollAreas.forEach((el, idx) => {
    if (prevScrollAreas[idx]) el.scrollTop = prevScrollAreas[idx];
  });
}

function renderVarRows(vars) {
  return vars.slice(0, 150).map(v => {
    let controls = '';
    if (v.type === 'bool') {
      controls = `<button class="btn ${v.bool_val?'green':'red'}" onclick="sendCmd({op:'toggle', key:'${v.key}'})">${v.bool_val?'TRUE':'FALSE'}</button>`;
    } else if (v.type === 'int' || v.type === 'float') {
      controls = `
        <button class="btn" onclick="sendCmd({op:'step', key:'${v.key}', delta:-10})">-10</button>
        <button class="btn" onclick="sendCmd({op:'step', key:'${v.key}', delta:-1})">-1</button>
        <span class="val-box">${v.val_repr}</span>
        <button class="btn" onclick="sendCmd({op:'step', key:'${v.key}', delta:1})">+1</button>
        <button class="btn" onclick="sendCmd({op:'step', key:'${v.key}', delta:10})">+10</button>`;
    } else {
      controls = `<span class="val-box">${v.val_repr}</span>`;
    }
    return `
      <div class="var-row ${v.modified?'modified':''}">
        <div class="var-info">
          <div class="var-name">
            <span class="star ${v.watched?'on':''}" onclick="sendCmd({op:'watch', key:'${v.key}'})">★</span>
            ${v.key}
            <span class="tag ${v.scope}">${v.scope}</span>
            <span class="tag define">${v.type}</span>
          </div>
          <div class="var-meta">${v.category} • ${v.file_short}:${v.line}</div>
        </div>
        <div class="var-controls">
          ${controls}
          ${v.line > 0 ? `<button class="btn" onclick="sendCmd({op:'open_editor', file:${JSON.stringify(v.file).replace(/"/g,"'")}, line:${v.line}})" title="Open in VS Code (${escHtml(v.file_short)}:${v.line})">Code</button>` : ''}
          <button class="btn cyan" onclick="promptSetVar('${v.key}', ${JSON.stringify(v.val_repr).replace(/"/g,"'")})">Edit</button>
          <button class="btn" onclick="sendCmd({op:'reset', key:'${v.key}'})" title="Reset to default">↺</button>
        </div>
      </div>`;
  }).join('');
}

function renderRowsOnly() {
  if (!state || currentTab !== 'variables') return;
  const container = document.getElementById('varRowsContainer');
  if (!container) return;
  let vars = (state.variables || []).filter(v => {
    if (currentCat === 'Watchlist' && !v.watched) return false;
    if (currentCat === 'Modified' && !v.modified) return false;
    if (currentCat === 'Store' && v.scope !== 'store') return false;
    if (currentCat === 'Persistent' && v.scope !== 'persistent') return false;
    if (currentCat === 'Defines' && v.scope !== 'define') return false;
    if (currentCat.startsWith('File: ') && v.file_short !== currentCat.slice(6)) return false;
    if (!['All','Watchlist','Modified','Store','Persistent','Defines'].includes(currentCat) && !currentCat.startsWith('File: ') && v.category !== currentCat) return false;
    if (searchQuery) {
      const hay = (v.key + ' ' + v.category + ' ' + v.file_short + ' ' + v.val_repr).toLowerCase();
      if (!hay.includes(searchQuery.toLowerCase())) return false;
    }
    return true;
  });
  document.getElementById('varCountLabel').textContent = vars.length + ' variables';
  container.innerHTML = renderVarRows(vars);
}

setInterval(fetchState, 350);
fetchState();
</script>
</body>
</html>"""

    # Instantiate global singleton manager (and clear any stale profiler wrappers from Shift+R reload)
    _pulse = _PulseManager()
    _pulse._restore_screen_profiler_hooks()

    def _pulse_label_callback(label_name, abnormal):
        _pulse.current_label = str(label_name)
        _pulse.check_for_diffs()

    def _pulse_interact_callback():
        if not _pulse.initialized and _pulse_is_enabled():
            _pulse.setup()
        _pulse.check_for_diffs()

    def _pulse_toggle_overlay():
        if not _pulse_is_enabled():
            return
        if not _pulse.initialized:
            _pulse.setup()
        if renpy.get_screen("pulse_devtools_overlay"):
            renpy.hide_screen("pulse_devtools_overlay")
        else:
            _pulse.check_for_diffs()
            renpy.show_screen("pulse_devtools_overlay")
        renpy.restart_interaction()

    def _pulse_toggle_mini_hud():
        if not _pulse_is_enabled():
            return
        persistent._pulse_hud_visible = not _pulse_is_mini_hud_visible()
        renpy.save_persistent()
        renpy.restart_interaction()

    def _pulse_popout_window():
        if not _pulse_is_enabled():
            return
        if not _pulse.initialized:
            _pulse.setup()
        _pulse.open_second_window()

    if _pulse_is_enabled():
        if _pulse_label_callback not in config.label_callbacks:
            config.label_callbacks.append(_pulse_label_callback)
        if _pulse_interact_callback not in config.interact_callbacks:
            config.interact_callbacks.append(_pulse_interact_callback)
        if "pulse_mini_hud" not in config.overlay_screens:
            config.overlay_screens.append("pulse_mini_hud")

        config.underlay.append(
            renpy.Keymap(
                K_F12=_pulse_toggle_overlay,
                shift_K_d=_pulse_toggle_overlay,
                shift_K_w=_pulse_popout_window,
                shift_K_p=_pulse_toggle_mini_hud,
            )
        )


################################################################################
## IN-GAME SCREENS: CORNER MINI-HUD PILL & FULL DEVTOOL OVERLAY
################################################################################

style pulse_ovl_vbox is vbox:
    xalign 0.0

style pulse_ovl_hbox is hbox:
    xalign 0.0

style pulse_ovl_text is text:
    xalign 0.0
    text_align 0.0
    outlines []

screen pulse_mini_hud():
    style_prefix "pulse_ovl"
    zorder 1900
    # Background queue polling timer for Second-Window Live Sync
    timer 0.2 repeat True action Function(_pulse.poll_cmd_queue)

    if _pulse_is_enabled() and _pulse_is_mini_hud_visible():
        $ _fn_short, _ln_num = _pulse.get_current_file_line()
        vbox:
            xpos 14
            ypos 12
            spacing 6

            # Compact Top-Left Pill
            frame:
                background Solid("#090f1ce0")
                padding (10, 5)
                hbox:
                    spacing 10
                    yalign 0.5
                    button:
                        background Solid("#00F7FF22")
                        hover_background Solid("#00F7FF44")
                        padding (8, 3)
                        action Function(_pulse_toggle_overlay)
                        text "● PULSE (F12)" size 14 color "#00F7FF" bold True outlines []
                    text (_pulse_esc(_pulse.current_label) + " | " + _pulse_esc(_fn_short) + ":" + str(_ln_num)) size 13 color "#B8C7E0" yalign 0.5 outlines []
                    button:
                        background Solid("#FF00D422")
                        hover_background Solid("#FF00D444")
                        padding (8, 3)
                        action Function(_pulse_popout_window)
                        text "2nd Win (Shift+W)" size 12 color "#FF00D4" outlines []
                    button:
                        background None
                        padding (4, 2)
                        action Function(_pulse_toggle_mini_hud)
                        text "×" size 14 color "#667799" hover_color "#FFFFFF" outlines []

            # Live Diff Toasts
            for _t in _pulse.toasts:
                frame:
                    background Solid("#0c1526e8")
                    padding (10, 4)
                    hbox:
                        spacing 6
                        text "Δ" size 13 color _t["color"] bold True outlines []
                        text _pulse_esc(_t["text"]) size 13 color "#EAEFF8" outlines []


screen pulse_devtools_overlay():
    style_prefix "pulse_ovl"
    modal True
    zorder 2000

    key "K_F12" action Hide("pulse_devtools_overlay")
    key "K_ESCAPE" action If(_pulse.editing_var is not None, SetField(_pulse, "editing_var", None), Hide("pulse_devtools_overlay"))

    $ _fn_short, _ln_num = _pulse.get_current_file_line()

    # Dark backdrop
    frame:
        xsize 1920
        ysize 1080
        background Solid("#04070de8")
        padding (36, 28)

        vbox:
            spacing 12
            xfill True
            yfill True

            # ------------------------------------------------------------------
            # HEADER BAR
            # ------------------------------------------------------------------
            frame:
                xfill True
                background Solid("#0c1322")
                padding (18, 12)
                hbox:
                    xfill True
                    yalign 0.5
                    hbox:
                        spacing 14
                        yalign 0.5
                        text "● REN'PY PULSE" size 22 color "#00F7FF" bold True outlines []
                        text ("Label: " + _pulse_esc(_pulse.current_label)) size 15 color "#FFFFFF" yalign 0.5 outlines []
                        text ("(" + _pulse_esc(_fn_short) + ":" + str(_ln_num) + ")") size 14 color "#8899B5" yalign 0.5 outlines []

                    hbox:
                        xalign 1.0
                        spacing 8
                        yalign 0.5
                        $ _hud_on = _pulse_is_mini_hud_visible()
                        button:
                            background Solid("#FF445540" if _pulse.macro_recording else "#1c2840")
                            hover_background Solid("#FF445566" if _pulse.macro_recording else "#2b3d60")
                            padding (10, 6)
                            action Function(_pulse.toggle_macro_recording)
                            text ("■ Stop Rec (" + str(len(_pulse.macro_steps)) + ")" if _pulse.macro_recording else "● Rec Macro") size 13 color ("#FF8899" if _pulse.macro_recording else "#B8C7E0") bold _pulse.macro_recording outlines []
                        button:
                            background Solid("#00FF8828" if _hud_on else "#1c2840")
                            hover_background Solid("#00FF8850" if _hud_on else "#2b3d60")
                            padding (10, 6)
                            action Function(_pulse_toggle_mini_hud)
                            text ("● Top-Left HUD: ON (Shift+P)" if _hud_on else "○ Top-Left HUD: OFF (Shift+P)") size 13 color ("#00FF88" if _hud_on else "#8899B5") bold True outlines []
                        button:
                            background Solid("#FF00D428")
                            hover_background Solid("#FF00D450")
                            padding (10, 6)
                            action Function(_pulse.open_second_window)
                            text "Pop Out 2nd Window (Shift+W)" size 13 color "#FF77E9" bold True outlines []
                        button:
                            background Solid("#FFB80028")
                            hover_background Solid("#FFB80050")
                            padding (10, 6)
                            action Function(_pulse.reset_all_store_vars)
                            text "Reset Store" size 13 color "#FFB800" outlines []
                        button:
                            background Solid("#1c2840")
                            hover_background Solid("#2b3d60")
                            padding (10, 6)
                            action Function(renpy.reload_script)
                            text "Reload (Shift+R)" size 13 color "#B8C7E0" outlines []
                        button:
                            background Solid("#FF445533")
                            hover_background Solid("#FF445566")
                            padding (12, 6)
                            action Hide("pulse_devtools_overlay")
                            text "Close (F12)" size 13 color "#FF8899" bold True outlines []

            # ------------------------------------------------------------------
            # NAVIGATION TABS
            # ------------------------------------------------------------------
            frame:
                xfill True
                background Solid("#090e1a")
                padding (10, 8)
                hbox:
                    spacing 6
                    for _tab_id, _tab_label in [
                        ("variables", "1. Variables"),
                        ("diffs", "2. Diffs (" + str(len(_pulse.diff_log)) + ")"),
                        ("teleport", "3. Teleport & Choices"),
                        ("presets", "4. Presets"),
                        ("inspector", "5. Screens & Layers"),
                        ("audio", "6. Audio"),
                        ("assets", "7. Assets & Styles"),
                        ("actions", "8. Actions & Macros"),
                        ("perf", "9. Perf & Lag"),
                    ]:
                        $ _is_tab = (_pulse.active_tab == _tab_id)
                        button:
                            background Solid("#00F7FF28" if _is_tab else "#121b2d")
                            hover_background Solid("#00F7FF40")
                            padding (10, 6)
                            action [SetField(_pulse, "active_tab", _tab_id), SetField(_pulse, "page_offset", 0)]
                            text _pulse_esc(_tab_label) size 13 color ("#00F7FF" if _is_tab else "#99AABB") bold _is_tab outlines []

            # ------------------------------------------------------------------
            # TAB 1: VARIABLES & PERSISTENT INSPECTOR
            # ------------------------------------------------------------------
            if _pulse.active_tab == "variables":
                $ _filtered_vars = _pulse.get_filtered_variables()
                $ _total_vars = len(_filtered_vars)
                $ _page_vars = _filtered_vars[_pulse.page_offset : _pulse.page_offset + _pulse.page_size]

                hbox:
                    spacing 14
                    xfill True
                    yfill True

                    # Category Sidebar
                    frame:
                        xsize 260
                        yfill True
                        background Solid("#0b111e")
                        padding (10, 10)
                        viewport:
                            scrollbars "vertical"
                            mousewheel True
                            draggable True
                            vbox:
                                spacing 4
                                xfill True
                                text "CATEGORIES" size 13 color "#667799" bold True outlines []
                                for _cat in _pulse.get_all_categories():
                                    $ _cat_sel = (_pulse.selected_category == _cat)
                                    button:
                                        xfill True
                                        background Solid("#00F7FF26" if _cat_sel else "#00000000")
                                        hover_background Solid("#18243a")
                                        padding (10, 6)
                                        action [SetField(_pulse, "selected_category", _cat), SetField(_pulse, "page_offset", 0)]
                                        text _pulse_esc(_cat) size 14 color ("#00F7FF" if _cat_sel else "#B8C7E0") outlines []

                    # Main Variable Table Area
                    vbox:
                        spacing 10
                        xfill True
                        yfill True

                        # Search & Pagination Toolbar
                        frame:
                            xfill True
                            background Solid("#0c1322")
                            padding (14, 8)
                            hbox:
                                xfill True
                                spacing 14
                                yalign 0.5
                                text "Filter:" size 15 color "#8899B5" yalign 0.5 outlines []
                                frame:
                                    xsize 460
                                    background Solid("#070b14")
                                    padding (10, 5)
                                    input:
                                        value FieldInputValue(_pulse, "search_query")
                                        size 15
                                        color "#00F7FF"
                                        outlines []
                                if _pulse.search_query:
                                    button:
                                        background Solid("#1c2840")
                                        padding (8, 4)
                                        action [SetField(_pulse, "search_query", ""), SetField(_pulse, "page_offset", 0)]
                                        text "Clear" size 13 color "#FFFFFF" outlines []

                                hbox:
                                    xalign 1.0
                                    spacing 10
                                    yalign 0.5
                                    text (str(_total_vars) + " matches") size 14 color "#8899B5" yalign 0.5 outlines []
                                    if _pulse.page_offset > 0:
                                        button:
                                            background Solid("#18243a")
                                            padding (10, 4)
                                            action SetField(_pulse, "page_offset", max(0, _pulse.page_offset - _pulse.page_size))
                                            text "< Prev" size 14 color "#00F7FF" outlines []
                                    if _pulse.page_offset + _pulse.page_size < _total_vars:
                                        button:
                                            background Solid("#18243a")
                                            padding (10, 4)
                                            action SetField(_pulse, "page_offset", _pulse.page_offset + _pulse.page_size)
                                            text "Next >" size 14 color "#00F7FF" outlines []

                        # Variable Rows Viewport
                        frame:
                            xfill True
                            yfill True
                            background Solid("#090f1b")
                            padding (12, 10)
                            viewport:
                                scrollbars "vertical"
                                mousewheel True
                                draggable True
                                vbox:
                                    spacing 6
                                    xfill True
                                    if not _page_vars:
                                        text "No variables match the current category and filter." size 16 color "#667799" outlines []
                                    for _v in _page_vars:
                                        frame:
                                            xfill True
                                            background Solid("#152036" if _v["modified"] else "#0f1728")
                                            padding (12, 8)
                                            hbox:
                                                xfill True
                                                yalign 0.5

                                                # Left Group: Star + Var Metadata (strictly left-aligned)
                                                hbox:
                                                    xalign 0.0
                                                    yalign 0.5
                                                    spacing 12

                                                    # Star / Watch Toggle
                                                    button:
                                                        xsize 32
                                                        yalign 0.5
                                                        background None
                                                        padding (4, 2)
                                                        action Function(_pulse.toggle_watch, _v["key"])
                                                        text ("★" if _v["watched"] else "☆") size 18 color ("#FFB800" if _v["watched"] else "#445577") xalign 0.5 outlines []

                                                    # Variable Name & Metadata
                                                    vbox:
                                                        xalign 0.0
                                                        yalign 0.5
                                                        xmaximum 780
                                                        spacing 2
                                                        hbox:
                                                            xalign 0.0
                                                            spacing 8
                                                            text _pulse_esc(_v["key"]) size 16 color ("#FFB800" if _v["modified"] else "#FFFFFF") bold True xalign 0.0 outlines []
                                                            text ("(" + _pulse_esc(_v["scope"]) + " : " + _pulse_esc(_v["type"]) + ")") size 13 color "#00F7FF" xalign 0.0 yalign 0.5 outlines []
                                                        text (_pulse_esc(_v["category"]) + " | " + _pulse_esc(_v["file_short"]) + ":" + str(_v["line"]) + " | default=" + _pulse_esc(_v["default_expr"])) size 12 color "#7788A5" xalign 0.0 outlines []

                                                # Type-Aware Value Controls
                                                hbox:
                                                    xalign 1.0
                                                    spacing 6
                                                    yalign 0.5
                                                    if _v["type"] == "bool":
                                                        button:
                                                            background Solid("#00FF8833" if _v["value"] else "#FF445533")
                                                            hover_background Solid("#00FF8866" if _v["value"] else "#FF445566")
                                                            padding (14, 5)
                                                            action Function(_pulse.toggle_bool, _v["key"])
                                                            text ("TRUE" if _v["value"] else "FALSE") size 14 color ("#00FF88" if _v["value"] else "#FF6677") bold True outlines []
                                                    elif _v["type"] in ("int", "float"):
                                                        button:
                                                            background Solid("#1a2740")
                                                            hover_background Solid("#2a3d64")
                                                            padding (8, 4)
                                                            action Function(_pulse.step_number, _v["key"], -10)
                                                            text "-10" size 13 color "#B8C7E0" outlines []
                                                        button:
                                                            background Solid("#1a2740")
                                                            hover_background Solid("#2a3d64")
                                                            padding (8, 4)
                                                            action Function(_pulse.step_number, _v["key"], -1)
                                                            text "-1" size 13 color "#B8C7E0" outlines []
                                                        frame:
                                                            background Solid("#060a12")
                                                            padding (12, 4)
                                                            text _pulse_esc(_v["val_repr"]) size 15 color "#00FF88" bold True outlines []
                                                        button:
                                                            background Solid("#1a2740")
                                                            hover_background Solid("#2a3d64")
                                                            padding (8, 4)
                                                            action Function(_pulse.step_number, _v["key"], 1)
                                                            text "+1" size 13 color "#B8C7E0" outlines []
                                                        button:
                                                            background Solid("#1a2740")
                                                            hover_background Solid("#2a3d64")
                                                            padding (8, 4)
                                                            action Function(_pulse.step_number, _v["key"], 10)
                                                            text "+10" size 13 color "#B8C7E0" outlines []
                                                    else:
                                                        frame:
                                                            background Solid("#060a12")
                                                            padding (12, 4)
                                                            text _pulse_esc(_v["val_repr"]) size 14 color "#00FF88" outlines []

                                                    if _v["line"] > 0:
                                                        button:
                                                            background Solid("#1a2740")
                                                            hover_background Solid("#00F7FF44")
                                                            padding (8, 4)
                                                            action Function(_pulse.open_in_editor, _v["file"], _v["line"])
                                                            text "Code" size 13 color "#00F7FF" outlines []

                                                    button:
                                                        background Solid("#00F7FF22")
                                                        hover_background Solid("#00F7FF44")
                                                        padding (10, 4)
                                                        action Function(_pulse.open_inline_editor, _v["key"])
                                                        text "Edit" size 13 color "#00F7FF" outlines []

                                                    button:
                                                        background Solid("#1a2740")
                                                        hover_background Solid("#FFB80044")
                                                        padding (8, 4)
                                                        action Function(_pulse.reset_var, _v["key"])
                                                        text "Reset" size 13 color "#99AABB" outlines []

            # ------------------------------------------------------------------
            # TAB 2: LIVE DIFF LOG
            # ------------------------------------------------------------------
            elif _pulse.active_tab == "diffs":
                frame:
                    xfill True
                    yfill True
                    background Solid("#090f1b")
                    padding (16, 14)
                    vbox:
                        spacing 10
                        xfill True
                        yfill True
                        hbox:
                            xfill True
                            text "REAL-TIME VARIABLE CHANGE HISTORY" size 16 color "#00F7FF" bold True outlines []
                            hbox:
                                xalign 1.0
                                spacing 12
                                button:
                                    background Solid("#00FF8828")
                                    hover_background Solid("#00FF8850")
                                    padding (10, 4)
                                    action Function(_pulse.save_recent_diffs_as_macro, 10)
                                    text "+ Save Last 10 Diffs as Macro" size 13 color "#00FF88" bold True outlines []
                                button:
                                    background Solid("#1a2740")
                                    padding (10, 4)
                                    action ToggleField(persistent, "_pulse_toasts_enabled")
                                    text ("Corner Diff Toasts: " + ("ON" if (getattr(persistent, "_pulse_toasts_enabled", True) is not False) else "OFF")) size 13 color "#00FF88" outlines []
                                button:
                                    background Solid("#FF445533")
                                    padding (10, 4)
                                    action SetField(_pulse, "diff_log", [])
                                    text "Clear History" size 13 color "#FF8899" outlines []

                        viewport:
                            scrollbars "vertical"
                            mousewheel True
                            draggable True
                            vbox:
                                spacing 6
                                xfill True
                                if not _pulse.diff_log:
                                    text "No variable mutations logged yet. Advance dialogue, make a choice, or edit a variable!" size 15 color "#667799" outlines []
                                for _d in _pulse.diff_log:
                                    frame:
                                        xfill True
                                        background Solid("#10192b")
                                        padding (12, 8)
                                        hbox:
                                            xfill True
                                            yalign 0.5
                                            vbox:
                                                spacing 2
                                                hbox:
                                                    spacing 10
                                                    text _pulse_esc(_d["var_key"]) size 16 color "#FFFFFF" bold True outlines []
                                                    text ("(" + _pulse_esc(_d["source"]) + ")") size 13 color "#00F7FF" outlines []
                                                text (_pulse_esc(_d["time"]) + " | Label: " + _pulse_esc(_d["label"]) + " | " + _pulse_esc(_d["file_line"])) size 12 color "#7788A5" outlines []
                                            hbox:
                                                xalign 1.0
                                                spacing 10
                                                yalign 0.5
                                                text _pulse_esc(_d["old_repr"]) size 14 color "#99AABB" outlines []
                                                text "->" size 14 color "#00F7FF" bold True outlines []
                                                text _pulse_esc(_d["new_repr"]) size 14 color "#00FF88" bold True outlines []
                                                if _d.get("line", 0) > 0:
                                                    button:
                                                        background Solid("#1a2740")
                                                        hover_background Solid("#00F7FF44")
                                                        padding (8, 4)
                                                        action Function(_pulse.open_in_editor, _d.get("file", ""), _d.get("line", 1))
                                                        text "Code" size 13 color "#00F7FF" outlines []
                                                button:
                                                    background Solid("#FFB80033")
                                                    hover_background Solid("#FFB80066")
                                                    padding (10, 4)
                                                    action Function(_pulse.undo_diff, _d["id"])
                                                    text "Undo" size 13 color "#FFB800" bold True outlines []

            # ------------------------------------------------------------------
            # TAB 3: SCENE TELEPORTER & CHOICE CONDITION UNLOCKER
            # ------------------------------------------------------------------
            elif _pulse.active_tab == "teleport":
                $ _rel_menus = _pulse.get_relevant_menus()
                $ _filt_labels = _pulse.get_filtered_labels()
                hbox:
                    spacing 16
                    xfill True
                    yfill True

                    # Left Column: Choice Condition Analyzer
                    frame:
                        xsize 880
                        yfill True
                        background Solid("#090f1b")
                        padding (14, 12)
                        vbox:
                            spacing 10
                            xfill True
                            yfill True
                            text ("CHOICE CONDITION INSPECTOR (Near " + _pulse_esc(_pulse.current_label) + ")") size 16 color "#00F7FF" bold True outlines []
                            viewport:
                                scrollbars "vertical"
                                mousewheel True
                                draggable True
                                vbox:
                                    spacing 10
                                    xfill True
                                    if not _rel_menus:
                                        text "No `menu:` blocks found in the active label or within 350 lines of current execution." size 14 color "#667799" outlines []
                                    for _m in _rel_menus:
                                        frame:
                                            xfill True
                                            background Solid("#10192b")
                                            padding (12, 10)
                                            vbox:
                                                spacing 6
                                                xfill True
                                                hbox:
                                                    xfill True
                                                    yalign 0.5
                                                    text ("Menu: " + _pulse_esc(_m["name"]) + " (" + _pulse_esc(_m["file_short"]) + ":" + str(_m["line"]) + ")") size 15 color "#FFB800" bold True outlines []
                                                    button:
                                                        xalign 1.0
                                                        background Solid("#1a2740")
                                                        hover_background Solid("#00F7FF44")
                                                        padding (8, 3)
                                                        action Function(_pulse.open_in_editor, _m["file_short"], _m["line"])
                                                        text "Code" size 12 color "#00F7FF" outlines []
                                                for _ch in _m["choices"]:
                                                    frame:
                                                        xfill True
                                                        background Solid("#0a101d")
                                                        padding (10, 6)
                                                        hbox:
                                                            xfill True
                                                            yalign 0.5
                                                            vbox:
                                                                xsize 620
                                                                spacing 2
                                                                text ('"' + _pulse_esc(_ch["caption"]) + '"') size 14 color "#FFFFFF" outlines []
                                                                if _ch["condition"]:
                                                                    text ("if " + _pulse_esc(_ch["condition"]) + "  (" + _pulse_esc(_ch["vars_summary"]) + ")") size 12 color "#8899B5" outlines []
                                                                else:
                                                                    text "Unconditional choice (Always unlocked)" size 12 color "#556688" outlines []
                                                            hbox:
                                                                xalign 1.0
                                                                spacing 8
                                                                yalign 0.5
                                                                if _ch["condition"]:
                                                                    text ("UNLOCKED" if _ch["passed"] else "LOCKED") size 13 color ("#00FF88" if _ch["passed"] else "#FF4455") bold True yalign 0.5 outlines []
                                                                    if not _ch["passed"]:
                                                                        button:
                                                                            background Solid("#00FF8833")
                                                                            hover_background Solid("#00FF8866")
                                                                            padding (10, 4)
                                                                            action Function(_pulse.force_satisfy_condition, _ch["condition"])
                                                                            text "Force Unlock" size 13 color "#00FF88" bold True outlines []
                                                                else:
                                                                    text "OPEN" size 13 color "#00F7FF" outlines []

                    # Right Column: Label Teleporter
                    frame:
                        xfill True
                        yfill True
                        background Solid("#090f1b")
                        padding (14, 12)
                        vbox:
                            spacing 10
                            xfill True
                            yfill True
                            hbox:
                                spacing 10
                                yalign 0.5
                                text "SEARCH LABELS:" size 15 color "#00F7FF" bold True yalign 0.5 outlines []
                                frame:
                                    xsize 420
                                    background Solid("#060a12")
                                    padding (10, 5)
                                    input:
                                        value FieldInputValue(_pulse, "label_search")
                                        size 15
                                        color "#00F7FF"
                                        outlines []
                            viewport:
                                scrollbars "vertical"
                                mousewheel True
                                draggable True
                                vbox:
                                    spacing 5
                                    xfill True
                                    for _lbl in _filt_labels[:100]:
                                        frame:
                                            xfill True
                                            background Solid("#10192b")
                                            padding (10, 6)
                                            hbox:
                                                xfill True
                                                yalign 0.5
                                                vbox:
                                                    text _pulse_esc(_lbl["name"]) size 15 color "#FFFFFF" bold True outlines []
                                                    text (_pulse_esc(_lbl["file"]) + ":" + str(_lbl["line"])) size 12 color "#7788A5" outlines []
                                                hbox:
                                                    xalign 1.0
                                                    spacing 8
                                                    button:
                                                        background Solid("#1a2740")
                                                        hover_background Solid("#00F7FF44")
                                                        padding (10, 4)
                                                        action Function(_pulse.open_in_editor, _lbl["file"], _lbl["line"])
                                                        text "Code" size 13 color "#00F7FF" outlines []
                                                    button:
                                                        background Solid("#00F7FF28")
                                                        hover_background Solid("#00F7FF55")
                                                        padding (12, 4)
                                                        action Function(_pulse.jump_to_label, _lbl["name"])
                                                        text "Jump" size 13 color "#00F7FF" bold True outlines []
                                                    button:
                                                        background Solid("#1a2740")
                                                        hover_background Solid("#2a3d64")
                                                        padding (12, 4)
                                                        action Function(_pulse.call_label_in_context, _lbl["name"])
                                                        text "Call" size 13 color "#B8C7E0" outlines []

            # ------------------------------------------------------------------
            # TAB 4: ROUTE PRESETS ("LOADOUTS")
            # ------------------------------------------------------------------
            elif _pulse.active_tab == "presets":
                $ _presets = _pulse.list_presets()
                frame:
                    xfill True
                    yfill True
                    background Solid("#090f1b")
                    padding (16, 14)
                    vbox:
                        spacing 12
                        xfill True
                        yfill True
                        hbox:
                            spacing 12
                            yalign 0.5
                            text "Preset Name:" size 15 color "#B8C7E0" yalign 0.5 outlines []
                            frame:
                                xsize 380
                                background Solid("#060a12")
                                padding (10, 6)
                                input:
                                    value FieldInputValue(_pulse, "preset_name_input")
                                    size 15
                                    color "#00F7FF"
                                    outlines []
                            button:
                                background Solid("#00FF8833")
                                hover_background Solid("#00FF8866")
                                padding (14, 6)
                                action Function(_pulse.save_preset)
                                text "+ Save Current Variables as Preset" size 14 color "#00FF88" bold True outlines []
                            if _pulse.preset_status_msg:
                                text _pulse_esc(_pulse.preset_status_msg) size 14 color "#00F7FF" yalign 0.5 outlines []

                        viewport:
                            scrollbars "vertical"
                            mousewheel True
                            draggable True
                            vbox:
                                spacing 8
                                xfill True
                                if not _presets:
                                    text "No route presets saved yet. Type a name above and click '+ Save Current Variables as Preset'!" size 15 color "#667799" outlines []
                                for _p in _presets:
                                    frame:
                                        xfill True
                                        background Solid("#10192b")
                                        padding (14, 10)
                                        hbox:
                                            xfill True
                                            yalign 0.5
                                            vbox:
                                                spacing 2
                                                text (_pulse_esc(_p["name"]) + "  (" + str(_p["var_count"]) + " variables)") size 16 color "#FFFFFF" bold True outlines []
                                                text ("Bookmarked Label: " + _pulse_esc(_p["label"]) + " | Created: " + _pulse_esc(_p["created"])) size 13 color "#7788A5" outlines []
                                            hbox:
                                                xalign 1.0
                                                spacing 10
                                                button:
                                                    background Solid("#00F7FF28")
                                                    hover_background Solid("#00F7FF55")
                                                    padding (12, 5)
                                                    action Function(_pulse.load_preset, _p["filename"], False)
                                                    text "Load Variables Only" size 14 color "#00F7FF" bold True outlines []
                                                button:
                                                    background Solid("#00FF8828")
                                                    hover_background Solid("#00FF8855")
                                                    padding (12, 5)
                                                    action Function(_pulse.load_preset, _p["filename"], True)
                                                    text ("Load + Jump to " + _pulse_esc(_p["label"])) size 14 color "#00FF88" bold True outlines []
                                                button:
                                                    background Solid("#FF445528")
                                                    hover_background Solid("#FF445555")
                                                    padding (12, 5)
                                                    action Function(_pulse.delete_preset, _p["filename"])
                                                    text "Delete" size 14 color "#FF8899" outlines []

            # ------------------------------------------------------------------
            # TAB 5: LIVE SCREEN & LAYER INSPECTOR
            # ------------------------------------------------------------------
            elif _pulse.active_tab == "inspector":
                $ _act_screens = _pulse.get_active_screens()
                $ _show_imgs = _pulse.get_showing_images()
                hbox:
                    spacing 16
                    xfill True
                    yfill True

                    # Active Screens Column
                    frame:
                        xsize 900
                        yfill True
                        background Solid("#090f1b")
                        padding (14, 12)
                        vbox:
                            spacing 8
                            xfill True
                            yfill True
                            text "ACTIVE SCREENS" size 16 color "#00F7FF" bold True outlines []
                            viewport:
                                scrollbars "vertical"
                                mousewheel True
                                draggable True
                                vbox:
                                    spacing 6
                                    xfill True
                                    for _s in _act_screens:
                                        frame:
                                            xfill True
                                            background Solid("#10192b")
                                            padding (10, 6)
                                            hbox:
                                                xfill True
                                                yalign 0.5
                                                text (_pulse_esc(_s["name"]) + " (" + _pulse_esc(_s["layer"]) + ")") size 14 color "#FFFFFF" outlines []
                                                button:
                                                    xalign 1.0
                                                    background Solid("#FFB80033")
                                                    padding (10, 3)
                                                    action Function(_pulse.toggle_screen_by_name, _s["name"])
                                                    text "Hide" size 13 color "#FFB800" outlines []

                    # Showing Images / CGs Column
                    frame:
                        xfill True
                        yfill True
                        background Solid("#090f1b")
                        padding (14, 12)
                        vbox:
                            spacing 8
                            xfill True
                            yfill True
                            text "SHOWING IMAGES & MOVIES" size 16 color "#00F7FF" bold True outlines []
                            viewport:
                                scrollbars "vertical"
                                mousewheel True
                                draggable True
                                vbox:
                                    spacing 6
                                    xfill True
                                    if not _show_imgs:
                                        text "No images or movies currently displayed on master/transient/overlay layers." size 14 color "#667799" outlines []
                                    for _img in _show_imgs:
                                        frame:
                                            xfill True
                                            background Solid("#10192b")
                                            padding (10, 6)
                                            hbox:
                                                xfill True
                                                yalign 0.5
                                                text (_pulse_esc(_img["full"]) + " (" + _pulse_esc(_img["layer"]) + ")") size 14 color "#FFFFFF" outlines []
                                                button:
                                                    xalign 1.0
                                                    background Solid("#FFB80033")
                                                    padding (10, 3)
                                                    action Function(_pulse.hide_showing_image, _img["tag"], _img["layer"])
                                                    text "Hide" size 13 color "#FFB800" outlines []

            # ------------------------------------------------------------------
            # TAB 6: DEDICATED AUDIO CHANNEL INSPECTOR
            # ------------------------------------------------------------------
            elif _pulse.active_tab == "audio":
                $ _aud_chans = _pulse.get_audio_channels_status()
                frame:
                    xfill True
                    yfill True
                    background Solid("#090f1b")
                    padding (16, 14)
                    vbox:
                        spacing 12
                        xfill True
                        yfill True
                        hbox:
                            xfill True
                            yalign 0.5
                            text "MULTI-CHANNEL AUDIO INSPECTOR" size 16 color "#00F7FF" bold True outlines []
                            text "Monitor active tracks, playback progress, mixer & channel volumes, and queued audio" size 13 color "#8899B5" xalign 1.0 yalign 0.5 outlines []

                        viewport:
                            scrollbars "vertical"
                            mousewheel True
                            draggable True
                            vbox:
                                spacing 10
                                xfill True
                                if not _aud_chans:
                                    frame:
                                        xfill True
                                        background Solid("#10192b")
                                        padding (16, 14)
                                        vbox:
                                            spacing 6
                                            text "No registered or active audio channels reported." size 15 color "#99AABB" outlines []
                                            if _pulse.last_audio_error:
                                                text ("Diagnostic: " + _pulse_esc(_pulse.last_audio_error)) size 13 color "#FF6677" outlines []
                                for _ch in _aud_chans:
                                    $ _c_vol = float(_ch.get("chan_volume", 1.0))
                                    $ _m_vol = float(_ch.get("mixer_volume", 1.0))
                                    $ _a_pct = float(_ch.get("progress_pct", 0.0))
                                    frame:
                                        xfill True
                                        background Solid("#10192b")
                                        padding (14, 10)
                                        vbox:
                                            spacing 6
                                            xfill True
                                            hbox:
                                                xfill True
                                                yalign 0.5
                                                hbox:
                                                    spacing 10
                                                    yalign 0.5
                                                    text _pulse_esc(_ch["channel"]) size 17 color "#00FF88" bold True outlines []
                                                    text ("(mixer: " + _pulse_esc(_ch.get("mixer", "music")) + ")") size 13 color "#00F7FF" yalign 0.5 outlines []
                                                    if _ch.get("muted"):
                                                        text "[[MUTED]]" size 12 color "#FF4455" bold True yalign 0.5 outlines []
                                                    if _ch.get("paused"):
                                                        text "[[PAUSED]]" size 12 color "#FFB800" bold True yalign 0.5 outlines []
                                                text ("Chan: " + str(int(_c_vol * 100)) + "%  |  Mixer: " + str(int(_m_vol * 100)) + "%  |  Pos: " + str(_ch.get("pos", 0.0)) + "s / " + str(_ch.get("duration", 0.0)) + "s") size 13 color "#B8C7E0" xalign 1.0 yalign 0.5 outlines []

                                            text _pulse_esc(_ch["playing"] if _ch["playing"] else "Idle — no track playing") size 14 color ("#FFFFFF" if _ch["playing"] else "#667799") outlines []

                                            frame:
                                                xsize 1760
                                                ysize 6
                                                padding (0, 0)
                                                background Solid("#060a12")
                                                frame:
                                                    xsize max(2, int(1760.0 * min(100.0, _a_pct) / 100.0))
                                                    ysize 6
                                                    padding (0, 0)
                                                    background Solid("#00F7FF" if _ch["playing"] else "#1a2740")

                                            hbox:
                                                spacing 8
                                                yalign 0.5
                                                button:
                                                    background Solid("#1a2740")
                                                    hover_background Solid("#2a3d64")
                                                    padding (10, 4)
                                                    action Function(_pulse.set_audio_volume, _ch["channel"], max(0.0, _c_vol - 0.1))
                                                    text "Vol -10%" size 13 color "#B8C7E0" outlines []
                                                button:
                                                    background Solid("#1a2740")
                                                    hover_background Solid("#2a3d64")
                                                    padding (10, 4)
                                                    action Function(_pulse.set_audio_volume, _ch["channel"], min(1.0, _c_vol + 0.1))
                                                    text "Vol +10%" size 13 color "#B8C7E0" outlines []
                                                button:
                                                    background Solid("#1a2740")
                                                    hover_background Solid("#2a3d64")
                                                    padding (10, 4)
                                                    action Function(_pulse.set_audio_volume, _ch["channel"], 1.0)
                                                    text "100%" size 13 color "#00FF88" outlines []
                                                if _ch["playing"]:
                                                    button:
                                                        background Solid("#00F7FF28")
                                                        hover_background Solid("#00F7FF50")
                                                        padding (12, 4)
                                                        action Function(_pulse.toggle_audio_pause, _ch["channel"])
                                                        text ("Resume" if _ch.get("paused") else "Pause") size 13 color "#00F7FF" bold True outlines []
                                                    button:
                                                        background Solid("#FF445533")
                                                        hover_background Solid("#FF445566")
                                                        padding (12, 4)
                                                        action Function(_pulse.stop_audio_channel, _ch["channel"])
                                                        text "Stop" size 13 color "#FF8899" bold True outlines []
                                                if _ch.get("queue"):
                                                    button:
                                                        background Solid("#FFB80028")
                                                        hover_background Solid("#FFB80050")
                                                        padding (12, 4)
                                                        action Function(_pulse.clear_audio_queue, _ch["channel"])
                                                        text ("Clear Queue (" + str(len(_ch["queue"])) + ")") size 13 color "#FFB800" outlines []

                                            if _ch.get("queue"):
                                                text ("Queued: " + _pulse_esc(" -> ".join([_q["short"] for _q in _ch["queue"]]))) size 12 color "#8899B5" outlines []

            # ------------------------------------------------------------------
            # TAB 7: IN-GAME ASSET & STYLE PREVIEWER
            # ------------------------------------------------------------------
            elif _pulse.active_tab == "assets":
                vbox:
                    spacing 10
                    xfill True
                    yfill True

                    # Subtab Switcher Bar
                    frame:
                        xfill True
                        background Solid("#0c1322")
                        padding (12, 8)
                        hbox:
                            spacing 10
                            yalign 0.5
                            button:
                                background Solid("#00F7FF33" if _pulse.asset_subtab == "images" else "#121b2d")
                                padding (14, 6)
                                action SetField(_pulse, "asset_subtab", "images")
                                text "Images & Sprites Gallery" size 14 color ("#00F7FF" if _pulse.asset_subtab == "images" else "#99AABB") bold True outlines []
                            button:
                                background Solid("#00F7FF33" if _pulse.asset_subtab == "styles" else "#121b2d")
                                padding (14, 6)
                                action SetField(_pulse, "asset_subtab", "styles")
                                text "Style Inspector" size 14 color ("#00F7FF" if _pulse.asset_subtab == "styles" else "#99AABB") bold True outlines []

                    if _pulse.asset_subtab == "images":
                        $ _img_items, _img_tags, _img_total = _pulse.get_registered_images_list()
                        if _pulse.selected_image_name is None and _img_items:
                            $ _pulse.selected_image_name = _img_items[0]["name"]
                        $ _sel_img_info = None
                        for _ii in _img_items:
                            if _ii["name"] == _pulse.selected_image_name:
                                $ _sel_img_info = _ii
                        hbox:
                            spacing 14
                            xfill True
                            yfill True

                            # Left: Search, Tags & Image List
                            frame:
                                xsize 820
                                yfill True
                                background Solid("#090f1b")
                                padding (12, 10)
                                vbox:
                                    spacing 8
                                    xfill True
                                    yfill True
                                    hbox:
                                        spacing 10
                                        yalign 0.5
                                        text "Search:" size 14 color "#8899B5" yalign 0.5 outlines []
                                        frame:
                                            xsize 420
                                            background Solid("#060a12")
                                            padding (10, 5)
                                            input:
                                                value FieldInputValue(_pulse, "asset_search")
                                                size 14
                                                color "#00F7FF"
                                                outlines []
                                        text (str(_img_total) + " images") size 13 color "#8899B5" yalign 0.5 outlines []

                                    viewport:
                                        ysize 40
                                        scrollbars "horizontal"
                                        mousewheel True
                                        hbox:
                                            spacing 6
                                            for _tg in _img_tags[:40]:
                                                $ _tg_sel = (_pulse.asset_tag_filter == _tg)
                                                button:
                                                    background Solid("#00F7FF33" if _tg_sel else "#121b2d")
                                                    padding (10, 4)
                                                    action SetField(_pulse, "asset_tag_filter", _tg)
                                                    text _pulse_esc(_tg) size 12 color ("#00F7FF" if _tg_sel else "#B8C7E0") outlines []

                                    viewport:
                                        scrollbars "vertical"
                                        mousewheel True
                                        draggable True
                                        vbox:
                                            spacing 5
                                            xfill True
                                            for _ii in _img_items:
                                                $ _is_sel_img = (_ii["name"] == _pulse.selected_image_name)
                                                button:
                                                    xfill True
                                                    background Solid("#00F7FF24" if _is_sel_img else "#10192b")
                                                    hover_background Solid("#1a2740")
                                                    padding (10, 6)
                                                    action SetField(_pulse, "selected_image_name", _ii["name"])
                                                    hbox:
                                                        xfill True
                                                        yalign 0.5
                                                        text _pulse_esc(_ii["name"]) size 14 color ("#00F7FF" if _is_sel_img else "#FFFFFF") bold _is_sel_img outlines []
                                                        text _pulse_esc(_ii["type"]) size 12 color "#7788A5" xalign 1.0 outlines []

                            # Right: Live Image Preview
                            frame:
                                xfill True
                                yfill True
                                background Solid("#090f1b")
                                padding (14, 12)
                                vbox:
                                    spacing 10
                                    xfill True
                                    yfill True
                                    if _pulse.selected_image_name:
                                        text _pulse_esc(_pulse.selected_image_name) size 18 color "#00F7FF" bold True outlines []
                                        if _sel_img_info:
                                            text ("Type: " + _pulse_esc(_sel_img_info["type"]) + "  |  Source: " + _pulse_esc(_sel_img_info["file"] or "Composite / Dynamic")) size 12 color "#8899B5" outlines []
                                        frame:
                                            xfill True
                                            ysize 500
                                            background Solid("#05080f")
                                            padding (10, 10)
                                            add Transform(_pulse.selected_image_name, xysize=(900, 470), fit="contain") xalign 0.5 yalign 0.5
                                        hbox:
                                            spacing 10
                                            button:
                                                background Solid("#00FF8833")
                                                hover_background Solid("#00FF8866")
                                                padding (14, 6)
                                                action Function(_pulse.preview_image_on_master, _pulse.selected_image_name)
                                                text "Show on Master Layer" size 14 color "#00FF88" bold True outlines []
                                            button:
                                                background Solid("#FFB80033")
                                                hover_background Solid("#FFB80066")
                                                padding (14, 6)
                                                action Function(_pulse.hide_showing_image, _pulse.selected_image_name.split(" ")[0], "master")
                                                text "Hide Tag" size 14 color "#FFB800" outlines []
                                            if _sel_img_info and _sel_img_info.get("has_file"):
                                                button:
                                                    background Solid("#1a2740")
                                                    hover_background Solid("#00F7FF44")
                                                    padding (14, 6)
                                                    action Function(_pulse.open_in_editor, _sel_img_info["file"], 1)
                                                    text "Open File" size 14 color "#00F7FF" outlines []
                                    else:
                                        text "No registered images found." size 15 color "#667799" outlines []

                    else:
                        $ _sty_items, _sty_total = _pulse.get_styles_list()
                        $ _sel_sty = _pulse.inspect_style_details(_pulse.selected_style_name)
                        hbox:
                            spacing 14
                            xfill True
                            yfill True

                            # Left: Style List
                            frame:
                                xsize 680
                                yfill True
                                background Solid("#090f1b")
                                padding (12, 10)
                                vbox:
                                    spacing 8
                                    xfill True
                                    yfill True
                                    hbox:
                                        spacing 8
                                        yalign 0.5
                                        frame:
                                            xsize 340
                                            background Solid("#060a12")
                                            padding (10, 5)
                                            input:
                                                value FieldInputValue(_pulse, "style_search")
                                                size 14
                                                color "#00F7FF"
                                                outlines []
                                        button:
                                            background Solid("#00F7FF33" if _pulse.style_scope_filter == "All" else "#121b2d")
                                            padding (10, 5)
                                            action SetField(_pulse, "style_scope_filter", "All")
                                            text "All" size 13 color "#FFFFFF" outlines []
                                        button:
                                            background Solid("#00F7FF33" if _pulse.style_scope_filter == "Customized" else "#121b2d")
                                            padding (10, 5)
                                            action SetField(_pulse, "style_scope_filter", "Customized")
                                            text "Custom" size 13 color "#00FF88" outlines []
                                    viewport:
                                        scrollbars "vertical"
                                        mousewheel True
                                        draggable True
                                        vbox:
                                            spacing 5
                                            xfill True
                                            for _st in _sty_items:
                                                $ _is_sel_st = (_st["name"] == _pulse.selected_style_name)
                                                button:
                                                    xfill True
                                                    background Solid("#00F7FF24" if _is_sel_st else "#10192b")
                                                    hover_background Solid("#1a2740")
                                                    padding (10, 6)
                                                    action SetField(_pulse, "selected_style_name", _st["name"])
                                                    hbox:
                                                        xfill True
                                                        yalign 0.5
                                                        text _pulse_esc(_st["name"]) size 14 color ("#00F7FF" if _is_sel_st else "#FFFFFF") bold _is_sel_st outlines []
                                                        if _st["parent"]:
                                                            text ("is " + _pulse_esc(_st["parent"])) size 12 color "#7788A5" xalign 1.0 outlines []

                            # Right: Style Property Inspector
                            frame:
                                xfill True
                                yfill True
                                background Solid("#090f1b")
                                padding (14, 12)
                                vbox:
                                    spacing 8
                                    xfill True
                                    yfill True
                                    if _sel_sty:
                                        text ("STYLE: " + _pulse_esc(_sel_sty["name"]) + ("  (inherits " + _pulse_esc(_sel_sty["parent"]) + ")" if _sel_sty["parent"] else "")) size 16 color "#00F7FF" bold True outlines []
                                        viewport:
                                            scrollbars "vertical"
                                            mousewheel True
                                            draggable True
                                            vbox:
                                                spacing 6
                                                xfill True
                                                text "RESOLVED KEY PROPERTIES" size 13 color "#7788A5" bold True outlines []
                                                for _rp in _sel_sty["resolved"]:
                                                    frame:
                                                        xfill True
                                                        background Solid("#10192b")
                                                        padding (10, 5)
                                                        hbox:
                                                            xfill True
                                                            text _pulse_esc(_rp["prop"]) size 13 color "#00F7FF" outlines []
                                                            text _pulse_esc(_rp["val"]) size 13 color "#00FF88" xalign 1.0 outlines []
                                                if _sel_sty["chain"]:
                                                    text "INHERITANCE CHAIN" size 13 color "#7788A5" bold True outlines []
                                                    for _ch_item in _sel_sty["chain"]:
                                                        frame:
                                                            xfill True
                                                            background Solid("#0d1524")
                                                            padding (10, 6)
                                                            vbox:
                                                                spacing 2
                                                                text _pulse_esc(_ch_item["style"]) size 14 color "#FFB800" bold True outlines []
                                                                text _pulse_esc(" | ".join([_p["prop"] + "=" + _p["val"] for _p in _ch_item["props"]]) if _ch_item["props"] else "(inherits parent defaults)") size 12 color "#B8C7E0" outlines []
                                    else:
                                        text "Select a style on the left to inspect its properties." size 14 color "#667799" outlines []

            # ------------------------------------------------------------------
            # TAB 8: QUICK ACTIONS, MACROS & PYTHON CONSOLE
            # ------------------------------------------------------------------
            elif _pulse.active_tab == "actions":
                $ _macros = _pulse.list_macros()
                hbox:
                    spacing 16
                    xfill True
                    yfill True

                    # Left: Registered Quick Actions + Macro Recorder/Runner + Safe Persistent Tools
                    frame:
                        xsize 980
                        yfill True
                        background Solid("#090f1b")
                        padding (14, 12)
                        vbox:
                            spacing 10
                            xfill True
                            yfill True
                            hbox:
                                xfill True
                                yalign 0.5
                                text "QUICK ACTIONS, MACROS & PERSISTENT" size 16 color "#00F7FF" bold True outlines []
                                hbox:
                                    xalign 1.0
                                    spacing 8
                                    button:
                                        background Solid("#00FF8828")
                                        padding (10, 4)
                                        action Function(_pulse.backup_persistent_data)
                                        text "Backup Persistent" size 13 color "#00FF88" outlines []
                                    button:
                                        background Solid("#00F7FF28")
                                        padding (10, 4)
                                        action Function(_pulse.restore_persistent_backup)
                                        text "Restore Backup" size 13 color "#00F7FF" outlines []
                                    button:
                                        background Solid("#FF445528")
                                        padding (10, 4)
                                        action Function(_pulse.reset_all_persistent_vars)
                                        text "Reset Persistent" size 13 color "#FF8899" outlines []

                            # Macro Recorder Controls
                            frame:
                                xfill True
                                background Solid("#0d1524")
                                padding (12, 8)
                                vbox:
                                    spacing 6
                                    xfill True
                                    hbox:
                                        xfill True
                                        yalign 0.5
                                        spacing 8
                                        text ("MACRO RECORDER (" + str(len(_pulse.macro_steps)) + " steps)") size 14 color "#FF77E9" bold True yalign 0.5 outlines []
                                        frame:
                                            xsize 260
                                            background Solid("#060a12")
                                            padding (8, 4)
                                            input:
                                                value FieldInputValue(_pulse, "macro_name_input")
                                                size 13
                                                color "#00F7FF"
                                                outlines []
                                        button:
                                            background Solid("#FF445540" if _pulse.macro_recording else "#00F7FF28")
                                            padding (10, 4)
                                            action Function(_pulse.toggle_macro_recording)
                                            text ("■ Stop Rec" if _pulse.macro_recording else "● Start Rec") size 13 color ("#FF8899" if _pulse.macro_recording else "#00F7FF") bold True outlines []
                                        button:
                                            background Solid("#00FF8833")
                                            padding (10, 4)
                                            action Function(_pulse.save_recorded_macro)
                                            text "Save Macro" size 13 color "#00FF88" bold True outlines []
                                        button:
                                            background Solid("#1a2740")
                                            padding (8, 4)
                                            action Function(_pulse.clear_macro_steps)
                                            text "Clear" size 13 color "#B8C7E0" outlines []
                                    if _pulse.macro_status_msg:
                                        text _pulse_esc(_pulse.macro_status_msg) size 12 color "#00F7FF" outlines []

                            viewport:
                                scrollbars "vertical"
                                mousewheel True
                                draggable True
                                vbox:
                                    spacing 6
                                    xfill True
                                    if _macros:
                                        text "SAVED MACROS" size 13 color "#7788A5" bold True outlines []
                                        for _mc in _macros:
                                            frame:
                                                xfill True
                                                background Solid("#131e33")
                                                padding (10, 7)
                                                hbox:
                                                    xfill True
                                                    yalign 0.5
                                                    vbox:
                                                        xsize 680
                                                        text (_pulse_esc(_mc["name"]) + "  (" + str(_mc["step_count"]) + " steps)") size 14 color "#FFFFFF" bold True outlines []
                                                        text _pulse_esc(_mc["summary"]) size 12 color "#8899B5" outlines []
                                                    hbox:
                                                        xalign 1.0
                                                        spacing 8
                                                        button:
                                                            background Solid("#00FF8833")
                                                            hover_background Solid("#00FF8866")
                                                            padding (12, 4)
                                                            action Function(_pulse.run_macro, _mc["filename"])
                                                            text "Run Macro" size 13 color "#00FF88" bold True outlines []
                                                        button:
                                                            background Solid("#FF445528")
                                                            hover_background Solid("#FF445555")
                                                            padding (10, 4)
                                                            action Function(_pulse.delete_macro, _mc["filename"])
                                                            text "Delete" size 13 color "#FF8899" outlines []

                                    text "REGISTERED GAME QUICK ACTIONS" size 13 color "#7788A5" bold True outlines []
                                    if not _pulse_registered_actions:
                                        text "No custom actions registered yet. Use `pulse_register_action(...)` to add game-specific shortcuts!" size 14 color "#667799" outlines []
                                    for _act in _pulse_registered_actions:
                                        $ _badge_txt = ""
                                        if _act.get("badge_fn"):
                                            python:
                                                try:
                                                    _badge_txt = str(_act["badge_fn"]())
                                                except Exception:
                                                    _badge_txt = ""
                                        frame:
                                            xfill True
                                            background Solid("#10192b")
                                            padding (12, 8)
                                            hbox:
                                                xfill True
                                                yalign 0.5
                                                vbox:
                                                    spacing 2
                                                    hbox:
                                                        spacing 8
                                                        text ("(" + _pulse_esc(_act["category"]) + ")") size 13 color "#00F7FF" bold True outlines []
                                                        text _pulse_esc(_act["label"]) size 15 color "#FFFFFF" bold True outlines []
                                                        if _badge_txt:
                                                            text ("— " + _pulse_esc(_badge_txt)) size 13 color "#00FF88" bold True outlines []
                                                    if _act["description"]:
                                                        text _pulse_esc(_act["description"]) size 12 color "#7788A5" outlines []
                                                button:
                                                    xalign 1.0
                                                    background Solid("#00F7FF28")
                                                    hover_background Solid("#00F7FF55")
                                                    padding (14, 5)
                                                    action Function(_pulse.run_registered_action, _act["id"])
                                                    text "Execute" size 13 color "#00F7FF" bold True outlines []

                    # Right: Interactive Python Console
                    frame:
                        xfill True
                        yfill True
                        background Solid("#090f1b")
                        padding (14, 12)
                        vbox:
                            spacing 10
                            xfill True
                            yfill True
                            text "PYTHON EXPRESSION & STATEMENT CONSOLE" size 16 color "#00F7FF" bold True outlines []
                            hbox:
                                spacing 8
                                xfill True
                                frame:
                                    xsize 680
                                    background Solid("#060a12")
                                    padding (10, 6)
                                    input:
                                        value FieldInputValue(_pulse, "console_input")
                                        size 15
                                        color "#00FF88"
                                        outlines []
                                button:
                                    background Solid("#00FF8833")
                                    hover_background Solid("#00FF8866")
                                    padding (14, 6)
                                    action Function(_pulse.execute_console_command)
                                    text "Run" size 14 color "#00FF88" bold True outlines []

                            viewport:
                                scrollbars "vertical"
                                mousewheel True
                                draggable True
                                vbox:
                                    spacing 6
                                    xfill True
                                    for _c in _pulse.console_history:
                                        frame:
                                            xfill True
                                            background Solid("#10192b")
                                            padding (10, 6)
                                            vbox:
                                                spacing 2
                                                text (">>> " + _pulse_esc(_c["expr"])) size 14 color "#B8C7E0" outlines []
                                                text _pulse_esc(_c["output"]) size 14 color ("#FF6677" if _c["is_error"] else "#00FF88") outlines []

            # ------------------------------------------------------------------
            # TAB 7: PERFORMANCE, MEMORY & CUSTOM UI LAG MONITOR
            # ------------------------------------------------------------------
            elif _pulse.active_tab == "perf":
                $ _perf = _pulse.get_resource_metrics()
                $ _prof_on = bool(_perf.get("profiler_enabled", False))
                $ _cache_pct = float(_perf.get("cache_pct", 0.0) or 0.0)
                $ _bar_col = "#FF4455" if _cache_pct >= 85.0 else ("#FFB800" if _cache_pct >= 60.0 else "#00FF88")
                $ _scr_audits = _perf.get("screen_audit", [])
                $ _img_loads = _perf.get("image_loads", [])

                vbox:
                    spacing 12
                    xfill True
                    yfill True

                    # Top Controls & Renderer Bar
                    frame:
                        xfill True
                        background Solid("#0c1322")
                        padding (14, 8)
                        hbox:
                            xfill True
                            yalign 0.5
                            spacing 10
                            button:
                                background Solid("#00FF8833" if _prof_on else "#00F7FF28")
                                hover_background Solid("#00FF8855" if _prof_on else "#00F7FF48")
                                padding (12, 6)
                                action Function(_pulse.toggle_ui_profiler)
                                text ("● Live UI Profiler: ON (" + str(_perf.get("profiler_elapsed", 0.0)) + "s)" if _prof_on else "○ Live UI Profiler: OFF (Click to Measure)") size 14 color ("#00FF88" if _prof_on else "#00F7FF") bold True outlines []
                            button:
                                background Solid("#1a2740")
                                hover_background Solid("#2a3d64")
                                padding (12, 6)
                                action Function(_pulse.reset_ui_profiler)
                                text "Reset Profiler" size 14 color "#B8C7E0" outlines []
                            button:
                                background Solid("#FFB80028")
                                hover_background Solid("#FFB80050")
                                padding (12, 6)
                                action Function(_pulse.trigger_free_memory)
                                text "Free Memory (GC)" size 14 color "#FFB800" bold True outlines []
                            button:
                                background Solid("#1a2740")
                                hover_background Solid("#2a3d64")
                                padding (12, 6)
                                action Function(_pulse.get_resource_metrics, True)
                                text "Sample Now" size 14 color "#00F7FF" outlines []
                            text ("Renderer: " + _pulse_esc(_perf.get("renderer", "unknown")) + (" (" + _pulse_esc(_perf.get("gpu_name", "")) + ")" if _perf.get("gpu_name") else "") + " | Sampled " + _pulse_esc(_perf.get("sampled_at", "-"))) size 13 color "#8899B5" xalign 1.0 yalign 0.5 outlines []

                    # 4 Summary Metric Cards
                    hbox:
                        xfill True
                        spacing 12
                        frame:
                            xsize 450
                            background Solid("#090f1b")
                            padding (14, 10)
                            vbox:
                                spacing 4
                                text "GPU TEXTURE MEMORY" size 12 color "#7788A5" bold True outlines []
                                text (str(_perf.get("tex_mb", 0.0)) + " MB") size 22 color "#00F7FF" bold True outlines []
                                text (str(_perf.get("tex_count", 0)) + " active GPU textures") size 13 color "#B8C7E0" outlines []
                        frame:
                            xsize 450
                            background Solid("#090f1b")
                            padding (14, 10)
                            vbox:
                                spacing 4
                                text ("IMAGE CACHE (" + str(_cache_pct) + "%)") size 12 color "#7788A5" bold True outlines []
                                text (str(_perf.get("cache_mb", 0.0)) + " / " + str(_perf.get("cache_limit_mb", 0.0)) + " MB") size 22 color _bar_col bold True outlines []
                                frame:
                                    xsize 410
                                    ysize 8
                                    padding (0, 0)
                                    background Solid("#060a12")
                                    frame:
                                        xsize max(2, int(410.0 * min(100.0, _cache_pct) / 100.0))
                                        ysize 8
                                        padding (0, 0)
                                        background Solid(_bar_col)
                        frame:
                            xsize 450
                            background Solid("#090f1b")
                            padding (14, 10)
                            vbox:
                                spacing 4
                                text "STORE & RENDER CACHE" size 12 color "#7788A5" bold True outlines []
                                text ("Store: " + str(_perf.get("store_count", 0)) + " | Persistent: " + str(_perf.get("persistent_count", 0))) size 16 color "#EAEFF8" bold True outlines []
                                text ("Render cache: " + str(_perf.get("render_cache_count", 0)) + " | GC: " + "/".join([str(_g) for _g in _perf.get("gc_counts", [])])) size 13 color "#8899B5" outlines []
                        frame:
                            xfill True
                            background Solid("#090f1b")
                            padding (14, 10)
                            vbox:
                                spacing 4
                                text "IMAGE LOAD STALLS" size 12 color "#7788A5" bold True outlines []
                                $ _stalls = int(_perf.get("stall_count", 0) or 0)
                                text (str(_stalls) + " Stalls") size 22 color ("#FF4455" if _stalls > 0 else "#00FF88") bold True outlines []
                                text ("In last " + str(len(_img_loads)) + " recent image loads") size 13 color "#B8C7E0" outlines []

                    # Bottom Split: Active Screen UI Lag Audit + Recent Image Load Log
                    hbox:
                        spacing 14
                        xfill True
                        yfill True

                        # Left: Active Screen UI Lag Audit
                        frame:
                            xsize 1120
                            yfill True
                            background Solid("#090f1b")
                            padding (14, 12)
                            vbox:
                                spacing 8
                                xfill True
                                yfill True
                                text "ACTIVE SCREEN UI LAG AUDIT (RANKED BY COMPLEXITY & TIMING)" size 15 color "#00F7FF" bold True outlines []
                                viewport:
                                    scrollbars "vertical"
                                    mousewheel True
                                    draggable True
                                    vbox:
                                        spacing 8
                                        xfill True
                                        if not _scr_audits:
                                            text "No non-Pulse game screens are currently active." size 14 color "#667799" outlines []
                                        for _sa in _scr_audits:
                                            frame:
                                                xfill True
                                                background Solid("#10192b")
                                                padding (12, 8)
                                                vbox:
                                                    spacing 4
                                                    xfill True
                                                    hbox:
                                                        xfill True
                                                        yalign 0.5
                                                        hbox:
                                                            spacing 8
                                                            yalign 0.5
                                                            text _pulse_esc(_sa["name"]) size 16 color "#FFFFFF" bold True outlines []
                                                            text ("(" + _pulse_esc(_sa["layer"]) + ")") size 13 color "#00F7FF" yalign 0.5 outlines []
                                                            if _sa["predict"] is False:
                                                                text "[[predict=False]]" size 12 color "#FF00D4" yalign 0.5 outlines []
                                                        button:
                                                            xalign 1.0
                                                            background Solid("#1a2740")
                                                            hover_background Solid("#2a3d64")
                                                            padding (10, 3)
                                                            action Function(_pulse.enable_engine_screen_profile, _sa["name"])
                                                            text "Log to profile_screen.txt" size 12 color "#B8C7E0" outlines []
                                                    text ("Nodes: " + str(_sa["nodes"]) + ("+" if _sa["truncated"] else "") + "  |  Transforms: " + str(_sa["transforms"]) + "  |  focus_mask: " + str(_sa["focus_masks"]) + "  |  Timers: " + str(_sa["timers"]) + "  |  Viewports: " + str(_sa["viewports"])) size 13 color "#B8C7E0" outlines []
                                                    if _prof_on or _sa["updates"] > 0 or _sa["renders"] > 0:
                                                        text ("Update: " + str(_sa["avg_upd_ms"]) + "ms avg / " + str(_sa["peak_upd_ms"]) + "ms peak (" + str(_sa["upd_per_sec"]) + "/s, " + str(_sa["updates"]) + "x)  |  Render: " + str(_sa["avg_ren_ms"]) + "ms avg / " + str(_sa["peak_ren_ms"]) + "ms peak (" + str(_sa["renders"]) + "x)") size 13 color "#00F7FF" outlines []
                                                    if _sa["hints"]:
                                                        text ("Lag Hints: " + _pulse_esc(" • ".join(_sa["hints"]))) size 13 color "#FFB800" bold True outlines []
                                                    else:
                                                        text "No UI lag red flags detected" size 12 color "#00FF88" outlines []

                        # Right: Recent Image Load Log (Stall Detector)
                        frame:
                            xfill True
                            yfill True
                            background Solid("#090f1b")
                            padding (14, 12)
                            vbox:
                                spacing 8
                                xfill True
                                yfill True
                                text "RECENT IMAGE LOAD LOG (STALL DETECTOR)" size 15 color "#00F7FF" bold True outlines []
                                viewport:
                                    scrollbars "vertical"
                                    mousewheel True
                                    draggable True
                                    vbox:
                                        spacing 6
                                        xfill True
                                        if not _img_loads:
                                            text "No recent image loads logged yet." size 14 color "#667799" outlines []
                                        for _il in _img_loads:
                                            frame:
                                                xfill True
                                                background Solid("#10192b")
                                                padding (10, 6)
                                                hbox:
                                                    xfill True
                                                    yalign 0.5
                                                    vbox:
                                                        xsize 480
                                                        text _pulse_esc(_il["short"]) size 14 color "#FFFFFF" bold True outlines []
                                                        text (_pulse_esc(_il["time"]) + " | " + _pulse_esc(_il["file"])) size 11 color "#7788A5" outlines []
                                                    text ("PRELOAD" if _il["preloaded"] else "STALL") size 12 color ("#00FF88" if _il["preloaded"] else "#FF4455") bold True xalign 1.0 outlines []

    # ------------------------------------------------------------------
    # MODAL POPUP FOR DIRECT VALUE EDITING
    # ------------------------------------------------------------------
    if _pulse.editing_var is not None:
        frame:
            xsize 1920
            ysize 1080
            background Solid("#000000aa")
            frame:
                xalign 0.5
                yalign 0.45
                xsize 680
                background Solid("#0e172a")
                padding (24, 20)
                vbox:
                    spacing 14
                    text ("Edit Variable: " + _pulse_esc(_pulse.editing_var)) size 18 color "#00F7FF" bold True outlines []
                    text "Enter a valid literal or Python expression (e.g. 25, True, 'Tatsuya', or [[1, 2, 3]):" size 13 color "#8899B5" outlines []
                    frame:
                        xfill True
                        background Solid("#060a12")
                        padding (12, 8)
                        input:
                            value FieldInputValue(_pulse, "editing_buffer")
                            size 16
                            color "#00FF88"
                            outlines []
                    if _pulse.editing_error:
                        text ("Error: " + _pulse_esc(_pulse.editing_error)) size 13 color "#FF4455" outlines []
                    hbox:
                        spacing 12
                        xalign 1.0
                        button:
                            background Solid("#00FF8833")
                            hover_background Solid("#00FF8866")
                            padding (16, 6)
                            action Function(_pulse.apply_inline_edit)
                            text "Apply Change" size 14 color "#00FF88" bold True outlines []
                        button:
                            background Solid("#FF445533")
                            hover_background Solid("#FF445566")
                            padding (16, 6)
                            action SetField(_pulse, "editing_var", None)
                            text "Cancel (Esc)" size 14 color "#FF8899" outlines []
