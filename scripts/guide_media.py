#!/usr/bin/env python3
"""Publish the assembly guide's photos, videos, 3D models and PDFs, and check what is published.

    python3 scripts/guide_media.py

The media lives in a public bucket, not in git. Each file is stored under its
guide path with a fingerprint of its contents (the start of their SHA-256)
added, such as ``guide/clips/p35-329-review-1a2b3c4d5e6f7a8b.mp4``, so a changed
file gets a new name and nothing stored is ever overwritten. The catalog, kept
in git, maps each path the guide uses (such as ``clips/p35-329-review.mp4``) to
that stored name.

Every run first checks, with no login, that no guide media is committed and
that every catalog entry is stored. Run without a terminal, as in CI, it stops
there. In a terminal it then asks for the media folder, shows what is new, and
asks before uploading anything. Uploading needs the gcloud CLI, signed in with
upload rights on the bucket, or Google Cloud Shell.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.error
from urllib.parse import quote
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MEDIA_DIR = ROOT / "frontend" / "public" / "assembly"
CATALOG = ROOT / "frontend" / "src" / "components" / "assembly" / "storedMedia.json"
BUCKET = "orca-public-a5h6t"
PREFIX = "guide/"
FINGERPRINT_LENGTH = 16

# A new type also needs a line in .gitignore and in pyproject.toml's wheel artifacts.
CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".png": "image/png",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".glb": "model/gltf-binary",
    ".stl": "model/stl",
    ".pdf": "application/pdf",
}
# Stored gzip-compressed: 3D models shrink to about 40 %, while photos and videos are already compressed.
GZIP_SUFFIXES = {".glb", ".stl"}
# A stored name never changes its contents, so browsers may keep a file for a year without asking again.
CACHE_CONTROL = "public, max-age=31536000, immutable"
# Not published: the guide shows the hand through the console's own model in orca_ui/models/hand_v2.
UNPUBLISHED_DIRS = {"movement"}
# Folders whose media must stay out of git; the bucket holds it instead.
GUIDE_MEDIA_DIRS = ("frontend/public/assembly", "orca_ui/webui/assembly", "orca_ui/models/assembly")
ARCHIVE_SUFFIXES = {".zip"}
LISTED = 10


def public_url(bucket: str, object_name: str) -> str:
    return f"https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{quote(object_name, safe='')}?alt=media"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe(path: Path, relative: str) -> dict:
    """The catalog entry for one media file: its stored name, the guide path plus a fingerprint, and its size."""
    suffix = path.suffix.lower()
    fingerprint = sha256_of(path)[:FINGERPRINT_LENGTH]
    stem = relative[: -len(path.suffix)]
    entry = {"object": f"{PREFIX}{stem}-{fingerprint}{suffix}", "size": path.stat().st_size}
    if suffix in GZIP_SUFFIXES:
        entry["encoding"] = "gzip"
    return entry


def scan(media_dir: Path) -> dict[str, dict]:
    """Every media file under ``media_dir``, keyed by its path relative to it."""
    found = {}
    for path in sorted(media_dir.rglob("*")):
        relative = path.relative_to(media_dir)
        if (path.is_file() and path.suffix.lower() in CONTENT_TYPES and not path.name.startswith(".")
                and relative.parts[0] not in UNPUBLISHED_DIRS):
            found[relative.as_posix()] = describe(path, relative.as_posix())
    return found


def load_catalog() -> dict:
    if CATALOG.is_file():
        return json.loads(CATALOG.read_text())
    return {"bucket": BUCKET, "files": {}}


def save_catalog(catalog: dict) -> None:
    catalog["files"] = dict(sorted(catalog["files"].items()))
    CATALOG.write_text(json.dumps(catalog, indent=1) + "\n")


def head(url: str) -> tuple[int, dict]:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as error:
        return error.code, {}


def stored_problem(bucket: str, entry: dict) -> str | None:
    """Why the bucket's copy of ``entry`` is missing or wrong, or None when it matches."""
    status, headers = head(public_url(bucket, entry["object"]))
    if status != 200:
        return "not stored" if status == 404 else f"HTTP {status}"
    encoding = entry.get("encoding", "identity")
    if headers.get("x-goog-stored-content-encoding", "identity") != encoding:
        return f"stored as {headers.get('x-goog-stored-content-encoding')}, expected {encoding}"
    if encoding == "identity" and headers.get("x-goog-stored-content-length") != str(entry["size"]):
        return f"size {headers.get('x-goog-stored-content-length')}, expected {entry['size']}"
    if "immutable" not in headers.get("cache-control", ""):
        return "missing the long cache setting"
    return None


