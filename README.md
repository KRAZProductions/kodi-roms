# kodi-roms

ROMs for the SQUID-MBC Kodi bundle on the Atari VCS, copied 2026-11-14 from
`/media/user/VCS_Bundles/bundles/UJZi5fBzNn0MEFWQ` on the dev unit.

| Folder | Files | System |
|---|---|---|
| Jaguar-Games | 2 | Atari Jaguar |
| Lynx-Games | 172 | Atari Lynx |
| NGP-Games | 72 | Neo Geo Pocket / Color |
| Supervision-Games | 88 | Watara Supervision |

## Install in Kodi (repo must be public while you do this)

1. Settings > File manager > Add source: `https://krazproductions.github.io/kodi-roms/`, name it `KRAZ`.
   (No GitHub Pages? Copy `repository.kraz.roms-1.0.0.zip` to a USB stick instead.)
2. Add-ons > Install from zip file > KRAZ > `repository.kraz.roms-1.0.0.zip`.
   Kodi asks to allow unknown sources the first time: say yes.
3. Add-ons > Install from repository > KRAZ ROMs Repository > Program add-ons > pick a pack > Install.
4. The pack copies its games into SQUID's games folder. If it says "restart Kodi", restart SQUID.

Opening a pack from Program add-ons runs the restore again.

## Updating

Change the `*-Games` folders, raise `PACK_VER` in `tools/build_repo.py`,
run `python3 tools/build_repo.py`, commit and push. Kodi picks up the new version.
