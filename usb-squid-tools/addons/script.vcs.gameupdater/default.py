# VCS Game Updater - Kodi front end. Logic lives in resources/lib/updater.py.
import json
import os
import shutil
import sys
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
ROOT = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
sys.path.insert(0, os.path.join(ROOT, "resources", "lib"))
import updater  # noqa: E402
from updater import UpdateError  # noqa: E402

TITLE = "VCS Game Updater"
DLG = xbmcgui.Dialog()


def log(msg):
    xbmc.log("[script.vcs.gameupdater] %s" % msg, xbmc.LOGINFO)


def staging_dir():
    # Must be a real path the console installer can read, so use the app home
    # (the per-app home is the same path inside and outside the sandbox).
    base = os.environ.get("KODIVCS_STATE") or os.path.join(os.path.expanduser("~"), ".vcs-game-updater")
    d = os.path.join(base, "game-updates")
    os.makedirs(d, exist_ok=True)
    return d


def history(entry):
    p = os.path.join(staging_dir(), "history.json")
    try:
        with open(p, encoding="utf-8") as f:
            h = json.load(f)
    except (OSError, ValueError):
        h = []
    entry["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    h.append(entry)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(h[-200:], f, indent=1)


def mb(n):
    return "%.0f MB" % (n / 1048576.0) if n else "unknown size"


def ask_link():
    last = ADDON.getSetting("last_link")
    link = DLG.input("Type your update GitHub link (e.g. github.com/YourName/YourGame)",
                     defaultt=last or "https://github.com/", type=xbmcgui.INPUT_ALPHANUM)
    return link.strip()


def pick(cands):
    if len(cands) == 1:
        return cands[0]
    labels = ["%s  (%s%s)" % (c["name"], mb(c["size"]),
                              ", release " + c["release"] if c["release"] else "") for c in cands]
    i = DLG.select("Which file is the game build?", labels)
    return cands[i] if i >= 0 else None


def do_download(cand):
    dest_dir = staging_dir()
    free = shutil.disk_usage(dest_dir).free
    if cand["size"] and cand["size"] * 1.05 > free:
        raise UpdateError("Not enough free space: the build needs %s, %s free." %
                          (mb(cand["size"]), mb(free)))
    dest = os.path.join(dest_dir, "update.zip")
    if os.path.exists(dest):
        os.remove(dest)
    prog = xbmcgui.DialogProgress()
    prog.create(TITLE, "Downloading %s ..." % cand["name"])
    t0 = [time.time()]

    def cb(done, total):
        if prog.iscanceled():
            return False
        if time.time() - t0[0] > 0.5:
            t0[0] = time.time()
            pct = int(done * 100 / total) if total else 0
            prog.update(pct, "Downloading %s\n%s of %s" % (cand["name"], mb(done), mb(total)))
        return True

    try:
        updater.download(cand["url"], dest, cb)
    finally:
        prog.close()
    return dest


def run():
    registry = updater.load_registry(os.path.join(ROOT, "resources", "registry.json"))

    link = ask_link()
    if not link:
        return
    busy = xbmcgui.DialogProgress()
    busy.create(TITLE, "Looking up %s ..." % link)
    try:
        cands = updater.resolve_link(link)
    finally:
        busy.close()
    cand = pick(cands)
    if not cand:
        return
    ADDON.setSetting("last_link", link)

    path = do_download(cand)
    try:
        busy = xbmcgui.DialogProgress()
        busy.create(TITLE, "Checking the build ...")
        try:
            info = updater.read_bundle(path)
        finally:
            busy.close()
        sid, name, newv = info["StoreID"], info["Name"], info.get("Version", "?")

        # Security key: the StoreID in the downloaded bundle.ini must be a known VCS store game.
        if sid not in registry:
            history({"link": link, "storeid": sid, "result": "refused: not in registry"})
            os.remove(path)
            raise UpdateError("Refused: StoreID %s is not in the VCS game registry.\n"
                              "Updates are only allowed for registered store games." % sid)

        sock = updater.installer_socket()
        if not sock:
            history({"link": link, "storeid": sid, "result": "blocked: no installer access"})
            raise UpdateError(
                "The build for %s (StoreID %s, version %s) downloaded and checked OK,\n"
                "but this console doesn't let apps reach its game installer, so the\n"
                "old game can't be swapped from here. The build is kept at:\n%s"
                % (name, sid, newv, path))

        # The GitHub bundle.ini StoreID must match a game installed on THIS VCS.
        # No match = stop before anything is touched; the original game stays as it is.
        inst = updater.find_installed(sock, sid)
        if not inst:
            history({"link": link, "storeid": sid, "result": "stopped: StoreID does not match an installed game"})
            os.remove(path)
            raise UpdateError("Update stopped: the StoreID in the GitHub build (%s) doesn't match "
                              "any game on this VCS.\nNothing was changed - your games are untouched."
                              % sid)
        oldv = inst.get("version") or "?"
        newv = updater.next_version(oldv)   # updated = installed Version + 1
        where = "VCS Bundles drive" if inst.get("slot", "internal") != "internal" else "internal storage"
        if not DLG.yesno(TITLE, "Replace %s (version %s) with the GitHub build as version %s?\n"
                         "StoreID %s matches the installed game. Saves are kept.\nFrom: %s (%s)"
                         % (inst.get("name", name), oldv, newv, sid, cand["name"], where)):
            return
        updater.set_version(path, newv)
        if updater.read_bundle(path).get("Version") != newv:
            raise UpdateError("Could not set the new Version in bundle.ini.")

        busy = xbmcgui.DialogProgress()
        busy.create(TITLE, "Installing %s version %s ...\nDon't turn off the console." % (name, newv))
        try:
            updater.install(sock, path, inst)
        finally:
            busy.close()
        after = updater.find_installed(sock, sid) or {}
        ok = after.get("version") == newv
        history({"link": link, "storeid": sid, "from": oldv, "to": after.get("version"),
                 "result": "installed" if ok else "installer reported success but version is %r" % after.get("version")})
        if not ok:
            raise UpdateError("The console installer finished, but %s still reports version %s "
                              "(expected %s)." % (name, after.get("version", "?"), newv))
        DLG.ok(TITLE, "%s is now version %s." % (name, newv))
        os.remove(path)
    except UpdateError:
        raise


if __name__ == "__main__":
    try:
        run()
    except UpdateError as e:
        log("stopped: %s" % e)
        DLG.ok(TITLE, str(e))
    except Exception as e:  # never leave the user with a silent failure
        log("crash: %r" % e)
        DLG.ok(TITLE, "Something went wrong: %s" % e)
