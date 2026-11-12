################################################################################
## REN'PY PULSE — Custom Hook Starter Template (`_pulse_hook.rpy`)
## Compatible with Ren'Py 7.5+ & 8.5+ | Safe to drop straight into `game/`!
##
## WHAT IS THIS FILE?
##   This optional file lets you add custom 1-click "Cheat / Debug" buttons to
##   Ren'Py Pulse and hide noisy internal UI variables—without ever editing
##   `renpy_pulse.rpy` itself!
##
## QUICK START (3 EASY STEPS FOR BEGINNERS):
##   1. Drop this file anywhere inside your project's `game/` folder alongside
##      `renpy_pulse.rpy` (for example: `game/_pulse_hook.rpy` or rename it to
##      `game/my_game_pulse_hook.rpy`).
##   2. Launch your game from the Ren'Py Launcher, press `F12` (or `Shift+W`
##      for the Second Window), and open Tab 6: "Actions" ("Actions & Console").
##      Click "Verify Custom Hook" to see it work right away!
##   3. Scroll down to the RECIPES below, uncomment any block (`Ctrl + /` in
##      VS Code), and swap the example variable/label names with your own!
##
## RELEASE SAFETY:
##   - Any file with `pulse_hook` in its filename is AUTOMATICALLY stripped out
##     when you build a release ZIP for players (`build.classify`).
##   - Even if you delete `renpy_pulse.rpy` later, leaving this file in `game/`
##     will NOT crash your game.
################################################################################

init -999 python:
    # Automatically exclude any *pulse_hook* file from player release builds
    if hasattr(build, "classify"):
        build.classify("**/*pulse_hook**", None)


