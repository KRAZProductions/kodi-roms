# USB Update Port: the shared logic both this add-on and the Kodi Updater USB Tool use.
#
# Background (confirmed on the dev unit, 2026-10-30): the Atari VCS runs every
# bundle under bwrap. The sandbox bind-mounts ONLY the bundle's own folder
# (read-only) plus the writable home on eMMC, /tmp and the system dirs. The
# host's /media tree, where USB sticks are mounted, is NOT bind-mounted in, and
# /dev/sd* is not exposed. So Kodi genuinely cannot mount or even see a second
# USB stick from inside the sandbox. This module is honest about that: it
# reports what is reachable, never pretends to mount a device, and picks the
# best writable spot it can actually reach as the "update port".
#
# Two safety rules run through everything here:
#   1. The VCS Bundle drive is READ-ONLY and must never be written to. Every
#      candidate path is checked against the bundle's own storage device and
#      refused if it lands there.
#   2. The port is only "open" while Kodi is running. The service opens it on
#      start and closes it on exit, so updates are only ever read in that
#      window. A heartbeat guards against a stale port left by a crash.
import json
import os
import time

import xbmc
import xbmcvfs

# Where the bundle launcher gave us a writable state folder and the read-only
# bundle. These come from kodi-vcs.sh / run-kodi.sh.
STATE = os.environ.get("KODIVCS_STATE", "")
BUNDLE = os.environ.get("KODIVCS_BUNDLE", "")

# The port's bookkeeping lives in writable state, next to the launcher's own.
PORT_DIR = os.path.join(STATE, "update-port") if STATE else ""
OPEN_MARKER = os.path.join(PORT_DIR, "open.json")
ACTIVE_FILE = os.path.join(PORT_DIR, "active-port.txt")

# A port is "open" only while this heartbeat is fresh. The service rewrites it
# roughly once a minute; anything older than this means Kodi is not running.
HEARTBEAT_STALE_S = 180


def log(msg, level=xbmc.LOGINFO):
    xbmc.log("usbport: %s" % msg, level)


def _device_of(path):
    """st_dev of path, walking up to the nearest parent that exists."""
    p = os.path.realpath(path)
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    try:
        return os.stat(p).st_dev
    except OSError:
        return None


def _bundle_device():
    return _device_of(BUNDLE) if BUNDLE else None


def is_under_bundle(path):
    """True if path resolves inside the bundle folder. realpath() is used, so
    this also catches a symlink in the Kodi home that points back into the
    read-only bundle (the linked 3DO/NGP/Supervision game folders do exactly
    that). This is the guard that protects the bundle: a write target for which
    this is True is refused."""
    if not path or not BUNDLE:
        return False
    rp = os.path.realpath(path)
    b = os.path.realpath(BUNDLE)
    return rp == b or rp.startswith(b + os.sep)


def is_on_bundle_drive(path):
    """True if path sits on the read-only VCS Bundle drive (same storage
    device as the bundle), or inside the bundle folder. Used to tag the bundle
    drive in the access report. The device test is only meaningful when the
    bundle drive is a different device from the writable home, which it is on
    the VCS (bundle on the USB drive, home on eMMC); where the two share a
    device the folder check still protects the bundle itself."""
    if is_under_bundle(path):
        return True
    bdev = _bundle_device()
    home = os.path.realpath(STATE) if STATE else ""
    # Don't tag the writable home as the bundle drive even if they happen to
    # share a device; only the bundle folder is off-limits there.
    if home and (os.path.realpath(path) == home
                 or os.path.realpath(path).startswith(home + os.sep)):
        return False
    if bdev is not None and _device_of(path) == bdev:
        return True
    return False


def _can_write(path):
    """Whether an EXISTING directory is writable, without creating anything.
    Used when reporting drives and when weighing a candidate port, so we never
    leave a folder behind on someone's USB stick just by looking at it."""
    return os.path.isdir(path) and os.access(path, os.W_OK)


def _ensure_home_staging(path):
    """Create our own staging folder in the writable home and confirm we can
    write a file in it. Only ever called for the home staging path, never for
    external media."""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return False
    probe = os.path.join(path, ".port-write-test")
    try:
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _mount_lines():
    """Every mount visible to us, from /proc/mounts: (device, mountpoint)."""
    out = []
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    dev = parts[0]
                    mnt = parts[1].encode().decode("unicode_escape")
                    out.append((dev, mnt))
    except OSError:
        pass
    return out


