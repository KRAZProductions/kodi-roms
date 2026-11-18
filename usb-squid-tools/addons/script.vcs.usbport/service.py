# USB Update Port service: holds the update port open only while Kodi runs.
#
# On start it opens the port (picking the next usable writable location and
# protecting the bundle drive) and then rewrites the heartbeat about once a
# minute. When Kodi exits, waitForAbort returns and the port is closed. That is
# what "force USB reading only while Kodi is open" means in the sandbox: the
# window in which any update is read begins when Kodi starts and ends the
# moment it stops.
import os
import sys

import xbmc
import xbmcaddon

sys.path.insert(0, xbmcaddon.Addon().getAddonInfo("path"))
import port  # noqa: E402

HEARTBEAT_S = 60


def main():
    if not port.STATE:
        port.log("no writable state folder; port not opened", xbmc.LOGWARNING)
        return
    path, writable = port.open_port()
    port.log("port opened: %r (writable=%s)" % (path, writable))
    monitor = xbmc.Monitor()
    try:
        while not monitor.waitForAbort(HEARTBEAT_S):
            port.open_port()  # refresh the heartbeat
    finally:
        port.close_port()
        port.log("port closed (Kodi exiting)")


main()