init 998 python:

    # ==========================================================================
    # SECTION 1: HIDE NOISY HELPER FILES OR TEMP VARIABLES (OPTIONAL)
    # ==========================================================================
    # Does your project have custom UI screens or minigame timers that clutter
    # up the Variable Inspector or Live Diff Log? Uncomment the lines below to
    # hide specific `.rpy` files, exact variable names, or variable prefixes.

    if hasattr(store, "pulse_configure"):
        pulse_configure(
            # ignore_files=["screens.rpy", "custom_ui.rpy"],
            # ignore_names=["temp_timer", "hover_cooldown"],
            # ignore_prefixes=["ui_temp_", "anim_"],
        )


    # ==========================================================================
    # SECTION 2: CUSTOM 1-CLICK QUICK ACTIONS (TAB 6: ACTIONS & CONSOLE)
    # ==========================================================================
    # Everything inside this `if` block ONLY runs in developer mode and ONLY
    # when `renpy_pulse.rpy` is installed.

    if (
        hasattr(store, "_pulse_is_enabled")
        and _pulse_is_enabled()
        and hasattr(store, "pulse_register_action")
    ):

        ## ---------------------------------------------------------------------
        ## STARTER DEMO (Active out of the box so you can test Tab 6 right away!)
        ## Feel free to delete or comment out this starter button once you add
        ## your own custom buttons below.
        ## ---------------------------------------------------------------------
        def _pulse_hook_verify():
            renpy.notify("Success! Your _pulse_hook.rpy file is connected.")

        pulse_register_action(
            label="Verify Custom Hook",
            category="Starter",
            callback=_pulse_hook_verify,
            description="Click to test your _pulse_hook.rpy setup! Safe to remove once you add your own cheats below.",
            badge_fn=lambda: "READY",
        )


        ## ---------------------------------------------------------------------
        ## RECIPE 1: BOOST OR MAX OUT ROUTE / STAT VARIABLES
        ## Great for testing affection routes, karma, RPG stats, or money without
        ## replaying scenes from Chapter 1.
        ## Tip: Select the `#` code lines below and press `Ctrl + /` to uncomment!
        ## ---------------------------------------------------------------------
        # def _my_boost_affection():
        #     # Replace `alice_points` and `player_gold` with your `default` variables!
        #     store.alice_points = getattr(store, "alice_points", 0) + 10
        #     store.player_gold = getattr(store, "player_gold", 0) + 500
        #
        # pulse_register_action(
        #     label="+10 Alice Affection & +500 Gold",
        #     category="Cheats",
        #     callback=_my_boost_affection,
        #     description="Adds +10 to alice_points and +500 to player_gold.",
        #     badge_fn=lambda: "Pts: " + str(getattr(store, "alice_points", 0)),
        # )


        ## ---------------------------------------------------------------------
        ## RECIPE 2: 1-CLICK ROUTE LOADOUT (SET MULTIPLE FLAGS AT ONCE)
        ## Set exact stats and story flags needed to unlock a late-game branch.
        ## ---------------------------------------------------------------------
        # def _my_true_ending_setup():
        #     store.alice_points = 100
        #     store.found_secret_letter = True
        #     store.bad_end_flag = False
        #
        # pulse_register_action(
        #     label="Setup True Ending Flags",
        #     category="Routes",
        #     callback=_my_true_ending_setup,
        #     description="Sets alice_points=100, found_secret_letter=True, and clears bad_end_flag.",
        #     badge_fn=lambda: "READY" if getattr(store, "found_secret_letter", False) else "LOCKED",
        # )


        ## ---------------------------------------------------------------------
        ## RECIPE 3: TOGGLE A PERSISTENT SETTING ON / OFF
        ## Great for testing Story Mode skips, adult content toggles, or extra UI
        ## modes stored in `persistent.*`.
        ## ---------------------------------------------------------------------
        # def _my_toggle_skip_minigames():
        #     persistent.skip_minigames = not bool(getattr(persistent, "skip_minigames", False))
        #     renpy.save_persistent()
        #
        # pulse_register_action(
        #     label="Toggle Skip Mini-Games",
        #     category="Modes",
        #     callback=_my_toggle_skip_minigames,
        #     description="Flips persistent.skip_minigames between True and False.",
        #     badge_fn=lambda: "ON" if getattr(persistent, "skip_minigames", False) else "OFF",
        # )


        ## ---------------------------------------------------------------------
        ## RECIPE 4: UNLOCK ALL CG GALLERY / EXTRA ITEMS
        ## Test your Gallery or Music Room screen without playing every route.
        ## ---------------------------------------------------------------------
        # def _my_unlock_all_gallery():
        #     # List your `default persistent.*` gallery flag names here:
        #     for flag_name in ("cg_beach_unlocked", "cg_festival_unlocked", "cg_ending_unlocked"):
        #         setattr(persistent, flag_name, True)
        #     renpy.save_persistent()
        #
        # pulse_register_action(
        #     label="Unlock All CG Gallery Flags",
        #     category="Unlocks",
        #     callback=_my_unlock_all_gallery,
        #     description="Marks all listed persistent CG gallery flags as True.",
        # )


        ## ---------------------------------------------------------------------
        ## RECIPE 5: OPEN A CUSTOM SCREEN OR JUMP TO A TEST SCENE
        ## Quickly pop open a custom menu (like a Phone UI, Map, or Gallery) or
        ## set variables and jump straight into a specific `label`.
        ## ---------------------------------------------------------------------
        # def _my_open_gallery_screen():
        #     if renpy.get_screen("pulse_devtools_overlay"):
        #         renpy.hide_screen("pulse_devtools_overlay")
        #     renpy.run(ShowMenu("gallery"))
        #
        # pulse_register_action(
        #     label="Open Gallery Screen",
        #     category="Navigation",
        #     callback=_my_open_gallery_screen,
        #     description="Closes the overlay and opens Ren'Py's gallery menu.",
        # )
        #
        # def _my_jump_to_chapter_2():
        #     store.alice_points = 50
        #     _pulse.jump_to_label("chapter_2_start")  # Replace with any label in your game!
        #
        # pulse_register_action(
        #     label="Jump to Chapter 2 (50 Pts)",
        #     category="Navigation",
        #     callback=_my_jump_to_chapter_2,
        #     description="Sets alice_points=50 and jumps straight to label `chapter_2_start`.",
        # )