def reachable_drives():
    """Report of what storage this sandbox can actually see. Each entry says
    whether it is the protected bundle drive and whether we could write to it.
    This is what the access check shows the user."""
    seen = []
    for dev, mnt in _mount_lines():
        # Skip the kernel/pseudo filesystems; they are not storage.
        if mnt.startswith(("/proc", "/sys", "/dev", "/run/udev")):
            continue
        if dev in ("proc", "sysfs", "tmpfs", "cgroup", "cgroup2", "devtmpfs",
                   "mqueue", "devpts", "overlay", "udev", "none", "securityfs",
                   "debugfs", "pstore", "efivarfs", "bpf", "hugetlbfs"):
            # tmpfs can be a real writable scratch area (/tmp), keep those two.
            if not (dev == "tmpfs" and mnt in ("/tmp", "/var/tmp")):
                continue
        on_bundle = is_on_bundle_drive(mnt)
        seen.append({
            "device": dev,
            "mount": mnt,
            "bundle_drive": on_bundle,
            "writable": _can_write(mnt) if not on_bundle else False,
        })
    return seen


def candidate_ports():
    """The places an update could arrive, best first. The first that is
    reachable, writable and NOT on the bundle drive becomes the open port.

    The USB-stick paths are listed first on purpose: if a host-side mount
    helper is ever added (it would need the console's own OS, outside the
    sandbox), its drop-in folder would appear here and be chosen automatically.
    Inside the plain sandbox those paths are simply not reachable, and the
    writable home staging folder is used instead."""
    cands = []
    # 1. A USB stick's KodiUpdate folder, if a host helper ever mounts one in.
    for dev, mnt in _mount_lines():
        if mnt.startswith("/media") or mnt.startswith("/run/media"):
            cands.append(os.path.join(mnt, "KodiUpdate"))
    # 2. A KodiUpdate folder beside the bundle drive root (read-only on the
    #    VCS; listed so the port is used read-only if that is all there is).
    if BUNDLE:
        cands.append(os.path.realpath(os.path.join(BUNDLE, "..", "..", "KodiUpdate")))
    # 3. The always-reachable writable staging folder in the home. This is the
    #    fallback the sandbox always has: drop packages here to update.
    if STATE:
        cands.append(os.path.join(STATE, "update-port", "incoming"))
    return cands


def choose_port():
    """Pick the next open port: the first reachable candidate we may use.

    Returns (path, writable, reason). A read-only bundle-drive candidate is
    reported but never returned as writable; a candidate that resolves onto the
    bundle drive for writing is refused outright (the bundle-USB safety rule).
    External media is never created or probed into: a USB KodiUpdate folder is
    only used if it already exists and is writable."""
    home_staging = os.path.join(STATE, "update-port", "incoming") if STATE else ""
    for path in candidate_ports():
        # Refuse to ever treat the bundle drive as a writable port; if it is
        # the only thing carrying updates, use it read-only.
        if is_on_bundle_drive(path):
            if os.path.isdir(path):
                return path, False, "bundle drive (read-only, protected)"
            continue
        if path == home_staging:
            # Our own folder in the writable home: create it and use it.
            if _ensure_home_staging(path):
                return path, True, "writable update port (home staging)"
        elif _can_write(path):
            # An existing, writable USB drop folder (needs a host-side mount to
            # be reachable from the sandbox); never created by us.
            return path, True, "writable update port (USB)"
    return "", False, "no writable port reachable"


def open_port():
    """Open the port for this Kodi session and write its heartbeat. Called by
    the service on start and once a minute after. Safe to call repeatedly."""
    if not PORT_DIR:
        return "", False
    os.makedirs(PORT_DIR, exist_ok=True)
    path, writable, reason = choose_port()
    info = {
        "pid": os.getpid(),
        "heartbeat": time.time(),
        "port": path,
        "writable": writable,
        "reason": reason,
    }
    tmp = OPEN_MARKER + ".new"
    with open(tmp, "w") as f:
        json.dump(info, f)
    os.replace(tmp, OPEN_MARKER)
    with open(ACTIVE_FILE, "w") as f:
        f.write(path)
    return path, writable


def close_port():
    """Close the port when Kodi exits, so no update is ever read while Kodi is
    not running."""
    for p in (OPEN_MARKER, ACTIVE_FILE):
        try:
            os.remove(p)
        except OSError:
            pass


def port_status():
    """What the rest of Kodi sees. is_open is True only while the heartbeat is
    fresh, i.e. only while Kodi is actually running."""
    if not os.path.isfile(OPEN_MARKER):
        return {"is_open": False, "port": "", "writable": False,
                "reason": "closed (Kodi not holding the port)"}
    try:
        with open(OPEN_MARKER, encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        return {"is_open": False, "port": "", "writable": False,
                "reason": "closed (unreadable marker)"}
    fresh = (time.time() - info.get("heartbeat", 0)) <= HEARTBEAT_STALE_S
    info["is_open"] = fresh
    if not fresh:
        info["reason"] = "stale (left by a previous session)"
    return info
