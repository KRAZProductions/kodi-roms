# USB Update Port: the access report shown when the user opens it from
# Programs. It tells the truth about what USB storage the Kodi sandbox can
# reach, which drive is the protected bundle drive, and where the open update
# port is.
import os
import sys

import xbmc
import xbmcaddon
import xbmcgui

sys.path.insert(0, xbmcaddon.Addon().getAddonInfo("path"))
import port  # noqa: E402

NAME = "USB Update Port"


def main():
    drives = port.reachable_drives()
    status = port.port_status()

    lines = []
    lines.append("[B]USB access from inside Kodi[/B]")
    lines.append("The Atari VCS sandbox hides USB storage, so Kodi cannot mount")
    lines.append("or see a separate USB stick on its own. Below is what it can")
    lines.append("actually reach right now.")
    lines.append("")

    lines.append("[B]Reachable storage[/B]")
    if drives:
        for d in drives:
            tag = ""
            if d["bundle_drive"]:
                tag = "  [COLOR orange](VCS Bundle drive - read-only, protected)[/COLOR]"
            elif d["writable"]:
                tag = "  [COLOR lightgreen](writable)[/COLOR]"
            else:
                tag = "  [COLOR grey](read-only)[/COLOR]"
            lines.append("%s%s" % (d["mount"], tag))
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append("[B]Update port[/B]")
    if status.get("is_open"):
        where = status.get("port") or "(none)"
        if status.get("writable"):
            lines.append("[COLOR lightgreen]OPEN[/COLOR] - %s" % where)
            lines.append("Drop update or patch packages here; the Game Updater")
            lines.append("reads them while Kodi is running.")
        else:
            lines.append("[COLOR orange]OPEN (read-only)[/COLOR] - %s" % where)
            lines.append("Reason: %s" % status.get("reason", ""))
    else:
        lines.append("[COLOR grey]CLOSED[/COLOR] - %s" % status.get("reason", ""))
    lines.append("")
    lines.append("The port is held open only while Kodi is running and closes")
    lines.append("when Kodi exits.")

    xbmcgui.Dialog().textviewer(NAME, "\n".join(lines))


main()
