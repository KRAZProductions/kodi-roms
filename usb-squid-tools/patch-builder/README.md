# USB Update Port + Game Updater (Kodi for Atari VCS)

Two Kodi add-ons that live in the bundle at
`runtime/usr/share/kodi/addons/` and are registered in
`runtime/usr/share/kodi/system/addon-manifest.xml`.

## Why they work the way they do

The Atari VCS runs every app in a `bwrap` sandbox. Confirmed read-only on the
dev unit (2026-10-30): the sandbox bind-mounts **only** the bundle's own folder
(read-only) plus the writable home on eMMC, `/tmp` and the system dirs. The
host `/media` tree, where USB sticks are mounted, is **not** bind-mounted in,
and `/dev/sd*` is not exposed. So an add-on inside Kodi genuinely cannot mount
or even see a second USB stick on its own, and cannot force one to mount — that
needs something running outside the sandbox (a host udev rule / helper on the
VCS OS, which is a separate, privileged change).

These add-ons therefore do everything that *is* possible from inside the
sandbox, honestly, and are built so a host-side mount helper can be added later
without changing them.

## 1. USB Update Port — `script.vcs.usbport`

A service plus a status screen (Programs → USB Update Port).

- **Checks USB access.** Reports exactly what storage the sandbox can reach
  right now, and whether each drive is writable.
- **Protects the VCS Bundle drive.** The bundle drive is read-only and is never
  written to. Every candidate and every patch target is checked with
  `realpath`; anything that resolves inside the bundle (including the linked
  `3DO Games` / `Neo Geo Pocket Games` / `Supervision Games` folders, which are
  symlinks back into the read-only bundle) is refused.
- **Chooses the next open port.** It walks a priority list and picks the first
  location it can actually use: an already-present, writable `KodiUpdate`
  folder on a USB drive (only reachable if a host mount helper is added — it is
  never *created* on your stick), otherwise the writable staging folder in the
  home (`<state>/update-port/incoming`). The chosen port is written to
  `<state>/update-port/active-port.txt`.
- **Only while Kodi is open.** The service opens the port on start, refreshes a
  heartbeat about once a minute, and closes it when Kodi exits. A port whose
  heartbeat is stale (left by a crash) is treated as closed. This is what
  "force USB reading only while Kodi is open" means inside the sandbox: updates
  are only ever read in that window.

## 2. Game Updater — `script.vcs.gamepatch`

Programs → Game Updater. Reads patch packages from the open port, shows what is
waiting, and applies the one you choose.

A patch is applied **only** when all of these hold, checked before a single
byte is written (so a patch applies completely or not at all):

- the patch names **this bundle's StoreID**, and
- a bundle **Version at or below** the one installed, and
- **every file's SHA-256 matches** the package, and (for a replace that
  declares `expect_sha256`) the file already on the system matches what the
  patch was built against.

Patches are written to the writable Kodi home only — emulator cores and other
add-on files (`base: addons`), userdata and skins (`base: home`), or a
`patched-games` overlay for updated/new ROMs (`base: games`). Replaced files
are backed up to `<state>/update-port/backups/<id>-<timestamp>/` first. Each
patch id is recorded in `<state>/update-port/applied.json` so it is not applied
twice by accident. Restart Kodi for an update to take effect.

## Patch package format

A folder or a tar named `<something>.kodipatch`, containing:

```
patch.json
files/<path>...        # the files the patch adds or replaces, mirroring the
                       # manifest paths (relative to the base, no leading dir)
```

`patch.json`:

```json
{
  "id": "ngp-fix-2026-11",
  "name": "Neo Geo Pocket fix",
  "target": { "storeid": "UJZi5fBzNn0MEFWQ", "min_version": 11 },
  "base": "addons",
  "files": [
    { "path": "game.libretro.beetle-ngp/.../core.so", "action": "replace",
      "sha256": "<new file>", "expect_sha256": "<current file, optional>" },
    { "path": "game.libretro.beetle-ngp/notes.txt", "action": "add",
      "sha256": "<new file>" }
  ]
}
```

Paths may not be absolute or contain `..`.

## Building a patch

Use `make-patch.py` (runs on the PC, Python 3):

```
python3 make-patch.py out/ngp-fix.kodipatch \
    --id ngp-fix-2026-11 --name "Neo Geo Pocket fix" \
    --storeid UJZi5fBzNn0MEFWQ --min-version 11 \
    --base addons \
    --replace game.libretro.beetle-ngp/.../core.so  /path/to/new/core.so \
    --expect-from game.libretro.beetle-ngp/.../core.so  /path/to/current/core.so \
    --add game.libretro.beetle-ngp/notes.txt  /path/to/notes.txt \
    --tar
```

It copies the files in, computes every SHA-256, writes `patch.json`, and (with
`--tar`) also writes a single-file `.tar` to rename to `<name>.kodipatch` and
drop on the port.

## Delivering a patch to the console

Inside the plain sandbox the reachable port is the home staging folder, which
is not visible from outside Kodi, so the practical delivery routes are:

- bundle the `.kodipatch` inside a new bundle build so it ships with Kodi, or
- add a host-side mount helper on the VCS OS (outside the sandbox) that mounts a
  tagged USB stick's `KodiUpdate` folder into a path the sandbox sees while
  Kodi runs — then the port picks it up automatically. This needs the console's
  own OS and privileges and is deliberately **not** part of these add-ons.
