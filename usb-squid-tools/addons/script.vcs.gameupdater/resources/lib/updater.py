# VCS Game Updater core logic (no Kodi imports, so it can be tested on a PC).
#
# Flow: GitHub link typed by the dev/user -> resolve to a bundle zip -> download
# -> read the zip's bundle.ini -> its StoreID is the security key: it must be
# in the registry AND match a game installed on this console -> the console's
# own installer (system-bridge-daemon, bundles/install) swaps the old game for
# the new build, into the same identifier and storage slot.

import configparser
import io
import json
import os
import re
import socket
import ssl
import urllib.parse
import urllib.request
import zipfile

MAX_BUNDLE = 5 * 1024 ** 3          # VCS bundle size limit (5 GiB)
BUNDLE_EXT = (".zip", ".bundle")
GITHUB_HOSTS = {
    "github.com", "www.github.com", "api.github.com", "codeload.github.com",
    "raw.githubusercontent.com", "objects.githubusercontent.com",
    "github-releases.githubusercontent.com", "release-assets.githubusercontent.com",
}
UA = "SQUID-VCS-Game-Updater/1.0"


class UpdateError(Exception):
    """A failure with a message meant for the person holding the controller."""


# ---------------------------------------------------------------- registry

def load_registry(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["games"]


# ---------------------------------------------------------------- network

def _ssl_context():
    try:
        import certifi  # script.module.certifi in SQUID
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _check_host(url):
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or (u.hostname or "").lower() not in GITHUB_HOSTS:
        raise UpdateError("Only https GitHub links are accepted:\n%s" % url)


class _GitHubOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_ssl_context()), _GitHubOnlyRedirect())


