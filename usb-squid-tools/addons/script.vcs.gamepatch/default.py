# Kodi Updater USB Tool: the screen the user opens from Programs. It lists the patches
# waiting on the open USB update port, shows what each one does, and applies
# the chosen one after checking the bundle information and every checksum.
import os
import sys

import xbmc
import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()
sys.path.insert(0, ADDON.getAddonInfo("path"))
# The USB Update Port add-on owns the port logic and the bundle-drive guard.
sys.path.insert(0, xbmcaddon.Addon("script.vcs.usbport").getAddonInfo("path"))

import patcher  # noqa: E402
import port  # noqa: E402

NAME = "Kodi Updater USB Tool"


def info(text):
    xbmcgui.Dialog().ok(NAME, text)


def notify(text, icon=xbmcgui.NOTIFICATION_INFO):
    xbmcgui.Dialog().notification(NAME, text, icon, 4000)


def describe(man, applied):
    target = man.get("target", {})
    lines = [
        "[B]%s[/B]" % man.get("name", man.get("id", "patch")),
        "",
        "For StoreID: %s" % target.get("storeid", "?"),
        "Needs bundle version: %s or newer" % target.get("min_version", 0),
        "Writes to: %s" % man.get("base", "?"),
        "Files: %d" % len(man.get("files", [])),
    ]
    if applied:
        lines.append("")
        lines.append("[COLOR orange]Already applied once on this system.[/COLOR]")
    return "\n".join(lines)


def main():
    status = port.port_status()
    if not status.get("is_open"):
        info("The USB update port is closed, so there is nothing to read.\n\n"
             "The port is only open while Kodi is running. Open the USB Update "
             "Port add-on from Programs to see its status.")
        return

    port_path = status.get("port", "")
    packages = patcher.find_packages(port_path)
    if not packages:
        info("No patches are waiting on the update port.\n\nPort: %s\n\n"
             "Copy a .kodipatch package here to update your games." % (port_path or "(none)"))
        return

    storeid, version = patcher.bundle_info()

    # Read each package's manifest for the chooser.
    entries = []
    for pkg_path in packages:
        pkg = None
        try:
            pkg = patcher.Package(pkg_path)
            man = pkg.manifest()
            label = man.get("name", os.path.basename(pkg_path))
            pid = man.get("id", os.path.basename(pkg_path))
            applied = patcher.already_applied(pid)
            if applied:
                label = "%s  (applied)" % label
            entries.append((pkg_path, man, applied, label))
        except patcher.PatchError as e:
            entries.append((pkg_path, None, False, "%s  [broken: %s]"
                            % (os.path.basename(pkg_path), e)))
        finally:
            if pkg:
                pkg.close()

    idx = xbmcgui.Dialog().select("%s - %d waiting" % (NAME, len(entries)),
                                  [e[3] for e in entries])
    if idx < 0:
        return
    pkg_path, man, applied, _ = entries[idx]
    if man is None:
        info("That package is broken and cannot be read.")
        return

    if not xbmcgui.Dialog().yesno(NAME, describe(man, applied),
                                  nolabel="Cancel", yeslabel="Apply"):
        return
    if applied and not xbmcgui.Dialog().yesno(
            NAME, "This patch was already applied once. Apply it again?",
            nolabel="No", yeslabel="Yes"):
        return

    # Verify everything (bundle match + all checksums) before writing a byte.
    pkg = None
    try:
        pkg = patcher.Package(pkg_path)
        manifest, plan = patcher.verify(pkg, storeid, version)
    except patcher.PatchError as e:
        info("Patch refused:\n\n%s" % e)
        if pkg:
            pkg.close()
        return

    try:
        changed, backup = patcher.apply(manifest, plan)
    except (patcher.PatchError, OSError) as e:
        info("Patch failed while writing:\n\n%s" % e)
        return
    finally:
        pkg.close()

    port.log("applied patch %r: %d file(s)" % (manifest.get("name"), len(changed)))
    msg = "Applied %d file(s)." % len(changed)
    if backup:
        msg += "\n\nReplaced files were backed up to:\n%s" % backup
    msg += "\n\nRestart Kodi for the update to take effect."
    info(msg)


main()
