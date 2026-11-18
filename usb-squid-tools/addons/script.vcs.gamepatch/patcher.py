# Game Updater: find, verify and apply game patches that arrive on the open
# USB update port.
#
# A patch only ever applies to the writable Kodi home (add-ons, userdata, a
# patched-games overlay). It is NEVER written to the read-only bundle or the
# VCS Bundle drive - every target path is checked and refused if it lands
# there. A patch is accepted only when its manifest names this exact bundle
# (StoreID) and a bundle Version at or below the one installed, and only when
# every file's SHA-256 matches. Verification is done in full before anything is
# written, so a patch applies completely or not at all.
#
# Package shape - a folder or a .tar named "<something>.kodipatch", holding:
#   patch.json          the manifest (below)
#   files/<path>...      the files the patch adds or replaces
#
# patch.json:
#   {
#     "id": "ngp-boxart-2026-11",            unique; recorded so it applies once
#     "name": "Neo Geo Pocket box art fix",  shown to the user
#     "target": {"storeid": "UJZi5fBzNn0MEFWQ", "min_version": 11},
#     "base": "home" | "addons" | "games",   which writable root the paths are under
#     "files": [
#       {"path": "addons/game.libretro.beetle-ngp/.../x.so",
#        "action": "replace", "sha256": "<new file>",
#        "expect_sha256": "<the file being replaced, optional>"},
#       {"path": "Foo.ngp", "action": "add", "sha256": "<new file>"}
#     ]
#   }
import hashlib
import json
import os
import shutil
import tarfile
import time

import xbmcvfs

# Writable roots a patch may target, resolved to the Kodi home. "games" is a
# writable overlay for updated or added ROMs (the shipped ROMs live on the
# read-only bundle and cannot be changed in place).
HOME = xbmcvfs.translatePath("special://home/")


def _base_root(base):
    if base == "home":
        return HOME
    if base == "addons":
        return os.path.join(HOME, "addons")
    if base == "games":
        return os.path.join(HOME, "patched-games")
    raise PatchError("manifest base must be home, addons or games (got %r)" % base)


class PatchError(Exception):
    pass


def _check_rel(rel):
    """A manifest file path must be relative and contain no '..' or drive/root,
    so it can never read from or write to anywhere but under its base. Checked
    before rel is used to read a payload or build a target."""
    if (not rel or rel.startswith(("/", "\\")) or ":" in rel
            or ".." in rel.replace("\\", "/").split("/")):
        raise PatchError("file path escapes its base: %s" % rel)
    return rel


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def bundle_info():
    """StoreID and Version from the bundle's own bundle.ini."""
    bundle = os.environ.get("KODIVCS_BUNDLE", "")
    storeid, version = "", 0
    ini = os.path.join(bundle, "bundle.ini")
    try:
        with open(ini, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("StoreID="):
                    storeid = line.split("=", 1)[1].strip()
                elif line.startswith("Version="):
                    try:
                        version = int(line.split("=", 1)[1].strip())
                    except ValueError:
                        pass
    except OSError:
        pass
    return storeid, version


# ---- reading a package ------------------------------------------------------

class Package:
    """A patch package, either a directory or a .tar. Gives the manifest and
    the bytes of each payload file, without unpacking anything to disk."""

    def __init__(self, path):
        self.path = path
        self.is_tar = os.path.isfile(path)
        self._tar = None
        if self.is_tar:
            try:
                self._tar = tarfile.open(path, "r:*")
            except (tarfile.TarError, OSError) as e:
                raise PatchError("cannot open package: %s" % e)

    def close(self):
        if self._tar:
            self._tar.close()

    def _read(self, rel):
        if self.is_tar:
            member = self._member(rel)
            if member is None:
                return None
            f = self._tar.extractfile(member)
            return f.read() if f else None
        full = os.path.join(self.path, rel)
        if not os.path.isfile(full):
            return None
        with open(full, "rb") as f:
            return f.read()

    def _member(self, rel):
        # Match a member regardless of a leading "./" the archiver may add.
        for name in (rel, "./" + rel):
            try:
                return self._tar.getmember(name)
            except KeyError:
                continue
        return None

    def manifest(self):
        raw = self._read("patch.json")
        if raw is None:
            raise PatchError("package has no patch.json")
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise PatchError("patch.json is not valid JSON: %s" % e)

    def payload(self, rel):
        data = self._read("files/" + rel)
        if data is None:
            raise PatchError("package is missing files/%s" % rel)
        return data


def find_packages(port_path):
    """Patch packages sitting on the open port, newest first."""
    out = []
    if not port_path or not os.path.isdir(port_path):
        return out
    try:
        names = os.listdir(port_path)
    except OSError:
        return out
    for name in names:
        if not name.endswith(".kodipatch"):
            continue
        full = os.path.join(port_path, name)
        if os.path.isdir(full) or os.path.isfile(full):
            out.append(full)
    out.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return out


# ---- the applied log (so a patch applies once) ------------------------------

def _applied_log():
    state = os.environ.get("KODIVCS_STATE", "")
    return os.path.join(state, "update-port", "applied.json") if state else ""


def already_applied(patch_id):
    log = _applied_log()
    if not log or not os.path.isfile(log):
        return False
    try:
        with open(log, encoding="utf-8") as f:
            return patch_id in json.load(f)
    except (OSError, ValueError):
        return False


def _record_applied(patch_id, name):
    log = _applied_log()
    if not log:
        return
    os.makedirs(os.path.dirname(log), exist_ok=True)
    data = {}
    if os.path.isfile(log):
        try:
            with open(log, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
    data[patch_id] = {"name": name, "when": time.strftime("%Y-%m-%d %H:%M:%S")}
    tmp = log + ".new"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, log)


# ---- verifying and applying -------------------------------------------------

def _safe_target(root, rel):
    """Resolve root/rel and make sure it stays inside root and never lands on
    the bundle drive. Returns the absolute target path."""
    import port  # the USB Update Port's bundle-drive guard

    root = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root, rel))
    if target != root and not target.startswith(root + os.sep):
        raise PatchError("file path escapes its base: %s" % rel)
    if port.is_under_bundle(target):
        raise PatchError("refused: %s would write into the read-only bundle" % rel)
    return target


