# USB SQUID tools

These are the two USB update add-ons from the SQUID (Kodi for Atari VCS) bundle, along with the patch builder.

- `addons/script.vcs.usbport`: the USB Update Port service and status screen.
- `addons/script.vcs.gamepatch`: the Game Updater. It applies `.kodipatch` packages to SQUID itself, after checking the StoreID, the version and the SHA-256 of every file.
- `patch-builder/`: `make-patch.py` (runs on a PC) builds `.kodipatch` packages. `patch-builder/README.md` documents the full format.

Source: KodiVCS16-work (SQUID v21).

## VCS Game Updater (`addons/script.vcs.gameupdater`)

Added in SQUID v22. When you open it, it asks for an update GitHub link; each developer uses their own repo. It downloads the build and checks that the StoreID in its bundle.ini matches a game installed on the console (and is in `resources/registry.json`). If the StoreID doesn't match, it stops and leaves the original game untouched. If it does, it sets Version to the installed version + 1 and swaps in the new build through the console's installer (`system-bridge-daemon`, `bundles/install`).
