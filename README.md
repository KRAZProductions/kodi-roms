# kodi-roms

ROMs for the SQUID-MBC Kodi bundle on the Atari VCS, copied 2026-11-14 from
`/media/user/VCS_Bundles/bundles/UJZi5fBzNn0MEFWQ` on the dev unit.

| Folder | Games | System | Pack version |
|---|---|---|---|
| Jaguar-Games | 22 | Atari Jaguar | 1.1.0 |
| Lynx-Games | 86 | Atari Lynx | 1.0.1 |
| NGP-Games | 36 | Neo Geo Pocket / Color | 1.0.0 |
| Supervision-Games | 44 | Watara Supervision | 1.0.0 |

Every game has box art as `<game name>.png` next to the ROM.
2026-11-14: 21 Jaguar games added (art from thumbnails.libretro.com Named_Boxarts;
Ultimate Brain Games uses a Named_Snaps screenshot, no box art exists). All 22
Jaguar games ran for 25+ seconds in SQUID v20 on the PC (Virtual Jaguar core).

## Install in Kodi (repo must be public while you do this)

1. Settings > File manager > Add source: `https://krazproductions.github.io/kodi-roms/`, name it `KRAZ`.
   (No GitHub Pages? Copy `repository.kraz.roms-1.0.0.zip` to a USB stick instead.)
2. Add-ons > Install from zip file > KRAZ > `repository.kraz.roms-1.0.0.zip`.
   Kodi asks to allow unknown sources the first time: say yes.
3. Add-ons > Install from repository > KRAZ ROMs Repository > Program add-ons > pick a pack > Install.
4. The pack copies its games into SQUID's games folder. If it says "restart Kodi", restart SQUID.

Opening a pack from Program add-ons runs the restore again.

## Updating

Change the `*-Games` folders, raise that pack's version in `PACK_VERS` in `tools/build_repo.py`,
run `python3 tools/build_repo.py`, commit and push. Kodi picks up the new version.