def verify(pkg, bundle_storeid, bundle_version):
    """Check the manifest and every file. Returns (manifest, plan) where plan
    is a list of (rel, target_abs, action, data). Raises PatchError on any
    problem - nothing is written here."""
    man = pkg.manifest()
    target = man.get("target", {})
    want_store = target.get("storeid", "")
    min_ver = int(target.get("min_version", 0) or 0)

    if want_store != bundle_storeid:
        raise PatchError("this patch is for StoreID %r, but this bundle is %r"
                         % (want_store, bundle_storeid))
    if bundle_version < min_ver:
        raise PatchError("this patch needs bundle Version %d or newer; this is %d"
                         % (min_ver, bundle_version))

    root = _base_root(man.get("base", ""))
    files = man.get("files", [])
    if not files:
        raise PatchError("patch lists no files")

    plan = []
    for entry in files:
        rel = entry.get("path", "")
        action = entry.get("action", "replace")
        want_sha = entry.get("sha256", "")
        if not rel or not want_sha:
            raise PatchError("a file entry is missing path or sha256")
        if action not in ("add", "replace"):
            raise PatchError("file %s: action must be add or replace" % rel)
        _check_rel(rel)

        data = pkg.payload(rel)
        got = sha256_bytes(data)
        if got != want_sha:
            raise PatchError("file %s: checksum mismatch (package is damaged "
                             "or tampered)" % rel)

        tgt = _safe_target(root, rel)
        if action == "replace":
            expect = entry.get("expect_sha256", "")
            if expect:
                if not os.path.isfile(tgt):
                    raise PatchError("file %s: expected an existing file to "
                                     "replace, none found" % rel)
                if sha256_file(tgt) != expect:
                    raise PatchError("file %s: the file here is not the one this "
                                     "patch expects to replace" % rel)
        plan.append((rel, tgt, action, data))
    return man, plan


def apply(man, plan):
    """Write a verified plan. Replaced files are backed up first so a bad patch
    can be undone by hand. Assumes verify() already passed."""
    patch_id = man.get("id") or man.get("name") or "patch"
    state = os.environ.get("KODIVCS_STATE", "")
    backup_dir = os.path.join(state, "update-port", "backups",
                              "%s-%s" % (patch_id, time.strftime("%Y%m%d%H%M%S")))
    changed = []
    for rel, tgt, action, data in plan:
        os.makedirs(os.path.dirname(tgt), exist_ok=True)
        if action == "replace" and os.path.isfile(tgt):
            bpath = os.path.join(backup_dir, rel)
            os.makedirs(os.path.dirname(bpath), exist_ok=True)
            shutil.copy2(tgt, bpath)
        tmp = tgt + ".patch-new"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, tgt)
        changed.append(rel)
    _record_applied(patch_id, man.get("name", patch_id))
    return changed, (backup_dir if os.path.isdir(backup_dir) else "")