def problems_in_bucket(bucket: str, entries: dict[str, dict]) -> dict[str, str]:
    by_object = {entry["object"]: entry for entry in entries.values()}
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = pool.map(lambda entry: (entry["object"], stored_problem(bucket, entry)), by_object.values())
    return {name: problem for name, problem in results if problem}


def media_tracked_in_git() -> list[str]:
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--", *GUIDE_MEDIA_DIRS],
                            capture_output=True, text=True, check=True).stdout.splitlines()
    blocked = set(CONTENT_TYPES) | ARCHIVE_SUFFIXES
    return [path for path in listed if Path(path).suffix.lower() in blocked]


def print_some(lines: list[str]) -> None:
    for line in lines[:LISTED]:
        print(f"    {line}")
    if len(lines) > LISTED:
        print(f"    ... and {len(lines) - LISTED:,} more")


def report_bucket_problems(catalog: dict, problems: dict[str, str]) -> None:
    lines = []
    for name, problem in sorted(problems.items()):
        paths = sorted(p for p, e in catalog["files"].items() if e["object"] == name)
        lines.append(f"{', '.join(paths)}: {problem}")
    print_some(lines)


def count(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n:,} {singular if n == 1 else plural or singular + 's'}"


def megabytes(entries: dict[str, dict]) -> float:
    return sum(entry["size"] for entry in entries.values()) / 1e6


def ask(question: str) -> str:
    try:
        return input(question).strip()
    except EOFError:
        return ""


def heading(text: str) -> None:
    print(f"\n== {text}")


def stage(source: Path, entry: dict, folder: Path) -> Path:
    """A copy at the path it will be stored under, gzip-compressed when the entry says so."""
    staged = folder / entry["object"].removeprefix(PREFIX)
    staged.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as raw, staged.open("wb") as out:
        if entry.get("encoding") == "gzip":
            with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0, compresslevel=9) as packed:
                shutil.copyfileobj(raw, packed)
        else:
            shutil.copyfileobj(raw, out)
    return staged


