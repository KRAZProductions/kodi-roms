# USB SQUID tools

These are the two USB update add-ons from the SQUID (Kodi for Atari VCS) bundle, along with the patch builder.

- `addons/script.vcs.usbport`: the USB Update Port service and status screen.
- `addons/script.vcs.gamepatch`: the Game Updater. It applies `.kodipatch` packages to SQUID itself, after checking the StoreID, the version and the SHA-256 of every file.
- `patch-builder/`: `make-patch.py` (runs on a PC) builds `.kodipatch` packages. `patch-builder/README.md` documents the full format.

Source: KodiVCS16-work (SQUID v21).
