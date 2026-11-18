#!/usr/bin/env python3
# Build a .kodipatch package the Game Updater (script.vcs.gamepatch) can apply.
#
# You give it a base (home | addons | games), this bundle's StoreID, the
# minimum bundle Version the patch needs, and one or more files to add or
# replace. It copies the files into the package, computes every SHA-256, and
# writes patch.json. The result is a folder; pass --tar to also make the
# single-file .kodipatch (a tar) that is easier to copy onto a stick.
#
# Example - replace a core and add a new ROM to the writable games overlay:
#   python3 make-patch.py out/ngp-fix.kodipatch \
#       --id ngp-fix-2026-11 --name "Neo Geo Pocket fix" \
#       --storeid UJZi5fBzNn0MEFWQ --min-version 11 \
#       --base addons \
#       --replace game.libretro.beetle-ngp/.../core.so  path/on/disk/core.so \
#       --add     game.libretro.beetle-ngp/readme.txt    path/on/disk/readme.txt
#
# A "replace" also records the SHA-256 of the file currently on the system when
# you pass --expect-from <the current file>, so the Updater refuses to apply if
# what is there is not what you built the patch against.
import argparse
import hashlib
import json
import os
import shutil
import tarfile


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", help="output package path, ending in .kodipatch")
    ap.add_argument("--id", required=True, help="unique patch id (applied once)")
    ap.add_argument("--name", required=True, help="shown to the user")
    ap.add_argument("--storeid", required=True, help="target bundle StoreID")
    ap.add_argument("--min-version", type=int, required=True)
    ap.add_argument("--base", required=True, choices=["home", "addons", "games"])
    ap.add_argument("--add", nargs=2, action="append", default=[],
                    metavar=("DEST", "SRC"), help="add a new file at DEST (under base)")
    ap.add_argument("--replace", nargs=2, action="append", default=[],
                    metavar=("DEST", "SRC"), help="replace the file at DEST (under base)")
    ap.add_argument("--expect-from", nargs=2, action="append", default=[],
                    metavar=("DEST", "CURRENT"),
                    help="record the sha256 of CURRENT as the file DEST must match")
    ap.add_argument("--tar", action="store_true", help="also write a single-file tar")
    args = ap.parse_args()

    expect = {dest: sha256(cur) for dest, cur in args.expect_from}

    out = args.out
    if os.path.exists(out):
        shutil.rmtree(out) if os.path.isdir(out) else os.remove(out)
    files_root = os.path.join(out, "files")

    entries = []
    for action, pairs in (("add", args.add), ("replace", args.replace)):
        for dest, src in pairs:
            dest = dest.lstrip("/")
            payload = os.path.join(files_root, dest)
            os.makedirs(os.path.dirname(payload), exist_ok=True)
            shutil.copy2(src, payload)
            entry = {"path": dest, "action": action, "sha256": sha256(src)}
            if action == "replace" and dest in expect:
                entry["expect_sha256"] = expect[dest]
            entries.append(entry)

    if not entries:
        ap.error("nothing to do: pass at least one --add or --replace")

    manifest = {
        "id": args.id,
        "name": args.name,
        "target": {"storeid": args.storeid, "min_version": args.min_version},
        "base": args.base,
        "files": entries,
    }
    with open(os.path.join(out, "patch.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print("built %s (%d file(s))" % (out, len(entries)))
    if args.tar:
        tar_path = out if out.endswith(".kodipatch") else out + ".kodipatch"
        tar_path = tar_path + ".tar" if os.path.isdir(out) and tar_path == out else tar_path
        # Write the tar next to the folder with a .tar suffix so both survive.
        tarred = out.rstrip("/") + ".tar"
        with tarfile.open(tarred, "w") as tf:
            tf.add(os.path.join(out, "patch.json"), arcname="patch.json")
            tf.add(files_root, arcname="files")
        print("also wrote %s (rename to <name>.kodipatch to drop on a stick)" % tarred)


if __name__ == "__main__":
    main()