def signed_in_account() -> str | None:
    listed = subprocess.run(["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
                            capture_output=True, text=True)
    return listed.stdout.strip() or None


def upload(bucket: str, media_dir: Path, new: dict[str, dict]) -> None:
    """Add the new objects with gcloud, keeping their folders.

    Each file type is staged in its own tree, laid out as it will be stored, and
    synced onto the bucket: rsync maps the tree onto the prefix exactly, never
    deletes, and --no-clobber skips any name already stored, so nothing is replaced.
    """
    groups: dict[tuple[str, str], Path] = {}
    with tempfile.TemporaryDirectory() as work:
        print("  Preparing the files (3D models are compressed first)...")
        for path, entry in new.items():
            key = (Path(path).suffix.lower(), entry.get("encoding", "identity"))
            stage(media_dir / path, entry, groups.setdefault(key, Path(work) / str(len(groups))))
        for (suffix, encoding), tree in sorted(groups.items()):
            command = ["gcloud", "storage", "rsync", "--recursive", "--no-clobber",
                       f"--content-type={CONTENT_TYPES[suffix]}"]
            if encoding == "gzip":
                command += ["--content-encoding=gzip", f"--cache-control={CACHE_CONTROL}, no-transform"]
            else:
                command += [f"--cache-control={CACHE_CONTROL}"]
            command += [str(tree), f"gs://{bucket}/{PREFIX.rstrip('/')}"]
            files = sum(1 for staged in tree.rglob("*") if staged.is_file())
            print(f"  Uploading {count(files, suffix + ' file')}; gcloud shows its own progress below.")
            subprocess.run(command, check=True)


def check(catalog: dict) -> tuple[list[str], dict[str, str]]:
    """Guide media committed to git, and catalog entries the bucket lacks or holds wrongly."""
    heading("Step 1: checking what is published (no login needed)")
    print("  Looking for guide media committed to git...")
    tracked = media_tracked_in_git()
    if tracked:
        print(f"  Problem: {count(len(tracked), 'guide media file')} committed to git. Media belongs in the")
        print("  bucket only. Take each out of git with `git rm --cached <file>` (your copy stays):")
        print_some(tracked)
    else:
        print("  OK: no guide media is in git.")
    stored_files = len({entry["object"] for entry in catalog["files"].values()})
    print(f"  Asking the bucket for the {count(stored_files, 'file')} the catalog lists (this can take half a minute)...")
    problems = problems_in_bucket(catalog.get("bucket", BUCKET), catalog["files"])
    if problems:
        print(f"  Missing from the bucket or stored wrongly: {count(len(problems), 'file')} the catalog lists.")
        report_bucket_problems(catalog, problems)
    else:
        print("  OK: every file the catalog lists is in the bucket.")
    return tracked, problems


def choose_folder() -> Path:
    print("  Which folder holds the media to publish? It must be laid out like")
    print(f"  {MEDIA_DIR.relative_to(ROOT)} (clips/, media/, parts/, ...).")
    print("  Press Enter to use that folder, or type another path.")
    while True:
        answer = ask("  Media folder: ")
        folder = Path(answer).expanduser().resolve() if answer else MEDIA_DIR
        if folder.is_dir():
            return folder
        print(f"  {folder} is not a folder. Try again, or press Ctrl+C to stop.")


def publish(catalog: dict) -> tuple[int, bool]:
    """Ask for the media folder, upload what the bucket lacks after a confirmation, then update the catalog.

    Returns the exit code and whether anything was uploaded.
    """
    bucket = catalog.get("bucket", BUCKET)
    heading("Step 2: choosing what to publish")
    media_dir = choose_folder()
    print("  Reading the media files and their fingerprints (about a minute for 1 GB)...")
    found = scan(media_dir)
    if not found:
        print(f"  No photos, videos, 3D models or PDFs in {media_dir}. Nothing to publish; nothing changed.")
        return 0, False
    print("  Asking the bucket which of them it already has...")
    changed = {path: entry for path, entry in found.items() if catalog["files"].get(path) != entry}
    missing = problems_in_bucket(bucket, found)
    to_upload = {path: entry for path, entry in found.items() if entry["object"] in missing}
    new_objects = {entry["object"]: entry for entry in to_upload.values()}
    print(f"  Found {count(len(found), 'media file')}: {count(len(new_objects), 'file')} to upload, "
          f"{count(len(changed), 'catalog entry', 'catalog entries')} new or changed.")
    if not changed and not to_upload:
        print("  Everything in this folder is already published. Nothing to do; nothing changed.")
        return 0, False
    if not to_upload:
        print("  These files are all in the bucket already, so only the catalog needs updating. No login needed.")
    else:
        heading("Step 3: uploading")
        print(f"  To upload ({megabytes(new_objects):,.1f} MB before compression):")
        print_some(sorted(to_upload))
        if shutil.which("gcloud") is None:
            print("\n  Uploading needs the Google Cloud CLI (gcloud), which isn't installed here.")
            print("  Either install it and sign in with `gcloud auth login`, or run this script in")
            print("  Google Cloud Shell, which is signed in already. Then run the script again.")
            print("  Nothing was uploaded, and the catalog is unchanged.")
            return 1, False
        account = signed_in_account()
        if account is None:
            print("\n  gcloud isn't signed in. Run `gcloud auth login`, then run this script again.")
            print("  Nothing was uploaded, and the catalog is unchanged.")
            return 1, False
        print(f"\n  Ready to upload {count(len(new_objects), 'file')} to gs://{bucket} as {account}.")
        print("  Anyone on the internet will be able to download these files. Uploads are only ever added:")
        print("  nothing in the bucket is replaced or deleted.")
        print("    y      upload, check that every file arrived, then update the catalog")
        print("    Enter  stop here; nothing is uploaded and the catalog stays as it is")
        reply = ask("  Upload? [y/N] ")
        if reply.lower() not in ("y", "yes"):
            print("  Stopped. Nothing was uploaded, and the catalog is unchanged.")
            return 0, False
        try:
            upload(bucket, media_dir, to_upload)
        except subprocess.CalledProcessError:
            print("\n  gcloud reported an error, shown above. A common cause is an account without upload")
            print("  rights on the bucket. The catalog is unchanged. Running the script again is safe:")
            print("  files that did arrive are skipped.")
            return 1, True
        print("  Checking that every uploaded file arrived intact...")
        still_wrong = problems_in_bucket(bucket, to_upload)
        if still_wrong:
            print(f"  {count(len(still_wrong), 'upload')} can't be confirmed, so the catalog is unchanged and the guide")
            print("  won't point at them. Running the script again is safe: confirmed files are skipped.")
            print_some([f"{name}: {problem}" for name, problem in sorted(still_wrong.items())])
            return 1, True
        print(f"  OK: {count(len(new_objects), 'file')} arrived intact.")
    if not changed:
        print("\n  Done. The catalog already lists these files, so there is nothing to commit.")
        return 0, bool(to_upload)
    catalog["files"].update(changed)
    save_catalog(catalog)
    relative = CATALOG.relative_to(ROOT)
    print("\n  Done. The catalog is updated. Next, commit it so the guide finds the files:")
    print(f"    git add {relative}")
    print("    git commit")
    return 0, bool(to_upload)


def main() -> int:
    if sys.argv[1:]:
        print(__doc__)
        return 0 if sys.argv[1] in ("-h", "--help") else 2
    try:
        return run()
    except KeyboardInterrupt:
        print("\nStopped. The catalog is unchanged; any file already uploaded is skipped next time.")
        return 1


def run() -> int:
    print("Assembly guide media: checks what is published, then lets you publish new or changed")
    print("photos, videos, 3D models and PDFs. Nothing is uploaded without your confirmation.")
    catalog = load_catalog()
    tracked, problems = check(catalog)
    if not sys.stdin.isatty():
        failed = bool(tracked or problems)
        print(f"\nNo terminal, so this run only checks. Result: {'problems found' if failed else 'all good'}.")
        return 1 if failed else 0
    if tracked:
        print("\nStopped: take the media out of git first, then run the script again.")
        return 1
    if problems:
        print("  These are uploaded in the next steps if the folder you choose contains them.")
    result, uploaded = publish(catalog)
    if problems and uploaded and result == 0:
        print("\n  Checking the files that were missing at the start...")
        remaining = problems_in_bucket(catalog.get("bucket", BUCKET), catalog["files"])
        if remaining:
            print(f"  Still not in the bucket: {count(len(remaining), 'file')} the catalog lists. The folder you chose doesn't")
            print("  contain their files. Run the script again with a folder that does:")
            report_bucket_problems(catalog, remaining)
            return 1
        print("  OK: every file the catalog lists is in the bucket now.")
    return result

if __name__ == "__main__":
    sys.exit(main())