def _get_json(url):
    _check_host(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/vnd.github+json"})
    try:
        with _opener().open(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("GitHub says this link was not found (404).\n"
                              "Check the link, and that the repo is public.")
        if e.code == 403:
            raise UpdateError("GitHub refused the request (403). This is usually "
                              "GitHub's hourly limit - try again later.")
        raise UpdateError("GitHub error %s for %s" % (e.code, url))
    except OSError as e:
        raise UpdateError("Could not reach GitHub: %s" % e)


def _assets_from_release(rel):
    out = []
    for a in rel.get("assets", []):
        if a.get("name", "").lower().endswith(BUNDLE_EXT):
            out.append({"name": a["name"], "url": a["browser_download_url"],
                        "size": a.get("size", 0), "release": rel.get("tag_name", "")})
    return out


def resolve_link(link):
    """Turn whatever GitHub link was typed into a list of candidate bundle files.

    Accepted:
      github.com/OWNER/REPO                       -> newest release's .zip/.bundle
      github.com/OWNER/REPO/releases/tag/TAG      -> that release
      github.com/OWNER/REPO/releases/download/... -> that file
      github.com/OWNER/REPO/blob|raw/REF/PATH     -> that file
      raw.githubusercontent.com/...               -> that file
    """
    link = link.strip()
    if not link:
        raise UpdateError("No link was entered.")
    if "://" not in link:
        link = "https://" + link
    _check_host(link)
    u = urllib.parse.urlparse(link)
    host = u.hostname.lower()
    parts = [p for p in u.path.split("/") if p]

    if host == "raw.githubusercontent.com" or host.endswith("githubusercontent.com"):
        return [{"name": urllib.parse.unquote(parts[-1]), "url": link, "size": 0, "release": ""}]
    if len(parts) < 2:
        raise UpdateError("That isn't a GitHub repository link.\n"
                          "Example: github.com/YourName/YourGame")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    rest = parts[2:]
    api = "https://api.github.com/repos/%s/%s" % (owner, repo)

    if rest[:2] == ["releases", "download"] and len(rest) >= 4:
        return [{"name": urllib.parse.unquote(rest[-1]), "url": link, "size": 0, "release": rest[2]}]
    if rest and rest[0] in ("blob", "raw") and len(rest) >= 3:
        raw = "https://raw.githubusercontent.com/%s/%s/%s" % (owner, repo, "/".join(rest[1:]))
        return [{"name": urllib.parse.unquote(rest[-1]), "url": raw, "size": 0, "release": rest[1]}]
    if rest[:2] == ["releases", "tag"] and len(rest) >= 3:
        rel = _get_json(api + "/releases/tags/" + urllib.parse.quote("/".join(rest[2:])))
        found = _assets_from_release(rel)
        if not found:
            raise UpdateError("Release %s has no .zip or .bundle file attached." % rest[2])
        return found

    # Plain repo link: newest release first, then .zip/.bundle files in the repo root.
    try:
        found = _assets_from_release(_get_json(api + "/releases/latest"))
        if found:
            return found
    except UpdateError:
        pass
    files = _get_json(api + "/contents/")
    found = [{"name": f["name"], "url": f["download_url"], "size": f.get("size", 0), "release": ""}
             for f in files if isinstance(f, dict) and f.get("type") == "file"
             and f.get("name", "").lower().endswith(BUNDLE_EXT) and f.get("download_url")]
    if not found:
        raise UpdateError("No game build found in %s/%s.\nAttach the bundle .zip to a "
                          "GitHub Release (or put it in the repo)." % (owner, repo))
    return found


def download(url, dest, progress=None):
    """Download to dest (a temp name first). progress(done, total) -> False cancels."""
    _check_host(url)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with _opener().open(req, timeout=60) as r, open(tmp, "wb") as out:
            total = int(r.headers.get("Content-Length") or 0)
            if total > MAX_BUNDLE:
                raise UpdateError("The file is larger than the VCS 5 GB bundle limit.")
            done = 0
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if done > MAX_BUNDLE:
                    raise UpdateError("The file is larger than the VCS 5 GB bundle limit.")
                if progress and progress(done, total) is False:
                    raise UpdateError("Download cancelled.")
        if total and done != total:
            raise UpdateError("The download was cut short (%d of %d bytes)." % (done, total))
        os.replace(tmp, dest)
    except OSError as e:
        raise UpdateError("Download failed: %s" % e)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return dest


# ---------------------------------------------------------------- bundle check

def read_bundle(path):
    """Validate a VCS bundle zip and return its [Bundle] info."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise UpdateError("The downloaded file is not a valid bundle zip.")
    with z:
        names = z.namelist()
        if "bundle.ini" not in names:
            raise UpdateError("bundle.ini is missing from the top level of the zip.\n"
                              "Zip the game from inside its folder.")
        total = 0
        for zi in z.infolist():
            n = zi.filename
            if n.startswith("/") or "\\" in n or ".." in n.split("/"):
                raise UpdateError("The zip contains an unsafe path: %s" % n)
            total += zi.file_size
        if total > MAX_BUNDLE:
            raise UpdateError("The game is larger than the VCS 5 GB bundle limit.")
        try:
            bad = z.testzip()
        except Exception:
            bad = "unreadable data"
        if bad:
            raise UpdateError("The zip is damaged (bad file: %s). Download it again." % bad)
        text = z.read("bundle.ini").decode("utf-8-sig", errors="replace")
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    try:
        cp.read_file(io.StringIO(text))
        b = dict(cp["Bundle"])
    except (configparser.Error, KeyError):
        raise UpdateError("bundle.ini has no [Bundle] section.")
    b = {k.strip(): v.strip() for k, v in b.items()}
    if b.get("HomebrewID"):
        raise UpdateError("This is a Homebrew bundle (HomebrewID). Only store games "
                          "with a StoreID can be updated.")
    if not b.get("StoreID"):
        raise UpdateError("bundle.ini has no StoreID, so the update can't be matched to a game.")
    for k in ("Name", "Exec", "Type"):
        if not b.get(k):
            raise UpdateError("bundle.ini is missing %s." % k)
    exe = b["Exec"].split()[0]
    if b["Type"] != "LauncherOnly" and not b.get("Launcher") and exe not in names:
        raise UpdateError("bundle.ini Exec=%s, but that file is not in the zip." % exe)
    return b


def next_version(installed_version):
    """Installed Version + 1 (the updater's mark that the game was updated)."""
    try:
        return str(int(str(installed_version).strip()) + 1)
    except (TypeError, ValueError):
        raise UpdateError("The installed game's Version (%r) is not a number, so it "
                          "can't be raised by 1." % installed_version)


def set_version(path, version):
    """Rewrite bundle.ini inside the zip with Version=<version>, without repacking
    the (possibly multi-GB) zip: the old bundle.ini entry is renamed to
    bundle.old in place (same length, so offsets and CRCs stay valid) and a new
    bundle.ini is appended."""
    with zipfile.ZipFile(path) as z:
        old = z.getinfo("bundle.ini")
        text = z.read(old).decode("utf-8-sig", errors="replace")
    lines, done = [], False
    for line in text.splitlines():
        if re.match(r"\s*Version\s*=", line):
            if not done:
                lines.append("Version=%s" % version)
                done = True
            continue
        lines.append(line)
    if not done:
        out, inserted = [], False
        for line in lines:
            out.append(line)
            if not inserted and line.strip().lower() == "[bundle]":
                out.append("Version=%s" % version)
                inserted = True
        lines = out
    new_ini = ("\n".join(lines) + "\n").encode("utf-8")

    with open(path, "r+b") as f:
        data_len = os.path.getsize(path)
        # Local header: name follows the 30-byte fixed header.
        f.seek(old.header_offset)
        hdr = f.read(30)
        if hdr[:4] != b"PK\x03\x04":
            raise UpdateError("Unexpected zip layout; can't update bundle.ini.")
        f.seek(old.header_offset + 30)
        if f.read(10) != b"bundle.ini":
            raise UpdateError("Unexpected zip layout; can't update bundle.ini.")
        f.seek(old.header_offset + 30)
        f.write(b"bundle.old")
        # Central directory: search the tail of the file for bundle.ini's record.
        tail = min(data_len, 64 * 1024 * 1024)
        f.seek(data_len - tail)
        blob = f.read(tail)
        pos = 0
        hit = None
        while True:
            pos = blob.find(b"PK\x01\x02", pos)
            if pos < 0:
                break
            nlen = int.from_bytes(blob[pos + 28:pos + 30], "little")
            off = int.from_bytes(blob[pos + 42:pos + 46], "little")
            name = blob[pos + 46:pos + 46 + nlen]
            if name == b"bundle.ini" and (off == old.header_offset or off == 0xFFFFFFFF):
                hit = pos
                break
            pos += 4
        if hit is None:
            raise UpdateError("Unexpected zip layout; can't update bundle.ini.")
        f.seek(data_len - tail + hit + 46)
        f.write(b"bundle.old")
    with zipfile.ZipFile(path, "a", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("bundle.ini", new_ini)
    return new_ini.decode("utf-8")


# ---------------------------------------------------------------- console installer

def installer_socket():
    cands = []
    if os.environ.get("XDG_RUNTIME_DIR"):
        cands.append(os.path.join(os.environ["XDG_RUNTIME_DIR"], "system-bridge-daemon"))
    cands.append("/run/user/%d/system-bridge-daemon" % os.getuid())
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def rpc(sock_path, method, params=None, timeout=None):
    """JSON-RPC 2.0 with Content-Length framing (what sbd-cli speaks)."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(sock_path)
        s.sendall(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        buf = b""
        need = None
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            if need is None and b"\r\n\r\n" in buf:
                head, _, _ = buf.partition(b"\r\n\r\n")
                m = re.search(rb"Content-Length:\s*(\d+)", head, re.I)
                if m:
                    need = len(head) + 4 + int(m.group(1))
            if need is not None and len(buf) >= need:
                break
    except OSError as e:
        raise UpdateError("Could not talk to the console installer: %s" % e)
    finally:
        s.close()
    _, _, payload = buf.partition(b"\r\n\r\n")
    try:
        resp = json.loads(payload.decode("utf-8"))
    except ValueError:
        raise UpdateError("The console installer gave no usable answer.")
    if resp.get("error"):
        raise UpdateError("The console installer refused: %s" %
                          resp["error"].get("message", resp["error"]))
    return resp.get("result")


def find_installed(sock_path, store_id):
    for b in rpc(sock_path, "bundles/list", None, timeout=30) or []:
        if b.get("store-id") == store_id:
            return b
    return None


def install(sock_path, bundle_path, installed):
    """Swap the installed game for the new zip (same identifier + slot)."""
    return rpc(sock_path, "bundles/install", {
        "path": os.path.realpath(bundle_path),
        "identifier": installed["identifier"],
        "slot": installed.get("slot") or "internal",
    }, timeout=None)
